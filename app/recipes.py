from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.config import RESOURCE_DIR
from app.game_modes import GAME_MODES, normalize_game_mode


RECIPE_DATA_PATH = RESOURCE_DIR / "data" / "recipes.json"


class RecipeDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecipeNotice:
    recipe_id: str
    product_text: str
    source_text: str
    requirement_text: str
    material_text: str = ""

    @property
    def compact_text(self) -> str:
        return f"{self.product_text} · {self.source_text} · {self.requirement_text}"


@dataclass(frozen=True)
class RecipeRequirementRow:
    name: str
    count_text: str
    is_tool: bool
    qualifiers: tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        if not self.qualifiers:
            return self.name
        return f"{self.name}（{'；'.join(self.qualifiers)}）"


class RecipeCatalog:
    def __init__(self, data_path: Path = RECIPE_DATA_PATH) -> None:
        self.data_path = data_path
        self.generated_at = ""
        self.source = ""
        self.handbook_categories: dict[str, dict[str, Any]] = {}
        self._records: dict[str, list[dict[str, Any]]] = {
            mode: [] for mode in GAME_MODES
        }
        self._requirements: dict[str, dict[str, list[dict[str, Any]]]] = {
            mode: {} for mode in GAME_MODES
        }
        self._load()

    @property
    def available(self) -> bool:
        return any(self._records.values())

    def records(self, game_mode: str) -> list[dict[str, Any]]:
        return list(self._records.get(_mode(game_mode), []))

    def record_count(self, game_mode: str) -> int:
        return len(self._records.get(_mode(game_mode), []))

    def tracked_requirement_lines(
        self,
        item_id: str,
        tracked_recipe_ids: Iterable[str],
        game_mode: str,
        *,
        max_lines: int = 4,
    ) -> list[str]:
        notices = self.tracked_requirement_notices(
            item_id,
            tracked_recipe_ids,
            game_mode,
        )
        lines = [notice.compact_text for notice in notices[:max_lines]]
        remaining = len(notices) - len(lines)
        if remaining > 0:
            lines.append(f"另有 {remaining} 个已关注配方也需要此物品")
        return lines

    def tracked_requirement_notices(
        self,
        item_id: str,
        tracked_recipe_ids: Iterable[str],
        game_mode: str,
    ) -> list[RecipeNotice]:
        tracked = {str(value) for value in tracked_recipe_ids if str(value)}
        if not item_id or not tracked:
            return []
        matches = [
            record
            for record in self._requirements.get(_mode(game_mode), {}).get(item_id, [])
            if str(record.get("id")) in tracked
        ]
        return [recipe_notice(record, item_id) for record in matches]

    def tracked_records(
        self, tracked_recipe_ids: Iterable[str]
    ) -> list[tuple[dict[str, Any], tuple[str, ...]]]:
        tracked = {str(value) for value in tracked_recipe_ids if str(value)}
        found: dict[str, tuple[dict[str, Any], list[str]]] = {}
        for mode in GAME_MODES:
            for record in self._records[mode]:
                recipe_id = str(record.get("id") or "")
                if recipe_id not in tracked:
                    continue
                if recipe_id not in found:
                    found[recipe_id] = (record, [mode])
                else:
                    found[recipe_id][1].append(mode)
        return [
            (record, tuple(modes))
            for record, modes in sorted(
                found.values(),
                key=lambda value: recipe_search_text(value[0]),
            )
        ]

    def category_path(self, record: dict[str, Any]) -> list[dict[str, str]]:
        product = record.get("product")
        raw_path = product.get("category_path") if isinstance(product, dict) else None
        path: list[dict[str, str]] = []
        for category_id in raw_path if isinstance(raw_path, list) else []:
            identifier = str(category_id)
            category = self.handbook_categories.get(identifier)
            if category is None:
                continue
            path.append(
                {
                    "id": identifier,
                    "name": str(category.get("name") or identifier),
                    "parent": str(category.get("parent") or ""),
                }
            )
        return path

    def _load(self) -> None:
        if not self.data_path.exists():
            return
        try:
            document = json.loads(self.data_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecipeDataError(f"本地配方数据无法读取：{exc}") from exc
        if not isinstance(document, dict) or int(document.get("schema_version", 0)) not in {
            1,
            2,
            3,
        }:
            raise RecipeDataError("本地配方数据版本不受支持。")
        modes = document.get("modes")
        if not isinstance(modes, dict):
            raise RecipeDataError("本地配方数据缺少 modes。")
        self.generated_at = str(document.get("generated_at") or "")
        self.source = str(document.get("source") or "")
        raw_categories = document.get("handbook_categories")
        if isinstance(raw_categories, dict):
            self.handbook_categories = {
                str(category_id): dict(value)
                for category_id, value in raw_categories.items()
                if isinstance(value, dict)
            }
        for mode in GAME_MODES:
            value = modes.get(mode)
            records = (
                [record for record in value if isinstance(record, dict)]
                if isinstance(value, list)
                else []
            )
            self._records[mode] = records
            requirement_index: dict[str, list[dict[str, Any]]] = {}
            for record in records:
                requirements = record.get("requirements")
                if not isinstance(requirements, list):
                    continue
                for requirement in requirements:
                    if not isinstance(requirement, dict):
                        continue
                    item_id = str(requirement.get("id") or "")
                    if item_id:
                        requirement_index.setdefault(item_id, []).append(record)
            self._requirements[mode] = requirement_index


def recipe_search_text(record: dict[str, Any]) -> str:
    product = record.get("product") if isinstance(record.get("product"), dict) else {}
    requirements = record.get("requirements")
    requirement_names = " ".join(
        str(item.get("name") or item.get("short_name") or "")
        for item in requirements or []
        if isinstance(item, dict)
    )
    return " ".join(
        (
            str(product.get("name") or ""),
            str(product.get("short_name") or ""),
            str(record.get("source") or ""),
            str(record.get("category") or ""),
            _unlock_task_search_text(record),
            requirement_names,
        )
    ).casefold()


def recipe_title(record: dict[str, Any]) -> str:
    product = record.get("product") if isinstance(record.get("product"), dict) else {}
    name = str(product.get("name") or product.get("short_name") or "未知产物")
    count = _format_count(product.get("count"))
    return f"{name} ×{count}"


def recipe_source_text(record: dict[str, Any]) -> str:
    action = "制作" if record.get("kind") == "craft" else "兑换"
    source = str(record.get("source") or "未知来源")
    level = int(record.get("level") or 0)
    level_text = f" Lv{level}" if level > 0 else ""
    return f"{source}{level_text} {action}"


def recipe_acquisition_text(record: dict[str, Any]) -> str:
    if record.get("kind") == "craft":
        return _format_duration(record.get("duration"))
    buy_limit = record.get("buy_limit")
    try:
        value = float(buy_limit)
    except (TypeError, ValueError):
        return "不限购"
    if value <= 0:
        return "不限购"
    return f"限购 ×{_format_count(value)}"


def recipe_unlock_note(record: dict[str, Any], display_language: str) -> str:
    if not bool(record.get("task_unlock")):
        return ""
    task = record.get("unlock_task")
    if not isinstance(task, dict):
        return "对应任务"
    name_en = str(task.get("name_en") or task.get("id") or "未知任务")
    name_zh = str(task.get("name_zh") or "")
    task_name = name_en if display_language.casefold() == "en" else name_zh or name_en
    trader = str(task.get("trader") or "Unknown trader")
    return f"{trader} · {task_name}"


def recipe_requirements_text(record: dict[str, Any], *, max_items: int = 5) -> str:
    requirements = record.get("requirements")
    if not isinstance(requirements, list):
        return ""
    parts: list[str] = []
    for item in requirements[:max_items]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("short_name") or "未知物品")
        qualifiers = _requirement_qualifiers(item)
        suffix = f"（{'；'.join(qualifiers)}）" if qualifiers else ""
        parts.append(f"{name} ×{_format_count(item.get('count'))}{suffix}")
    remaining = len(requirements) - len(parts)
    if remaining > 0:
        parts.append(f"另 {remaining} 项")
    return "；".join(parts)


