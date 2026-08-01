from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.gui import MainWindow
from app.ui.theme import apply_app_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Tarkov Raid Assistant")
    app.setQuitOnLastWindowClosed(False)
    apply_app_theme(app)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
