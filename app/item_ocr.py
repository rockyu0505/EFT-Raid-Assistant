from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

from app.config import APP_DIR
from app.models import ParsedItemName
from app.ocr import OcrUnavailableError, OcrVariant
from app.rapid_ocr import RapidOcrUnavailableError, run_rapid_text


UI_NOISE = {
    "inspect",
    "required search",
    "filter by item",
    "linked search",
    "discard",
    "use",
    "equip",
    "open",
    "close",
    "back",
    "weight",
    "durability",
    "搜索",
    "整理栏位",
    "返回",
    "总览",
    "装备",
    "健康",
    "技能",
    "地图",
    "任务",
    "成就",
}

INVENTORY_TAB_DEBUG_PATH = APP_DIR / "debug" / "last_inventory_tab.png"


def refine_tooltip_name_crop(
    search_path: Path,
    output_path: Path,
    padding: tuple[int, int, int, int] = (10, 8, 10, 8),
    cursor_anchor: tuple[int, int] | None = None,
    cursor_bottom_gap: int = 20,
    cursor_gap_tolerance: int = 36,
) -> tuple[bool, list[str]]:
    """Find the tooltip bounds inside the hover search crop and save a tighter name crop."""
    image = Image.open(search_path).convert("RGB")
    border_box = _find_tooltip_border_box(
        image,
        cursor_anchor=cursor_anchor,
        cursor_bottom_gap=cursor_bottom_gap,
        cursor_gap_tolerance=cursor_gap_tolerance,
    )
    if border_box is not None:
        crop_box = _inset_box(border_box, 2, image.size)
        image.crop(crop_box).save(output_path)
        x0, y0, x1, y1 = border_box
        details = [f"border:{x1 - x0}x{y1 - y0}"]
        if cursor_anchor is not None:
            details.append(f"cursor-gap:{cursor_anchor[1] - y1}/{cursor_bottom_gap}")
        return True, details

    image.save(output_path)
    return False, []


def _find_tooltip_border_box(
    image: Image.Image,
    cursor_anchor: tuple[int, int] | None = None,
    cursor_bottom_gap: int = 20,
    cursor_gap_tolerance: int = 36,
) -> tuple[int, int, int, int] | None:
    gray = ImageOps.grayscale(image)
    mask = _tooltip_border_mask(gray)
    runs = _horizontal_border_runs(mask, min_run=24)
    if not runs:
        return None

    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    width, height = image.size
    gray_pixels = gray.load()
    min_box_height = max(20, round(height * 0.08))
    for index, (top_y, top_x0, top_x1) in enumerate(runs):
        for bottom_y, bottom_x0, bottom_x1 in runs[index + 1 :]:
            box_height = bottom_y - top_y
            if box_height > 76:
                break
            if box_height < min_box_height:
                continue

            overlap = min(top_x1, bottom_x1) - max(top_x0, bottom_x0)
            x0 = max(0, min(top_x0, bottom_x0) - 2)
            x1 = min(width, max(top_x1, bottom_x1) + 2)
            box_width = x1 - x0
            if box_width < 38 or box_width > min(850, width):
                continue
            if overlap < min(32, box_width * 0.35):
                continue

            top_score = _horizontal_line_score(mask, top_y, x0, x1)
            bottom_score = _horizontal_line_score(mask, bottom_y, x0, x1)
            left_score = max(
                _vertical_line_score(mask, x0, top_y, bottom_y),
                _vertical_line_score(mask, min(top_x0, bottom_x0), top_y, bottom_y),
            )
            right_score = max(
                _vertical_line_score(mask, x1 - 1, top_y, bottom_y),
                _vertical_line_score(mask, max(top_x1, bottom_x1) - 1, top_y, bottom_y),
            )
            dark_ratio = _dark_interior_ratio(gray_pixels, (x0, top_y, x1, bottom_y))
            bright_ratio = _bright_interior_ratio(gray_pixels, (x0, top_y, x1, bottom_y))
            if top_score + bottom_score < 0.8:
                continue
            if left_score + right_score < 0.08:
                continue
            if dark_ratio < 0.70:
                continue
            if bright_ratio < 0.055:
                continue
            if cursor_anchor is not None:
                gap = cursor_anchor[1] - bottom_y
                if gap < -6 or gap > cursor_bottom_gap + cursor_gap_tolerance:
                    continue

            score = (
                (top_score + bottom_score) * 80
                + (left_score + right_score) * 90
                + dark_ratio * 70
                + bright_ratio * 160
                + box_width * 0.05
                + box_height * 0.25
            )
            if cursor_anchor is not None:
                gap = cursor_anchor[1] - bottom_y
                gap_error = abs(gap - cursor_bottom_gap)
                gap_score = max(0.0, 1.0 - gap_error / max(1, cursor_gap_tolerance))
                score += gap_score * 130
            candidates.append((score, (x0, top_y, x1, bottom_y)))

    if not candidates:
        return None
    if cursor_anchor is not None:
        candidates = _penalize_parent_tooltip_boxes(candidates)
    return max(candidates, key=lambda value: value[0])[1]


