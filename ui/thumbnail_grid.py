import json
import logging
from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QDrag, QIcon, QPixmap
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from config import PAGE_SIZE, THUMB_SIZES
from core.database import SessionLocal
from core.models import Album, Image, album_image_table
from core.query_worker import abort_query, run_query
from core.thumbnailer import ThumbnailWorker
from ui.thread_utils import stop_thread
from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class DragListWidget(QListWidget):
    """支持拖拽的 QListWidget，拖拽时携带选中图片的 ID 列表。"""

    def __init__(self, parent_grid: "ThumbnailGrid"):
        super().__init__()
        self._parent_grid = parent_grid

    def startDrag(self, supportedActions):
        """重写 startDrag，将选中图片 ID 写入 MIME 数据"""
        selected_ids = self._parent_grid.get_selected_image_ids()
        if not selected_ids:
            return

        mime_data = QMimeData()
        mime_data.setData(
            "application/x-image-ids",
            json.dumps(selected_ids).encode("utf-8"),
        )

        # 使用第一个选中项的图标作为拖拽预览
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        current = self.currentItem()
        if current:
            drag.setPixmap(current.icon().pixmap(64, 64))

        drag.exec(Qt.DropAction.CopyAction)


class ThumbnailGrid(QWidget):
    """缩略图网格，使用 QListWidget IconMode 纯图片方格展示。"""

    image_selected = Signal(int)  # image_id
    image_double_clicked = Signal(int)  # image_id
    context_action = Signal(str, list)  # action_name, image_ids
    images_dragged = Signal(list)  # image_ids (拖拽开始)
    load_finished = Signal(int, str)  # count, filter_description
    selection_changed = Signal(int)  # selected_count

    def __init__(self, parent=None):
        super().__init__(parent)
        self._item_map: dict[int, QListWidgetItem] = {}
        self._thread: QThread | None = None
        self._worker: ThumbnailWorker | None = None
        self._filter_mode: str = "all"
        self._filter_value: object = None
        self._filter_style: str | None = None
        self._offset = 0
        self._current_size_key = "medium"
        self._filter_desc: str = ""
        self._loading = False
        self._no_more_data = False
        self._pending_query = (None, None)  # (worker, thread)

        # 缩略图懒加载防抖 timer
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(300)
        self._thumb_timer.timeout.connect(self._load_visible_thumbs)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.list_widget = DragListWidget(self)
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self._apply_thumb_size(self._current_size_key)
        self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list_widget.setMovement(QListWidget.Movement.Static)
        self.list_widget.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self.list_widget.setDragEnabled(True)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)

        # 滚动触发无限加载
        self.list_widget.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # 选中数量变化通知
        self.list_widget.itemSelectionChanged.connect(
            lambda: self.selection_changed.emit(len(self.list_widget.selectedItems()))
        )

        layout.addWidget(self.list_widget)

    def _apply_thumb_size(self, size_key: str):
        """应用缩略图尺寸"""
        size = THUMB_SIZES.get(size_key, 256)
        self.list_widget.setIconSize(QSize(size, size))
        self.list_widget.setGridSize(QSize(size + 4, size + 4))

    def _abort_pending_query(self):
        """中止待处理的查询"""
        worker, thread = self._pending_query
        abort_query(thread, worker)
        self._pending_query = (None, None)

    def _start_query(self, query_func, on_result):
        """启动新查询，自动中止旧查询"""
        self._abort_pending_query()
        worker, thread = run_query(self, query_func, on_result=on_result)
        self._pending_query = (worker, thread)

    def set_thumb_size(self, size_key: str):
        """切换缩略图尺寸并更新已有项"""
        self._current_size_key = size_key
        size = THUMB_SIZES.get(size_key, 256)
        self._apply_thumb_size(size_key)
        item_size = QSize(size + 4, size + 4)
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setSizeHint(item_size)

    def load_images(self, *, folder_id: int | None = None,
                    album_id: int | None = None,
                    project_type: str | None = None,
                    style_name: str | None = None,
                    imported_only: bool = False):
        """加载图片列表，支持多种过滤模式（异步）。"""
        self._stop_worker()
        self.list_widget.clear()
        self._item_map.clear()
        self._offset = 0
        self._filter_style = None
        self._loading = False
        self._no_more_data = False

        if album_id is not None:
            self._filter_mode = "album"
            self._filter_value = album_id
            self._filter_desc = f"相册"
        elif project_type and style_name:
            self._filter_mode = "full_classify"
            self._filter_value = project_type
            self._filter_style = style_name
            self._filter_desc = f"{project_type} / {style_name}"
        elif project_type:
            self._filter_mode = "project_type"
            self._filter_value = project_type
            self._filter_desc = project_type
        elif style_name:
            self._filter_mode = "style"
            self._filter_value = style_name
            self._filter_desc = style_name
        elif imported_only:
            self._filter_mode = "imported"
            self._filter_value = None
            self._filter_desc = "导入库"
        elif folder_id is not None:
            self._filter_mode = "folder"
            self._filter_value = folder_id
            self._filter_desc = f"文件夹"
        else:
            self._filter_mode = "all"
            self._filter_value = None
            self._filter_desc = "全部图片"

        self._start_query(self._query_page, on_result=self._on_page_loaded)

    def add_images_from_search(self, images: list):
        """用外部搜索结果填充网格"""
        self._stop_worker()
        self._abort_pending_query()
        self.list_widget.clear()
        self._item_map.clear()
        self._offset = 0
        self._loading = False
        self._no_more_data = True  # 搜索结果不支持无限滚动

        item_size = QSize(THUMB_SIZES[self._current_size_key] + 4,
                          THUMB_SIZES[self._current_size_key] + 4)
        need_thumbs = []
        for img in images:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, img.id)
            item.setToolTip(img.file_name)
            item.setSizeHint(item_size)

            thumb_path = img.thumb_path
            if thumb_path and Path(thumb_path).exists():
                pixmap = QPixmap(thumb_path)
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap))
            else:
                need_thumbs.append(img.id)

            self.list_widget.addItem(item)
            self._item_map[img.id] = item

        if need_thumbs:
            self._start_thumbnail_worker(need_thumbs)

        self.load_finished.emit(len(images), "搜索结果")

    def _build_filter_stmt(self, db: Session) -> select:
        """构建带过滤条件的查询（不含排序和分页）"""
        stmt = select(Image)

        if self._filter_mode == "folder":
            stmt = stmt.where(Image.folder_id == self._filter_value)
        elif self._filter_mode == "project_type":
            stmt = stmt.where(Image.project_type == self._filter_value)
        elif self._filter_mode == "full_classify":
            stmt = stmt.where(
                Image.project_type == self._filter_value,
                Image.style_name == self._filter_style,
            )
        elif self._filter_mode == "album":
            stmt = (
                stmt.join(album_image_table,
                          Image.id == album_image_table.c.image_id)
                .where(album_image_table.c.album_id == self._filter_value)
            )
        elif self._filter_mode == "style":
            stmt = stmt.where(Image.style_name == self._filter_value)
        elif self._filter_mode == "imported":
            stmt = stmt.where(Image.imported == True)

        return stmt

    def _query_page(self, db: Session) -> list:
        """查询一页图片数据（在后台线程执行）"""
        stmt = self._build_filter_stmt(db)
        if self._filter_mode == "album":
            stmt = stmt.order_by(album_image_table.c.sort_order)
        else:
            stmt = stmt.order_by(Image.id.desc())
        stmt = stmt.offset(self._offset).limit(PAGE_SIZE)
        results = db.execute(stmt).scalars().all()
        # 返回轻量数据：id, file_name, thumb_path
        return [(img.id, img.file_name, img.thumb_path) for img in results]

    def _on_page_loaded(self, results: list):
        """页面加载完成回调（主线程）"""
        self._loading = False

        if not results:
            self._no_more_data = True
            self.load_finished.emit(self.list_widget.count(), self._filter_desc)
            return

        item_size = QSize(THUMB_SIZES[self._current_size_key] + 4,
                          THUMB_SIZES[self._current_size_key] + 4)
        for img_id, file_name, thumb_path in results:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, img_id)
            item.setToolTip(file_name)
            item.setSizeHint(item_size)

            # 已有缩略图直接加载
            if thumb_path and Path(thumb_path).exists():
                pixmap = QPixmap(thumb_path)
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap))

            self.list_widget.addItem(item)
            self._item_map[img_id] = item

        self._offset += len(results)

        # 触发可见区域缩略图懒加载（防抖）
        self._thumb_timer.start()

        self.load_finished.emit(self.list_widget.count(), self._filter_desc)

    def _on_scroll(self, value: int):
        """滚动事件：接近底部时加载下一页"""
        bar = self.list_widget.verticalScrollBar()
        if bar.maximum() == 0:
            return
        # 接近底部时加载下一页（阈值：2 个视口高度）
        threshold = self.list_widget.viewport().height() * 2
        if value >= bar.maximum() - threshold and not self._loading and not self._no_more_data:
            self._loading = True
            self._start_query(self._query_page, on_result=self._on_page_loaded)

        # 滚动时触发缩略图懒加载（防抖）
        self._thumb_timer.start()

    def _load_visible_thumbs(self):
        """只对可见区域的 item 生成缩略图"""
        if self._worker and self._thread and self._thread.isRunning():
            return  # 已有缩略图任务在运行

        viewport = self.list_widget.viewport()
        visible_ids = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item:
                continue
            # 检查 item 是否在可见区域内
            item_rect = self.list_widget.visualItemRect(item)
            if item_rect.intersects(viewport.rect()):
                # 检查是否已有图标
                if item.icon().isNull():
                    img_id = item.data(Qt.ItemDataRole.UserRole)
                    if img_id is not None:
                        visible_ids.append(img_id)

        if visible_ids:
            self._start_thumbnail_worker(visible_ids)

    def _start_thumbnail_worker(self, image_ids: list[int]):
        self._stop_worker()

        self._thread = QThread()
        self._worker = ThumbnailWorker(image_ids, self._current_size_key)
        self._worker.moveToThread(self._thread)

        self._worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._worker.finished.connect(self._on_thumbnail_done)
        self._worker.error.connect(self._on_thumbnail_error)

        self._thread.started.connect(self._worker.run)
        self._thread.start()

    def _stop_worker(self):
        if self._worker:
            self._worker.cancel()
            # 断开信号，防止旧 Worker 的 finished/error 回调污染新 Worker
            try:
                self._worker.thumbnail_ready.disconnect(self._on_thumbnail_ready)
                self._worker.finished.disconnect(self._on_thumbnail_done)
                self._worker.error.disconnect(self._on_thumbnail_error)
            except RuntimeError:
                pass  # 信号已断开
        stop_thread(self._thread)
        self._thread = None
        self._worker = None

    def _on_thumbnail_ready(self, image_id: int, thumb_path: str):
        item = self._item_map.get(image_id)
        if item:
            pixmap = QPixmap(thumb_path)
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap))

    def _on_thumbnail_done(self):
        logger.debug("缩略图生成完成")
        self._cleanup_thread()

    def _on_thumbnail_error(self, msg: str):
        logger.error("缩略图错误: %s", msg)
        self._cleanup_thread()

    def _cleanup_thread(self):
        stop_thread(self._thread, timeout=1000)
        self._thread = None
        self._worker = None

    def _on_item_clicked(self, item: QListWidgetItem):
        image_id = item.data(Qt.ItemDataRole.UserRole)
        if image_id is not None:
            self.image_selected.emit(image_id)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        image_id = item.data(Qt.ItemDataRole.UserRole)
        if image_id is not None:
            self.image_double_clicked.emit(image_id)

    def get_all_image_ids(self) -> list[int]:
        """返回当前网格中所有图片 ID（按显示顺序）"""
        ids = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            img_id = item.data(Qt.ItemDataRole.UserRole)
            if img_id is not None:
                ids.append(img_id)
        return ids

    def add_image_item(self, img: Image):
        """手动添加一个图片项（用于搜索结果等外部加载）"""
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, img.id)
        item.setToolTip(img.file_name)
        size = THUMB_SIZES[self._current_size_key] + 4
        item.setSizeHint(QSize(size, size))

        thumb_path = img.thumb_path
        if thumb_path and Path(thumb_path).exists():
            pixmap = QPixmap(thumb_path)
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap))

        self.list_widget.addItem(item)
        self._item_map[img.id] = item

    def clear(self):
        """清空网格和内部状态"""
        self._stop_worker()
        self._abort_pending_query()
        self.list_widget.clear()
        self._item_map.clear()
        self._loading = False
        self._no_more_data = False

    def get_selected_image_id(self) -> int | None:
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def get_selected_image_ids(self) -> list[int]:
        """返回所有选中项的图片 ID"""
        ids = []
        for item in self.list_widget.selectedItems():
            img_id = item.data(Qt.ItemDataRole.UserRole)
            if img_id is not None:
                ids.append(img_id)
        return ids

    def _show_context_menu(self, pos):
        """右键菜单"""
        selected_ids = self.get_selected_image_ids()
        if not selected_ids:
            return

        menu = QMenu(self)

        db = SessionLocal()
        try:
            # 添加到相册子菜单
            album_menu = menu.addMenu("添加到相册")
            album_menu.addAction("新建相册...").setData("new_album")
            albums = db.execute(select(Album)).scalars().all()
            if albums:
                album_menu.addSeparator()
                for album in albums:
                    action = album_menu.addAction(album.name)
                    action.setData(f"add_to_album:{album.id}")
        finally:
            db.close()

        menu.addSeparator()
        menu.addAction("设置项目类型/风格...").setData("set_metadata")
        menu.addAction("导入到库...").setData("import")
        menu.addSeparator()
        menu.addAction("复制文件路径").setData("copy_path")
        menu.addAction("在资源管理器中打开").setData("open_in_explorer")
        menu.addSeparator()
        menu.addAction("删除记录").setData("delete_records")

        action = menu.exec(self.list_widget.mapToGlobal(pos))
        if action and action.data():
            self.context_action.emit(action.data(), selected_ids)

    def keyPressEvent(self, event):
        """键盘快捷键"""
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key.Key_A and modifiers == Qt.KeyboardModifier.ControlModifier:
            self.list_widget.selectAll()
        elif key == Qt.Key.Key_Escape:
            self.list_widget.clearSelection()
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            current = self.list_widget.currentItem()
            if current:
                img_id = current.data(Qt.ItemDataRole.UserRole)
                if img_id is not None:
                    self.image_double_clicked.emit(img_id)
        elif key == Qt.Key.Key_Delete:
            selected = self.get_selected_image_ids()
            if selected:
                self.context_action.emit("delete_records", selected)
        else:
            super().keyPressEvent(event)
