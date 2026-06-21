from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


TRADERS: list[str] = [
    "Prapor",
    "Therapist",
    "Fence",
    "Skier",
    "Peacekeeper",
    "Mechanic",
    "Ragman",
    "Jaeger",
    "Arena Ref",
]


@dataclass(frozen=True)
class CaptureResult:
    image_path: str
    crop_path: str
    size: tuple[int, int]
    region_name: str


@dataclass
class TraderReminder:
    trader: str
    restock_at: datetime
    notify_at: datetime
    repeat_seconds: int = 0
    last_triggered_at: datetime | None = None
    triggered: bool = False


@dataclass(frozen=True)
class ParsedOcr:
    raw_text: str
    timers: list[str]
    variant_name: str


@dataclass(frozen=True)
class ParsedItemName:
    raw_text: str
    candidates: list[str]
    variant_name: str


@dataclass(frozen=True)
class ItemPrice:
    game_mode: str
    name: str
    short_name: str
    matched_name: str
    confidence: float
    last_low_price: int | None
    avg_24h_price: int | None
    base_price: int | None
    best_vendor_name: str | None
    best_vendor_price: int | None
    best_vendor_currency: str | None
    wiki_link: str | None
    updated: str | None
