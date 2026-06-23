from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.models import TRADERS


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "selected_traders": TRADERS.copy(),
    "capture_hotkey": "F8",
    "item_lookup_hotkey": "Q",
    "schedule_hotkey": "F10",
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
    "item_ocr_engine": "rapidocr",
    "item_ocr_language": "chi_sim+eng",
    "inventory_tab_roi_base": [105, 0, 235, 48],
    "price_game_mode_default": "pve",
    "state_detection_cache_seconds": 2,
    "require_tarkov_foreground": True,
    "price_overlay_enabled": True,
    "price_overlay_seconds": 10,
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
    "sound_enabled": True,
    "popup_enabled": True,
    "tesseract_cmd": "",
}


def load_config() -> dict[str, Any]:
    """Load config.json, merging it onto defaults so new keys are harmless."""
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG.copy()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()

    merged = DEFAULT_CONFIG.copy()
    merged.update(data)
    return merged


def save_config(config: dict[str, Any]) -> None:
    """Persist user settings to config.json in the project directory."""
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
