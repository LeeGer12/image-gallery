import logging

from PySide6.QtCore import QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class CollapsibleSection(QFrame):
    """单个可折叠区块：标题栏 + 内容区。"""

    toggled = Signal(bool)  # True=展开, False=折叠

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        self._header = QToolButton()
        self._header.setText(title)
        self._header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._header.setArrowType(Qt.ArrowType.DownArrow)
        self._header.setCheckable(True)
        self._header.setChecked(True)
        self._header.setAutoRaise(True)
        self._header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._header.clicked.connect(self._on_header_clicked)
        layout.addWidget(self._header)

        # 内容区
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        layout.addWidget(self._content)

        # 动画
        self._animation = QPropertyAnimation(self._content, b"maximumHeight")
        self._animation.setDuration(200)

    def _on_header_clicked(self):
        checked = self._header.isChecked()
        if checked:
            self._expand()
        else:
            self._collapse()
        self.toggled.emit(checked)

    def _expand(self):
        self._header.setArrowType(Qt.ArrowType.DownArrow)
        self._content.setVisible(True)

    def _collapse(self):
        self._header.setArrowType(Qt.ArrowType.RightArrow)
        self._content.setVisible(False)

    def set_content(self, widget: QWidget):
        """设置内容区 widget"""
        # 清空已有内容
        while self._content_layout.count():
            child = self._content_layout.takeAt(0)
            if child.widget():
                child.widget().setParent(None)
        self._content_layout.addWidget(widget)

    def expand(self):
        """展开"""
        self._header.setChecked(True)
        self._expand()

    def collapse(self):
        """折叠"""
        self._header.setChecked(False)
        self._collapse()

    def is_expanded(self) -> bool:
        return self._header.isChecked()


class AccordionSidebar(QWidget):
    """侧边栏容器，包含多个 CollapsibleSection。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sections: list[CollapsibleSection] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()

        self._layout = layout

    def add_section(self, title: str, content_widget: QWidget | None = None) -> CollapsibleSection:
        """添加一个可折叠区块"""
        section = CollapsibleSection(title)
        if content_widget:
            section.set_content(content_widget)

        # 插入到 stretch 之前
        idx = self._layout.count() - 1  # stretch 的位置
        self._layout.insertWidget(idx, section)
        self._sections.append(section)
        return section

    def clear_sections(self):
        """清空所有区块"""
        for section in self._sections:
            section.setParent(None)
        self._sections.clear()