def _penalize_parent_tooltip_boxes(
    candidates: list[tuple[float, tuple[int, int, int, int]]],
) -> list[tuple[float, tuple[int, int, int, int]]]:
    """Prefer the inner tooltip when inventory label rows form a larger fake box."""
    adjusted: list[tuple[float, tuple[int, int, int, int]]] = []
    for score, box in candidates:
        x0, y0, x1, y1 = box
        width = x1 - x0
        height = y1 - y0
        parent_penalty = 0.0
        for _, other in candidates:
            if other == box:
                continue
            ox0, oy0, ox1, oy1 = other
            other_height = oy1 - oy0
            if other_height + 12 >= height:
                continue
            if abs(oy1 - y1) > 4:
                continue
            overlap = min(x1, ox1) - max(x0, ox0)
            if overlap <= 0:
                continue
            if overlap / max(1, min(width, ox1 - ox0)) >= 0.70:
                parent_penalty = 95.0
                break
        adjusted.append((score - parent_penalty, box))
    return adjusted


def _tooltip_border_mask(gray: Image.Image) -> list[bytearray]:
    width, height = gray.size
    pixels = gray.load()
    mask: list[bytearray] = []
    for y in range(height):
        row = bytearray(width)
        for x in range(width):
            value = pixels[x, y]
            if value < 65 or value > 230:
                continue
            has_dark_neighbor = False
            for dx, dy in ((0, 2), (0, -2), (2, 0), (-2, 0)):
                nx = min(width - 1, max(0, x + dx))
                ny = min(height - 1, max(0, y + dy))
                if pixels[nx, ny] < 55:
                    has_dark_neighbor = True
                    break
            if has_dark_neighbor:
                row[x] = 1
        mask.append(row)
    return mask


def _horizontal_border_runs(
    mask: list[bytearray],
    min_run: int,
) -> list[tuple[int, int, int]]:
    runs: list[tuple[int, int, int]] = []
    for y, row in enumerate(mask):
        x = 0
        width = len(row)
        while x < width:
            while x < width and not row[x]:
                x += 1
            x0 = x
            while x < width and row[x]:
                x += 1
            if x - x0 >= min_run:
                runs.append((y, x0, x))
    return runs


def _horizontal_line_score(mask: list[bytearray], y: int, x0: int, x1: int) -> float:
    if y < 0 or y >= len(mask) or x1 <= x0:
        return 0.0
    row = mask[y]
    return sum(row[x0:x1]) / (x1 - x0)


def _vertical_line_score(mask: list[bytearray], x: int, y0: int, y1: int) -> float:
    if not mask or y1 <= y0:
        return 0.0
    width = len(mask[0])
    left = max(0, x - 3)
    right = min(width, x + 4)
    if right <= left:
        return 0.0
    total = (right - left) * (y1 - y0 + 1)
    hits = 0
    for y in range(max(0, y0), min(len(mask), y1 + 1)):
        row = mask[y]
        hits += sum(row[left:right])
    return hits / total


