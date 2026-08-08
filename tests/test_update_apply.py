from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app.update_apply as update_apply
from app.update_apply import apply_update
from app.updater import APP_NAME, UPDATER_EXE_NAME, UpdateError


def _create_install(root: Path) -> None:
    (root / f"{APP_NAME}.exe").write_bytes(b"old exe")
    (root / UPDATER_EXE_NAME).write_bytes(b"old updater")
    (root / "VERSION").write_text("0.7.2\n", encoding="utf-8")
    (root / "_internal").mkdir()
    (root / "_internal" / "old.bin").write_bytes(b"old runtime")
    (root / "config.json").write_text('{"keep": true}', encoding="utf-8")
    for directory in ("cache", "data", "debug"):
        path = root / directory
        path.mkdir()
        (path / "user.txt").write_text(directory, encoding="utf-8")


def _create_package(path: Path, *, traversal: bool = False) -> str:
    prefix = f"{APP_NAME}/"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{prefix}{APP_NAME}.exe", b"new exe")
        archive.writestr(f"{prefix}{UPDATER_EXE_NAME}", b"new updater")
        archive.writestr(f"{prefix}VERSION", "0.8.0\n")
        archive.writestr(f"{prefix}_internal/new.bin", b"new runtime")
        if traversal:
            archive.writestr(f"{prefix}../outside.txt", b"bad")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ApplyUpdateTests(unittest.TestCase):
    def test_update_replaces_runtime_and_preserves_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            install = Path(temporary) / APP_NAME
            install.mkdir()
            _create_install(install)
            package_dir = install / ".update-cache" / "0.8.0"
            package_dir.mkdir(parents=True)
            package = package_dir / "EFT-Raid-Assistant-0.8.0-win64.zip"
            digest = _create_package(package)

            apply_update(
                package,
                install,
                expected_version="0.8.0",
                expected_sha256=digest,
            )

            self.assertEqual((install / f"{APP_NAME}.exe").read_bytes(), b"new exe")
            self.assertFalse((install / "_internal" / "old.bin").exists())
            self.assertEqual((install / "_internal" / "new.bin").read_bytes(), b"new runtime")
            self.assertEqual((install / "VERSION").read_text(encoding="utf-8"), "0.8.0\n")
            self.assertTrue((install / "config.json").is_file())
            for directory in ("cache", "data", "debug"):
                self.assertTrue((install / directory / "user.txt").is_file())
            self.assertFalse(package.exists())
            self.assertFalse(list(install.glob(".update-backup-*")))

    def test_copy_failure_rolls_back_old_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            install = Path(temporary) / APP_NAME
            install.mkdir()
            _create_install(install)
            package = Path(temporary) / "update.zip"
            digest = _create_package(package)
            original_move = update_apply._move_path

            def fail_new_runtime(source: Path, destination: Path) -> None:
                if ".update-staging-" in str(source) and source.name == "_internal":
                    raise OSError("simulated copy failure")
                original_move(source, destination)

            with patch("app.update_apply._move_path", side_effect=fail_new_runtime):
                with self.assertRaises(UpdateError):
                    apply_update(
                        package,
                        install,
                        expected_version="0.8.0",
                        expected_sha256=digest,
                    )

            self.assertEqual((install / f"{APP_NAME}.exe").read_bytes(), b"old exe")
            self.assertEqual((install / "VERSION").read_text(encoding="utf-8"), "0.7.2\n")
            self.assertTrue((install / "_internal" / "old.bin").is_file())
            self.assertTrue((install / "config.json").is_file())

    def test_traversal_archive_is_rejected_before_install_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            install = Path(temporary) / APP_NAME
            install.mkdir()
            _create_install(install)
            package = Path(temporary) / "bad.zip"
            digest = _create_package(package, traversal=True)
            with self.assertRaises(UpdateError):
                apply_update(
                    package,
                    install,
                    expected_version="0.8.0",
                    expected_sha256=digest,
                )
            self.assertEqual((install / f"{APP_NAME}.exe").read_bytes(), b"old exe")


if __name__ == "__main__":
    unittest.main()
