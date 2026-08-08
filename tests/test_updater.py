from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.updater import (
    APP_NAME,
    UPDATER_EXE_NAME,
    ReleaseAsset,
    ReleaseInfo,
    UpdateError,
    check_for_update,
    download_update,
    is_version_newer,
    normalize_version,
    parse_update_manifest,
    verify_update_archive,
)
from scripts.package_release import _build_update_manifest


class _FakeResponse(io.BytesIO):
    def __init__(self, value: bytes, status: int = 200) -> None:
        super().__init__(value)
        self.status = status

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _package_bytes(version: str = "0.8.0") -> bytes:
    target = io.BytesIO()
    prefix = f"{APP_NAME}/"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{prefix}{APP_NAME}.exe", b"new exe")
        archive.writestr(f"{prefix}{UPDATER_EXE_NAME}", b"new updater")
        archive.writestr(f"{prefix}VERSION", f"{version}\n")
        archive.writestr(f"{prefix}_internal/runtime.bin", b"runtime")
    return target.getvalue()


class VersionTests(unittest.TestCase):
    def test_semantic_versions_order_release_and_prerelease(self) -> None:
        self.assertTrue(is_version_newer("0.8.0", "0.8.0-dev"))
        self.assertTrue(is_version_newer("0.8.0-rc.2", "0.8.0-rc.1"))
        self.assertTrue(is_version_newer("0.9.0", "0.8.99"))
        self.assertFalse(is_version_newer("0.7.2", "0.8.0-dev"))
        self.assertFalse(is_version_newer("0.8.0-dev", "0.8.0"))
        self.assertEqual(normalize_version("v0.8.0+build.4"), "0.8.0")

    def test_invalid_version_is_rejected(self) -> None:
        with self.assertRaises(UpdateError):
            normalize_version("0.8")


class ManifestTests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "version": "0.8.0",
            "title": "EFT Raid Assistant 0.8.0",
            "notes": "Changes",
            "release_page": "https://github.com/example/release",
            "assets": {
                "package": {
                    "name": "EFT-Raid-Assistant-0.8.0-win64.zip",
                    "size": 123,
                    "sha256": "a" * 64,
                    "urls": ["https://downloads.example/app.zip"],
                },
                "checksum": {
                    "name": "EFT-Raid-Assistant-0.8.0-win64.zip.sha256",
                    "size": 102,
                    "urls": ["https://downloads.example/app.zip.sha256"],
                },
            },
        }

    def test_manifest_parses_exact_assets_and_mirror_order(self) -> None:
        payload = self._payload()
        package = payload["assets"]["package"]  # type: ignore[index]
        package["urls"] = [  # type: ignore[index]
            "https://mirror.example/app.zip",
            "https://github.com/example/app.zip",
        ]
        release = parse_update_manifest(payload, source_url="https://manifest.example")
        self.assertEqual(release.version, "0.8.0")
        self.assertEqual(release.package.urls[0], "https://mirror.example/app.zip")
        self.assertEqual(release.source_url, "https://manifest.example")

    def test_manifest_rejects_http_and_mismatched_names(self) -> None:
        payload = self._payload()
        payload["release_page"] = "http://example.com/release"
        with self.assertRaises(UpdateError):
            parse_update_manifest(payload)

        payload = self._payload()
        payload["assets"]["package"]["name"] = "wrong.zip"  # type: ignore[index]
        with self.assertRaises(UpdateError):
            parse_update_manifest(payload)

    def test_check_result_only_offers_newer_version(self) -> None:
        with patch("app.updater.fetch_update_manifest") as fetch:
            fetch.return_value = parse_update_manifest(self._payload())
            self.assertTrue(check_for_update("0.7.2").update_available)
            self.assertFalse(check_for_update("0.8.0").update_available)

    def test_all_manifest_urls_returning_404_is_a_normal_unavailable_state(self) -> None:
        def not_found(request: object, timeout: float) -> None:
            del timeout
            raise urllib.error.HTTPError(
                request.full_url,  # type: ignore[attr-defined]
                404,
                "Not Found",
                {},
                None,
            )

        with patch("app.updater.urllib.request.urlopen", side_effect=not_found):
            result = check_for_update(
                "0.8.0-dev",
                manifest_urls=(
                    "https://mirror.example/update-manifest.json",
                    "https://github.example/update-manifest.json",
                ),
            )
        self.assertTrue(result.manifest_unavailable)
        self.assertFalse(result.update_available)
        self.assertNotIn("https://", result.error)

    def test_packaging_manifest_can_prepend_release_time_mirrors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            "os.environ",
            {"EFT_UPDATE_MIRROR_BASE_URLS": "https://cn.example/releases;https://backup.example"},
        ):
            archive = Path(temporary) / "EFT-Raid-Assistant-0.8.0-win64.zip"
            archive.write_bytes(b"archive")
            checksum = archive.with_suffix(f"{archive.suffix}.sha256")
            checksum.write_text("a" * 64 + f"  {archive.name}\n", encoding="utf-8")
            manifest = _build_update_manifest(
                version="0.8.0",
                archive_path=archive,
                checksum_path=checksum,
                digest="a" * 64,
            )
            package = manifest["assets"]["package"]  # type: ignore[index]
            urls = package["urls"]  # type: ignore[index]
            self.assertEqual(urls[0], f"https://cn.example/releases/{archive.name}")
            self.assertIn("github.com", urls[-1])


class DownloadTests(unittest.TestCase):
    def test_download_verifies_checksum_and_archive(self) -> None:
        package = _package_bytes()
        digest = hashlib.sha256(package).hexdigest()
        package_name = "EFT-Raid-Assistant-0.8.0-win64.zip"
        checksum = f"{digest}  {package_name}\n".encode()
        release = ReleaseInfo(
            version="0.8.0",
            title="0.8.0",
            notes="",
            release_page="https://example.com/release",
            package=ReleaseAsset(
                name=package_name,
                size=len(package),
                urls=("https://example.com/package",),
                sha256=digest,
            ),
            checksum=ReleaseAsset(
                name=f"{package_name}.sha256",
                size=len(checksum),
                urls=("https://example.com/checksum",),
            ),
        )

        def open_url(request: object, timeout: float) -> _FakeResponse:
            del timeout
            url = request.full_url  # type: ignore[attr-defined]
            return _FakeResponse(checksum if url.endswith("checksum") else package)

        with tempfile.TemporaryDirectory() as temporary, patch(
            "app.updater.urllib.request.urlopen",
            side_effect=open_url,
        ):
            downloaded = download_update(release, destination_root=Path(temporary))
            self.assertEqual(downloaded.sha256, digest)
            self.assertTrue(downloaded.package_path.is_file())
            verify_update_archive(downloaded.package_path, expected_version="0.8.0")

    def test_archive_rejects_version_mismatch_and_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.zip"
            path.write_bytes(_package_bytes("0.8.1"))
            with self.assertRaises(UpdateError):
                verify_update_archive(path, expected_version="0.8.0")

    def test_archive_rejects_unexpected_root_and_excessive_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("outside.txt", b"bad")
            with self.assertRaises(UpdateError):
                verify_update_archive(path, expected_version="0.8.0")

            path.write_bytes(_package_bytes())
            with patch("app.updater.MAX_ARCHIVE_UNCOMPRESSED_BYTES", 1):
                with self.assertRaises(UpdateError):
                    verify_update_archive(path, expected_version="0.8.0")

            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../outside", b"bad")
            with self.assertRaises(UpdateError):
                verify_update_archive(path, expected_version="0.8.0")


if __name__ == "__main__":
    unittest.main()
