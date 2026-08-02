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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the compact, versioned EFT craft/barter bundle."
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    station_names = _load_station_names()
    modes: dict[str, list[dict[str, Any]]] = {}
    source_etags: dict[str, str] = {}
    item_document, item_etag = _fetch_json("regular/items")
    item_zh_document, item_zh_etag = _fetch_json("regular/items_zh")
    source_etags["regular/items"] = item_etag
    source_etags["regular/items_zh"] = item_zh_etag
    handbook_categories = _handbook_categories(item_document, item_zh_document)
    trader_document, trader_etag = _fetch_json("regular/traders")
    trader_en_document, trader_en_etag = _fetch_json("regular/traders_en")
    source_etags["regular/traders"] = trader_etag
    source_etags["regular/traders_en"] = trader_en_etag
    trader_names = _trader_names(trader_document, trader_en_document)
    task_en_document, task_en_etag = _fetch_json("regular/tasks_en")
    task_zh_document, task_zh_etag = _fetch_json("regular/tasks_zh")
    source_etags["regular/tasks_en"] = task_en_etag
    source_etags["regular/tasks_zh"] = task_zh_etag
    for mode in GAME_MODES:
        item_map = _load_item_map(mode)
        tasks, task_etag = _fetch_json(f"{mode}/tasks")
        crafts, craft_etag = _fetch_json(f"{mode}/crafts")
        barters, barter_etag = _fetch_json(f"{mode}/barters")
        source_etags[f"{mode}/tasks"] = task_etag
        source_etags[f"{mode}/crafts"] = craft_etag
        source_etags[f"{mode}/barters"] = barter_etag
        unlock_tasks = _task_unlocks(
            tasks,
            task_en_document,
            task_zh_document,
            trader_names,
        )
        craft_rows = _data_list(crafts)
        barter_rows = _data_list(barters)
        _validate_source_count(mode, "crafts", craft_rows)
        _validate_source_count(mode, "barters", barter_rows)
        records = [
            *(
                _craft_record(
                    record,
                    item_map,
                    station_names,
                    handbook_categories,
                    unlock_tasks,
                )
                for record in craft_rows
            ),
            *(
                _barter_record(
                    record,
                    item_map,
                    handbook_categories,
                    trader_names,
                    unlock_tasks,
                )
                for record in barter_rows
            ),
        ]
        _validate_records(mode, records)
        modes[mode] = sorted(
            records,
            key=lambda record: (
                str(record.get("kind")),
                str(record.get("source")),
                str(record.get("product", {}).get("name")),
            ),
        )

    document = {
        "schema_version": 3,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "tarkov.dev JSON API",
        "source_url": JSON_API,
        "source_etags": source_etags,
        "handbook_categories": handbook_categories,
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
        headers={"Accept": "application/json", "User-Agent": "EFT-Raid-Assistant/0.7.0"},
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


def _handbook_categories(
    item_document: dict[str, Any], translations_document: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    data = item_document.get("data")
    raw_categories = data.get("handbookCategories") if isinstance(data, dict) else None
    translations = translations_document.get("data")
    if not isinstance(raw_categories, dict) or not isinstance(translations, dict):
        raise RuntimeError("The items endpoint did not include handbook categories/translations.")
    categories: dict[str, dict[str, Any]] = {}
    for category_id, value in raw_categories.items():
        if not isinstance(value, dict):
            continue
        identifier = str(value.get("id") or category_id)
        source_name = str(value.get("name") or "")
        normalized_name = str(value.get("normalizedName") or "")
        categories[identifier] = {
            "name": str(
                translations.get(source_name)
                or normalized_name.replace("-", " ").title()
                or identifier
            ),
            "normalized_name": normalized_name,
            "parent": str(value.get("parent") or ""),
        }
    if len(categories) < 50:
        raise RuntimeError(
            f"Refusing to build a recipe bundle with only {len(categories)} handbook categories."
        )
    return categories


def _trader_names(
    trader_document: dict[str, Any], translations_document: dict[str, Any]
) -> dict[str, str]:
    traders = trader_document.get("data")
    translations = translations_document.get("data")
    if not isinstance(traders, dict) or not isinstance(translations, dict):
        raise RuntimeError("The traders endpoint did not include English translations.")
    names: dict[str, str] = {}
    for trader_id, value in traders.items():
        if not isinstance(value, dict):
            continue
        identifier = str(value.get("id") or trader_id)
        name_key = str(value.get("name") or "")
        normalized_name = str(value.get("normalizedName") or "")
        names[identifier] = str(
            translations.get(name_key)
            or normalized_name.replace("-", " ").title()
            or identifier
        )
    if len(names) < 8:
        raise RuntimeError(f"Refusing to build with only {len(names)} trader names.")
    return names


def _task_unlocks(
    task_document: dict[str, Any],
    translations_en_document: dict[str, Any],
    translations_zh_document: dict[str, Any],
    trader_names: dict[str, str],
) -> dict[str, dict[str, str]]:
    data = task_document.get("data")
    tasks = data.get("tasks") if isinstance(data, dict) else None
    translations_en = translations_en_document.get("data")
    translations_zh = translations_zh_document.get("data")
    if not all(
        isinstance(value, dict)
        for value in (tasks, translations_en, translations_zh)
    ):
        raise RuntimeError("The tasks endpoint did not include task translations.")
    result: dict[str, dict[str, str]] = {}
    for task_id, value in tasks.items():
        if not isinstance(value, dict):
            continue
        identifier = str(value.get("id") or task_id)
        name_key = str(value.get("name") or "")
        normalized_name = str(value.get("normalizedName") or "")
        name_en = str(
            translations_en.get(name_key)
            or normalized_name.replace("-", " ").title()
            or identifier
        )
        trader_id = str(value.get("trader") or "")
        result[identifier] = {
            "id": identifier,
            "trader": trader_names.get(trader_id, trader_id or "Unknown trader"),
            "name_en": name_en,
            "name_zh": str(translations_zh.get(name_key) or ""),
        }
    if len(result) < 400:
        raise RuntimeError(f"Refusing to build with only {len(result)} tasks.")
    return result


def _craft_record(
    record: dict[str, Any],
    items: dict[str, dict[str, Any]],
    stations: dict[str, str],
    handbook_categories: dict[str, dict[str, Any]],
    unlock_tasks: dict[str, dict[str, str]],
) -> dict[str, Any]:
    station_id = str(record.get("station") or "")
    unlock_task = _unlock_task(record, unlock_tasks)
    result = {
        "id": str(record.get("id") or ""),
        "kind": "craft",
        "source": stations.get(station_id, station_id or "未知工作站"),
        "level": _int_value(record.get("level")),
        "duration": _int_value(record.get("duration")),
        "task_unlock": unlock_task is not None,
        "product": _contained_item(
            record.get("productItem"),
            items,
            handbook_categories=handbook_categories,
        ),
        "requirements": [
            _contained_item(item, items)
            for item in record.get("requiredItems", [])
            if isinstance(item, dict)
        ],
    }
    if unlock_task is not None:
        result["unlock_task"] = unlock_task
    return result


def _barter_record(
    record: dict[str, Any],
    items: dict[str, dict[str, Any]],
    handbook_categories: dict[str, dict[str, Any]],
    trader_names: dict[str, str],
    unlock_tasks: dict[str, dict[str, str]],
) -> dict[str, Any]:
    trader_id = str(record.get("trader") or "")
    unlock_task = _unlock_task(record, unlock_tasks)
    result = {
        "id": str(record.get("id") or ""),
        "kind": "barter",
        "source": trader_names.get(trader_id, trader_id or "Unknown trader"),
        "level": _int_value(record.get("minTraderLevel")),
        "buy_limit": _number(record.get("buyLimit")),
        "task_unlock": unlock_task is not None,
        "product": _contained_item(
            record.get("offeredItem"),
            items,
            handbook_categories=handbook_categories,
        ),
        "requirements": [
            _contained_item(item, items)
            for item in record.get("requiredItems", [])
            if isinstance(item, dict)
        ],
    }
    if unlock_task is not None:
        result["unlock_task"] = unlock_task
    return result


def _unlock_task(
    record: dict[str, Any], unlock_tasks: dict[str, dict[str, str]]
) -> dict[str, str] | None:
    task_id = str(record.get("taskUnlock") or "")
    if not task_id:
        return None
    task = unlock_tasks.get(task_id)
    if task is None:
        raise RuntimeError(f"Recipe references unresolved unlock task: {task_id}")
    return task


def _contained_item(
    value: object,
    items: dict[str, dict[str, Any]],
    *,
    handbook_categories: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    if handbook_categories is not None:
        result["category_path"] = _handbook_category_path(item, handbook_categories)
    return result


def _handbook_category_path(
    item: dict[str, Any], categories: dict[str, dict[str, Any]]
) -> list[str]:
    raw_ids = item.get("handbookCategories")
    category_ids = [str(value) for value in raw_ids] if isinstance(raw_ids, list) else []
    if not category_ids:
        return []

    def path_to_root(category_id: str) -> list[str]:
        path: list[str] = []
        seen: set[str] = set()
        current = category_id
        while current and current not in seen and current in categories:
            seen.add(current)
            path.append(current)
            current = str(categories[current].get("parent") or "")
        path.reverse()
        return path

    return max((path_to_root(category_id) for category_id in category_ids), key=len, default=[])


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
