from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import suppress


class HotkeyManager:
    def __init__(self) -> None:
        self._listener: object | None = None

    def register(
        self,
        capture_hotkey: str,
        schedule_hotkey: str,
        on_capture: Callable[[], None],
        on_schedule: Callable[[], None] | None,
        item_lookup_hotkey: str = "",
        on_item_lookup: Callable[[], None] | None = None,
        hideout_scan_hotkey: str = "",
        on_hideout_scan: Callable[[], None] | None = None,
        reminder_hold_hotkey: str = "",
        on_reminder_hold: Callable[[], None] | None = None,
        display_filter_restore_hotkey: str = "",
        on_display_filter_restore: Callable[[], None] | None = None,
        extra_hotkeys: list[tuple[str, Callable[[], None]]] | None = None,
    ) -> None:
        self.unregister()
        try:
            from pynput import keyboard  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pynput is not installed; global hotkeys are disabled.") from exc

        bindings = {}
        if capture_hotkey.strip():
            bindings[normalize_hotkey(capture_hotkey)] = _direct(on_capture)
        if schedule_hotkey.strip() and on_schedule is not None:
            bindings[normalize_hotkey(schedule_hotkey)] = _direct(on_schedule)
        if item_lookup_hotkey.strip() and on_item_lookup is not None:
            bindings[normalize_hotkey(item_lookup_hotkey)] = _direct(on_item_lookup)
        if hideout_scan_hotkey.strip() and on_hideout_scan is not None:
            bindings[normalize_hotkey(hideout_scan_hotkey)] = _direct(on_hideout_scan)
        if reminder_hold_hotkey.strip() and on_reminder_hold is not None:
            bindings[normalize_hotkey(reminder_hold_hotkey)] = _direct(on_reminder_hold)
        if display_filter_restore_hotkey.strip() and on_display_filter_restore is not None:
            bindings[normalize_hotkey(display_filter_restore_hotkey)] = _direct(
                on_display_filter_restore
            )
        for hotkey, callback in extra_hotkeys or []:
            if hotkey.strip():
                bindings[normalize_hotkey(hotkey)] = _direct(callback)
        if not bindings:
            return

        parsed_bindings = [
            (frozenset(keyboard.HotKey.parse(hotkey)), callback)
            for hotkey, callback in bindings.items()
        ]
        pressed: set[object] = set()
        activated: set[int] = set()
        listener: object

        def on_press(key: object) -> None:
            canonical = listener.canonical(key)  # type: ignore[attr-defined]
            if canonical in pressed:
                return
            pressed.add(canonical)
            current = frozenset(pressed)
            for index, (required, callback) in enumerate(parsed_bindings):
                if current == required and index not in activated:
                    activated.add(index)
                    callback()

        def on_release(key: object) -> None:
            canonical = listener.canonical(key)  # type: ignore[attr-defined]
            pressed.discard(canonical)
            for index, (required, _callback) in enumerate(parsed_bindings):
                if not required.issubset(pressed):
                    activated.discard(index)

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener = listener
        listener.start()  # type: ignore[attr-defined]

    def unregister(self, join_timeout: float = 1.0) -> None:
        if self._listener is None:
            return
        listener = self._listener
        try:
            listener.stop()  # type: ignore[attr-defined]
        finally:
            self._listener = None
        join = getattr(listener, "join", None)
        if callable(join):
            with suppress(RuntimeError):
                join(timeout=max(0.0, join_timeout))


def normalize_hotkey(value: str) -> str:
    """Convert user-friendly hotkeys like F8 or Ctrl+Shift+O to pynput format."""
    raw = value.strip()
    if not raw:
        raise ValueError("Hotkey cannot be empty.")

    parts = [part.strip().lower() for part in re.split(r"\+", raw) if part.strip()]
    normalized: list[str] = []
    for part in parts:
        aliases = {
            "ctrl": "<ctrl>",
            "control": "<ctrl>",
            "shift": "<shift>",
            "alt": "<alt>",
            "cmd": "<cmd>",
            "win": "<cmd>",
        }
        if part in aliases:
            normalized.append(aliases[part])
        elif re.fullmatch(r"f([1-9]|1[0-2])", part):
            normalized.append(f"<{part}>")
        elif re.fullmatch(r"[a-z0-9]", part):
            normalized.append(part)
        else:
            raise ValueError(f"Unsupported hotkey part: {part}")

    return "+".join(normalized)


def _direct(callback: Callable[[], None]) -> Callable[[], None]:
    def wrapped() -> None:
        callback()

    return wrapped
