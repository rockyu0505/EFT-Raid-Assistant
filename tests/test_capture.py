from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.capture import (
    Region,
    _try_tarkov_window,
    capture_hover_item_name_region,
    capture_inventory_tab_region,
    scale_box,
)
from app.config import HOVER_SEARCH_MARGINS, INVENTORY_TAB_ROI_BASE


class CaptureScalingTests(unittest.TestCase):
    def test_tarkov_1_1_inventory_tab_roi_scales_to_4k_tab_interior(self) -> None:
        self.assertEqual(
            scale_box(INVENTORY_TAB_ROI_BASE, (3840, 2160)),
            (309, 0, 628, 60),
        )

    def test_16_by_10_window_scales_both_axes_without_letterboxing(self) -> None:
        self.assertEqual(
            scale_box((105, 0, 235, 48), (2560, 1600)),
            (131, 0, 294, 67),
        )

    def test_inventory_capture_uses_the_full_window_coordinates(self) -> None:
        target = Region(200, 100, 2560, 1600, "Tarkov window")
        captured_regions: list[Region] = []

        def fake_grab(region: Region) -> Image.Image:
            captured_regions.append(region)
            return Image.new("RGB", (region.width, region.height), "black")

        with patch("app.capture._grab_region", side_effect=fake_grab):
            crop, size, name = capture_inventory_tab_region(
                "Auto",
                None,
                (105, 0, 235, 48),
                region=target,
                save_debug_image=False,
            )

        self.assertEqual(size, (2560, 1600))
        self.assertEqual(name, "Tarkov window")
        self.assertEqual(crop.size, (163, 67))
        self.assertEqual(
            captured_regions,
            [Region(331, 100, 163, 67, "Tarkov window")],
        )

    def test_hover_capture_reports_visible_client_right_edge(self) -> None:
        target = Region(100, 50, 1000, 600, "Tarkov window")
        captured_regions: list[Region] = []

        def fake_grab(region: Region) -> Image.Image:
            captured_regions.append(region)
            return Image.new("RGB", (region.width, region.height), "black")

        with patch("app.capture._cursor_position", return_value=(950, 350)), patch(
            "app.capture._grab_region",
            side_effect=fake_grab,
        ):
            _, crop, size, _, cursor_anchor, client_right_edge, client_top_edge = (
                capture_hover_item_name_region(
                    "Auto",
                    search_margins=HOVER_SEARCH_MARGINS,
                    region=target,
                    save_full_screenshot=False,
                    save_debug_images=False,
                )
            )

        self.assertEqual(size, (1000, 600))
        self.assertEqual(crop.size, (810, 420))
        self.assertEqual(cursor_anchor, (660, 240))
        self.assertEqual(client_right_edge, 810)
        self.assertIsNone(client_top_edge)
        self.assertEqual(
            captured_regions,
            [Region(290, 110, 810, 420, "Tarkov window; cursor tooltip search")],
        )

    def test_4k_hover_capture_contains_the_cursor_gap_and_maximum_tooltip_width(
        self,
    ) -> None:
        target = Region(0, 0, 3840, 2160, "Tarkov window")
        captured_regions: list[Region] = []

        def fake_grab(region: Region) -> Image.Image:
            captured_regions.append(region)
            return Image.new("RGB", (region.width, region.height), "black")

        with patch("app.capture._cursor_position", return_value=(1600, 1000)), patch(
            "app.capture._grab_region",
            side_effect=fake_grab,
        ):
            _, crop, _, _, cursor_anchor, client_right_edge, client_top_edge = (
                capture_hover_item_name_region(
                    "Auto",
                    search_margins=HOVER_SEARCH_MARGINS,
                    region=target,
                    save_full_screenshot=False,
                    save_debug_images=False,
                )
            )

        self.assertEqual(crop.size, (1360, 420))
        self.assertEqual(cursor_anchor, (660, 240))
        self.assertIsNone(client_right_edge)
        self.assertIsNone(client_top_edge)
        self.assertGreaterEqual(crop.width - cursor_anchor[0], 18 + 640)
        self.assertEqual(
            captured_regions,
            [Region(940, 760, 1360, 420, "Tarkov window; cursor tooltip search")],
        )

    def test_top_clipped_hover_capture_keeps_space_below_the_cursor(self) -> None:
        target = Region(100, 50, 1000, 600, "Tarkov window")
        captured_regions: list[Region] = []

        def fake_grab(region: Region) -> Image.Image:
            captured_regions.append(region)
            return Image.new("RGB", (region.width, region.height), "black")

        with patch("app.capture._cursor_position", return_value=(600, 90)), patch(
            "app.capture._grab_region",
            side_effect=fake_grab,
        ):
            _, crop, _, _, cursor_anchor, _, client_top_edge = capture_hover_item_name_region(
                "Auto",
                search_margins=HOVER_SEARCH_MARGINS,
                region=target,
                save_full_screenshot=False,
                save_debug_images=False,
            )

        self.assertEqual(cursor_anchor, (500, 40))
        self.assertEqual(client_top_edge, 0)
        self.assertEqual(crop.size, (1000, 220))
        self.assertEqual(
            captured_regions,
            [Region(100, 50, 1000, 220, "Tarkov window; cursor tooltip search")],
        )


