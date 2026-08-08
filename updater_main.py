from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
from pathlib import Path

from app.update_apply import apply_update, write_update_result
from app.updater import APP_NAME, UpdateError


SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x00000102


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply an EFT Raid Assistant update.")
    parser.add_argument("--package", required=True)
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--restart-exe", required=True)
    args = parser.parse_args()

    install_dir = Path(args.install_dir).resolve()
    restart_exe = Path(args.restart_exe).resolve()
    success = False
    message = ""
    try:
        _wait_for_process(args.pid, timeout_ms=120_000)
        apply_update(
            Path(args.package),
            install_dir,
            expected_version=args.expected_version,
            expected_sha256=args.sha256,
        )
        success = True
        message = f"已更新到 {args.expected_version}。"
    except Exception as exc:
        message = str(exc)
        _show_error(f"自动更新失败，旧版本已尽力恢复。\n\n{message}")

    try:
        write_update_result(
            install_dir,
            success=success,
            version=args.expected_version,
            message=message,
        )
    except OSError:
        pass

    if restart_exe.parent == install_dir and restart_exe.is_file():
        try:
            subprocess.Popen(
                [str(restart_exe)],
                cwd=install_dir,
                close_fds=True,
                creationflags=0x00000008 | 0x00000200,
            )
        except OSError as exc:
            _show_error(f"更新处理完成，但无法重新启动程序。\n\n{exc}")
            return 2
    return 0 if success else 1


def _wait_for_process(pid: int, *, timeout_ms: int) -> None:
    if sys.platform != "win32":
        raise UpdateError("更新助手只能在 Windows 上运行。")
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return
    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout_ms))
        if result == WAIT_TIMEOUT:
            raise UpdateError(f"等待 {APP_NAME} 退出超时。")
    finally:
        kernel32.CloseHandle(handle)


def _show_error(message: str) -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            str(message),
            f"{APP_NAME} 更新助手",
            0x00000010,
        )
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
