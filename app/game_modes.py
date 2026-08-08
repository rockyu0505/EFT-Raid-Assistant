from __future__ import annotations


REGULAR_GAME_MODE = "regular"
PVE_GAME_MODE = "pve"
SEASONAL_GAME_MODE = "pvp-season"

GAME_MODES = (REGULAR_GAME_MODE, PVE_GAME_MODE, SEASONAL_GAME_MODE)
GRAPHQL_GAME_MODES = (REGULAR_GAME_MODE, PVE_GAME_MODE)

GAME_MODE_CHOICES = (
    ("PvE", PVE_GAME_MODE),
    ("PvP", REGULAR_GAME_MODE),
    ("赛季服", SEASONAL_GAME_MODE),
)


def normalize_game_mode(value: object) -> str:
    normalized = str(value or "").strip().casefold().replace("_", "-")
    if normalized in {"pve", "pvemode", "pve-mode"}:
        return PVE_GAME_MODE
    if normalized in {
        "pvp-season",
        "pvpseason",
        "season",
        "seasonal",
        "season-mode",
        "seasonal-mode",
    }:
        return SEASONAL_GAME_MODE
    return REGULAR_GAME_MODE


def game_mode_label(value: object) -> str:
    mode = normalize_game_mode(value)
    if mode == PVE_GAME_MODE:
        return "PvE"
    if mode == SEASONAL_GAME_MODE:
        return "赛季服"
    return "PvP"