class TarkovWindowSelectionTests(unittest.TestCase):
    def test_foreground_game_window_is_preferred_to_an_enumerated_launcher(self) -> None:
        gui, process = _fake_win32_modules(foreground=20)

        with (
            patch.dict(sys.modules, {"win32gui": gui, "win32process": process}),
            patch(
                "app.capture._process_name_from_pid",
                side_effect=lambda pid: {
                    1010: "BsgLauncher.exe",
                    1020: "EscapeFromTarkov.exe",
                }[pid],
            ),
        ):
            region = _try_tarkov_window()

        self.assertEqual(
            region,
            Region(
                2560,
                0,
                2560,
                1600,
                "Tarkov window (Escape from Tarkov / EscapeFromTarkov.exe) at 2560,0",
            ),
        )
        self.assertEqual(gui.enumerated, 0)

    def test_fallback_rejects_launcher_process_and_selects_the_game(self) -> None:
        gui, process = _fake_win32_modules(foreground=30)

        with (
            patch.dict(sys.modules, {"win32gui": gui, "win32process": process}),
            patch(
                "app.capture._process_name_from_pid",
                side_effect=lambda pid: {
                    1010: "BsgLauncher.exe",
                    1020: "EscapeFromTarkov.exe",
                    1030: "explorer.exe",
                }[pid],
            ),
        ):
            region = _try_tarkov_window()

        self.assertEqual(
            region,
            Region(
                2560,
                0,
                2560,
                1600,
                "Tarkov window (Escape from Tarkov / EscapeFromTarkov.exe) at 2560,0",
            ),
        )
        self.assertEqual(gui.enumerated, 1)


def _fake_win32_modules(*, foreground: int) -> tuple[object, object]:
    titles = {
        10: "Escape from Tarkov Launcher",
        20: "Escape from Tarkov",
        30: "File Explorer",
    }
    sizes = {
        10: (0, 0, 1920, 1080),
        20: (0, 0, 2560, 1600),
        30: (0, 0, 1200, 800),
    }
    origins = {
        10: (0, 0),
        20: (2560, 0),
        30: (100, 100),
    }
    state = SimpleNamespace(enumerated=0)

    def enum_windows(callback: object, argument: object) -> None:
        state.enumerated += 1
        for hwnd in (10, 20, 30):
            callback(hwnd, argument)

    def client_to_screen(hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
        origin_x, origin_y = origins[hwnd]
        return origin_x + point[0], origin_y + point[1]

    gui = SimpleNamespace(
        GetForegroundWindow=lambda: foreground,
        IsWindowVisible=lambda hwnd: True,
        IsIconic=lambda hwnd: False,
        GetWindowText=lambda hwnd: titles[hwnd],
        GetClientRect=lambda hwnd: sizes[hwnd],
        ClientToScreen=client_to_screen,
        GetWindowRect=lambda hwnd: (
            origins[hwnd][0],
            origins[hwnd][1],
            origins[hwnd][0] + sizes[hwnd][2],
            origins[hwnd][1] + sizes[hwnd][3],
        ),
        EnumWindows=enum_windows,
        enumerated=state.enumerated,
    )

    original_enum_windows = gui.EnumWindows

    def tracked_enum_windows(callback: object, argument: object) -> None:
        original_enum_windows(callback, argument)
        gui.enumerated = state.enumerated

    gui.EnumWindows = tracked_enum_windows
    process = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, 1000 + hwnd))
    return gui, process


if __name__ == "__main__":
    unittest.main()
