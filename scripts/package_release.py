from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_NAME = "EFT Raid Assistant"
SEED_CACHE_FILES = (
    "tarkov_items_regular.json",
    "tarkov_items_pve.json",
    "hideout_requirements_zh.json",
)
PUBLIC_FILES = (
    "RELEASE_README_zh.txt",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "VERSION",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a verified portable dev package.")
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

    if not (app_dir / f"{APP_NAME}.exe").exists():
        raise RuntimeError(f"Packaged executable is missing: {app_dir}")

    for name in PUBLIC_FILES:
        shutil.copy2(PROJECT_DIR / name, app_dir / name)

    packaged_env = dict(os.environ)
    packaged_env["QT_QPA_PLATFORM"] = "offscreen"
    packaged_env["EFT_SMOKE_TEST"] = "1"
    packaged_env["EFT_APP_DATA_DIR"] = str(build_dir / "packaged-smoke-data")
    _run(
        [str(app_dir / f"{APP_NAME}.exe"), "--ocr-smoke-test"],
        cwd=app_dir,
        env=packaged_env,
        timeout=180,
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
    print(
        json.dumps(
            {
                "version": version,
                "archive": str(archive_path),
                "size_bytes": archive_path.stat().st_size,
                "sha256": digest,
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
        f"{prefix}RELEASE_README_zh.txt",
        f"{prefix}LICENSE",
        f"{prefix}THIRD_PARTY_NOTICES.md",
        f"{prefix}VERSION",
        f"{prefix}_internal/data/recipes.json",
        f"{prefix}_internal/data/item_aliases_zh.json",
        f"{prefix}_internal/assets/app_icon.ico",
        f"{prefix}_internal/cache/tarkov_items_regular.json",
        f"{prefix}_internal/cache/tarkov_items_pve.json",
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
