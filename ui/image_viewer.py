import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.database import SessionLocal
from core.models import Image

logger = logging.getLogger(__name__)


class ImageLoadWorker(QObject):
    """后台加载图片原始字节数据，不在工作线程创建 QPixmap（Qt6 禁止）。"""

    finished = Signal(int, str, bytes)  # image_id, file_name, image_bytes
    error = Signal(str)

    def __init__(self, image_id: int):
        super().__init__()
        self._image_id = image_id
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return

        db = SessionLocal()
        try:
            image = db.get(Image, self._image_id)
            if not image or self._cancelled:
                return

            file_name = image.file_name
            src = Path(image.file_path)
            if not src.exists() and image.storage_path:
                src = Path(image.storage_path)

            image_bytes = b""
            if src.exists() and not self._cancelled:
                if image.file_size and image.file_size < 100 * 1024 * 1024:
                    image_bytes = src.read_bytes()
                else:
                    # 大文件只读取缩略图
                    if image.thumb_path:
                        tp = Path(image.thumb_path)
                        if tp.exists():
                            image_bytes = tp.read_bytes()
            elif image.thumb_path and not self._cancelled:
                # 原图不存在，回退到缩略图
                tp = Path(image.thumb_path)
                if tp.exists():
                    image_bytes = tp.read_bytes()

            if self._cancelled:
                return

            self.finished.emit(self._image_id, file_name, image_bytes)
        except Exception as e:
            logger.error("ImageLoadWorker error: %s", e)
            self.error.emit(str(e))
        finally:
            db.close()


