from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

from app.config import APP_DIR
from app.models import ParsedItemName
from app.ocr import OcrUnavailableError, OcrVariant
from app.tesseract_runtime import configure_tesseract


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

INVENTORY_KEYWORDS = {
    "overall",
    "gear",
    "health",
    "skills",
    "map",
    "tasks",
    "traders",
    "hideout",
    "pockets",
    "backpack",
    "tactical rig",
    "pouch",
    "loot",
    "inspect",
    "linked search",
    "required search",
    "filter by item",
    "总览",
    "装备",
    "健康",
    "技能",
    "地图",
    "任务",
    "成就",
    "返回",
    "搜索",
    "整理栏位",
    "背包",
    "快捷栏",
    "角色",
    "商人",
    "跳蚤市场",
}

DETAIL_KEYWORDS = {
    "inspect",
    "linked search",
    "required search",
    "filter by item",
}

DEFAULT_INVENTORY_TAB_BOX = (105, 0, 235, 48)
DEFAULT_GAME_MODE_BOX = (0, 1088, 360, 1152)
BASE_SCREEN_SIZE = (2048, 1152)
INVENTORY_TAB_DEBUG_PATH = APP_DIR / "debug" / "last_inventory_tab.png"
GAME_MODE_DEBUG_PATH = APP_DIR / "debug" / "last_game_mode.png"

BAD_CAPTURE_KEYWORDS = {
    "塔科夫局内助手",
    "识别物品并查价",
    "查询手动名称",
    "Anaconda Prompt",
    "Google Chrome",
    "MainWindow",
    "Codex",
    "Escapefromtarkov",
    "EscapeFromTarkov",
}


def detect_bad_capture_overlay(
    screenshot_path: Path,
    tesseract_cmd: str = "",
    language: str = "chi_sim+eng",
) -> tuple[bool, list[str], str]:
    """Detect desktop overlays or this app window covering the game capture."""
    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise OcrUnavailableError("pytesseract is not installed.") from exc

    configure_tesseract(pytesseract, tesseract_cmd)

    image = Image.open(screenshot_path)
    image.thumbnail((1600, 900), Image.Resampling.LANCZOS)
    text = _ocr_detection_crop(pytesseract, image, language, "--psm 11")
    normalized = _normalize_detection_text(text)
    found = _matching_keywords(normalized, BAD_CAPTURE_KEYWORDS)
    return bool(found), found, text


def refine_tooltip_name_crop(
    search_path: Path,
    output_path: Path,
    tesseract_cmd: str = "",
    language: str = "chi_sim+eng",
    padding: tuple[int, int, int, int] = (10, 8, 10, 8),
) -> tuple[bool, list[str]]:
    """Find the tooltip bounds inside the hover search crop and save a tighter name crop."""
    image = Image.open(search_path).convert("RGB")
    border_box = _find_tooltip_border_box(image)
    if border_box is not None:
        crop_box = _inset_box(border_box, 2, image.size)
        image.crop(crop_box).save(output_path)
        x0, y0, x1, y1 = border_box
        return True, [f"border:{x1 - x0}x{y1 - y0}"]

    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise OcrUnavailableError("pytesseract is not installed.") from exc

    configure_tesseract(pytesseract, tesseract_cmd)

    boxes = _ocr_word_boxes(pytesseract, image, language)
    if not boxes:
        return False, []

    clusters = _cluster_text_boxes(boxes)
    if not clusters:
        return False, []

    cluster = max(clusters, key=_cluster_score)
    x0 = min(box["left"] for box in cluster)
    y0 = min(box["top"] for box in cluster)
    x1 = max(box["left"] + box["width"] for box in cluster)
    y1 = max(box["top"] + box["height"] for box in cluster)
    pad_left, pad_top, pad_right, pad_bottom = padding
    crop_box = _fit_box(
        (x0 - pad_left, y0 - pad_top, x1 + pad_right, y1 + pad_bottom),
        image.size,
    )
    image.crop(crop_box).save(output_path)
    return True, [str(box["text"]) for box in cluster]


def _find_tooltip_border_box(image: Image.Image) -> tuple[int, int, int, int] | None:
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
            if dark_ratio < 0.42:
                continue
            if bright_ratio < 0.055:
                continue

            score = (
                (top_score + bottom_score) * 80
                + (left_score + right_score) * 90
                + dark_ratio * 70
                + bright_ratio * 160
                + box_width * 0.05
                + box_height * 0.25
            )
            candidates.append((score, (x0, top_y, x1, bottom_y)))

    if not candidates:
        return None
    return max(candidates, key=lambda value: value[0])[1]


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


