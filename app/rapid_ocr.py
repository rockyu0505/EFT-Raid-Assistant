from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from PIL import Image


class RapidOcrUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class RapidText:
    raw_text: str
    lines: list[str]
    scores: list[float]
    variant_name: str


_ENGINES: dict[str, object] = {}
_ENGINE_INIT_MS: dict[str, int] = {}


def run_rapid_text(
    image: Image.Image,
    *,
    model_version: str = "v5",
    use_det: bool = True,
    use_cls: bool = False,
    use_rec: bool = True,
) -> RapidText:
    try:
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RapidOcrUnavailableError("numpy is not installed.") from exc

    engine = _get_engine(model_version)
    started = time.perf_counter()
    result = engine(
        np.array(image.convert("RGB")),
        use_det=use_det,
        use_cls=use_cls,
        use_rec=use_rec,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    lines = [str(text).strip() for text in (getattr(result, "txts", None) or []) if str(text).strip()]
    scores = [float(score) for score in (getattr(result, "scores", None) or [])]
    key = _engine_key(model_version)
    return RapidText(
        raw_text="\n".join(lines),
        lines=lines,
        scores=scores,
        variant_name=f"rapidocr-{key}:{elapsed_ms}ms:init{_ENGINE_INIT_MS.get(key, 0)}ms",
    )


def _get_engine(model_version: str) -> object:
    key = _engine_key(model_version)
    if key in _ENGINES:
        _ENGINE_INIT_MS[key] = 0
        return _ENGINES[key]

    try:
        from rapidocr import OCRVersion, RapidOCR  # type: ignore
    except ImportError as exc:
        raise RapidOcrUnavailableError("rapidocr is not installed.") from exc

    started = time.perf_counter()
    params: dict[str, Any] | None = None
    if key == "v5":
        params = {"Rec.ocr_version": OCRVersion.PPOCRV5}
    _ENGINES[key] = RapidOCR(params=params)
    _ENGINE_INIT_MS[key] = round((time.perf_counter() - started) * 1000)
    return _ENGINES[key]


def _engine_key(model_version: str) -> str:
    value = model_version.strip().casefold().replace("-", "_")
    return "v5" if value in {"v5", "rapidocr_v5", "ppocrv5"} else "v4"
