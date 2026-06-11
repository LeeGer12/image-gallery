import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QMessageBox,
)

from core.auth import hash_password, verify_password
from core.models import User
from core.query_worker import run_query
from core.session import set_current_user
from core.database import SessionLocal
from sqlalchemy import select, func

logger = logging.getLogger(__name__)


class LoginDialog(QDialog):
    """启动时的登录/注册对话框。

    用户为空 → 注册模式（第一个用户自动成为 admin）
    用户非空 → 选择模式（从列表中选择用户名）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ImageGallery - 登录")
        self.setMinimumWidth(350)
        self.setModal(True)
        self._users = []
        self._build_ui()
        self._check_users()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        self._title_label = QLabel("请选择用户")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        layout.addWidget(self._title_label)

        # 选择模式容器
        self._select_group = QGroupBox()
        select_layout = QVBoxLayout(self._select_group)
        self._user_list = QListWidget()
        self._user_list.setMinimumHeight(150)
        self._user_list.itemDoubleClicked.connect(self._on_confirm)
        self._user_list.currentItemChanged.connect(self._on_user_selected)
        select_layout.addWidget(self._user_list)
        layout.addWidget(self._select_group)

        # 注册模式容器
        self._register_group = QGroupBox()
        register_layout = QVBoxLayout(self._register_group)
        register_layout.addWidget(QLabel("用户名:"))
        self._input_username = QLineEdit()
        self._input_username.setPlaceholderText("英文，用于标识身份")
        register_layout.addWidget(self._input_username)
        register_layout.addWidget(QLabel("显示名称:"))
        self._input_display = QLineEdit()
        self._input_display.setPlaceholderText("中文，如：张三")
        register_layout.addWidget(self._input_display)
        register_layout.addWidget(QLabel("密码:"))
        self._input_reg_password = QLineEdit()
        self._input_reg_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._input_reg_password.setPlaceholderText("管理员密码")
        register_layout.addWidget(self._input_reg_password)
        register_layout.addWidget(QLabel("确认密码:"))
        self._input_reg_confirm = QLineEdit()
        self._input_reg_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self._input_reg_confirm.setPlaceholderText("再次输入密码")
        register_layout.addWidget(self._input_reg_confirm)
        self._register_hint = QLabel("第一个用户将自动成为管理员")
        self._register_hint.setStyleSheet("color: #666; font-size: 12px;")
        register_layout.addWidget(self._register_hint)
        layout.addWidget(self._register_group)

        # 选择模式下的密码输入（仅 admin 需要）
        self._login_password_layout = QHBoxLayout()
        self._login_password_label = QLabel("密码:")
        self._login_password_layout.addWidget(self._login_password_label)
        self._input_login_password = QLineEdit()
        self._input_login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._input_login_password.setPlaceholderText("管理员密码")
        self._input_login_password.returnPressed.connect(self._on_confirm)
        self._login_password_layout.addWidget(self._input_login_password)
        layout.addLayout(self._login_password_layout)
        self._login_password_label.hide()
        self._input_login_password.hide()

        # 按钮
        btn_layout = QHBoxLayout()
        self._btn_confirm = QPushButton("确认")
        self._btn_confirm.setDefault(True)
        self._btn_confirm.clicked.connect(self._on_confirm)
        btn_layout.addStretch()
        btn_layout.addWidget(self._btn_confirm)
        layout.addLayout(btn_layout)

    def _check_users(self):
        """异步检查 users 表是否为空"""
        def query_count(db):
            return db.execute(select(func.count()).select_from(User)).scalar()

        run_query(self, query_count, on_result=self._on_count_result)

    def _on_count_result(self, count):
        if count == 0:
            self._show_register_mode()
        else:
            self._load_users()

    def _show_register_mode(self):
        """显示注册界面"""
        self._select_group.hide()
        self._register_group.show()
        self._title_label.setText("首次使用 - 注册管理员")
        self._input_username.setFocus()

    def _show_select_mode(self):
        """显示选择界面"""
        self._register_group.hide()
        self._select_group.show()
        self._title_label.setText("请选择用户")

    def _load_users(self):
        """加载活跃用户列表"""
        def query_users(db):
            rows = db.execute(
                select(User).where(User.is_active == True).order_by(User.username)
            ).scalars().all()
            # 转为字典，避免 ORM 对象跨线程 detached 问题
            return [
                {"id": u.id, "username": u.username, "display_name": u.display_name,
                 "role": u.role, "has_password": bool(u.password_hash)}
                for u in rows
            ]

        run_query(self, query_users, on_result=self._on_users_loaded)

    def _on_users_loaded(self, users):
        self._users = users
        self._user_list.clear()
        for user in users:
            role_text = " (管理员)" if user["role"] == "admin" else ""
            display = user.get("display_name") or user["username"]
            item = QListWidgetItem(f"{display}{role_text}")
            item.setData(Qt.ItemDataRole.UserRole, user["id"])
            item.setData(Qt.ItemDataRole.UserRole + 1, user["username"])
            item.setData(Qt.ItemDataRole.UserRole + 2, user["role"])
            item.setData(Qt.ItemDataRole.UserRole + 3, user.get("display_name") or "")
            item.setData(Qt.ItemDataRole.UserRole + 4, user["has_password"])
            self._user_list.addItem(item)
        if self._user_list.count() > 0:
            self._user_list.setCurrentRow(0)
        self._show_select_mode()

    def _on_user_selected(self, current, _previous):
        """选中用户变化时，根据角色显示/隐藏密码框"""
        if not current:
            self._login_password_label.hide()
            self._input_login_password.hide()
            return
        role = current.data(Qt.ItemDataRole.UserRole + 2)
        has_password = current.data(Qt.ItemDataRole.UserRole + 4)
        need_password = role == "admin" and has_password
        self._login_password_label.setVisible(need_password)
        self._input_login_password.setVisible(need_password)
        if need_password:
            self._input_login_password.clear()
            self._input_login_password.setFocus()

    def _on_confirm(self):
        """确认登录/注册"""
        if self._register_group.isVisible():
            self._do_register()
        else:
            self._do_login()

    def _do_register(self):
        """执行注册"""
        username = self._input_username.text().strip()
        display_name = self._input_display.text().strip()
        password = self._input_reg_password.text()
        confirm = self._input_reg_confirm.text()

        if not username:
            QMessageBox.warning(self, "提示", "请输入用户名")
            self._input_username.setFocus()
            return

        # 检查用户名格式（只允许英文、数字、下划线）
        if not username.isascii() or not username.replace("_", "").isalnum():
            QMessageBox.warning(self, "提示", "用户名只能包含英文、数字和下划线")
            self._input_username.setFocus()
            return

        if not password:
            QMessageBox.warning(self, "提示", "请设置管理员密码")
            self._input_reg_password.setFocus()
            return

        if password != confirm:
            QMessageBox.warning(self, "提示", "两次输入的密码不一致")
            self._input_reg_confirm.setFocus()
            return

        hashed = hash_password(password)

        def create_admin(db):
            existing = db.execute(
                select(User).where(User.username == username)
            ).scalar_one_or_none()
            if existing:
                return None  # 用户名已存在
            user = User(
                username=username,
                display_name=display_name or username,
                role="admin",
                is_active=True,
                password_hash=hashed,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

        run_query(self, create_admin, on_result=self._on_register_result)

    def _on_register_result(self, user):
        if user is None:
            QMessageBox.warning(self, "提示", "用户名已存在，请换一个")
            self._input_username.setFocus()
            return
        set_current_user(user.id, user.username, user.role, user.display_name or "")
        self.accept()

    def _do_login(self):
        """执行登录"""
        item = self._user_list.currentItem()
        if not item:
            QMessageBox.warning(self, "提示", "请选择一个用户")
            return
        user_id = item.data(Qt.ItemDataRole.UserRole)
        username = item.data(Qt.ItemDataRole.UserRole + 1)
        role = item.data(Qt.ItemDataRole.UserRole + 2)
        display_name = item.data(Qt.ItemDataRole.UserRole + 3) or ""
        has_password = item.data(Qt.ItemDataRole.UserRole + 4)

        # admin 需要验证密码
        if role == "admin" and has_password:
            password = self._input_login_password.text()
            if not password:
                QMessageBox.warning(self, "提示", "请输入管理员密码")
                self._input_login_password.setFocus()
                return
            # 异步验证密码
            def check_password(db):
                u = db.execute(
                    select(User).where(User.id == user_id)
                ).scalar_one_or_none()
                if not u or not u.password_hash:
                    return False
                return verify_password(password, u.password_hash)

            def on_result(ok):
                if ok:
                    set_current_user(user_id, username, role, display_name)
                    self.accept()
                else:
                    QMessageBox.warning(self, "错误", "密码错误")

            run_query(self, check_password, on_result=on_result)
        else:
            set_current_user(user_id, username, role, display_name)
            self.accept()