def requirement_line(record: dict[str, Any], item_id: str) -> str:
    return recipe_notice(record, item_id).compact_text


def recipe_notice(record: dict[str, Any], item_id: str) -> RecipeNotice:
    required_count: object = 0
    matched_requirement: dict[str, Any] = {}
    requirements = record.get("requirements")
    if isinstance(requirements, list):
        for item in requirements:
            if isinstance(item, dict) and str(item.get("id") or "") == item_id:
                required_count = item.get("count")
                matched_requirement = item
                break
    count_text = _format_count(required_count)
    qualifiers = _requirement_qualifiers(matched_requirement)
    qualifier_text = "".join(f" · {qualifier}" for qualifier in qualifiers)
    material_name = str(
        matched_requirement.get("name")
        or matched_requirement.get("short_name")
        or "当前物品"
    )
    return RecipeNotice(
        recipe_id=str(record.get("id") or ""),
        product_text=recipe_title(record),
        source_text=recipe_source_text(record),
        requirement_text=(
            f"需求：{count_text} 个{qualifier_text}"
        ),
        material_text=f"{material_name} ×{count_text}{qualifier_text}",
    )


def recipe_requirement_rows(record: dict[str, Any]) -> list[RecipeRequirementRow]:
    requirements = record.get("requirements")
    if not isinstance(requirements, list):
        return []
    rows: list[RecipeRequirementRow] = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("short_name") or "未知物品")
        qualifiers: list[str] = []
        try:
            min_level = int(item.get("min_level") or 0)
        except (TypeError, ValueError):
            min_level = 0
        if min_level > 0:
            qualifiers.append(f"等级≥{min_level}")
        if bool(item.get("functional")):
            qualifiers.append("需可用")
        rows.append(
            RecipeRequirementRow(
                name=name,
                count_text=f"×{_format_count(item.get('count'))}",
                is_tool=bool(item.get("tool")),
                qualifiers=tuple(qualifiers),
            )
        )
    return rows


def _requirement_qualifiers(item: dict[str, Any]) -> list[str]:
    qualifiers: list[str] = []
    if bool(item.get("tool")):
        qualifiers.append("工具")
    try:
        min_level = int(item.get("min_level") or 0)
    except (TypeError, ValueError):
        min_level = 0
    if min_level > 0:
        qualifiers.append(f"物品等级≥{min_level}")
    if bool(item.get("functional")):
        qualifiers.append("需可用状态")
    return qualifiers


def _format_count(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "?"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_duration(value: object) -> str:
    try:
        total_seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        total_seconds = 0
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _unlock_task_search_text(record: dict[str, Any]) -> str:
    task = record.get("unlock_task")
    if not isinstance(task, dict):
        return ""
    return " ".join(
        str(task.get(key) or "") for key in ("trader", "name_en", "name_zh")
    )


def _mode(value: str) -> str:
    return normalize_game_mode(value)
