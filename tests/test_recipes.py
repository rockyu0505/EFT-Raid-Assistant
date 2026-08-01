from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.config import DEFAULT_CONFIG
from app.gui import MainWindow, PriceToast, _build_price_view
from app.recipes import RecipeCatalog, RecipeNotice, recipe_search_text


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
                    "tool": False,
                    "min_level": 15,
                    "functional": True,
                }
            ],
        }
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
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

        path = RecipeCatalog(self.path).category_path(record)
        self.assertEqual([category["name"] for category in path], ["弹药", "子弹"])

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
                    source_text="制作 · 工作台 Lv2",
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
        self.assertGreaterEqual(window.minimumWidth(), 1080)

        requirement_rows = [
            recipe_item.childCount()
            for product_index in range(window.recipe_result_tree.topLevelItemCount())
            for product_item in [window.recipe_result_tree.topLevelItem(product_index)]
            for recipe_index in range(product_item.childCount())
            for recipe_item in [product_item.child(recipe_index)]
        ]
        self.assertTrue(any(count > 0 for count in requirement_rows))

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


if __name__ == "__main__":
    unittest.main()
