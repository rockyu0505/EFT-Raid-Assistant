from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from app.config import APP_DIR
from app.updater import (
    DEFAULT_RELEASE_PAGE,
    UPDATER_EXE_NAME,
    DownloadedUpdate,
    ReleaseInfo,
    UpdateCancelled,
    UpdateCheckResult,
    check_for_update,
    configured_manifest_urls,
    download_update,
    launch_update_helper,
    read_current_version,
    read_update_result,
)


@dataclass(frozen=True)
class DownloadTaskResult:
    downloaded: DownloadedUpdate | None = None
    error: str = ""
    cancelled: bool = False


class UpdateCoordinator(QObject):
    check_finished = Signal(object, bool)
    download_progress = Signal(int, int)
    download_finished = Signal(object)
    restart_requested = Signal()

    def __init__(
        self,
        config: dict[str, object],
        parent: QWidget,
        *,
        log: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._parent = parent
        self._log = log or (lambda _message: None)
        self._closing = False
        self._checking = False
        self._downloading = False
        self._offered_version = ""
        self._active_release: ReleaseInfo | None = None
        self._download_cancel = threading.Event()
        self._threads: set[threading.Thread] = set()
        self._threads_lock = threading.Lock()
        self._progress_dialog: QProgressDialog | None = None
        self.check_finished.connect(self._on_check_finished)
        self.download_progress.connect(self._on_download_progress)
        self.download_finished.connect(self._on_download_finished)

    def schedule_startup_check(self) -> None:
        if not self._startup_check_supported():
            return
        QTimer.singleShot(700, self.show_previous_update_result)
        QTimer.singleShot(1800, lambda: self.check_now(interactive=False))

    def show_previous_update_result(self) -> None:
        if self._closing:
            return
        result = read_update_result(APP_DIR)
        if not result:
            return
        success = bool(result.get("success", False))
        version = str(result.get("version", "")).strip()
        message = str(result.get("message", "")).strip()
        if success:
            QMessageBox.information(
                self._parent,
                "更新完成",
                message or f"EFT Raid Assistant 已更新到 {version}。",
            )
            return
        QMessageBox.warning(
            self._parent,
            "自动更新未完成",
            message or "更新失败，程序已尝试恢复旧版本。",
        )

    def check_now(self, *, interactive: bool = True) -> None:
        if self._closing:
            return
        if self._checking:
            if interactive:
                QMessageBox.information(self._parent, "检查更新", "正在检查更新，请稍候。")
            return
        self._checking = True

        def work() -> None:
            try:
                current = read_current_version()
                urls = configured_manifest_urls(
                    self._config.get("update_manifest_urls")
                )
                result = check_for_update(current, manifest_urls=urls)
            except Exception as exc:
                result = UpdateCheckResult(current_version="", error=str(exc))
            self.check_finished.emit(result, interactive)

        self._start_thread("app-update-check", work)

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._download_cancel.set()
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None
        deadline = time.monotonic() + 0.8
        with self._threads_lock:
            threads = list(self._threads)
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)

    def _on_check_finished(self, result: object, interactive: bool) -> None:
        self._checking = False
        if self._closing or not isinstance(result, UpdateCheckResult):
            return
        if result.manifest_unavailable:
            self._log(f"软件更新清单尚未发布：{result.error}")
            if interactive:
                QMessageBox.information(
                    self._parent,
                    "检查更新",
                    f"当前版本：{result.current_version}\n\n"
                    "当前发布渠道尚未提供自动更新清单。\n"
                    "这通常表示最新正式版早于自动更新功能；现有版本可以继续使用。",
                )
            return
        if result.error:
            self._log(f"软件更新检查失败：{result.error}")
            if interactive:
                self._show_check_error(result.error)
            return
        release = result.release
        if release is None or not result.update_available:
            self._log(f"软件更新检查完成：当前版本 {result.current_version}。")
            if interactive:
                QMessageBox.information(
                    self._parent,
                    "检查更新",
                    f"当前已是最新版本：{result.current_version}",
                )
            return
        if not interactive and self._offered_version == release.version:
            return
        self._offered_version = release.version
        self._active_release = release
        self._offer_release(release, result.current_version)

    def _offer_release(self, release: ReleaseInfo, current_version: str) -> None:
        dialog = QMessageBox(self._parent)
        dialog.setWindowTitle("发现软件更新")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(f"发现 EFT Raid Assistant {release.version}")
        dialog.setInformativeText(
            f"当前版本：{current_version}\n"
            f"更新包：{release.package.size / (1024 * 1024):.1f} MB\n\n"
            "是否自动下载并校验更新？下载期间可以继续使用程序。"
        )
        if release.notes:
            dialog.setDetailedText(release.notes[:12000])
        download_button = dialog.addButton("下载并更新", QMessageBox.ButtonRole.AcceptRole)
        later_button = dialog.addButton("暂不更新", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(download_button)
        dialog.exec()
        if dialog.clickedButton() == download_button:
            self._start_download(release)
        elif dialog.clickedButton() == later_button:
            self._log(f"用户暂缓了 {release.version} 更新。")

    def _start_download(self, release: ReleaseInfo) -> None:
        if self._downloading or self._closing:
            return
        if not self._automatic_apply_supported():
            self._offer_manual_download(
                release.release_page,
                "当前运行方式不支持自动替换，请打开发布页手动下载完整 ZIP。",
            )
            return
        self._downloading = True
        self._download_cancel = threading.Event()
        dialog = QProgressDialog(
            f"正在下载 EFT Raid Assistant {release.version}…",
            "取消",
            0,
            1000,
            self._parent,
        )
        dialog.setWindowTitle("下载软件更新")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        dialog.canceled.connect(self._download_cancel.set)
        dialog.show()
        self._progress_dialog = dialog

        def progress(received: int, total: int) -> None:
            self.download_progress.emit(int(received), int(total))

        def work() -> None:
            try:
                downloaded = download_update(
                    release,
                    destination_root=APP_DIR / ".update-cache",
                    progress=progress,
                    cancel_event=self._download_cancel,
                )
                result = DownloadTaskResult(downloaded=downloaded)
            except UpdateCancelled as exc:
                result = DownloadTaskResult(error=str(exc), cancelled=True)
            except Exception as exc:
                result = DownloadTaskResult(error=str(exc))
            self.download_finished.emit(result)

        self._start_thread("app-update-download", work)

    def _on_download_progress(self, received: int, total: int) -> None:
        dialog = self._progress_dialog
        if dialog is None or total <= 0:
            return
        value = max(0, min(1000, int(received * 1000 / total)))
        dialog.setValue(value)
        dialog.setLabelText(
            f"正在下载 {received / (1024 * 1024):.1f} / "
            f"{total / (1024 * 1024):.1f} MB"
        )

    def _on_download_finished(self, result: object) -> None:
        self._downloading = False
        dialog = self._progress_dialog
        self._progress_dialog = None
        if dialog is not None:
            dialog.close()
        if self._closing or not isinstance(result, DownloadTaskResult):
            return
        if result.cancelled:
            self._log("软件更新下载已取消；临时文件保留用于下次续传。")
            return
        if result.downloaded is None:
            self._log(f"软件更新下载失败：{result.error}")
            release_page = (
                self._active_release.release_page
                if self._active_release is not None
                else DEFAULT_RELEASE_PAGE
            )
            self._offer_manual_download(release_page, result.error)
            return
        downloaded = result.downloaded
        answer = QMessageBox.question(
            self._parent,
            "更新已下载并校验",
            f"EFT Raid Assistant {downloaded.release.version} 已通过 SHA-256 和文件结构校验。\n\n"
            "需要重启程序才能完成替换。是否立即重启并更新？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._log("更新包已缓存，将在下次确认后快速进入重启步骤。")
            return
        try:
            launch_update_helper(downloaded)
        except Exception as exc:
            QMessageBox.critical(self._parent, "无法启动更新助手", str(exc))
            return
        self.restart_requested.emit()

    def _show_check_error(self, error: str) -> None:
        self._offer_manual_download(
            DEFAULT_RELEASE_PAGE,
            f"无法连接更新服务：\n{error}",
        )

    def _offer_manual_download(self, release_page: str, message: str) -> None:
        dialog = QMessageBox(self._parent)
        dialog.setWindowTitle("自动更新暂不可用")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(message)
        dialog.setInformativeText("可以打开 GitHub 发布页手动下载；现有版本不会受到影响。")
        open_button = dialog.addButton("打开发布页", QMessageBox.ButtonRole.AcceptRole)
        close_button = dialog.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(open_button)
        dialog.exec()
        if dialog.clickedButton() == open_button:
            QDesktopServices.openUrl(QUrl(release_page))
        elif dialog.clickedButton() == close_button:
            return

    def _start_thread(self, name: str, target: Callable[[], None]) -> None:
        def run() -> None:
            try:
                target()
            finally:
                with self._threads_lock:
                    self._threads.discard(threading.current_thread())

        thread = threading.Thread(target=run, name=name, daemon=True)
        with self._threads_lock:
            self._threads.add(thread)
        thread.start()

    @staticmethod
    def _startup_check_supported() -> bool:
        return (
            bool(getattr(sys, "frozen", False))
            and os.environ.get("EFT_SMOKE_TEST") != "1"
        )

    @staticmethod
    def _automatic_apply_supported() -> bool:
        return (
            os.name == "nt"
            and bool(getattr(sys, "frozen", False))
            and (APP_DIR / UPDATER_EXE_NAME).is_file()
        )
