from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from app.models import TraderReminder


class ReminderManager(QObject):
    reminder_triggered = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self._reminders: dict[str, TraderReminder] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._check_reminders)
        self._timer.start()

    def schedule(
        self,
        trader: str,
        countdown_seconds: int,
        lead_seconds: int,
        repeat_seconds: int,
    ) -> TraderReminder:
        now = datetime.now()
        restock_at = now + timedelta(seconds=countdown_seconds)
        notify_at = restock_at - timedelta(seconds=max(0, lead_seconds))
        reminder = TraderReminder(
            trader=trader,
            restock_at=restock_at,
            notify_at=notify_at,
            repeat_seconds=max(0, repeat_seconds),
        )
        self._reminders[trader] = reminder
        self._check_reminders()
        return reminder

    def clear(self) -> None:
        self._reminders.clear()

    def shutdown(self) -> None:
        self._timer.stop()
        self._reminders.clear()

    def active(self) -> dict[str, TraderReminder]:
        return dict(self._reminders)

    def _check_reminders(self) -> None:
        now = datetime.now()
        for reminder in list(self._reminders.values()):
            if now < reminder.notify_at:
                continue

            should_trigger = not reminder.triggered
            if reminder.triggered and reminder.repeat_seconds > 0:
                last = reminder.last_triggered_at or reminder.notify_at
                should_trigger = now >= last + timedelta(seconds=reminder.repeat_seconds)

            if should_trigger:
                reminder.triggered = True
                reminder.last_triggered_at = now
                self.reminder_triggered.emit(reminder.trader, reminder)
