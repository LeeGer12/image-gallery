from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from core.database import SessionLocal
from core.models import Image
from sqlalchemy import select


class BatchMetaDialog(QDialog):
    """批量设置项目类型和风格对话框。"""

    def __init__(self, image_ids: list[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置项目类型/风格")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"已选择 {len(image_ids)} 张图片"))

        form = QFormLayout()

        self._type_input = QLineEdit()
        self._type_input.setPlaceholderText("项目类型（如售楼处、样板间）")
        form.addRow("项目类型:", self._type_input)

        self._style_input = QLineEdit()
        self._style_input.setPlaceholderText("风格名称")
        form.addRow("风格名称:", self._style_input)

        self._setup_completers()

        layout.addLayout(form)

        self._only_empty = QCheckBox("仅更新空白字段")
        self._only_empty.setChecked(True)
        layout.addWidget(self._only_empty)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

    def _setup_completers(self):
        db = SessionLocal()
        try:
            fields = [
                (self._type_input, Image.project_type),
                (self._style_input, Image.style_name),
            ]
            for line_edit, column in fields:
                values = db.execute(
                    select(column).where(column.isnot(None)).distinct()
                ).scalars().all()
                completer = QCompleter(values, self)
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                line_edit.setCompleter(completer)
        finally:
            db.close()

    def get_data(self) -> tuple[str, str, bool]:
        return (
            self._type_input.text().strip(),
            self._style_input.text().strip(),
            self._only_empty.isChecked(),
        )