def _ocr_word_boxes(
    pytesseract: object,
    image: Image.Image,
    language: str,
) -> list[dict[str, int | str]]:
    scale = 2
    gray = ImageOps.grayscale(image)
    upscaled = gray.resize((gray.width * scale, gray.height * scale), Image.Resampling.LANCZOS)
    contrasted = ImageOps.autocontrast(ImageEnhance.Contrast(upscaled).enhance(2.2))
    data = _image_to_data(pytesseract, contrasted, language, "--psm 11")

    boxes: list[dict[str, int | str]] = []
    count = len(data.get("text", []))
    for index in range(count):
        text = _clean_line(str(data["text"][index]))
        if not text:
            continue
        lowered = text.lower()
        if lowered in UI_NOISE or any(noise in lowered for noise in UI_NOISE):
            continue
        if not re.search(r"[A-Za-z\u4e00-\u9fff]", text):
            continue
        try:
            confidence = float(data.get("conf", ["-1"])[index])
        except (TypeError, ValueError):
            confidence = -1.0
        if confidence < 0:
            continue

        left = round(int(data["left"][index]) / scale)
        top = round(int(data["top"][index]) / scale)
        width = max(1, round(int(data["width"][index]) / scale))
        height = max(1, round(int(data["height"][index]) / scale))
        boxes.append(
            {
                "text": text,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
        )
    return boxes


def _cluster_text_boxes(boxes: list[dict[str, int | str]]) -> list[list[dict[str, int | str]]]:
    lines: list[list[dict[str, int | str]]] = []
    for box in sorted(boxes, key=lambda value: (int(value["top"]), int(value["left"]))):
        placed = False
        center_y = int(box["top"]) + int(box["height"]) // 2
        for line in lines:
            line_top = min(int(item["top"]) for item in line)
            line_bottom = max(int(item["top"]) + int(item["height"]) for item in line)
            if line_top - 6 <= center_y <= line_bottom + 6:
                line.append(box)
                placed = True
                break
        if not placed:
            lines.append([box])

    for line in lines:
        line.sort(key=lambda value: int(value["left"]))
    lines.sort(key=lambda line: min(int(item["top"]) for item in line))

    clusters: list[list[dict[str, int | str]]] = []
    for line in lines:
        if not clusters:
            clusters.append(line)
            continue
        previous = clusters[-1]
        previous_bottom = max(int(item["top"]) + int(item["height"]) for item in previous)
        line_top = min(int(item["top"]) for item in line)
        horizontal_overlap = _line_horizontal_overlap(previous, line)
        if line_top - previous_bottom <= 14 and horizontal_overlap:
            previous.extend(line)
        else:
            clusters.append(line)
    return clusters


def _line_horizontal_overlap(
    first: list[dict[str, int | str]],
    second: list[dict[str, int | str]],
) -> bool:
    first_left = min(int(item["left"]) for item in first)
    first_right = max(int(item["left"]) + int(item["width"]) for item in first)
    second_left = min(int(item["left"]) for item in second)
    second_right = max(int(item["left"]) + int(item["width"]) for item in second)
    overlap = min(first_right, second_right) - max(first_left, second_left)
    return overlap > -24


def _cluster_score(cluster: list[dict[str, int | str]]) -> float:
    text_length = sum(len(str(box["text"])) for box in cluster)
    width = max(int(box["left"]) + int(box["width"]) for box in cluster) - min(
        int(box["left"]) for box in cluster
    )
    height = max(int(box["top"]) + int(box["height"]) for box in cluster) - min(
        int(box["top"]) for box in cluster
    )
    return text_length * 12 + width * 0.08 + height * 0.04


def run_item_name_ocr(
    crop_path: Path,
    tesseract_cmd: str = "",
    language: str = "chi_sim+eng",
) -> ParsedItemName:
    """OCR a UI crop and return likely item-name candidates."""
    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise OcrUnavailableError("pytesseract is not installed.") from exc

    configure_tesseract(pytesseract, tesseract_cmd)

    image = Image.open(crop_path)
    variants = _build_item_variants(image)

    best = ParsedItemName(raw_text="", candidates=[], variant_name="none")
    for variant in variants:
        text = _image_to_string(pytesseract, variant.image, language, "--psm 6")
        candidates = parse_item_name_candidates(text)
        if _score_candidates(candidates) > _score_candidates(best.candidates):
            best = ParsedItemName(raw_text=text, candidates=candidates, variant_name=variant.name)
        if candidates:
            break

    return best


def detect_inventory_screen(
    screenshot_path: Path,
    tesseract_cmd: str = "",
    language: str = "chi_sim+eng",
    tab_box: tuple[int, int, int, int] = DEFAULT_INVENTORY_TAB_BOX,
) -> tuple[bool, list[str], str]:
    """Use the top-left active equipment tab to detect the inventory screen."""
    image = Image.open(screenshot_path)
    tab_crop = image.crop(_fit_box(_scale_box(tab_box, image.size), image.size))
    INVENTORY_TAB_DEBUG_PATH.parent.mkdir(exist_ok=True)
    tab_crop.save(INVENTORY_TAB_DEBUG_PATH)
    tab_visual_score = _active_tab_visual_score(tab_crop)
    if tab_visual_score >= 1.0:
        return True, [f"tab:visual:{tab_visual_score:.2f}"], ""

    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise OcrUnavailableError("pytesseract is not installed.") from exc

    configure_tesseract(pytesseract, tesseract_cmd)

    tab_text = _ocr_detection_crop(pytesseract, tab_crop, language, "--psm 7")
    normalized_tab = _normalize_detection_text(tab_text)
    tab_found = _matching_keywords(normalized_tab, {"装备", "gear"})
    if tab_found:
        return True, [f"tab:{keyword}" for keyword in tab_found], tab_text

    broad = image.copy()
    broad.thumbnail((1600, 900), Image.Resampling.LANCZOS)
    text = _ocr_detection_crop(pytesseract, broad, language, "--psm 11")
    normalized = _normalize_detection_text(text)
    found = _matching_keywords(normalized, INVENTORY_KEYWORDS)
    has_detail_marker = any(keyword in found for keyword in DETAIL_KEYWORDS)
    return has_detail_marker or len(found) >= 2, found, tab_text + "\n" + text


def detect_inventory_tab_crop(
    crop_path: Path,
    tesseract_cmd: str = "",
    language: str = "chi_sim+eng",
) -> tuple[bool, list[str], str]:
    """Detect the inventory screen from an already-captured top-left tab crop."""
    tab_crop = Image.open(crop_path)
    INVENTORY_TAB_DEBUG_PATH.parent.mkdir(exist_ok=True)
    if crop_path != INVENTORY_TAB_DEBUG_PATH:
        tab_crop.save(INVENTORY_TAB_DEBUG_PATH)

    tab_visual_score = _active_tab_visual_score(tab_crop)
    if tab_visual_score >= 1.0:
        return True, [f"tab:visual:{tab_visual_score:.2f}"], ""

    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise OcrUnavailableError("pytesseract is not installed.") from exc

    configure_tesseract(pytesseract, tesseract_cmd)

    tab_text = _ocr_detection_crop(pytesseract, tab_crop, language, "--psm 7")
    normalized_tab = _normalize_detection_text(tab_text)
    tab_found = _matching_keywords(normalized_tab, {"瑁呭", "gear"})
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


def detect_game_mode(
    screenshot_path: Path,
    tesseract_cmd: str = "",
    language: str = "chi_sim+eng",
    mode_box: tuple[int, int, int, int] = DEFAULT_GAME_MODE_BOX,
) -> tuple[str | None, str]:
    """Detect PvE/PvP from the bottom-left game version strip."""
    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise OcrUnavailableError("pytesseract is not installed.") from exc

    configure_tesseract(pytesseract, tesseract_cmd)

    image = Image.open(screenshot_path)
    crop = image.crop(_fit_box(_scale_box(mode_box, image.size), image.size))
    GAME_MODE_DEBUG_PATH.parent.mkdir(exist_ok=True)
    crop.save(GAME_MODE_DEBUG_PATH)

    texts = _ocr_game_mode_variants(pytesseract, crop, language)
    joined = "\n".join(texts)
    normalized = _normalize_game_mode_text(joined)
    if "pve" in normalized or "ve" in normalized:
        return "pve", joined
    if "pvp" in normalized or "vp" in normalized:
        return "regular", joined
    return None, joined


def detect_game_mode_crop(
    crop_path: Path,
    tesseract_cmd: str = "",
    language: str = "chi_sim+eng",
) -> tuple[str | None, str]:
    """Detect PvE/PvP from an already-captured bottom-left mode crop."""
    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise OcrUnavailableError("pytesseract is not installed.") from exc

    configure_tesseract(pytesseract, tesseract_cmd)

    crop = Image.open(crop_path)
    GAME_MODE_DEBUG_PATH.parent.mkdir(exist_ok=True)
    if crop_path != GAME_MODE_DEBUG_PATH:
        crop.save(GAME_MODE_DEBUG_PATH)

    texts = _ocr_game_mode_variants(pytesseract, crop, language)
    joined = "\n".join(texts)
    normalized = _normalize_game_mode_text(joined)
    if "pve" in normalized or "ve" in normalized:
        return "pve", joined
    if "pvp" in normalized or "vp" in normalized:
        return "regular", joined
    return None, joined


def _ocr_game_mode_variants(
    pytesseract: object,
    image: Image.Image,
    language: str,
) -> list[str]:
    gray = ImageOps.grayscale(image)
    upscaled = gray.resize((gray.width * 6, gray.height * 6), Image.Resampling.LANCZOS)
    contrasted = ImageOps.autocontrast(ImageEnhance.Contrast(upscaled).enhance(3.0))
    sharpened = ImageEnhance.Sharpness(contrasted).enhance(1.8)
    variants = [
        sharpened,
        ImageOps.invert(sharpened),
        upscaled.point(lambda pixel: 255 if pixel > 90 else 0),
        ImageOps.invert(upscaled.point(lambda pixel: 255 if pixel > 60 else 0)),
    ]

    texts: list[str] = []
    for variant in variants:
        for config in ("--psm 7", "--psm 8", "--psm 11"):
            text = _image_to_string(pytesseract, variant, language, config)
            if text.strip():
                texts.append(text)
    return texts


def _normalize_game_mode_text(text: str) -> str:
    value = text.casefold()
    value = value.replace("上", "e")
    value = value.replace("巳", "e")
    value = value.replace("曰", "e")
    value = value.replace("|", "")
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value)
    return value


