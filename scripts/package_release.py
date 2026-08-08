from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import zipfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_NAME = "EFT Raid Assistant"
UPDATER_NAME = f"{APP_NAME} Updater.exe"
SEED_CACHE_FILES = (
    "tarkov_items_regular.json",
    "tarkov_items_pve.json",
    "tarkov_items_pvp-season.json",
    "hideout_requirements_zh.json",
)
PUBLIC_FILES = (
    "RELEASE_README_zh.txt",
    "DEVELOPMENT.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "VERSION",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a verified portable package.")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    version = (PROJECT_DIR / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError("VERSION is empty")

    build_dir = PROJECT_DIR / "build"
    dist_dir = PROJECT_DIR / "dist"
    release_dir = PROJECT_DIR / "release"
    seed_dir = build_dir / "release-cache"
    app_dir = dist_dir / APP_NAME
    updater_dist_dir = build_dir / "updater-dist"
    updater_work_dir = build_dir / "updater-work"

    if not args.skip_build:
        _remove_tree(build_dir)
        _remove_tree(dist_dir)
        seed_dir.mkdir(parents=True)
        for name in SEED_CACHE_FILES:
            source = PROJECT_DIR / "cache" / name
            if not source.exists():
                raise RuntimeError(f"Required release cache is missing: {source}")
            shutil.copy2(source, seed_dir / name)

    if not args.skip_tests:
        _run([sys.executable, "-m", "compileall", "-q", "-f", "app", "main.py"])
        _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
        smoke_env = dict(os.environ)
        smoke_env["QT_QPA_PLATFORM"] = "offscreen"
        smoke_env["EFT_SMOKE_TEST"] = "1"
        smoke_env["EFT_APP_DATA_DIR"] = str(build_dir / "source-smoke-data")
        _run([sys.executable, "main.py", "--smoke-test"], env=smoke_env, timeout=45)

    if not args.skip_build:
        build_env = dict(os.environ)
        build_env["EFT_RELEASE_CACHE_DIR"] = str(seed_dir)
        _run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--clean",
                "--noconfirm",
                "EFT Raid Assistant.spec",
            ],
            env=build_env,
            timeout=900,
        )
        _run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--clean",
                "--noconfirm",
                "--distpath",
                str(updater_dist_dir),
                "--workpath",
                str(updater_work_dir),
                "EFT Raid Assistant Updater.spec",
            ],
            timeout=420,
        )
        updater_exe = updater_dist_dir / UPDATER_NAME
        if not updater_exe.is_file():
            raise RuntimeError(f"Packaged updater is missing: {updater_exe}")
        shutil.copy2(updater_exe, app_dir / UPDATER_NAME)

    if not (app_dir / f"{APP_NAME}.exe").exists():
        raise RuntimeError(f"Packaged executable is missing: {app_dir}")
    if not (app_dir / UPDATER_NAME).exists():
        raise RuntimeError(f"Packaged updater is missing: {app_dir / UPDATER_NAME}")

    for name in PUBLIC_FILES:
        shutil.copy2(PROJECT_DIR / name, app_dir / name)

    packaged_env = dict(os.environ)
    packaged_env["QT_QPA_PLATFORM"] = "offscreen"
    packaged_env["EFT_SMOKE_TEST"] = "1"
    packaged_env["EFT_APP_DATA_DIR"] = str(build_dir / "packaged-smoke-data")
    _run(
        [str(app_dir / UPDATER_NAME), "--help"],
        cwd=app_dir,
        timeout=60,
    )
    _run(
        [str(app_dir / f"{APP_NAME}.exe"), "--ocr-smoke-test"],
        cwd=app_dir,
        env=packaged_env,
        timeout=180,
    )
    _run(
        [str(app_dir / f"{APP_NAME}.exe"), "--display-smoke-test"],
        cwd=app_dir,
        env=packaged_env,
        timeout=60,
    )
    _run(
        [str(app_dir / f"{APP_NAME}.exe"), "--smoke-test"],
        cwd=app_dir,
        env=packaged_env,
        timeout=180,
    )
    _remove_path(app_dir / "config.json")
    _remove_tree(app_dir / "debug")

    release_dir.mkdir(exist_ok=True)
    archive_path = release_dir / f"EFT-Raid-Assistant-{version}-win64.zip"
    _remove_path(archive_path)
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for source in sorted(app_dir.rglob("*")):
            if source.is_file():
                archive.write(source, source.relative_to(dist_dir))

    verification = _verify_archive(archive_path)
    digest = _sha256(archive_path)
    checksum_path = archive_path.with_suffix(f"{archive_path.suffix}.sha256")
    checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8")
    manifest_path = release_dir / "update-manifest.json"
    manifest_path.write_text(
        json.dumps(
            _build_update_manifest(
                version=version,
                archive_path=archive_path,
                checksum_path=checksum_path,
                digest=digest,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "version": version,
                "archive": str(archive_path),
                "size_bytes": archive_path.stat().st_size,
                "sha256": digest,
                "manifest": str(manifest_path),
                "verification": verification,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _run(
    command: list[str],
    *,
    cwd: Path = PROJECT_DIR,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> None:
    subprocess.run(command, cwd=cwd, env=env, timeout=timeout, check=True)


def _verify_archive(path: Path) -> dict[str, int]:
    with zipfile.ZipFile(path) as archive:
        names = {name.replace("\\", "/") for name in archive.namelist()}
    prefix = f"{APP_NAME}/"
    required = {
        f"{prefix}{APP_NAME}.exe",
        f"{prefix}{UPDATER_NAME}",
        f"{prefix}RELEASE_README_zh.txt",
        f"{prefix}DEVELOPMENT.md",
        f"{prefix}LICENSE",
        f"{prefix}THIRD_PARTY_NOTICES.md",
        f"{prefix}VERSION",
        f"{prefix}_internal/data/recipes.json",
        f"{prefix}_internal/data/item_aliases_zh.json",
        f"{prefix}_internal/assets/app_icon.ico",
        f"{prefix}_internal/cache/tarkov_items_regular.json",
        f"{prefix}_internal/cache/tarkov_items_pve.json",
        f"{prefix}_internal/cache/tarkov_items_pvp-season.json",
        f"{prefix}_internal/cache/hideout_requirements_zh.json",
    }
    missing = sorted(required - names)
    if missing:
        raise RuntimeError(f"Archive is missing required files: {missing}")
    forbidden = [
        name
        for name in names
        if name.casefold().endswith("/config.json")
        or "/debug/" in name.casefold()
    ]
    if forbidden:
        raise RuntimeError(f"Archive contains runtime leftovers: {forbidden}")
    if not any(name.startswith(f"{prefix}_internal/") for name in names):
        raise RuntimeError("Archive does not contain the _internal runtime")
    return {"entries": len(names), "required": len(required), "forbidden": 0}


def _build_update_manifest(
    *,
    version: str,
    archive_path: Path,
    checksum_path: Path,
    digest: str,
) -> dict[str, object]:
    tag = f"v{version}"
    release_root = (
        "https://github.com/rockyu0505/EFT-Raid-Assistant/releases/download/"
        f"{urllib.parse.quote(tag, safe='')}"
    )
    mirror_bases = [
        value.strip().rstrip("/")
        for value in os.environ.get("EFT_UPDATE_MIRROR_BASE_URLS", "").split(";")
        if value.strip()
    ]

    def urls_for(name: str) -> list[str]:
        quoted = urllib.parse.quote(name, safe="")
        return [f"{base}/{quoted}" for base in mirror_bases] + [
            f"{release_root}/{quoted}"
        ]

    return {
        "schema_version": 1,
        "version": version,
        "title": f"EFT Raid Assistant {version}",
        "notes": _release_notes(version),
        "release_page": (
            "https://github.com/rockyu0505/EFT-Raid-Assistant/releases/tag/"
            f"{urllib.parse.quote(tag, safe='')}"
        ),
        "assets": {
            "package": {
                "name": archive_path.name,
                "size": archive_path.stat().st_size,
                "sha256": digest,
                "urls": urls_for(archive_path.name),
            },
            "checksum": {
                "name": checksum_path.name,
                "size": checksum_path.stat().st_size,
                "urls": urls_for(checksum_path.name),
            },
        },
    }


def _release_notes(version: str) -> str:
    changelog_path = PROJECT_DIR / "CHANGELOG.md"
    try:
        lines = changelog_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    candidates = {version, version.split("-", 1)[0]}
    start = -1
    for index, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        heading = line[3:].strip()
        if any(heading == candidate or heading.startswith(f"{candidate} ") for candidate in candidates):
            start = index + 1
            break
    if start < 0:
        return ""
    collected: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _remove_tree(path: Path) -> None:
    _assert_project_child(path)
    if path.exists():
        shutil.rmtree(path)


def _remove_path(path: Path) -> None:
    _assert_project_child(path)
    if path.exists():
        path.unlink()


def _assert_project_child(path: Path) -> None:
    resolved = path.resolve()
    if resolved == PROJECT_DIR or PROJECT_DIR not in resolved.parents:
        raise RuntimeError(f"Refusing to remove path outside project outputs: {resolved}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
