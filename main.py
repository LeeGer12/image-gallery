import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from config import APP_NAME, APP_VERSION
from core.database import init_db


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    init_db()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    # 加载全局样式
    style_path = Path(__file__).parent / "assets" / "style.qss"
    if style_path.exists():
        app.setStyleSheet(style_path.read_text(encoding="utf-8"))

    from ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
