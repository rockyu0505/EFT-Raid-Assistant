from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from app.update_ui import UpdateCoordinator
from app.updater import UPDATER_EXE_NAME, UpdateCheckResult


class UpdatePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_startup_check_only_runs_in_packaged_non_smoke_build(self) -> None:
        with patch.object(sys, "frozen", True, create=True), patch.dict(
            os.environ,
            {"EFT_SMOKE_TEST": "0"},
        ):
            self.assertTrue(UpdateCoordinator._startup_check_supported())

        with patch.object(sys, "frozen", True, create=True), patch.dict(
            os.environ,
            {"EFT_SMOKE_TEST": "1"},
        ):
            self.assertFalse(UpdateCoordinator._startup_check_supported())

        had_frozen = hasattr(sys, "frozen")
        frozen_value = getattr(sys, "frozen", None)
        try:
            if had_frozen:
                delattr(sys, "frozen")
            with patch.dict(os.environ, {"EFT_SMOKE_TEST": "0"}):
                self.assertFalse(UpdateCoordinator._startup_check_supported())
        finally:
            if had_frozen:
                setattr(sys, "frozen", frozen_value)

    def test_automatic_apply_requires_packaged_windows_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(sys, "frozen", True, create=True), patch(
                "app.update_ui.os.name",
                "nt",
            ), patch("app.update_ui.APP_DIR", root):
                self.assertFalse(UpdateCoordinator._automatic_apply_supported())
                (root / UPDATER_EXE_NAME).write_bytes(b"helper")
                self.assertTrue(UpdateCoordinator._automatic_apply_supported())

    def test_missing_manifest_dialog_is_informational_and_hides_raw_404(self) -> None:
        parent = QWidget()
        logs: list[str] = []
        coordinator = UpdateCoordinator({}, parent, log=logs.append)
        result = UpdateCheckResult(
            current_version="0.8.0-dev",
            error="当前发布渠道尚未提供自动更新清单。",
            manifest_unavailable=True,
        )
        with patch.object(QMessageBox, "information") as information:
            coordinator._on_check_finished(result, interactive=True)
        information.assert_called_once()
        title = information.call_args.args[1]
        message = information.call_args.args[2]
        self.assertEqual(title, "检查更新")
        self.assertIn("0.8.0-dev", message)
        self.assertIn("尚未提供自动更新清单", message)
        self.assertNotIn("HTTP", message)
        self.assertNotIn("https://", message)
        self.assertTrue(logs)


if __name__ == "__main__":
    unittest.main()
