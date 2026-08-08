from __future__ import annotations

import re
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np
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
TOOLTIP_BORDER_INSET = 2
TOOLTIP_REFERENCE_HEIGHT = 2160
TOOLTIP_DOUBLE_LINE_MIN_BORDER_HEIGHT = 96


def refine_tooltip_name_crop(
    search_path: Path,
    output_path: Path,
    padding: tuple[int, int, int, int] = (10, 8, 10, 8),
    cursor_anchor: tuple[int, int] | None = None,
    cursor_bottom_gap: int = 20,
    cursor_gap_tolerance: int = 36,
    cursor_left_gap: int | None = None,
    cursor_horizontal_tolerance: int = 12,
    max_box_width: int | None = None,
    client_right_edge_x: int | None = None,
    client_top_edge_y: int | None = None,
    client_edge_tolerance: int = 12,
) -> tuple[bool, list[str]]:
    """Find the tooltip bounds inside the hover search crop and save a tighter name crop."""
    image = Image.open(search_path).convert("RGB")
    refined_image, refined, details = refine_tooltip_name_image(
        image,
        padding=padding,
        cursor_anchor=cursor_anchor,
        cursor_bottom_gap=cursor_bottom_gap,
        cursor_gap_tolerance=cursor_gap_tolerance,
        cursor_left_gap=cursor_left_gap,
        cursor_horizontal_tolerance=cursor_horizontal_tolerance,
        max_box_width=max_box_width,
        client_right_edge_x=client_right_edge_x,
        client_top_edge_y=client_top_edge_y,
        client_edge_tolerance=client_edge_tolerance,
    )
    refined_image.save(output_path)
    return refined, details


def refine_tooltip_name_image(
    image: Image.Image,
    padding: tuple[int, int, int, int] = (10, 8, 10, 8),
    cursor_anchor: tuple[int, int] | None = None,
    cursor_bottom_gap: int = 20,
    cursor_gap_tolerance: int = 36,
    cursor_left_gap: int | None = None,
    cursor_horizontal_tolerance: int = 12,
    max_box_width: int | None = None,
    client_right_edge_x: int | None = None,
    client_top_edge_y: int | None = None,
    client_edge_tolerance: int = 12,
) -> tuple[Image.Image, bool, list[str]]:
    """Find the tooltip bounds and return the name crop without filesystem round-trips."""
    del padding  # Border detection already returns the exact content bounds used by the legacy path.
    image = image.convert("RGB")
    border_box = _find_tooltip_border_box(
        image,
        cursor_anchor=cursor_anchor,
        cursor_bottom_gap=cursor_bottom_gap,
        cursor_gap_tolerance=cursor_gap_tolerance,
        cursor_left_gap=cursor_left_gap,
        cursor_horizontal_tolerance=cursor_horizontal_tolerance,
        max_box_width=max_box_width,
        client_right_edge_x=client_right_edge_x,
        client_top_edge_y=client_top_edge_y,
        client_edge_tolerance=client_edge_tolerance,
    )
    if border_box is not None:
        crop_box = _inset_box(border_box, TOOLTIP_BORDER_INSET, image.size)
        refined_image = image.crop(crop_box)
        x0, y0, x1, y1 = border_box
        details = [f"border:{x1 - x0}x{y1 - y0}"]
        if cursor_anchor is not None:
            vertical_anchor = _cursor_vertical_anchor(
                y0,
                y1,
                cursor_anchor[1],
                cursor_bottom_gap,
                cursor_gap_tolerance,
            )
            if vertical_anchor is not None:
                _, gap = vertical_anchor
                details.append(f"cursor-gap:{gap}/{cursor_bottom_gap}")
            if cursor_left_gap is not None:
                expected_left = cursor_anchor[0] + cursor_left_gap
                if abs(x0 - expected_left) <= max(1, cursor_horizontal_tolerance):
                    details.append(f"cursor-left:{x0 - cursor_anchor[0]}/{cursor_left_gap}")
            if client_right_edge_x is not None:
                if abs(x1 - client_right_edge_x) <= max(1, client_edge_tolerance):
                    details.append(f"client-right:{x1}/{client_right_edge_x}")
            if client_top_edge_y is not None:
                if abs(y0 - client_top_edge_y) <= max(1, client_edge_tolerance):
                    details.append(f"client-top:{y0}/{client_top_edge_y}")
        return refined_image, True, details

    return image, False, []


