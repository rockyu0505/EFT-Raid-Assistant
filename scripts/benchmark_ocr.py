from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.item_ocr import run_item_name_ocr
from app.prices import PriceLookupError, TarkovPriceClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark item OCR backends on cropped tooltip images.")
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--mode", default="pve", choices=["pve", "regular"])
    parser.add_argument(
        "--engines",
        default="tesseract,rapidocr,rapidocr+tesseract",
        help="Comma-separated OCR engines to test.",
    )
    args = parser.parse_args()

    client = TarkovPriceClient()
    engines = [value.strip() for value in args.engines.split(",") if value.strip()]
    for image_path in args.images:
        print(f"\n== {image_path} ==")
        for engine in engines:
            started = time.perf_counter()
            result = run_item_name_ocr(image_path, "", "chi_sim+eng", engine)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            query = result.candidates[0] if result.candidates else ""
            try:
                price = client.lookup_candidates(result.candidates, args.mode) if query else None
            except PriceLookupError as exc:
                print(
                    f"{engine:20} {elapsed_ms:8.1f} ms | {result.variant_name:28} "
                    f"| OCR={_safe(query)} | match=ERR {_safe(str(exc))}"
                )
                continue

            if price is None:
                print(
                    f"{engine:20} {elapsed_ms:8.1f} ms | {result.variant_name:28} "
                    f"| OCR=<none> | match=<none>"
                )
            else:
                display_name = price.zh_name or price.name
                print(
                    f"{engine:20} {elapsed_ms:8.1f} ms | {result.variant_name:28} "
                    f"| OCR={_safe(query)} | match={_safe(display_name)} ({price.confidence:.0%})"
                )
    return 0


def _safe(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")


if __name__ == "__main__":
    raise SystemExit(main())
