from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image
from mss import mss

from app.config import APP_DIR


BASE_SCREEN_SIZE = (2048, 1152)
DEFAULT_TIMER_STRIP_BOX = (0, 150, 1500, 240)
DEFAULT_ITEM_NAME_BOX = (670, 120, 1420, 260)
DEFAULT_HOVER_TOOLTIP_OFFSET = (12, -60)
DEFAULT_HOVER_TOOLTIP_SIZE = (360, 110)
DEFAULT_HOVER_SEARCH_MARGINS = (560, 560, 240, 45)
TARKOV_WINDOW_KEYWORDS = ("escapefromtarkov", "escape from tarkov", "tarkov")
TARKOV_PROCESS_KEYWORDS = ("escapefromtarkov", "tarkov")
DEBUG_DIR = APP_DIR / "debug"
FULL_SCREENSHOT_PATH = DEBUG_DIR / "last_full_screenshot.png"
TIMER_STRIP_PATH = DEBUG_DIR / "last_timer_strip.png"
ITEM_NAME_PATH = DEBUG_DIR / "last_item_name.png"
ITEM_HOVER_SEARCH_PATH = DEBUG_DIR / "last_item_hover_search.png"
INVENTORY_TAB_PATH = DEBUG_DIR / "last_inventory_tab.png"
GAME_MODE_PATH = DEBUG_DIR / "last_game_mode.png"
HIDEOUT_SCREENSHOT_PATH = DEBUG_DIR / "last_hideout_screenshot.png"


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int
    name: str

    def as_mss(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


def is_tarkov_foreground() -> tuple[bool, str]:
    """Return whether the active foreground window appears to be Tarkov."""
    try:
        import win32gui  # type: ignore
        import win32process  # type: ignore
    except ImportError:
        return False, "pywin32 is not installed; cannot check foreground window."

    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd).strip()
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process_name = _process_name_from_pid(pid)
    haystacks = [
        title.lower().replace(" ", ""),
        process_name.lower().replace(" ", ""),
    ]
    title_match = any(
        keyword.replace(" ", "") in haystacks[0] for keyword in TARKOV_WINDOW_KEYWORDS
    )
    process_match = any(
        keyword.replace(" ", "") in haystacks[1] for keyword in TARKOV_PROCESS_KEYWORDS
    )
    details = title or f"hwnd={hwnd}"
    if process_name:
        details = f"{details} / {process_name}"
    return title_match or process_match, details


def _process_name_from_pid(pid: int) -> str:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return ""

    kernel32 = ctypes.windll.kernel32
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ""

    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        if not ok:
            return ""
        return Path(buffer.value).name
    finally:
        kernel32.CloseHandle(handle)


def scale_box(
    box: tuple[int, int, int, int],
    current_size: tuple[int, int],
    base_size: tuple[int, int] = BASE_SCREEN_SIZE,
) -> tuple[int, int, int, int]:
    """Scale a base-resolution ROI box to the current capture size."""
    x_scale = current_size[0] / base_size[0]
    y_scale = current_size[1] / base_size[1]
    x0, y0, x1, y1 = box
    return (
        max(0, round(x0 * x_scale)),
        max(0, round(y0 * y_scale)),
        max(0, round(x1 * x_scale)),
        max(0, round(y1 * y_scale)),
    )


def scale_metric(
    value: int,
    current_height: int,
    reference_height: int,
    minimum: int,
) -> int:
    """Scale a vertical UI pixel metric to the current capture height."""
    if value <= 0:
        return minimum
    if current_height <= 0 or reference_height <= 0:
        return max(minimum, value)
    return max(minimum, round(value * current_height / reference_height))


def capture_timer_strip(
    capture_mode: str,
    manual_size: tuple[int, int] | None,
    roi_base: tuple[int, int, int, int] = DEFAULT_TIMER_STRIP_BOX,
) -> tuple[Image.Image, Image.Image, tuple[int, int], str]:
    """Capture the selected region, save the full screenshot and timer crop."""
    DEBUG_DIR.mkdir(exist_ok=True)
    region = _resolve_region(capture_mode)

    with mss() as screen:
        grabbed = screen.grab(region.as_mss())

    image = Image.frombytes("RGB", grabbed.size, grabbed.rgb)
    actual_size = image.size
    scale_size = manual_size or actual_size

    crop_box = scale_box(roi_base, scale_size)
    crop_box = _fit_crop_box(crop_box, actual_size)
    crop = image.crop(crop_box)

    image.save(FULL_SCREENSHOT_PATH)
    crop.save(TIMER_STRIP_PATH)
    return image, crop, actual_size, region.name


