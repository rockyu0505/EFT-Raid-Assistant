from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.config import APP_DIR


TARKOV_DEV_GRAPHQL = "https://api.tarkov.dev/graphql"
HIDEOUT_CACHE_PATH = APP_DIR / "cache" / "hideout_requirements_zh.json"
HIDEOUT_PROGRESS_PATH = APP_DIR / "data" / "hideout_progress.json"

HIDEOUT_QUERY = """
query HideoutRequirements($lang: LanguageCode, $gameMode: GameMode) {
  hideoutStations(lang: $lang, gameMode: $gameMode) {
    id
    name
    normalizedName
    levels {
      id
      level
      constructionTime
      itemRequirements {
        count
        quantity
        item {
          id
          name
          shortName
          normalizedName
          avg24hPrice
          basePrice
          width
          height
        }
      }
    }
  }
}
"""

GAME_ITEM_ORDER_OVERRIDES: dict[tuple[str, int], list[int]] = {
    # tarkov.dev's itemRequirements order is not always the same as the in-game row.
    # These indices reorder API rows into the observed in-game left-to-right order.
    ("water-collector", 3): [3, 0, 1, 2],
    ("bitcoin-farm", 2): [2, 0, 4, 3, 1],
}


@dataclass(frozen=True)
class HideoutQuantity:
    owned: int
    required: int


@dataclass(frozen=True)
class HideoutScan:
    raw_text: str
    station_name: str | None
    current_level: int | None
    quantities: list[HideoutQuantity]
    variant_name: str
    target_level: int | None = None


class HideoutDataError(RuntimeError):
    pass


