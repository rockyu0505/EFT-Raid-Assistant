from __future__ import annotations

import os
import sys
from pathlib import Path


def configure_tesseract(pytesseract: object, tesseract_cmd: str = "") -> None:
    """Configure pytesseract for source runs and PyInstaller builds."""
    if tesseract_cmd.strip():
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd.strip()
        return

    runtime_dir = _runtime_dir()
    exe_candidates = [
        runtime_dir / "tesseract" / "tesseract.exe",
        runtime_dir / "Library" / "bin" / "tesseract.exe",
    ]
    for exe_path in exe_candidates:
        if exe_path.exists():
            pytesseract.pytesseract.tesseract_cmd = str(exe_path)
            break

    tessdata_candidates = [
        runtime_dir / "tessdata",
        runtime_dir / "tesseract" / "tessdata",
        runtime_dir / "Library" / "share" / "tessdata",
    ]
    for tessdata_path in tessdata_candidates:
        if tessdata_path.exists():
            os.environ.setdefault("TESSDATA_PREFIX", str(tessdata_path))
            break


def _runtime_dir() -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir)
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