class ImageViewerDialog(QDialog):
    """全屏图片预览，支持左右翻页和另存为。"""

    def __init__(self, image_ids: list[int], current_index: int = 0, parent=None):
        super().__init__(parent)
        self._image_ids = image_ids
        self._current_index = current_index
        self._pixmap: QPixmap | None = None
        self._thread: QThread | None = None
        self._worker: ImageLoadWorker | None = None
        self._loading = False

        self.setWindowTitle("图片查看")
        self.setMinimumSize(800, 600)
        self.setStyleSheet("background-color: #1e1e1e;")

        self._build_ui()
        self._load_current_image()
        self._update_nav_buttons()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 工具栏
        toolbar = QToolBar()
        toolbar.setStyleSheet(
            "QToolBar { background: #2d2d2d; border: none; padding: 4px; }"
            "QPushButton { color: white; background: #3d3d3d; border: 1px solid #555;"
            "  padding: 6px 16px; border-radius: 3px; }"
            "QPushButton:hover { background: #4d4d4d; }"
            "QPushButton:disabled { color: #666; background: #2d2d2d; }"
        )

        self._btn_prev = QPushButton("◀ 上一张")
        self._btn_prev.clicked.connect(self._show_prev)
        self._btn_prev.setShortcut(QKeySequence(Qt.Key.Key_Left))
        toolbar.addWidget(self._btn_prev)

        self._lbl_index = QLabel()
        self._lbl_index.setStyleSheet("color: #ccc; padding: 0 12px;")
        toolbar.addWidget(self._lbl_index)

        self._btn_next = QPushButton("下一张 ▶")
        self._btn_next.clicked.connect(self._show_next)
        self._btn_next.setShortcut(QKeySequence(Qt.Key.Key_Right))
        toolbar.addWidget(self._btn_next)

        toolbar.addSeparator()

        self._btn_save = QPushButton("另存为")
        self._btn_save.clicked.connect(self._save_as)
        toolbar.addWidget(self._btn_save)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self._btn_close = QPushButton("关闭")
        self._btn_close.clicked.connect(self.close)
        self._btn_close.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        toolbar.addWidget(self._btn_close)

        layout.addWidget(toolbar)

        # 图片显示区域
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background: #1e1e1e;")
        layout.addWidget(self._image_label, 1)

    def _load_current_image(self):
        if not self._image_ids:
            return

        # 取消之前的加载任务
        self._cancel_loading()

        image_id = self._image_ids[self._current_index]
        self._image_label.setText("加载中...")
        self._loading = True

        # 后台加载图片
        self._thread = QThread(self)
        self._worker = ImageLoadWorker(image_id)
        self._worker.moveToThread(self._thread)

        self._worker.finished.connect(self._on_image_loaded)
        self._worker.error.connect(self._on_image_error)
        self._thread.started.connect(self._worker.run)
        self._thread.start()

        self._lbl_index.setText(
            f"{self._current_index + 1} / {len(self._image_ids)}"
        )

    def _cancel_loading(self):
        """取消正在进行的加载任务"""
        if self._worker:
            self._worker.cancel()
            # 断开信号，防止旧 Worker 回调污染新 Worker
            try:
                self._worker.finished.disconnect()
                self._worker.error.disconnect()
            except RuntimeError:
                pass  # 信号已断开
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
            # 不调用 terminate()，避免未定义行为
        # 使用 deleteLater 清理，避免线程安全问题
        if self._worker:
            self._worker.deleteLater()
        if self._thread:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._loading = False

    def _on_image_loaded(self, image_id, file_name, image_bytes):
        """图片加载完成回调（主线程），在此创建 QPixmap"""
        # 检查是否是当前请求的图片（防止快速切换时旧回调覆盖新图片）
        if image_id != self._image_ids[self._current_index]:
            return

        self._loading = False
        pixmap = QPixmap()
        if image_bytes:
            pixmap.loadFromData(image_bytes)

        if not pixmap.isNull():
            self._pixmap = pixmap
            self._fit_image()
            self.setWindowTitle(f"图片查看 - {file_name}")
        else:
            self._image_label.setText("无法加载图片")
            self._pixmap = None

        self._cleanup_thread()

    def _on_image_error(self, msg):
        """图片加载错误回调"""
        logger.error("图片加载失败: %s", msg)
        self._image_label.setText(f"加载失败: {msg}")
        self._loading = False
        self._cleanup_thread()

    def _cleanup_thread(self):
        """清理线程资源"""
        if self._thread:
            self._thread.quit()
            self._thread.wait(1000)
        if self._worker:
            self._worker.deleteLater()
        if self._thread:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None

    def _fit_image(self):
        if self._pixmap is None or self._pixmap.isNull():
            return

        available = self._image_label.size()
        scaled = self._pixmap.scaled(
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_image()

    def _show_prev(self):
        if self._current_index > 0:
            self._current_index -= 1
            self._load_current_image()
            self._update_nav_buttons()

    def _show_next(self):
        if self._current_index < len(self._image_ids) - 1:
            self._current_index += 1
            self._load_current_image()
            self._update_nav_buttons()

    def _update_nav_buttons(self):
        self._btn_prev.setEnabled(self._current_index > 0)
        self._btn_next.setEnabled(self._current_index < len(self._image_ids) - 1)

    def _save_as(self):
        if not self._image_ids:
            return

        image_id = self._image_ids[self._current_index]
        db = SessionLocal()
        try:
            image = db.get(Image, image_id)
            if not image:
                return

            src = Path(image.file_path)
            if not src.exists() and image.storage_path:
                src = Path(image.storage_path)
            if not src.exists():
                self._image_label.setText("原文件不存在，无法另存为")
                return

            # 默认文件名，保留原后缀
            default_name = image.file_name
            save_path, _ = QFileDialog.getSaveFileName(
                self, "另存为", default_name,
                "图片文件 (*.jpg *.jpeg *.png *.webp *.bmp *.tiff);;所有文件 (*)"
            )
            if save_path:
                import shutil
                shutil.copy2(str(src), save_path)
                logger.info("另存为: %s -> %s", src, save_path)
        finally:
            db.close()

    def closeEvent(self, event):
        """关闭时清理线程资源"""
        self._cancel_loading()
        super().closeEvent(event)
