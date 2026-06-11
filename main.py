import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("ImageGallery")

    # 加载全局样式
    style_path = Path(__file__).parent / "assets" / "style.qss"
    if style_path.exists():
        app.setStyleSheet(style_path.read_text(encoding="utf-8"))

    # ── 配置检查：settings.json 不存在时弹出向导 ──
    from core.settings import get_server_ip

    if get_server_ip() is None:
        from ui.setup_wizard import SetupWizard

        wizard = SetupWizard()
        if wizard.exec() != SetupWizard.DialogCode.Accepted:
            sys.exit(0)

    # ── 初始化数据库（循环：失败则重新配置） ──
    while True:
        import importlib
        import config
        importlib.reload(config)
        app.setApplicationName(config.APP_NAME)
        app.setApplicationVersion(config.APP_VERSION)

        from core.database import rebuild_engine, init_db
        rebuild_engine()

        try:
            init_db()
            break  # 成功，跳出循环
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            from ui.setup_wizard import SetupWizard

            msg = (
                f"无法连接到数据库：\n{e}\n\n"
                "请确认中枢电脑已开机，PostgreSQL 已启动，网络已连接。"
            )
            wizard = SetupWizard(error_msg=msg)
            if wizard.exec() != SetupWizard.DialogCode.Accepted:
                sys.exit(0)
            # 向导保存了新配置，重试

    # ── 登录 ──
    from ui.login_dialog import LoginDialog

    login = LoginDialog()
    if login.exec() != LoginDialog.DialogCode.Accepted:
        sys.exit(0)

    # ── 主窗口 ──
    from ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
