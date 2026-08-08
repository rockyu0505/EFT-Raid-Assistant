from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.config as config_module
from app.config import (
    CONFIG_VERSION,
    DEFAULT_CONFIG,
    HOVER_SEARCH_MARGINS,
    INITIAL_TARKOV_1_1_HOVER_SEARCH_MARGINS,
    INVENTORY_TAB_ROI_BASE,
    LEGACY_HOVER_SEARCH_MARGINS,
    LEGACY_INVENTORY_TAB_ROI_BASE,
    inventory_tab_roi_candidates,
    load_config,
    resolve_app_directories,
    save_config,
)


class ConfigTests(unittest.TestCase):
    def test_fee_profile_defaults_are_unconfigured_player_levels(self) -> None:
        self.assertEqual(DEFAULT_CONFIG["flea_intelligence_center_level"], 0)
        self.assertEqual(DEFAULT_CONFIG["flea_hideout_management_level"], 0)

    def test_directory_resolution_separates_portable_data_and_frozen_resources(self) -> None:
        writable, resources = resolve_app_directories(
            frozen=True,
            executable=Path("C:/Portable/EFT Raid Assistant/EFT Raid Assistant.exe"),
            module_file=Path("C:/unused/app/config.py"),
            bundle_dir=Path("C:/Temp/_MEI123"),
        )

        self.assertEqual(writable, Path("C:/Portable/EFT Raid Assistant").resolve())
        self.assertEqual(resources, Path("C:/Temp/_MEI123").resolve())

    def test_old_config_migrates_stale_cache_policy_and_saves_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "config_version": 1,
                        "enabled_features": ["price_lookup"],
                        "performance_gc_after_worker": True,
                        "performance_skip_auto_price_refresh": True,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(config_module, "CONFIG_PATH", path):
                loaded = load_config()
                save_config(loaded)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["config_version"], CONFIG_VERSION)
            self.assertFalse(loaded["smart_price_enabled"])
            self.assertFalse(loaded["performance_skip_auto_price_refresh"])
            self.assertEqual(loaded["inventory_tab_roi_base"], list(INVENTORY_TAB_ROI_BASE))
            self.assertEqual(loaded["performance_ocr_threads"], 2)
            self.assertTrue(loaded["performance_price_timing_logs"])
            self.assertNotIn("performance_gc_after_worker", loaded)
            self.assertEqual(saved["config_version"], CONFIG_VERSION)
            self.assertNotIn("performance_gc_after_worker", saved)
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_version_3_config_migrates_the_legacy_inventory_tab_roi(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "config_version": 3,
                        "inventory_tab_roi_base": list(LEGACY_INVENTORY_TAB_ROI_BASE),
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(config_module, "CONFIG_PATH", path):
                loaded = load_config()

        self.assertEqual(loaded["inventory_tab_roi_base"], list(INVENTORY_TAB_ROI_BASE))

    def test_version_4_config_expands_the_legacy_hover_search_below_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "config_version": 4,
                        "hover_search_margins": list(LEGACY_HOVER_SEARCH_MARGINS),
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(config_module, "CONFIG_PATH", path):
                loaded = load_config()

        self.assertEqual(loaded["hover_search_margins"], list(HOVER_SEARCH_MARGINS))
        self.assertEqual(loaded["tooltip_max_width"], 640)

    def test_version_6_config_expands_the_4k_hover_search_to_the_full_tooltip_width(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "config_version": 6,
                        "hover_search_margins": list(
                            INITIAL_TARKOV_1_1_HOVER_SEARCH_MARGINS
                        ),
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(config_module, "CONFIG_PATH", path):
                loaded = load_config()

        self.assertEqual(loaded["hover_search_margins"], list(HOVER_SEARCH_MARGINS))
        self.assertEqual(loaded["tooltip_max_width"], 640)

    def test_inventory_tab_roi_candidates_preserve_custom_and_legacy_fallbacks(self) -> None:
        custom = (200, 1, 300, 40)

        self.assertEqual(
            inventory_tab_roi_candidates(custom),
            [custom, INVENTORY_TAB_ROI_BASE, LEGACY_INVENTORY_TAB_ROI_BASE],
        )

    def test_version_3_config_preserves_a_custom_inventory_tab_roi(self) -> None:
        custom = [200, 1, 300, 40]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "config_version": 3,
                        "inventory_tab_roi_base": custom,
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(config_module, "CONFIG_PATH", path):
                loaded = load_config()

        self.assertEqual(loaded["inventory_tab_roi_base"], custom)


if __name__ == "__main__":
    unittest.main()
