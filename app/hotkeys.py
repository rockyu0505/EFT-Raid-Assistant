from __future__ import annotations

import re
import threading
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
            bindings[normalize_hotkey(capture_hotkey)] = _threaded(on_capture)
        if schedule_hotkey.strip() and on_schedule is not None:
            bindings[normalize_hotkey(schedule_hotkey)] = _threaded(on_schedule)
        if item_lookup_hotkey.strip() and on_item_lookup is not None:
            bindings[normalize_hotkey(item_lookup_hotkey)] = _threaded(on_item_lookup)
        if hideout_scan_hotkey.strip() and on_hideout_scan is not None:
            bindings[normalize_hotkey(hideout_scan_hotkey)] = _threaded(on_hideout_scan)
        if reminder_hold_hotkey.strip() and on_reminder_hold is not None:
            bindings[normalize_hotkey(reminder_hold_hotkey)] = _threaded(on_reminder_hold)
        if display_filter_restore_hotkey.strip() and on_display_filter_restore is not None:
            bindings[normalize_hotkey(display_filter_restore_hotkey)] = _threaded(
                on_display_filter_restore
            )
        for hotkey, callback in extra_hotkeys or []:
            if hotkey.strip():
                bindings[normalize_hotkey(hotkey)] = _threaded(callback)
        if not bindings:
            return
        self._listener = keyboard.GlobalHotKeys(bindings)
        self._listener.start()

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


def _threaded(callback: Callable[[], None]) -> Callable[[], None]:
    def wrapped() -> None:
        threading.Thread(target=callback, daemon=True).start()

    return wrapped