def capture_item_name_region(
    capture_mode: str,
    manual_size: tuple[int, int] | None,
    roi_base: tuple[int, int, int, int] = DEFAULT_ITEM_NAME_BOX,
) -> tuple[Image.Image, Image.Image, tuple[int, int], str]:
    """Capture an adjustable item-name/details region for OCR price lookup."""
    DEBUG_DIR.mkdir(exist_ok=True)
    region = _resolve_region(capture_mode)

    with mss() as screen:
        grabbed = screen.grab(region.as_mss())

    image = Image.frombytes("RGB", grabbed.size, grabbed.rgb)
    actual_size = image.size
    scale_size = manual_size or actual_size

    crop_box = scale_box(roi_base, scale_size)
    crop_box = _fit_crop_box(crop_box, actual_size)
    crop = image.crop(crop_box)

    image.save(FULL_SCREENSHOT_PATH)
    crop.save(ITEM_NAME_PATH)
    return image, crop, actual_size, region.name


def capture_hover_item_name_region(
    capture_mode: str,
    offset: tuple[int, int] = DEFAULT_HOVER_TOOLTIP_OFFSET,
    crop_size: tuple[int, int] = DEFAULT_HOVER_TOOLTIP_SIZE,
    search_margins: tuple[int, int, int, int] | None = DEFAULT_HOVER_SEARCH_MARGINS,
    region: Region | None = None,
    save_full_screenshot: bool = True,
) -> tuple[Image.Image, Image.Image, tuple[int, int], str, tuple[int, int]]:
    """Capture the tooltip search area near the current mouse cursor."""
    DEBUG_DIR.mkdir(exist_ok=True)
    region = region or _resolve_region(capture_mode)
    cursor_x, cursor_y = _cursor_position()
    rel_x = cursor_x - region.left
    rel_y = cursor_y - region.top
    if search_margins is not None:
        left, right, up, down = search_margins
        x0 = rel_x - left
        y0 = rel_y - up
        x1 = rel_x + right
        y1 = rel_y + down
    else:
        x0 = rel_x + offset[0]
        y0 = rel_y + offset[1]
        x1 = x0 + crop_size[0]
        y1 = y0 + crop_size[1]
    crop_box = _fit_crop_box((x0, y0, x1, y1), (region.width, region.height))
    cursor_anchor = (rel_x - crop_box[0], rel_y - crop_box[1])
    crop_region = Region(
        left=region.left + crop_box[0],
        top=region.top + crop_box[1],
        width=crop_box[2] - crop_box[0],
        height=crop_box[3] - crop_box[1],
        name=f"{region.name}; cursor tooltip search",
    )
    crop = _grab_region(crop_region)

    if save_full_screenshot:
        image = _grab_region(region)
        image.save(FULL_SCREENSHOT_PATH)
    else:
        image = crop
    crop.save(ITEM_HOVER_SEARCH_PATH)
    crop.save(ITEM_NAME_PATH)
    return image, crop, (region.width, region.height), crop_region.name, cursor_anchor


def capture_inventory_tab_region(
    capture_mode: str,
    manual_size: tuple[int, int] | None,
    roi_base: tuple[int, int, int, int],
    region: Region | None = None,
) -> tuple[Image.Image, tuple[int, int], str]:
    DEBUG_DIR.mkdir(exist_ok=True)
    region = region or _resolve_region(capture_mode)
    crop = _capture_scaled_roi(region, manual_size, roi_base)
    crop.save(INVENTORY_TAB_PATH)
    return crop, (region.width, region.height), region.name


def capture_game_mode_region(
    capture_mode: str,
    manual_size: tuple[int, int] | None,
    roi_base: tuple[int, int, int, int],
    region: Region | None = None,
) -> tuple[Image.Image, tuple[int, int], str]:
    DEBUG_DIR.mkdir(exist_ok=True)
    region = region or _resolve_region(capture_mode)
    crop = _capture_scaled_roi(region, manual_size, roi_base)
    crop.save(GAME_MODE_PATH)
    return crop, (region.width, region.height), region.name


