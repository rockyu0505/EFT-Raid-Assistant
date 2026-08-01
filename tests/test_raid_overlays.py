from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.ui.raid_overlays import RaidControlOverlay, RaidLogOverlay
from app.ui.state import LogBus, SettingsStore


class RaidOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_control_sync_is_quiet_and_loads_current_values(self) -> None:
        overlay = RaidControlOverlay()
        emitted: list[object] = []
        overlay.game_mode_changed.connect(emitted.append)
        overlay.price_duration_changed.connect(emitted.append)
        overlay.gamma_values_changed.connect(emitted.append)
        config = {
            "price_game_mode_default": "regular",
            "item_display_language": "en",
            "price_overlay_seconds": 12,
            "feedback_overlay_seconds": 7,
            "raid_panel_opacity": 88,
            "display_filter_active_preset": "Night",
        }
        presets = [
            {
                "name": "Night",
                "gamma": 0.72,
                "black_lift": 0.12,
                "gain": 0.91,
                "contrast": 1.04,
            }
        ]

        overlay.sync(config, presets, "PvP · cache ready")

        self.assertEqual(emitted, [])
        self.assertEqual(overlay.game_mode_combo.currentData(), "regular")
        self.assertEqual(overlay.language_combo.currentData(), "en")
        self.assertEqual(overlay.price_duration.value(), 12)
        self.assertEqual(overlay.gamma_values()["gamma"], 0.72)
        self.assertEqual(overlay.status_label.text(), "PvP · cache ready")

    def test_control_emits_user_changes(self) -> None:
        overlay = RaidControlOverlay()
        overlay.sync(
            {"price_game_mode_default": "pve"},
            [{"name": "Default", "gamma": 1.0}],
            "ready",
        )
        modes: list[str] = []
        overlay.game_mode_changed.connect(modes.append)

        overlay.game_mode_combo.setCurrentIndex(1)

        self.assertEqual(modes, ["regular"])

    def test_log_overlay_is_focus_safe_and_trims_history(self) -> None:
        overlay = RaidLogOverlay(max_lines=20)
        for index in range(25):
            overlay.append_line(f"line {index}")

        self.assertLessEqual(overlay.text.document().blockCount(), 20)
        self.assertIn("line 24", overlay.text.toPlainText())
        self.assertTrue(
            bool(overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        )
        self.assertTrue(overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_settings_store_emits_only_real_changes(self) -> None:
        values: dict[str, object] = {"mode": "pve"}
        store = SettingsStore(values)
        changes: list[tuple[str, object]] = []
        store.changed.connect(lambda key, value: changes.append((key, value)))

        self.assertFalse(store.set("mode", "pve"))
        self.assertTrue(store.set("mode", "regular"))

        self.assertEqual(values["mode"], "regular")
        self.assertEqual(changes, [("mode", "regular")])

    def test_log_bus_separates_full_stream_from_visible_events(self) -> None:
        bus = LogBus()
        all_lines: list[str] = []
        visible_lines: list[str] = []
        bus.line_ready.connect(all_lines.append)
        bus.visible_line_ready.connect(visible_lines.append)

        bus.publish("debug")
        bus.publish("raid event", visible=True)

        self.assertEqual(all_lines, ["debug", "raid event"])
        self.assertEqual(visible_lines, ["raid event"])


if __name__ == "__main__":
    unittest.main()
