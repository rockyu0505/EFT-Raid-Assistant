from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

from app.models import TRADERS


CONFIG_VERSION = 2


def resolve_app_directories(
    *,
    frozen: bool,
    executable: str | Path,
    module_file: str | Path,
    bundle_dir: str | Path | None = None,
) -> tuple[Path, Path]:
    if frozen:
        writable_dir = Path(executable).resolve().parent
        resource_dir = Path(bundle_dir).resolve() if bundle_dir else writable_dir
        return writable_dir, resource_dir
    project_dir = Path(module_file).resolve().parent.parent
    return project_dir, project_dir


APP_DIR, RESOURCE_DIR = resolve_app_directories(
    frozen=bool(getattr(sys, "frozen", False)),
    executable=sys.executable,
    module_file=__file__,
    bundle_dir=getattr(sys, "_MEIPASS", None),
)
if os.environ.get("EFT_APP_DATA_DIR"):
    APP_DIR = Path(os.environ["EFT_APP_DATA_DIR"]).resolve()
CONFIG_PATH = APP_DIR / "config.json"


FEATURE_DEFINITIONS: dict[str, str] = {
    "price_lookup": "局内查价",
    "trader_reminders": "商人补货（Beta）",
    "hideout": "藏身处记录（Beta）",
    "display_filter": "画面增强 / Gamma（Beta）",
    "recipe_tracking": "关注制作/兑换配方",
}
DEFAULT_ENABLED_FEATURES = ["price_lookup"]


REMOVED_CONFIG_KEYS = {
    "display_filter_next_hotkey",
    "item_ocr_engine",
    "item_ocr_language",
    "reminder_overlay_seconds",
    "schedule_hotkey",
    "tesseract_cmd",
}


DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "enabled_features": DEFAULT_ENABLED_FEATURES.copy(),
    "feature_setup_complete": False,
    "selected_traders": TRADERS.copy(),
    "capture_hotkey": "F8",
    "item_lookup_hotkey": "Q",
    "hideout_scan_hotkey": "F6",
    "reminder_hold_hotkey": "F7",
    "raid_panel_hotkey": "F9",
    "raid_log_hotkey": "F10",
    "display_filter_restore_hotkey": "Ctrl+F9",
    "capture_mode": "Auto",
    "manual_resolution_enabled": False,
    "manual_width": 2048,
    "manual_height": 1152,
    "roi_base": [0, 150, 1500, 240],
    "item_roi_base": [670, 120, 1420, 260],
    "item_capture_mode": "Hover tooltip",
    "hover_tooltip_offset": [12, -60],
    "hover_tooltip_size": [360, 110],
    "hover_search_margins": [560, 560, 240, 45],
    "hover_name_padding": [10, 8, 10, 8],
    "tooltip_cursor_bottom_gap": 20,
    "tooltip_cursor_gap_tolerance": 36,
    "tooltip_cursor_reference_height": 2160,
    "hover_wait_ms": 0,
    "button_capture_delay_seconds": 0,
    "inventory_tab_roi_base": [105, 0, 235, 48],
    "price_game_mode_default": "pve",
    "state_detection_cache_seconds": 2,
    "require_tarkov_foreground": True,
    "price_overlay_enabled": True,
    "price_overlay_seconds": 10,
    "close_to_tray": True,
    "ui_font_size": 11,
    "item_display_language": "zh",
    "price_value_basis": "slot",
    "firearm_value_color": "#8FA35A",
    "firearm_value_accent": "#6F7F3A",
    "price_value_tiers": [
        {"label": "白", "min": 0, "max": 10000, "color": "#F2F2F2"},
        {"label": "绿", "min": 10000, "max": 20000, "color": "#36D27F"},
        {"label": "蓝", "min": 20000, "max": 50000, "color": "#5DA8FF"},
        {"label": "紫", "min": 50000, "max": 100000, "color": "#B47CFF"},
        {"label": "金", "min": 100000, "max": 250000, "color": "#F2C14E"},
        {"label": "红", "min": 250000, "max": 500000, "color": "#FF5A5F"},
        {
            "label": "彩",
            "min": 500000,
            "max": None,
            "color": "#FF4FD8",
            "accent": "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF3B5C, stop:0.2 #FFB000, stop:0.4 #45D483, stop:0.6 #46B7FF, stop:0.8 #9B72FF, stop:1 #FF4FD8)",
        },
    ],
    "require_inventory_check": True,
    "refresh_prices_on_startup": True,
    "lead_time_seconds": 10,
    "repeat_alert_seconds": 0,
    "feedback_overlay_seconds": 6,
    "raid_panel_opacity": 84,
    "raid_log_opacity": 72,
    "raid_log_max_lines": 200,
    "tracked_recipe_ids": [],
    "recipe_overlay_accent_color": "#E8C47A",
    "sound_enabled": True,
    "popup_enabled": True,
    "performance_mode_enabled": True,
    "performance_log_max_lines": 600,
    "performance_gc_after_worker": True,
    "performance_cleanup_interval_seconds": 60,
    "performance_max_concurrent_workers": 2,
    "performance_skip_auto_price_refresh": False,
    "price_cache_stale_hours": 24,
    "main_window_geometry": [],
    "main_log_height": 170,
    "main_log_collapsed": False,
    "recipe_result_column_widths": [430, 58, 80, 115, 260],
    "tracked_recipe_column_widths": [430, 58, 80, 115, 260],
    "recipe_expanded_categories": [],
    "recipe_category_expansion_initialized": False,
    "raid_panel_position": [],
    "raid_log_position": [],
    "display_filter_restore_on_exit": True,
    "display_filter_eye_care_enabled": True,
    "display_filter_eye_care_check_seconds": 2,
    "display_filter_active_preset": "",
    "display_filter_presets": [
        {
            "name": "Indoor Lift",
            "description": "暗处提亮，保留亮部余量",
            "gamma": 0.78,
            "black_lift": 0.08,
            "gain": 0.96,
            "contrast": 1.03,
            "hotkey": "",
        },
        {
            "name": "Night Soft",
            "description": "夜图和室内更柔和的暗部抬升",
            "gamma": 0.68,
            "black_lift": 0.13,
            "gain": 0.92,
            "contrast": 0.98,
            "hotkey": "",
        },
        {
            "name": "Outdoor Guard",
            "description": "轻度提暗，压住天空和雪地过曝",
            "gamma": 0.88,
            "black_lift": 0.04,
            "gain": 0.90,
            "contrast": 1.06,
            "hotkey": "",
        },
    ],
}


def load_config() -> dict[str, Any]:
    """Load config.json, merging it onto defaults so new keys are harmless."""
    if not CONFIG_PATH.exists():
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)

    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_CONFIG)

    migrated = _migrate_config(data)
    merged = copy.deepcopy(DEFAULT_CONFIG)
    merged.update(migrated)
    merged["enabled_features"] = _clean_enabled_features(merged.get("enabled_features"))
    for key in REMOVED_CONFIG_KEYS:
        merged.pop(key, None)
    return merged


def save_config(config: dict[str, Any]) -> None:
    """Persist user settings to config.json in the project directory."""
    cleaned = {key: value for key, value in config.items() if key not in REMOVED_CONFIG_KEYS}
    cleaned["config_version"] = CONFIG_VERSION
    cleaned["enabled_features"] = _clean_enabled_features(cleaned.get("enabled_features"))
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = CONFIG_PATH.with_suffix(f"{CONFIG_PATH.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(CONFIG_PATH)


def _clean_enabled_features(value: object) -> list[str]:
    if not isinstance(value, list):
        return DEFAULT_ENABLED_FEATURES.copy()
    return [str(item) for item in value if str(item) in FEATURE_DEFINITIONS]


def _migrate_config(value: dict[str, Any]) -> dict[str, Any]:
    migrated = copy.deepcopy(value)
    try:
        version = int(migrated.get("config_version", 0))
    except (TypeError, ValueError):
        version = 0
    if version < 2:
        # Older builds skipped startup cache checks indefinitely in performance mode.
        migrated["performance_skip_auto_price_refresh"] = False
    migrated["config_version"] = CONFIG_VERSION
    return migrated
