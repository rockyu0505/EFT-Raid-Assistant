from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
JSON_API = "https://json.tarkov.dev"
OUTPUT_PATH = ROOT / "data" / "recipes.json"
GAME_MODES = ("regular", "pve")
MINIMUM_SOURCE_COUNTS = {"crafts": 100, "barters": 400}

TRADER_NAMES = {
    "54cb50c76803fa8b248b4571": "普拉波",
    "54cb57776803fa99248b456e": "医生",
    "579dc571d53a0658a154fbec": "围栏",
    "58330581ace78e27b8b10cee": "滑雪者",
    "5935c25fb3acc3127c3d8cd9": "和平使者",
    "5a7c2eca46aef81a7ca2145d": "机械师",
    "5ac3b934156ae10c4430e83c": "服装商",
    "5c0647fdd443bc2504c2d371": "耶格",
    "6617beeaa9cfa777ca915b7c": "Ref",
}

CATEGORY_NAMES = {
    "gun": "武器",
    "ammo": "弹药",
    "ammoBox": "弹药",
    "armor": "护甲",
    "armorPlate": "护甲",
    "helmet": "头盔",
    "rig": "胸挂",
    "backpack": "背包",
    "container": "容器",
    "keys": "钥匙",
    "meds": "医疗",
    "injectors": "医疗",
    "provisions": "食物与饮品",
    "grenade": "投掷物",
    "mods": "武器配件",
    "suppressor": "武器配件",
    "wearable": "装备",
    "barter": "物资",
    "preset": "武器与装备预设",
}
CATEGORY_PRIORITY = tuple(CATEGORY_NAMES)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the compact, versioned EFT craft/barter bundle."
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    station_names = _load_station_names()
    modes: dict[str, list[dict[str, Any]]] = {}
    source_etags: dict[str, str] = {}
    for mode in GAME_MODES:
        item_map = _load_item_map(mode)
        crafts, craft_etag = _fetch_json(f"{mode}/crafts")
        barters, barter_etag = _fetch_json(f"{mode}/barters")
        source_etags[f"{mode}/crafts"] = craft_etag
        source_etags[f"{mode}/barters"] = barter_etag
        craft_rows = _data_list(crafts)
        barter_rows = _data_list(barters)
        _validate_source_count(mode, "crafts", craft_rows)
        _validate_source_count(mode, "barters", barter_rows)
        records = [
            *(_craft_record(record, item_map, station_names) for record in craft_rows),
            *(_barter_record(record, item_map) for record in barter_rows),
        ]
        _validate_records(mode, records)
        modes[mode] = sorted(
            records,
            key=lambda record: (
                str(record.get("kind")),
                str(record.get("category")),
                str(record.get("source")),
                str(record.get("product", {}).get("name")),
            ),
        )

    document = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "tarkov.dev JSON API",
        "source_url": JSON_API,
        "source_etags": source_etags,
        "modes": modes,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    temporary_output.write_text(encoded + "\n", encoding="utf-8")
    temporary_output.replace(output)
    print(
        f"Wrote {output} ({output.stat().st_size} bytes): "
        + ", ".join(f"{mode}={len(records)}" for mode, records in modes.items())
    )
    return 0


