from __future__ import annotations

import ctypes
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


class DisplayFilterError(RuntimeError):
    """Raised when the Windows gamma ramp cannot be read or written."""


GammaRampData = tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]
ColorEffectData = tuple[float, ...]


@dataclass(frozen=True)
class DisplayFilterBaseline:
    backend: str
    data: GammaRampData | ColorEffectData

    @property
    def label(self) -> str:
        if self.backend == "gamma_ramp":
            return "Windows Gamma Ramp"
        return "Windows 全屏颜色矩阵（兼容模式）"


class _GammaRamp(ctypes.Structure):
    _fields_ = [
        ("red", ctypes.c_ushort * 256),
        ("green", ctypes.c_ushort * 256),
        ("blue", ctypes.c_ushort * 256),
    ]


class _MagColorEffect(ctypes.Structure):
    _fields_ = [("transform", ctypes.c_float * 25)]


def build_gamma_ramp(preset: dict[str, Any]) -> GammaRampData:
    gamma = _positive_float(preset.get("gamma", 1.0), 1.0)
    black_lift = _clamp(_float(preset.get("black_lift", 0.0), 0.0), 0.0, 0.35)
    gain = _clamp(_float(preset.get("gain", 1.0), 1.0), 0.5, 1.25)
    contrast = _clamp(_float(preset.get("contrast", 1.0), 1.0), 0.65, 1.45)

    channel: list[int] = []
    last = 0
    for index in range(256):
        source = index / 255.0
        lifted = black_lift + (1.0 - black_lift) * (source**gamma)
        contrasted = ((lifted - 0.5) * contrast) + 0.5
        value = _clamp(contrasted * gain, 0.0, 1.0)
        raw = int(round(value * 65535.0))
        raw = max(last, raw)
        channel.append(raw)
        last = raw
    return (tuple(channel), tuple(channel), tuple(channel))


def get_gamma_ramp() -> GammaRampData:
    hdc = _screen_dc()
    ramp = _GammaRamp()
    try:
        ok = _gdi32().GetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        if not ok:
            raise DisplayFilterError("GetDeviceGammaRamp failed.")
        return (
            tuple(int(value) for value in ramp.red),
            tuple(int(value) for value in ramp.green),
            tuple(int(value) for value in ramp.blue),
        )
    finally:
        _user32().ReleaseDC(None, hdc)


def set_gamma_ramp(data: GammaRampData) -> None:
    hdc = _screen_dc()
    ramp = _to_ctypes_ramp(data)
    try:
        ok = _gdi32().SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        if not ok:
            raise DisplayFilterError("SetDeviceGammaRamp failed.")
    finally:
        _user32().ReleaseDC(None, hdc)


def apply_preset(preset: dict[str, Any]) -> None:
    set_gamma_ramp(build_gamma_ramp(preset))


def start_display_filter(preset: dict[str, Any]) -> DisplayFilterBaseline:
    """Capture the current display state and apply a preset with a safe fallback."""
    gamma_error = ""
    try:
        baseline = get_gamma_ramp()
        set_gamma_ramp(build_gamma_ramp(preset))
    except DisplayFilterError as exc:
        gamma_error = str(exc)
    else:
        return DisplayFilterBaseline("gamma_ramp", baseline)

    try:
        _magnification_initialize()
        baseline_effect = _get_fullscreen_color_effect()
        _set_fullscreen_color_effect(_build_color_effect(preset))
    except DisplayFilterError as exc:
        _magnification_uninitialize()
        raise DisplayFilterError(
            f"Gamma Ramp 不可用（{gamma_error}）；兼容颜色矩阵也失败（{exc}）。"
        ) from exc
    return DisplayFilterBaseline("magnification", baseline_effect)


def update_display_filter(
    preset: dict[str, Any], baseline: DisplayFilterBaseline
) -> None:
    if baseline.backend == "gamma_ramp":
        set_gamma_ramp(build_gamma_ramp(preset))
        return
    if baseline.backend == "magnification":
        _set_fullscreen_color_effect(_build_color_effect(preset))
        return
    raise DisplayFilterError(f"Unknown display-filter backend: {baseline.backend}")


def restore_display_filter(baseline: DisplayFilterBaseline) -> None:
    if baseline.backend == "gamma_ramp":
        if not isinstance(baseline.data, tuple):
            raise DisplayFilterError("Invalid Gamma Ramp baseline.")
        set_gamma_ramp(baseline.data)  # type: ignore[arg-type]
        return
    if baseline.backend == "magnification":
        _set_fullscreen_color_effect(baseline.data)  # type: ignore[arg-type]
        _magnification_uninitialize()
        return
    raise DisplayFilterError(f"Unknown display-filter backend: {baseline.backend}")


