from __future__ import annotations

import os
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.config import DEFAULT_CONFIG
from app.gui import MainWindow, ReminderOverlay
from app.models import TraderReminder
from app.reminders import ReminderManager, format_countdown, remaining_countdown_seconds


class _ReminderSmokeWindow(MainWindow):
    def _reset_run_log(self) -> None:
        pass

    def _build_tray_icon(self) -> None:
        pass

    def _register_hotkeys(self) -> None:
        pass

    def _apply_performance_settings(self) -> None:
        pass

    def _save_config(self) -> None:
        pass


class ReminderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_manager_publishes_active_reminders_and_clear_state(self) -> None:
        manager = ReminderManager()
        manager._timer.stop()
        updates: list[dict[str, TraderReminder]] = []
        manager.reminders_updated.connect(updates.append)

        reminder = manager.schedule("Prapor", 65, 10, 0)

        self.assertEqual(list(manager.active()), ["Prapor"])
        self.assertEqual(list(updates[-1]), ["Prapor"])
        self.assertIn(remaining_countdown_seconds(reminder), (64, 65))
        self.assertEqual(format_countdown(65), "00:01:05")

        updates.clear()
        replaced = manager.replace(
            [
                ("Prapor", 90, 10, 0),
                ("Therapist", 120, 10, 0),
            ]
        )
        self.assertEqual(list(replaced), ["Prapor", "Therapist"])
        self.assertEqual(len(updates), 1)
        self.assertEqual(list(updates[0]), ["Prapor", "Therapist"])

        manager.clear()
        self.assertEqual(updates[-1], {})
        manager.shutdown()

    def test_overlay_lists_all_reminders_and_preserves_explicit_hide(self) -> None:
        now = datetime.now()
        reminders = {
            "Prapor": TraderReminder(
                trader="Prapor",
                restock_at=now + timedelta(seconds=90),
                notify_at=now + timedelta(seconds=80),
            ),
            "Therapist": TraderReminder(
                trader="Therapist",
                restock_at=now + timedelta(seconds=30),
                notify_at=now + timedelta(seconds=20),
            ),
        }
        overlay = ReminderOverlay("F6")
        overlay.set_reminders(reminders)

        self.assertEqual(overlay._count_label.text(), "2 个")
        self.assertEqual(set(overlay._countdown_labels), {"Prapor", "Therapist"})
        self.assertFalse(overlay.isVisible())
        self.assertIn("F6", overlay._footer_label.text())

        self.assertTrue(overlay.toggle_visibility())
        self.app.processEvents()
        self.assertTrue(overlay.isVisible())
        self.assertFalse(overlay.toggle_visibility())
        self.assertFalse(overlay.isVisible())

        reminders["Prapor"].triggered = True
        overlay.set_reminders(reminders)
        overlay.show_triggered("Prapor")
        self.assertFalse(overlay.isVisible())
        self.assertIn("即将补货", overlay._status_labels["Prapor"].text())

        self.assertTrue(overlay.toggle_visibility())
        overlay.clear_reminders()
        self.assertFalse(overlay.isVisible())

    def test_trader_panel_uses_read_only_live_countdowns_and_auto_schedules(self) -> None:
        config = deepcopy(DEFAULT_CONFIG)
        config["enabled_features"] = ["trader_reminders"]
        config["feature_setup_complete"] = True
        config["selected_traders"] = ["Prapor"]
        with patch("app.gui.load_config", return_value=config):
            window = _ReminderSmokeWindow()

        self.assertEqual(window.table.horizontalHeaderItem(2).text(), "实时倒计时")
        self.assertFalse(hasattr(window, "schedule_button"))
        self.assertTrue(hasattr(window, "toggle_countdown_button"))
        self.assertIsNone(window.table.cellWidget(0, 2))
        self.assertFalse(
            bool(window.countdown_items["Prapor"].flags() & Qt.ItemFlag.ItemIsEditable)
        )

        window.countdown_items["Prapor"].setText("00:01:05")
        scheduled, invalid = window._schedule_selected_reminders()

        self.assertEqual([trader for trader, _ in scheduled], ["Prapor"])
        self.assertEqual(invalid, [])
        self.assertEqual(list(window.reminders.active()), ["Prapor"])
        self.assertEqual(list(window.reminder_overlay._reminders), ["Prapor"])
        self.assertIn(window.status_items["Prapor"].text(), {"倒计时中", "即将补货"})

        self.assertTrue(window.reminder_overlay.toggle_visibility())
        window.countdown_items["Prapor"].setText("00:02:00")
        window._schedule_selected_reminders()
        self.app.processEvents()
        self.assertTrue(window.reminder_overlay.isVisible())

        window.shutdown()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
