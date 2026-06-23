from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.item_ocr import run_item_name_ocr
from app.prices import PriceLookupError, TarkovPriceClient


OUT_DIR = PROJECT_ROOT / "debug" / "synthetic_ocr"
TEMP_IMAGE = OUT_DIR / "_current_tooltip.png"
FAILURE_IMAGE_DIR = OUT_DIR / "failures"
DEFAULT_FONT_PATHS = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
]


@dataclass(frozen=True)
class TestCase:
    item_id: str
    name: str
    short_name: str
    zh_name: str
    zh_short_name: str
    render_name: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic EFT tooltip crops and benchmark OCR match accuracy."
    )
    parser.add_argument("--mode", default="pve", choices=["pve", "regular"])
    parser.add_argument(
        "--engines",
        default="rapidocr,tesseract",
        help="Comma-separated engines: rapidocr,rapidocr_v5,tesseract,rapidocr+tesseract",
    )
    parser.add_argument(
        "--name-source",
        default="zh",
        choices=["zh", "en", "both"],
        help="Which official item names to render into tooltips.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit number of items for a smoke run.")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-width", type=int, default=640)
    parser.add_argument("--font-size", type=int, default=19)
    parser.add_argument("--save-failures", action="store_true")
    parser.add_argument("--output-prefix", default="")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.save_failures:
        FAILURE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    client = TarkovPriceClient()
    items = client._get_items(args.mode)  # noqa: SLF001 - benchmark script needs stable IDs.
    cases = _build_cases(items, args.name_source)
    cases = cases[args.offset :]
    if args.limit > 0:
        cases = cases[: args.limit]

    font = _load_font(args.font_size)
    engines = [engine.strip() for engine in args.engines.split(",") if engine.strip()]
    prefix = f"{args.output_prefix}_" if args.output_prefix else ""
    csv_path = OUT_DIR / f"{prefix}{args.mode}_{args.name_source}_results.csv"
    summary_path = OUT_DIR / f"{prefix}{args.mode}_{args.name_source}_summary.json"
    suggestions_path = OUT_DIR / f"{prefix}{args.mode}_{args.name_source}_alias_suggestions.json"

    rows: list[dict[str, Any]] = []
    started_all = time.perf_counter()
    for index, case in enumerate(cases, start=1):
        image = render_tooltip(case.render_name, font, max_width=args.max_width)
        image.save(TEMP_IMAGE)

        for engine in engines:
            started = time.perf_counter()
            ocr_result = run_item_name_ocr(TEMP_IMAGE, "", "chi_sim+eng", engine)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            match = _lookup_candidates(client, ocr_result.candidates, args.mode, items)
            status = _status_for_match(case, match)
            row = {
                "engine": engine,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "variant": ocr_result.variant_name,
                "target_id": case.item_id,
                "target_name": case.name,
                "target_zh_name": case.zh_name,
                "render_name": case.render_name,
                "ocr_candidates": " | ".join(ocr_result.candidates),
                "matched_id": match.get("id", ""),
                "matched_name": match.get("name", ""),
                "matched_zh_name": match.get("zhName", ""),
                "matched_confidence": match.get("confidence", ""),
                "matched_query": match.get("query", ""),
            }
            rows.append(row)

            if args.save_failures and status != "ok":
                safe_id = _safe_filename(case.item_id or str(index))
                image.save(FAILURE_IMAGE_DIR / f"{engine}_{status}_{safe_id}.png")

        if index % 25 == 0 or index == len(cases):
            elapsed = time.perf_counter() - started_all
            print(
                f"{index}/{len(cases)} items, {len(rows)} rows, "
                f"{elapsed / max(index, 1):.2f}s/item"
            )

    _write_csv(csv_path, rows)
    summary = _summarize(rows, len(cases), engines)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    suggestions = _build_alias_suggestions(rows)
    suggestions_path.write_text(
        json.dumps(suggestions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"CSV: {csv_path}")
    print(f"Summary: {summary_path}")
    print(f"Suggestions: {suggestions_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _build_cases(items: list[dict[str, Any]], name_source: str) -> list[TestCase]:
    cases: list[TestCase] = []
    for item in items:
        base = TestCase(
            item_id=str(item.get("id") or ""),
            name=str(item.get("name") or ""),
            short_name=str(item.get("shortName") or ""),
            zh_name=str(item.get("zhName") or ""),
            zh_short_name=str(item.get("zhShortName") or ""),
            render_name="",
        )
        names: list[str] = []
        if name_source in {"zh", "both"}:
            names.append(base.zh_name or base.name)
        if name_source in {"en", "both"}:
            names.append(base.name)
        seen: set[str] = set()
        for name in names:
            name = name.strip()
            key = name.casefold()
            if not name or key in seen:
                continue
            seen.add(key)
            cases.append(
                TestCase(
                    item_id=base.item_id,
                    name=base.name,
                    short_name=base.short_name,
                    zh_name=base.zh_name,
                    zh_short_name=base.zh_short_name,
                    render_name=name,
                )
            )
    return cases


def render_tooltip(text: str, font: ImageFont.FreeTypeFont, max_width: int = 640) -> Image.Image:
    lines = _wrap_text(text, font, max_width=max_width - 34)
    probe = Image.new("RGB", (16, 16))
    draw = ImageDraw.Draw(probe)
    bboxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    text_width = max(max(1, bbox[2] - bbox[0]) for bbox in bboxes)
    line_height = max(max(18, bbox[3] - bbox[1]) for bbox in bboxes)
    width = min(max_width, max(150, text_width + 34))
    height = max(34, len(lines) * line_height + (len(lines) - 1) * 3 + 18)

    image = Image.new("RGB", (width, height), (15, 18, 18))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, height - 1), outline=(84, 89, 72), width=1)
    draw.rectangle((1, 1, width - 2, height - 2), outline=(26, 27, 23), width=1)
    draw.rectangle((3, 3, width - 4, height - 4), fill=(24, 26, 25))

    y = 8
    for line in lines:
        draw.text((16, y), line, fill=(210, 214, 207), font=font)
        y += line_height + 3
    return image


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    probe = Image.new("RGB", (16, 16))
    draw = ImageDraw.Draw(probe)

    def width(value: str) -> int:
        bbox = draw.textbbox((0, 0), value, font=font)
        return bbox[2] - bbox[0]

    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9.,'()/+&-]*|[\u4e00-\u9fff]|\\S", text)
    lines: list[str] = []
    current = ""
    for token in tokens:
        glue = "" if not current or re.match(r"[\u4e00-\u9fff]", token) else " "
        candidate = f"{current}{glue}{token}" if current else token
        if current and width(candidate) > max_width:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [text]