def _build_color_effect(preset: dict[str, Any]) -> ColorEffectData:
    """Approximate the nonlinear curve with a desktop-wide linear color matrix."""
    channel = build_gamma_ramp(preset)[0]
    xs = [index / 255.0 for index in range(256)]
    ys = [value / 65535.0 for value in channel]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    variance = sum((value - mean_x) ** 2 for value in xs)
    slope = sum(
        (x_value - mean_x) * (y_value - mean_y)
        for x_value, y_value in zip(xs, ys)
    ) / variance
    offset = mean_y - slope * mean_x
    slope = _clamp(slope, 0.1, 2.0)
    offset = _clamp(offset, -0.5, 0.5)

    values = [0.0] * 25
    for index in (0, 6, 12):
        values[index] = slope
    values[18] = 1.0
    values[20] = offset
    values[21] = offset
    values[22] = offset
    values[24] = 1.0
    return tuple(values)


def _magnification_initialize() -> None:
    if os.name != "nt":
        raise DisplayFilterError("Windows full-screen color effects are unavailable.")
    if not _magnification().MagInitialize():
        raise DisplayFilterError("MagInitialize failed.")


def _magnification_uninitialize() -> None:
    if os.name != "nt":
        return
    try:
        _magnification().MagUninitialize()
    except OSError:
        pass


def _get_fullscreen_color_effect() -> ColorEffectData:
    effect = _MagColorEffect()
    if not _magnification().MagGetFullscreenColorEffect(ctypes.byref(effect)):
        raise DisplayFilterError("MagGetFullscreenColorEffect failed.")
    return tuple(float(value) for value in effect.transform)


def _set_fullscreen_color_effect(data: Sequence[float]) -> None:
    if len(data) != 25:
        raise DisplayFilterError("Color effect must contain 25 matrix values.")
    effect = _MagColorEffect()
    for index, value in enumerate(data):
        effect.transform[index] = float(value)
    if not _magnification().MagSetFullscreenColorEffect(ctypes.byref(effect)):
        raise DisplayFilterError("MagSetFullscreenColorEffect failed.")


def _magnification() -> ctypes.WinDLL:
    library = ctypes.WinDLL("Magnification", use_last_error=True)
    library.MagInitialize.restype = ctypes.c_bool
    library.MagUninitialize.restype = ctypes.c_bool
    library.MagGetFullscreenColorEffect.argtypes = [ctypes.c_void_p]
    library.MagGetFullscreenColorEffect.restype = ctypes.c_bool
    library.MagSetFullscreenColorEffect.argtypes = [ctypes.c_void_p]
    library.MagSetFullscreenColorEffect.restype = ctypes.c_bool
    return library


def _screen_dc() -> int:
    if os.name != "nt":
        raise DisplayFilterError("Windows Gamma Ramp is only available on Windows.")
    hdc = _user32().GetDC(None)
    if not hdc:
        raise DisplayFilterError("GetDC failed.")
    return int(hdc)


def _user32() -> ctypes.WinDLL:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.GetDC.restype = ctypes.c_void_p
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.ReleaseDC.restype = ctypes.c_int
    return user32


def _gdi32() -> ctypes.WinDLL:
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi32.GetDeviceGammaRamp.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.GetDeviceGammaRamp.restype = ctypes.c_bool
    gdi32.SetDeviceGammaRamp.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SetDeviceGammaRamp.restype = ctypes.c_bool
    return gdi32


def _to_ctypes_ramp(data: GammaRampData) -> _GammaRamp:
    if len(data) != 3:
        raise DisplayFilterError("Gamma ramp must contain red, green, and blue channels.")
    ramp = _GammaRamp()
    for channel_name, source in zip(("red", "green", "blue"), data):
        values = _validate_channel(source)
        target = getattr(ramp, channel_name)
        for index, value in enumerate(values):
            target[index] = value
    return ramp


def _validate_channel(values: Sequence[int]) -> tuple[int, ...]:
    if len(values) != 256:
        raise DisplayFilterError("Each gamma ramp channel must contain 256 values.")
    cleaned = tuple(_clamp_int(value, 0, 65535) for value in values)
    if any(cleaned[index] > cleaned[index + 1] for index in range(255)):
        raise DisplayFilterError("Gamma ramp values must be monotonic.")
    return cleaned


def _float(value: object, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _positive_float(value: object, fallback: float) -> float:
    return max(0.1, _float(value, fallback))


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _clamp_int(value: object, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = minimum
    return min(max(number, minimum), maximum)