def _find_tooltip_border_box(
    image: Image.Image,
    cursor_anchor: tuple[int, int] | None = None,
    cursor_bottom_gap: int = 20,
    cursor_gap_tolerance: int = 36,
    cursor_left_gap: int | None = None,
    cursor_horizontal_tolerance: int = 12,
    max_box_width: int | None = None,
    client_right_edge_x: int | None = None,
    client_top_edge_y: int | None = None,
    client_edge_tolerance: int = 12,
) -> tuple[int, int, int, int] | None:
    gray = ImageOps.grayscale(image)
    mask = _tooltip_border_mask(gray)
    runs = _horizontal_border_runs(mask, min_run=24)
    if not runs:
        return None

    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    width, height = image.size
    gray_pixels = np.asarray(gray, dtype=np.uint8)
    horizontally_anchored = cursor_anchor is not None and (
        cursor_left_gap is not None or client_right_edge_x is not None
    )
    # Cursor anchoring already provides the strong geometric guard. Keeping the
    # old search-crop-relative minimum here rejected valid 720p/900p tooltips,
    # whose border height scales down while the 420px search crop does not.
    min_box_height = 18 if horizontally_anchored else max(20, round(height * 0.08))
    max_box_height = max(76, round(height * 0.45))
    for index, (top_y, top_x0, top_x1) in enumerate(runs):
        for bottom_y, bottom_x0, bottom_x1 in runs[index + 1 :]:
            box_height = bottom_y - top_y
            if box_height > max_box_height:
                break
            if box_height < min_box_height:
                continue

            overlap_x0 = max(top_x0, bottom_x0)
            overlap_x1 = min(top_x1, bottom_x1)
            overlap = overlap_x1 - overlap_x0
            if horizontally_anchored:
                # A tooltip edge can merge into a much longer inventory/window
                # separator. The shared span preserves the cursor-anchored box;
                # taking the union would turn that separator into a false wide box.
                x0 = max(0, overlap_x0 - 2)
                x1 = min(width, overlap_x1 + 2)
            else:
                x0 = max(0, min(top_x0, bottom_x0) - 2)
                x1 = min(width, max(top_x1, bottom_x1) + 2)
            box_width = x1 - x0
            width_limit = min(850, width)
            if max_box_width is not None:
                width_limit = min(width_limit, max(38, max_box_width))
            if box_width < 38 or box_width > width_limit:
                continue
            if overlap < min(32, box_width * 0.35):
                continue

            horizontal_anchor_score = 0.0
            left_matches = False
            edge_matches = False
            if cursor_anchor is not None and (
                cursor_left_gap is not None or client_right_edge_x is not None
            ):
                if cursor_left_gap is not None:
                    expected_left = cursor_anchor[0] + cursor_left_gap
                    left_error = abs(x0 - expected_left)
                    left_tolerance = max(1, cursor_horizontal_tolerance)
                    if left_error <= left_tolerance:
                        left_matches = True
                        horizontal_anchor_score = max(
                            horizontal_anchor_score,
                            160.0 * (1.0 - left_error / left_tolerance),
                        )

                if client_right_edge_x is not None:
                    edge_error = abs(x1 - client_right_edge_x)
                    edge_tolerance = max(1, client_edge_tolerance)
                    if edge_error <= edge_tolerance:
                        edge_matches = True
                        horizontal_anchor_score = max(
                            horizontal_anchor_score,
                            160.0 * (1.0 - edge_error / edge_tolerance),
                        )

                if not left_matches and not edge_matches:
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
            bright_ratio, bright_area = _bright_interior_statistics(
                gray_pixels,
                (x0, top_y, x1, bottom_y),
            )
            if top_score + bottom_score < 0.8:
                continue
            if left_score + right_score < 0.08:
                continue
            if dark_ratio < 0.70:
                continue

            vertical_anchor: tuple[str, int] | None = None
            top_edge_matches = False
            if cursor_anchor is not None:
                vertical_anchor = _cursor_vertical_anchor(
                    top_y,
                    bottom_y,
                    cursor_anchor[1],
                    cursor_bottom_gap,
                    cursor_gap_tolerance,
                )
                if client_top_edge_y is not None:
                    top_edge_error = abs(top_y - client_top_edge_y)
                    top_edge_matches = (
                        top_edge_error <= max(1, client_edge_tolerance)
                        and cursor_anchor[1]
                        <= box_height + cursor_bottom_gap + cursor_gap_tolerance
                    )
                if vertical_anchor is None and not top_edge_matches:
                    continue

            strict_anchor_match = (
                (left_matches or edge_matches)
                and (vertical_anchor is not None or top_edge_matches)
                and top_score + bottom_score >= 1.35
                and left_score + right_score >= 0.16
                and dark_ratio >= 0.78
            )
            bright_pixels = round(bright_ratio * bright_area)
            if strict_anchor_match:
                # Once the full border and both cursor axes agree, this stage
                # only rejects a visually empty box. OCR and the local item
                # matcher decide whether the contained text is a valid item;
                # name length must not be inferred from pixel density here.
                if bright_pixels < 8:
                    continue
            else:
                # Tarkov 1.1 widened the tooltip while keeping roughly the same
                # amount of name text. Keep the legacy density requirement for
                # small/unanchored boxes, but accept a cursor-anchored large box
                # when it still contains a meaningful absolute amount of text.
                minimum_bright_ratio = max(0.015, min(0.055, 240 / max(1, bright_area)))
                if bright_ratio < minimum_bright_ratio:
                    continue

            score = (
                (top_score + bottom_score) * 80
                + (left_score + right_score) * 90
                + dark_ratio * 70
                + bright_ratio * 160
                + box_height * 0.25
                + horizontal_anchor_score
            )
            if cursor_anchor is None or (
                cursor_left_gap is None and client_right_edge_x is None
            ):
                score += box_width * 0.05
            if vertical_anchor is not None:
                _, gap = vertical_anchor
                gap_error = abs(gap - cursor_bottom_gap)
                gap_score = max(0.0, 1.0 - gap_error / max(1, cursor_gap_tolerance))
                score += gap_score * 130
            elif top_edge_matches:
                score += 130
            candidates.append((score, (x0, top_y, x1, bottom_y)))

    if not candidates:
        return None
    if cursor_anchor is not None:
        candidates = _penalize_parent_tooltip_boxes(candidates)
    return max(candidates, key=lambda value: value[0])[1]


