from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QObject, Signal


class LogBus(QObject):
    """Thread-safe bridge from application events to any visible log surfaces."""

    line_ready = Signal(str)
    visible_line_ready = Signal(str)

    def publish(self, line: str, *, visible: bool = False) -> None:
        text = str(line)
        self.line_ready.emit(text)
        if visible:
            self.visible_line_ready.emit(text)


class SettingsStore(QObject):
    """Shared mutable settings state for progressively decoupling UI from config dicts."""

    changed = Signal(str, object)

    def __init__(self, values: dict[str, Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._values = values

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)

    def set(self, key: str, value: object) -> bool:
        if self._values.get(key) == value:
            return False
        self._values[key] = value
        self.changed.emit(key, value)
        return True

    def update(self, values: dict[str, object]) -> list[str]:
        changed: list[str] = []
        for key, value in values.items():
            if self.set(key, value):
                changed.append(key)
        return changed

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._values)
