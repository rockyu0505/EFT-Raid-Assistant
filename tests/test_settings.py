from __future__ import annotations

import copy
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox

from app.config import DEFAULT_CONFIG, FEATURE_DEFINITIONS
from app.gui import FeatureSetupDialog, SettingsDialog
from app.ui.theme import THEME_LABELS, apply_app_theme


class SettingsInformationArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        apply_app_theme(self.app, 11, "light")

    def test_top_level_settings_follow_user_tasks(self) -> None:
        dialog = SettingsDialog(copy.deepcopy(DEFAULT_CONFIG))

        self.assertEqual(
            [dialog.settings_tabs.tabText(index) for index in range(dialog.settings_tabs.count())],
            ["常规", "功能", "查价", "提醒与浮窗", "快捷键", "高级"],
        )
        self.assertEqual(
            [dialog.advanced_tabs.tabText(index) for index in range(dialog.advanced_tabs.count())],
            ["性能与诊断", "截图与识别", "画面增强"],
        )
        self.assertEqual(dialog.settings_tabs.currentIndex(), 0)
        self.assertEqual(
            [dialog.ui_theme.itemText(index) for index in range(dialog.ui_theme.count())],
            list(THEME_LABELS.values()),
        )
        dialog.close()

    def test_feature_page_contains_module_choices_not_gamma_safety_controls(self) -> None:
        dialog = SettingsDialog(copy.deepcopy(DEFAULT_CONFIG))
        feature_page = dialog.settings_tabs.widget(1)
        feature_checks = feature_page.findChildren(QCheckBox)

        self.assertEqual(len(feature_checks), len(FEATURE_DEFINITIONS))
        self.assertTrue(all(check.objectName() == "featureChoice" for check in feature_checks))
        self.assertNotIn(dialog.display_filter_restore_on_exit, feature_checks)
        self.assertNotIn(dialog.display_filter_eye_care_enabled, feature_checks)
        dialog.close()

    def test_first_run_asks_for_fee_profile_without_using_personal_defaults(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        dialog = FeatureSetupDialog(config)

        self.assertEqual(dialog.flea_intelligence_center_level.currentData(), 0)
        self.assertEqual(dialog.flea_hideout_management_level.value(), 0)
        self.assertEqual(dialog.values()["flea_intelligence_center_level"], 0)
        self.assertEqual(dialog.values()["flea_hideout_management_level"], 0)

        dialog.flea_intelligence_center_level.setCurrentIndex(
            dialog.flea_intelligence_center_level.findData(2)
        )
        dialog.flea_hideout_management_level.setValue(17)
        self.assertEqual(dialog.values()["flea_intelligence_center_level"], 2)
        self.assertEqual(dialog.values()["flea_hideout_management_level"], 17)
        dialog.close()

    def test_reorganization_preserves_advanced_and_common_values(self) -> None:
        config = copy.deepcopy(DEFAULT_CONFIG)
        config.update(
            {
                "ui_theme": "dark",
                "item_display_language": "en",
                "close_to_tray": False,
                "price_cache_stale_hours": 72,
                "performance_max_concurrent_workers": 3,
                "hover_search_margins": [401, 402, 403, 404],
                "display_filter_eye_care_check_seconds": 7,
                "flea_intelligence_center_level": 3,
                "flea_hideout_management_level": 20,
            }
        )
        dialog = SettingsDialog(config)
        values = dialog.values()

        for key in (
            "ui_theme",
            "item_display_language",
            "close_to_tray",
            "price_cache_stale_hours",
            "performance_max_concurrent_workers",
            "hover_search_margins",
            "display_filter_eye_care_check_seconds",
            "flea_intelligence_center_level",
            "flea_hideout_management_level",
        ):
            self.assertEqual(values[key], config[key])
        dialog.close()

    def test_every_theme_renders_every_top_level_page(self) -> None:
        for theme in THEME_LABELS:
            apply_app_theme(self.app, 11, theme)
            dialog = SettingsDialog(copy.deepcopy(DEFAULT_CONFIG))
            dialog.show()
            for index in range(dialog.settings_tabs.count()):
                dialog.settings_tabs.setCurrentIndex(index)
                self.app.processEvents()
                image = dialog.grab().toImage()
                self.assertFalse(image.isNull())
                self.assertGreater(image.width(), 600)
                self.assertGreater(image.height(), 500)
            dialog.close()


if __name__ == "__main__":
    unittest.main()
