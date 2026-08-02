from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.diagnostics import create_diagnostic_bundle


class DiagnosticBundleTests(unittest.TestCase):
    def test_bundle_contains_summary_and_recent_debug_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            resource_dir = root / "resources"
            debug_dir = app_dir / "debug"
            debug_dir.mkdir(parents=True)
            resource_dir.mkdir(parents=True)
            (resource_dir / "VERSION").write_text("0.7.0-dev\n", encoding="utf-8")
            (debug_dir / "latest_run.log").write_text("hello", encoding="utf-8")
            destination = root / "diagnostics.zip"

            create_diagnostic_bundle(
                destination,
                {
                    "api_token": "do-not-export",
                    "tracked_recipe_ids": ["a", "b"],
                    "ui_font_size": 12,
                },
                app_dir=app_dir,
                resource_dir=resource_dir,
            )

            with zipfile.ZipFile(destination) as archive:
                self.assertIn("diagnostic_summary.json", archive.namelist())
                self.assertIn("debug/latest_run.log", archive.namelist())
                summary = json.loads(archive.read("diagnostic_summary.json"))

            self.assertEqual(summary["version"], "0.7.0-dev")
            self.assertEqual(summary["config"]["api_token"], "<redacted>")
            self.assertEqual(summary["config"]["tracked_recipe_count"], 2)
            self.assertNotIn("tracked_recipe_ids", summary["config"])


if __name__ == "__main__":
    unittest.main()
