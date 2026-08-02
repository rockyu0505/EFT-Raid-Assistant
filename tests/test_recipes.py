from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHeaderView

from app.config import DEFAULT_CONFIG
from app.gui import MainWindow, PriceToast, SettingsDialog, _build_price_view
from app.recipes import (
    RecipeCatalog,
    RecipeNotice,
    recipe_acquisition_text,
    recipe_requirement_rows,
    recipe_search_text,
    recipe_source_text,
    recipe_unlock_note,
)
from app.ui.theme import apply_app_theme


class _RecipeSmokeWindow(MainWindow):
    def _reset_run_log(self) -> None:
        pass

    def _build_tray_icon(self) -> None:
        pass

    def _register_hotkeys(self) -> None:
        pass

    def _apply_performance_settings(self) -> None:
        pass

    def _save_config(self) -> None:
        pass


class RecipeCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "recipes.json"
        recipe = {
            "id": "craft-1",
            "kind": "craft",
            "source": "工作台",
            "level": 2,
            "duration": 3661,
            "task_unlock": True,
            "unlock_task": {
                "id": "task-1",
                "trader": "Mechanic",
                "name_en": "Test Drive",
                "name_zh": "试驾",
            },
            "product": {
                "id": "product",
                "name": "测试弹药",
                "count": 60,
                "category_path": ["ammo", "rounds"],
            },
            "requirements": [
                {
                    "id": "powder",
                    "name": "火药",
                    "count": 2,
                    "tool": True,
                    "min_level": 15,
                    "functional": True,
                }
            ],
        }
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "generated_at": "2026-08-01T00:00:00Z",
                    "source": "test",
                    "handbook_categories": {
                        "ammo": {"name": "弹药", "parent": ""},
                        "rounds": {"name": "子弹", "parent": "ammo"},
                    },
                    "modes": {"regular": [recipe], "pve": []},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_indexes_only_tracked_recipes_by_requirement(self) -> None:
        catalog = RecipeCatalog(self.path)

        self.assertEqual(catalog.record_count("regular"), 1)
        self.assertEqual(catalog.tracked_requirement_lines("powder", [], "regular"), [])
        lines = catalog.tracked_requirement_lines("powder", ["craft-1"], "regular")

        self.assertEqual(len(lines), 1)
        self.assertIn("测试弹药 ×60", lines[0])
        self.assertIn("需当前物品 ×2", lines[0])
        self.assertIn("物品等级≥15", lines[0])
        self.assertIn("需可用状态", lines[0])

    def test_search_text_contains_product_source_and_requirement(self) -> None:
        record = RecipeCatalog(self.path).records("regular")[0]
        search_text = recipe_search_text(record)

        self.assertIn("测试弹药", search_text)
        self.assertIn("工作台", search_text)
        self.assertIn("火药", search_text)
        self.assertIn("试驾", search_text)
        self.assertIn("test drive", search_text)

        path = RecipeCatalog(self.path).category_path(record)
        self.assertEqual([category["name"] for category in path], ["弹药", "子弹"])

        self.assertEqual(recipe_source_text(record), "工作台 Lv2 制作")
        self.assertEqual(recipe_acquisition_text(record), "01:01:01")
        self.assertEqual(
            recipe_unlock_note(record, "zh"),
            "Mechanic · 试驾",
        )
        self.assertEqual(
            recipe_unlock_note(record, "en"),
            "Mechanic · Test Drive",
        )
        record["unlock_task"]["name_zh"] = ""
        self.assertEqual(
            recipe_unlock_note(record, "zh"),
            "Mechanic · Test Drive",
        )
        self.assertEqual(
            recipe_acquisition_text({"kind": "barter", "buy_limit": 3}),
            "限购 ×3",
        )
        requirement = recipe_requirement_rows(record)[0]
        self.assertEqual(requirement.display_name, "火药（等级≥15；需可用）")
        self.assertTrue(requirement.is_tool)
        self.assertEqual(requirement.count_text, "×2")

    def test_recipe_notice_is_in_price_card_and_log(self) -> None:
        price = SimpleNamespace(
            game_mode="regular",
            name="Gunpowder",
            short_name="Powder",
            confidence=1.0,
            best_vendor_name="Therapist",
            best_vendor_currency="RUB",
            best_vendor_price=10_000,
            avg_24h_price=12_000,
            last_low_price=11_000,
            slots=1,
            is_firearm=False,
        )

        view = _build_price_view(
            price,
            "en",
            [],
            "slot",
            recipe_notices=[
                RecipeNotice(
                    recipe_id="craft-1",
                    product_text="测试弹药 ×60",
                    source_text="工作台 Lv2 制作",
                    requirement_text="需当前物品 ×2",
                )
            ],
            recipe_accent_color="#33AA77",
        )

        self.assertEqual(len(view.recipe_notices), 1)
        self.assertIn("测试弹药", view.label_html)
        self.assertIn("#33AA77", view.label_html)
        self.assertIn("关注配方", view.log_text)

        toast = PriceToast(view)
        self.assertFalse(toast._recipe_box.isHidden())
        self.assertIn("测试弹药", toast._recipe_content_label.text())
        self.assertIn("#33AA77", toast._recipe_box.styleSheet())
        toast.close()

    def test_main_window_builds_bundled_recipe_tree(self) -> None:
        config = deepcopy(DEFAULT_CONFIG)
        config["enabled_features"] = ["recipe_tracking"]
        config["feature_setup_complete"] = True
        catalog = RecipeCatalog()
        tracked_id = str(catalog.records("pve")[0]["id"])
        config["tracked_recipe_ids"] = [tracked_id]
        config["recipe_overlay_accent_color"] = "#3366AA"
        with patch("app.gui.load_config", return_value=config):
            window = _RecipeSmokeWindow()

        self.assertIsNotNone(window.recipe_catalog)
        self.assertEqual(window.recipe_catalog.record_count("pve"), 1020)
        self.assertGreater(window.recipe_category_tree.topLevelItemCount(), 0)
        self.assertGreater(window.recipe_result_tree.topLevelItemCount(), 0)
        self.assertGreater(window.tracked_recipe_tree.topLevelItemCount(), 0)
        self.assertIn(
            "交换用物品", window.recipe_category_tree.topLevelItem(1).text(0)
        )
        self.assertIn("已关注总览 (1)", window.recipe_tabs.tabText(1))
        self.assertIn("共 1020 个配方", window.recipe_summary_label.text())
        self.assertEqual(window.recipe_color_label.text(), "#3366AA")
        self.assertGreaterEqual(window.minimumWidth(), 1160)
        self.assertGreaterEqual(window.width(), 1520)
        self.assertEqual(window.recipe_result_tree.headerItem().text(1), "工具")
        self.assertEqual(window.recipe_result_tree.headerItem().text(3), "耗时 / 限购")
        self.assertEqual(window.recipe_result_tree.headerItem().text(4), "任务依赖")
        for tree in (window.recipe_result_tree, window.tracked_recipe_tree):
            self.assertTrue(
                all(
                    tree.header().sectionResizeMode(column)
                    == QHeaderView.ResizeMode.Interactive
                    for column in range(tree.columnCount())
                )
            )

        product_item = window.recipe_result_tree.topLevelItem(0)
        self.assertTrue(product_item.text(0).endswith(f"（{product_item.childCount()}）"))
        recipe_item = product_item.child(0)
        self.assertRegex(recipe_item.text(0), r"(制作|兑换)$")
        self.assertEqual(recipe_item.text(1), "")
        self.assertTrue(recipe_item.text(2).startswith("产出 ×"))
        self.assertEqual(recipe_item.foreground(2).color().name(), "#e8c47a")
        requirement_item = recipe_item.child(0)
        self.assertIn(requirement_item.text(1), ("", "✓"))
        self.assertEqual(requirement_item.foreground(2).color().name(), "#8fc7ff")

        requirement_items = [
            recipe_item.child(requirement_index)
            for product_index in range(window.recipe_result_tree.topLevelItemCount())
            for product_item in [window.recipe_result_tree.topLevelItem(product_index)]
            for recipe_index in range(product_item.childCount())
            for recipe_item in [product_item.child(recipe_index)]
            for requirement_index in range(recipe_item.childCount())
        ]
        self.assertTrue(requirement_items)
        self.assertTrue(any(item.text(1) == "✓" for item in requirement_items))
        self.assertTrue(any("（等级≥" in item.text(0) for item in requirement_items))

        recipe_items = [
            product_item.child(recipe_index)
            for product_index in range(window.recipe_result_tree.topLevelItemCount())
            for product_item in [window.recipe_result_tree.topLevelItem(product_index)]
            for recipe_index in range(product_item.childCount())
        ]
        self.assertTrue(
            any(
                item.text(0).endswith("制作")
                and re.fullmatch(r"\d{2,3}:\d{2}:\d{2}", item.text(3))
                for item in recipe_items
            )
        )
        self.assertTrue(
            any(
                item.text(0).endswith("兑换")
                and item.text(3).startswith(("限购", "不限购"))
                for item in recipe_items
            )
        )
        self.assertTrue(
            any(" · " in item.text(4) for item in recipe_items)
        )
        self.assertTrue(
            any(
                item.text(0).startswith(
                    (
                        "Prapor",
                        "Therapist",
                        "Skier",
                        "Peacekeeper",
                        "Mechanic",
                        "Ragman",
                        "Jaeger",
                        "Ref",
                    )
                )
                for item in recipe_items
            )
        )

        tracked_product = window.tracked_recipe_tree.topLevelItem(0)
        tracked_product.child(0).setSelected(True)
        window._delete_selected_tracked_recipes()
        self.assertEqual(config["tracked_recipe_ids"], [])
        window.hide()
        window.deleteLater()

    def test_bundled_snapshot_uses_game_handbook_paths(self) -> None:
        catalog = RecipeCatalog()
        records = catalog.records("regular")

        self.assertGreaterEqual(len(catalog.handbook_categories), 80)
        self.assertEqual(sum(bool(catalog.category_path(record)) for record in records), 1019)
        unlocks = [record for record in records if record.get("task_unlock")]
        self.assertEqual(len(unlocks), 104)
        self.assertTrue(
            all(isinstance(record.get("unlock_task"), dict) for record in unlocks)
        )

    def test_interface_font_setting_applies_live(self) -> None:
        config = deepcopy(DEFAULT_CONFIG)
        config["ui_font_size"] = 15
        dialog = SettingsDialog(config)

        self.assertEqual(dialog.ui_font_size.value(), 15)
        dialog.ui_font_size.setValue(17)
        self.assertEqual(dialog.values()["ui_font_size"], 17)
        apply_app_theme(self.app, 17)
        self.assertEqual(self.app.font().pointSize(), 17)

        apply_app_theme(self.app, int(DEFAULT_CONFIG["ui_font_size"]))
        dialog.close()

    def test_recipe_tree_font_and_spacing_scale_live(self) -> None:
        apply_app_theme(self.app, 11)
        config = deepcopy(DEFAULT_CONFIG)
        config["enabled_features"] = ["recipe_tracking"]
        config["feature_setup_complete"] = True
        with patch("app.gui.load_config", return_value=config):
            window = _RecipeSmokeWindow()

        window.show()
        self.app.processEvents()
        apply_app_theme(self.app, 17)
        window._sync_recipe_tree_fonts()
        window._populate_recipe_tree()
        self.app.processEvents()

        for tree in (
            window.recipe_category_tree,
            window.recipe_result_tree,
            window.tracked_recipe_tree,
        ):
            item = tree.topLevelItem(0)
            self.assertEqual(tree.font().pointSize(), 17)
            self.assertGreaterEqual(
                tree.visualItemRect(item).height(),
                round(tree.fontMetrics().height() * 1.4),
            )
        self.assertEqual(
            window.recipe_result_tree.topLevelItem(0).font(0).pointSize(), 17
        )

        window.hide()
        window.deleteLater()
        apply_app_theme(self.app, int(DEFAULT_CONFIG["ui_font_size"]))

    def test_feature_switch_rebuilds_main_ui_without_restart(self) -> None:
        config = deepcopy(DEFAULT_CONFIG)
        config["enabled_features"] = ["price_lookup"]
        config["feature_setup_complete"] = True
        with patch("app.gui.load_config", return_value=config):
            window = _RecipeSmokeWindow()

        previous = window._enabled_features().copy()
        config["enabled_features"] = ["recipe_tracking"]
        window._apply_runtime_feature_configuration(previous)
        self.app.processEvents()

        self.assertIsNone(window.price_client)
        self.assertIsNotNone(window.recipe_catalog)
        self.assertTrue(hasattr(window, "recipe_category_tree"))
        self.assertFalse(hasattr(window, "price_mode_combo"))
        self.assertEqual(
            [title for title, _builder in window._panel_defs],
            ["数据", "关注配方"],
        )
        window.hide()
        window.deleteLater()

    def test_recipe_column_width_and_log_state_are_remembered(self) -> None:
        config = deepcopy(DEFAULT_CONFIG)
        config["enabled_features"] = ["recipe_tracking"]
        config["feature_setup_complete"] = True
        config["recipe_result_column_widths"] = [520, 72, 96, 130, 300]
        with patch("app.gui.load_config", return_value=config):
            window = _RecipeSmokeWindow()

        self.assertEqual(window.recipe_result_tree.columnWidth(0), 520)
        window.recipe_result_tree.setColumnWidth(1, 92)
        self.app.processEvents()
        self.assertEqual(config["recipe_result_column_widths"][1], 92)

        window._set_main_log_collapsed(True)
        self.assertTrue(config["main_log_collapsed"])
        self.assertFalse(window.log.isVisible())
        window._set_main_log_collapsed(False)
        self.assertFalse(config["main_log_collapsed"])
        window.hide()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