def _cursor_vertical_anchor(
    top_y: int,
    bottom_y: int,
    cursor_y: int,
    expected_gap: int,
    tolerance: int,
) -> tuple[str, int] | None:
    """Describe whether a tooltip is immediately above the cursor."""
    maximum_gap = expected_gap + tolerance
    gap = cursor_y - bottom_y
    if not -6 <= gap <= maximum_gap:
        return None
    return "above", gap


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


def _tooltip_border_mask(gray: Image.Image) -> np.ndarray:
    pixels = np.asarray(gray, dtype=np.uint8)
    if pixels.ndim != 2 or pixels.size == 0:
        return np.zeros((0, 0), dtype=np.bool_)

    height, width = pixels.shape
    y_positions = np.arange(height)
    x_positions = np.arange(width)
    dark_neighbor = np.zeros((height, width), dtype=np.bool_)
    dark_neighbor |= pixels[np.minimum(y_positions + 2, height - 1), :] < 55
    dark_neighbor |= pixels[np.maximum(y_positions - 2, 0), :] < 55
    dark_neighbor |= pixels[:, np.minimum(x_positions + 2, width - 1)] < 55
    dark_neighbor |= pixels[:, np.maximum(x_positions - 2, 0)] < 55
    return (pixels >= 65) & (pixels <= 230) & dark_neighbor


