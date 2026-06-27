from __future__ import annotations

import json
import re
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.config import APP_DIR
from app.models import HistoricalPriceSummary, ItemPrice


TARKOV_DEV_GRAPHQL = "https://api.tarkov.dev/graphql"
CACHE_DIR = APP_DIR / "cache"
LEGACY_ITEM_CACHE_PATH = CACHE_DIR / "tarkov_items.json"
DATA_DIR = APP_DIR / "data"
CHINESE_ALIASES_PATH = DATA_DIR / "item_aliases_zh.json"
GAME_MODES = ("regular", "pve")
_CJK_VARIANT_TRANSLATION = str.maketrans(
    {
        "\u8c93": "\u732b",
        "\u9ec3": "\u9ec4",
        "\u88fd": "\u5236",
        "\u5c4d": "\u5c38",
        "\u639b": "\u6302",
        "\u9ce5": "\u9e1f",
        "\u99ac": "\u9a6c",
        "\u9f8d": "\u9f99",
        "\u9f9c": "\u9f9f",
        "\u9f52": "\u9f7f",
        "\u8eca": "\u8f66",
        "\u96fb": "\u7535",
        "\u5f48": "\u5f39",
        "\u69cd": "\u67aa",
        "\u93e1": "\u955c",
        "\u982d": "\u5934",
        "\u8b77": "\u62a4",
        "\u9ad4": "\u4f53",
        "\u7d05": "\u7ea2",
        "\u85cd": "\u84dd",
        "\u7da0": "\u7eff",
        "\u88dd": "\u88c5",
        "\u5099": "\u5907",
        "\u8907": "\u590d",
    }
)

ITEMS_QUERY = """
query ItemPrices($gameMode: GameMode, $lang: LanguageCode) {
  items(gameMode: $gameMode, lang: $lang) {
    id
    name
    normalizedName
    shortName
    width
    height
    types
    lastLowPrice
    low24hPrice
    high24hPrice
    avg24hPrice
    changeLast48hPercent
    lastOfferCount
    basePrice
    wikiLink
    updated
    sellFor {
      price
      priceRUB
      source
      currency
      vendor {
        name
      }
    }
  }
}
"""

HISTORICAL_PRICES_QUERY = """
query HistoricalItemPrices($id: ID!, $gameMode: GameMode, $days: Int) {
  historicalItemPrices(id: $id, gameMode: $gameMode, days: $days) {
    price
    priceMin
    offerCount
    offerCountMin
    timestamp
  }
}
"""


class PriceLookupError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompletionEntry:
    display: str
    lookup: str
    tag: str
    tag_color: str
    tag_text_color: str = "#F5F7FA"


