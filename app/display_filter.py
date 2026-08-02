from __future__ import annotations

import ctypes
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from ctypes import wintypes
from typing import Any


class DisplayFilterError(RuntimeError):
    """Raised when the Windows gamma ramp cannot be read or written."""


GammaRampData = tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]
ColorEffectData = tuple[float, ...]


@dataclass(frozen=True)
class DisplayFilterBaseline:
    backend: str
    data: GammaRampData | ColorEffectData
    target_id: str = ""

    @property
    def label(self) -> str:
        if self.backend == "gamma_ramp":
            target = f" · {self.target_id}" if self.target_id else ""
            return f"Windows Gamma Ramp{target}"
        return "Windows 全屏颜色矩阵（兼容模式）"


@dataclass(frozen=True)
class DisplayTarget:
    target_id: str
    adapter_name: str
    monitor_name: str
    primary: bool = False
    geometry: tuple[int, int, int, int] | None = None

    @property
    def label(self) -> str:
        match = re.search(r"DISPLAY(\d+)$", self.target_id, re.IGNORECASE)
        number = match.group(1) if match else self.target_id
        primary = "（主显示器）" if self.primary else ""
        monitor = self.monitor_name.strip() or "通用显示器"
        adapter = self.adapter_name.strip() or "未知显示适配器"
        geometry = ""
        if self.geometry is not None:
            left, top, width, height = self.geometry
            geometry = f" · {width}×{height} @ {left},{top}"
        return f"显示器 {number}{primary} · {monitor} · {adapter}{geometry}"


class _GammaRamp(ctypes.Structure):
    _fields_ = [
        ("red", ctypes.c_ushort * 256),
        ("green", ctypes.c_ushort * 256),
        ("blue", ctypes.c_ushort * 256),
    ]


class _MagColorEffect(ctypes.Structure):
    _fields_ = [("transform", ctypes.c_float * 25)]


class _DisplayDeviceW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MonitorInfoExW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _Rect),
        ("rcWork", _Rect),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


_DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
_DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
_DISPLAY_DEVICE_MIRRORING_DRIVER = 0x00000008


def enumerate_display_targets() -> list[DisplayTarget]:
    """Return active Windows display outputs with monitor and adapter names."""
    if os.name != "nt":
        return []
    targets: list[DisplayTarget] = []
    geometries = _monitor_geometries()
    index = 0
    while True:
        adapter = _enum_display_device(None, index)
        if adapter is None:
            break
        index += 1
        flags = int(adapter.StateFlags)
        if not flags & _DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            continue
        if flags & _DISPLAY_DEVICE_MIRRORING_DRIVER:
            continue
        target_id = str(adapter.DeviceName).strip()
        if not target_id:
            continue
        monitor_name = ""
        monitor_index = 0
        while True:
            monitor = _enum_display_device(target_id, monitor_index)
            if monitor is None:
                break
            monitor_index += 1
            candidate = str(monitor.DeviceString).strip()
            if candidate:
                monitor_name = candidate
                break
        targets.append(
            DisplayTarget(
                target_id=target_id,
                adapter_name=str(adapter.DeviceString).strip(),
                monitor_name=monitor_name,
                primary=bool(flags & _DISPLAY_DEVICE_PRIMARY_DEVICE),
                geometry=geometries.get(target_id.casefold()),
            )
        )
    return sorted(targets, key=lambda target: (not target.primary, target.target_id))


def preferred_display_target_id(
    preferred: object,
    targets: Sequence[DisplayTarget] | None = None,
) -> str:
    available = list(targets) if targets is not None else enumerate_display_targets()
    requested = str(preferred or "").strip()
    if requested and any(target.target_id == requested for target in available):
        return requested
    for target in available:
        if target.primary:
            return target.target_id
    return available[0].target_id if available else ""


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


def get_gamma_ramp(target_id: str = "") -> GammaRampData:
    hdc, is_device_dc = _gamma_dc(target_id)
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
        _release_gamma_dc(hdc, is_device_dc)


def set_gamma_ramp(data: GammaRampData, target_id: str = "") -> None:
    hdc, is_device_dc = _gamma_dc(target_id)
    ramp = _to_ctypes_ramp(data)
    try:
        ok = _gdi32().SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        if not ok:
            raise DisplayFilterError("SetDeviceGammaRamp failed.")
    finally:
        _release_gamma_dc(hdc, is_device_dc)


def apply_preset(preset: dict[str, Any], target_id: str = "") -> None:
    set_gamma_ramp(build_gamma_ramp(preset), target_id)


