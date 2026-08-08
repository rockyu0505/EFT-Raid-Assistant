from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from urllib.parse import urlsplit

from app.config import APP_DIR, RESOURCE_DIR


APP_NAME = "EFT Raid Assistant"
UPDATER_EXE_NAME = f"{APP_NAME} Updater.exe"
UPDATE_RESULT_FILENAME = ".update-result.json"
DEFAULT_UPDATE_MANIFEST_URL = (
    "https://github.com/rockyu0505/EFT-Raid-Assistant/"
    "releases/latest/download/update-manifest.json"
)
DEFAULT_RELEASE_PAGE = (
    "https://github.com/rockyu0505/EFT-Raid-Assistant/releases/latest"
)
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_CHECKSUM_BYTES = 64 * 1024
MAX_PACKAGE_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 50_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_VERSION_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    pass


class UpdateCancelled(UpdateError):
    pass


class UpdateManifestUnavailable(UpdateError):
    pass


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple[int | str, ...]


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    size: int
    urls: tuple[str, ...]
    sha256: str = ""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    title: str
    notes: str
    release_page: str
    package: ReleaseAsset
    checksum: ReleaseAsset
    source_url: str = ""


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    release: ReleaseInfo | None = None
    error: str = ""
    manifest_unavailable: bool = False

    @property
    def update_available(self) -> bool:
        return self.release is not None and is_version_newer(
            self.release.version,
            self.current_version,
        )


@dataclass(frozen=True)
class DownloadedUpdate:
    release: ReleaseInfo
    package_path: Path
    checksum_path: Path
    sha256: str


def parse_version(value: object) -> Version:
    text = str(value or "").strip()
    match = _VERSION_RE.fullmatch(text)
    if match is None:
        raise UpdateError(f"无法识别版本号：{text or '空值'}")
    identifiers: list[int | str] = []
    prerelease = match.group("prerelease")
    if prerelease:
        for identifier in prerelease.split("."):
            identifiers.append(int(identifier) if identifier.isdigit() else identifier.casefold())
    return Version(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        prerelease=tuple(identifiers),
    )


def normalize_version(value: object) -> str:
    parsed = parse_version(value)
    base = f"{parsed.major}.{parsed.minor}.{parsed.patch}"
    if parsed.prerelease:
        return f"{base}-" + ".".join(str(part) for part in parsed.prerelease)
    return base


def is_version_newer(candidate: object, current: object) -> bool:
    left = parse_version(candidate)
    right = parse_version(current)
    left_core = (left.major, left.minor, left.patch)
    right_core = (right.major, right.minor, right.patch)
    if left_core != right_core:
        return left_core > right_core
    if not left.prerelease:
        return bool(right.prerelease)
    if not right.prerelease:
        return False
    for left_part, right_part in zip(left.prerelease, right.prerelease):
        if left_part == right_part:
            continue
        if isinstance(left_part, int) and isinstance(right_part, str):
            return False
        if isinstance(left_part, str) and isinstance(right_part, int):
            return True
        return left_part > right_part
    return len(left.prerelease) > len(right.prerelease)


def read_current_version(resource_dir: Path = RESOURCE_DIR) -> str:
    path = Path(resource_dir) / "VERSION"
    try:
        return normalize_version(path.read_text(encoding="utf-8").strip())
    except OSError as exc:
        raise UpdateError(f"无法读取当前版本：{exc}") from exc


def configured_manifest_urls(value: object = None) -> tuple[str, ...]:
    urls: list[str] = []
    if isinstance(value, (list, tuple)):
        urls.extend(str(item).strip() for item in value if str(item).strip())
    override = os.environ.get("EFT_UPDATE_MANIFEST_URL", "").strip()
    if override:
        urls.insert(0, override)
    urls.append(DEFAULT_UPDATE_MANIFEST_URL)
    return tuple(dict.fromkeys(_validate_https_url(url) for url in urls))


def check_for_update(
    current_version: str,
    *,
    manifest_urls: Iterable[str] | None = None,
    timeout: float = 12,
) -> UpdateCheckResult:
    try:
        current = normalize_version(current_version)
        release = fetch_update_manifest(manifest_urls=manifest_urls, timeout=timeout)
        return UpdateCheckResult(current_version=current, release=release)
    except UpdateManifestUnavailable as exc:
        return UpdateCheckResult(
            current_version=str(current_version),
            error=str(exc),
            manifest_unavailable=True,
        )
    except UpdateError as exc:
        return UpdateCheckResult(current_version=str(current_version), error=str(exc))