def _horizontal_border_runs(
    mask: np.ndarray,
    min_run: int,
) -> list[tuple[int, int, int]]:
    if mask.ndim != 2 or mask.size == 0:
        return []
    padded = np.pad(mask.astype(np.int8, copy=False), ((0, 0), (1, 1)))
    transitions = np.diff(padded, axis=1)
    runs: list[tuple[int, int, int]] = []
    for y in range(mask.shape[0]):
        starts = np.flatnonzero(transitions[y] == 1)
        ends = np.flatnonzero(transitions[y] == -1)
        for x0, x1 in zip(starts.tolist(), ends.tolist()):
            if x1 - x0 >= min_run:
                runs.append((y, x0, x1))
    return runs


def _horizontal_line_score(mask: np.ndarray, y: int, x0: int, x1: int) -> float:
    if mask.ndim != 2 or y < 0 or y >= mask.shape[0] or x1 <= x0:
        return 0.0
    return float(np.count_nonzero(mask[y, x0:x1])) / (x1 - x0)


def _vertical_line_score(mask: np.ndarray, x: int, y0: int, y1: int) -> float:
    if mask.ndim != 2 or mask.size == 0 or y1 <= y0:
        return 0.0
    height, width = mask.shape
    left = max(0, x - 3)
    right = min(width, x + 4)
    if right <= left:
        return 0.0
    total = (right - left) * (y1 - y0 + 1)
    hits = np.count_nonzero(mask[max(0, y0) : min(height, y1 + 1), left:right])
    return float(hits) / total


def _dark_interior_ratio(
    pixels: np.ndarray,
    box: tuple[int, int, int, int],
) -> float:
    x0, y0, x1, y1 = box
    values = pixels[y0 + 3 : y1 - 2, x0 + 3 : x1 - 3]
    if values.size == 0:
        return 0.0
    return float(np.count_nonzero(values < 65)) / values.size


def _bright_interior_statistics(
    pixels: np.ndarray,
    box: tuple[int, int, int, int],
) -> tuple[float, int]:
    x0, y0, x1, y1 = box
    values = pixels[y0 + 3 : y1 - 2, x0 + 3 : x1 - 3]
    if values.size == 0:
        return 0.0, 0
    return float(np.count_nonzero(values > 115)) / values.size, int(values.size)


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
    line_count_hint: int | None = None,
) -> ParsedItemName:
    """OCR a UI crop and return likely item-name candidates."""
    return _run_rapidocr_item_name(crop_path, model_version, line_count_hint)


def run_item_name_ocr_image(
    image: Image.Image,
    model_version: str = "v5",
    line_count_hint: int | None = None,
) -> ParsedItemName:
    """OCR an in-memory UI crop and return likely item-name candidates."""
    return _run_rapidocr_item_name_image(
        image.convert("RGB"),
        model_version,
        line_count_hint,
    )


def _run_rapidocr_item_name(
    crop_path: Path,
    model_version: str = "v5",
    line_count_hint: int | None = None,
) -> ParsedItemName:
    image = Image.open(crop_path).convert("RGB")
    return _run_rapidocr_item_name_image(image, model_version, line_count_hint)


