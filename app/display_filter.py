from __future__ import annotations

import ctypes
import os
from collections.abc import Sequence
from typing import Any


class DisplayFilterError(RuntimeError):
    """Raised when the Windows gamma ramp cannot be read or written."""


GammaRampData = tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]


class _GammaRamp(ctypes.Structure):
    _fields_ = [
        ("red", ctypes.c_ushort * 256),
        ("green", ctypes.c_ushort * 256),
        ("blue", ctypes.c_ushort * 256),
    ]


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