def fetch_update_manifest(
    *,
    manifest_urls: Iterable[str] | None = None,
    timeout: float = 12,
) -> ReleaseInfo:
    urls = tuple(manifest_urls or configured_manifest_urls())
    if not urls:
        raise UpdateError("没有可用的更新清单地址。")
    errors: list[str] = []
    not_found_count = 0
    for raw_url in urls:
        try:
            url = _validate_https_url(raw_url)
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "EFT-Raid-Assistant-Updater",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload_bytes = response.read(MAX_MANIFEST_BYTES + 1)
            if len(payload_bytes) > MAX_MANIFEST_BYTES:
                raise UpdateError("更新清单超过允许大小。")
            payload = json.loads(payload_bytes.decode("utf-8"))
            return parse_update_manifest(payload, source_url=url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                not_found_count += 1
            errors.append(f"{raw_url}: HTTP {exc.code} {exc.reason}")
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            urllib.error.URLError,
            UpdateError,
        ) as exc:
            errors.append(f"{raw_url}: {exc}")
    if not_found_count == len(urls):
        raise UpdateManifestUnavailable("当前发布渠道尚未提供自动更新清单。")
    raise UpdateError("无法获取更新信息。" + (f"\n{errors[-1]}" if errors else ""))


def parse_update_manifest(payload: object, *, source_url: str = "") -> ReleaseInfo:
    if not isinstance(payload, dict):
        raise UpdateError("更新清单不是 JSON 对象。")
    try:
        schema_version = int(payload.get("schema_version", 0))
    except (TypeError, ValueError) as exc:
        raise UpdateError("更新清单 schema_version 无效。") from exc
    if schema_version != 1:
        raise UpdateError(f"不支持的更新清单版本：{schema_version}")
    version = normalize_version(payload.get("version"))
    assets = payload.get("assets")
    if not isinstance(assets, dict):
        raise UpdateError("更新清单缺少 assets。")
    package = _parse_asset(assets.get("package"), require_sha256=True)
    checksum = _parse_asset(assets.get("checksum"), require_sha256=False)
    expected_package_name = f"EFT-Raid-Assistant-{version}-win64.zip"
    if package.name != expected_package_name:
        raise UpdateError(
            f"更新包名称与版本不匹配：{package.name}，应为 {expected_package_name}"
        )
    if checksum.name != f"{package.name}.sha256":
        raise UpdateError("SHA-256 文件名与更新包不匹配。")
    title = str(payload.get("title", "")).strip() or f"EFT Raid Assistant {version}"
    notes = str(payload.get("notes", "")).strip()
    release_page = _validate_https_url(
        str(payload.get("release_page", "")).strip() or DEFAULT_RELEASE_PAGE
    )
    return ReleaseInfo(
        version=version,
        title=title,
        notes=notes,
        release_page=release_page,
        package=package,
        checksum=checksum,
        source_url=source_url,
    )


def download_update(
    release: ReleaseInfo,
    *,
    destination_root: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = 30,
) -> DownloadedUpdate:
    root = Path(destination_root or (APP_DIR / ".update-cache"))
    destination = root / release.version
    destination.mkdir(parents=True, exist_ok=True)
    checksum_path = destination / release.checksum.name
    package_path = destination / release.package.name

    _download_asset(
        release.checksum,
        checksum_path,
        cancel_event=cancel_event,
        timeout=timeout,
        max_bytes=MAX_CHECKSUM_BYTES,
    )
    expected_sha256 = _read_checksum(checksum_path, release.package.name)
    if expected_sha256 != release.package.sha256:
        raise UpdateError("更新清单与 SHA-256 文件给出的摘要不一致。")

    if not _existing_package_is_valid(
        package_path,
        expected_sha256,
        release.version,
    ):
        _ensure_download_space(destination, release.package.size)
        _download_asset(
            release.package,
            package_path,
            progress=progress,
            cancel_event=cancel_event,
            timeout=timeout,
            max_bytes=MAX_PACKAGE_BYTES,
        )
    actual_sha256 = sha256_file(package_path)
    if actual_sha256 != expected_sha256:
        package_path.unlink(missing_ok=True)
        raise UpdateError("更新包 SHA-256 校验失败，已删除损坏文件。")
    verify_update_archive(package_path, expected_version=release.version)
    if progress is not None:
        progress(release.package.size, release.package.size)
    return DownloadedUpdate(
        release=release,
        package_path=package_path,
        checksum_path=checksum_path,
        sha256=actual_sha256,
    )