class TarkovPriceClient:
    def __init__(
        self,
        endpoint: str = TARKOV_DEV_GRAPHQL,
        cache_path: Path = LEGACY_ITEM_CACHE_PATH,
        aliases_path: Path = CHINESE_ALIASES_PATH,
    ) -> None:
        self.endpoint = endpoint
        self.legacy_cache_path = cache_path
        self.aliases_path = aliases_path
        self.current_game_mode = "regular"
        self._items_by_mode: dict[str, list[dict[str, Any]]] = {mode: [] for mode in GAME_MODES}
        self._fetched_at_by_mode: dict[str, float] = {mode: 0.0 for mode in GAME_MODES}
        self._search_index_by_mode: dict[str, dict[str, set[int]]] = {
            mode: {} for mode in GAME_MODES
        }
        self._name_lookup_by_mode: dict[str, dict[str, int]] = {mode: {} for mode in GAME_MODES}
        self._full_name_lookup_by_mode: dict[str, dict[str, int]] = {
            mode: {} for mode in GAME_MODES
        }
        self._lookup_cache: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}
        self._aliases: dict[str, str] = {}
        for mode in GAME_MODES:
            self._load_disk_cache(mode)
        self.reload_aliases()

    def set_game_mode(self, game_mode: str) -> str:
        self.current_game_mode = _normalize_game_mode(game_mode)
        self._load_disk_cache(self.current_game_mode)
        return self.current_game_mode

    def lookup(self, query: str, game_mode: str | None = None) -> ItemPrice:
        query = query.strip()
        if not query:
            raise PriceLookupError("物品名为空。")

        mode = _normalize_game_mode(game_mode or self.current_game_mode)
        items = self._get_items(mode)
        normalized_query = _normalize(query)
        cache_key = (mode, normalized_query)
        cached = self._lookup_cache.get(cache_key)
        if cached is not None:
            match, confidence = cached
        else:
            match, confidence = self._find_exact_full_name_match(query, items, mode)
            if match is None:
                match, confidence = self._find_exact_name_match(normalized_query, items, mode)
            if match is None:
                match, confidence = self._find_alias_match(normalized_query, items, normalized=True)
            if match is None:
                match, confidence = self._find_best_match(query, items, mode)
            if match is not None:
                self._lookup_cache[cache_key] = (match, confidence)
        if match is None:
            raise PriceLookupError(f"没有匹配到塔科夫物品：'{query}'。")

        return self._to_item_price(match, confidence, query, mode)

    def lookup_candidates(self, queries: list[str], game_mode: str | None = None) -> ItemPrice:
        candidates = _dedupe_query_candidates(queries)
        if not candidates:
            raise PriceLookupError("物品名为空。")

        mode = _normalize_game_mode(game_mode or self.current_game_mode)
        items = self._get_items(mode)
        ordered_candidates = sorted(candidates, key=_candidate_specificity_score, reverse=True)

        for query in ordered_candidates:
            match, confidence = self._find_exact_full_name_match(query, items, mode)
            if match is not None:
                return self._to_item_price(match, confidence, query, mode)

        for query in ordered_candidates:
            match, confidence = self._find_alias_match(_normalize(query), items, normalized=True)
            if match is not None:
                return self._to_item_price(match, confidence, query, mode)

        errors: list[str] = []
        for query in ordered_candidates:
            try:
                return self.lookup(query, mode)
            except PriceLookupError as exc:
                errors.append(str(exc))

        raise PriceLookupError(errors[0] if errors else "没有匹配到塔科夫物品。")

    def _to_item_price(
        self,
        match: dict[str, Any],
        confidence: float,
        query: str,
        mode: str,
    ) -> ItemPrice:
        best_vendor = _best_vendor_offer(match.get("sellFor") or [])
        avg_24h_price = _as_int(match.get("avg24hPrice"))
        width = _as_int(match.get("width"))
        height = _as_int(match.get("height"))
        slots = _item_slots(width, height)
        item_types = _item_types(match)
        is_firearm = _is_firearm_item(match, item_types)
        return ItemPrice(
            item_id=str(match.get("id") or ""),
            game_mode=mode,
            name=str(match.get("name") or ""),
            short_name=str(match.get("shortName") or ""),
            zh_name=str(match.get("zhName") or ""),
            zh_short_name=str(match.get("zhShortName") or ""),
            matched_name=query,
            confidence=min(confidence, 1.0),
            last_low_price=_as_int(match.get("lastLowPrice")),
            low_24h_price=_as_int(match.get("low24hPrice")),
            high_24h_price=_as_int(match.get("high24hPrice")),
            avg_24h_price=avg_24h_price,
            change_48h_percent=_as_float(match.get("changeLast48hPercent")),
            last_offer_count=_as_int(match.get("lastOfferCount")),
            base_price=_as_int(match.get("basePrice")),
            width=width,
            height=height,
            slots=slots,
            value_per_slot=_value_per_slot(avg_24h_price, slots),
            item_types=item_types,
            is_firearm=is_firearm,
            best_vendor_name=best_vendor[0],
            best_vendor_price=best_vendor[1],
            best_vendor_price_rub=best_vendor[2],
            best_vendor_currency=best_vendor[3],
            wiki_link=match.get("wikiLink"),
            updated=match.get("updated"),
        )

    def historical_price_summary(
        self,
        item_id: str,
        game_mode: str | None = None,
        days: int = 2,
        sample_limit: int = 5,
    ) -> HistoricalPriceSummary:
        item_id = item_id.strip()
        if not item_id:
            raise PriceLookupError("物品 ID 为空，无法查询历史价格。")
        mode = _normalize_game_mode(game_mode or self.current_game_mode)
        points = self._fetch_historical_prices(item_id, mode, days)
        usable = [point for point in points if _as_int(point.get("price")) is not None]
        recent = usable[-max(1, sample_limit):]
        prices = [_as_int(point.get("price")) for point in recent]
        clean_prices = [price for price in prices if price is not None]
        median_price = round(statistics.median(clean_prices)) if clean_prices else None
        all_prices = [_as_int(point.get("price")) for point in usable]
        clean_all_prices = [price for price in all_prices if price is not None]
        latest = recent[-1] if recent else (usable[-1] if usable else {})
        return HistoricalPriceSummary(
            item_id=item_id,
            game_mode=mode,
            median_price=median_price,
            sample_count=len(clean_prices),
            latest_price=_as_int(latest.get("price")) if isinstance(latest, dict) else None,
            latest_min_price=_as_int(latest.get("priceMin")) if isinstance(latest, dict) else None,
            latest_offer_count=_as_int(latest.get("offerCount")) if isinstance(latest, dict) else None,
            low_price=min(clean_all_prices) if clean_all_prices else None,
            high_price=max(clean_all_prices) if clean_all_prices else None,
            days=days,
        )

    def refresh_items(self, game_mode: str | None = None) -> int:
        mode = _normalize_game_mode(game_mode or self.current_game_mode)
        items = self._fetch_items(mode, "en")
        zh_items = self._fetch_items(mode, "zh")
        items = _merge_localized_items(items, zh_items)
        self._items_by_mode[mode] = items
        self._fetched_at_by_mode[mode] = time.time()
        self._build_search_index(mode)
        self._lookup_cache.clear()
        self._write_disk_cache(mode, items)
        return len(items)

    def refresh_all_modes(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for mode in GAME_MODES:
            counts[mode] = self.refresh_items(mode)
        return counts

    def cache_status(self) -> str:
        parts: list[str] = []
        for mode in GAME_MODES:
            items = self._items_by_mode.get(mode) or []
            label = _game_mode_label(mode)
            if not items:
                parts.append(f"{label}:空")
                continue
            fetched_at = self._fetched_at_by_mode.get(mode) or 0.0
            if fetched_at:
                value = time.strftime("%m-%d %H:%M", time.localtime(fetched_at))
            else:
                value = "已加载"
            parts.append(f"{label}:{value}")
        return " / ".join(parts)

    def completion_entries(self, game_mode: str | None = None) -> list[CompletionEntry]:
        mode = _normalize_game_mode(game_mode or self.current_game_mode)
        try:
            items = self._get_items(mode)
        except PriceLookupError:
            return []

        entries: list[CompletionEntry] = []
        for item in items:
            zh_name = str(item.get("zhName") or "").strip()
            name = str(item.get("name") or "").strip()
            short_name = str(item.get("shortName") or "").strip()
            normalized_name = str(item.get("normalizedName") or "").strip()

            lookup = zh_name or name or short_name or normalized_name
            if not lookup:
                continue

            display = zh_name or name or short_name or normalized_name
            tag, tag_color, tag_text_color = _completion_tag(item)

            entries.append(
                CompletionEntry(
                    display=display,
                    lookup=lookup,
                    tag=tag,
                    tag_color=tag_color,
                    tag_text_color=tag_text_color,
                )
            )
        return sorted(entries, key=lambda entry: entry.display.casefold())

    def reload_aliases(self) -> int:
        self._aliases = {}
        if not self.aliases_path.exists():
            return 0
        try:
            data = json.loads(self.aliases_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0

        if not isinstance(data, dict):
            return 0

        for alias, target in data.items():
            if not isinstance(alias, str) or not isinstance(target, str):
                continue
            if alias.startswith("_"):
                continue
            alias_key = _normalize(alias)
            if alias_key and target.strip():
                self._aliases[alias_key] = target.strip()
        self._lookup_cache.clear()
        return len(self._aliases)

    def alias_status(self) -> str:
        return f"{len(self._aliases)} 条"

    def _get_items(self, game_mode: str) -> list[dict[str, Any]]:
        items = self._items_by_mode.get(game_mode) or []
        if items:
            if not self._search_index_by_mode.get(game_mode):
                self._build_search_index(game_mode)
            return items

        self._load_disk_cache(game_mode)
        items = self._items_by_mode.get(game_mode) or []
        if items:
            if not self._search_index_by_mode.get(game_mode):
                self._build_search_index(game_mode)
            return items

        raise PriceLookupError(
            f"{_game_mode_label(game_mode)} 物品价格缓存为空。请联网后使用 数据 > 刷新价格缓存。"
        )

    def _fetch_items(self, game_mode: str, language: str = "en") -> list[dict[str, Any]]:
        payload = json.dumps(
            {"query": ITEMS_QUERY, "variables": {"gameMode": game_mode, "lang": language}}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "EFT-Reminder-Price-Overlay/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise PriceLookupError(f"价格 API 请求失败：{exc}") from exc

        if data.get("errors"):
            raise PriceLookupError(f"价格 API 返回错误：{data['errors']}")

        items = data.get("data", {}).get("items")
        if not isinstance(items, list):
            raise PriceLookupError("价格 API 响应中没有物品列表。")

        return [item for item in items if isinstance(item, dict)]

    def _fetch_historical_prices(
        self,
        item_id: str,
        game_mode: str,
        days: int,
    ) -> list[dict[str, Any]]:
        payload = json.dumps(
            {
                "query": HISTORICAL_PRICES_QUERY,
                "variables": {"id": item_id, "gameMode": game_mode, "days": max(1, int(days))},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "EFT-Reminder-Price-Overlay/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise PriceLookupError(f"历史价格 API 请求失败：{exc}") from exc

        if data.get("errors"):
            raise PriceLookupError(f"历史价格 API 返回错误：{data['errors']}")

        points = data.get("data", {}).get("historicalItemPrices")
        if not isinstance(points, list):
            raise PriceLookupError("历史价格 API 响应中没有价格点。")
        return [point for point in points if isinstance(point, dict)]

    def _load_disk_cache(self, game_mode: str) -> None:
        cache_path = _cache_path_for_mode(game_mode)
        if not cache_path.exists() and game_mode == "regular" and self.legacy_cache_path.exists():
            cache_path = self.legacy_cache_path
        if not cache_path.exists():
            return
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        items = data.get("items")
        if not isinstance(items, list):
            return
        self._items_by_mode[game_mode] = [item for item in items if isinstance(item, dict)]
        self._fetched_at_by_mode[game_mode] = float(data.get("fetched_at") or 0.0)
        self._build_search_index(game_mode)
        self._lookup_cache.clear()

    def _write_disk_cache(self, game_mode: str, items: list[dict[str, Any]]) -> None:
        CACHE_DIR.mkdir(exist_ok=True)
        payload = {
            "fetched_at": self._fetched_at_by_mode[game_mode],
            "source": self.endpoint,
            "game_mode": game_mode,
            "items": items,
        }
        _cache_path_for_mode(game_mode).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _find_best_match(
        self,
        query: str,
        items: list[dict[str, Any]],
        game_mode: str,
    ) -> tuple[dict[str, Any] | None, float]:
        normalized_query = _normalize(query)
        best_item: dict[str, Any] | None = None
        best_score = 0.0

        for item in self._candidate_items_for_query(normalized_query, items, game_mode):
            names = [
                item.get("name"),
                item.get("shortName"),
                item.get("normalizedName"),
                item.get("zhName"),
                item.get("zhShortName"),
            ]
            for name in names:
                if not isinstance(name, str) or not name.strip():
                    continue
                score = _match_score(normalized_query, _normalize(name))
                score = _apply_feature_adjustments(normalized_query, str(name), item, score)
                score = _apply_short_name_anchor(normalized_query, item, score)
                if score > best_score:
                    best_item = item
                    best_score = score

        if best_score < 0.58:
            return None, best_score
        return best_item, best_score

    def _build_search_index(self, game_mode: str) -> None:
        items = self._items_by_mode.get(game_mode) or []
        index: dict[str, set[int]] = {}
        name_lookup: dict[str, int] = {}
        full_name_lookup: dict[str, set[int]] = {}
        for item_index, item in enumerate(items):
            for token in _item_index_tokens(item):
                index.setdefault(token, set()).add(item_index)
            for value in _item_name_values(item):
                normalized = _normalize(value)
                if normalized:
                    name_lookup.setdefault(normalized, item_index)
            for value in _item_full_name_values(item):
                compact = _compact_exact_name_text(value)
                if compact:
                    full_name_lookup.setdefault(compact, set()).add(item_index)
        self._search_index_by_mode[game_mode] = index
        self._name_lookup_by_mode[game_mode] = name_lookup
        self._full_name_lookup_by_mode[game_mode] = {
            compact: next(iter(indexes))
            for compact, indexes in full_name_lookup.items()
            if len(indexes) == 1
        }

    def _candidate_items_for_query(
        self,
        normalized_query: str,
        items: list[dict[str, Any]],
        game_mode: str,
    ) -> list[dict[str, Any]]:
        index = self._search_index_by_mode.get(game_mode) or {}
        if not index:
            return items

        model_indexes = _candidate_indexes_for_models(_extract_models(normalized_query), index)
        if model_indexes:
            return [items[index] for index in sorted(model_indexes) if index < len(items)]

        query_tokens = _query_index_tokens(normalized_query)
        candidate_indexes: set[int] = set()
        for token in query_tokens:
            candidate_indexes.update(index.get(token, set()))

        if not candidate_indexes:
            return items

        return [items[index] for index in sorted(candidate_indexes) if index < len(items)]

    def _find_alias_match(
        self,
        query: str,
        items: list[dict[str, Any]],
        normalized: bool = False,
    ) -> tuple[dict[str, Any] | None, float]:
        if not self._aliases:
            return None, 0.0

        normalized_query = query if normalized else _normalize(query)
        target = self._aliases.get(normalized_query)
        confidence = 1.0
        if target is None:
            best_alias = ""
            best_score = 0.0
            compact_query = _compact_alias_text(normalized_query)
            for alias in self._aliases:
                compact_alias = _compact_alias_text(alias)
                if (
                    compact_alias
                    and len(compact_alias) >= 4
                    and compact_alias in compact_query
                ):
                    score = 0.96
                else:
                    score = _match_score(normalized_query, alias)
                if _has_model_conflict(normalized_query, alias):
                    score -= 0.35
                if score > best_score:
                    best_alias = alias
                    best_score = score
            if best_score < 0.76:
                return None, best_score
            target = self._aliases[best_alias]
            confidence = best_score

        return _resolve_alias_target(target, items), confidence

    def _find_exact_name_match(
        self,
        normalized_query: str,
        items: list[dict[str, Any]],
        game_mode: str,
    ) -> tuple[dict[str, Any] | None, float]:
        lookup = self._name_lookup_by_mode.get(game_mode) or {}
        item_index = lookup.get(normalized_query)
        if item_index is None or item_index >= len(items):
            return None, 0.0
        return items[item_index], 1.0

    def _find_exact_full_name_match(
        self,
        query: str,
        items: list[dict[str, Any]],
        game_mode: str,
    ) -> tuple[dict[str, Any] | None, float]:
        lookup = self._full_name_lookup_by_mode.get(game_mode) or {}
        item_index = lookup.get(_compact_exact_name_text(query))
        if item_index is None or item_index >= len(items):
            return None, 0.0
        return items[item_index], 1.0

def _normalize(value: str) -> str:
    value = value.translate(_CJK_VARIANT_TRANSLATION).casefold().replace("-", " ")
    value = value.replace("×", "x")
    value = re.sub(r"(?<=\d)\s+(?=[\u4e00-\u9fff])", "", value)
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", value)
    value = re.sub(r"(\d)(\d{2}x\d{2})", r"\1.\2", value)
    return " ".join(value.split())


def _compact_alias_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", _normalize(value))


def _compact_exact_name_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", _normalize(value))


def _dedupe_query_candidates(queries: list[str]) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for query in queries:
        value = str(query).strip()
        key = _compact_exact_name_text(value)
        if value and key not in seen:
            seen.add(key)
            candidates.append(value)
    return candidates


def _candidate_specificity_score(value: str) -> tuple[int, int, int]:
    normalized = _normalize(value)
    compact = _compact_exact_name_text(normalized)
    model_count = len(_extract_models(normalized))
    caliber_count = len(_extract_calibers(normalized))
    token_count = len(_match_tokens(normalized))
    return model_count + caliber_count, token_count, len(compact)


def _merge_localized_items(
    english_items: list[dict[str, Any]],
    localized_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    localized_by_id = {
        item.get("id"): item for item in localized_items if isinstance(item.get("id"), str)
    }
    merged: list[dict[str, Any]] = []
    for item in english_items:
        copy = dict(item)
        localized = localized_by_id.get(item.get("id"))
        if localized:
            copy["zhName"] = localized.get("name")
            copy["zhShortName"] = localized.get("shortName")
        merged.append(copy)
    return merged


def _normalize_game_mode(game_mode: str) -> str:
    value = str(game_mode).strip().casefold()
    if value in {"pve", "pvemode"}:
        return "pve"
    return "regular"


def _game_mode_label(game_mode: str) -> str:
    return "PvE" if _normalize_game_mode(game_mode) == "pve" else "PvP"


def _cache_path_for_mode(game_mode: str) -> Path:
    return CACHE_DIR / f"tarkov_items_{_normalize_game_mode(game_mode)}.json"


def _resolve_alias_target(target: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized_target = _normalize(target)
    for item in items:
        values = [
            item.get("id"),
            item.get("normalizedName"),
            item.get("name"),
            item.get("shortName"),
            item.get("zhName"),
            item.get("zhShortName"),
        ]
        for value in values:
            if isinstance(value, str) and _normalize(value) == normalized_target:
                return item
    return None


def _match_score(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    if query == candidate:
        return 1.0
    if query in candidate or candidate in query:
        shorter = min(len(query), len(candidate))
        longer = max(len(query), len(candidate))
        ratio = shorter / longer
        if shorter < 8 and ratio < 0.5:
            return 0.42 + 0.30 * ratio
        if ratio < 0.35:
            return 0.55 + 0.25 * ratio
        return 0.82 + 0.18 * ratio

    sequence_score = SequenceMatcher(None, query, candidate).ratio()
    query_tokens = _match_tokens(query)
    candidate_tokens = _match_tokens(candidate)
    if not query_tokens or not candidate_tokens:
        return sequence_score

    shared = query_tokens & candidate_tokens
    if not shared:
        return sequence_score
    query_coverage = len(shared) / len(query_tokens)
    candidate_coverage = len(shared) / len(candidate_tokens)
    token_score = query_coverage * 0.75 + candidate_coverage * 0.25
    return max(sequence_score, sequence_score * 0.55 + token_score * 0.45)


def _apply_short_name_anchor(
    normalized_query: str,
    item: dict[str, Any],
    score: float,
) -> float:
    short_name = item.get("shortName")
    if not isinstance(short_name, str) or not short_name.strip():
        return score
    normalized_short = _normalize(short_name)
    short_tokens = [
        token
        for token in _match_tokens(normalized_short)
        if len(token) >= 4 and not token.isdigit()
    ]
    if not short_tokens:
        return score
    query_tokens = _match_tokens(normalized_query)
    shared = set(short_tokens) & query_tokens
    if not shared:
        compact_query = _compact_alias_text(normalized_query)
        shared = {token for token in short_tokens if token in compact_query}
    if not shared:
        return score
    anchored = 0.82
    name = str(item.get("name") or "").casefold()
    normalized_name = str(item.get("normalizedName") or "").casefold()
    if "figurine" in name or "figurine" in normalized_name:
        anchored += 0.06
    if normalized_query.startswith(next(iter(shared))):
        anchored += 0.04
    return max(score, min(anchored, 0.96))


def _match_tokens(value: str) -> set[str]:
    value = _normalize(value)
    tokens = set(re.findall(r"[a-z0-9.]+|[\u4e00-\u9fff]+", value))
    expanded: set[str] = set()
    for token in tokens:
        if len(token) > 1 or token.isdigit():
            expanded.add(token)
        expanded.update(_attached_ocr_token_parts(token))
        expanded.update(_model_tokens_from_token(token))
        if re.search(r"[\u4e00-\u9fff]", token):
            expanded.update(token[index : index + 2] for index in range(max(0, len(token) - 1)))
    return expanded


def _query_index_tokens(value: str) -> set[str]:
    tokens = _match_tokens(value)
    tokens.update(_extract_models(value))
    tokens.update(_extract_calibers(value))
    tokens.update(_extract_capacities(value))
    tokens.update(_extract_item_type_terms(value))
    return {token for token in tokens if len(token) >= 2}


def _item_index_tokens(item: dict[str, Any]) -> set[str]:
    values = [
        item.get("name"),
        item.get("shortName"),
        item.get("normalizedName"),
        item.get("zhName"),
        item.get("zhShortName"),
    ]
    text = " ".join(str(value) for value in values if value)
    return _query_index_tokens(_normalize(text))

def _item_name_values(item: dict[str, Any]) -> list[str]:
    return [
        str(value)
        for value in [
            item.get("name"),
            item.get("shortName"),
            item.get("normalizedName"),
            item.get("zhName"),
            item.get("zhShortName"),
        ]
        if isinstance(value, str) and value.strip()
    ]


def _item_full_name_values(item: dict[str, Any]) -> list[str]:
    return [
        str(value)
        for value in [
            item.get("name"),
            item.get("normalizedName"),
            item.get("zhName"),
        ]
        if isinstance(value, str) and value.strip()
    ]


def _candidate_indexes_for_models(
    query_models: set[str],
    index: dict[str, set[int]],
) -> set[int]:
    if not query_models:
        return set()

    candidate_indexes: set[int] = set()
    for model in query_models:
        candidate_indexes.update(index.get(model, set()))

    query_parts = _model_parts_from_models(query_models)
    if not query_parts:
        return candidate_indexes

    for token, token_indexes in index.items():
        for candidate_prefix, candidate_number in _model_parts_from_models({token}):
            if any(
                query_prefix == candidate_prefix and abs(query_number - candidate_number) <= 5
                for query_prefix, query_number in query_parts
            ):
                candidate_indexes.update(token_indexes)
                break

    return candidate_indexes


def _apply_feature_adjustments(
    normalized_query: str,
    candidate_name: str,
    item: dict[str, Any],
    score: float,
) -> float:
    candidate_text = _normalize(
        " ".join(
            str(value)
            for value in [
                candidate_name,
                item.get("name"),
                item.get("shortName"),
                item.get("normalizedName"),
                item.get("zhName"),
                item.get("zhShortName"),
            ]
            if value
        )
    )

    query_calibers = _extract_calibers(normalized_query)
    candidate_calibers = _extract_calibers(candidate_text)
    if query_calibers and candidate_calibers:
        if query_calibers & candidate_calibers:
            score += 0.12
        else:
            score -= 0.28

    query_capacities = _extract_capacities(normalized_query)
    candidate_capacities = _extract_capacities(candidate_text)
    if query_capacities and candidate_capacities:
        if query_capacities & candidate_capacities:
            score += 0.10
        else:
            score -= 0.18

    query_models = _extract_models(normalized_query)
    candidate_models = _extract_models(candidate_text)
    if query_models:
        if not candidate_models:
            score -= 0.28
        elif query_models & candidate_models:
            score += 0.30
        elif _has_near_model_match(normalized_query, candidate_text):
            score += 0.04
        else:
            score -= 0.38

    query_types = _extract_item_type_terms(normalized_query)
    candidate_types = _extract_item_type_terms(candidate_text)
    if query_types and candidate_types:
        if query_types & candidate_types:
            score += 0.12
        else:
            score -= 0.16

    return max(0.0, score)


def _extract_calibers(value: str) -> set[str]:
    normalized = _normalize(value).replace(" ", "")
    raw_calibers = re.findall(r"(?<![\d.])(?:\d\.\d{2}|\d{1,2})x\d{2,3}(?!\d)", normalized)
    calibers = {_normalize_caliber(caliber) for caliber in raw_calibers}
    return {caliber for caliber in calibers if _is_likely_caliber(caliber)}


def _normalize_caliber(value: str) -> str:
    if "." in value:
        return value
    match = re.fullmatch(r"(\d)(\d{2}x\d{2,3})", value)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    return value


def _is_likely_caliber(value: str) -> bool:
    if "." in value:
        return True
    return value in {"9x18", "9x19", "9x21", "9x39", "12x70", "20x70", "23x75", "30x29", "40x46"}


def _extract_capacities(value: str) -> set[str]:
    normalized = _normalize(value)
    capacities = set(re.findall(r"(\d{1,3})\s*(?:round|发)", normalized))
    capacities.update(re.findall(r"\bd\s*(\d{1,3})\b", normalized))
    return capacities


def _extract_models(value: str) -> set[str]:
    normalized = _normalize(value)
    words = re.findall(r"[a-z0-9]+", normalized)
    models: set[str] = set()

    for word in words:
        models.update(_model_tokens_from_token(word))

    for left, right in zip(words, words[1:]):
        if re.fullmatch(r"[a-z]{1,5}", left) and re.fullmatch(r"\d{2,4}[a-z0-9]*", right):
            models.add(f"{left}{right}")
            models.update(_model_tokens_from_token(right))

    return models


def _model_tokens_from_token(token: str) -> set[str]:
    token = token.casefold()
    if not re.search(r"\d", token):
        return set()
    if re.fullmatch(r"(?:i|ii|iii|iv|v|vi|vii|viii|ix|x)\d+", token):
        return set()

    models: set[str] = set()
    if re.fullmatch(r"[a-z]{1,6}\d{1,4}[a-z0-9]*", token):
        models.add(token)
    if re.fullmatch(r"\d{1,4}[a-z]{1,4}\d?", token):
        models.add(token)

    embedded = re.search(r"(\d{1,4}[a-z]{1,4}\d?)$", token)
    if embedded:
        models.add(embedded.group(1))

    return models


def _attached_ocr_token_parts(token: str) -> set[str]:
    token = token.casefold()
    parts: set[str] = set()

    roman_digit = re.fullmatch(r"(i|ii|iii|iv|v|vi|vii|viii|ix|x)(\d+)", token)
    if roman_digit:
        parts.update(roman_digit.groups())

    compact_scope = re.fullmatch(r"(\d{1,2}x\d{2})(\d{2})", token)
    if compact_scope:
        parts.update(compact_scope.groups())

    return parts


def _has_near_model_match(query: str, candidate: str) -> bool:
    query_parts = _extract_model_parts(query)
    candidate_parts = _extract_model_parts(candidate)
    for query_prefix, query_number in query_parts:
        for candidate_prefix, candidate_number in candidate_parts:
            if query_prefix == candidate_prefix and abs(query_number - candidate_number) <= 5:
                return True
    return False


def _has_model_conflict(query: str, candidate: str) -> bool:
    query_models = _extract_models(query)
    candidate_models = _extract_models(candidate)
    if not query_models or not candidate_models:
        return False
    return not (query_models & candidate_models) and not _has_near_model_match(query, candidate)


def _extract_model_parts(value: str) -> list[tuple[str, int]]:
    return _model_parts_from_models(_extract_models(value))


def _model_parts_from_models(models: set[str]) -> list[tuple[str, int]]:
    parts: list[tuple[str, int]] = []
    for model in models:
        match = re.fullmatch(r"([a-z]{1,5})(\d{2,4})[a-z0-9]*", model)
        if not match:
            continue
        prefix, number = match.groups()
        try:
            parts.append((prefix, int(number)))
        except ValueError:
            continue
    return parts


def _extract_item_type_terms(value: str) -> set[str]:
    normalized = _normalize(value)
    groups = {
        "assault_rifle": {"assault rifle", "突击步枪", "卡宾枪", "carbine"},
        "magazine": {"magazine", "弹匣", "弹鼓"},
        "case": {"case", "箱"},
        "sight": {"sight", "照门", "准星"},
        "muzzle": {"muzzle", "膛口", "制退器"},
    }
    found: set[str] = set()
    for key, terms in groups.items():
        if any(term in normalized for term in terms):
            found.add(key)
    return found


def _best_vendor_offer(
    offers: list[dict[str, Any]],
) -> tuple[str | None, int | None, int | None, str | None]:
    vendor_offers: list[tuple[str, int, int, str]] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        source = str(offer.get("source") or "").casefold()
        vendor = offer.get("vendor") or {}
        name = vendor.get("name") if isinstance(vendor, dict) else None
        if source == "fleamarket" or str(name or "").casefold() == "flea market":
            continue
        price = _as_int(offer.get("price"))
        if price is None:
            continue
        price_rub = _as_int(offer.get("priceRUB")) or price
        vendor_offers.append(
            (
                str(name or offer.get("source") or "Vendor"),
                price,
                price_rub,
                str(offer.get("currency") or "RUB"),
            )
        )

    if not vendor_offers:
        return None, None, None, None

    best_name, best_price, best_price_rub, best_currency = max(
        vendor_offers,
        key=lambda offer: offer[2],
    )
    return best_name, best_price, best_price_rub, best_currency


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _item_slots(width: int | None, height: int | None) -> int | None:
    if width is None or height is None:
        return None
    if width <= 0 or height <= 0:
        return None
    return width * height


def _value_per_slot(value: int | None, slots: int | None) -> int | None:
    if value is None or slots is None or slots <= 0:
        return None
    return round(value / slots)


def _item_types(item: dict[str, Any]) -> tuple[str, ...]:
    raw_types = item.get("types")
    if not isinstance(raw_types, list):
        return ()
    values: list[str] = []
    for value in raw_types:
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return tuple(values)


def _completion_tag(item: dict[str, Any]) -> tuple[str, str, str]:
    item_types = {_normalize(value) for value in _item_types(item)}
    text = " ".join(
        str(value)
        for value in (
            item.get("name"),
            item.get("shortName"),
            item.get("normalizedName"),
            item.get("zhName"),
            item.get("zhShortName"),
        )
        if value
    )
    lowered = text.casefold()
    normalized = _normalize(text)

    if "gun" in item_types:
        return "枪械", "#506B3F", "#F5FFE8"
    if "preset" in item_types:
        return "预设", "#53606D", "#F2F5F8"
    if "ammo" in item_types:
        if "grenade" in item_types:
            return "投掷物", "#7D6040", "#FFF4E0"
        return "弹药", "#3D5F9E", "#F2F6FF"
    if "ammobox" in item_types:
        return "弹药包", "#4B6EAF", "#F2F6FF"
    if "keys" in item_types:
        return "钥匙", "#8B6F33", "#FFF5D6"
    if "meds" in item_types:
        return "医疗用品", "#8B3B48", "#FFECEF"
    if "injectors" in item_types:
        return "注射器", "#9A4051", "#FFECEF"
    if "provisions" in item_types:
        return "食物饮水", "#6B7D38", "#FAFFE8"
    if "container" in item_types or "markedonly" in item_types:
        return "容器", "#5E526F", "#F7F0FF"
    if "backpack" in item_types:
        return "背包", "#3F6B5A", "#ECFFF8"
    if "rig" in item_types:
        return "胸挂", "#4C655B", "#ECFFF8"
    if "armorplate" in item_types:
        return "插板", "#5A6670", "#F0F6FA"
    if "armor" in item_types:
        return "护甲", "#5A6670", "#F0F6FA"
    if "helmet" in item_types:
        return "头盔", "#5B5F65", "#F3F6F8"
    if "headphones" in item_types:
        return "耳机", "#496E75", "#EFFFFF"
    if "glasses" in item_types:
        return "眼部", "#506A82", "#F0F8FF"
    if "specialslot" in item_types:
        return "特殊", "#6B607C", "#F7F0FF"
    if "mods" in item_types:
        return _mod_completion_tag(lowered, normalized)
    if "barter" in item_types:
        return _barter_completion_tag(lowered, normalized)
    if "poster" in item_types:
        return "海报", "#7A5D7D", "#FFF2FF"
    if "noflea" in item_types:
        return "禁售", "#62676F", "#F3F5F7"
    return "物品", "#4F5D6B", "#F5F7FA"


def _mod_completion_tag(lowered: str, normalized: str) -> tuple[str, str, str]:
    checks = (
        (("flashlight", "tactical device", "laser", "anpeq", "an/peq", "手电", "战术设备", "镭射"), "战术", "#2E6F73", "#EFFFFF"),
        (("suppressor", "silencer", "消音"), "消音", "#536A57", "#F1FFF3"),
        (("muzzle", "compensator", "flash hider", "brake", "制退", "消焰", "枪口"), "枪口", "#5F684C", "#FAFFE8"),
        (("barrel", "枪管"), "枪管", "#6A5845", "#FFF5EA"),
        (("magazine", "mag ", "弹匣"), "弹匣", "#565F86", "#F2F4FF"),
        (("receiver", "upper", "lower", "机匣"), "机匣", "#66606A", "#F8F4FF"),
        (("scope", "sight", "optic", "瞄准镜", "准星", "照门"), "瞄具", "#4E6580", "#F0F8FF"),
        (("mount", "rail", "ring", "基座", "导轨"), "基座", "#59636A", "#F5FAFF"),
        (("handguard", "护木"), "护木", "#526A4B", "#F2FFE8"),
        (("stock", "buffer tube", "枪托", "缓冲管"), "枪托", "#5B624E", "#FAFFE8"),
        (("grip", "握把"), "握把", "#686047", "#FFF8E8"),
        (("charging handle", "拉机柄"), "拉机柄", "#5E6470", "#F4F7FB"),
    )
    for terms, label, color, text_color in checks:
        if any(term in lowered or term in normalized for term in terms):
            return label, color, text_color
    return "配件", "#505F69", "#F5FAFF"


def _barter_completion_tag(lowered: str, normalized: str) -> tuple[str, str, str]:
    checks = (
        (("bolt", "screw", "nail", "hose", "tube", "tape", "plexiglass", "foam", "sealant", "wire", "cord", "bulb", "建筑", "螺丝", "螺栓", "钉", "软管", "胶带", "电线", "灯泡"), "建材", "#7A6740", "#FFF7E5"),
        (("circuit", "capacitor", "battery", "powerbank", "cpu", "ram", "ssd", "motor", "relay", "电子", "电容", "电池", "马达", "继电器"), "电子", "#3F6E78", "#EFFFFF"),
        (("wrench", "screwdriver", "pliers", "tool", "drill", "工具", "扳手", "螺丝刀", "钳", "电钻"), "工具", "#766042", "#FFF4E5"),
        (("figurine", "chainlet", "bitcoin", "coin", "skull", "vase", "statue", "gold", "雕像", "金币", "金链", "花瓶"), "贵重", "#8C6A28", "#FFF5D0"),
        (("fuel", "propane", "燃料", "丙烷"), "燃料", "#7A4F3B", "#FFF0E8"),
    )
    for terms, label, color, text_color in checks:
        if any(term in lowered or term in normalized for term in terms):
            return label, color, text_color
    return "可交换", "#6A6455", "#FFF9EB"


FIREARM_TYPE_TERMS = {
    "gun",
    "guns",
    "weapon",
    "weapons",
    "firearm",
    "firearms",
}

FIREARM_NAME_TERMS = (
    "assault rifle",
    "assault carbine",
    "marksman rifle",
    "sniper rifle",
    "bolt-action rifle",
    "submachine gun",
    "machine gun",
    "shotgun",
    "revolver",
    "pistol",
    "grenade launcher",
    "卡宾枪",
    "突击步枪",
    "射手步枪",
    "狙击步枪",
    "栓动步枪",
    "冲锋枪",
    "机枪",
    "霰弹枪",
    "手枪",
    "左轮",
    "榴弹发射器",
)

FIREARM_EXCLUDE_TERMS = (
    "magazine",
    "round",
    "ammo",
    "ammunition",
    "cartridge",
    "receiver",
    "upper",
    "lower",
    "barrel",
    "handguard",
    "stock",
    "grip",
    "sight",
    "scope",
    "mount",
    "muzzle",
    "suppressor",
    "adapter",
    "弹匣",
    "弹药",
    "子弹",
    "机匣",
    "上机匣",
    "下机匣",
    "枪管",
    "护木",
    "枪托",
    "握把",
    "瞄具",
    "瞄准镜",
    "基座",
    "消音",
)


def _is_firearm_item(item: dict[str, Any], item_types: tuple[str, ...]) -> bool:
    normalized_types = {_normalize(value) for value in item_types}
    if normalized_types & FIREARM_TYPE_TERMS:
        return True

    text = " ".join(
        str(value)
        for value in (
            item.get("name"),
            item.get("shortName"),
            item.get("normalizedName"),
            item.get("zhName"),
            item.get("zhShortName"),
        )
        if value
    )
    lowered = text.casefold()
    normalized_text = _normalize(text)
    if any(term in lowered or term in normalized_text for term in FIREARM_EXCLUDE_TERMS):
        return False
    return any(term in lowered or term in normalized_text for term in FIREARM_NAME_TERMS)