def _ocr_detection_crop(
    pytesseract: object,
    image: Image.Image,
    language: str,
    config: str,
) -> str:
    gray = ImageOps.grayscale(image)
    upscaled = gray.resize((gray.width * 3, gray.height * 3), Image.Resampling.LANCZOS)
    contrasted = ImageOps.autocontrast(ImageEnhance.Contrast(upscaled).enhance(2.0))
    return _image_to_string(pytesseract, contrasted, language, config)


def _normalize_detection_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _matching_keywords(text: str, keywords: set[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword.casefold() in text]


def _scale_box(
    box: tuple[int, int, int, int],
    current_size: tuple[int, int],
    base_size: tuple[int, int] = BASE_SCREEN_SIZE,
) -> tuple[int, int, int, int]:
    x_scale = current_size[0] / base_size[0]
    y_scale = current_size[1] / base_size[1]
    x0, y0, x1, y1 = box
    return (
        round(x0 * x_scale),
        round(y0 * y_scale),
        round(x1 * x_scale),
        round(y1 * y_scale),
    )


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


def _image_to_string(
    pytesseract: object,
    image: Image.Image,
    language: str,
    config: str,
) -> str:
    last_language_error: Exception | None = None
    for lang in _language_fallbacks(language):
        try:
            if lang:
                return pytesseract.image_to_string(image, lang=lang, config=config)
            return pytesseract.image_to_string(image, config=config)
        except Exception as exc:
            if not _is_tesseract_language_error(exc):
                raise
            last_language_error = exc
    if last_language_error is not None:
        raise last_language_error
    return pytesseract.image_to_string(image, config=config)


def _image_to_data(
    pytesseract: object,
    image: Image.Image,
    language: str,
    config: str,
) -> dict[str, list[Any]]:
    output_type = pytesseract.Output.DICT
    last_language_error: Exception | None = None
    for lang in _language_fallbacks(language):
        try:
            if lang:
                return pytesseract.image_to_data(
                    image,
                    lang=lang,
                    config=config,
                    output_type=output_type,
                )
            return pytesseract.image_to_data(image, config=config, output_type=output_type)
        except Exception as exc:
            if not _is_tesseract_language_error(exc):
                raise
            last_language_error = exc
    if last_language_error is not None:
        raise last_language_error
    return pytesseract.image_to_data(image, config=config, output_type=output_type)


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


def _is_tesseract_language_error(exc: Exception) -> bool:
    error = str(exc)
    return (
        "Failed loading language" in error
        or "Tesseract couldn't load" in error
        or "Error opening data file" in error
        or "Could not initialize tesseract" in error
    )


def _score_candidates(candidates: list[str]) -> int:
    if not candidates:
        return 0
    return len(candidates) * 10 + min(len(candidates[0]), 40)


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
