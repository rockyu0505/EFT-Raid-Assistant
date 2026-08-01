from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.config import load_config
from app.gui import MainWindow
from app.ui.theme import apply_app_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Tarkov Raid Assistant")
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    apply_app_theme(app, config.get("ui_font_size", 11))

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