def _run_rapidocr_item_name_image(
    image: Image.Image,
    model_version: str = "v5",
    line_count_hint: int | None = None,
) -> ParsedItemName:
    best = ParsedItemName(raw_text="", candidates=[], variant_name="rapidocr-none")
    best_score = 0
    raw_parts: list[str] = []
    for attempt, recognition_score in _iter_item_name_ocr_attempts_with_score(
        image,
        model_version,
        line_count_hint,
    ):
        raw_parts.append(f"{attempt.variant_name}:{attempt.raw_text}")
        score = _score_candidates(attempt.candidates) + recognition_score
        if line_count_hint == 2 and "line-split" in attempt.variant_name and attempt.candidates:
            score += 60
        if score > best_score:
            best_score = score
            best = attempt

    if best.candidates:
        return best
    return ParsedItemName(
        raw_text="\n".join(raw_parts),
        candidates=[],
        variant_name="rapidocr:none",
    )


def iter_item_name_ocr_image_attempts(
    image: Image.Image,
    model_version: str = "v5",
    line_count_hint: int | None = None,
) -> Iterator[ParsedItemName]:
    """Yield progressively more expensive OCR attempts in preferred order."""
    for attempt, _ in _iter_item_name_ocr_attempts_with_score(
        image.convert("RGB"),
        model_version,
        line_count_hint,
    ):
        yield attempt


def _iter_item_name_ocr_attempts_with_score(
    image: Image.Image,
    model_version: str,
    line_count_hint: int | None,
) -> Iterator[tuple[ParsedItemName, int]]:
    if line_count_hint == 1:
        line_images = [image]
    else:
        line_images = _split_text_line_images(image)
        if line_count_hint == 2 and len(line_images) < 2:
            line_images = _force_split_double_line_image(image)
    variants = _build_item_variants(image)
    line_variants = [
        (f"lines:{index + 1}", _build_item_variants(line_image)[0].image)
        for index, line_image in enumerate(line_images)
        if line_image.width > 0 and line_image.height > 0
    ]
    variant_images = [(variant.name, variant.image) for variant in variants]
    if len(line_variants) > 1:
        variant_images.insert(0, ("line-split", line_variants))

    for variant_name, variant_payload in variant_images:
        started = time.perf_counter()
        try:
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
        except RapidOcrUnavailableError as exc:
            raise OcrUnavailableError(str(exc)) from exc
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        text = "\n".join(texts)
        candidates = parse_item_name_candidates(text)
        yield (
            ParsedItemName(
                raw_text=text,
                candidates=candidates,
                variant_name=f"rapidocr:{variant_name}:{elapsed_ms}ms",
            ),
            round(max(scores) * 10) if scores else 0,
        )


def tooltip_line_count_hint(
    crop_height: int,
    capture_height: int,
    reference_height: int = TOOLTIP_REFERENCE_HEIGHT,
) -> int:
    """Infer Tarkov 1.1's fixed one/two-line tooltip layout from border height."""
    if crop_height <= 0 or capture_height <= 0 or reference_height <= 0:
        return 1
    border_height = crop_height + TOOLTIP_BORDER_INSET * 2
    normalized_height = border_height * reference_height / capture_height
    return 2 if normalized_height >= TOOLTIP_DOUBLE_LINE_MIN_BORDER_HEIGHT else 1


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


def _force_split_double_line_image(image: Image.Image) -> list[Image.Image]:
    """Split an expected two-line tooltip at the darkest central row."""
    gray = np.asarray(ImageOps.grayscale(image), dtype=np.uint8)
    if gray.ndim != 2 or gray.size == 0 or image.height < 24:
        return [image]

    height, width = gray.shape
    first = max(1, round(height * 0.32))
    last = min(height - 1, round(height * 0.68))
    if last <= first:
        return [image]
    row_hits = np.count_nonzero(gray >= 125, axis=1)
    split_y = first + int(np.argmin(row_hits[first:last]))
    if split_y <= 2 or split_y >= height - 2:
        return [image]

    halves = [
        image.crop((0, 0, width, split_y)),
        image.crop((0, split_y, width, height)),
    ]
    trimmed = [_trim_line_to_bright_content(part) for part in halves]
    if any(part.width < 12 or part.height < 5 for part in trimmed):
        return [image]
    return trimmed


