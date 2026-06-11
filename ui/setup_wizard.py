"""首次启动配置向导：输入服务器 IP → 测试连接 → 保存配置。"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


class _TestWorker(QThread):
    """后台测试数据库连接和文件夹可达性。"""

    db_ok = Signal(bool, str)    # success, message
    fs_ok = Signal(bool, str)    # success, message

    def __init__(self, server_ip: str):
        super().__init__()
        self._ip = server_ip

    def run(self):
        # 测试数据库连接
        try:
            from sqlalchemy import create_engine, text

            url = f"postgresql+psycopg2://gallery:ImageGallery2026@{self._ip}:5432/imagegallery"
            engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            self.db_ok.emit(True, "数据库连接成功")
        except Exception as e:
            self.db_ok.emit(False, f"数据库连接失败: {e}")

        # 测试文件夹可达性
        try:
            share_path = Path(f"//{self._ip}/ImageGalleryStorage")
            if share_path.exists():
                self.fs_ok.emit(True, "共享文件夹可访问")
            else:
                # 尝试创建
                try:
                    share_path.mkdir(parents=True, exist_ok=True)
                    self.fs_ok.emit(True, "共享文件夹已创建")
                except OSError as e:
                    self.fs_ok.emit(False, f"共享文件夹不可达: {e}")
        except Exception as e:
            self.fs_ok.emit(False, f"文件夹测试失败: {e}")


class SetupWizard(QDialog):
    """首次启动配置向导。"""

    def __init__(self, parent=None, error_msg: str = ""):
        super().__init__(parent)
        self.setWindowTitle("ImageGallery - 连接配置")
        self.setMinimumWidth(450)
        self.setModal(True)
        self._server_ip = ""
        self._db_ok = False
        self._fs_ok = False
        self._worker = None
        self._error_msg = error_msg
        self._build_ui()
        if error_msg:
            self._show_error_step(error_msg)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # ── 步骤 1：输入 IP ──
        step1 = QWidget()
        s1_layout = QVBoxLayout(step1)
        title = QLabel("连接图库服务器")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
        s1_layout.addWidget(title)

        hint = QLabel(
            "请输入中枢电脑的 IP 地址。\n"
            "（在中枢电脑上打开 cmd，输入 ipconfig 可查看）"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; margin-bottom: 10px;")
        s1_layout.addWidget(hint)

        ip_group = QGroupBox("服务器 IP 地址")
        ip_layout = QHBoxLayout(ip_group)
        self._ip_input = QLineEdit()
        self._ip_input.setPlaceholderText("例如 192.168.1.100")
        self._ip_input.returnPressed.connect(self._on_next)
        ip_layout.addWidget(self._ip_input)
        s1_layout.addWidget(ip_group)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_next = QPushButton("下一步")
        self._btn_next.setDefault(True)
        self._btn_next.clicked.connect(self._on_next)
        btn_row.addWidget(self._btn_next)
        s1_layout.addLayout(btn_row)

        self._stack.addWidget(step1)

        # ── 步骤 2：测试连接 ──
        step2 = QWidget()
        s2_layout = QVBoxLayout(step2)
        t2 = QLabel("正在测试连接...")
        t2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t2.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        s2_layout.addWidget(t2)

        self._db_label = QLabel("⏳ 数据库连接...")
        self._db_label.setStyleSheet("font-size: 14px; margin: 5px 20px;")
        s2_layout.addWidget(self._db_label)

        self._fs_label = QLabel("⏳ 共享文件夹...")
        self._fs_label.setStyleSheet("font-size: 14px; margin: 5px 20px;")
        s2_layout.addWidget(self._fs_label)

        self._btn_retry = QPushButton("重试")
        self._btn_retry.clicked.connect(self._on_next)
        self._btn_retry.hide()
        s2_layout.addWidget(self._btn_retry, alignment=Qt.AlignmentFlag.AlignCenter)

        self._stack.addWidget(step2)

        # ── 步骤 3：成功 ──
        step3 = QWidget()
        s3_layout = QVBoxLayout(step3)
        ok_label = QLabel("✅ 连接成功")
        ok_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ok_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #2e7d32; margin: 20px;")
        s3_layout.addWidget(ok_label)

        self._btn_enter = QPushButton("进入图库")
        self._btn_enter.setDefault(True)
        self._btn_enter.clicked.connect(self.accept)
        s3_layout.addWidget(self._btn_enter, alignment=Qt.AlignmentFlag.AlignCenter)

        self._stack.addWidget(step3)

        # ── 错误步骤（init_db 失败时显示）──
        step_err = QWidget()
        se_layout = QVBoxLayout(step_err)
        err_title = QLabel("⚠️ 连接失败")
        err_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        err_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #c62828; margin: 10px;")
        se_layout.addWidget(err_title)

        self._err_detail = QLabel()
        self._err_detail.setWordWrap(True)
        self._err_detail.setStyleSheet("color: #666; margin: 10px 20px;")
        se_layout.addWidget(self._err_detail)

        hint = QLabel("请确认中枢电脑已开机，PostgreSQL 已启动，网络已连接。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #999; margin: 5px 20px;")
        se_layout.addWidget(hint)

        btn_err_row = QHBoxLayout()
        btn_err_row.addStretch()
        btn_reconfig = QPushButton("重新配置")
        btn_reconfig.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        btn_err_row.addWidget(btn_reconfig)
        btn_err_retry = QPushButton("重试连接")
        btn_err_retry.clicked.connect(self.accept)  # accept 让 main.py 重试 init_db
        btn_err_row.addWidget(btn_err_retry)
        se_layout.addLayout(btn_err_row)

        self._stack.addWidget(step_err)

    def _show_error_step(self, msg: str):
        """显示错误步骤（init_db 失败时）。"""
        self._err_detail.setText(msg)
        self._stack.setCurrentIndex(3)

    def _validate_ip(self, ip: str) -> bool:
        """简单验证 IP 格式。"""
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(p) <= 255 for p in parts)
        except ValueError:
            return False

    def _on_next(self):
        """步骤 1 → 步骤 2：开始测试。"""
        ip = self._ip_input.text().strip()
        if not ip:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请输入服务器 IP 地址")
            return
        if not self._validate_ip(ip):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "IP 地址格式不正确，应为如 192.168.1.100")
            return

        self._server_ip = ip
        self._stack.setCurrentIndex(1)
        self._db_label.setText("⏳ 数据库连接...")
        self._db_label.setStyleSheet("font-size: 14px; margin: 5px 20px; color: #333;")
        self._fs_label.setText("⏳ 共享文件夹...")
        self._fs_label.setStyleSheet("font-size: 14px; margin: 5px 20px; color: #333;")
        self._btn_retry.hide()
        self._db_ok = False
        self._fs_ok = False
        self._btn_next.setEnabled(False)

        self._worker = _TestWorker(ip)
        self._worker.db_ok.connect(self._on_db_result)
        self._worker.fs_ok.connect(self._on_fs_result)
        self._worker.finished.connect(self._on_test_done)
        self._worker.start()

    def _on_db_result(self, ok: bool, msg: str):
        self._db_ok = ok
        icon = "✅" if ok else "❌"
        color = "#2e7d32" if ok else "#c62828"
        self._db_label.setText(f"{icon} {msg}")
        self._db_label.setStyleSheet(f"font-size: 14px; margin: 5px 20px; color: {color};")

    def _on_fs_result(self, ok: bool, msg: str):
        self._fs_ok = ok
        icon = "✅" if ok else "❌"
        color = "#2e7d32" if ok else "#c62828"
        self._fs_label.setText(f"{icon} {msg}")
        self._fs_label.setStyleSheet(f"font-size: 14px; margin: 5px 20px; color: {color};")

    def _on_test_done(self):
        self._btn_next.setEnabled(True)
        if self._db_ok and self._fs_ok:
            # 保存配置
            from core.settings import save_settings
            save_settings({"server_ip": self._server_ip})
            self._stack.setCurrentIndex(2)
        else:
            self._btn_retry.show()

    def get_server_ip(self) -> str:
        return self._server_ip
