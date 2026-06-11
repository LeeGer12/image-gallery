import json
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.models import Image
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "未知"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def _format_datetime(dt: datetime | None) -> str:
    if dt is None:
        return "未知"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class PropertyPanel(QWidget):
    """右侧属性面板，展示选中图片的详细信息。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(200)
        self._build_ui()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(4, 4, 4, 4)

        # 预览图
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(120)
        self._layout.addWidget(self._preview)

        # 基本信息
        self._info_group = QGroupBox("文件信息")
        form = QFormLayout()
        self._lbl_name = QLabel()
        self._lbl_name.setWordWrap(True)
        self._lbl_path = QLabel()
        self._lbl_path.setWordWrap(True)
        self._lbl_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._lbl_size = QLabel()
        self._lbl_dim = QLabel()
        self._lbl_format = QLabel()
        self._lbl_color = QLabel()
        self._lbl_created = QLabel()
        self._lbl_modified = QLabel()

        form.addRow("文件名:", self._lbl_name)
        form.addRow("路径:", self._lbl_path)
        form.addRow("大小:", self._lbl_size)
        form.addRow("尺寸:", self._lbl_dim)
        form.addRow("格式:", self._lbl_format)
        form.addRow("色彩:", self._lbl_color)
        form.addRow("创建时间:", self._lbl_created)
        form.addRow("修改时间:", self._lbl_modified)
        self._info_group.setLayout(form)
        self._layout.addWidget(self._info_group)

        # EXIF 信息
        self._exif_group = QGroupBox("EXIF 信息")
        self._exif_form = QFormLayout()
        self._exif_group.setLayout(self._exif_form)
        self._layout.addWidget(self._exif_group)

        # 分类信息
        self._meta_group = QGroupBox("分类信息")
        meta_form = QFormLayout()
        self._lbl_project_type = QLabel()
        self._lbl_style = QLabel()
        self._lbl_imported = QLabel()
        self._lbl_imported_by = QLabel()
        self._lbl_storage = QLabel()
        self._lbl_storage.setWordWrap(True)
        self._lbl_storage.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        meta_form.addRow("项目类型:", self._lbl_project_type)
        meta_form.addRow("风格:", self._lbl_style)
        meta_form.addRow("已导入:", self._lbl_imported)
        meta_form.addRow("导入者:", self._lbl_imported_by)
        meta_form.addRow("导入路径:", self._lbl_storage)
        self._meta_group.setLayout(meta_form)
        self._layout.addWidget(self._meta_group)

        self._layout.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._clear_display()

    def show_image(self, image_id: int, db: Session):
        """显示指定图片的属性（同步，供内部使用）。"""
        image = db.get(Image, image_id)
        if not image:
            self._clear_display()
            return

        data = {
            "file_name": image.file_name,
            "file_path": image.file_path,
            "file_size": image.file_size,
            "width": image.width,
            "height": image.height,
            "format": image.format,
            "color_space": image.color_space,
            "created_at": image.created_at,
            "modified_at": image.modified_at,
            "exif_json": image.exif_json,
            "project_type": image.project_type,
            "style_name": image.style_name,
            "imported": image.imported,
            "storage_path": image.storage_path,
            "thumb_path": image.thumb_path,
        }
        self.show_image_from_data(data)

    def show_image_from_data(self, data: dict | None):
        """从字典数据显示图片属性（异步回调使用）。"""
        if not data:
            self._clear_display()
            return

        # 预览图
        self._load_preview_from_data(data)

        # 基本信息
        self._lbl_name.setText(data.get("file_name", ""))
        self._lbl_path.setText(data.get("file_path", ""))
        self._lbl_size.setText(_format_size(data.get("file_size")))
        w, h = data.get("width"), data.get("height")
        self._lbl_dim.setText(f"{w} × {h}" if w else "未知")
        self._lbl_format.setText(data.get("format") or "未知")
        self._lbl_color.setText(data.get("color_space") or "未知")
        self._lbl_created.setText(_format_datetime(data.get("created_at")))
        self._lbl_modified.setText(_format_datetime(data.get("modified_at")))

        # EXIF
        self._clear_exif()
        exif_json = data.get("exif_json")
        if exif_json:
            try:
                exif = json.loads(exif_json)
                for key, value in exif.items():
                    lbl = QLabel(str(value))
                    lbl.setWordWrap(True)
                    self._exif_form.addRow(f"{key}:", lbl)
            except json.JSONDecodeError:
                pass

        # 分类信息
        self._lbl_project_type.setText(data.get("project_type") or "未设置")
        self._lbl_style.setText(data.get("style_name") or "未设置")
        self._lbl_imported.setText("是" if data.get("imported") else "否")
        self._lbl_imported_by.setText(data.get("imported_by_name") or "未知")
        self._lbl_storage.setText(data.get("storage_path") or "无")

        self._info_group.show()
        self._exif_group.show()
        self._meta_group.show()

    def _load_preview(self, image: Image):
        """加载预览图，宽度跟随面板"""
        data = {
            "thumb_path": image.thumb_path,
            "file_path": image.file_path,
            "file_size": image.file_size,
        }
        self._load_preview_from_data(data)

    def _load_preview_from_data(self, data: dict):
        """从字典数据加载预览图"""
        pixmap = None

        thumb_path = data.get("thumb_path")
        if thumb_path and Path(thumb_path).exists():
            pixmap = QPixmap(thumb_path)

        file_path = data.get("file_path")
        file_size = data.get("file_size")
        if (pixmap is None or pixmap.isNull()) and file_size:
            if file_size < 20 * 1024 * 1024 and file_path:
                pixmap = QPixmap(file_path)

        if pixmap and not pixmap.isNull():
            panel_width = max(self.width() - 20, 100)
            scaled = pixmap.scaledToWidth(
                min(panel_width, pixmap.width()),
                Qt.TransformationMode.SmoothTransformation,
            )
            self._preview.setPixmap(scaled)
        else:
            self._preview.setText("无预览")

    def _clear_display(self):
        self._preview.clear()
        self._preview.setText("选择图片查看属性")
        self._lbl_name.setText("")
        self._lbl_path.setText("")
        self._lbl_size.setText("")
        self._lbl_dim.setText("")
        self._lbl_format.setText("")
        self._lbl_color.setText("")
        self._lbl_created.setText("")
        self._lbl_modified.setText("")
        self._clear_exif()
        self._lbl_project_type.setText("")
        self._lbl_style.setText("")
        self._lbl_imported.setText("")
        self._lbl_imported_by.setText("")
        self._lbl_storage.setText("")
        self._info_group.hide()
        self._exif_group.hide()
        self._meta_group.hide()

    def _clear_exif(self):
        while self._exif_form.rowCount() > 0:
            self._exif_form.removeRow(0)
