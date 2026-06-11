import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.auth import hash_password, verify_password
from core.models import User
from core.query_worker import run_query
from core.session import get_current_user_id, get_current_user
from sqlalchemy import select, text

logger = logging.getLogger(__name__)


class UserManageDialog(QDialog):
    """管理员专属：用户管理对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("用户管理")
        self.setMinimumSize(500, 400)
        self.setModal(True)
        self._build_ui()
        self._load_users()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 用户表格
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["用户名", "显示名", "角色", "状态", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        # 新增用户区域
        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("用户名:"))
        self._input_username = QLineEdit()
        self._input_username.setPlaceholderText("英文")
        self._input_username.setMaximumWidth(120)
        add_layout.addWidget(self._input_username)

        add_layout.addWidget(QLabel("显示名:"))
        self._input_display = QLineEdit()
        self._input_display.setPlaceholderText("中文")
        self._input_display.setMaximumWidth(120)
        add_layout.addWidget(self._input_display)

        add_layout.addWidget(QLabel("角色:"))
        self._role_combo = QComboBox()
        self._role_combo.addItems(["普通用户", "管理员"])
        self._role_combo.setMaximumWidth(100)
        self._role_combo.currentIndexChanged.connect(self._on_role_changed)
        add_layout.addWidget(self._role_combo)

        self._password_label = QLabel("密码:")
        self._password_label.hide()
        add_layout.addWidget(self._password_label)
        self._input_password = QLineEdit()
        self._input_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._input_password.setPlaceholderText("管理员密码")
        self._input_password.setMaximumWidth(120)
        self._input_password.hide()
        add_layout.addWidget(self._input_password)

        btn_add = QPushButton("添加用户")
        btn_add.clicked.connect(self._on_add_user)
        add_layout.addWidget(btn_add)
        layout.addLayout(add_layout)

    def _on_role_changed(self, index):
        """角色切换时显示/隐藏密码输入框"""
        need_password = index == 1  # "管理员"
        self._password_label.setVisible(need_password)
        self._input_password.setVisible(need_password)

    def _load_users(self):
        """加载用户列表"""
        def query_users(db):
            # 调试：用原生 SQL 验证数据库实际行数
            raw_count = db.execute(text("SELECT count(*) FROM users")).scalar()
            logger.info("[DEBUG] 原生 SQL count: %d", raw_count)
            raw_rows = db.execute(text("SELECT id, username, role FROM users ORDER BY id")).fetchall()
            logger.info("[DEBUG] 原生 SQL 全部用户: %s", [(r[0], r[1], r[2]) for r in raw_rows])

            rows = db.execute(
                select(User).order_by(User.role.desc(), User.username)
            ).scalars().all()
            # 转为字典，避免 ORM 对象跨线程 detached 问题
            result = [
                {"id": u.id, "username": u.username, "display_name": u.display_name,
                 "role": u.role, "is_active": u.is_active}
                for u in rows
            ]
            logger.info("[DEBUG] ORM 查询到 %d 个用户: %s", len(result), [r["username"] for r in result])
            return result

        run_query(self, query_users, on_result=self._populate_table)

    def _populate_table(self, users):
        logger.info("_populate_table 收到 %d 个用户: %s", len(users), [u["username"] for u in users])
        current_user_id = get_current_user_id()
        self._table.setRowCount(len(users))
        for row, user in enumerate(users):
            self._table.setItem(row, 0, QTableWidgetItem(user["username"]))
            self._table.setItem(row, 1, QTableWidgetItem(user.get("display_name") or ""))

            role_text = "管理员" if user["role"] == "admin" else "普通用户"
            self._table.setItem(row, 2, QTableWidgetItem(role_text))

            status_text = "启用" if user["is_active"] else "停用"
            self._table.setItem(row, 3, QTableWidgetItem(status_text))

            # 操作按钮
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)

            uid = user["id"]
            is_self = uid == current_user_id

            if not is_self:
                if user["is_active"]:
                    btn_deactivate = QPushButton("停用")
                    btn_deactivate.clicked.connect(lambda checked, _uid=uid: self._toggle_active(_uid, False))
                    btn_layout.addWidget(btn_deactivate)
                else:
                    btn_activate = QPushButton("启用")
                    btn_activate.clicked.connect(lambda checked, _uid=uid: self._toggle_active(_uid, True))
                    btn_layout.addWidget(btn_activate)
                # 删除按钮
                btn_delete = QPushButton("删除")
                btn_delete.setStyleSheet("color: red;")
                btn_delete.clicked.connect(lambda checked, _uid=uid, _name=user["username"]: self._on_delete_user(_uid, _name))
                btn_layout.addWidget(btn_delete)
            else:
                lbl = QLabel("(当前用户)")
                lbl.setStyleSheet("color: #888;")
                btn_layout.addWidget(lbl)

            self._table.setCellWidget(row, 4, btn_widget)

    def _toggle_active(self, user_id: int, active: bool):
        """启用/停用用户"""
        action = "启用" if active else "停用"

        def do_toggle(db):
            user = db.get(User, user_id)
            if user:
                user.is_active = active
                db.commit()
                return True
            return False

        def on_done(result):
            if result:
                self._load_users()
            else:
                QMessageBox.warning(self, "错误", f"用户{action}失败")

        run_query(self, do_toggle, on_result=on_done)

    def _on_delete_user(self, user_id: int, username: str):
        """彻底删除用户（需验证当前管理员密码）"""
        from ui.password_dialog import ask_password
        password = ask_password("验证身份", "请输入管理员密码以确认删除:", self)
        if password is None:
            return

        current_user = get_current_user()
        current_id = current_user["id"]

        def do_delete(db):
            # 验证当前管理员密码
            admin = db.get(User, current_id)
            if not admin or not admin.password_hash:
                return "auth_fail"
            if not verify_password(password, admin.password_hash):
                return "auth_fail"

            user = db.get(User, user_id)
            if not user:
                return "not_found"
            db.delete(user)
            db.commit()
            return "ok"

        def on_done(result):
            if result == "ok":
                self._load_users()
            elif result == "auth_fail":
                QMessageBox.warning(self, "错误", "密码验证失败")
            else:
                QMessageBox.warning(self, "错误", "用户不存在或已被删除")

        run_query(self, do_delete, on_result=on_done)

    def _on_add_user(self):
        """添加新用户"""
        username = self._input_username.text().strip()
        display_name = self._input_display.text().strip()
        role = "admin" if self._role_combo.currentIndex() == 1 else "normal"

        if not username:
            QMessageBox.warning(self, "提示", "请输入用户名")
            self._input_username.setFocus()
            return

        if not username.isascii() or not username.replace("_", "").isalnum():
            QMessageBox.warning(self, "提示", "用户名只能包含英文、数字和下划线")
            self._input_username.setFocus()
            return

        password = self._input_password.text()
        if role == "admin" and not password:
            QMessageBox.warning(self, "提示", "请为管理员设置密码")
            self._input_password.setFocus()
            return

        hashed = hash_password(password) if password else None

        def create_user(db):
            existing = db.execute(
                select(User).where(User.username == username)
            ).scalar_one_or_none()
            if existing:
                return None
            user = User(
                username=username,
                display_name=display_name or username,
                role=role,
                is_active=True,
                password_hash=hashed,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

        def on_result(user):
            if user is None:
                QMessageBox.warning(self, "提示", "用户名已存在")
                return
            logger.info("用户创建成功: %s (id=%s)", user.username, user.id)
            self._input_username.clear()
            self._input_display.clear()
            self._input_password.clear()
            self._load_users()

        run_query(self, create_user, on_result=on_result)
