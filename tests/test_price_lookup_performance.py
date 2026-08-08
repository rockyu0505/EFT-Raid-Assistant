from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image, ImageDraw

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app.rapid_ocr as rapid_ocr
from app.capture import Region, capture_item_name_region
from app.config import (
    ACHIEVEMENTS_TAB_ROI_BASE,
    INVENTORY_TAB_ROI_BASE,
    LEGACY_ACHIEVEMENTS_TAB_ROI_BASE,
    LEGACY_INVENTORY_TAB_ROI_BASE,
)
from app.gui import MainWindow
from app.item_ocr import (
    _find_tooltip_border_box,
    _tooltip_border_mask,
    detect_character_header_image,
    detect_inventory_tab_image,
    iter_item_name_ocr_image_attempts,
    parse_item_name_candidates,
    refine_tooltip_name_image,
    run_item_name_ocr_image,
    tooltip_line_count_hint,
)
from app.prices import _match_score


class RapidOcrThreadBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_threads = rapid_ocr.rapid_ocr_threads()
        self.original_engines = dict(rapid_ocr._ENGINES)
        rapid_ocr._ENGINES.clear()

    def tearDown(self) -> None:
        rapid_ocr.configure_rapid_ocr_threads(self.original_threads)
        rapid_ocr._ENGINES.clear()
        rapid_ocr._ENGINES.update(self.original_engines)

    def test_thread_budget_accepts_only_supported_low_impact_values(self) -> None:
        for value in (1, 2, 4):
            self.assertEqual(rapid_ocr.configure_rapid_ocr_threads(value), value)
            self.assertEqual(rapid_ocr.rapid_ocr_threads(), value)

        self.assertEqual(rapid_ocr.configure_rapid_ocr_threads(32), 2)
        self.assertEqual(rapid_ocr.configure_rapid_ocr_threads("invalid"), 2)

    def test_engine_receives_the_configured_onnx_thread_limits(self) -> None:
        created: list[dict[str, object]] = []

        class FakeRapidOcr:
            def __init__(self, params: dict[str, object]) -> None:
                created.append(params)

        fake_module = SimpleNamespace(
            OCRVersion=SimpleNamespace(PPOCRV5="v5"),
            RapidOCR=FakeRapidOcr,
        )
        with patch.dict(sys.modules, {"rapidocr": fake_module}):
            rapid_ocr.configure_rapid_ocr_threads(2)
            two_thread_engine = rapid_ocr._get_engine("v5")
            rapid_ocr.configure_rapid_ocr_threads(4)
            four_thread_engine = rapid_ocr._get_engine("v5")

        self.assertIsNot(two_thread_engine, four_thread_engine)
        self.assertEqual(
            created[0]["EngineConfig.onnxruntime.intra_op_num_threads"],
            2,
        )
        self.assertEqual(
            created[0]["EngineConfig.onnxruntime.inter_op_num_threads"],
            1,
        )
        self.assertEqual(
            created[1]["EngineConfig.onnxruntime.intra_op_num_threads"],
            4,
        )