def verify_update_archive(path: Path, *, expected_version: str) -> None:
    expected = normalize_version(expected_version)
    prefix = f"{APP_NAME}/"
    required = {
        f"{prefix}{APP_NAME}.exe",
        f"{prefix}{UPDATER_EXE_NAME}",
        f"{prefix}VERSION",
    }
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise UpdateError("更新包文件数量异常。")
            uncompressed_size = sum(max(0, info.file_size) for info in infos)
            if uncompressed_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise UpdateError("更新包解压后的总大小超出安全范围。")
            normalized_names = [info.filename.replace("\\", "/") for info in infos]
            names = set(normalized_names)
            if len({name.casefold() for name in normalized_names}) != len(normalized_names):
                raise UpdateError("更新包包含重复或大小写冲突的路径。")
            for name in normalized_names:
                _safe_archive_name(name)
            missing = required - names
            if missing:
                raise UpdateError(f"更新包缺少必要文件：{sorted(missing)}")
            if not any(name.startswith(f"{prefix}_internal/") for name in names):
                raise UpdateError("更新包缺少 _internal 运行目录。")
            version_text = archive.read(f"{prefix}VERSION").decode("utf-8").strip()
    except (OSError, KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"更新包结构无效：{exc}") from exc
    if normalize_version(version_text) != expected:
        raise UpdateError(
            f"更新包版本不匹配：{version_text or '空值'}，应为 {expected}"
        )


def launch_update_helper(
    downloaded: DownloadedUpdate,
    *,
    install_dir: Path = APP_DIR,
    executable: Path | None = None,
    helper_path: Path | None = None,
) -> subprocess.Popen[bytes]:
    if os.name != "nt":
        raise UpdateError("自动替换目前只支持 Windows。")
    install_dir = Path(install_dir).resolve()
    executable = Path(executable or sys.executable).resolve()
    helper_source = Path(helper_path or (install_dir / UPDATER_EXE_NAME)).resolve()
    if not helper_source.is_file():
        raise UpdateError(f"更新助手不存在：{helper_source}")
    if not executable.is_file():
        raise UpdateError(f"主程序不存在：{executable}")
    helper_dir = Path(tempfile.gettempdir()) / "EFTRaidAssistantUpdater"
    helper_dir.mkdir(parents=True, exist_ok=True)
    helper_copy = helper_dir / (
        f"EFT-Raid-Assistant-Updater-{downloaded.release.version}-{uuid.uuid4().hex}.exe"
    )
    shutil.copy2(helper_source, helper_copy)
    command = [
        str(helper_copy),
        "--package",
        str(downloaded.package_path),
        "--install-dir",
        str(install_dir),
        "--pid",
        str(os.getpid()),
        "--expected-version",
        downloaded.release.version,
        "--sha256",
        downloaded.sha256,
        "--restart-exe",
        str(executable),
    ]
    creation_flags = 0x00000008 | 0x00000200
    try:
        return subprocess.Popen(
            command,
            cwd=helper_dir,
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as exc:
        helper_copy.unlink(missing_ok=True)
        raise UpdateError(f"无法启动更新助手：{exc}") from exc


def read_update_result(app_dir: Path = APP_DIR) -> dict[str, object] | None:
    path = Path(app_dir) / UPDATE_RESULT_FILENAME
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            return {"success": False, "message": "更新结果文件过大，已忽略。"}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_asset(value: object, *, require_sha256: bool) -> ReleaseAsset:
    if not isinstance(value, dict):
        raise UpdateError("更新清单的附件结构无效。")
    name = str(value.get("name", "")).strip()
    if not name or Path(name).name != name:
        raise UpdateError("更新附件文件名无效。")
    try:
        size = int(value.get("size", 0))
    except (TypeError, ValueError) as exc:
        raise UpdateError(f"更新附件大小无效：{name}") from exc
    if size <= 0 or size > MAX_PACKAGE_BYTES:
        raise UpdateError(f"更新附件大小超出范围：{name}")
    raw_urls = value.get("urls")
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]
    if not isinstance(raw_urls, list) or not raw_urls:
        raise UpdateError(f"更新附件缺少下载地址：{name}")
    urls = tuple(dict.fromkeys(_validate_https_url(str(url)) for url in raw_urls))
    sha256 = str(value.get("sha256", "")).strip().casefold()
    if require_sha256 and not _SHA256_RE.fullmatch(sha256):
        raise UpdateError(f"更新附件缺少有效 SHA-256：{name}")
    if sha256 and not _SHA256_RE.fullmatch(sha256):
        raise UpdateError(f"更新附件 SHA-256 无效：{name}")
    return ReleaseAsset(name=name, size=size, urls=urls, sha256=sha256)


