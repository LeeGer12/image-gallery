"""密码输入对话框，供登录验证和敏感操作验证复用。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class PasswordDialog(QDialog):
    """模态密码输入对话框。"""

    def __init__(self, title: str, prompt: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)

        self._label = QLabel(prompt)
        layout.addWidget(self._label)

        self._input = QLineEdit()
        self._input.setEchoMode(QLineEdit.EchoMode.Password)
        self._input.setPlaceholderText("请输入密码")
        self._input.returnPressed.connect(self._on_confirm)
        layout.addWidget(self._input)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_confirm = QPushButton("确认")
        btn_confirm.setDefault(True)
        btn_confirm.clicked.connect(self._on_confirm)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_confirm)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self._input.setFocus()

    def _on_confirm(self):
        if not self._input.text():
            QMessageBox.warning(self, "提示", "请输入密码")
            return
        self.accept()

    def get_password(self) -> str:
        return self._input.text()


def ask_password(title: str, prompt: str, parent=None) -> str | None:
    """便捷函数：弹出密码对话框，返回密码字符串或 None（取消）。"""
    dlg = PasswordDialog(title, prompt, parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.get_password()
    return None
