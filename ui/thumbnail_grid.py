import json
import logging
from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt, QThread, Signal
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
from core.thumbnailer import ThumbnailWorker
from ui.thread_utils import stop_thread
from sqlalchemy import select
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
    """缩略图网格，使用 QListWidget IconMode 展示图片。"""

    image_selected = Signal(int)  # image_id
    image_double_clicked = Signal(int)  # image_id
    context_action = Signal(str, list)  # action_name, image_ids
    images_dragged = Signal(list)  # image_ids (拖拽开始)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._item_map: dict[int, QListWidgetItem] = {}
        self._thread: QThread | None = None
        self._worker: ThumbnailWorker | None = None
        self._filter_mode: str = "all"
        self._filter_value: object = None
        self._offset = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.list_widget = DragListWidget(self)
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        thumb_size = THUMB_SIZES["medium"]
        self.list_widget.setIconSize(QSize(thumb_size, thumb_size))
        self.list_widget.setGridSize(QSize(thumb_size + 20, thumb_size + 40))
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

        layout.addWidget(self.list_widget)

    def load_images(self, db: Session, folder_id: int | None = None,
                    album_id: int | None = None,
                    project_type: str | None = None,
                    style_name: str | None = None,
                    imported_only: bool = False):
        """加载图片列表，支持多种过滤模式。"""
        self._stop_worker()
        self.list_widget.clear()
        self._item_map.clear()
        self._offset = 0

        self._filter_project_type = None
        self._filter_style = None

        if album_id is not None:
            self._filter_mode = "album"
            self._filter_value = album_id
        elif project_type and style_name:
            self._filter_mode = "full_classify"
            self._filter_value = project_type
            self._filter_style = style_name
        elif project_type:
            self._filter_mode = "project_type"
            self._filter_value = project_type
        elif style_name:
            self._filter_mode = "style"
            self._filter_value = style_name
        elif imported_only:
            self._filter_mode = "imported"
            self._filter_value = None
        elif folder_id is not None:
            self._filter_mode = "folder"
            self._filter_value = folder_id
        else:
            self._filter_mode = "all"
            self._filter_value = None

        self._load_page(db)

    def _load_page(self, db: Session):
        """加载一页图片"""
        stmt = select(Image)

        if self._filter_mode == "folder":
            stmt = stmt.where(Image.folder_id == self._filter_value)
        elif self._filter_mode == "project_type":
            stmt = stmt.where(
                Image.project_type == self._filter_value,
            )
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
                .order_by(album_image_table.c.sort_order)
            )
        elif self._filter_mode == "style":
            stmt = stmt.where(Image.style_name == self._filter_value)
        elif self._filter_mode == "imported":
            stmt = stmt.where(Image.imported == True)

        if self._filter_mode != "album":
            stmt = stmt.order_by(Image.id.desc())

        stmt = stmt.offset(self._offset).limit(PAGE_SIZE)

        results = db.execute(stmt).scalars().all()
        if not results:
            return

        need_thumbs = []
        for img in results:
            item = QListWidgetItem(img.file_name)
            item.setData(Qt.ItemDataRole.UserRole, img.id)

            # 尝试加载已有缩略图
            thumb_path = img.thumb_path
            if thumb_path and Path(thumb_path).exists():
                pixmap = QPixmap(thumb_path)
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap))
            else:
                need_thumbs.append(img.id)

            self.list_widget.addItem(item)
            self._item_map[img.id] = item

        self._offset += len(results)

        # 异步生成缺失的缩略图
        if need_thumbs:
            self._start_thumbnail_worker(need_thumbs)

    def _start_thumbnail_worker(self, image_ids: list[int]):
        self._stop_worker()

        self._thread = QThread()
        self._worker = ThumbnailWorker(image_ids, "medium")
        self._worker.moveToThread(self._thread)

        self._worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._worker.finished.connect(self._on_thumbnail_done)
        self._worker.error.connect(self._on_thumbnail_error)

        self._thread.started.connect(self._worker.run)
        self._thread.start()

    def _stop_worker(self):
        if self._worker:
            self._worker.cancel()
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
        item = QListWidgetItem(img.file_name)
        item.setData(Qt.ItemDataRole.UserRole, img.id)

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
        self.list_widget.clear()
        self._item_map.clear()

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

        action = menu.exec(self.list_widget.mapToGlobal(pos))
        if action and action.data():
            self.context_action.emit(action.data(), selected_ids)