def _validate_https_url(value: str) -> str:
    url = str(value).strip()
    parts = urlsplit(url)
    if parts.scheme.casefold() != "https" or not parts.netloc:
        raise UpdateError(f"更新地址必须使用 HTTPS：{url or '空值'}")
    if parts.username or parts.password:
        raise UpdateError("更新地址不能包含用户名或密码。")
    return url


def _download_asset(
    asset: ReleaseAsset,
    target: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float,
    max_bytes: int,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part_path = target.with_suffix(f"{target.suffix}.part")
    errors: list[str] = []
    for url in asset.urls:
        try:
            _download_url(
                url,
                part_path,
                expected_size=asset.size,
                progress=progress,
                cancel_event=cancel_event,
                timeout=timeout,
                max_bytes=max_bytes,
            )
            os.replace(part_path, target)
            return
        except UpdateCancelled:
            raise
        except (OSError, urllib.error.URLError, UpdateError) as exc:
            errors.append(f"{url}: {exc}")
    raise UpdateError(
        f"下载失败：{asset.name}" + (f"\n{errors[-1]}" if errors else "")
    )


def _download_url(
    url: str,
    part_path: Path,
    *,
    expected_size: int,
    progress: Callable[[int, int], None] | None,
    cancel_event: threading.Event | None,
    timeout: float,
    max_bytes: int,
) -> None:
    resume_at = part_path.stat().st_size if part_path.exists() else 0
    if resume_at > expected_size or resume_at > max_bytes:
        part_path.unlink(missing_ok=True)
        resume_at = 0
    headers = {"User-Agent": "EFT-Raid-Assistant-Updater"}
    if resume_at:
        headers["Range"] = f"bytes={resume_at}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", response.getcode() or 200))
        if resume_at and status != 206:
            resume_at = 0
        mode = "ab" if resume_at and status == 206 else "wb"
        received = resume_at
        if progress is not None:
            progress(received, expected_size)
        with part_path.open(mode) as stream:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise UpdateCancelled("用户已取消下载。")
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                received += len(chunk)
                if received > max_bytes or received > expected_size:
                    raise UpdateError("下载数据超过清单声明大小。")
                stream.write(chunk)
                if progress is not None:
                    progress(received, expected_size)
    if received != expected_size:
        raise UpdateError(f"下载大小不完整：{received} / {expected_size}")


def _read_checksum(path: Path, package_name: str) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise UpdateError(f"无法读取 SHA-256 文件：{exc}") from exc
    parts = text.split()
    if not parts or not _SHA256_RE.fullmatch(parts[0].casefold()):
        raise UpdateError("SHA-256 文件内容无效。")
    if len(parts) >= 2 and parts[-1].lstrip("*") != package_name:
        raise UpdateError("SHA-256 文件指向了其他更新包。")
    return parts[0].casefold()


def _existing_package_is_valid(path: Path, sha256: str, version: str) -> bool:
    if not path.is_file():
        return False
    try:
        if sha256_file(path) != sha256:
            return False
        verify_update_archive(path, expected_version=version)
        return True
    except (OSError, UpdateError):
        return False


def _ensure_download_space(destination: Path, expected_size: int) -> None:
    free = shutil.disk_usage(destination).free
    required = expected_size + max(256 * 1024 * 1024, expected_size // 2)
    if free < required:
        raise UpdateError(
            f"磁盘空间不足：至少需要 {required // (1024 * 1024)} MB 可用空间。"
        )


def _safe_archive_name(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise UpdateError(f"更新包包含不安全路径：{value}")
    if path.parts[0] != APP_NAME:
        raise UpdateError(f"更新包包含意外顶层路径：{value}")
    for part in path.parts:
        if not part or part in {".", ".."} or ":" in part or "\x00" in part:
            raise UpdateError(f"更新包包含不安全路径：{value}")
        if part.rstrip(" .") != part:
            raise UpdateError(f"更新包包含 Windows 路径冲突：{value}")
    return path
