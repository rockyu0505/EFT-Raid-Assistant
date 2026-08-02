from __future__ import annotations

import json
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import APP_DIR, RESOURCE_DIR


MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_INPUT_BYTES = 25 * 1024 * 1024
DEBUG_SUFFIXES = {".json", ".log", ".png", ".txt"}
SENSITIVE_KEY_PARTS = ("password", "secret", "access_token", "api_token")


def create_diagnostic_bundle(
    destination: Path,
    config: dict[str, Any],
    *,
    app_dir: Path = APP_DIR,
    resource_dir: Path = RESOURCE_DIR,
) -> Path:
    """Create a bounded support bundle without changing application data."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": _read_version(resource_dir),
        "python": sys.version,
        "platform": platform.platform(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "app_dir": str(app_dir),
        "resource_dir": str(resource_dir),
        "config": _sanitized_config(config),
        "resources": {
            "recipes": (resource_dir / "data" / "recipes.json").exists(),
            "aliases": (resource_dir / "data" / "item_aliases_zh.json").exists(),
            "price_cache_seed": (resource_dir / "cache").exists(),
        },
    }

    debug_files = _recent_debug_files(app_dir / "debug")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostic_summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2),
        )
        total_bytes = 0
        for source in debug_files:
            size = source.stat().st_size
            if size > MAX_FILE_BYTES or total_bytes + size > MAX_BUNDLE_INPUT_BYTES:
                continue
            archive.write(source, f"debug/{source.name}")
            total_bytes += size
    return destination


def _read_version(resource_dir: Path) -> str:
    path = resource_dir / "VERSION"
    try:
        return path.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _sanitized_config(config: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in config.items():
        normalized = key.casefold()
        if any(part in normalized for part in SENSITIVE_KEY_PARTS):
            result[key] = "<redacted>"
        elif key == "tracked_recipe_ids" and isinstance(value, list):
            result["tracked_recipe_count"] = len(value)
        else:
            result[key] = value
    return result


def _recent_debug_files(debug_dir: Path) -> list[Path]:
    if not debug_dir.exists():
        return []
    candidates = [
        path
        for path in debug_dir.iterdir()
        if path.is_file() and path.suffix.casefold() in DEBUG_SUFFIXES
    ]
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)
