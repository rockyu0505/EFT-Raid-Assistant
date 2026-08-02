from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.config as config_module
from app.config import CONFIG_VERSION, load_config, resolve_app_directories, save_config


class ConfigTests(unittest.TestCase):
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
            self.assertFalse(loaded["performance_skip_auto_price_refresh"])
            self.assertEqual(saved["config_version"], CONFIG_VERSION)
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