def _fetch_json(resource_path: str) -> tuple[dict[str, Any], str]:
    request = urllib.request.Request(
        f"{JSON_API}/{resource_path}",
        headers={"Accept": "application/json", "User-Agent": "EFT-Raid-Assistant/0.6"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read()
        etag = str(response.headers.get("ETag") or "")
    document = json.loads(raw.decode("utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError(f"Invalid JSON document: {resource_path}")
    return document, etag


def _data_list(document: dict[str, Any]) -> list[dict[str, Any]]:
    value = document.get("data")
    if not isinstance(value, list):
        raise RuntimeError("Expected a data array from tarkov.dev.")
    return [record for record in value if isinstance(record, dict)]


def _validate_source_count(
    game_mode: str, resource: str, rows: list[dict[str, Any]]
) -> None:
    minimum = MINIMUM_SOURCE_COUNTS[resource]
    if len(rows) < minimum:
        raise RuntimeError(
            f"Refusing to replace the bundle: {game_mode}/{resource} returned "
            f"only {len(rows)} records (minimum {minimum})."
        )


def _validate_records(game_mode: str, records: list[dict[str, Any]]) -> None:
    identifiers = [str(record.get("id") or "") for record in records]
    if any(not identifier for identifier in identifiers):
        raise RuntimeError(f"{game_mode}: one or more recipes have no id.")
    if len(set(identifiers)) != len(identifiers):
        raise RuntimeError(f"{game_mode}: duplicate recipe ids were returned.")
    unresolved: list[str] = []
    for record in records:
        product = record.get("product")
        if not isinstance(product, dict) or not str(product.get("id") or ""):
            unresolved.append(str(record.get("id") or "unknown"))
            continue
        if str(product.get("name") or "") == str(product.get("id") or ""):
            unresolved.append(str(record.get("id") or "unknown"))
        for requirement in record.get("requirements", []):
            if not isinstance(requirement, dict):
                continue
            if str(requirement.get("name") or "") == str(requirement.get("id") or ""):
                unresolved.append(str(record.get("id") or "unknown"))
                break
    if unresolved:
        preview = ", ".join(unresolved[:5])
        raise RuntimeError(
            f"{game_mode}: item caches could not resolve {len(unresolved)} recipes "
            f"({preview}). Refresh item caches first."
        )


def _load_item_map(mode: str) -> dict[str, dict[str, Any]]:
    path = ROOT / "cache" / f"tarkov_items_{mode}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, list):
        raise RuntimeError(f"Refresh the {mode} item cache before building recipes: {path}")
    return {
        str(item.get("id")): item
        for item in items
        if isinstance(item, dict) and str(item.get("id") or "")
    }


def _load_station_names() -> dict[str, str]:
    path = ROOT / "cache" / "hideout_requirements_zh.json"
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    stations = document.get("stations") if isinstance(document, dict) else None
    if not isinstance(stations, list):
        return {}
    return {
        str(station.get("id")): str(station.get("name") or station.get("id"))
        for station in stations
        if isinstance(station, dict) and str(station.get("id") or "")
    }


def _craft_record(
    record: dict[str, Any],
    items: dict[str, dict[str, Any]],
    stations: dict[str, str],
) -> dict[str, Any]:
    station_id = str(record.get("station") or "")
    return {
        "id": str(record.get("id") or ""),
        "kind": "craft",
        "category": _item_category(record.get("productItem"), items),
        "source": stations.get(station_id, station_id or "未知工作站"),
        "level": _int_value(record.get("level")),
        "duration": _int_value(record.get("duration")),
        "task_unlock": bool(record.get("taskUnlock")),
        "product": _contained_item(record.get("productItem"), items),
        "requirements": [
            _contained_item(item, items)
            for item in record.get("requiredItems", [])
            if isinstance(item, dict)
        ],
    }


def _barter_record(
    record: dict[str, Any], items: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    trader_id = str(record.get("trader") or "")
    return {
        "id": str(record.get("id") or ""),
        "kind": "barter",
        "category": _item_category(record.get("offeredItem"), items),
        "source": TRADER_NAMES.get(trader_id, trader_id or "未知商人"),
        "level": _int_value(record.get("minTraderLevel")),
        "buy_limit": _number(record.get("buyLimit")),
        "task_unlock": bool(record.get("taskUnlock")),
        "product": _contained_item(record.get("offeredItem"), items),
        "requirements": [
            _contained_item(item, items)
            for item in record.get("requiredItems", [])
            if isinstance(item, dict)
        ],
    }


def _contained_item(value: object, items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    contained = value if isinstance(value, dict) else {}
    item_id = str(contained.get("item") or "")
    item = items.get(item_id, {})
    attributes = contained.get("attributes")
    result: dict[str, Any] = {
        "id": item_id,
        "name": str(item.get("zhName") or item.get("name") or item_id),
        "count": _number(contained.get("count")),
    }
    short_name = str(item.get("shortName") or "")
    if short_name:
        result["short_name"] = short_name
    if isinstance(attributes, dict):
        if bool(attributes.get("tool")):
            result["tool"] = True
        min_level = _int_value(attributes.get("minLevel"))
        if min_level > 0:
            result["min_level"] = min_level
        if bool(attributes.get("functional")):
            result["functional"] = True
    return result


def _item_category(value: object, items: dict[str, dict[str, Any]]) -> str:
    contained = value if isinstance(value, dict) else {}
    item = items.get(str(contained.get("item") or ""), {})
    raw_types = item.get("types")
    types = {str(value) for value in raw_types} if isinstance(raw_types, list) else set()
    for category in CATEGORY_PRIORITY:
        if category in types:
            return CATEGORY_NAMES[category]
    return "特殊物品"


def _number(value: object) -> int | float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else round(number, 3)


def _int_value(value: object) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
