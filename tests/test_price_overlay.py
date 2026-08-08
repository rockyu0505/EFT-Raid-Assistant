from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QEasingCurve, QRect
from PySide6.QtWidgets import QApplication

from app.capture import Region
from app.gui import (
    PRICE_CAPTURE_COMPOSITOR_SETTLE_SECONDS,
    PriceOverlay,
    PriceToast,
    PriceView,
    _capture_window_rect,
)


def _view(key: str) -> PriceView:
    return PriceView(
        title=f"Item {key}",
        subtitle="",
        detail="detail",
        value_text="10,000 RUB",
        secondary_value_text="",
        tier_label="",
        tier_color="#7CC7FF",
        tier_accent="#3A9DFF",
        label_html="",
        log_text="",
        toast_key=key,
    )


class PriceOverlayAnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_position_animation_accelerates_cruises_and_decelerates(self) -> None:
        toast = PriceToast(_view("one"))
        toast.move(0, 0)

        toast.animate_to(QPoint(120, 60), 360)

        group = toast._position_animation
        self.assertIsNotNone(group)
        assert group is not None
        self.assertEqual(group.animationCount(), 3)
        self.assertEqual([group.animationAt(index).duration() for index in range(3)], [90, 180, 90])
        self.assertEqual(
            [group.animationAt(index).easingCurve().type() for index in range(3)],
            [QEasingCurve.Type.InQuad, QEasingCurve.Type.Linear, QEasingCurve.Type.OutQuad],
        )
        self.assertEqual(group.animationAt(0).endValue(), QPoint(20, 10))
        self.assertEqual(group.animationAt(1).endValue(), QPoint(100, 50))
        self.assertEqual(group.animationAt(2).endValue(), QPoint(120, 60))

        group.stop()
        toast.close()

    def test_new_toast_fades_in_and_fourth_toast_moves_while_fading_out(self) -> None:
        overlay = PriceOverlay()
        with patch.object(PriceToast, "show_for", autospec=True) as show_for, patch.object(
            PriceToast,
            "animate_to",
            autospec=True,
        ), patch.object(PriceToast, "fade_out", autospec=True) as fade_out:
            overlay.show_price(_view("one"), 10)
            overlay.show_price(_view("two"), 10)
            overlay.show_price(_view("three"), 10)
            oldest = overlay._toasts[-1]

            overlay.show_price(_view("four"), 10)

        self.assertEqual([toast.toast_key for toast in overlay._toasts], ["four", "three", "two"])
        self.assertEqual(len(overlay._toasts), 3)
        self.assertIs(show_for.call_args.args[0], overlay._toasts[0])
        self.assertTrue(show_for.call_args.kwargs["fade_in"])
        self.assertEqual(show_for.call_args.kwargs["fade_delay_ms"], 140)
        self.assertEqual(show_for.call_args.kwargs["fade_duration_ms"], 360)
        fade_out.assert_called_once()
        self.assertIs(fade_out.call_args.args[0], oldest)
        self.assertEqual(fade_out.call_args.args[1], 360)
        self.assertIsInstance(fade_out.call_args.kwargs["move_target"], QPoint)

        overlay.clear_prices()

    def test_new_toast_waits_before_using_a_gentle_fade_curve(self) -> None:
        toast = PriceToast(_view("one"))
        callbacks = []
        with patch("app.gui.QTimer.singleShot", side_effect=lambda _, callback: callbacks.append(callback)):
            toast.show_for(
                10,
                fade_in=True,
                fade_delay_ms=140,
                fade_duration_ms=360,
            )

        self.assertEqual(toast._opacity.opacity(), 0.0)
        self.assertEqual(len(callbacks), 2)
        callbacks[0]()
        animation = toast._opacity_animation
        self.assertIsNotNone(animation)
        assert animation is not None
        self.assertEqual(animation.duration(), 360)
        self.assertEqual(animation.easingCurve().type(), QEasingCurve.Type.InOutCubic)

        animation.stop()
        toast.close()

    def test_removing_a_toast_animates_the_remaining_stack(self) -> None:
        overlay = PriceOverlay()
        with patch.object(PriceToast, "show_for", autospec=True), patch.object(
            PriceToast,
            "animate_to",
            autospec=True,
        ) as animate_to:
            overlay.show_price(_view("one"), 10)
            overlay.show_price(_view("two"), 10)
            removed = overlay._toasts[-1]
            animate_to.reset_mock()

            overlay._forget_toast(removed)

        self.assertEqual([toast.toast_key for toast in overlay._toasts], ["two"])
        animate_to.assert_called_once()
        self.assertIs(animate_to.call_args.args[0], overlay._toasts[0])

        overlay.clear_prices()

    def test_capture_guard_hides_only_toasts_intersecting_the_capture(self) -> None:
        overlay = PriceOverlay()
        near = Mock()
        near.isVisible.return_value = True
        near.frameGeometry.return_value = QRect(100, 100, 200, 100)
        near._closing = False
        far = Mock()
        far.isVisible.return_value = True
        far.frameGeometry.return_value = QRect(900, 700, 200, 100)
        far._closing = False
        overlay._toasts = [near, far]

        with patch.object(QApplication, "processEvents") as process_events, patch(
            "app.gui.time.sleep"
        ) as sleep:
            with overlay.capture_guard(Region(50, 50, 500, 400, "capture")):
                near.hide.assert_called_once_with()
                far.hide.assert_not_called()
                near.show.assert_not_called()
                sleep.assert_called_once_with(PRICE_CAPTURE_COMPOSITOR_SETTLE_SECONDS)

        near.show.assert_called_once_with()
        near.raise_.assert_called_once_with()
        far.show.assert_not_called()
        self.assertEqual(process_events.call_count, 3)

    def test_capture_guard_uses_native_pixels_on_a_scaled_display(self) -> None:
        overlay = PriceOverlay()
        toast = Mock()
        toast.isVisible.return_value = True
        toast.frameGeometry.return_value = QRect(1560, 80, 360, 180)
        toast._closing = False
        overlay._toasts = [toast]
        native_rect = QRect(3120, 160, 720, 360)

        with patch("app.gui._capture_window_rect", return_value=native_rect), patch(
            "app.gui.time.sleep"
        ):
            with overlay.capture_guard(Region(2280, 0, 1360, 420, "4K tooltip crop")):
                toast.hide.assert_called_once_with()

        toast.show.assert_called_once_with()
        toast.raise_.assert_called_once_with()

    def test_native_capture_rect_comes_from_the_top_level_window(self) -> None:
        toast = Mock()
        toast.winId.return_value = 321
        toast.frameGeometry.return_value = QRect(1560, 80, 360, 180)

        with patch("win32gui.GetWindowRect", return_value=(3120, 160, 3840, 520)):
            rect = _capture_window_rect(toast)

        self.assertEqual(rect, QRect(3120, 160, 720, 360))

    def test_native_capture_rect_falls_back_to_qt_geometry(self) -> None:
        toast = Mock()
        toast.winId.return_value = 321
        logical_rect = QRect(1560, 80, 360, 180)
        toast.frameGeometry.return_value = logical_rect

        with patch("win32gui.GetWindowRect", side_effect=RuntimeError("no native window")):
            rect = _capture_window_rect(toast)

        self.assertEqual(rect, logical_rect)


if __name__ == "__main__":
    unittest.main()
