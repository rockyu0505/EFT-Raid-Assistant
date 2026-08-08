from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QCheckBox, QStyle, QStyleOptionButton, QTreeWidget

from app.ui.theme import THEME_LABELS, apply_app_theme, normalize_theme


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
        blue = self._unused_header_color("night_blue")
        pink = self._unused_header_color("sakura_pink")
        contrast = self._unused_header_color("high_contrast")

        self.assertLess(max(dark.red(), dark.green(), dark.blue()), 90)
        self.assertGreater(min(light.red(), light.green(), light.blue()), 180)
        self.assertLess(max(blue.red(), blue.green(), blue.blue()), 100)
        self.assertGreater(blue.blue(), blue.red())
        self.assertGreater(min(pink.red(), pink.green(), pink.blue()), 180)
        self.assertGreater(pink.red(), pink.green())
        self.assertLess(max(contrast.red(), contrast.green(), contrast.blue()), 30)

    def test_theme_registry_includes_blue_and_pink_without_changing_fallback(self) -> None:
        self.assertEqual(
            list(THEME_LABELS.items()),
            [
                ("light", "浅色"),
                ("dark", "深色"),
                ("night_blue", "夜蓝"),
                ("sakura_pink", "樱粉"),
                ("high_contrast", "高对比度"),
            ],
        )
        self.assertEqual(normalize_theme("NIGHT_BLUE"), "night_blue")
        self.assertEqual(normalize_theme("sakura_pink"), "sakura_pink")
        self.assertEqual(normalize_theme("unknown"), "light")

    def _checkbox_indicator_image(self, theme: str, checked: bool):
        apply_app_theme(self.app, 11, theme)
        checkbox = QCheckBox("功能选项")
        checkbox.setObjectName("featureChoice")
        checkbox.setChecked(checked)
        checkbox.resize(240, 48)
        checkbox.show()
        self.app.processEvents()

        option = QStyleOptionButton()
        checkbox.initStyleOption(option)
        indicator = checkbox.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator,
            option,
            checkbox,
        )
        image = checkbox.grab().toImage().copy(indicator)
        checkbox.hide()
        return image

    def test_dark_checkbox_uses_theme_surface_instead_of_a_white_box(self) -> None:
        image = self._checkbox_indicator_image("dark", False)
        center = image.pixelColor(image.width() // 2, image.height() // 2)

        self.assertLess(max(center.red(), center.green(), center.blue()), 80)

    def test_checked_checkbox_has_a_clear_theme_colored_state(self) -> None:
        unchecked = self._checkbox_indicator_image("dark", False)
        checked = self._checkbox_indicator_image("dark", True)
        changed_pixels = 0
        for y in range(min(unchecked.height(), checked.height())):
            for x in range(min(unchecked.width(), checked.width())):
                if unchecked.pixelColor(x, y) != checked.pixelColor(x, y):
                    changed_pixels += 1

        self.assertGreater(changed_pixels, 80)

    def test_dark_checked_checkbox_renders_the_bundled_dark_checkmark(self) -> None:
        apply_app_theme(self.app, 11, "dark")
        self.assertFalse(QPixmap("eftassets:checkbox_check_dark.xpm").isNull())
        checked = self._checkbox_indicator_image("dark", True)
        dark_mark_pixels = 0
        accent_pixels = 0
        for y in range(checked.height()):
            for x in range(checked.width()):
                color = checked.pixelColor(x, y)
                if max(color.red(), color.green(), color.blue()) < 55:
                    dark_mark_pixels += 1
                if color.red() > 175 and color.green() > 145 and color.blue() < 150:
                    accent_pixels += 1

        self.assertGreater(dark_mark_pixels, 20)
        self.assertGreater(accent_pixels, 150)


if __name__ == "__main__":
    unittest.main()