def start_display_filter(
    preset: dict[str, Any], target_id: str = ""
) -> DisplayFilterBaseline:
    """Capture the current display state and apply a preset with a safe fallback."""
    gamma_error = ""
    try:
        baseline = get_gamma_ramp(target_id)
        set_gamma_ramp(build_gamma_ramp(preset), target_id)
    except DisplayFilterError as exc:
        gamma_error = str(exc)
    else:
        return DisplayFilterBaseline("gamma_ramp", baseline, target_id)

    if target_id:
        raise DisplayFilterError(
            f"目标显示器 {target_id} 不支持 Windows Gamma Ramp（{gamma_error}）。"
            "为避免误改其他屏幕，按显示器模式不会自动回退到全屏兼容滤镜。"
        )

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
        set_gamma_ramp(build_gamma_ramp(preset), baseline.target_id)
        return
    if baseline.backend == "magnification":
        _set_fullscreen_color_effect(_build_color_effect(preset))
        return
    raise DisplayFilterError(f"Unknown display-filter backend: {baseline.backend}")


def restore_display_filter(baseline: DisplayFilterBaseline) -> None:
    if baseline.backend == "gamma_ramp":
        if not isinstance(baseline.data, tuple):
            raise DisplayFilterError("Invalid Gamma Ramp baseline.")
        set_gamma_ramp(baseline.data, baseline.target_id)  # type: ignore[arg-type]
        return
    if baseline.backend == "magnification":
        _set_fullscreen_color_effect(baseline.data)  # type: ignore[arg-type]
        _magnification_uninitialize()
        return
    raise DisplayFilterError(f"Unknown display-filter backend: {baseline.backend}")


def probe_display_target(target_id: str) -> None:
    """Verify that a target Gamma Ramp can be read and written without changing it."""
    baseline = get_gamma_ramp(target_id)
    set_gamma_ramp(baseline, target_id)


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


def _gamma_dc(target_id: str) -> tuple[int, bool]:
    if not target_id:
        return _screen_dc(), False
    if os.name != "nt":
        raise DisplayFilterError("Windows Gamma Ramp is only available on Windows.")
    hdc = _gdi32().CreateDCW("DISPLAY", target_id, None, None)
    if not hdc:
        raise DisplayFilterError(f"CreateDCW failed for {target_id}.")
    return int(hdc), True


def _release_gamma_dc(hdc: int, is_device_dc: bool) -> None:
    if is_device_dc:
        _gdi32().DeleteDC(hdc)
    else:
        _user32().ReleaseDC(None, hdc)


def _enum_display_device(
    device_name: str | None, index: int
) -> _DisplayDeviceW | None:
    device = _DisplayDeviceW()
    device.cb = ctypes.sizeof(device)
    if not _user32().EnumDisplayDevicesW(
        device_name,
        int(index),
        ctypes.byref(device),
        0,
    ):
        return None
    return device


def _monitor_geometries() -> dict[str, tuple[int, int, int, int]]:
    if os.name != "nt":
        return {}
    geometries: dict[str, tuple[int, int, int, int]] = {}
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(_Rect),
        wintypes.LPARAM,
    )

    def collect(
        monitor_handle: int,
        _monitor_dc: int,
        _monitor_rect: ctypes.POINTER(_Rect),
        _data: int,
    ) -> bool:
        info = _MonitorInfoExW()
        info.cbSize = ctypes.sizeof(info)
        if _user32().GetMonitorInfoW(monitor_handle, ctypes.byref(info)):
            rect = info.rcMonitor
            geometries[str(info.szDevice).casefold()] = (
                int(rect.left),
                int(rect.top),
                int(rect.right - rect.left),
                int(rect.bottom - rect.top),
            )
        return True

    callback = callback_type(collect)
    if not _user32().EnumDisplayMonitors(None, None, callback, 0):
        return {}
    return geometries


def _user32() -> ctypes.WinDLL:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.GetDC.restype = ctypes.c_void_p
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.EnumDisplayDevicesW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(_DisplayDeviceW),
        wintypes.DWORD,
    ]
    user32.EnumDisplayDevicesW.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.LPARAM,
    ]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    return user32


def _gdi32() -> ctypes.WinDLL:
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi32.GetDeviceGammaRamp.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.GetDeviceGammaRamp.restype = ctypes.c_bool
    gdi32.SetDeviceGammaRamp.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SetDeviceGammaRamp.restype = ctypes.c_bool
    gdi32.CreateDCW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
    ]
    gdi32.CreateDCW.restype = ctypes.c_void_p
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.restype = wintypes.BOOL
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
