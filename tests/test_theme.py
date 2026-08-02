from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidget

from app.ui.theme import apply_app_theme


class ThemeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _unused_header_color(self, theme: str):
        apply_app_theme(self.app, 11, theme)
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["第一列", "第二列"])
        tree.resize(620, 220)
        tree.setColumnWidth(0, 140)
        tree.setColumnWidth(1, 140)
        tree.show()
        self.app.processEvents()

        image = tree.grab().toImage()
        sample = image.pixelColor(560, max(4, tree.header().height() // 2))
        tree.hide()
        return sample

    def test_unused_header_area_follows_selected_theme(self) -> None:
        dark = self._unused_header_color("dark")
        light = self._unused_header_color("light")
        contrast = self._unused_header_color("high_contrast")

        self.assertLess(max(dark.red(), dark.green(), dark.blue()), 90)
        self.assertGreater(min(light.red(), light.green(), light.blue()), 180)
        self.assertLess(max(contrast.red(), contrast.green(), contrast.blue()), 30)


if __name__ == "__main__":
    unittest.main()