class HideoutTracker:
    def __init__(
        self,
        endpoint: str = TARKOV_DEV_GRAPHQL,
        cache_path: Path = HIDEOUT_CACHE_PATH,
        progress_path: Path = HIDEOUT_PROGRESS_PATH,
    ) -> None:
        self.endpoint = endpoint
        self.cache_path = cache_path
        self.progress_path = progress_path
        self._stations: list[dict[str, Any]] = []
        self._progress: dict[str, Any] = {"stations": {}}
        self._load_requirements()
        self._load_progress()

    def station_names(self) -> list[str]:
        self.ensure_requirements()
        return [str(station.get("name") or "") for station in self._stations]

    def ensure_requirements(self) -> None:
        if not self._stations:
            self.refresh_requirements()

    def refresh_requirements(self) -> int:
        payload = json.dumps(
            {
                "query": HIDEOUT_QUERY,
                "variables": {"lang": "zh", "gameMode": "pve"},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "EFT-Raid-Assistant-Hideout/0.5",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise HideoutDataError(f"藏身处 API 请求失败：{exc}") from exc

        if data.get("errors"):
            raise HideoutDataError(f"藏身处 API 返回错误：{data['errors']}")
        stations = data.get("data", {}).get("hideoutStations")
        if not isinstance(stations, list):
            raise HideoutDataError("藏身处 API 响应中没有设施列表。")

        self._stations = [station for station in stations if isinstance(station, dict)]
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(
                {
                    "fetched_at": time.time(),
                    "lang": "zh",
                    "game_mode": "pve",
                    "stations": self._stations,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return len(self._stations)

    def record_scan(self, scan: HideoutScan) -> dict[str, Any]:
        self.ensure_requirements()
        station = self._match_station(scan.station_name, scan.raw_text)
        inferred_target_level = scan.target_level
        if station is None:
            requirement_match = self._match_station_by_requirements(scan)
            if requirement_match is not None:
                station, inferred_target_level = requirement_match
        if station is None:
            raise HideoutDataError("没有识别到可匹配的藏身处设施名称。")

        target_level = inferred_target_level or self._infer_target_level(station, scan)
        if target_level is None:
            raise HideoutDataError("没有识别到可用的设施等级或需求数量。")

        target = _station_level(station, target_level)
        if target is None:
            raise HideoutDataError(f"{station.get('name')} 没有等级 {target_level} 数据。")

        current_level = max(0, target_level - 1)
        if scan.current_level is not None:
            current_level = max(0, scan.current_level)

        item_rows: list[dict[str, Any]] = []
        item_reqs = _game_ordered_item_requirements(station, target)
        expected_counts = [
            _as_int(requirement.get("count")) or _as_int(requirement.get("quantity")) or 0
            for requirement in item_reqs
        ]
        aligned_quantities = _align_quantities(scan.quantities, expected_counts)
        for index, requirement in enumerate(item_reqs):
            item = requirement.get("item") or {}
            required = _as_int(requirement.get("count")) or _as_int(requirement.get("quantity")) or 0
            quantity = aligned_quantities[index] if index < len(aligned_quantities) else None
            owned = quantity.owned if quantity is not None else None
            remaining = max(0, required - owned) if owned is not None else required
            item_rows.append(
                {
                    "order": index,
                    "item_id": str(item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "short_name": str(item.get("shortName") or ""),
                    "normalized_name": str(item.get("normalizedName") or ""),
                    "owned": owned,
                    "required": required,
                    "remaining": remaining,
                }
            )

        station_id = str(station.get("id") or "")
        record = {
            "station_id": station_id,
            "station_name": str(station.get("name") or ""),
            "station_normalized_name": str(station.get("normalizedName") or ""),
            "current_level": current_level,
            "target_level": target_level,
            "max_level": _max_station_level(station),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ocr_variant": scan.variant_name,
            "recognized_station": scan.station_name or "",
            "recognized_current_level": scan.current_level,
            "recognized_quantity_count": sum(1 for quantity in aligned_quantities if quantity is not None),
            "raw_quantity_count": len(scan.quantities),
            "expected_quantity_count": len(item_reqs),
            "items": item_rows,
        }
        self._progress.setdefault("stations", {})[station_id] = record
        self._save_progress()
        return record

    def records(self) -> list[dict[str, Any]]:
        stations = self._progress.get("stations")
        if not isinstance(stations, dict):
            return []
        return [record for record in stations.values() if isinstance(record, dict)]

    def item_demand_lines(self, item_id: str) -> list[str]:
        if not item_id:
            return []
        if not self._stations:
            return []
        lines: list[str] = []
        total_remaining = 0
        for record in sorted(self.records(), key=lambda value: str(value.get("station_name") or "")):
            demand = self._item_demand_for_record(record, item_id)
            if demand is None:
                continue
            total_remaining += int(demand["remaining_to_max"])
            station_name = str(record.get("station_name") or "")
            current_level = _as_int(record.get("current_level")) or 0
            target_level = _as_int(record.get("target_level")) or current_level + 1
            owned = demand.get("owned")
            current_required = int(demand["current_required"])
            remaining_to_max = int(demand["remaining_to_max"])
            if current_required > 0:
                owned_text = "?" if owned is None else str(owned)
                lines.append(
                    f"{station_name} L{current_level}->L{target_level}: "
                    f"{owned_text}/{current_required}，满级还需 {remaining_to_max}"
                )
            else:
                lines.append(f"{station_name}: 当前无需求，满级还需 {remaining_to_max}")
        if lines:
            lines.append(f"已记录设施总计：满级还需 {total_remaining}")
        return lines

    def _item_demand_for_record(
        self,
        record: dict[str, Any],
        item_id: str,
    ) -> dict[str, Any] | None:
        station = self._station_by_id(str(record.get("station_id") or ""))
        if station is None:
            return None
        target_level = _as_int(record.get("target_level")) or 0
        if target_level <= 0:
            return None
        current_required = 0
        owned: int | None = None
        current_remaining = 0
        for item in record.get("items") or []:
            if not isinstance(item, dict) or str(item.get("item_id") or "") != item_id:
                continue
            current_required = _as_int(item.get("required")) or 0
            owned = _as_int(item.get("owned"))
            current_remaining = _as_int(item.get("remaining")) or current_required
            break

        future_required = 0
        for level in station.get("levels") or []:
            level_number = _as_int(level.get("level"))
            if level_number is None or level_number < target_level:
                continue
            if level_number == target_level:
                continue
            for requirement in level.get("itemRequirements") or []:
                item = requirement.get("item") or {}
                if str(item.get("id") or "") == item_id:
                    future_required += _as_int(requirement.get("count")) or 0

        remaining_to_max = current_remaining + future_required
        if current_required <= 0 and remaining_to_max <= 0:
            return None
        return {
            "owned": owned,
            "current_required": current_required,
            "current_remaining": current_remaining,
            "remaining_to_max": remaining_to_max,
        }

    def _match_station(self, candidate: str | None, raw_text: str) -> dict[str, Any] | None:
        if candidate:
            direct = self._station_by_name(candidate)
            if direct is not None:
                return direct
        normalized_text = _normalize_text(raw_text)
        for station in self._stations:
            station_name = str(station.get("name") or "")
            key = _normalize_text(station_name)
            if key and key in normalized_text:
                return station

        best_score = 0.0
        best_station: dict[str, Any] | None = None
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        for station in self._stations:
            station_name = str(station.get("name") or "")
            station_key = _normalize_text(station_name)
            for line in lines:
                line_key = _normalize_text(line)
                score = SequenceMatcher(None, station_key, line_key).ratio()
                if score > best_score:
                    best_score = score
                    best_station = station
        return best_station if best_score >= 0.58 else None

    def _match_station_by_requirements(
        self,
        scan: HideoutScan,
    ) -> tuple[dict[str, Any], int] | None:
        observed = [quantity.required for quantity in scan.quantities]
        if not observed:
            return None
        best_station: dict[str, Any] | None = None
        best_level: int | None = None
        best_score = -10**9
        best_exact = 0
        for station in self._stations:
            for level in station.get("levels") or []:
                item_reqs = _game_ordered_item_requirements(station, level)
                expected = [_as_int(requirement.get("count")) or 0 for requirement in item_reqs]
                if not expected:
                    continue
                score, exact = _ordered_sequence_score(observed, expected)
                if score > best_score:
                    best_score = score
                    best_exact = exact
                    best_station = station
                    best_level = _as_int(level.get("level"))
        if best_station is None or best_level is None:
            return None
        if best_exact < 2 and best_score < 4:
            return None
        return best_station, best_level

    def _infer_target_level(
        self,
        station: dict[str, Any],
        scan: HideoutScan,
    ) -> int | None:
        required_counts = [quantity.required for quantity in scan.quantities]
        if required_counts:
            best_level: int | None = None
            best_score = -1
            for level in station.get("levels") or []:
                item_reqs = _game_ordered_item_requirements(station, level)
                expected = [
                    _as_int(requirement.get("count")) or 0
                    for requirement in item_reqs
                ]
                if not expected:
                    continue
                score, _ = _ordered_sequence_score(required_counts, expected)
                if score > best_score:
                    best_score = score
                    best_level = _as_int(level.get("level"))
            if best_level is not None and best_score >= max(1, min(len(required_counts), len(_station_level_requirements(station, best_level))) // 2):
                return best_level
        if scan.current_level is not None:
            return scan.current_level + 1
        return None

    def _station_by_name(self, name: str) -> dict[str, Any] | None:
        key = _normalize_text(name)
        for station in self._stations:
            if key == _normalize_text(str(station.get("name") or "")):
                return station
        return None

    def _station_by_id(self, station_id: str) -> dict[str, Any] | None:
        for station in self._stations:
            if str(station.get("id") or "") == station_id:
                return station
        return None

    def _load_requirements(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        stations = data.get("stations")
        if isinstance(stations, list):
            self._stations = [station for station in stations if isinstance(station, dict)]

    def _load_progress(self) -> None:
        if not self.progress_path.exists():
            return
        try:
            data = json.loads(self.progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            self._progress = data
            self._progress.setdefault("stations", {})

    def _save_progress(self) -> None:
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self._progress["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.progress_path.write_text(
            json.dumps(self._progress, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _station_level(station: dict[str, Any], level_number: int) -> dict[str, Any] | None:
    for level in station.get("levels") or []:
        if _as_int(level.get("level")) == level_number:
            return level
    return None


def _station_level_requirements(station: dict[str, Any], level_number: int) -> list[dict[str, Any]]:
    level = _station_level(station, level_number)
    if level is None:
        return []
    return _game_ordered_item_requirements(station, level)


def _game_ordered_item_requirements(
    station: dict[str, Any],
    level: dict[str, Any],
) -> list[dict[str, Any]]:
    requirements = [req for req in level.get("itemRequirements") or [] if isinstance(req, dict)]
    level_number = _as_int(level.get("level"))
    key = (str(station.get("normalizedName") or ""), level_number or 0)
    order = GAME_ITEM_ORDER_OVERRIDES.get(key)
    if not order or sorted(order) != list(range(len(requirements))):
        return requirements
    return [requirements[index] for index in order]


def _max_station_level(station: dict[str, Any]) -> int:
    levels = [_as_int(level.get("level")) or 0 for level in station.get("levels") or []]
    return max(levels) if levels else 0


def _sequence_score(observed: list[int], expected: list[int]) -> int:
    if not observed or not expected:
        return 0
    score = 0
    limit = min(len(observed), len(expected))
    for index in range(limit):
        if observed[index] == expected[index]:
            score += 2
        elif abs(observed[index] - expected[index]) <= 1:
            score += 1
    score -= abs(len(observed) - len(expected))
    return score


def _ordered_sequence_score(observed: list[int], expected: list[int]) -> tuple[int, int]:
    if not observed or not expected:
        return 0, 0
    rows = len(observed) + 1
    cols = len(expected) + 1
    scores = [[0 for _ in range(cols)] for _ in range(rows)]
    exacts = [[0 for _ in range(cols)] for _ in range(rows)]
    for i in range(1, rows):
        scores[i][0] = scores[i - 1][0] - 1
    for j in range(1, cols):
        scores[0][j] = scores[0][j - 1] - 1

    for i, observed_value in enumerate(observed, start=1):
        for j, expected_value in enumerate(expected, start=1):
            if observed_value == expected_value:
                match_score = 4
                exact_bonus = 1
            elif abs(observed_value - expected_value) <= 1:
                match_score = 1
                exact_bonus = 0
            else:
                match_score = -3
                exact_bonus = 0

            candidates = [
                (scores[i - 1][j] - 1, exacts[i - 1][j]),
                (scores[i][j - 1] - 1, exacts[i][j - 1]),
                (scores[i - 1][j - 1] + match_score, exacts[i - 1][j - 1] + exact_bonus),
            ]
            best_score, best_exact = max(candidates, key=lambda item: (item[0], item[1]))
            scores[i][j] = best_score
            exacts[i][j] = best_exact
    return scores[-1][-1], exacts[-1][-1]


def _align_quantities(
    quantities: list[HideoutQuantity],
    expected_counts: list[int],
) -> list[HideoutQuantity | None]:
    if not quantities or not expected_counts:
        return quantities
    rows = len(quantities) + 1
    cols = len(expected_counts) + 1
    scores = [[0 for _ in range(cols)] for _ in range(rows)]
    choices = [["" for _ in range(cols)] for _ in range(rows)]

    for i in range(1, rows):
        scores[i][0] = scores[i - 1][0] - 1
        choices[i][0] = "skip_observed"
    for j in range(1, cols):
        scores[0][j] = scores[0][j - 1] - 2
        choices[0][j] = "missing_expected"

    for i, quantity in enumerate(quantities, start=1):
        for j, expected in enumerate(expected_counts, start=1):
            candidates: list[tuple[int, str]] = [
                (scores[i - 1][j] - 1, "skip_observed"),
                (scores[i][j - 1] - 2, "missing_expected"),
            ]
            if quantity.required == expected:
                candidates.append((scores[i - 1][j - 1] + 6, "match"))
            elif abs(quantity.required - expected) <= 1:
                candidates.append((scores[i - 1][j - 1] + 2, "match"))

            best_score, best_choice = max(candidates, key=lambda item: item[0])
            scores[i][j] = best_score
            choices[i][j] = best_choice

    aligned: list[HideoutQuantity | None] = [None for _ in expected_counts]
    i = len(quantities)
    j = len(expected_counts)
    while i > 0 or j > 0:
        choice = choices[i][j]
        if choice == "match":
            aligned[j - 1] = quantities[i - 1]
            i -= 1
            j -= 1
        elif choice == "missing_expected":
            j -= 1
        else:
            i -= 1
    return aligned


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold())


def _as_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