def capture_hideout_screen(capture_mode: str) -> tuple[Image.Image, tuple[int, int], str]:
    """Capture the full selected region for hideout upgrade OCR."""
    DEBUG_DIR.mkdir(exist_ok=True)
    region = _resolve_region(capture_mode)
    image = _grab_region(region)
    image.save(HIDEOUT_SCREENSHOT_PATH)
    return image, (region.width, region.height), region.name


def resolve_capture_region(capture_mode: str) -> Region:
    return _resolve_region(capture_mode)


def _capture_scaled_roi(
    region: Region,
    manual_size: tuple[int, int] | None,
    roi_base: tuple[int, int, int, int],
) -> Image.Image:
    scale_size = manual_size or (region.width, region.height)
    crop_box = scale_box(roi_base, scale_size)
    crop_box = _fit_crop_box(crop_box, (region.width, region.height))
    crop_region = Region(
        left=region.left + crop_box[0],
        top=region.top + crop_box[1],
        width=crop_box[2] - crop_box[0],
        height=crop_box[3] - crop_box[1],
        name=region.name,
    )
    return _grab_region(crop_region)


def _grab_region(region: Region) -> Image.Image:
    with mss() as screen:
        grabbed = screen.grab(region.as_mss())
    return Image.frombytes("RGB", grabbed.size, grabbed.rgb)


def _fit_crop_box(
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


def _resolve_region(capture_mode: str) -> Region:
    normalized = capture_mode.lower()
    if normalized in {"auto", "tarkov window"}:
        region = _try_tarkov_window()
        if region is not None:
            return region
        if normalized == "tarkov window":
            return _primary_monitor_region("Tarkov window not found; primary monitor")

    if normalized in {"auto", "monitor under cursor"}:
        region = _monitor_under_cursor()
        if region is not None:
            return region

    return _primary_monitor_region("Primary monitor")


def _primary_monitor_region(name: str) -> Region:
    with mss() as screen:
        monitor = screen.monitors[1]
    return Region(
        left=monitor["left"],
        top=monitor["top"],
        width=monitor["width"],
        height=monitor["height"],
        name=name,
    )


def _monitor_under_cursor() -> Region | None:
    try:
        import win32api  # type: ignore
    except ImportError:
        return _primary_monitor_region("Monitor under cursor unavailable; primary monitor")

    cursor_x, cursor_y = win32api.GetCursorPos()
    with mss() as screen:
        for monitor in screen.monitors[1:]:
            left = monitor["left"]
            top = monitor["top"]
            right = left + monitor["width"]
            bottom = top + monitor["height"]
            if left <= cursor_x < right and top <= cursor_y < bottom:
                return Region(
                    left=left,
                    top=top,
                    width=monitor["width"],
                    height=monitor["height"],
                    name="Monitor under cursor",
                )
    return None


def _cursor_position() -> tuple[int, int]:
    try:
        import win32api  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for hover tooltip capture.") from exc
    return win32api.GetCursorPos()


def _try_tarkov_window() -> Region | None:
    try:
        import win32gui  # type: ignore
    except ImportError:
        return None

    keywords = ("escapefromtarkov", "escape from tarkov", "tarkov")
    matches: list[Any] = []

    def enum_handler(hwnd: int, _: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).lower()
        if any(keyword in title for keyword in keywords):
            matches.append(hwnd)

    win32gui.EnumWindows(enum_handler, None)
    if not matches:
        return None

    hwnd = matches[0]
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        screen_left, screen_top = win32gui.ClientToScreen(hwnd, (left, top))
        screen_right, screen_bottom = win32gui.ClientToScreen(hwnd, (right, bottom))
    except Exception:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        screen_left, screen_top, screen_right, screen_bottom = left, top, right, bottom

    width = max(1, screen_right - screen_left)
    height = max(1, screen_bottom - screen_top)
    return Region(
        left=screen_left,
        top=screen_top,
        width=width,
        height=height,
        name="Tarkov window",
    )


def debug_paths() -> tuple[Path, Path]:
    return FULL_SCREENSHOT_PATH, TIMER_STRIP_PATH


def item_debug_path() -> Path:
    return ITEM_NAME_PATH


def hover_search_debug_path() -> Path:
    return ITEM_HOVER_SEARCH_PATH


def inventory_tab_debug_path() -> Path:
    return INVENTORY_TAB_PATH


def game_mode_debug_path() -> Path:
    return GAME_MODE_PATH


def hideout_debug_path() -> Path:
    return HIDEOUT_SCREENSHOT_PATH
