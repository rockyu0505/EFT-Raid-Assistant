from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from app.config import APP_DIR
from app.hideout import HideoutQuantity, HideoutScan
from app.rapid_ocr import RapidOcrUnavailableError, run_rapid_text


HIDEOUT_OCR_TEXT_PATH = APP_DIR / "debug" / "last_hideout_ocr.txt"
HIDEOUT_PANEL_PATH = APP_DIR / "debug" / "last_hideout_panel.png"
HIDEOUT_TITLE_PATH = APP_DIR / "debug" / "last_hideout_title.png"
HIDEOUT_REQUIREMENTS_PATH = APP_DIR / "debug" / "last_hideout_requirements.png"
HIDEOUT_QUANTITIES_PATH = APP_DIR / "debug" / "last_hideout_quantities.png"


@dataclass(frozen=True)
class HideoutPanelBox:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def run_hideout_ocr(
    screenshot_path: Path,
    station_names: list[str],
) -> HideoutScan:
    """OCR the stable hideout upgrade panel instead of the whole screenshot."""
    image = Image.open(screenshot_path).convert("RGB")
    panel = _locate_hideout_panel(image)

    raw_parts: list[str] = []
    if panel is None:
        scan = _run_fullscreen_fallback(image, station_names, raw_parts)
        _write_raw_text(raw_parts)
        return scan

    crops = _panel_crops(image, panel)
    for path, crop in [
        (HIDEOUT_PANEL_PATH, crops["panel"]),
        (HIDEOUT_TITLE_PATH, crops["title"]),
        (HIDEOUT_REQUIREMENTS_PATH, crops["requirements"]),
        (HIDEOUT_QUANTITIES_PATH, crops["quantities"]),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(path)

    title_candidates = _ocr_candidates(crops["title"])
    requirements_candidates = _ocr_candidates(crops["requirements"])
    quantities_candidates = _ocr_candidates(crops["quantities"])

    title_text = _best_text(
        title_candidates,
        lambda value: (100 if _parse_station_name(value, station_names) else 0) + len(_normalize(value)),
    )
    requirements_text = _best_text(
        requirements_candidates,
        lambda value: (100 if _parse_target_level(value) is not None else 0)
        + len(_parse_quantities(value)) * 10
        + min(len(value), 120),
    )
    quantities_text = _best_text(
        quantities_candidates,
        lambda value: len(_parse_quantities(value)) * 100 + min(len(value), 120),
    )

    raw_text = "\n".join([title_text, requirements_text, quantities_text])
    target_level = _parse_target_level(requirements_text)
    scan = HideoutScan(
        raw_text=raw_text,
        station_name=_parse_station_name(title_text, station_names)
        or _parse_station_name(raw_text, station_names),
        current_level=(target_level - 1 if target_level is not None else _parse_current_level(raw_text)),
        quantities=_parse_quantities(f"{requirements_text}\n{quantities_text}"),
        variant_name=f"panel:{panel.width}x{panel.height}",
        target_level=target_level,
    )
    raw_parts.append(
        "== panel ==\n"
        f"box={panel.left},{panel.top},{panel.right},{panel.bottom}\n\n"
        f"== selected title ==\n{title_text}\n\n"
        f"== selected requirements ==\n{requirements_text}\n\n"
        f"== selected quantities ==\n{quantities_text}\n\n"
        f"== all title candidates ==\n{_format_candidates(title_candidates)}\n\n"
        f"== all requirements candidates ==\n{_format_candidates(requirements_candidates)}\n\n"
        f"== all quantities candidates ==\n{_format_candidates(quantities_candidates)}"
    )
    _write_raw_text(raw_parts)
    return scan


def hideout_ocr_text_path() -> Path:
    return HIDEOUT_OCR_TEXT_PATH


def hideout_panel_debug_path() -> Path:
    return HIDEOUT_PANEL_PATH


def hideout_quantities_debug_path() -> Path:
    return HIDEOUT_QUANTITIES_PATH


def _locate_hideout_panel(image: Image.Image) -> HideoutPanelBox | None:
    gray = np.asarray(ImageOps.grayscale(image), dtype=np.float32)
    height, width = gray.shape
    mask = (gray > 30) & (gray < 210)

    bottom_search = (
        int(width * 0.45),
        int(width * 0.995),
        int(height * 0.78),
        int(height * 0.91),
    )
    bx0, bx1, by0, by1 = bottom_search
    row_scores = mask[by0:by1, bx0:bx1].sum(axis=1)
    if row_scores.size == 0:
        return None
    bottom = by0 + int(row_scores.argmax())
    if int(row_scores.max()) < int(width * 0.25):
        return None

    y0 = int(height * 0.04)
    y1 = max(y0 + 1, bottom)
    left = _best_vertical_line(mask, int(width * 0.45), int(width * 0.56), y0, y1)
    right = _best_vertical_line(mask, int(width * 0.94), int(width * 0.995), y0, y1)
    if left is None or right is None or right - left < int(width * 0.30):
        return None

    top_y0 = int(height * 0.04)
    top_y1 = max(top_y0 + 1, bottom - int(height * 0.25))
    top_scores = mask[top_y0:top_y1, left:right].sum(axis=1)
    if top_scores.size == 0:
        return None
    top = top_y0 + int(top_scores.argmax())
    if int(top_scores.max()) < int((right - left) * 0.35):
        return None

    padding = max(2, round(height / 1080))
    return HideoutPanelBox(
        max(0, left - padding),
        max(0, top - padding),
        min(width, right + padding + 1),
        min(height, bottom + padding + 1),
    )


def _best_vertical_line(
    mask: np.ndarray,
    x0: int,
    x1: int,
    y0: int,
    y1: int,
) -> int | None:
    if x1 <= x0 or y1 <= y0:
        return None
    scores = mask[y0:y1, x0:x1].sum(axis=0)
    if scores.size == 0:
        return None
    index = int(scores.argmax())
    if int(scores[index]) < int((y1 - y0) * 0.20):
        return None
    return x0 + index


def _panel_crops(image: Image.Image, box: HideoutPanelBox) -> dict[str, Image.Image]:
    left, top, right, bottom = box.left, box.top, box.right, box.bottom
    width, height = box.width, box.height

    def crop_rel(x0: float, y0: float, x1: float, y1: float) -> Image.Image:
        return image.crop(
            (
                left + round(width * x0),
                top + round(height * y0),
                left + round(width * x1),
                top + round(height * y1),
            )
        )

    return {
        "panel": image.crop((left, top, right, bottom)),
        "title": crop_rel(0.10, 0.02, 0.50, 0.17),
        "requirements": crop_rel(0.30, 0.24, 0.75, 0.54),
        "quantities": crop_rel(0.05, 0.34, 0.96, 0.72),
    }


def _ocr_candidates(image: Image.Image) -> list[tuple[str, str, str]]:
    candidates: list[tuple[str, str, str]] = []
    for variant_name, variant in _build_variants(image, max_width=1800, upscale=2.0):
        try:
            rapid = run_rapid_text(variant, model_version="v5", use_det=True)
        except RapidOcrUnavailableError as exc:
            raise RuntimeError(str(exc)) from exc
        if rapid.raw_text.strip():
            candidates.append((variant_name, rapid.variant_name, rapid.raw_text))
    return candidates


def _best_text(
    candidates: list[tuple[str, str, str]],
    scorer: Callable[[str], int],
) -> str:
    if not candidates:
        return ""
    return max(candidates, key=lambda candidate: scorer(candidate[2]))[2]


def _format_candidates(candidates: list[tuple[str, str, str]]) -> str:
    return "\n\n".join(
        f"[{variant_name} {config}]\n{text}"
        for variant_name, config, text in candidates
    )


def _run_fullscreen_fallback(
    image: Image.Image,
    station_names: list[str],
    raw_parts: list[str],
) -> HideoutScan:
    best = HideoutScan(
        raw_text="",
        station_name=None,
        current_level=None,
        quantities=[],
        variant_name="none",
    )
    best_score = -1
    for variant_name, variant in _build_variants(image, max_width=2560, upscale=1.0):
        try:
            text = run_rapid_text(variant, model_version="v5", use_det=True).raw_text
        except RapidOcrUnavailableError as exc:
            raise RuntimeError(str(exc)) from exc
        target_level = _parse_target_level(text)
        scan = HideoutScan(
            raw_text=text,
            station_name=_parse_station_name(text, station_names),
            current_level=(target_level - 1 if target_level is not None else _parse_current_level(text)),
            quantities=_parse_quantities(text),
            variant_name=f"fullscreen:{variant_name}",
            target_level=target_level,
        )
        score = _score_scan(scan)
        raw_parts.append(f"== fullscreen {variant_name} ==\n{text}")
        if score > best_score:
            best_score = score
            best = scan
    return best


def _build_variants(
    image: Image.Image,
    max_width: int,
    upscale: float,
) -> list[tuple[str, Image.Image]]:
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, max(1, round(image.height * ratio))))
    if upscale > 1.0:
        image = image.resize(
            (max(1, round(image.width * upscale)), max(1, round(image.height * upscale)))
        )
    gray = ImageOps.grayscale(image)
    contrast = ImageEnhance.Contrast(gray).enhance(1.85)
    sharp = ImageEnhance.Sharpness(contrast).enhance(1.4)
    return [
        ("contrast", sharp),
        ("gray", gray),
    ]


