from __future__ import annotations

import math
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from app.models import TraderReminder


class ReminderManager(QObject):
    reminder_triggered = Signal(str, object)
    reminders_updated = Signal(object)

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
        reminder = self._create_reminder(
            trader,
            countdown_seconds,
            lead_seconds,
            repeat_seconds,
            now,
        )
        self._reminders[trader] = reminder
        self._check_reminders()
        return reminder

    def replace(
        self,
        schedules: list[tuple[str, int, int, int]],
    ) -> dict[str, TraderReminder]:
        now = datetime.now()
        self._reminders = {
            trader: self._create_reminder(
                trader,
                countdown_seconds,
                lead_seconds,
                repeat_seconds,
                now,
            )
            for trader, countdown_seconds, lead_seconds, repeat_seconds in schedules
        }
        self._check_reminders()
        return self.active()

    def clear(self) -> None:
        self._reminders.clear()
        self.reminders_updated.emit({})

    def shutdown(self) -> None:
        self._timer.stop()
        self._reminders.clear()

    def active(self) -> dict[str, TraderReminder]:
        return dict(self._reminders)

    @staticmethod
    def _create_reminder(
        trader: str,
        countdown_seconds: int,
        lead_seconds: int,
        repeat_seconds: int,
        now: datetime,
    ) -> TraderReminder:
        restock_at = now + timedelta(seconds=countdown_seconds)
        notify_at = restock_at - timedelta(seconds=max(0, lead_seconds))
        return TraderReminder(
            trader=trader,
            restock_at=restock_at,
            notify_at=notify_at,
            repeat_seconds=max(0, repeat_seconds),
        )

    def _check_reminders(self) -> None:
        now = datetime.now()
        triggered: list[TraderReminder] = []
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
                triggered.append(reminder)

        self.reminders_updated.emit(self.active())
        for reminder in triggered:
            self.reminder_triggered.emit(reminder.trader, reminder)


def remaining_countdown_seconds(
    reminder: TraderReminder,
    now: datetime | None = None,
) -> int:
    current = now or datetime.now()
    return max(0, math.ceil((reminder.restock_at - current).total_seconds()))


def format_countdown(seconds: int) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
