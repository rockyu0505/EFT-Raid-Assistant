from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from app.models import ParsedOcr
from app.tesseract_runtime import configure_tesseract


TIMER_RE = re.compile(r"\b(\d{1,2})\s*:\s*(\d{2})\s*:\s*(\d{2})\b")


class OcrUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrVariant:
    name: str
    image: Image.Image


def run_ocr(crop_path: Path, tesseract_cmd: str = "") -> ParsedOcr:
    """Run OCR on a timer strip and return the best parsed countdowns."""
    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise OcrUnavailableError("pytesseract is not installed.") from exc

    configure_tesseract(pytesseract, tesseract_cmd)

    image = Image.open(crop_path)
    variants = _build_variants(image)

    best = ParsedOcr(raw_text="", timers=[], variant_name="none")
    for variant in variants:
        text = pytesseract.image_to_string(
            variant.image,
            config="--psm 6 -c tessedit_char_whitelist=0123456789:",
        )
        timers = parse_timers(text)
        if len(timers) > len(best.timers):
            best = ParsedOcr(raw_text=text, timers=timers, variant_name=variant.name)
        if len(timers) >= 9:
            break

    return best


def parse_timers(text: str) -> list[str]:
    """Parse HH:MM:SS-like OCR output and repair a few safe OCR mistakes."""
    timers: list[str] = []
    normalized = text.replace(";", ":").replace(".", ":").replace(",", ":")

    for match in TIMER_RE.finditer(normalized):
        hour = int(match.group(1))
        minute = int(match.group(2))
        second = int(match.group(3))

        if minute >= 60 or second >= 60:
            continue

        if hour > 8 and hour < 100:
            repaired = hour % 10
            if repaired <= 8:
                hour = repaired

        if hour > 8:
            continue

        timers.append(f"{hour:02d}:{minute:02d}:{second:02d}")

    return timers


def is_valid_timer(value: str) -> bool:
    return timer_to_seconds(value) is not None


def timer_to_seconds(value: str) -> int | None:
    match = TIMER_RE.search(value.strip())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3))
    if hour > 8 or minute >= 60 or second >= 60:
        return None
    return hour * 3600 + minute * 60 + second


def _build_variants(image: Image.Image) -> list[OcrVariant]:
    gray = ImageOps.grayscale(image)
    upscaled = gray.resize((gray.width * 4, gray.height * 4), Image.Resampling.LANCZOS)
    contrasted = ImageOps.autocontrast(ImageEnhance.Contrast(upscaled).enhance(2.2))
    threshold = contrasted.point(lambda pixel: 255 if pixel > 150 else 0)
    inverted_threshold = ImageOps.invert(contrasted).point(lambda pixel: 255 if pixel > 120 else 0)
    return [
        OcrVariant("contrast", contrasted),
        OcrVariant("threshold", threshold),
        OcrVariant("inverted-threshold", inverted_threshold),
    ]
