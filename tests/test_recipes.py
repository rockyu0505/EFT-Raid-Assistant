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
from app.gui import MainWindow, _build_price_view
from app.recipes import RecipeCatalog, recipe_search_text


class _RecipeSmokeWindow(MainWindow):
    def _reset_run_log(self) -> None:
        pass

    def _build_tray_icon(self) -> None:
        pass

    def _register_hotkeys(self) -> None:
        pass

    def _apply_performance_settings(self) -> None:
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
            "category": "弹药",
            "source": "工作台",
            "level": 2,
            "product": {"id": "product", "name": "测试弹药", "count": 60},
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
                    "schema_version": 1,
                    "generated_at": "2026-08-01T00:00:00Z",
                    "source": "test",
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
        self.assertIn("需此物品 ×2", lines[0])
        self.assertIn("物品等级≥15", lines[0])
        self.assertIn("需可用状态", lines[0])

    def test_search_text_contains_product_source_and_requirement(self) -> None:
        record = RecipeCatalog(self.path).records("regular")[0]
        search_text = recipe_search_text(record)

        self.assertIn("测试弹药", search_text)
        self.assertIn("工作台", search_text)
        self.assertIn("火药", search_text)

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
            recipe_lines=["测试弹药 ×60 · 制作 · 工作台 Lv2 · 需此物品 ×2"],
        )

        self.assertIn("关注配方", view.detail)
        self.assertIn("测试弹药", view.label_html)
        self.assertIn("关注配方", view.log_text)

    def test_main_window_builds_bundled_recipe_tree(self) -> None:
        config = deepcopy(DEFAULT_CONFIG)
        config["enabled_features"] = ["recipe_tracking"]
        config["feature_setup_complete"] = True
        with patch("app.gui.load_config", return_value=config):
            window = _RecipeSmokeWindow()

        self.assertIsNotNone(window.recipe_catalog)
        self.assertEqual(window.recipe_catalog.record_count("pve"), 1020)
        self.assertGreater(window.recipe_tree.topLevelItemCount(), 0)
        self.assertIn("共 1020 个配方", window.recipe_summary_label.text())
        window.hide()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