def _trim_line_to_bright_content(image: Image.Image) -> Image.Image:
    gray = np.asarray(ImageOps.grayscale(image), dtype=np.uint8)
    positions = np.argwhere(gray >= 125)
    if positions.size == 0:
        return image
    padding = max(2, round(image.height * 0.10))
    y0, x0 = positions.min(axis=0)
    y1, x1 = positions.max(axis=0)
    return image.crop(
        (
            max(0, int(x0) - padding),
            max(0, int(y0) - padding),
            min(image.width, int(x1) + padding + 1),
            min(image.height, int(y1) + padding + 1),
        )
    )


def detect_inventory_tab_crop(crop_path: Path) -> tuple[bool, list[str], str]:
    """Detect the inventory screen from an already-captured top-left tab crop."""
    tab_crop = Image.open(crop_path)
    INVENTORY_TAB_DEBUG_PATH.parent.mkdir(exist_ok=True)
    if crop_path != INVENTORY_TAB_DEBUG_PATH:
        tab_crop.save(INVENTORY_TAB_DEBUG_PATH)

    return detect_inventory_tab_image(tab_crop)


def detect_inventory_tab_image(tab_crop: Image.Image) -> tuple[bool, list[str], str]:
    """Detect the inventory screen directly from an in-memory crop."""
    tab_crop = tab_crop.convert("RGB")

    tab_visual_score = _active_tab_visual_score(tab_crop)
    if tab_visual_score >= 1.0:
        return True, [f"tab:visual:{tab_visual_score:.2f}"], ""

    tab_text = _ocr_detection_crop(tab_crop)
    normalized_tab = _normalize_detection_text(tab_text)
    tab_found = _matching_keywords(normalized_tab, {"装备", "gear"})
    return bool(tab_found), [f"tab:{keyword}" for keyword in tab_found], tab_text

def detect_character_header_image(tab_crop: Image.Image) -> tuple[bool, list[str], str]:
    """Detect the character screen from its stable achievements-tab label."""
    tab_text = _ocr_detection_crop(tab_crop.convert("RGB"))
    normalized_tab = _normalize_detection_text(tab_text)
    tab_found = _matching_keywords(
        normalized_tab,
        {"成就", "achievement", "achievements"},
    )
    return bool(tab_found), [f"header:{keyword}" for keyword in tab_found], tab_text


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
    line_values: list[str] = []
    for line in text.splitlines():
        value = _clean_line(line)
        if not value:
            continue
        lowered = value.lower()
        # Navigation labels are noise only as standalone OCR lines. Item names
        # such as "地形调查地图" legitimately contain one of these words.
        if lowered in UI_NOISE:
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
        line_values.append(value)
        candidates.extend(_line_candidate_variants(value))

    deduped: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    if len(line_values) > 1:
        joined = _join_wrapped_name_lines(line_values)
        joined_key = joined.casefold()
        if joined and len(joined) <= 120 and joined_key not in seen:
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


def _join_wrapped_name_lines(lines: list[str]) -> str:
    tokens: list[str] = []
    for line in lines:
        next_tokens = line.split()
        if not next_tokens:
            continue
        if not tokens:
            tokens.extend(next_tokens)
            continue

        overlap = 0
        for size in range(min(len(tokens), len(next_tokens)), 0, -1):
            previous_keys = [_normalize_candidate_key(token) for token in tokens[-size:]]
            next_keys = [_normalize_candidate_key(token) for token in next_tokens[:size]]
            if previous_keys == next_keys:
                overlap = size
                break
        tokens.extend(next_tokens[overlap:])
    return " ".join(tokens)


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
