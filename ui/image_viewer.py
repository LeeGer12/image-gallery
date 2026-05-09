import logging
from pathlib import Path

from PySide6.QtCore import Qt
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


class ImageViewerDialog(QDialog):
    """全屏图片预览，支持左右翻页和另存为。"""

    def __init__(self, image_ids: list[int], current_index: int = 0, parent=None):
        super().__init__(parent)
        self._image_ids = image_ids
        self._current_index = current_index
        self._pixmap: QPixmap | None = None

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

        image_id = self._image_ids[self._current_index]
        db = SessionLocal()
        try:
            image = db.get(Image, image_id)
            if not image:
                self._image_label.setText("图片不存在")
                return

            # 尝试加载原图（限制大文件）
            pixmap = None
            src = Path(image.file_path)
            if not src.exists() and image.storage_path:
                src = Path(image.storage_path)
            if src.exists():
                if image.file_size and image.file_size < 100 * 1024 * 1024:
                    pixmap = QPixmap(str(src))

            # 回退到缩略图
            if (pixmap is None or pixmap.isNull()) and image.thumb_path:
                tp = Path(image.thumb_path)
                if tp.exists():
                    pixmap = QPixmap(image.thumb_path)

            if pixmap and not pixmap.isNull():
                self._pixmap = pixmap
                self._fit_image()
                self.setWindowTitle(f"图片查看 - {image.file_name}")
            else:
                self._image_label.setText("无法加载图片")
                self._pixmap = None
        finally:
            db.close()

        self._lbl_index.setText(
            f"{self._current_index + 1} / {len(self._image_ids)}"
        )

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