def _lookup_candidates(
    client: TarkovPriceClient,
    candidates: list[str],
    mode: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        price = client.lookup_candidates(candidates, mode)
    except PriceLookupError:
        return {}
    item = _find_item_for_price(price.name, price.zh_name, price.short_name, items)
    return {
        "id": str(item.get("id") or "") if item else "",
        "name": price.name,
        "zhName": price.zh_name,
        "confidence": round(price.confidence, 4),
        "query": price.matched_name,
    }


def _find_item_for_price(
    name: str,
    zh_name: str,
    short_name: str,
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in items:
        if item.get("name") == name and (not zh_name or item.get("zhName") == zh_name):
            return item
    for item in items:
        if item.get("name") == name or item.get("zhName") == zh_name or item.get("shortName") == short_name:
            return item
    return None


def _status_for_match(case: TestCase, match: dict[str, Any]) -> str:
    if not match:
        return "no_match"
    return "ok" if match.get("id") == case.item_id else "wrong_match"


def _summarize(rows: list[dict[str, Any]], item_count: int, engines: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"item_count": item_count, "engines": {}}
    for engine in engines:
        engine_rows = [row for row in rows if row["engine"] == engine]
        statuses = defaultdict(int)
        for row in engine_rows:
            statuses[row["status"]] += 1
        elapsed_values = [float(row["elapsed_ms"]) for row in engine_rows]
        summary["engines"][engine] = {
            "rows": len(engine_rows),
            "ok": statuses["ok"],
            "no_match": statuses["no_match"],
            "wrong_match": statuses["wrong_match"],
            "accuracy": round(statuses["ok"] / max(1, len(engine_rows)), 4),
            "avg_ms": round(sum(elapsed_values) / max(1, len(elapsed_values)), 2),
            "max_ms": round(max(elapsed_values) if elapsed_values else 0, 2),
        }
    return summary


def _build_alias_suggestions(rows: list[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row["status"] == "ok":
            continue
        candidate = str(row.get("matched_query") or row.get("ocr_candidates") or "").strip()
        if not candidate:
            continue
        first_candidate = candidate.split("|", 1)[0].strip()
        if not first_candidate:
            continue
        target = str(row.get("target_zh_name") or row.get("target_name") or "").strip()
        if target:
            grouped[first_candidate].add(target)
    return {
        candidate: sorted(targets)[0]
        for candidate, targets in sorted(grouped.items())
        if len(targets) == 1
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in DEFAULT_FONT_PATHS:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:80]


if __name__ == "__main__":
    raise SystemExit(main())
