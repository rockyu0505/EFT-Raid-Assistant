from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from app.hotkeys import HotkeyManager


class _FakeHotKey:
    @staticmethod
    def parse(value: str) -> list[str]:
        return value.split("+")


class _FakeListener:
    def __init__(self, *, on_press, on_release) -> None:
        self.on_press = on_press
        self.on_release = on_release
        self.started = False

    def canonical(self, key: object) -> object:
        return key

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        pass

    def join(self, timeout: float = 0.0) -> None:
        pass


class HotkeyManagerTests(unittest.TestCase):
    def test_modified_chord_does_not_also_fire_bare_key(self) -> None:
        keyboard = types.SimpleNamespace(HotKey=_FakeHotKey, Listener=_FakeListener)
        pynput = types.ModuleType("pynput")
        pynput.keyboard = keyboard  # type: ignore[attr-defined]
        calls: list[str] = []
        manager = HotkeyManager()

        with patch.dict(sys.modules, {"pynput": pynput}):
            manager.register(
                capture_hotkey="F9",
                schedule_hotkey="",
                on_capture=lambda: calls.append("bare"),
                on_schedule=None,
                display_filter_restore_hotkey="Ctrl+F9",
                on_display_filter_restore=lambda: calls.append("modified"),
            )

        listener = manager._listener
        self.assertIsInstance(listener, _FakeListener)
        listener.on_press("<ctrl>")
        listener.on_press("<f9>")
        self.assertEqual(calls, ["modified"])
        listener.on_release("<f9>")
        listener.on_release("<ctrl>")
        listener.on_press("<f9>")
        self.assertEqual(calls, ["modified", "bare"])


if __name__ == "__main__":
    unittest.main()
