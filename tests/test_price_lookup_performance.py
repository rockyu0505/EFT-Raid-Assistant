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
from app.gui import MainWindow
from app.item_ocr import (
    _find_tooltip_border_box,
    _tooltip_border_mask,
    detect_inventory_tab_image,
    refine_tooltip_name_image,
)


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

    def test_tooltip_refinement_returns_an_image_without_writing_a_file(self) -> None:
        image = Image.new("RGB", (100, 50), "black")
        with patch("app.item_ocr._find_tooltip_border_box", return_value=(10, 5, 90, 45)):
            refined, detected, details = refine_tooltip_name_image(image)

        self.assertTrue(detected)
        self.assertEqual(refined.size, (76, 36))
        self.assertEqual(details, ["border:80x40"])

    def test_bright_inventory_tab_uses_visual_detection_without_ocr(self) -> None:
        image = Image.new("RGB", (244, 90), "white")
        with patch("app.item_ocr._ocr_detection_crop") as ocr_fallback:
            detected, found, raw_text = detect_inventory_tab_image(image)

        self.assertTrue(detected)
        self.assertTrue(found[0].startswith("tab:visual:"))
        self.assertEqual(raw_text, "")
        ocr_fallback.assert_not_called()

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