class InMemoryPriceLookupTests(unittest.TestCase):
    def test_vectorized_tooltip_mask_matches_the_scalar_rules(self) -> None:
        values = np.random.default_rng(42).integers(0, 256, size=(31, 47), dtype=np.uint8)
        image = Image.fromarray(values, mode="L")
        expected = np.zeros_like(values, dtype=np.bool_)
        height, width = values.shape
        for y in range(height):
            for x in range(width):
                value = values[y, x]
                if value < 65 or value > 230:
                    continue
                for dx, dy in ((0, 2), (0, -2), (2, 0), (-2, 0)):
                    nx = min(width - 1, max(0, x + dx))
                    ny = min(height - 1, max(0, y + dy))
                    if values[ny, nx] < 55:
                        expected[y, x] = True
                        break

        np.testing.assert_array_equal(_tooltip_border_mask(image), expected)

    def test_vectorized_tooltip_detector_finds_a_synthetic_name_box(self) -> None:
        image = Image.new("RGB", (320, 130), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((125, 41, 236, 82), outline=(100, 100, 100), width=1)
        drawing.rectangle((145, 50, 220, 60), fill=(180, 180, 180))

        self.assertEqual(_find_tooltip_border_box(image), (123, 41, 239, 82))

    def test_cursor_anchored_detector_accepts_tarkov_1_1_large_tooltip(self) -> None:
        image = Image.new("RGB", (700, 220), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((180, 60, 582, 156), outline=(100, 100, 100), width=1)
        for x in (220, 245, 270, 295, 320, 345):
            drawing.rectangle((x, 82, x + 10, 92), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(350, 180),
            cursor_bottom_gap=20,
            cursor_gap_tolerance=36,
        )

        self.assertEqual(detected, (178, 60, 585, 156))

    def test_cursor_anchored_detector_rejects_empty_large_box(self) -> None:
        image = Image.new("RGB", (700, 220), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((180, 60, 582, 156), outline=(100, 100, 100), width=1)

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(350, 180),
            cursor_bottom_gap=20,
            cursor_gap_tolerance=36,
        )

        self.assertIsNone(detected)

    def test_cursor_left_anchor_prefers_tooltip_over_inventory_label_row(self) -> None:
        image = Image.new("RGB", (1120, 285), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((580, 145, 824, 220), outline=(100, 100, 100), width=1)
        for x in (610, 635, 660, 685):
            drawing.rectangle((x, 165, x + 10, 180), fill=(180, 180, 180))

        drawing.rectangle((90, 179, 540, 214), outline=(100, 100, 100), width=1)
        for x in range(120, 500, 35):
            drawing.rectangle((x, 188, x + 12, 199), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(560, 240),
            cursor_bottom_gap=20,
            cursor_gap_tolerance=36,
            cursor_left_gap=18,
            cursor_horizontal_tolerance=12,
            max_box_width=560,
        )

        self.assertIsNotNone(detected)
        assert detected is not None
        self.assertLessEqual(abs(detected[0] - 578), 2)
        self.assertLess(detected[2] - detected[0], 300)

    def test_cursor_left_anchor_rejects_an_unrelated_inventory_label_row(self) -> None:
        image = Image.new("RGB", (1120, 285), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((90, 179, 540, 214), outline=(100, 100, 100), width=1)
        for x in range(120, 500, 35):
            drawing.rectangle((x, 188, x + 12, 199), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(560, 240),
            cursor_bottom_gap=20,
            cursor_gap_tolerance=36,
            cursor_left_gap=18,
            cursor_horizontal_tolerance=12,
            max_box_width=560,
        )

        self.assertIsNone(detected)

    def test_strict_cursor_anchor_accepts_a_short_low_density_name(self) -> None:
        image = Image.new("RGB", (1120, 332), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((573, 89, 697, 139), outline=(100, 100, 100), width=1)
        for x in (595, 610, 625, 640):
            drawing.rectangle((x, 105, x + 3, 113), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(560, 152),
            cursor_bottom_gap=13,
            cursor_gap_tolerance=24,
            cursor_left_gap=12,
            cursor_horizontal_tolerance=8,
            max_box_width=373,
        )

        self.assertIsNotNone(detected)
        assert detected is not None
        self.assertLessEqual(abs(detected[0] - 572), 2)
        self.assertLessEqual(abs(detected[3] - 139), 1)

    def test_strict_cursor_anchor_still_rejects_an_empty_tooltip(self) -> None:
        image = Image.new("RGB", (1120, 332), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((573, 89, 697, 139), outline=(100, 100, 100), width=1)

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(560, 152),
            cursor_bottom_gap=13,
            cursor_gap_tolerance=24,
            cursor_left_gap=12,
            cursor_horizontal_tolerance=8,
            max_box_width=373,
        )

        self.assertIsNone(detected)

    def test_strict_cursor_anchor_accepts_a_scaled_720p_single_line_tooltip(
        self,
    ) -> None:
        image = Image.new("RGB", (1120, 420), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((567, 208, 667, 233), outline=(100, 100, 100), width=1)
        drawing.rectangle((590, 216, 596, 223), fill=(180, 180, 180))
        drawing.rectangle((601, 216, 607, 223), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(560, 240),
            cursor_bottom_gap=7,
            cursor_gap_tolerance=14,
            cursor_left_gap=6,
            cursor_horizontal_tolerance=4,
            max_box_width=187,
        )

        self.assertIsNotNone(detected)

    def test_tooltip_height_selects_the_tarkov_1_1_line_layout(self) -> None:
        self.assertEqual(tooltip_line_count_hint(46, 1440), 1)
        self.assertEqual(tooltip_line_count_hint(71, 2160), 1)
        self.assertEqual(tooltip_line_count_hint(74, 2160), 1)
        self.assertEqual(tooltip_line_count_hint(69, 1440), 2)

    def test_single_line_height_never_invokes_line_splitting(self) -> None:
        image = Image.new("RGB", (180, 71), "black")
        rapid = SimpleNamespace(lines=["医疗工具"], scores=[0.99])

        with patch("app.item_ocr._split_text_line_images") as split_lines, patch(
            "app.item_ocr.run_rapid_text",
            return_value=rapid,
        ):
            result = run_item_name_ocr_image(image, line_count_hint=1)

        split_lines.assert_not_called()
        self.assertEqual(result.candidates[0], "医疗工具")
        self.assertNotIn("line-split", result.variant_name)

    def test_adaptive_ocr_iterator_does_not_run_fallbacks_before_requested(self) -> None:
        image = Image.new("RGB", (180, 71), "black")
        rapid = SimpleNamespace(lines=["医疗工具"], scores=[0.99])

        with patch("app.item_ocr.run_rapid_text", return_value=rapid) as run_rapid:
            attempts = iter_item_name_ocr_image_attempts(image, line_count_hint=1)
            first = next(attempts)

        self.assertEqual(first.candidates, ["医疗工具"])
        self.assertIn("contrast", first.variant_name)
        run_rapid.assert_called_once()

    def test_double_line_height_prefers_the_joined_split_result(self) -> None:
        image = Image.new("RGB", (400, 69), "black")
        line_images = [
            Image.new("RGB", (360, 28), "black"),
            Image.new("RGB", (140, 26), "black"),
        ]
        rapid_results = [
            SimpleNamespace(
                lines=["Magpul PMAG 30 GEN M3 5.45x39 30发"],
                scores=[0.96],
            ),
            SimpleNamespace(lines=["AK弹匣 (FDE)"], scores=[0.99]),
            SimpleNamespace(lines=["错误整框候选"], scores=[0.99]),
            SimpleNamespace(lines=["错误整框候选"], scores=[0.99]),
            SimpleNamespace(lines=["错误整框候选"], scores=[0.99]),
        ]

        with patch(
            "app.item_ocr._split_text_line_images",
            return_value=line_images,
        ), patch(
            "app.item_ocr.run_rapid_text",
            side_effect=rapid_results,
        ):
            result = run_item_name_ocr_image(image, line_count_hint=2)

        self.assertIn("line-split", result.variant_name)
        self.assertEqual(
            result.candidates[0],
            "Magpul PMAG 30 GEN M3 5.45x39 30发 AK弹匣 (FDE)",
        )

    def test_cursor_anchor_uses_shared_span_when_tooltip_top_merges_with_window_line(
        self,
    ) -> None:
        image = Image.new("RGB", (1120, 285), "black")
        drawing = ImageDraw.Draw(image)
        drawing.line((368, 115, 1119, 115), fill=(100, 100, 100), width=1)
        drawing.line((580, 115, 580, 220), fill=(100, 100, 100), width=1)
        drawing.line((767, 115, 767, 220), fill=(100, 100, 100), width=1)
        drawing.line((580, 145, 767, 145), fill=(100, 100, 100), width=1)
        drawing.line((580, 220, 767, 220), fill=(100, 100, 100), width=1)
        for x in (618, 645, 672, 699):
            drawing.rectangle((x, 165, x + 6, 175), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(560, 240),
            cursor_bottom_gap=20,
            cursor_gap_tolerance=36,
            cursor_left_gap=18,
            cursor_horizontal_tolerance=12,
            max_box_width=560,
        )

        self.assertEqual(detected, (578, 145, 770, 220))

    def test_client_right_edge_anchor_finds_a_clamped_tooltip(self) -> None:
        image = Image.new("RGB", (500, 285), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((80, 145, 499, 220), outline=(100, 100, 100), width=1)
        for x in (120, 150, 180, 210, 240, 270):
            drawing.rectangle((x, 165, x + 10, 180), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(430, 240),
            cursor_bottom_gap=20,
            cursor_gap_tolerance=36,
            cursor_left_gap=18,
            cursor_horizontal_tolerance=12,
            max_box_width=560,
            client_right_edge_x=500,
            client_edge_tolerance=12,
        )

        self.assertIsNotNone(detected)
        assert detected is not None
        self.assertEqual(detected[2], 500)

    def test_client_top_edge_anchor_finds_a_clamped_tooltip(self) -> None:
        image = Image.new("RGB", (1120, 420), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((580, 0, 824, 78), outline=(100, 100, 100), width=1)
        for x in (610, 635, 660, 685):
            drawing.rectangle((x, 20, x + 10, 35), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(560, 40),
            cursor_bottom_gap=20,
            cursor_gap_tolerance=36,
            cursor_left_gap=18,
            cursor_horizontal_tolerance=12,
            max_box_width=560,
            client_top_edge_y=0,
            client_edge_tolerance=12,
        )

        self.assertIsNotNone(detected)
        assert detected is not None
        self.assertLessEqual(abs(detected[0] - 578), 2)
        self.assertLessEqual(abs(detected[1]), 1)

    def test_cursor_anchor_does_not_assume_a_tooltip_flips_below_the_cursor(self) -> None:
        image = Image.new("RGB", (1120, 420), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((580, 260, 824, 338), outline=(100, 100, 100), width=1)
        for x in (610, 635, 660, 685):
            drawing.rectangle((x, 280, x + 10, 295), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(560, 240),
            cursor_bottom_gap=20,
            cursor_gap_tolerance=36,
            cursor_left_gap=18,
            cursor_horizontal_tolerance=12,
            max_box_width=560,
        )

        self.assertIsNone(detected)

    def test_cursor_anchor_rejects_a_box_wider_than_the_tooltip_limit(self) -> None:
        image = Image.new("RGB", (1400, 285), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((580, 145, 1240, 220), outline=(100, 100, 100), width=1)
        for x in range(620, 1160, 35):
            drawing.rectangle((x, 165, x + 12, 180), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(560, 240),
            cursor_bottom_gap=20,
            cursor_gap_tolerance=36,
            cursor_left_gap=18,
            cursor_horizontal_tolerance=12,
            max_box_width=560,
        )

        self.assertIsNone(detected)

    def test_cursor_anchor_accepts_the_measured_1440p_double_line_width(self) -> None:
        image = Image.new("RGB", (1360, 420), "black")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((673, 154, 1076, 227), outline=(100, 100, 100), width=1)
        for x in range(710, 1010, 30):
            drawing.rectangle((x, 170, x + 9, 181), fill=(180, 180, 180))
        for x in range(710, 890, 30):
            drawing.rectangle((x, 196, x + 9, 207), fill=(180, 180, 180))

        detected = _find_tooltip_border_box(
            image,
            cursor_anchor=(660, 240),
            cursor_bottom_gap=13,
            cursor_gap_tolerance=24,
            cursor_left_gap=12,
            cursor_horizontal_tolerance=8,
            max_box_width=427,
        )

        self.assertIsNotNone(detected)
        assert detected is not None
        self.assertGreaterEqual(detected[2] - detected[0], 400)

    def test_wrapped_tooltip_name_joins_original_lines_not_trimmed_variants(self) -> None:
        candidates = parse_item_name_candidates(
            "Magpul PMAG 30 GEN M3 5.45x39 30发\nAK弹匣 (FDE)"
        )

        self.assertEqual(
            candidates[0],
            "Magpul PMAG 30 GEN M3 5.45x39 30发 AK弹匣 (FDE)",
        )
        self.assertNotIn(
            "Magpul PMAG 30 GEN M3 5.45x39 30发 AK弹匣 AK弹匣 (FDE)",
            candidates,
        )

    def test_item_name_can_contain_a_navigation_label(self) -> None:
        self.assertEqual(parse_item_name_candidates("地形调查地图"), ["地形调查地图"])

    def test_short_name_at_half_of_noisy_query_does_not_clear_match_threshold(self) -> None:
        self.assertLess(_match_score("绳索电路板医", "电路板"), 0.58)

    def test_tooltip_refinement_returns_an_image_without_writing_a_file(self) -> None:
        image = Image.new("RGB", (100, 50), "black")
        with patch("app.item_ocr._find_tooltip_border_box", return_value=(10, 5, 90, 45)):
            refined, detected, details = refine_tooltip_name_image(image)

        self.assertTrue(detected)
        self.assertEqual(refined.size, (76, 36))
        self.assertEqual(details, ["border:80x40"])

    def test_hover_lookup_stops_before_ocr_when_tooltip_border_is_not_found(self) -> None:
        search = Image.new("RGB", (1120, 420), "black")
        window = SimpleNamespace(
            _closing=False,
            price_client=object(),
            config={
                "capture_mode": "Auto",
                "item_capture_mode": "Hover tooltip",
                "require_inventory_check": False,
            },
            _cached_item_region=None,
            _item_region_calibrated=False,
            _feature_enabled=lambda _: True,
            _ensure_tarkov_foreground=lambda _: True,
            _manual_size=lambda: None,
            _clear_state_detection_cache=Mock(),
            _log=Mock(),
            _log_event=Mock(),
            _log_price_lookup_timings=Mock(),
            item_price_label=Mock(),
        )
        with patch(
            "app.gui.resolve_capture_region",
            return_value=Region(0, 0, 3840, 2160, "Tarkov"),
        ), patch(
            "app.gui.capture_hover_item_name_region",
            return_value=(
                search,
                search,
                (3840, 2160),
                "Tarkov; cursor tooltip search",
                (560, 240),
                None,
                None,
            ),
        ), patch(
            "app.gui.refine_tooltip_name_image",
            return_value=(search, False, []),
        ), patch(
            "app.gui.save_item_lookup_debug_images"
        ) as save_debug, patch(
            "app.gui.iter_item_name_ocr_image_attempts"
        ) as run_ocr:
            MainWindow.capture_item_price(window)

        run_ocr.assert_not_called()
        save_debug.assert_called_once()
        window.item_price_label.setText.assert_called_once_with(
            "Price: tooltip not detected"
        )

    def test_bright_inventory_tab_uses_visual_detection_without_ocr(self) -> None:
        image = Image.new("RGB", (244, 90), "white")
        with patch("app.item_ocr._ocr_detection_crop") as ocr_fallback:
            detected, found, raw_text = detect_inventory_tab_image(image)

        self.assertTrue(detected)
        self.assertTrue(found[0].startswith("tab:visual:"))
        self.assertEqual(raw_text, "")
        ocr_fallback.assert_not_called()

    def test_character_header_recognizes_the_achievements_label(self) -> None:
        image = Image.new("RGB", (240, 40), "black")
        with patch("app.item_ocr._ocr_detection_crop", return_value="任务 成就"):
            detected, found, raw_text = detect_character_header_image(image)

        self.assertTrue(detected)
        self.assertEqual(found, ["header:成就"])
        self.assertEqual(raw_text, "任务 成就")

    def test_manual_item_capture_skips_full_screen_grab_when_debug_is_disabled(self) -> None:
        region = Region(0, 0, 200, 100, "test")
        crop = Image.new("RGB", (50, 20), "black")
        with patch("app.capture._capture_scaled_roi", return_value=crop), patch(
            "app.capture._grab_region"
        ) as full_screen_grab:
            image, result_crop, size, name = capture_item_name_region(
                "Auto",
                manual_size=None,
                region=region,
                save_debug_images=False,
            )

        self.assertIs(image, crop)
        self.assertIs(result_crop, crop)
        self.assertEqual(size, (200, 100))
        self.assertEqual(name, "test")
        full_screen_grab.assert_not_called()

    def test_inventory_detection_falls_back_to_the_legacy_tab_roi(self) -> None:
        new_crop = Image.new("RGB", (100, 30), "black")
        legacy_crop = Image.new("RGB", (100, 30), "white")
        window = SimpleNamespace(
            config={
                "inventory_tab_roi_base": list(INVENTORY_TAB_ROI_BASE),
                "state_detection_cache_seconds": 0,
            },
            _inventory_check_cache=None,
            _log=Mock(),
        )
        with patch(
            "app.gui.capture_inventory_tab_region",
            side_effect=[
                (new_crop, (3840, 2160), "Tarkov"),
                (legacy_crop, (3840, 2160), "Tarkov"),
            ],
        ) as capture_tab, patch(
            "app.gui.detect_inventory_tab_image",
            side_effect=[
                (False, [], ""),
                (True, ["tab:visual:1.10"], ""),
            ],
        ):
            detected, found, image = MainWindow._detect_inventory_from_capture(
                window,
                "Auto",
                None,
                Region(0, 0, 3840, 2160, "Tarkov"),
            )

        self.assertTrue(detected)
        self.assertEqual(found, ["tab:visual:1.10"])
        self.assertIs(image, legacy_crop)
        self.assertEqual(
            [call.args[2] for call in capture_tab.call_args_list],
            [INVENTORY_TAB_ROI_BASE, LEGACY_INVENTORY_TAB_ROI_BASE],
        )
        window._log.assert_called_once()

    def test_character_header_detection_falls_back_to_the_legacy_roi(self) -> None:
        new_crop = Image.new("RGB", (100, 30), "black")
        legacy_crop = Image.new("RGB", (100, 30), "black")
        window = SimpleNamespace(
            config={"state_detection_cache_seconds": 0},
            _character_header_check_cache=None,
            _log=Mock(),
        )
        with patch(
            "app.gui.capture_inventory_tab_region",
            side_effect=[
                (new_crop, (3840, 2160), "Tarkov"),
                (legacy_crop, (3840, 2160), "Tarkov"),
            ],
        ) as capture_tab, patch(
            "app.gui.detect_character_header_image",
            side_effect=[
                (False, [], ""),
                (True, ["header:成就"], "成就"),
            ],
        ):
            detected, found, image = MainWindow._detect_character_header_from_capture(
                window,
                "Auto",
                None,
                Region(0, 0, 3840, 2160, "Tarkov"),
            )

        self.assertTrue(detected)
        self.assertEqual(found, ["header:成就"])
        self.assertIs(image, legacy_crop)
        self.assertEqual(
            [call.args[2] for call in capture_tab.call_args_list],
            [ACHIEVEMENTS_TAB_ROI_BASE, LEGACY_ACHIEVEMENTS_TAB_ROI_BASE],
        )


class CleanupPolicyTests(unittest.TestCase):
    def test_periodic_cleanup_does_not_clear_inventory_detection_cache(self) -> None:
        cached_state = (1.0, (3840, 2160), True, ["tab:visual:1.10"])
        window = SimpleNamespace(
            config={"performance_mode_enabled": True},
            _inventory_check_cache=cached_state,
        )
        with patch("app.gui.gc.collect") as collect:
            MainWindow._cleanup_memory(window)

        collect.assert_called_once_with()
        self.assertIs(window._inventory_check_cache, cached_state)

    def test_periodic_cleanup_is_skipped_while_tarkov_is_foreground(self) -> None:
        window = SimpleNamespace(
            _closing=False,
            _active_worker_count=lambda: 0,
            _cleanup_memory=Mock(),
        )
        with patch("app.gui.is_tarkov_foreground", return_value=(True, "Tarkov")):
            MainWindow._on_resource_cleanup_timer(window)

        window._cleanup_memory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
