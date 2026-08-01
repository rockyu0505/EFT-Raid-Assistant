from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt

from app.display_filter import (
    DisplayFilterBaseline,
    DisplayFilterError,
    _build_color_effect,
    restore_display_filter,
    start_display_filter,
    update_display_filter,
)
from app.gui import MainWindow


class DisplayFilterTests(unittest.TestCase):
    def test_identity_color_effect_is_identity_matrix(self) -> None:
        effect = _build_color_effect(
            {"gamma": 1.0, "black_lift": 0.0, "gain": 1.0, "contrast": 1.0}
        )

        self.assertEqual(len(effect), 25)
        self.assertAlmostEqual(effect[0], 1.0, places=3)
        self.assertAlmostEqual(effect[6], 1.0, places=3)
        self.assertAlmostEqual(effect[12], 1.0, places=3)
        self.assertAlmostEqual(effect[20], 0.0, places=3)

    def test_start_falls_back_to_magnification_backend(self) -> None:
        baseline_effect = tuple(float(index) for index in range(25))
        with patch(
            "app.display_filter.get_gamma_ramp",
            side_effect=DisplayFilterError("unsupported"),
        ), patch("app.display_filter._magnification_initialize") as initialize, patch(
            "app.display_filter._get_fullscreen_color_effect",
            return_value=baseline_effect,
        ), patch("app.display_filter._set_fullscreen_color_effect") as set_effect:
            baseline = start_display_filter({"gamma": 0.8})

        self.assertEqual(baseline, DisplayFilterBaseline("magnification", baseline_effect))
        initialize.assert_called_once_with()
        set_effect.assert_called_once()

    def test_magnification_backend_updates_and_restores(self) -> None:
        baseline_effect = tuple(float(index) for index in range(25))
        baseline = DisplayFilterBaseline("magnification", baseline_effect)
        with patch("app.display_filter._set_fullscreen_color_effect") as set_effect, patch(
            "app.display_filter._magnification_uninitialize"
        ) as uninitialize:
            update_display_filter({"gamma": 0.7}, baseline)
            restore_display_filter(baseline)

        self.assertEqual(set_effect.call_count, 2)
        self.assertEqual(set_effect.call_args_list[-1].args[0], baseline_effect)
        uninitialize.assert_called_once_with()

    def test_eye_care_does_not_restore_while_any_assistant_window_is_active(self) -> None:
        window = Mock()
        window._closing = False
        window._display_filter_baseline = object()
        window._display_filter_eye_care_enabled.return_value = True
        with patch(
            "app.gui.QApplication.applicationState",
            return_value=Qt.ApplicationState.ApplicationActive,
        ), patch("app.gui.is_tarkov_foreground") as is_tarkov_foreground:
            MainWindow._on_display_filter_eye_care_check(window)

        is_tarkov_foreground.assert_not_called()
        window.restore_display_filter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
