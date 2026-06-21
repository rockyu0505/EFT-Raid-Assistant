from __future__ import annotations

import re
import threading
from collections.abc import Callable


class HotkeyManager:
    def __init__(self) -> None:
        self._listener: object | None = None

    def register(
        self,
        capture_hotkey: str,
        schedule_hotkey: str,
        on_capture: Callable[[], None],
        on_schedule: Callable[[], None],
        item_lookup_hotkey: str = "",
        on_item_lookup: Callable[[], None] | None = None,
    ) -> None:
        self.unregister()
        try:
            from pynput import keyboard  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pynput is not installed; global hotkeys are disabled.") from exc

        bindings = {
            normalize_hotkey(capture_hotkey): _threaded(on_capture),
            normalize_hotkey(schedule_hotkey): _threaded(on_schedule),
        }
        if item_lookup_hotkey.strip() and on_item_lookup is not None:
            bindings[normalize_hotkey(item_lookup_hotkey)] = _threaded(on_item_lookup)
        self._listener = keyboard.GlobalHotKeys(bindings)
        self._listener.start()

    def unregister(self) -> None:
        if self._listener is None:
            return
        try:
            self._listener.stop()  # type: ignore[attr-defined]
        finally:
            self._listener = None


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
