from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)


class AlbumDialog(QDialog):
    """创建/编辑相册对话框。"""

    def __init__(self, parent=None, album_name: str = "", album_desc: str = ""):
        super().__init__(parent)
        self.setWindowTitle("相册")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._name_input = QLineEdit(album_name)
        self._name_input.setPlaceholderText("请输入相册名称")
        form.addRow("相册名称:", self._name_input)

        self._desc_input = QTextEdit(album_desc)
        self._desc_input.setMaximumHeight(80)
        self._desc_input.setPlaceholderText("可选描述")
        form.addRow("描述:", self._desc_input)

        layout.addLayout(form)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

        # 名称为空时禁用 OK
        self._name_input.textChanged.connect(self._validate)
        self._validate()

    def _validate(self):
        ok_btn = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setEnabled(bool(self._name_input.text().strip()))

    def get_data(self) -> tuple[str, str]:
        return self._name_input.text().strip(), self._desc_input.toPlainText().strip()
