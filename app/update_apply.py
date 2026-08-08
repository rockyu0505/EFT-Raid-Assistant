from __future__ import annotations

import json
import os
import shutil
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from app.updater import (
    APP_NAME,
    UPDATE_RESULT_FILENAME,
    UpdateError,
    normalize_version,
    sha256_file,
    verify_update_archive,
)


PRESERVED_ROOT_NAMES = {
    "config.json",
    "cache",
    "data",
    "debug",
    ".update-cache",
    UPDATE_RESULT_FILENAME,
}


def apply_update(
    package_path: Path,
    install_dir: Path,
    *,
    expected_version: str,
    expected_sha256: str,
) -> None:
    package_path = Path(package_path).resolve()
    install_dir = _validate_install_dir(Path(install_dir))
    expected_version = normalize_version(expected_version)
    expected_sha256 = str(expected_sha256).strip().casefold()
    if not package_path.is_file():
        raise UpdateError(f"更新包不存在：{package_path}")
    if sha256_file(package_path) != expected_sha256:
        raise UpdateError("更新助手复核 SHA-256 失败。")
    verify_update_archive(package_path, expected_version=expected_version)

    token = uuid.uuid4().hex
    staging_dir = install_dir / f".update-staging-{token}"
    backup_dir = install_dir / f".update-backup-{token}"
    installed_paths: list[Path] = []
    moved_backups: list[tuple[Path, Path]] = []
    try:
        staging_dir.mkdir(parents=False, exist_ok=False)
        _extract_archive(package_path, staging_dir)
        source_root = staging_dir / APP_NAME
        if not source_root.is_dir():
            raise UpdateError(f"更新包缺少顶层目录：{APP_NAME}")
        source_children = sorted(source_root.iterdir(), key=lambda path: path.name.casefold())
        if not source_children:
            raise UpdateError("更新包顶层目录为空。")
        forbidden = sorted(
            child.name for child in source_children if child.name in PRESERVED_ROOT_NAMES
        )
        if forbidden:
            raise UpdateError(f"更新包试图覆盖用户数据：{forbidden}")

        backup_dir.mkdir(parents=False, exist_ok=False)
        for source in source_children:
            destination = install_dir / source.name
            if destination.exists():
                backup = backup_dir / source.name
                _move_path(destination, backup)
                moved_backups.append((backup, destination))

        for source in source_children:
            destination = install_dir / source.name
            _move_path(source, destination)
            installed_paths.append(destination)
    except Exception as exc:
        rollback_errors: list[str] = []
        for path in reversed(installed_paths):
            try:
                _remove_path(path, install_dir)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        for backup, destination in reversed(moved_backups):
            try:
                if backup.exists():
                    _move_path(backup, destination)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        detail = f"更新失败，已回滚：{exc}"
        if rollback_errors:
            detail += f"；回滚警告：{rollback_errors[-1]}"
        raise UpdateError(detail) from exc
    finally:
        _best_effort_remove(staging_dir, install_dir)

    _best_effort_remove(backup_dir, install_dir)
    _cleanup_download(package_path, install_dir)


def write_update_result(
    install_dir: Path,
    *,
    success: bool,
    version: str,
    message: str,
) -> None:
    install_dir = Path(install_dir).resolve()
    path = install_dir / UPDATE_RESULT_FILENAME
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    payload = {
        "success": bool(success),
        "version": str(version),
        "message": str(message),
    }
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _validate_install_dir(path: Path) -> Path:
    resolved = path.resolve()
    if resolved == Path(resolved.anchor) or not resolved.parent.exists():
        raise UpdateError(f"安装目录不安全：{resolved}")
    if not (resolved / f"{APP_NAME}.exe").is_file():
        raise UpdateError(f"安装目录缺少主程序：{resolved}")
    return resolved


def _extract_archive(package_path: Path, staging_dir: Path) -> None:
    try:
        with zipfile.ZipFile(package_path) as archive:
            for info in archive.infolist():
                relative = _safe_member_path(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise UpdateError(f"更新包不允许符号链接：{info.filename}")
                destination = staging_dir.joinpath(*relative.parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"无法解压更新包：{exc}") from exc


def _safe_member_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise UpdateError(f"更新包包含不安全路径：{value}")
    if path.parts[0] != APP_NAME:
        raise UpdateError(f"更新包包含意外顶层路径：{value}")
    return path


def _move_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def _remove_path(path: Path, install_dir: Path) -> None:
    resolved = path.resolve()
    root = install_dir.resolve()
    if resolved == root or root not in resolved.parents:
        raise OSError(f"拒绝删除安装目录之外的路径：{resolved}")
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _best_effort_remove(path: Path, install_dir: Path) -> None:
    try:
        if path.exists():
            _remove_path(path, install_dir)
    except OSError:
        pass


def _cleanup_download(package_path: Path, install_dir: Path) -> None:
    try:
        cache_root = (install_dir / ".update-cache").resolve()
        resolved_package = package_path.resolve()
        if cache_root not in resolved_package.parents:
            return
        checksum_path = package_path.with_suffix(f"{package_path.suffix}.sha256")
        package_path.unlink(missing_ok=True)
        checksum_path.unlink(missing_ok=True)
        current = package_path.parent
        while current != cache_root.parent and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            if current == cache_root:
                break
            current = current.parent
    except OSError:
        pass
