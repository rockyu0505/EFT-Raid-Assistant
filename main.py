from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.config import load_config
from app.gui import MainWindow
from app.ui.theme import apply_app_theme


def main() -> int:
    smoke_test = "--smoke-test" in sys.argv
    if "--ocr-smoke-test" in sys.argv:
        from PIL import Image

        from app.rapid_ocr import run_rapid_text

        run_rapid_text(
            Image.new("RGB", (360, 120), "white"),
            model_version="v5",
            use_det=True,
        )
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("Tarkov Raid Assistant")
    app.setQuitOnLastWindowClosed(False)
    config = load_config()
    apply_app_theme(app, config.get("ui_font_size", 11))

    window = MainWindow()
    window.show()
    if smoke_test:
        QTimer.singleShot(2000, window.request_exit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