def _dark_interior_ratio(
    pixels: Any,
    box: tuple[int, int, int, int],
) -> float:
    x0, y0, x1, y1 = box
    values = 0
    dark = 0
    for y in range(y0 + 3, y1 - 2):
        for x in range(x0 + 3, x1 - 3):
            values += 1
            if pixels[x, y] < 65:
                dark += 1
    if values == 0:
        return 0.0
    return dark / values


def _bright_interior_ratio(
    pixels: Any,
    box: tuple[int, int, int, int],
) -> float:
    x0, y0, x1, y1 = box
    values = 0
    bright = 0
    for y in range(y0 + 3, y1 - 2):
        for x in range(x0 + 3, x1 - 3):
            values += 1
            if pixels[x, y] > 115:
                bright += 1
    if values == 0:
        return 0.0
    return bright / values


def _inset_box(
    box: tuple[int, int, int, int],
    inset: int,
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return _fit_box((x0 + inset, y0 + inset, x1 - inset, y1 - inset), image_size)


def run_item_name_ocr(
    crop_path: Path,
    model_version: str = "v5",
) -> ParsedItemName:
    """OCR a UI crop and return likely item-name candidates."""
    return _run_rapidocr_item_name(crop_path, model_version)


def _run_rapidocr_item_name(crop_path: Path, model_version: str = "v4") -> ParsedItemName:
    image = Image.open(crop_path).convert("RGB")
    line_images = _split_text_line_images(image)
    variants = _build_item_variants(image)
    line_variants = [
        (f"lines:{index + 1}", line_image)
        for index, line_image in enumerate(line_images)
        if line_image.width > 0 and line_image.height > 0
    ]
    variant_images = [(variant.name, variant.image) for variant in variants]
    if len(line_variants) > 1:
        variant_images.insert(0, ("line-split", line_variants))
    best = ParsedItemName(raw_text="", candidates=[], variant_name="rapidocr-none")
    best_score = 0
    raw_parts: list[str] = []

    for variant_name, variant_payload in variant_images:
        started = time.perf_counter()
        if isinstance(variant_payload, list):
            texts: list[str] = []
            scores: list[float] = []
            for _, line_image in variant_payload:
                rapid = run_rapid_text(
                    line_image,
                    model_version=model_version,
                    use_det=False,
                    use_cls=False,
                    use_rec=True,
                )
                texts.extend(rapid.lines)
                scores.extend(rapid.scores)
        else:
            rapid = run_rapid_text(
                variant_payload,
                model_version=model_version,
                use_det=False,
                use_cls=False,
                use_rec=True,
            )
            texts = rapid.lines
            scores = rapid.scores
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        text = "\n".join(texts)
        raw_parts.append(f"{variant_name}:{elapsed_ms}ms:{text}")
        candidates = parse_item_name_candidates(text)
        score = _score_candidates(candidates)
        if scores:
            score += round(max(scores) * 10)
        if score > best_score:
            best_score = score
            best = ParsedItemName(
                raw_text=text,
                candidates=candidates,
                variant_name=f"rapidocr:{variant_name}:{elapsed_ms}ms",
            )

    if best.candidates:
        return best
    return ParsedItemName(
        raw_text="\n".join(raw_parts),
        candidates=[],
        variant_name="rapidocr:none",
    )


def _split_text_line_images(image: Image.Image) -> list[Image.Image]:
    gray = ImageOps.grayscale(image)
    width, height = gray.size
    if width < 20 or height < 20:
        return [image]

    pixels = gray.load()
    threshold = 125
    min_hits = max(3, round(width * 0.012))
    rows: list[int] = []
    for y in range(height):
        hits = 0
        for x in range(width):
            if pixels[x, y] >= threshold:
                hits += 1
        if hits >= min_hits:
            rows.append(y)
    if not rows:
        return [image]

    groups: list[tuple[int, int]] = []
    start = previous = rows[0]
    max_gap = max(2, round(height * 0.045))
    for y in rows[1:]:
        if y - previous <= max_gap:
            previous = y
            continue
        groups.append((start, previous))
        start = previous = y
    groups.append((start, previous))

    min_height = max(5, round(height * 0.11))
    text_groups = [(top, bottom) for top, bottom in groups if bottom - top + 1 >= min_height]
    if len(text_groups) < 2:
        return [image]

    padding = max(3, round(height * 0.08))
    line_images: list[Image.Image] = []
    for top, bottom in text_groups:
        if bottom >= height - 2:
            continue
        y0 = max(0, top - padding)
        y1 = min(height, bottom + padding + 1)
        bright_columns: list[int] = []
        for x in range(width):
            for y in range(max(0, top), min(height, bottom + 1)):
                if pixels[x, y] >= threshold:
                    bright_columns.append(x)
                    break
        if not bright_columns:
            continue
        x0 = max(0, min(bright_columns) - padding)
        x1 = min(width, max(bright_columns) + padding + 1)
        if x1 - x0 < max(12, round(width * 0.05)):
            continue
        line_images.append(image.crop((x0, y0, x1, y1)))
    return line_images


def detect_inventory_tab_crop(crop_path: Path) -> tuple[bool, list[str], str]:
    """Detect the inventory screen from an already-captured top-left tab crop."""
    tab_crop = Image.open(crop_path)
    INVENTORY_TAB_DEBUG_PATH.parent.mkdir(exist_ok=True)
    if crop_path != INVENTORY_TAB_DEBUG_PATH:
        tab_crop.save(INVENTORY_TAB_DEBUG_PATH)

    tab_visual_score = _active_tab_visual_score(tab_crop)
    if tab_visual_score >= 1.0:
        return True, [f"tab:visual:{tab_visual_score:.2f}"], ""

    tab_text = _ocr_detection_crop(tab_crop)
    normalized_tab = _normalize_detection_text(tab_text)
    tab_found = _matching_keywords(normalized_tab, {"装备", "gear"})
    return bool(tab_found), [f"tab:{keyword}" for keyword in tab_found], tab_text

def _active_tab_visual_score(image: Image.Image) -> float:
    """Score the selected equipment tab by its bright highlighted tab background."""
    gray = ImageOps.grayscale(image)
    values = list(gray.getdata())
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    bright_ratio = sum(1 for value in values if value > 135) / len(values)
    very_bright_ratio = sum(1 for value in values if value > 170) / len(values)
    score = 0.0
    if mean > 80:
        score += min((mean - 80) / 55, 1.0) * 0.45
    if bright_ratio > 0.22:
        score += min((bright_ratio - 0.22) / 0.25, 1.0) * 0.45
    if very_bright_ratio > 0.12:
        score += min((very_bright_ratio - 0.12) / 0.25, 1.0) * 0.25
    return score


def _ocr_detection_crop(image: Image.Image) -> str:
    gray = ImageOps.grayscale(image)
    upscaled = gray.resize((gray.width * 3, gray.height * 3), Image.Resampling.LANCZOS)
    contrasted = ImageOps.autocontrast(ImageEnhance.Contrast(upscaled).enhance(2.0))
    try:
        return run_rapid_text(contrasted, model_version="v5", use_det=True).raw_text
    except RapidOcrUnavailableError as exc:
        raise OcrUnavailableError(str(exc)) from exc

def _normalize_detection_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _matching_keywords(text: str, keywords: set[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword.casefold() in text]


def _fit_box(
    box: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    width, height = image_size
    x0, y0, x1, y1 = box
    x0 = min(max(0, x0), width - 1)
    y0 = min(max(0, y0), height - 1)
    x1 = min(max(x0 + 1, x1), width)
    y1 = min(max(y0 + 1, y1), height)
    return x0, y0, x1, y1


def parse_item_name_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for line in text.splitlines():
        value = _clean_line(line)
        if not value:
            continue
        lowered = value.lower()
        if lowered in UI_NOISE or any(noise in lowered for noise in UI_NOISE):
            continue
        has_cjk = re.search(r"[\u4e00-\u9fff]", value) is not None
        if (not has_cjk and len(value) < 3) or len(value) > 90:
            continue
        if not re.search(r"[A-Za-z\u4e00-\u9fff]", value):
            continue
        if value.count(" ") > 12:
            continue
        if _looks_like_ocr_gibberish(value):
            continue
        candidates.extend(_line_candidate_variants(value))

    deduped: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    if len(deduped) > 1:
        joined = " ".join(deduped)
        if len(joined) <= 120 and _normalize_candidate_key(deduped[0]) not in _normalize_candidate_key(
            deduped[1]
        ):
            deduped.insert(0, joined)
    return deduped[:5]


def _clean_line(value: str) -> str:
    value = value.replace("|", "I")
    value = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff .,'()/+&-]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .:-")
    value = re.sub(r"(?<=[0-9])\s+(?=[\u4e00-\u9fff])", "", value)
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", value)
    return value


def _normalize_candidate_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold())


def _line_candidate_variants(value: str) -> list[str]:
    variants: list[str] = []
    trimmed = _trim_tail_after_last_cjk(value)
    if trimmed and trimmed != value:
        variants.append(trimmed)
    variants.append(value)

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        key = variant.casefold()
        if key and key not in seen:
            seen.add(key)
            deduped.append(variant)
    return deduped


def _looks_like_ocr_gibberish(value: str) -> bool:
    has_cjk = re.search(r"[\u4e00-\u9fff]", value) is not None
    latin_tokens = re.findall(r"[A-Za-z]{2,}", value)
    suspicious = 0
    for token in latin_tokens:
        if len(token) < 5:
            continue
        rest = token[1:]
        if re.search(r"[A-Z]", rest) and re.search(r"[a-z]", rest):
            suspicious += 1
            if not has_cjk and len(token) >= 10 and not re.search(r"\d", value):
                return True
    return has_cjk and suspicious >= 2


def _trim_tail_after_last_cjk(value: str) -> str:
    matches = list(re.finditer(r"[\u4e00-\u9fff]", value))
    if not matches:
        return value
    last_cjk_end = matches[-1].end()
    tail = value[last_cjk_end:].strip()
    if not tail:
        return value
    if re.search(r"[\u4e00-\u9fff]", tail):
        return value
    return value[:last_cjk_end].strip(" .,:;()/[]{}-")
def _language_fallbacks(language: str) -> list[str]:
    requested = language.strip()
    options: list[str] = []
    if requested:
        options.append(requested)
        for part in re.split(r"[+\s]+", requested):
            part = part.strip()
            if part:
                options.append(part)
    options.append("")

    deduped: list[str] = []
    seen: set[str] = set()
    for value in options:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    return deduped
def _score_candidates(candidates: list[str]) -> int:
    if not candidates:
        return 0
    first = candidates[0]
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", first))
    latin_count = len(re.findall(r"[A-Za-z]", first))
    score = len(candidates) * 10 + min(len(first), 40)
    if cjk_count:
        score += 18 + cjk_count * 8
    if not cjk_count and latin_count:
        tokens = re.findall(r"[A-Za-z]+", first)
        uppercase_tokens = [token for token in tokens if token.isupper() and not re.search(r"\d", token)]
        if len(uppercase_tokens) >= 2 and len(first) <= 18:
            score -= 14
    return score


def _build_item_variants(image: Image.Image) -> list[OcrVariant]:
    gray = ImageOps.grayscale(image)
    upscaled = gray.resize((gray.width * 3, gray.height * 3), Image.Resampling.LANCZOS)
    contrasted = ImageOps.autocontrast(ImageEnhance.Contrast(upscaled).enhance(2.0))
    sharpened = ImageEnhance.Sharpness(contrasted).enhance(1.6)
    threshold = sharpened.point(lambda pixel: 255 if pixel > 135 else 0)
    inverted = ImageOps.invert(sharpened)
    return [
        OcrVariant("contrast", sharpened),
        OcrVariant("threshold", threshold),
        OcrVariant("inverted", inverted),
    ]
