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

    def test_unused_header_area_stays_dark(self) -> None:
        apply_app_theme(self.app, 11)
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

        self.assertLess(max(sample.red(), sample.green(), sample.blue()), 90)
        tree.hide()


if __name__ == "__main__":
    unittest.main()