def _parse_station_name(text: str, station_names: list[str]) -> str | None:
    normalized_text = _normalize(text)
    for station in station_names:
        key = _normalize(station)
        if key and key in normalized_text:
            return station

    best_name: str | None = None
    best_score = 0.0
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for station in station_names:
        station_key = _normalize(station)
        for line in lines:
            line_key = _normalize(line)
            if not line_key:
                continue
            score = SequenceMatcher(None, station_key, line_key).ratio()
            if score > best_score:
                best_score = score
                best_name = station
    return best_name if best_score >= 0.58 else None


def _parse_target_level(text: str) -> int | None:
    normalized = text.replace("：", ":").replace("﹕", ":")
    patterns = [
        r"升级\s*要求\s*[:：]?\s*(\d{1,2})",
        r"(?:upgrade|requirements?)\s*[:：]?\s*(\d{1,2})",
        r"(?:瑕|要).{0,4}(?:姹|求).{0,4}(\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue
        value = _safe_int(match.group(1))
        if value is not None and 1 <= value <= 6:
            return value
    for line in normalized.splitlines():
        if "/" in line:
            continue
        numbers = [_safe_int(match.group(1)) for match in re.finditer(r"(?<!\d)(\d{1,2})(?!\d)", line)]
        numbers = [value for value in numbers if value is not None and 1 <= value <= 6]
        if numbers:
            return numbers[-1]
    return None


def _parse_current_level(text: str) -> int | None:
    normalized = text.replace("：", ":").replace("﹕", ":")
    patterns = [
        r"(?:当前|目前)?\s*(?:等级|级别|level|lvl)\s*[:：]?\s*(\d{1,2})",
        r"\bL\s*(\d{1,2})\b",
        r"(\d{1,2})\s*级",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue
        value = _safe_int(match.group(1))
        if value is not None and 0 <= value <= 6:
            return value
    return None


def _parse_quantities(text: str) -> list[HideoutQuantity]:
    cleaned = (
        text.replace("／", "/")
        .replace("∕", "/")
        .replace("|", "/")
        .replace("\\", "/")
        .replace("O", "0")
        .replace("o", "0")
    )
    quantities: list[HideoutQuantity] = []
    number = r"(?:\d{1,3}(?:[\s,]\d{3})+|\d{1,6})"
    pattern = re.compile(rf"(?<!\d)({number})\s*/\s*({number})(?!\d)")
    for match in pattern.finditer(cleaned):
        owned = _safe_int(match.group(1))
        required = _safe_int(match.group(2))
        if owned is None or required is None:
            continue
        owned = _trim_noisy_owned_prefix(owned, required)
        if required <= 0 or owned > max(required * 3, required + 20):
            continue
        quantities.append(HideoutQuantity(owned=owned, required=required))
    return quantities


def _trim_noisy_owned_prefix(owned: int, required: int) -> int:
    if required <= 0 or owned <= required:
        return owned
    required_width = max(1, len(str(required)))
    text = str(owned)
    for width in range(1, min(required_width + 1, len(text)) + 1):
        suffix = int(text[-width:])
        if suffix <= required:
            return suffix
    return owned


def _score_scan(scan: HideoutScan) -> int:
    score = len(scan.quantities) * 8
    if scan.station_name:
        score += 40
    if scan.target_level is not None:
        score += 30
    if scan.current_level is not None:
        score += 20
    score += min(len(scan.raw_text), 2000) // 120
    return score


def _write_raw_text(parts: list[str]) -> None:
    HIDEOUT_OCR_TEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HIDEOUT_OCR_TEXT_PATH.write_text("\n\n".join(parts), encoding="utf-8")


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold())


def _safe_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(re.sub(r"[\s,]+", "", str(value)))
    except (TypeError, ValueError):
        return None
