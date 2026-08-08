from __future__ import annotations

import copy
import gc
import html
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    QModelIndex,
    QPoint,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QSequentialAnimationGroup,
    QSignalBlocker,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QCloseEvent,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QSpinBox,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.capture import (
    Region,
    capture_hideout_screen,
    capture_hover_item_name_region,
    capture_inventory_tab_region,
    capture_item_name_region,
    capture_timer_strip,
    debug_paths,
    hideout_debug_path,
    is_tarkov_foreground,
    item_debug_path,
    resolve_capture_region,
    save_item_lookup_debug_images,
    scale_metric,
)
from app.config import (
    APP_DIR,
    HOVER_SEARCH_MARGINS,
    INVENTORY_TAB_ROI_BASE,
    RESOURCE_DIR,
    achievements_tab_roi_candidates,
    inventory_tab_roi_candidates,
    load_config,
    save_config,
)
from app.config import CONFIG_PATH, DEFAULT_ENABLED_FEATURES, FEATURE_DEFINITIONS
from app.display_filter import (
    DisplayFilterBaseline,
    DisplayFilterError,
    DisplayTarget,
    build_gamma_ramp,
    enumerate_display_targets,
    preferred_display_target_id,
    probe_display_target,
    restore_display_filter as restore_system_display_filter,
    start_display_filter,
    update_display_filter,
)
from app.diagnostics import create_diagnostic_bundle
from app.hideout import HideoutDataError, HideoutTracker
from app.hideout_ocr import hideout_ocr_text_path, run_hideout_ocr
from app.hotkeys import HotkeyManager, normalize_hotkey
from app.game_modes import (
    GAME_MODES,
    GAME_MODE_CHOICES,
    game_mode_label,
    normalize_game_mode,
)
from app.item_ocr import (
    detect_character_header_image,
    detect_inventory_tab_image,
    iter_item_name_ocr_image_attempts,
    refine_tooltip_name_image,
    run_item_name_ocr_image,
    tooltip_line_count_hint,
)
from app.models import TRADERS, TraderReminder
from app.ocr import OcrUnavailableError, run_ocr, timer_to_seconds
from app.prices import (
    PriceLookupError,
    TarkovPriceClient,
    calculate_flea_market_fee,
    ensure_editable_aliases_path,
)
from app.price_estimator import (
    SmartPriceEstimate,
    build_fast_price_estimate,
    classify_sale_region,
)
from app.rapid_ocr import configure_rapid_ocr_threads
from app.reminders import ReminderManager, format_countdown, remaining_countdown_seconds
from app.recipes import (
    RecipeCatalog,
    RecipeDataError,
    RecipeNotice,
    recipe_acquisition_text,
    recipe_requirement_rows,
    recipe_search_text,
    recipe_source_text,
    recipe_unlock_note,
)
from app.ui.raid_overlays import RaidControlOverlay, RaidLogOverlay
from app.ui.state import LogBus, SettingsStore
from app.ui.theme import THEME_LABELS, apply_app_theme
from app.update_ui import UpdateCoordinator


DISPLAY_FILTER_SLIDERS = {
    "gamma": ("Gamma 曲线", 40, 160, 100, 2),
    "black_lift": ("暗部抬升", 0, 35, 100, 2),
    "gain": ("亮度/Gain", 50, 125, 100, 2),
    "contrast": ("对比度", 65, 145, 100, 2),
}

HANDBOOK_ROOT_ORDER = {
    name: index
    for index, name in enumerate(
        (
            "barter-items",
            "gear",
            "weapon-parts-mods",
            "weapons",
            "ammo",
            "provisions",
            "medication",
            "keys",
            "info-items",
            "special-equipment",
            "task-items",
            "maps",
            "money",
        )
    )
}


HOTKEY_CONFIG_LABELS = [
    ("capture_hotkey", "识别倒计时"),
    ("item_lookup_hotkey", "物品查价"),
    ("hideout_scan_hotkey", "识别藏身处"),
    ("reminder_hold_hotkey", "显示/隐藏补货倒计时"),
    ("raid_panel_hotkey", "打开/关闭局内控制"),
    ("raid_log_hotkey", "打开/关闭局内日志"),
    ("display_filter_restore_hotkey", "恢复 Gamma"),
]

MAX_VISIBLE_RECIPE_NOTICES = 3


class HotkeyLineEdit(QLineEdit):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self._capture_start_text = ""
        self._conflict_checker: Callable[["HotkeyLineEdit", str], bool] | None = None
        self.setPlaceholderText("点击后按一次快捷键；右键取消，Backspace/Delete 清空")
        self.setToolTip("点击输入框后直接按下要绑定的按键或组合键，例如 F9、Alt+2、Ctrl+Alt+1；右键恢复本次设定前的按键。")

    def set_conflict_checker(
        self, checker: Callable[["HotkeyLineEdit", str], bool] | None
    ) -> None:
        self._conflict_checker = checker

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        super().focusInEvent(event)
        self._capture_start_text = self.text()
        self.selectAll()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.RightButton:
            self.setText(self._capture_start_text)
            self.clearFocus()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        key = int(event.key())
        if key == int(Qt.Key.Key_Escape):
            self.clearFocus()
            event.accept()
            return
        if key in (int(Qt.Key.Key_Backspace), int(Qt.Key.Key_Delete)):
            self.clear()
            event.accept()
            return

        hotkey = _hotkey_text_from_event(event)
        if hotkey is None:
            event.accept()
            return
        if not hotkey:
            QMessageBox.information(
                self,
                "不支持的快捷键",
                "目前支持 F1-F12、字母、数字，以及 Ctrl/Shift/Alt/Win 组合。",
            )
            event.accept()
            return
        if self._conflict_checker is not None and not self._conflict_checker(self, hotkey):
            event.accept()
            return
        self.setText(hotkey)
        self.clearFocus()
        event.accept()


def _hotkey_text_from_event(event) -> str | None:
    key = int(event.key())
    if key in {
        int(Qt.Key.Key_Control),
        int(Qt.Key.Key_Shift),
        int(Qt.Key.Key_Alt),
        int(Qt.Key.Key_Meta),
    }:
        return None

    parts: list[str] = []
    modifiers = event.modifiers()
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        parts.append("Ctrl")
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        parts.append("Shift")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        parts.append("Alt")
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        parts.append("Win")

    if int(Qt.Key.Key_F1) <= key <= int(Qt.Key.Key_F12):
        parts.append(f"F{key - int(Qt.Key.Key_F1) + 1}")
    elif int(Qt.Key.Key_0) <= key <= int(Qt.Key.Key_9):
        parts.append(chr(ord("0") + key - int(Qt.Key.Key_0)))
    elif int(Qt.Key.Key_A) <= key <= int(Qt.Key.Key_Z):
        parts.append(chr(ord("A") + key - int(Qt.Key.Key_A)))
    else:
        return ""
    return "+".join(parts)


@dataclass(frozen=True)
class PriceCacheRefreshResult:
    source: str
    counts: dict[str, int] | None = None
    error: str = ""


class MainWindow(QMainWindow):
    capture_requested = Signal()
    item_lookup_requested = Signal()
    hideout_scan_requested = Signal()
    reminder_hold_requested = Signal()
    raid_panel_toggle_requested = Signal()
    raid_log_toggle_requested = Signal()
    display_filter_restore_requested = Signal()
    display_filter_preset_requested = Signal(str)
    price_result_ready = Signal(object, str)
    price_lookup_timing_ready = Signal(str, float)
    price_history_ready = Signal(object, object, str)
    cache_refresh_ready = Signal(object)
    price_history_json_failed = Signal(object, str)
    hideout_scan_ready = Signal(object, str)
    hideout_cache_ready = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("塔科夫局内助手")
        self.config = load_config()
        if os.environ.get("EFT_SMOKE_TEST") == "1":
            self.config["feature_setup_complete"] = True
            self.config["refresh_prices_on_startup"] = False
        self.resize(1520, 920)
        self.setMinimumSize(1160, 720)
        self._restore_main_window_geometry()

        self.settings_store = SettingsStore(self.config, self)
        self._display_targets: list[DisplayTarget] = enumerate_display_targets()
        self.config["display_filter_target_id"] = preferred_display_target_id(
            self.config.get("display_filter_target_id", ""),
            self._display_targets,
        )
        self.log_bus = LogBus(self)
        self._first_run = not CONFIG_PATH.exists()
        self._runtime_enabled_features: set[str] = set()
        self._maybe_run_feature_setup()
        self._runtime_enabled_features = self._configured_enabled_features()
        self.hotkeys = HotkeyManager()
        self.reminders = ReminderManager() if self._feature_enabled("trader_reminders") else None
        self.price_client = TarkovPriceClient() if self._feature_enabled("price_lookup") else None
        self.hideout_tracker = HideoutTracker() if self._feature_enabled("hideout") else None
        self.recipe_catalog: RecipeCatalog | None = None
        self._recipe_data_error = ""
        self._last_data_error = ""
        if self._feature_enabled("recipe_tracking"):
            try:
                self.recipe_catalog = RecipeCatalog()
            except RecipeDataError as exc:
                self._recipe_data_error = str(exc)
        self.current_price_game_mode = str(self.config.get("price_game_mode_default", "pve"))
        if self.price_client is not None:
            self.current_price_game_mode = self.price_client.set_game_mode(
                self.current_price_game_mode
            )
        else:
            self.current_price_game_mode = normalize_game_mode(
                self.current_price_game_mode
            )
        self.price_overlay = PriceOverlay() if self._feature_enabled("price_lookup") else None
        self.feedback_overlay = (
            FeedbackOverlay()
            if any(
                self._feature_enabled(feature)
                for feature in ("trader_reminders", "hideout", "display_filter")
            )
            else None
        )
        self.reminder_overlay = (
            ReminderOverlay(str(self.config.get("reminder_hold_hotkey", "F7")))
            if self._feature_enabled("trader_reminders")
            else None
        )
        self.raid_control_overlay = RaidControlOverlay()
        self.raid_log_overlay = RaidLogOverlay(
            max_lines=int(self.config.get("raid_log_max_lines", 200))
        )
        self.raid_log_overlay.set_opacity_percent(
            int(self.config.get("raid_log_opacity", 72))
        )
        self.raid_control_overlay.set_saved_position(
            self.config.get("raid_panel_position")
        )
        self.raid_log_overlay.set_saved_position(self.config.get("raid_log_position"))
        self.raid_control_overlay.position_changed.connect(
            lambda x, y: self._set_live_setting("raid_panel_position", [x, y])
        )
        self.raid_log_overlay.position_changed.connect(
            lambda x, y: self._set_live_setting("raid_log_position", [x, y])
        )
        self.log_bus.line_ready.connect(self.raid_log_overlay.append_line)
        self._display_filter_baseline: DisplayFilterBaseline | None = None
        self._display_filter_index = -1
        self._display_filter_controls_loading = False
        self._display_filter_dialog: DisplayFilterControlDialog | None = None
        self._display_filter_eye_timer = QTimer(self)
        self._display_filter_eye_timer.timeout.connect(self._on_display_filter_eye_care_check)
        self._resource_cleanup_timer = QTimer(self)
        self._resource_cleanup_timer.timeout.connect(self._on_resource_cleanup_timer)
        self._config_save_timer = QTimer(self)
        self._config_save_timer.setSingleShot(True)
        self._config_save_timer.timeout.connect(self._save_config)
        self._run_log_path = APP_DIR / "debug" / "latest_run.log"
        self._reset_run_log()
        self._cached_item_region: Region | None = None
        self._item_region_calibrated = False
        self._inventory_check_cache: (
            tuple[float, tuple[int, int] | None, bool, list[str]] | None
        ) = None
        self._character_header_check_cache: (
            tuple[float, tuple[int, int] | None, bool, list[str]] | None
        ) = None
        self._closing = False
        self._workers: set[threading.Thread] = set()
        self._workers_lock = threading.Lock()
        self._force_exit = False
        self._tray_notice_shown = False
        self._active_price_key = ""
        self.tray_icon: QSystemTrayIcon | None = None
        self.update_coordinator: UpdateCoordinator | None = None
        self.item_completion_model = QStandardItemModel(0, 2, self)
        self.item_completion_lookup: dict[str, str] = {}
        self.panel_buttons: list[QPushButton] = []

        self.watch_checks: dict[str, QCheckBox] = {}
        self.countdown_items: dict[str, QTableWidgetItem] = {}
        self.restock_items: dict[str, QTableWidgetItem] = {}
        self.status_items: dict[str, QTableWidgetItem] = {}
        self._recipe_tree_loading = False

        if self.reminders is not None:
            self.reminders.reminder_triggered.connect(self._on_reminder_triggered)
            self.reminders.reminders_updated.connect(self._on_reminders_updated)
        self.capture_requested.connect(self.capture_and_ocr)
        self.item_lookup_requested.connect(self.capture_item_price)
        self.hideout_scan_requested.connect(self.capture_hideout_progress)
        self.reminder_hold_requested.connect(self.toggle_reminder_hold)
        self.raid_panel_toggle_requested.connect(self.toggle_raid_control_overlay)
        self.raid_log_toggle_requested.connect(self.toggle_raid_log_overlay)
        self.display_filter_restore_requested.connect(self.restore_display_filter)
        self.display_filter_preset_requested.connect(self.apply_display_filter_preset_by_name)
        self.price_result_ready.connect(self._on_price_result_ready)
        self.price_lookup_timing_ready.connect(self._on_price_lookup_timing_ready)
        self.price_history_ready.connect(self._on_price_history_ready)
        self.cache_refresh_ready.connect(self._on_cache_refresh_ready)
        self.price_history_json_failed.connect(self._on_price_history_json_failed)
        self.hideout_scan_ready.connect(self._on_hideout_scan_ready)
        self.hideout_cache_ready.connect(self._on_hideout_cache_ready)
        self.raid_control_overlay.game_mode_changed.connect(
            self._on_raid_game_mode_changed
        )
        self.raid_control_overlay.language_changed.connect(
            lambda value: self._set_live_setting("item_display_language", value)
        )
        self.raid_control_overlay.price_duration_changed.connect(
            lambda value: self._set_live_setting("price_overlay_seconds", value)
        )
        self.raid_control_overlay.feedback_duration_changed.connect(
            lambda value: self._set_live_setting("feedback_overlay_seconds", value)
        )
        self.raid_control_overlay.panel_opacity_changed.connect(
            lambda value: self._set_live_setting("raid_panel_opacity", value)
        )
        self.raid_control_overlay.display_target_changed.connect(
            self._on_raid_display_target_changed
        )
        self.raid_control_overlay.gamma_enabled_changed.connect(
            self._on_raid_gamma_enabled_changed
        )
        self.raid_control_overlay.gamma_values_changed.connect(
            self._on_raid_gamma_values_changed
        )
        self.raid_control_overlay.gamma_restore_requested.connect(
            lambda: self.restore_display_filter(show_feedback=False)
        )

        self._build_ui()
        self.log_bus.visible_line_ready.connect(self._append_main_log_line)
        self._build_tray_icon()
        self.update_coordinator = UpdateCoordinator(
            self.config,
            self,
            log=self._log_event,
        )
        self.update_coordinator.restart_requested.connect(
            self._restart_for_app_update
        )
        self.update_coordinator.schedule_startup_check()
        self._refresh_item_completer()
        self._register_hotkeys()
        self._update_cache_status_label()
        self._sync_raid_control_overlay()
        self._apply_performance_settings()
        if self._should_auto_refresh_price_cache():
            self.refresh_price_cache(background=True)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._should_minimize_to_tray():
            action = self._confirm_close_action()
            if action == "tray":
                event.ignore()
                self.hide_to_tray()
                return
            if action == "exit":
                self._force_exit = True
                self.shutdown()
                event.accept()
                QApplication.quit()
                return
            event.ignore()
            return
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._capture_main_window_geometry()
        if self._feature_enabled("display_filter") and bool(
            self.config.get("display_filter_restore_on_exit", True)
        ):
            self.restore_display_filter(show_feedback=False)
        self._save_config()
        if self.update_coordinator is not None:
            self.update_coordinator.shutdown()
        self.hotkeys.unregister(join_timeout=1.0)
        if self.reminders is not None:
            self.reminders.shutdown()
        if self.price_overlay is not None:
            self.price_overlay.hide()
        if self.feedback_overlay is not None:
            self.feedback_overlay.hide()
        if self.reminder_overlay is not None:
            self.reminder_overlay.hide()
        self.raid_control_overlay.hide()
        self.raid_log_overlay.hide()
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self._join_workers(timeout=1.0)
        self._cleanup_memory()

    def _restore_main_window_geometry(self) -> None:
        value = self.config.get("main_window_geometry")
        if not isinstance(value, list) or len(value) < 4:
            return
        try:
            x, y, width, height = (int(value[index]) for index in range(4))
        except (TypeError, ValueError):
            return
        width = max(self.minimumWidth(), width)
        height = max(self.minimumHeight(), height)
        candidate = QRect(x, y, width, height)
        screens = QApplication.screens()
        if screens and not any(
            screen.availableGeometry().intersects(candidate) for screen in screens
        ):
            return
        self.resize(width, height)
        self.move(QPoint(x, y))
        if len(value) >= 5 and bool(value[4]):
            self.setWindowState(
                self.windowState() | Qt.WindowState.WindowMaximized
            )

    def _capture_main_window_geometry(self) -> None:
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        self.config["main_window_geometry"] = [
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
            self.isMaximized(),
        ]

    def _configured_enabled_features(self) -> set[str]:
        value = self.config.get("enabled_features", DEFAULT_ENABLED_FEATURES)
        if not isinstance(value, list):
            return set(DEFAULT_ENABLED_FEATURES)
        return {str(item) for item in value if str(item) in FEATURE_DEFINITIONS}

    def _enabled_features(self) -> set[str]:
        runtime = getattr(self, "_runtime_enabled_features", None)
        if isinstance(runtime, set):
            return runtime
        return self._configured_enabled_features()

    def _feature_enabled(self, feature_id: str) -> bool:
        return feature_id in self._enabled_features()

    def _maybe_run_feature_setup(self) -> None:
        if not self._first_run or bool(self.config.get("feature_setup_complete", False)):
            return
        dialog = FeatureSetupDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config.update(dialog.values())
        else:
            self.config["enabled_features"] = DEFAULT_ENABLED_FEATURES.copy()
        self.config["feature_setup_complete"] = True
        save_config(self.config)

    def _build_panel_defs(self) -> list[tuple[str, Callable[[], QWidget]]]:
        panels: list[tuple[str, Callable[[], QWidget]]] = []
        if self._feature_enabled("price_lookup"):
            panels.append(("局内查价", self._build_price_panel))
        if self._feature_enabled("trader_reminders"):
            panels.append(("商人补货", self._build_trader_panel))
        if self._feature_enabled("price_lookup"):
            panels.append(("数据", self._build_data_panel))
        elif self._feature_enabled("hideout") or self._feature_enabled("recipe_tracking"):
            panels.append(("数据", self._build_data_panel))
        if self._feature_enabled("hideout"):
            panels.append(("藏身处", self._build_hideout_panel))
        if self._feature_enabled("display_filter"):
            panels.append(("Gamma", self._build_display_filter_panel))
        if self._feature_enabled("recipe_tracking"):
            panels.append(("关注配方", self._build_recipe_panel))
        if not panels:
            panels.append(("未启用", self._build_disabled_panel))
        return panels

    def _build_ui(self) -> None:
        self.setWindowIcon(_load_app_icon(self))
        self.menuBar().clear()
        self.panel_buttons.clear()
        self.watch_checks.clear()
        self.countdown_items.clear()
        self.restock_items.clear()
        self.status_items.clear()
        self._build_menu()

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        self._panel_defs = self._build_panel_defs()
        sidebar = self._build_sidebar()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        self.panel_stack = QStackedWidget()
        for _title, builder in self._panel_defs:
            self.panel_stack.addWidget(builder())
        self.panel_stack.setCurrentIndex(0)
        self._select_panel(0)

        self.main_log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(self.main_log_group)
        log_actions = QHBoxLayout()
        log_actions.addStretch(1)
        self.main_log_toggle_button = QPushButton("收起日志")
        self.main_log_toggle_button.clicked.connect(
            lambda: self._set_main_log_collapsed(
                not bool(self.config.get("main_log_collapsed", False))
            )
        )
        log_actions.addWidget(self.main_log_toggle_button)
        log_layout.addLayout(log_actions)
        log_layout.addWidget(self._build_log_panel())

        self.main_content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_content_splitter.setChildrenCollapsible(False)
        self.main_content_splitter.addWidget(self.panel_stack)
        self.main_content_splitter.addWidget(self.main_log_group)
        self.main_content_splitter.setStretchFactor(0, 1)
        self.main_content_splitter.setStretchFactor(1, 0)
        self.main_content_splitter.splitterMoved.connect(
            self._on_main_content_splitter_moved
        )
        log_height = max(100, _safe_int(self.config.get("main_log_height")) or 170)
        self.main_content_splitter.setSizes(
            [max(420, self.height() - log_height), log_height]
        )
        content_layout.addWidget(self.main_content_splitter, 1)
        self._set_main_log_collapsed(
            bool(self.config.get("main_log_collapsed", False)),
            persist=False,
        )

        layout.addWidget(sidebar)
        layout.addWidget(content, 1)
        self.setCentralWidget(root)

    def _set_main_log_collapsed(
        self, collapsed: bool, *, persist: bool = True
    ) -> None:
        if not hasattr(self, "main_log_group") or not hasattr(self, "log"):
            return
        collapsed = bool(collapsed)
        if not collapsed and hasattr(self, "main_content_splitter"):
            self.main_log_group.setMinimumHeight(0)
            self.main_log_group.setMaximumHeight(16777215)
            self.log.show()
            height = max(100, _safe_int(self.config.get("main_log_height")) or 170)
            total = max(
                sum(self.main_content_splitter.sizes()),
                self.main_content_splitter.height(),
                height + 420,
            )
            self.main_content_splitter.setSizes([max(420, total - height), height])
        else:
            sizes = self.main_content_splitter.sizes()
            if (
                not bool(self.config.get("main_log_collapsed", False))
                and len(sizes) >= 2
                and sizes[1] > 100
            ):
                self.config["main_log_height"] = sizes[1]
            self.log.hide()
            collapsed_height = max(
                58,
                self.main_log_toggle_button.sizeHint().height() + 46,
            )
            self.main_log_group.setMinimumHeight(collapsed_height)
            self.main_log_group.setMaximumHeight(collapsed_height)
            total = max(
                sum(sizes),
                self.main_content_splitter.height(),
                collapsed_height + 420,
            )
            self.main_content_splitter.setSizes(
                [max(420, total - collapsed_height), collapsed_height]
            )
            QTimer.singleShot(0, self._pin_collapsed_main_log_to_bottom)
        self.main_log_toggle_button.setText("展开日志" if collapsed else "收起日志")
        self.config["main_log_collapsed"] = collapsed
        if persist:
            self._config_save_timer.start(250)

    def _pin_collapsed_main_log_to_bottom(self) -> None:
        if (
            not hasattr(self, "main_content_splitter")
            or not bool(self.config.get("main_log_collapsed", False))
        ):
            return
        collapsed_height = self.main_log_group.maximumHeight()
        total = max(
            sum(self.main_content_splitter.sizes()),
            self.main_content_splitter.height(),
        )
        if total <= 0:
            return
        self.main_content_splitter.setSizes(
            [max(1, total - collapsed_height), collapsed_height]
        )

    def _on_main_content_splitter_moved(
        self, _position: int, _index: int
    ) -> None:
        if bool(self.config.get("main_log_collapsed", False)):
            return
        sizes = self.main_content_splitter.sizes()
        if len(sizes) >= 2 and sizes[1] > 0:
            self.config["main_log_height"] = max(100, sizes[1])
            self._config_save_timer.start(350)

    def _build_tray_icon(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._log("System tray is not available; close-to-tray is disabled.")
            return
        icon = _load_app_icon(self)
        self.setWindowIcon(icon)

        menu = QMenu(self)
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.show_from_tray)
        raid_control_action = QAction("打开/关闭局内控制", self)
        raid_control_action.triggered.connect(self.toggle_raid_control_overlay)
        raid_log_action = QAction("打开/关闭局内日志", self)
        raid_log_action.triggered.connect(self.toggle_raid_log_overlay)
        settings_action = QAction("设置", self)
        settings_action.triggered.connect(self.open_settings)
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.request_exit)
        menu.addAction(show_action)
        menu.addAction(raid_control_action)
        menu.addAction(raid_log_action)
        if self._feature_enabled("price_lookup"):
            price_action = QAction("立即查价", self)
            price_action.triggered.connect(lambda: self.item_lookup_requested.emit())
            menu.addAction(price_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(exit_action)

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("EFT Raid Assistant")
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _should_minimize_to_tray(self) -> bool:
        return (
            not self._force_exit
            and bool(self.config.get("close_to_tray", True))
            and self.tray_icon is not None
            and self.tray_icon.isVisible()
        )

    def _confirm_close_action(self) -> str:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("关闭 EFT Raid Assistant")
        dialog.setText("要把程序最小化到托盘，还是直接退出？")
        dialog.setInformativeText("最小化到托盘后，热键、查价和提醒会继续在后台运行。")
        tray_button = dialog.addButton("最小化到托盘", QMessageBox.ButtonRole.AcceptRole)
        exit_button = dialog.addButton("退出程序", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(tray_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked == tray_button:
            return "tray"
        if clicked == exit_button:
            return "exit"
        if clicked == cancel_button:
            return "cancel"
        return "cancel"

    def hide_to_tray(self) -> None:
        self.hide()
        if self.tray_icon is not None and not self._tray_notice_shown:
            self.tray_icon.showMessage(
                "EFT Raid Assistant 仍在运行",
                "窗口已最小化到托盘，热键和查价后台继续可用。右键托盘图标可退出。",
                QSystemTrayIcon.MessageIcon.Information,
                3500,
            )
            self._tray_notice_shown = True
        self._log("主窗口已最小化到托盘，后台热键保持运行。")

    def show_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def request_exit(self) -> None:
        self._force_exit = True
        self.close()
        QApplication.quit()

    def check_for_app_updates(self) -> None:
        if self.update_coordinator is None:
            QMessageBox.information(self, "检查更新", "更新组件尚未完成初始化。")
            return
        self.update_coordinator.check_now(interactive=True)

    def _restart_for_app_update(self) -> None:
        self._force_exit = True
        self.shutdown()
        self.close()
        QApplication.quit()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_from_tray()

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("appSidebar")
        sidebar.setFixedWidth(168)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 13, 10, 10)
        layout.setSpacing(8)

        eyebrow = QLabel("EFT / RAID")
        eyebrow.setObjectName("brandEyebrow")
        title = QLabel("ASSISTANT")
        title.setObjectName("brandTitle")
        meta = QLabel("LOCAL OPS CONSOLE")
        meta.setObjectName("brandMeta")
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(meta)
        layout.addSpacing(10)

        for index, (title, _builder) in enumerate(self._panel_defs):
            button = QPushButton(title)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.clicked.connect(lambda checked=False, page=index: self._select_panel(page))
            self.panel_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)

        settings_button = QPushButton("设置")
        settings_button.setObjectName("navButton")
        settings_button.setMinimumHeight(34)
        settings_button.clicked.connect(self.open_settings)
        layout.addWidget(settings_button)
        return sidebar

    def _select_panel(self, index: int) -> None:
        if hasattr(self, "panel_stack"):
            self.panel_stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.panel_buttons):
            button.setChecked(button_index == index)

    def _build_price_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(self._build_status_bar())
        layout.addWidget(self._build_item_lookup_group())
        layout.addStretch(1)
        return panel

    def _build_trader_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(self._build_trader_group())
        return panel

    def _build_data_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        status = QGroupBox("数据状态")
        status_layout = QVBoxLayout(status)
        self.data_status_label = QLabel("正在读取本地数据状态...")
        self.data_status_label.setWordWrap(True)
        self.data_error_label = QLabel("")
        self.data_error_label.setObjectName("dataErrorLabel")
        self.data_error_label.setWordWrap(True)
        status_layout.addWidget(self.data_status_label)
        status_layout.addWidget(self.data_error_label)

        actions = QGroupBox("数据维护")
        actions_layout = QVBoxLayout(actions)
        if self._feature_enabled("price_lookup"):
            refresh_button = QPushButton("刷新价格缓存")
            refresh_button.clicked.connect(
                lambda: self.refresh_price_cache(background=True)
            )
            reload_button = QPushButton("重新加载中文别名")
            reload_button.clicked.connect(self.reload_chinese_aliases)
            open_alias_button = QPushButton("打开中文别名文件")
            open_alias_button.clicked.connect(self.open_chinese_aliases)
            actions_layout.addWidget(refresh_button)
            actions_layout.addWidget(reload_button)
            actions_layout.addWidget(open_alias_button)
        if self._feature_enabled("hideout"):
            refresh_hideout_button = QPushButton("刷新藏身处需求数据")
            refresh_hideout_button.clicked.connect(
                lambda: self.refresh_hideout_cache(background=True)
            )
            actions_layout.addWidget(refresh_hideout_button)
        diagnostics_button = QPushButton("导出诊断包")
        diagnostics_button.setToolTip(
            "导出版本、设置摘要和最近调试文件，便于定位问题；不会修改现有数据。"
        )
        diagnostics_button.clicked.connect(self.export_diagnostics)
        actions_layout.addWidget(diagnostics_button)
        actions_layout.addStretch(1)

        layout.addWidget(status)
        layout.addWidget(actions)
        layout.addStretch(1)
        QTimer.singleShot(0, self._update_data_status_summary)
        return panel

    def _build_hideout_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        actions = QGroupBox("藏身处升级识别")
        actions_layout = QGridLayout(actions)
        self.hideout_status_label = QLabel("藏身处: 尚未识别")
        self.hideout_status_label.setWordWrap(True)
        scan_button = QPushButton("识别藏身处升级")
        scan_button.clicked.connect(self.capture_hideout_progress)
        refresh_button = QPushButton("刷新需求数据")
        refresh_button.clicked.connect(lambda: self.refresh_hideout_cache(background=True))
        open_screenshot_button = QPushButton("打开藏身处截图")
        open_screenshot_button.clicked.connect(self.open_hideout_screenshot)
        open_ocr_button = QPushButton("打开 OCR 文本")
        open_ocr_button.clicked.connect(self.open_hideout_ocr_text)
        actions_layout.addWidget(self.hideout_status_label, 0, 0, 1, 4)
        actions_layout.addWidget(scan_button, 1, 0)
        actions_layout.addWidget(refresh_button, 1, 1)
        actions_layout.addWidget(open_screenshot_button, 1, 2)
        actions_layout.addWidget(open_ocr_button, 1, 3)

        self.hideout_table = QTableWidget(0, 6)
        self.hideout_table.setHorizontalHeaderLabels(
            ["设施", "当前等级", "升级等级", "识别数量", "升级需求", "更新时间"]
        )
        self.hideout_table.verticalHeader().setVisible(False)
        self.hideout_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hideout_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.hideout_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.hideout_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.hideout_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.hideout_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.hideout_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )

        layout.addWidget(actions)
        layout.addWidget(self.hideout_table, 1)
        self._update_hideout_table()
        return panel

    def _build_recipe_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        header = QGroupBox("关注制作 / 商人兑换")
        header_layout = QVBoxLayout(header)
        intro = QLabel(
            "按游戏手册的产物分类浏览，展开产物后勾选具体制作或兑换。"
            "查到关注配方的材料时，价格浮窗会追加用途卡片。"
        )
        intro.setWordWrap(True)
        header_layout.addWidget(intro)

        search_row = QHBoxLayout()
        self.recipe_search_field = QLineEdit()
        self.recipe_search_field.setPlaceholderText("搜索产物、来源、任务或所需物品")
        self.recipe_search_field.textChanged.connect(self._populate_recipe_results)
        collapse_button = QPushButton("折叠配方")
        collapse_button.clicked.connect(lambda: self.recipe_result_tree.collapseAll())
        search_row.addWidget(self.recipe_search_field, 1)
        search_row.addWidget(collapse_button)
        header_layout.addLayout(search_row)

        self.recipe_summary_label = QLabel("")
        self.recipe_summary_label.setWordWrap(True)
        header_layout.addWidget(self.recipe_summary_label)
        layout.addWidget(header)

        self.recipe_tabs = QTabWidget()

        browser = QWidget()
        browser_layout = QVBoxLayout(browser)
        browser_layout.setContentsMargins(0, 8, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.recipe_category_tree = QTreeWidget()
        self.recipe_category_tree.setHeaderLabels(["游戏手册产物分类"])
        self.recipe_category_tree.setMinimumWidth(260)
        self.recipe_category_tree.setMaximumWidth(390)
        self.recipe_category_tree.setUniformRowHeights(True)
        self.recipe_category_tree.itemSelectionChanged.connect(
            self._populate_recipe_results
        )
        self.recipe_category_tree.itemExpanded.connect(
            self._on_recipe_category_expansion_changed
        )
        self.recipe_category_tree.itemCollapsed.connect(
            self._on_recipe_category_expansion_changed
        )
        splitter.addWidget(self.recipe_category_tree)

        self.recipe_result_tree = QTreeWidget()
        self._configure_recipe_detail_tree(
            self.recipe_result_tree,
            "产物 / 配方 / 所需物品",
            "recipe_result_column_widths",
        )
        self.recipe_result_tree.itemChanged.connect(self._on_recipe_item_changed)
        splitter.addWidget(self.recipe_result_tree)
        splitter.setSizes([280, 1000])
        browser_layout.addWidget(splitter, 1)
        self.recipe_tabs.addTab(browser, "按产物浏览")

        tracked_page = QWidget()
        tracked_layout = QVBoxLayout(tracked_page)
        tracked_layout.setContentsMargins(0, 8, 0, 0)
        color_group = QGroupBox("查价浮窗中的关注配方区域")
        color_layout = QHBoxLayout(color_group)
        self.recipe_color_swatch = QLabel()
        self.recipe_color_swatch.setFixedSize(52, 24)
        self.recipe_color_label = QLabel()
        color_button = QPushButton("选择提示颜色")
        color_button.clicked.connect(self._choose_recipe_overlay_color)
        reset_color_button = QPushButton("恢复默认")
        reset_color_button.clicked.connect(self._reset_recipe_overlay_color)
        color_layout.addWidget(QLabel("独立底色与标题强调色"))
        color_layout.addWidget(self.recipe_color_swatch)
        color_layout.addWidget(self.recipe_color_label)
        color_layout.addStretch(1)
        color_layout.addWidget(color_button)
        color_layout.addWidget(reset_color_button)
        tracked_layout.addWidget(color_group)

        self.tracked_recipe_tree = QTreeWidget()
        self._configure_recipe_detail_tree(
            self.tracked_recipe_tree,
            "已关注产物 / 配方 / 所需物品",
            "tracked_recipe_column_widths",
        )
        self.tracked_recipe_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tracked_recipe_tree.itemChanged.connect(self._on_recipe_item_changed)
        tracked_layout.addWidget(self.tracked_recipe_tree, 1)
        tracked_actions = QHBoxLayout()
        delete_selected_button = QPushButton("删除选中的关注配方")
        delete_selected_button.clicked.connect(self._delete_selected_tracked_recipes)
        clear_button = QPushButton("清除全部关注")
        clear_button.clicked.connect(self._clear_tracked_recipes)
        tracked_actions.addStretch(1)
        tracked_actions.addWidget(delete_selected_button)
        tracked_actions.addWidget(clear_button)
        tracked_layout.addLayout(tracked_actions)
        self.recipe_tabs.addTab(tracked_page, "已关注总览")

        layout.addWidget(self.recipe_tabs, 1)
        self._update_recipe_color_preview()
        self._sync_recipe_tree_fonts()
        self._populate_recipe_tree()
        return panel

    def _sync_recipe_tree_fonts(self) -> None:
        application = QApplication.instance()
        if application is None:
            return
        font = QFont(application.font())
        for attribute in (
            "recipe_category_tree",
            "recipe_result_tree",
            "tracked_recipe_tree",
        ):
            tree = getattr(self, attribute, None)
            if not isinstance(tree, QTreeWidget):
                continue
            tree.setFont(font)
            tree.header().setFont(font)
            tree.scheduleDelayedItemsLayout()

    def _configure_recipe_detail_tree(
        self,
        tree: QTreeWidget,
        first_header: str,
        width_config_key: str,
    ) -> None:
        tree.setHeaderLabels(
            [first_header, "工具", "数量", "耗时 / 限购", "任务依赖"]
        )
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.header().setStretchLastSection(False)
        tree.header().setMinimumSectionSize(42)
        for column in range(tree.columnCount()):
            tree.header().setSectionResizeMode(
                column, QHeaderView.ResizeMode.Interactive
            )
        defaults = [430, 58, 80, 115, 260]
        configured = self.config.get(width_config_key, defaults)
        widths = configured if isinstance(configured, list) else defaults
        for column, default_width in enumerate(defaults):
            try:
                width = int(widths[column])
            except (IndexError, TypeError, ValueError):
                width = default_width
            tree.setColumnWidth(column, max(42, min(1600, width)))
        tree.headerItem().setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
        tree.headerItem().setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
        tree.headerItem().setTextAlignment(3, Qt.AlignmentFlag.AlignCenter)
        tree.header().sectionResized.connect(
            lambda _column, _old, _new, current_tree=tree, key=width_config_key: (
                self._remember_recipe_column_widths(current_tree, key)
            )
        )

    def _remember_recipe_column_widths(
        self, tree: QTreeWidget, config_key: str
    ) -> None:
        widths = [tree.columnWidth(column) for column in range(tree.columnCount())]
        if self.settings_store.set(config_key, widths):
            self._config_save_timer.start(350)

    def _on_recipe_category_expansion_changed(
        self, item: QTreeWidgetItem
    ) -> None:
        if self._recipe_tree_loading:
            return
        category_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if not category_id or category_id == "__all__":
            return
        expanded = {
            str(value)
            for value in self.config.get("recipe_expanded_categories", [])
            if str(value)
        }
        if item.isExpanded():
            expanded.add(category_id)
        else:
            expanded.discard(category_id)
        self.settings_store.set("recipe_expanded_categories", sorted(expanded))
        self.settings_store.set("recipe_category_expansion_initialized", True)
        self._config_save_timer.start(350)

    def _tracked_recipe_ids(self) -> set[str]:
        value = self.config.get("tracked_recipe_ids", [])
        if not isinstance(value, list):
            return set()
        return {str(item) for item in value if str(item)}

    def _populate_recipe_tree(self, _search_text: str = "") -> None:
        if not hasattr(self, "recipe_category_tree"):
            return
        self._populate_recipe_category_tree()
        self._populate_recipe_results()
        self._populate_tracked_recipe_overview()

    def _populate_recipe_category_tree(self) -> None:
        if not hasattr(self, "recipe_category_tree"):
            return
        self._recipe_tree_loading = True
        self.recipe_category_tree.blockSignals(True)
        try:
            self.recipe_category_tree.clear()
            if self.recipe_catalog is None or not self.recipe_catalog.available:
                message = self._recipe_data_error or "本版本没有可用的本地配方数据。"
                self.recipe_category_tree.addTopLevelItem(QTreeWidgetItem([message]))
                self.recipe_summary_label.setText(message)
                return

            mode = self.current_price_game_mode
            records = self.recipe_catalog.records(mode)
            category_products: dict[str, set[str]] = {}
            for record in records:
                product = record.get("product")
                product_id = (
                    str(product.get("id") or record.get("id") or "")
                    if isinstance(product, dict)
                    else str(record.get("id") or "")
                )
                path = self.recipe_catalog.category_path(record)
                if not path:
                    category_products.setdefault("__uncategorized__", set()).add(
                        product_id
                    )
                for category in path:
                    category_id = category["id"]
                    category_products.setdefault(category_id, set()).add(product_id)
            counts = {
                category_id: len(product_ids)
                for category_id, product_ids in category_products.items()
            }
            all_product_count = len(
                {
                    str((record.get("product") or {}).get("id") or record.get("id") or "")
                    for record in records
                    if isinstance(record.get("product"), dict)
                }
            )

            all_item = QTreeWidgetItem(
                [f"全部产物 ({all_product_count}) · 配方 {len(records)}"]
            )
            all_item.setData(0, Qt.ItemDataRole.UserRole, "__all__")
            self.recipe_category_tree.addTopLevelItem(all_item)
            item_by_id: dict[str, QTreeWidgetItem] = {}

            def add_category(category_id: str) -> QTreeWidgetItem:
                existing = item_by_id.get(category_id)
                if existing is not None:
                    return existing
                definition = self.recipe_catalog.handbook_categories.get(category_id, {})
                item = QTreeWidgetItem(
                    [f"{definition.get('name') or category_id} ({counts[category_id]})"]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, category_id)
                item_by_id[category_id] = item
                parent_id = str(definition.get("parent") or "")
                if parent_id and parent_id in counts:
                    add_category(parent_id).addChild(item)
                else:
                    self.recipe_category_tree.addTopLevelItem(item)
                return item

            def category_sort_key(category_id: str) -> tuple[object, ...]:
                path: list[tuple[str, str]] = []
                current = category_id
                seen: set[str] = set()
                while current and current not in seen:
                    seen.add(current)
                    definition = self.recipe_catalog.handbook_categories.get(current, {})
                    path.append(
                        (
                            str(definition.get("normalized_name") or ""),
                            str(definition.get("name") or current).casefold(),
                        )
                    )
                    current = str(definition.get("parent") or "")
                path.reverse()
                root_normalized = path[0][0] if path else ""
                return (
                    HANDBOOK_ROOT_ORDER.get(root_normalized, 999),
                    tuple(name for _normalized, name in path),
                )

            for category_id in sorted(counts, key=category_sort_key):
                if category_id != "__uncategorized__":
                    add_category(category_id)
            if counts.get("__uncategorized__"):
                uncategorized = QTreeWidgetItem(
                    [f"未分类 ({counts['__uncategorized__']})"]
                )
                uncategorized.setData(
                    0, Qt.ItemDataRole.UserRole, "__uncategorized__"
                )
                self.recipe_category_tree.addTopLevelItem(uncategorized)
            if bool(
                self.config.get("recipe_category_expansion_initialized", False)
            ):
                expanded = {
                    str(value)
                    for value in self.config.get("recipe_expanded_categories", [])
                    if str(value)
                }
                for category_id, item in item_by_id.items():
                    item.setExpanded(category_id in expanded)
            else:
                self.recipe_category_tree.expandToDepth(0)
            self.recipe_category_tree.setCurrentItem(all_item)
        finally:
            self.recipe_category_tree.blockSignals(False)
            self._recipe_tree_loading = False

    def _populate_recipe_results(self, _search_text: str = "") -> None:
        if self._recipe_tree_loading or not hasattr(self, "recipe_result_tree"):
            return
        self._recipe_tree_loading = True
        self.recipe_result_tree.blockSignals(True)
        try:
            self.recipe_result_tree.clear()
            if self.recipe_catalog is None or not self.recipe_catalog.available:
                return
            mode = self.current_price_game_mode
            records = self.recipe_catalog.records(mode)
            query = self.recipe_search_field.text().strip().casefold()
            selected = self.recipe_category_tree.currentItem()
            category_id = (
                str(selected.data(0, Qt.ItemDataRole.UserRole) or "__all__")
                if selected is not None
                else "__all__"
            )
            if category_id != "__all__":
                if category_id == "__uncategorized__":
                    records = [
                        record
                        for record in records
                        if not self.recipe_catalog.category_path(record)
                    ]
                else:
                    records = [
                        record
                        for record in records
                        if category_id
                        in {
                            category["id"]
                            for category in self.recipe_catalog.category_path(record)
                        }
                    ]
            if query:
                records = [
                    record for record in records if query in recipe_search_text(record)
                ]

            tracked = self._tracked_recipe_ids()
            products: dict[str, list[dict[str, object]]] = {}
            for record in records:
                product = record.get("product")
                product_id = (
                    str(product.get("id") or record.get("id") or "")
                    if isinstance(product, dict)
                    else str(record.get("id") or "")
                )
                products.setdefault(product_id, []).append(record)

            for product_records in sorted(
                products.values(),
                key=lambda values: _recipe_product_name(values[0]).casefold(),
            ):
                product_item = QTreeWidgetItem(
                    [
                        f"{_recipe_product_name(product_records[0])}"
                        f"（{len(product_records)}）",
                        "",
                        "",
                        "",
                        "",
                    ]
                )
                product_font = QFont(self.recipe_result_tree.font())
                product_font.setBold(True)
                product_item.setFont(0, product_font)
                product_item.setToolTip(0, f"{len(product_records)} 个具体配方")
                self.recipe_result_tree.addTopLevelItem(product_item)
                for record in product_records:
                    recipe_id = str(record.get("id") or "")
                    recipe_item = self._build_recipe_tree_item(
                        record,
                        checked=recipe_id in tracked,
                    )
                    product_item.addChild(recipe_item)
                    if query:
                        recipe_item.setExpanded(True)
                if query:
                    product_item.setExpanded(True)

            total = self.recipe_catalog.record_count(mode)
            mode_ids = {
                str(record.get("id") or "")
                for record in self.recipe_catalog.records(mode)
            }
            self.recipe_summary_label.setText(
                f"{_game_mode_label(mode)}：共 {total} 个配方 · 当前显示 "
                f"{len(products)} 种产物 / {len(records)} 个配方 · "
                f"本模式已关注 {len(tracked & mode_ids)} 个 · 全部模式 {len(tracked)} 个"
            )
        finally:
            self.recipe_result_tree.blockSignals(False)
            self._recipe_tree_loading = False

    def _build_recipe_tree_item(
        self,
        record: dict[str, object],
        *,
        checked: bool,
        mode_text: str = "",
    ) -> QTreeWidgetItem:
        source_text = recipe_source_text(record)
        if mode_text:
            source_text = f"{source_text}（{mode_text}）"
        acquisition_text = recipe_acquisition_text(record)
        note_text = recipe_unlock_note(
            record,
            str(self.config.get("item_display_language", "zh")),
        )
        recipe_item = QTreeWidgetItem(
            [
                source_text,
                "",
                _recipe_product_count_text(record),
                acquisition_text,
                note_text,
            ]
        )
        recipe_item.setFlags(recipe_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        recipe_item.setForeground(2, QBrush(QColor("#E8C47A")))
        recipe_item.setTextAlignment(
            2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        recipe_item.setForeground(3, QBrush(QColor("#C9D0DA")))
        recipe_item.setTextAlignment(
            3, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        if note_text:
            recipe_item.setToolTip(4, note_text)
        recipe_id = str(record.get("id") or "")
        recipe_item.setData(0, Qt.ItemDataRole.UserRole, recipe_id)
        recipe_item.setCheckState(
            0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )
        for requirement in recipe_requirement_rows(record):
            tool_text = "✓" if requirement.is_tool else ""
            requirement_item = QTreeWidgetItem(
                [requirement.display_name, tool_text, requirement.count_text, "", ""]
            )
            requirement_item.setData(0, Qt.ItemDataRole.UserRole, recipe_id)
            requirement_item.setForeground(0, QBrush(QColor("#AAB3BE")))
            requirement_item.setForeground(1, QBrush(QColor("#82D9A0")))
            requirement_item.setForeground(2, QBrush(QColor("#8FC7FF")))
            requirement_item.setTextAlignment(
                1, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            requirement_item.setTextAlignment(
                2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            recipe_item.addChild(requirement_item)
        return recipe_item

    def _populate_tracked_recipe_overview(self) -> None:
        if not hasattr(self, "tracked_recipe_tree"):
            return
        self._recipe_tree_loading = True
        self.tracked_recipe_tree.blockSignals(True)
        try:
            self.tracked_recipe_tree.clear()
            if self.recipe_catalog is None:
                return
            tracked = self._tracked_recipe_ids()
            entries = self.recipe_catalog.tracked_records(tracked)
            products: dict[str, list[tuple[dict[str, object], tuple[str, ...]]]] = {}
            for record, modes in entries:
                product = record.get("product")
                product_id = (
                    str(product.get("id") or record.get("id") or "")
                    if isinstance(product, dict)
                    else str(record.get("id") or "")
                )
                products.setdefault(product_id, []).append((record, modes))
            for product_entries in sorted(
                products.values(),
                key=lambda values: _recipe_product_name(values[0][0]).casefold(),
            ):
                product_item = QTreeWidgetItem(
                    [
                        f"{_recipe_product_name(product_entries[0][0])}"
                        f"（{len(product_entries)}）",
                        "",
                        "",
                        "",
                        "",
                    ]
                )
                product_font = QFont(self.tracked_recipe_tree.font())
                product_font.setBold(True)
                product_item.setFont(0, product_font)
                product_item.setToolTip(
                    0, f"{len(product_entries)} 个已关注配方"
                )
                self.tracked_recipe_tree.addTopLevelItem(product_item)
                for record, modes in product_entries:
                    mode_text = "/".join(_game_mode_label(mode) for mode in modes)
                    recipe_item = self._build_recipe_tree_item(
                        record,
                        checked=True,
                        mode_text=mode_text,
                    )
                    product_item.addChild(recipe_item)
            if entries:
                self.tracked_recipe_tree.expandToDepth(1)
            else:
                self.tracked_recipe_tree.addTopLevelItem(
                    QTreeWidgetItem(["还没有关注任何配方。", "", "", "", ""])
                )
            self.recipe_tabs.setTabText(1, f"已关注总览 ({len(entries)})")
        finally:
            self.tracked_recipe_tree.blockSignals(False)
            self._recipe_tree_loading = False

    def _on_recipe_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._recipe_tree_loading or column != 0:
            return
        recipe_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if not recipe_id:
            return
        tracked = self._tracked_recipe_ids()
        if item.checkState(0) == Qt.CheckState.Checked:
            tracked.add(recipe_id)
        else:
            tracked.discard(recipe_id)
        self.settings_store.set("tracked_recipe_ids", sorted(tracked))
        self._config_save_timer.start(250)
        self._update_recipe_summary_only()
        QTimer.singleShot(0, self._refresh_recipe_views)

    def _refresh_recipe_views(self) -> None:
        self._sync_recipe_result_checks()
        self._populate_tracked_recipe_overview()

    def _sync_recipe_result_checks(self) -> None:
        """Update recipe checkboxes without rebuilding the browsed result tree."""
        if not hasattr(self, "recipe_result_tree"):
            return
        tracked = self._tracked_recipe_ids()
        self.recipe_result_tree.blockSignals(True)
        try:
            for product_index in range(self.recipe_result_tree.topLevelItemCount()):
                product_item = self.recipe_result_tree.topLevelItem(product_index)
                for recipe_index in range(product_item.childCount()):
                    recipe_item = product_item.child(recipe_index)
                    recipe_id = str(
                        recipe_item.data(0, Qt.ItemDataRole.UserRole) or ""
                    )
                    if not recipe_id:
                        continue
                    recipe_item.setCheckState(
                        0,
                        Qt.CheckState.Checked
                        if recipe_id in tracked
                        else Qt.CheckState.Unchecked,
                    )
        finally:
            self.recipe_result_tree.blockSignals(False)

    def _update_recipe_summary_only(self) -> None:
        if not hasattr(self, "recipe_summary_label") or self.recipe_catalog is None:
            return
        total = self.recipe_catalog.record_count(self.current_price_game_mode)
        mode_ids = {
            str(record.get("id") or "")
            for record in self.recipe_catalog.records(self.current_price_game_mode)
        }
        tracked = self._tracked_recipe_ids()
        self.recipe_summary_label.setText(
            f"{_game_mode_label(self.current_price_game_mode)}：共 {total} 个配方 · "
            f"本模式已关注 {len(tracked & mode_ids)} 个 · 全部模式 {len(tracked)} 个"
        )

    def _delete_selected_tracked_recipes(self) -> None:
        selected_ids: set[str] = set()

        def collect_recipe_ids(item: QTreeWidgetItem) -> None:
            recipe_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            if recipe_id:
                selected_ids.add(recipe_id)
            for child_index in range(item.childCount()):
                collect_recipe_ids(item.child(child_index))

        for item in self.tracked_recipe_tree.selectedItems():
            collect_recipe_ids(item)
        if not selected_ids:
            return
        tracked = self._tracked_recipe_ids() - selected_ids
        self.settings_store.set("tracked_recipe_ids", sorted(tracked))
        self._config_save_timer.start(250)
        self._sync_recipe_result_checks()
        self._populate_tracked_recipe_overview()
        self._update_recipe_summary_only()
        self._log_event(f"已删除 {len(selected_ids)} 个关注配方。")

    def _clear_tracked_recipes(self) -> None:
        if not self._tracked_recipe_ids():
            return
        answer = QMessageBox.question(
            self,
            "清除全部关注配方",
            "确定清除所有已关注的制作和兑换配方吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.settings_store.set("tracked_recipe_ids", [])
        self._config_save_timer.start(250)
        self._sync_recipe_result_checks()
        self._populate_tracked_recipe_overview()
        self._update_recipe_summary_only()
        self._log_event("已清除全部关注配方。")

    def _recipe_overlay_color(self) -> str:
        color = QColor(
            str(self.config.get("recipe_overlay_accent_color", "#E8C47A"))
        )
        return color.name().upper() if color.isValid() else "#E8C47A"

    def _choose_recipe_overlay_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._recipe_overlay_color()),
            self,
            "选择关注配方提示颜色",
        )
        if not color.isValid():
            return
        self.settings_store.set("recipe_overlay_accent_color", color.name().upper())
        self._config_save_timer.start(250)
        self._update_recipe_color_preview()

    def _reset_recipe_overlay_color(self) -> None:
        self.settings_store.set("recipe_overlay_accent_color", "#E8C47A")
        self._config_save_timer.start(250)
        self._update_recipe_color_preview()

    def _update_recipe_color_preview(self) -> None:
        if not hasattr(self, "recipe_color_swatch"):
            return
        color = self._recipe_overlay_color()
        tint = QColor(color)
        self.recipe_color_swatch.setStyleSheet(
            f"background:rgba({tint.red()},{tint.green()},{tint.blue()},90); "
            "border:1px solid rgba(255,255,255,70); "
            "border-radius:4px;"
        )
        self.recipe_color_label.setText(color)

    def _build_display_filter_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        group = QGroupBox("画面增强（Gamma / 亮度）")
        group_layout = QVBoxLayout(group)
        self.display_filter_status_label = QLabel("画面增强当前已关闭")
        self.display_filter_status_label.setWordWrap(True)
        group_layout.addWidget(self.display_filter_status_label)

        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        controls = QWidget()
        controls_layout = QFormLayout(controls)
        self.display_filter_preset_combo = QComboBox()
        for index, preset in enumerate(self._display_filter_presets()):
            self.display_filter_preset_combo.addItem(str(preset.get("name", f"Preset {index + 1}")), index)
        active = str(self.config.get("display_filter_active_preset", ""))
        if active:
            for index, preset in enumerate(self._display_filter_presets()):
                if str(preset.get("name", "")) == active:
                    self.display_filter_preset_combo.setCurrentIndex(index)
                    break
        self.display_filter_preset_combo.currentIndexChanged.connect(
            self._on_display_filter_preset_changed
        )
        self.display_filter_target_combo = QComboBox()
        self._populate_display_target_combo(self.display_filter_target_combo)
        self.display_filter_target_combo.currentIndexChanged.connect(
            self._on_display_filter_target_changed
        )

        self.display_filter_sliders: dict[str, QSlider] = {}
        self.display_filter_value_labels: dict[str, QLabel] = {}
        self.display_filter_summary_label = QLabel("")
        self.display_filter_summary_label.setWordWrap(True)
        controls_layout.addRow("目标显示器", self.display_filter_target_combo)
        controls_layout.addRow("配色方案", self.display_filter_preset_combo)
        for key, (label, minimum, maximum, _scale, _decimals) in DISPLAY_FILTER_SLIDERS.items():
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(minimum, maximum)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            slider.setTickInterval(max(1, (maximum - minimum) // 5))
            value_label = QLabel("")
            value_label.setMinimumWidth(56)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(value_label)
            self.display_filter_sliders[key] = slider
            self.display_filter_value_labels[key] = value_label
            slider.valueChanged.connect(self._on_display_filter_slider_changed)
            controls_layout.addRow(label, row)
        controls_layout.addRow("参数", self.display_filter_summary_label)

        self.display_filter_curve = GammaCurvePreview()
        top_layout.addWidget(controls, 1)
        top_layout.addWidget(self.display_filter_curve)
        group_layout.addWidget(top)

        self.display_filter_live_preview = QCheckBox("开启后，拖动滑条立即更新画面")
        self.display_filter_live_preview.setChecked(False)
        group_layout.addWidget(self.display_filter_live_preview)
        target_note = QLabel(
            "每次只修改所选 Windows 显示输出。名称中会同时显示物理显示器和显示适配器；"
            "HDR、夜间模式、独占全屏或显卡驱动仍可能拦截 Gamma。"
        )
        target_note.setWordWrap(True)
        group_layout.addWidget(target_note)

        self.display_filter_preset_name = QLineEdit()
        self.display_filter_preset_name.setPlaceholderText("输入名称后保存为自定义方案")
        self.display_filter_preset_hotkey = HotkeyLineEdit("当前 Gamma 方案")
        self.display_filter_preset_hotkey.set_conflict_checker(
            self._check_display_filter_preset_hotkey
        )
        self.display_filter_preset_hotkey.setPlaceholderText("点击后按一次快捷键；留空则不绑定")
        name_row = QWidget()
        name_layout = QHBoxLayout(name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        new_button = QPushButton("新建方案")
        new_button.clicked.connect(self.create_display_filter_preset)
        save_button = QPushButton("保存/覆盖方案")
        save_button.clicked.connect(self.save_current_display_filter_preset)
        delete_button = QPushButton("删除方案")
        delete_button.clicked.connect(self.delete_selected_display_filter_preset)
        name_layout.addWidget(self.display_filter_preset_name, 1)
        name_layout.addWidget(new_button)
        name_layout.addWidget(save_button)
        name_layout.addWidget(delete_button)
        group_layout.addWidget(name_row)
        hotkey_row = QWidget()
        hotkey_layout = QFormLayout(hotkey_row)
        hotkey_layout.setContentsMargins(0, 0, 0, 0)
        hotkey_layout.addRow("当前方案热键", self.display_filter_preset_hotkey)
        group_layout.addWidget(hotkey_row)

        apply_button = QPushButton("开启当前方案")
        apply_button.clicked.connect(self.apply_selected_display_filter)
        next_button = QPushButton("切换到下一个预设")
        next_button.clicked.connect(lambda checked=False: self.cycle_display_filter_preset(notify=False))
        restore_button = QPushButton("关闭并恢复原始画面")
        restore_button.clicked.connect(lambda checked=False: self.restore_display_filter(show_feedback=False))
        floating_button = QPushButton("打开高级独立调节窗")
        floating_button.clicked.connect(self.open_display_filter_control_window)
        probe_button = QPushButton("检测所选显示器")
        probe_button.clicked.connect(self.probe_selected_display_filter_target)
        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.addWidget(apply_button)
        buttons_layout.addWidget(next_button)
        buttons_layout.addWidget(restore_button)
        buttons_layout.addWidget(probe_button)
        buttons_layout.addWidget(floating_button)
        group_layout.addWidget(buttons)

        layout.addWidget(group)
        layout.addStretch(1)
        self._on_display_filter_preset_changed()
        return panel

    def _build_disabled_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        title = QLabel("当前没有启用任何功能")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        detail = QLabel("可以打开设置，在“功能”页选择要启用的模块；保存后重启软件生效。")
        detail.setWordWrap(True)
        settings_button = QPushButton("打开设置")
        settings_button.clicked.connect(self.open_settings)
        layout.addWidget(title)
        layout.addWidget(detail)
        layout.addWidget(settings_button)
        layout.addStretch(1)
        return panel

    def _display_filter_presets(self) -> list[dict[str, object]]:
        presets = self.config.get("display_filter_presets", [])
        if not isinstance(presets, list):
            return []
        return [preset for preset in presets if isinstance(preset, dict)]

    def _display_filter_target_options(self, *, refresh: bool = False) -> list[tuple[str, str]]:
        if refresh:
            self._display_targets = enumerate_display_targets()
        if not self._display_targets:
            return [("", "Windows 主显示器（自动）")]
        qt_screens = list(QApplication.screens())
        screens = {
            (
                screen.geometry().x(),
                screen.geometry().y(),
                screen.geometry().width(),
                screen.geometry().height(),
            ): screen
            for screen in qt_screens
        }
        options: list[tuple[str, str]] = []
        for target_index, target in enumerate(self._display_targets):
            label = target.label
            screen = screens.get(target.geometry)
            if screen is None and len(qt_screens) == len(self._display_targets):
                screen = qt_screens[target_index]
            if screen is not None and target.monitor_name.casefold() in {
                "",
                "generic pnp monitor",
                "通用即插即用监视器",
            }:
                physical_name = str(screen.name()).strip()
                if physical_name:
                    label = label.replace(target.monitor_name or "通用显示器", physical_name, 1)
            options.append((target.target_id, label))
        return options

    def _populate_display_target_combo(
        self, combo: QComboBox, *, refresh: bool = False
    ) -> None:
        options = self._display_filter_target_options(refresh=refresh)
        selected = preferred_display_target_id(
            self.config.get("display_filter_target_id", ""),
            self._display_targets,
        )
        self.config["display_filter_target_id"] = selected
        with QSignalBlocker(combo):
            combo.clear()
            for target_id, label in options:
                combo.addItem(label, target_id)
            index = combo.findData(selected)
            combo.setCurrentIndex(max(0, index))

    def _selected_display_filter_target_id(self) -> str:
        if hasattr(self, "display_filter_target_combo"):
            selected = str(self.display_filter_target_combo.currentData() or "")
        else:
            selected = str(self.config.get("display_filter_target_id", ""))
        return preferred_display_target_id(selected, self._display_targets)

    def _display_filter_target_label(self, target_id: str) -> str:
        for target in self._display_targets:
            if target.target_id == target_id:
                return target.label
        return target_id or "Windows 主显示器（自动）"

    def _set_display_filter_target(
        self,
        target_id: str,
        *,
        reapply: bool = False,
        preset: dict[str, object] | None = None,
    ) -> None:
        selected = preferred_display_target_id(target_id, self._display_targets)
        changed = str(self.config.get("display_filter_target_id", "")) != selected
        self.config["display_filter_target_id"] = selected
        for combo in (
            getattr(self, "display_filter_target_combo", None),
            getattr(self.raid_control_overlay, "display_target_combo", None),
            getattr(self._display_filter_dialog, "target_combo", None),
        ):
            if not isinstance(combo, QComboBox):
                continue
            with QSignalBlocker(combo):
                index = combo.findData(selected)
                if index >= 0:
                    combo.setCurrentIndex(index)
        if changed:
            self._config_save_timer.start(350)
            self._log_event(
                f"Gamma 目标显示器已切换：{self._display_filter_target_label(selected)}"
            )
        if reapply and self._display_filter_baseline is not None:
            self._apply_display_filter_preset(
                preset or self._display_filter_preset_from_controls(),
                notify=False,
            )

    def _on_display_filter_target_changed(self) -> None:
        target_id = str(self.display_filter_target_combo.currentData() or "")
        self._set_display_filter_target(
            target_id,
            reapply=self._display_filter_baseline is not None,
            preset=self._display_filter_preset_from_controls(),
        )

    def probe_selected_display_filter_target(self) -> None:
        target_id = self._selected_display_filter_target_id()
        label = self._display_filter_target_label(target_id)
        try:
            probe_display_target(target_id)
        except DisplayFilterError as exc:
            self.display_filter_status_label.setText(f"显示器检测失败：{exc}")
            self._log_event(f"Gamma 显示器检测失败：{label} · {exc}")
            self._show_operation_feedback(
                "显示器检测失败",
                label,
                str(exc),
                accent_color="#FF5A5F",
            )
            return
        message = "Windows Gamma Ramp 接口可读写；检测过程写回原值，不改变画面。"
        self.display_filter_status_label.setText(f"显示器检测通过：{label}")
        self._log_event(f"Gamma 显示器检测通过：{label}")
        self._show_operation_feedback(
            "显示器检测通过",
            label,
            message,
            accent_color="#36D27F",
        )

    def _selected_display_filter_preset(self) -> dict[str, object] | None:
        presets = self._display_filter_presets()
        if not presets:
            return None
        index = 0
        if hasattr(self, "display_filter_preset_combo"):
            index = max(0, self.display_filter_preset_combo.currentIndex())
        else:
            active = str(self.config.get("display_filter_active_preset", ""))
            for preset_index, preset in enumerate(presets):
                if str(preset.get("name", "")) == active:
                    index = preset_index
                    break
        return presets[index % len(presets)]

    def _display_filter_preset_from_controls(self) -> dict[str, object]:
        preset = self._selected_display_filter_preset() or {}
        result: dict[str, object] = {
            "name": str(preset.get("name", "Custom")),
            "description": str(preset.get("description", "自定义 Gamma 曲线")),
            "hotkey": str(preset.get("hotkey", "")),
        }
        if hasattr(self, "display_filter_preset_hotkey"):
            result["hotkey"] = self.display_filter_preset_hotkey.text().strip()
        for key, (_label, _minimum, _maximum, scale, decimals) in DISPLAY_FILTER_SLIDERS.items():
            slider = self.display_filter_sliders.get(key)
            if slider is None:
                result[key] = round(float(preset.get(key, 1.0)), decimals)
            else:
                result[key] = round(slider.value() / scale, decimals)
        return result

    def _load_display_filter_controls(self, preset: dict[str, object]) -> None:
        self._display_filter_controls_loading = True
        try:
            for key, (_label, minimum, maximum, scale, _decimals) in DISPLAY_FILTER_SLIDERS.items():
                slider = self.display_filter_sliders.get(key)
                if slider is None:
                    continue
                value = int(round(_preset_float(preset, key, slider.value() / scale) * scale))
                slider.setValue(min(max(value, minimum), maximum))
            if hasattr(self, "display_filter_preset_name"):
                self.display_filter_preset_name.setText(str(preset.get("name", "")))
            if hasattr(self, "display_filter_preset_hotkey"):
                self.display_filter_preset_hotkey.setText(str(preset.get("hotkey", "")))
        finally:
            self._display_filter_controls_loading = False
        self._update_display_filter_summary()

    def _on_display_filter_preset_changed(self) -> None:
        preset = self._selected_display_filter_preset()
        if preset is not None and hasattr(self, "display_filter_sliders"):
            self._load_display_filter_controls(preset)
            return
        self._update_display_filter_summary()

    def _on_display_filter_slider_changed(self) -> None:
        if self._display_filter_controls_loading:
            return
        self._update_display_filter_summary()
        if (
            self._feature_enabled("display_filter")
            and hasattr(self, "display_filter_live_preview")
            and self.display_filter_live_preview.isChecked()
        ):
            self._apply_display_filter_preset(self._display_filter_preset_from_controls())

    def _update_display_filter_summary(self) -> None:
        if not hasattr(self, "display_filter_summary_label"):
            return
        if hasattr(self, "display_filter_sliders"):
            preset = self._display_filter_preset_from_controls()
        else:
            preset = self._selected_display_filter_preset()
        if preset is None:
            self.display_filter_summary_label.setText("没有可用预设")
            return
        for key, value_label in getattr(self, "display_filter_value_labels", {}).items():
            value_label.setText(_format_display_filter_value(key, _preset_float(preset, key, 1.0)))
        if hasattr(self, "display_filter_curve"):
            self.display_filter_curve.set_preset(preset)
        summary = (
            f"{preset.get('description', '')}\n"
            f"gamma={preset.get('gamma', 1.0)}，"
            f"black_lift={preset.get('black_lift', 0.0)}，"
            f"gain={preset.get('gain', 1.0)}，"
            f"contrast={preset.get('contrast', 1.0)}，"
            f"hotkey={preset.get('hotkey', '') or '未绑定'}"
        )
        self.display_filter_summary_label.setText(summary)

    def apply_selected_display_filter(self) -> None:
        if not self._feature_enabled("display_filter"):
            self._log("Gamma 显示调校模块未启用，已跳过应用预设。")
            return
        preset = self._selected_display_filter_preset()
        if preset is None:
            self._show_operation_feedback("Gamma 调校失败", "没有预设", "请先在配置中添加显示预设。", accent_color="#FF5A5F")
            return
        self._apply_display_filter_preset(self._display_filter_preset_from_controls())

    def apply_current_display_filter_values(self) -> None:
        if not self._feature_enabled("display_filter"):
            self._log("Gamma 显示调校模块未启用，已跳过应用当前参数。")
            return
        self._apply_display_filter_preset(self._display_filter_preset_from_controls())

    def _check_display_filter_preset_hotkey(
        self, _field: HotkeyLineEdit, hotkey: str
    ) -> bool:
        try:
            normalize_hotkey(hotkey)
        except ValueError as exc:
            QMessageBox.warning(self, "热键无效", str(exc))
            return False
        return True

    def _resolve_display_filter_preset_hotkey_conflicts(
        self, preset_name: str, hotkey: str
    ) -> bool:
        text = hotkey.strip()
        if not text:
            return True
        try:
            normalized = normalize_hotkey(text)
        except ValueError as exc:
            QMessageBox.warning(self, "热键无效", str(exc))
            return False

        conflict = self._find_hotkey_conflict(
            normalized, exclude_preset_name=preset_name
        )
        if conflict is None:
            return True

        kind, label, target = conflict
        answer = QMessageBox.question(
            self,
            "快捷键冲突",
            f"{hotkey} 已被“{label}”使用。是否替代？选择“是”会清空原绑定。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

        if kind == "config":
            self.config[str(target)] = ""
        elif kind == "preset":
            target["hotkey"] = ""  # type: ignore[index]
        return True

    def _find_hotkey_conflict(
        self, normalized: str, *, exclude_preset_name: str = ""
    ) -> tuple[str, str, object] | None:
        for config_key, label in HOTKEY_CONFIG_LABELS:
            text = str(self.config.get(config_key, "")).strip()
            if not text:
                continue
            try:
                if normalize_hotkey(text) == normalized:
                    return ("config", label, config_key)
            except ValueError:
                continue

        for preset in self._display_filter_presets():
            name = str(preset.get("name", "")).strip()
            if name and name == exclude_preset_name:
                continue
            text = str(preset.get("hotkey", "")).strip()
            if not text:
                continue
            try:
                if normalize_hotkey(text) == normalized:
                    return ("preset", f"Gamma 方案：{name}", preset)
            except ValueError:
                continue
        return None

    def create_display_filter_preset(self) -> None:
        if not self._feature_enabled("display_filter"):
            self._log("Gamma 显示调校模块未启用，已跳过新建方案。")
            return
        default_name = self._unique_display_filter_preset_name("自定义方案")
        name, ok = QInputDialog.getText(
            self,
            "新建 Gamma 方案",
            "方案名称：",
            text=default_name,
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if self._display_filter_preset_name_exists(name):
            QMessageBox.warning(
                self,
                "方案名称已存在",
                "这个 Gamma 方案名称已经存在。请换一个名称，或使用“保存/覆盖方案”。",
            )
            return
        preset = self._display_filter_preset_from_controls()
        preset["name"] = name
        preset["description"] = "自定义 Gamma 曲线"
        preset["hotkey"] = ""
        self._upsert_display_filter_preset(preset)
        self._log_event(f"Gamma 方案已新建：{name}")

    def save_current_display_filter_preset(self) -> None:
        if not self._feature_enabled("display_filter"):
            self._log("Gamma 显示调校模块未启用，已跳过保存方案。")
            return
        name = self.display_filter_preset_name.text().strip()
        if not name:
            name, ok = QInputDialog.getText(self, "保存 Gamma 方案", "方案名称：")
            if not ok:
                return
            name = name.strip()
        if not name:
            return
        preset = self._display_filter_preset_from_controls()
        hotkey = str(preset.get("hotkey", "")).strip()
        if not self._resolve_display_filter_preset_hotkey_conflicts(name, hotkey):
            return
        hotkey = ""
        if hotkey:
            try:
                normalize_hotkey(hotkey)
            except ValueError as exc:
                self._show_operation_feedback(
                    "Gamma 方案未保存",
                    "热键无效",
                    str(exc),
                    accent_color="#FF5A5F",
                )
                return
        preset["name"] = name
        preset["description"] = "自定义 Gamma 曲线"
        self._upsert_display_filter_preset(preset)
        self._log_event(f"Gamma 方案已保存：{name}")

    def _display_filter_preset_name_exists(self, name: str) -> bool:
        normalized = name.strip()
        return any(
            str(preset.get("name", "")).strip() == normalized
            for preset in self._display_filter_presets()
        )

    def _unique_display_filter_preset_name(self, base: str) -> str:
        existing = {
            str(preset.get("name", "")).strip()
            for preset in self._display_filter_presets()
        }
        if base not in existing:
            return base
        index = 2
        while f"{base} {index}" in existing:
            index += 1
        return f"{base} {index}"

    def delete_selected_display_filter_preset(self) -> None:
        preset = self._selected_display_filter_preset()
        if preset is None:
            return
        name = str(preset.get("name", ""))
        presets = [item for item in self._display_filter_presets() if str(item.get("name", "")) != name]
        self.config["display_filter_presets"] = presets
        self._reload_display_filter_presets(select_name="")
        save_config(self.config)
        self._register_hotkeys()
        self._log_event(f"Gamma 方案已删除：{name}")

    def _upsert_display_filter_preset(self, preset: dict[str, object]) -> None:
        name = str(preset.get("name", "")).strip()
        presets = []
        replaced = False
        for item in self._display_filter_presets():
            if str(item.get("name", "")) == name:
                presets.append(preset)
                replaced = True
            else:
                presets.append(item)
        if not replaced:
            presets.append(preset)
        self.config["display_filter_presets"] = presets
        self.config["display_filter_active_preset"] = name
        save_config(self.config)
        self._reload_display_filter_presets(select_name=name)
        if self._display_filter_dialog is not None:
            self._display_filter_dialog.reload_presets(select_name=name)
        self._register_hotkeys()

    def _reload_display_filter_presets(self, *, select_name: str = "") -> None:
        if not hasattr(self, "display_filter_preset_combo"):
            return
        self.display_filter_preset_combo.blockSignals(True)
        self.display_filter_preset_combo.clear()
        for index, preset in enumerate(self._display_filter_presets()):
            self.display_filter_preset_combo.addItem(str(preset.get("name", f"Preset {index + 1}")), index)
        selected = 0
        if select_name:
            for index, preset in enumerate(self._display_filter_presets()):
                if str(preset.get("name", "")) == select_name:
                    selected = index
                    break
        if self.display_filter_preset_combo.count() > 0:
            self.display_filter_preset_combo.setCurrentIndex(selected)
        self.display_filter_preset_combo.blockSignals(False)
        self._on_display_filter_preset_changed()

    def open_display_filter_control_window(self) -> None:
        if not self._feature_enabled("display_filter"):
            self._log("Gamma 显示调校模块未启用，已跳过打开调节浮窗。")
            return
        if self._display_filter_dialog is None:
            self._display_filter_dialog = DisplayFilterControlDialog(self)
        self._populate_display_target_combo(
            self._display_filter_dialog.target_combo,
            refresh=True,
        )
        self._display_filter_dialog.reload_presets(
            select_name=str(self.config.get("display_filter_active_preset", ""))
        )
        self._display_filter_dialog.show()
        self._display_filter_dialog.raise_()
        self._display_filter_dialog.activateWindow()

    def cycle_display_filter_preset(self, *, notify: bool = True) -> None:
        if not self._feature_enabled("display_filter"):
            self._log("Gamma 显示调校模块未启用，已跳过预设切换。")
            return
        presets = self._display_filter_presets()
        if not presets:
            self._show_operation_feedback("Gamma 调校失败", "没有预设", "请先在配置中添加显示预设。", accent_color="#FF5A5F")
            return
        if hasattr(self, "display_filter_preset_combo"):
            next_index = (self.display_filter_preset_combo.currentIndex() + 1) % len(presets)
            self.display_filter_preset_combo.setCurrentIndex(next_index)
            preset = presets[next_index]
        else:
            self._display_filter_index = (self._display_filter_index + 1) % len(presets)
            preset = presets[self._display_filter_index]
        self._apply_display_filter_preset(preset, notify=notify)

    def apply_display_filter_preset_by_name(self, name: str) -> None:
        if not self._feature_enabled("display_filter"):
            return
        for index, preset in enumerate(self._display_filter_presets()):
            if str(preset.get("name", "")) == name:
                if hasattr(self, "display_filter_preset_combo"):
                    self.display_filter_preset_combo.setCurrentIndex(index)
                self._apply_display_filter_preset(preset, notify=True)
                return
        self._log(f"Gamma 预设热键指向了不存在的方案：{name}")

    def _apply_display_filter_preset(self, preset: dict[str, object], *, notify: bool = False) -> None:
        if not self._feature_enabled("display_filter"):
            self._log("Gamma 显示调校模块未启用，已跳过写入系统 Gamma。")
            return
        name = str(preset.get("name", "Unnamed"))
        target_id = self._selected_display_filter_target_id()
        try:
            if (
                self._display_filter_baseline is not None
                and self._display_filter_baseline.target_id != target_id
            ):
                restore_system_display_filter(self._display_filter_baseline)
                self._display_filter_baseline = None
            if self._display_filter_baseline is None:
                self._display_filter_baseline = start_display_filter(preset, target_id)
            else:
                update_display_filter(preset, self._display_filter_baseline)
        except DisplayFilterError as exc:
            still_active = self._display_filter_baseline is not None
            self.raid_control_overlay.set_gamma_active(still_active)
            message = (
                f"参数更新失败：{exc}。请点击关闭以恢复原始画面。"
                if still_active
                else str(exc)
            )
            self.raid_control_overlay.set_gamma_status(message, error=True)
            if hasattr(self, "display_filter_status_label"):
                self.display_filter_status_label.setText(f"画面增强失败：{message}")
            if notify:
                self._log_event(f"画面增强失败：{message}")
                self._show_operation_feedback(
                    "画面增强失败", name, message, accent_color="#FF5A5F"
                )
            return
        self.config["display_filter_active_preset"] = name
        self.raid_control_overlay.set_gamma_active(True)
        backend_label = self._display_filter_baseline.label
        self.raid_control_overlay.set_gamma_status(
            f"画面增强已开启 · {backend_label}"
        )
        if hasattr(self, "display_filter_status_label"):
            self.display_filter_status_label.setText(f"已应用：{name} · {backend_label}")
        self._start_display_filter_eye_care_timer()
        if notify:
            self._log_event(f"已应用 Gamma 调校：{name}")
            self._show_operation_feedback(
                "已应用 Gamma 调校",
                name,
                str(preset.get("description", "")),
                accent_color="#5DA8FF",
            )

    def restore_display_filter(self, *, show_feedback: bool = True) -> None:
        if self._display_filter_baseline is None:
            self.raid_control_overlay.set_gamma_active(False)
            self.raid_control_overlay.set_gamma_status("画面增强当前处于关闭状态。")
            if show_feedback:
                self._show_operation_feedback(
                    "Gamma 未修改",
                    "无需恢复",
                    "本次会话还没有应用显示调校。",
                    accent_color="#F2C14E",
                )
            return
        try:
            restore_system_display_filter(self._display_filter_baseline)
        except DisplayFilterError as exc:
            self.raid_control_overlay.set_gamma_status(str(exc), error=True)
            if show_feedback:
                self._show_operation_feedback("Gamma 恢复失败", "系统原始 Gamma", str(exc), accent_color="#FF5A5F")
                self._log_event(f"Gamma 恢复失败：{exc}")
            return
        self._display_filter_baseline = None
        self.raid_control_overlay.set_gamma_active(False)
        self.raid_control_overlay.set_gamma_status("画面增强已关闭，显示已恢复。")
        self._stop_display_filter_eye_care_timer()
        self.config["display_filter_active_preset"] = ""
        if hasattr(self, "display_filter_status_label"):
            self.display_filter_status_label.setText("已恢复系统原始 Gamma")
        if show_feedback:
            self._log_event("已恢复系统原始 Gamma。")
            self._show_operation_feedback(
                "已恢复 Gamma",
                "系统原始设置",
                "显示调校已关闭。",
                accent_color="#36D27F",
            )

    def _display_filter_eye_care_enabled(self) -> bool:
        return self._feature_enabled("display_filter") and bool(
            self.config.get("display_filter_eye_care_enabled", True)
        )

    def _start_display_filter_eye_care_timer(self) -> None:
        if not self._display_filter_eye_care_enabled() or self._display_filter_baseline is None:
            self._stop_display_filter_eye_care_timer()
            return
        try:
            seconds = float(self.config.get("display_filter_eye_care_check_seconds", 2))
        except (TypeError, ValueError):
            seconds = 2.0
        self._display_filter_eye_timer.start(max(1, int(seconds * 1000)))

    def _stop_display_filter_eye_care_timer(self) -> None:
        if self._display_filter_eye_timer.isActive():
            self._display_filter_eye_timer.stop()

    def _on_display_filter_eye_care_check(self) -> None:
        if (
            self._closing
            or self._display_filter_baseline is None
            or not self._display_filter_eye_care_enabled()
        ):
            self._stop_display_filter_eye_care_timer()
            return
        if QApplication.applicationState() == Qt.ApplicationState.ApplicationActive:
            return
        is_foreground, _title = is_tarkov_foreground()
        if is_foreground:
            return
        self.restore_display_filter(show_feedback=False)
        message = "护眼模式：检测到 Tarkov 不活跃，已恢复系统 Gamma。可按已绑定的 Gamma 方案热键重新应用。"
        self._log_event(message)
        self._show_operation_feedback(
            "护眼模式已关闭 Gamma",
            "Tarkov 不活跃",
            "按已绑定的 Gamma 方案热键，或在 Gamma 面板重新应用。",
            accent_color="#F2C14E",
        )

    def _build_menu(self) -> None:
        settings_action = QAction("打开设置", self)
        settings_action.triggered.connect(self.open_settings)
        refresh_action = QAction("刷新价格缓存", self)
        refresh_action.triggered.connect(lambda: self.refresh_price_cache(background=True))
        reload_aliases_action = QAction("重新加载中文别名", self)
        reload_aliases_action.triggered.connect(self.reload_chinese_aliases)
        open_aliases_action = QAction("打开中文别名文件", self)
        open_aliases_action.triggered.connect(self.open_chinese_aliases)
        raid_control_action = QAction("打开/关闭局内控制", self)
        raid_control_action.triggered.connect(self.toggle_raid_control_overlay)
        raid_log_action = QAction("打开/关闭局内日志", self)
        raid_log_action.triggered.connect(self.toggle_raid_log_overlay)
        diagnostics_action = QAction("导出诊断包", self)
        diagnostics_action.triggered.connect(self.export_diagnostics)
        update_action = QAction("检查软件更新", self)
        update_action.triggered.connect(self.check_for_app_updates)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.request_exit)

        settings_menu = self.menuBar().addMenu("设置")
        settings_menu.addAction(settings_action)

        raid_menu = self.menuBar().addMenu("局内")
        raid_menu.addAction(raid_control_action)
        raid_menu.addAction(raid_log_action)

        if self._feature_enabled("price_lookup"):
            data_menu = self.menuBar().addMenu("数据")
            data_menu.addAction(refresh_action)
            data_menu.addAction(reload_aliases_action)
            data_menu.addAction(open_aliases_action)

        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(diagnostics_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction(update_action)

    def _build_status_bar(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.detected_size_label = QLabel("截图: -")
        self.cache_status_label = QLabel("价格: -")
        layout.addWidget(self.detected_size_label, 1)
        layout.addWidget(self.cache_status_label, 1)
        return widget

    def _build_item_lookup_group(self) -> QGroupBox:
        group = QGroupBox("物品价格")
        layout = QGridLayout(group)

        self.item_name_field = QLineEdit()
        self.item_name_field.setPlaceholderText("OCR 结果或手动输入物品名")
        self.item_name_field.returnPressed.connect(self.lookup_manual_item_name)
        completer = QCompleter(self.item_completion_model, self)
        completer.setCompletionColumn(0)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completion_popup = QTreeView(self.item_name_field)
        completion_popup.setRootIsDecorated(False)
        completion_popup.setUniformRowHeights(True)
        completion_popup.setHeaderHidden(True)
        completion_popup.setAlternatingRowColors(True)
        completion_popup.setMinimumWidth(680)
        self._configure_item_completion_popup(completion_popup)
        completer.setPopup(completion_popup)
        completer.activated[QModelIndex].connect(self._on_item_completion_index_activated)
        self.item_name_field.setCompleter(completer)
        self.price_mode_combo = QComboBox()
        for label, mode in GAME_MODE_CHOICES:
            self.price_mode_combo.addItem(label, mode)
        mode_index = self.price_mode_combo.findData(self.current_price_game_mode)
        self.price_mode_combo.setCurrentIndex(max(0, mode_index))
        self.price_mode_combo.currentIndexChanged.connect(self._on_price_mode_changed)
        price_mode_widget = QWidget()
        price_mode_layout = QHBoxLayout(price_mode_widget)
        price_mode_layout.setContentsMargins(0, 0, 0, 0)
        price_mode_layout.addWidget(QLabel("价格模式"))
        price_mode_layout.addWidget(self.price_mode_combo)
        self.item_price_label = QLabel("价格: -")
        self.item_price_label.setWordWrap(True)
        self.item_price_label.setTextFormat(Qt.TextFormat.RichText)

        self.item_capture_button = QPushButton("识别物品并查价")
        self.item_capture_button.clicked.connect(self.capture_item_price_after_delay)
        self.lookup_button = QPushButton("查询手动名称")
        self.lookup_button.clicked.connect(self.lookup_manual_item_name)
        self.open_item_crop_button = QPushButton("打开物品截图")
        self.open_item_crop_button.clicked.connect(self.open_item_crop)

        layout.addWidget(QLabel("物品名"), 0, 0)
        layout.addWidget(self.item_name_field, 0, 1, 1, 3)
        layout.addWidget(price_mode_widget, 0, 4)
        layout.addWidget(self.item_price_label, 1, 0, 1, 5)
        layout.addWidget(self.item_capture_button, 2, 0)
        layout.addWidget(self.lookup_button, 2, 1)
        layout.addWidget(self.open_item_crop_button, 2, 2)
        return group

    def _build_trader_group(self) -> QGroupBox:
        group = QGroupBox("商人补货")
        layout = QVBoxLayout(group)
        note = QLabel(
            "勾选要关注的商人后识别；有效倒计时会直接建立提醒并每秒更新，无需手动输入。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(self._build_trader_table())

        buttons = QHBoxLayout()
        self.capture_button = QPushButton("识别倒计时")
        self.capture_button.clicked.connect(self.capture_and_ocr)
        self.toggle_countdown_button = QPushButton("显示/隐藏倒计时悬浮窗")
        self.toggle_countdown_button.clicked.connect(self.toggle_reminder_hold)
        self.clear_button = QPushButton("清空提醒")
        self.clear_button.clicked.connect(self.clear_reminders)
        self.open_crop_button = QPushButton("打开倒计时截图")
        self.open_crop_button.clicked.connect(self.open_debug_crop)

        buttons.addWidget(self.capture_button)
        buttons.addWidget(self.toggle_countdown_button)
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.open_crop_button)
        layout.addLayout(buttons)
        return group

    def _build_trader_table(self) -> QTableWidget:
        table = QTableWidget(len(TRADERS), 5)
        self.table = table
        table.setHorizontalHeaderLabels(
            ["商人", "提醒", "实时倒计时", "补货时间", "状态"]
        )
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        selected = set(self.config.get("selected_traders", TRADERS))
        for row, trader in enumerate(TRADERS):
            name_item = QTableWidgetItem(trader)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, name_item)

            watch = QCheckBox()
            watch.setChecked(trader in selected)
            self.watch_checks[trader] = watch
            table.setCellWidget(row, 1, _centered(watch))

            countdown_item = QTableWidgetItem("-")
            countdown_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            countdown_item.setFlags(countdown_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.countdown_items[trader] = countdown_item
            table.setItem(row, 2, countdown_item)

            restock_item = QTableWidgetItem("")
            restock_item.setFlags(restock_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.restock_items[trader] = restock_item
            table.setItem(row, 3, restock_item)

            status_item = QTableWidgetItem("未启用")
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.status_items[trader] = status_item
            table.setItem(row, 4, status_item)

        return table

    def _build_log_panel(self) -> QTextEdit:
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        self._apply_log_limit()
        return self.log

    def _apply_performance_settings(self) -> None:
        self._apply_log_limit()
        ocr_threads = configure_rapid_ocr_threads(
            self.config.get("performance_ocr_threads", 2)
        )
        self.config["performance_ocr_threads"] = ocr_threads
        if bool(self.config.get("performance_mode_enabled", True)):
            try:
                seconds = int(self.config.get("performance_cleanup_interval_seconds", 60))
            except (TypeError, ValueError):
                seconds = 60
            self._resource_cleanup_timer.start(max(15, seconds) * 1000)
        elif self._resource_cleanup_timer.isActive():
            self._resource_cleanup_timer.stop()

    def _apply_log_limit(self) -> None:
        if not hasattr(self, "log"):
            return
        try:
            limit = int(self.config.get("performance_log_max_lines", 600))
        except (TypeError, ValueError):
            limit = 600
        self.log.document().setMaximumBlockCount(max(100, limit))

    def _raid_status_text(self) -> str:
        if self.price_client is None:
            return "价格模块未启用 · 其他局内设置仍可使用"
        stale_hours = _safe_int(self.config.get("price_cache_stale_hours")) or 24
        return (
            f"{_game_mode_label(self.current_price_game_mode)} · "
            f"{self.price_client.cache_status(stale_hours)}"
        )

    def _sync_raid_control_overlay(self) -> None:
        presets = self._display_filter_presets() if self._feature_enabled("display_filter") else []
        self.raid_control_overlay.sync(
            self.config,
            presets,
            self._raid_status_text(),
            gamma_active=self._display_filter_baseline is not None,
            display_targets=self._display_filter_target_options(refresh=True),
        )

    def toggle_raid_control_overlay(self) -> None:
        if self._closing:
            return
        self._sync_raid_control_overlay()
        visible = self.raid_control_overlay.toggle()
        state = "打开" if visible else "关闭"
        self._log_event(f"局内控制窗已{state}。")

    def toggle_raid_log_overlay(self) -> None:
        if self._closing:
            return
        visible = self.raid_log_overlay.toggle()
        state = "打开" if visible else "关闭"
        self._log_event(f"局内日志窗已{state}。")

    def _set_live_setting(self, key: str, value: object) -> None:
        if not self.settings_store.set(key, value):
            return
        self._config_save_timer.start(350)

    def _on_raid_game_mode_changed(self, mode: str) -> None:
        if mode not in GAME_MODES:
            return
        changed = self.settings_store.set("price_game_mode_default", mode)
        if self.price_client is not None:
            self.current_price_game_mode = self.price_client.set_game_mode(mode)
        else:
            self.current_price_game_mode = mode
        if hasattr(self, "price_mode_combo"):
            with QSignalBlocker(self.price_mode_combo):
                index = self.price_mode_combo.findData(self.current_price_game_mode)
                self.price_mode_combo.setCurrentIndex(max(0, index))
        self._update_cache_status_label()
        self._refresh_item_completer()
        if hasattr(self, "recipe_category_tree"):
            self._populate_recipe_tree()
        self.raid_control_overlay.status_label.setText(self._raid_status_text())
        if changed:
            self._config_save_timer.start(350)
            self._log_event(
                f"局内价格模式已切换为 {_game_mode_label(self.current_price_game_mode)}。"
            )

    def _on_raid_gamma_values_changed(self, values: object) -> None:
        if not isinstance(values, dict):
            return
        self._apply_display_filter_preset(values, notify=False)
        self._config_save_timer.start(350)

    def _on_raid_display_target_changed(self, target_id: str) -> None:
        self._set_display_filter_target(
            target_id,
            reapply=self._display_filter_baseline is not None,
            preset=self.raid_control_overlay.gamma_values(),
        )

    def _on_raid_gamma_enabled_changed(self, enabled: bool) -> None:
        if enabled:
            self._apply_display_filter_preset(
                self.raid_control_overlay.gamma_values(),
                notify=True,
            )
            return
        self.restore_display_filter(show_feedback=False)
        self._log_event("画面增强已关闭，显示已恢复。")

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        previous_features = self._configured_enabled_features()
        previous_font_size = _safe_int(self.config.get("ui_font_size")) or 11
        previous_theme = str(self.config.get("ui_theme", "light"))
        previous_language = str(self.config.get("item_display_language", "zh"))
        self.config.update(dialog.values())
        features_changed = previous_features != self._configured_enabled_features()
        font_size = _safe_int(self.config.get("ui_font_size")) or 11
        current_theme = str(self.config.get("ui_theme", "light"))
        if font_size != previous_font_size or current_theme != previous_theme:
            apply_app_theme(QApplication.instance(), font_size, current_theme)
            self._sync_recipe_tree_fonts()
        if features_changed:
            self._apply_runtime_feature_configuration(previous_features)
        if hasattr(self, "price_mode_combo"):
            mode_index = self.price_mode_combo.findData(
                str(self.config.get("price_game_mode_default", "pve"))
            )
            self.price_mode_combo.setCurrentIndex(max(0, mode_index))
        self._save_config()
        if self.reminder_overlay is not None:
            self.reminder_overlay.set_toggle_hotkey(
                str(self.config.get("reminder_hold_hotkey", "F7"))
            )
        self._register_hotkeys()
        self._start_display_filter_eye_care_timer()
        self._apply_performance_settings()
        self.raid_log_overlay.set_max_lines(int(self.config.get("raid_log_max_lines", 200)))
        self.raid_log_overlay.set_opacity_percent(int(self.config.get("raid_log_opacity", 72)))
        self._sync_raid_control_overlay()
        self._log("设置已更新。")
        if features_changed:
            self._log_event("功能开关已应用，主界面和模块热键已同步更新。")
        self._update_cache_status_label()
        self._refresh_item_completer()
        if (
            font_size != previous_font_size
            or previous_language
            != str(self.config.get("item_display_language", "zh"))
        ) and hasattr(self, "recipe_category_tree"):
            self._populate_recipe_tree()
        if self._should_auto_refresh_price_cache():
            self.refresh_price_cache(background=True)

    def _apply_runtime_feature_configuration(
        self, previous_features: set[str]
    ) -> None:
        new_features = self._configured_enabled_features()
        if new_features == previous_features:
            return

        if (
            "display_filter" in previous_features
            and "display_filter" not in new_features
            and self._display_filter_baseline is not None
        ):
            self.restore_display_filter(show_feedback=False)

        if "trader_reminders" not in new_features:
            if self.reminders is not None:
                self.reminders.shutdown()
            self.reminders = None
            if self.reminder_overlay is not None:
                self.reminder_overlay.hide()
            self.reminder_overlay = None
        elif self.reminders is None:
            self.reminders = ReminderManager()
            self.reminders.reminder_triggered.connect(self._on_reminder_triggered)
            self.reminders.reminders_updated.connect(self._on_reminders_updated)
            self.reminder_overlay = ReminderOverlay(
                str(self.config.get("reminder_hold_hotkey", "F7"))
            )

        if "price_lookup" not in new_features:
            if self.price_overlay is not None:
                self.price_overlay.hide()
            self.price_overlay = None
            self.price_client = None
        elif self.price_client is None:
            self.price_client = TarkovPriceClient()
            self.current_price_game_mode = self.price_client.set_game_mode(
                str(self.config.get("price_game_mode_default", "pve"))
            )
            self.price_overlay = PriceOverlay()

        if "hideout" not in new_features:
            self.hideout_tracker = None
        elif self.hideout_tracker is None:
            self.hideout_tracker = HideoutTracker()

        self._recipe_data_error = ""
        if "recipe_tracking" not in new_features:
            self.recipe_catalog = None
        elif self.recipe_catalog is None:
            try:
                self.recipe_catalog = RecipeCatalog()
            except RecipeDataError as exc:
                self._recipe_data_error = str(exc)

        feedback_features = {"trader_reminders", "hideout", "display_filter"}
        if new_features.intersection(feedback_features):
            if self.feedback_overlay is None:
                self.feedback_overlay = FeedbackOverlay()
        elif self.feedback_overlay is not None:
            self.feedback_overlay.hide()
            self.feedback_overlay = None

        previous_log = self.log.toPlainText() if hasattr(self, "log") else ""
        self._runtime_enabled_features = new_features
        self._clear_feature_ui_references()
        self._build_ui()
        if previous_log and hasattr(self, "log"):
            self.log.setPlainText(previous_log)

        if self.tray_icon is not None:
            self.tray_icon.hide()
            self.tray_icon.deleteLater()
            self.tray_icon = None
        self._build_tray_icon()

    def _clear_feature_ui_references(self) -> None:
        names = (
            "detected_size_label",
            "cache_status_label",
            "item_name_field",
            "item_price_label",
            "item_capture_button",
            "lookup_button",
            "open_item_crop_button",
            "price_mode_combo",
            "table",
            "capture_button",
            "toggle_countdown_button",
            "clear_button",
            "open_crop_button",
            "data_status_label",
            "data_error_label",
            "hideout_status_label",
            "hideout_table",
            "display_filter_status_label",
            "display_filter_target_combo",
            "recipe_search_field",
            "recipe_summary_label",
            "recipe_tabs",
            "recipe_category_tree",
            "recipe_result_tree",
            "recipe_color_swatch",
            "recipe_color_label",
            "tracked_recipe_tree",
        )
        for name in names:
            if hasattr(self, name):
                delattr(self, name)

    def reload_chinese_aliases(self) -> None:
        if self.price_client is None:
            self._log("查价模块未启用，已跳过中文别名重载。")
            return
        count = self.price_client.reload_aliases()
        self._update_cache_status_label()
        self._refresh_item_completer()
        self._log(f"中文别名已重新加载：{count} 条。")

    def open_chinese_aliases(self) -> None:
        if not self._feature_enabled("price_lookup"):
            self._log("查价模块未启用，已跳过打开中文别名文件。")
            return
        aliases_path = ensure_editable_aliases_path()
        os.startfile(aliases_path)  # type: ignore[attr-defined]

    def export_diagnostics(self) -> None:
        default_name = f"EFT-Raid-Assistant-diagnostics-{datetime.now():%Y%m%d-%H%M%S}.zip"
        destination, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出诊断包",
            str(APP_DIR / default_name),
            "ZIP 压缩包 (*.zip)",
        )
        if not destination:
            return
        path = Path(destination)
        if path.suffix.casefold() != ".zip":
            path = path.with_suffix(".zip")
        try:
            created = create_diagnostic_bundle(path, self.config)
        except (OSError, ValueError) as exc:
            self._last_data_error = f"诊断包导出失败：{exc}"
            self._update_data_status_summary()
            QMessageBox.warning(self, "诊断包导出失败", str(exc))
            return
        self._last_data_error = ""
        self._update_data_status_summary()
        self._log(f"诊断包已导出：{created}")
        QMessageBox.information(
            self,
            "诊断包已导出",
            f"文件已保存到：\n{created}",
        )

    def _save_config(self) -> None:
        if self.watch_checks:
            self.config["selected_traders"] = [
                trader for trader, check in self.watch_checks.items() if check.isChecked()
            ]
        if hasattr(self, "price_mode_combo"):
            self.config["price_game_mode_default"] = self._selected_price_game_mode()
        save_config(self.config)

    def _selected_price_game_mode(self) -> str:
        if not hasattr(self, "price_mode_combo"):
            return str(self.config.get("price_game_mode_default", "pve"))
        return str(self.price_mode_combo.currentData() or "pve")

    def _on_price_mode_changed(self) -> None:
        if self.price_client is None:
            return
        mode = self._selected_price_game_mode()
        self.current_price_game_mode = self.price_client.set_game_mode(mode)
        self.settings_store.set("price_game_mode_default", self.current_price_game_mode)
        save_config(self.config)
        self._update_cache_status_label()
        self._refresh_item_completer()
        if hasattr(self, "recipe_category_tree"):
            self._populate_recipe_tree()
        self._sync_raid_control_overlay()
        self._log(f"Price mode set manually: {_game_mode_label(self.current_price_game_mode)}.")

    def _should_auto_refresh_price_cache(self) -> bool:
        if not self._feature_enabled("price_lookup") or self.price_client is None:
            return False
        if not bool(self.config.get("refresh_prices_on_startup", True)):
            return False
        if bool(self.config.get("performance_mode_enabled", True)) and bool(
            self.config.get("performance_skip_auto_price_refresh", True)
        ):
            stale_hours = _safe_int(self.config.get("price_cache_stale_hours")) or 24
            if not self.price_client.cache_is_stale(stale_hours):
                self._log("性能模式：价格缓存仍新鲜，已跳过启动刷新。")
                return False
            self._log("价格缓存已过期，将执行低流量 ETag 检查并按需刷新。")
        return True

    def _register_hotkeys(self) -> None:
        trader_enabled = self._feature_enabled("trader_reminders")
        price_enabled = self._feature_enabled("price_lookup")
        hideout_enabled = self._feature_enabled("hideout")
        filter_enabled = self._feature_enabled("display_filter")
        preset_hotkeys = self._display_filter_preset_hotkey_bindings() if filter_enabled else []
        overlay_hotkeys = [
            (
                str(self.config.get("raid_panel_hotkey", "F9")),
                lambda: self.raid_panel_toggle_requested.emit(),
            ),
            (
                str(self.config.get("raid_log_hotkey", "F10")),
                lambda: self.raid_log_toggle_requested.emit(),
            ),
        ]
        try:
            self.hotkeys.register(
                capture_hotkey=str(self.config.get("capture_hotkey", "F8"))
                if trader_enabled
                else "",
                schedule_hotkey="",
                on_capture=lambda: self.capture_requested.emit(),
                on_schedule=None,
                item_lookup_hotkey=str(self.config.get("item_lookup_hotkey", "Q"))
                if price_enabled
                else "",
                on_item_lookup=lambda: self.item_lookup_requested.emit(),
                hideout_scan_hotkey=str(self.config.get("hideout_scan_hotkey", "F6"))
                if hideout_enabled
                else "",
                on_hideout_scan=lambda: self.hideout_scan_requested.emit(),
                reminder_hold_hotkey=str(self.config.get("reminder_hold_hotkey", "F7"))
                if trader_enabled
                else "",
                on_reminder_hold=lambda: self.reminder_hold_requested.emit(),
                display_filter_restore_hotkey=str(
                    self.config.get("display_filter_restore_hotkey", "Ctrl+F9")
                )
                if filter_enabled
                else "",
                on_display_filter_restore=lambda: self.display_filter_restore_requested.emit(),
                extra_hotkeys=[*overlay_hotkeys, *preset_hotkeys],
            )
        except Exception as exc:
            self._log(f"热键注册失败：{exc}")
            return
        self._log(
            "热键已注册："
            f"倒计时={self.config.get('capture_hotkey', 'F8') if trader_enabled else '关闭'}，"
            f"物品查价={self.config.get('item_lookup_hotkey', 'Q') if price_enabled else '关闭'}，"
            f"藏身处={self.config.get('hideout_scan_hotkey', 'F6') if hideout_enabled else '关闭'}，"
            f"显示/隐藏补货倒计时={self.config.get('reminder_hold_hotkey', 'F7') if trader_enabled else '关闭'}，"
            f"局内控制={self.config.get('raid_panel_hotkey', 'F9')}，"
            f"局内日志={self.config.get('raid_log_hotkey', 'F10')}，"
            f"Gamma预设={len(preset_hotkeys)} 个"
        )

    def _display_filter_preset_hotkey_bindings(self) -> list[tuple[str, Callable[[], None]]]:
        bindings: list[tuple[str, Callable[[], None]]] = []
        seen_hotkeys: set[str] = set()
        for value in [
            self.config.get("capture_hotkey", "") if self._feature_enabled("trader_reminders") else "",
            self.config.get("item_lookup_hotkey", "") if self._feature_enabled("price_lookup") else "",
            self.config.get("hideout_scan_hotkey", "") if self._feature_enabled("hideout") else "",
            self.config.get("reminder_hold_hotkey", "") if self._feature_enabled("trader_reminders") else "",
            self.config.get("raid_panel_hotkey", ""),
            self.config.get("raid_log_hotkey", ""),
            self.config.get("display_filter_restore_hotkey", ""),
        ]:
            text = str(value).strip()
            if not text:
                continue
            try:
                seen_hotkeys.add(normalize_hotkey(text))
            except ValueError:
                continue
        for preset in self._display_filter_presets():
            name = str(preset.get("name", "")).strip()
            hotkey = str(preset.get("hotkey", "")).strip()
            if not name or not hotkey:
                continue
            try:
                key = normalize_hotkey(hotkey)
            except ValueError as exc:
                self._log(f"Gamma 预设热键无效，已跳过：{name} / {hotkey} / {exc}")
                continue
            if key in seen_hotkeys:
                self._log(f"Gamma 预设热键重复，已跳过：{name} / {hotkey}")
                continue
            seen_hotkeys.add(key)
            bindings.append(
                (hotkey, lambda preset_name=name: self.display_filter_preset_requested.emit(preset_name))
            )
        return bindings

    def refresh_price_cache(self, background: bool = False) -> None:
        if not self._feature_enabled("price_lookup") or self.price_client is None:
            self._log("价格模块未启用，已跳过价格缓存刷新。")
            return
        if background:
            self.cache_status_label.setText("价格: 正在通过 JSON API 刷新...")
            self._start_worker("price-cache-refresh", self._refresh_price_cache_worker, "json")
            return
        self._refresh_price_cache_worker("json")

    def _refresh_price_cache_worker(self, source: str = "json") -> None:
        if self._closing or self.price_client is None:
            return
        try:
            counts = self.price_client.refresh_all_modes(source=source)
        except PriceLookupError as exc:
            result = PriceCacheRefreshResult(source=source, error=str(exc))
        except Exception as exc:
            result = PriceCacheRefreshResult(source=source, error=f"价格缓存刷新异常：{exc}")
        else:
            result = PriceCacheRefreshResult(source=source, counts=counts)
        if not self._closing:
            self.cache_refresh_ready.emit(result)

    def _on_cache_refresh_ready(self, result: PriceCacheRefreshResult) -> None:
        if self._closing or not self._feature_enabled("price_lookup"):
            return
        source_label = "JSON API" if result.source == "json" else "GraphQL"
        if result.error:
            status = f"{source_label} 价格缓存刷新失败：{result.error}"
            self._last_data_error = status
            self._log(status)
            self._update_cache_status_label()
            if result.source == "json":
                answer = QMessageBox.question(
                    self,
                    "JSON 价格 API 不可用",
                    f"{result.error}\n\n现有本地缓存已经保留。是否尝试备用 GraphQL API？\n"
                    "注意：GraphQL 目前只能刷新 PvP/PvE，赛季服会保留现有缓存。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    self.cache_status_label.setText("价格: 正在尝试 GraphQL...")
                    QTimer.singleShot(0, self._start_graphql_price_cache_fallback)
                else:
                    self._log("用户取消了 GraphQL 备用刷新，继续使用现有本地缓存。")
            else:
                QMessageBox.warning(
                    self,
                    "GraphQL 价格 API 也不可用",
                    f"{result.error}\n\n程序将继续使用现有本地缓存。",
                )
            return

        counts = result.counts or {}
        if result.source == "graphql":
            seasonal_count = (
                self.price_client.cached_item_count("pvp-season")
                if self.price_client is not None
                else 0
            )
            status = (
                f"价格缓存已通过 {source_label} 就绪："
                f"PvP {counts.get('regular', 0)} 个物品，"
                f"PvE {counts.get('pve', 0)} 个物品；"
                f"赛季服保留 {seasonal_count} 个物品"
            )
        else:
            status = (
                f"价格缓存已通过 {source_label} 就绪："
                f"PvP {counts.get('regular', 0)} 个物品，"
                f"PvE {counts.get('pve', 0)} 个物品，"
                f"赛季服 {counts.get('pvp-season', 0)} 个物品"
            )
        self._log(status)
        self._last_data_error = ""
        self._update_cache_status_label()
        self._refresh_item_completer()

    def _start_graphql_price_cache_fallback(self) -> None:
        if self._closing or self.price_client is None:
            return
        self._start_worker(
            "price-cache-graphql-fallback",
            self._refresh_price_cache_worker,
            "graphql",
        )

    def refresh_hideout_cache(self, background: bool = False) -> None:
        if not self._feature_enabled("hideout") or self.hideout_tracker is None:
            self._log("藏身处模块未启用，已跳过需求数据刷新。")
            return
        if background:
            self.hideout_status_label.setText("藏身处: 正在刷新需求数据...")
            self._start_worker("hideout-cache-refresh", self._refresh_hideout_cache_worker)
            return
        self._refresh_hideout_cache_worker()

    def _refresh_hideout_cache_worker(self) -> None:
        if self._closing or self.hideout_tracker is None:
            return
        try:
            count = self.hideout_tracker.refresh_requirements()
        except HideoutDataError as exc:
            status = f"藏身处需求数据刷新失败：{exc}"
        except Exception as exc:
            status = f"藏身处需求数据刷新异常：{exc}"
        else:
            status = f"藏身处需求数据已刷新：{count} 个设施。"
        if not self._closing:
            self.hideout_cache_ready.emit(status)

    def _on_hideout_cache_ready(self, status: str) -> None:
        if self._closing or not self._feature_enabled("hideout"):
            return
        self.hideout_status_label.setText(status)
        if "失败" in status or "异常" in status:
            self._last_data_error = status
        else:
            self._last_data_error = ""
        self._log(status)
        self._update_data_status_summary()

    def capture_hideout_progress(self) -> None:
        if self._closing or not self._feature_enabled("hideout") or self.hideout_tracker is None:
            self._log("藏身处模块未启用，已跳过识别。")
            return
        self._save_config()
        if not self._ensure_tarkov_foreground("hideout scan"):
            self._show_operation_feedback(
                "藏身处识别未开始",
                "未截图",
                "当前前台窗口不是 Tarkov。",
                accent_color="#F2C14E",
            )
            return
        capture_mode = str(self.config.get("capture_mode", "Auto"))
        try:
            _, size, region_name = capture_hideout_screen(capture_mode)
        except Exception as exc:
            self._log(f"Hideout screenshot failed: {exc}")
            self._show_operation_feedback(
                "藏身处截图失败",
                "未记录",
                str(exc),
                accent_color="#FF5A5F",
            )
            return

        if hasattr(self, "detected_size_label"):
            self.detected_size_label.setText(f"Capture: {size[0]}x{size[1]} ({region_name})")
        self.hideout_status_label.setText("藏身处: 已截图，正在 OCR...")
        self._log(f"Captured hideout screen: {size[0]}x{size[1]}, source: {region_name}.")
        self._show_operation_feedback(
            "藏身处识别中",
            "正在 OCR...",
            f"截图 {size[0]}x{size[1]} ({region_name})",
            accent_color="#5DA8FF",
            seconds=3,
        )
        self._start_worker("hideout-scan", self._hideout_scan_worker, hideout_debug_path())

    def _hideout_scan_worker(self, screenshot_path: Path) -> None:
        if self._closing or self.hideout_tracker is None:
            return
        try:
            self.hideout_tracker.ensure_requirements()
            scan = run_hideout_ocr(
                screenshot_path,
                self.hideout_tracker.station_names(),
            )
            record = self.hideout_tracker.record_scan(scan)
        except Exception as exc:
            if not self._closing:
                self.hideout_scan_ready.emit(None, str(exc))
            return
        if not self._closing:
            self.hideout_scan_ready.emit(record, "")

    def _on_hideout_scan_ready(self, record: object, error: str) -> None:
        if self._closing or not self._feature_enabled("hideout"):
            return
        if error:
            message = f"藏身处识别失败：{error}"
            self.hideout_status_label.setText(message)
            self._log_event(message)
            self._log(f"Hideout OCR text saved to: {hideout_ocr_text_path()}")
            self._show_operation_feedback(
                "藏身处识别失败",
                "未记录",
                error,
                accent_color="#FF5A5F",
            )
            return
        if not isinstance(record, dict):
            message = "藏身处识别失败：没有可用记录。"
            self.hideout_status_label.setText(message)
            self._log_event(message)
            self._show_operation_feedback(
                "藏身处识别失败",
                "未记录",
                "没有可用记录。",
                accent_color="#FF5A5F",
            )
            return
        self._update_hideout_table()
        station_name = str(record.get("station_name") or "")
        current_level = record.get("current_level")
        target_level = record.get("target_level")
        recognized = record.get("recognized_quantity_count")
        expected = record.get("expected_quantity_count")
        item_summary = _format_hideout_item_summary(record)
        message = (
            f"藏身处已记录：{station_name} L{current_level}->L{target_level}，"
            f"识别 {recognized}/{expected} 项。\n"
            f"本次升级需求：{item_summary}"
        )
        self.hideout_status_label.setText(message)
        self._log_event(message)
        self._show_operation_feedback(
            "藏身处识别已记录",
            f"{station_name} L{current_level}->L{target_level}",
            f"识别 {recognized}/{expected} 项\n本次升级需求：{item_summary}",
            accent_color="#36D27F",
        )

    def _update_hideout_table(self) -> None:
        if not hasattr(self, "hideout_table") or self.hideout_tracker is None:
            return
        records = self.hideout_tracker.records()
        self.hideout_table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = [
                str(record.get("station_name") or ""),
                str(record.get("current_level") or ""),
                str(record.get("target_level") or ""),
                f"{record.get('recognized_quantity_count')}/{record.get('expected_quantity_count')}",
                _format_hideout_item_summary(record),
                str(record.get("updated_at") or ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.hideout_table.setItem(row, column, item)
        self.hideout_table.resizeRowsToContents()

    def open_hideout_screenshot(self) -> None:
        path = hideout_debug_path()
        if path.exists():
            os.startfile(path)  # type: ignore[attr-defined]
            return
        QMessageBox.information(self, "没有藏身处截图", "还没有藏身处截图。")

    def open_hideout_ocr_text(self) -> None:
        path = hideout_ocr_text_path()
        if path.exists():
            os.startfile(path)  # type: ignore[attr-defined]
            return
        QMessageBox.information(self, "没有藏身处 OCR 文本", "还没有藏身处 OCR 文本。")

    def _update_cache_status_label(self) -> None:
        if hasattr(self, "cache_status_label") and self.price_client is not None:
            stale_hours = _safe_int(self.config.get("price_cache_stale_hours")) or 24
            self.cache_status_label.setText(
                f"价格: {self.price_client.cache_status(stale_hours)} / "
                f"中文别名: {self.price_client.alias_status()}"
            )
        self._update_data_status_summary()
        if hasattr(self, "raid_control_overlay"):
            self.raid_control_overlay.status_label.setText(self._raid_status_text())

    def _update_data_status_summary(self) -> None:
        if not hasattr(self, "data_status_label"):
            return
        lines: list[str] = []
        if self.price_client is not None:
            stale_hours = _safe_int(self.config.get("price_cache_stale_hours")) or 24
            lines.append(
                f"价格（{_game_mode_label(self.current_price_game_mode)}）："
                f"{self.price_client.cache_status(stale_hours)}"
            )
            lines.append(f"中文别名：{self.price_client.alias_status()}")
        else:
            lines.append("价格：模块未启用")

        if self.recipe_catalog is not None:
            lines.append(
                "配方："
                f"PvP {self.recipe_catalog.record_count('regular')} 条 / "
                f"PvE {self.recipe_catalog.record_count('pve')} 条 / "
                f"赛季服 {self.recipe_catalog.record_count('pvp-season')} 条"
                + (
                    f" · 生成于 {self.recipe_catalog.generated_at}"
                    if self.recipe_catalog.generated_at
                    else ""
                )
            )
        elif self._recipe_data_error:
            lines.append(f"配方：不可用（{self._recipe_data_error}）")
        else:
            lines.append("配方：模块未启用")

        if self.hideout_tracker is not None:
            lines.append(
                f"藏身处需求：本地已有 {self.hideout_tracker.requirement_count()} 个设施"
            )
        else:
            lines.append("藏身处需求：模块未启用")

        self.data_status_label.setText("\n".join(lines))
        if hasattr(self, "data_error_label"):
            self.data_error_label.setText(
                f"最近一次数据错误：{self._last_data_error}"
                if self._last_data_error
                else "最近一次数据错误：无"
            )

    def capture_and_ocr(self) -> None:
        if self._closing or not self._feature_enabled("trader_reminders") or self.reminders is None:
            self._log("商人补货模块未启用，已跳过倒计时识别。")
            return
        self._save_config()
        if not self._ensure_tarkov_foreground("倒计时识别"):
            self._show_operation_feedback(
                "商人倒计时识别未开始",
                "未截图",
                "当前前台窗口不是 Tarkov。",
                accent_color="#F2C14E",
            )
            return
        manual_size = self._manual_size()

        try:
            _, _, size, region_name = capture_timer_strip(
                str(self.config.get("capture_mode", "Auto")),
                manual_size=manual_size,
                roi_base=tuple(self.config.get("roi_base", [0, 150, 1500, 240])),
            )
        except Exception as exc:
            self._log(f"截图失败：{exc}")
            self._show_operation_feedback(
                "商人倒计时截图失败",
                "未设置提醒",
                str(exc),
                accent_color="#FF5A5F",
            )
            return

        if hasattr(self, "detected_size_label"):
            self.detected_size_label.setText(f"截图: {size[0]}x{size[1]} ({region_name})")
        self._log(f"已截图：{size[0]}x{size[1]}，来源：{region_name}。")
        self._show_operation_feedback(
            "商人倒计时识别中",
            "正在 OCR...",
            f"截图 {size[0]}x{size[1]} ({region_name})",
            accent_color="#5DA8FF",
            seconds=3,
        )

        _, crop_path = debug_paths()
        try:
            result = run_ocr(crop_path)
        except OcrUnavailableError as exc:
            self._log(str(exc))
            self._show_operation_feedback(
                "商人倒计时 OCR 不可用",
                "未设置提醒",
                str(exc),
                accent_color="#FF5A5F",
            )
            return
        except Exception as exc:
            self._log(f"OCR 失败：{exc}")
            self._show_operation_feedback(
                "商人倒计时 OCR 失败",
                "未设置提醒",
                str(exc),
                accent_color="#FF5A5F",
            )
            return

        self._log(f"OCR 预处理：{result.variant_name}")
        self._log("识别到的倒计时：" + (", ".join(result.timers) or "无"))

        for index, trader in enumerate(TRADERS):
            if index < len(result.timers):
                self.countdown_items[trader].setText(result.timers[index])
                self.restock_items[trader].setText("")
                self.status_items[trader].setText(
                    "已识别" if self.watch_checks[trader].isChecked() else "未选择"
                )
            else:
                self.countdown_items[trader].setText("-")
                self.restock_items[trader].setText("")
                self.status_items[trader].setText("OCR 失败")

        if len(result.timers) < len(TRADERS):
            self._log(
                f"注意：只识别到 {len(result.timers)} 个倒计时，商人数量为 {len(TRADERS)}。"
                "未识别到的商人不会设置提醒。"
            )
        scheduled, invalid = self._schedule_selected_reminders()
        self._show_trader_capture_feedback(result.timers, scheduled, invalid)

    def capture_item_price(self) -> None:
        if self._closing or not self._feature_enabled("price_lookup") or self.price_client is None:
            self._log("查价模块未启用，已跳过物品查价。")
            return
        pipeline_started = time.perf_counter()
        timings: list[tuple[str, float]] = []
        if not self._ensure_tarkov_foreground("item lookup"):
            return
        manual_size = self._manual_size()
        capture_mode = str(self.config.get("capture_mode", "Auto"))
        item_mode = str(self.config.get("item_capture_mode", "Hover tooltip"))
        if item_mode == "Hover tooltip":
            wait_ms = int(self.config.get("hover_wait_ms", 0))
            if wait_ms > 0:
                self._log(f"Waiting for hover tooltip: {wait_ms} ms.")
                time.sleep(wait_ms / 1000)

        capture_region: Region | None = None
        calibrated_now = False
        hover_cursor_anchor: tuple[int, int] | None = None
        hover_client_right_edge: int | None = None
        hover_client_top_edge: int | None = None
        hover_search_image = None
        item_image = None
        inventory_image = None
        character_header_image = None
        item_line_count_hint: int | None = None
        stage_started = time.perf_counter()
        try:
            previous_region = self._cached_item_region
            capture_region = resolve_capture_region(capture_mode)
            resolution_changed = _region_size_signature(previous_region) != _region_size_signature(
                capture_region
            )
            calibrated_now = not self._item_region_calibrated or resolution_changed
            self._cached_item_region = capture_region
            self._item_region_calibrated = True
            if resolution_changed:
                self._clear_state_detection_cache()

            if item_mode == "Hover tooltip":
                (
                    _,
                    hover_search_image,
                    size,
                    region_name,
                    hover_cursor_anchor,
                    hover_client_right_edge,
                    hover_client_top_edge,
                ) = capture_hover_item_name_region(
                    capture_mode,
                    offset=tuple(self.config.get("hover_tooltip_offset", [12, -60])),
                    crop_size=tuple(self.config.get("hover_tooltip_size", [360, 110])),
                    search_margins=tuple(
                        self.config.get("hover_search_margins", list(HOVER_SEARCH_MARGINS))
                    ),
                    region=capture_region,
                    save_full_screenshot=False,
                    save_debug_images=False,
                    capture_guard=(
                        getattr(self, "price_overlay", None).capture_guard
                        if getattr(self, "price_overlay", None) is not None
                        and bool(self.config.get("price_overlay_enabled", True))
                        else None
                    ),
                )
                item_image = hover_search_image
            else:
                _, item_image, size, region_name = capture_item_name_region(
                    capture_mode,
                    manual_size=manual_size,
                    roi_base=tuple(self.config.get("item_roi_base", [670, 120, 1420, 260])),
                    region=capture_region,
                    save_debug_images=False,
                )
        except Exception as exc:
            self._cached_item_region = None
            self._item_region_calibrated = False
            timings.append(("ROI截图失败", _elapsed_ms(stage_started)))
            self._log(f"物品截图失败：{exc}")
            self._log_price_lookup_timings(timings, pipeline_started)
            QMessageBox.warning(self, "物品截图失败", str(exc))
            return
        timings.append(("ROI截图", _elapsed_ms(stage_started)))

        if hasattr(self, "detected_size_label"):
            self.detected_size_label.setText(f"Capture: {size[0]}x{size[1]} ({region_name})")
        self._log(f"Captured item region: {size[0]}x{size[1]}, source: {region_name}.")
        if calibrated_now:
            self._log("Capture region calibrated with ROI-only capture; full-screen PNG skipped.")
        else:
            self._log("Using ROI-only capture: tooltip + inventory tab.")

        if bool(self.config.get("require_inventory_check", True)):
            stage_started = time.perf_counter()
            try:
                detected, found, inventory_image = self._detect_inventory_from_capture(
                    capture_mode,
                    manual_size,
                    capture_region,
                )
            except OcrUnavailableError as exc:
                timings.append(("装备页检测失败", _elapsed_ms(stage_started)))
                self._log(str(exc))
                self._log_price_lookup_timings(timings, pipeline_started)
                QMessageBox.warning(self, "OCR 不可用", str(exc))
                return
            except Exception as exc:
                timings.append(("装备页检测失败", _elapsed_ms(stage_started)))
                self._log(f"Inventory tab check failed: {exc}")
                self._log_price_lookup_timings(timings, pipeline_started)
                return
            timings.append(("装备页检测", _elapsed_ms(stage_started)))
            if not detected:
                fallback_started = time.perf_counter()
                try:
                    header_detected, header_found, character_header_image = (
                        self._detect_character_header_from_capture(
                            capture_mode,
                            manual_size,
                            capture_region,
                        )
                    )
                except OcrUnavailableError as exc:
                    timings.append(("角色页回退失败", _elapsed_ms(fallback_started)))
                    self._log(str(exc))
                    self._log_price_lookup_timings(timings, pipeline_started)
                    QMessageBox.warning(self, "OCR 不可用", str(exc))
                    return
                except Exception as exc:
                    timings.append(("角色页回退失败", _elapsed_ms(fallback_started)))
                    self._log(f"Character header fallback failed: {exc}")
                    self._log_price_lookup_timings(timings, pipeline_started)
                    return
                timings.append(("角色页回退", _elapsed_ms(fallback_started)))
                if header_detected:
                    detected = True
                    found = header_found
                    self._log(
                        "Equipment tab is obscured; achievements header detected. "
                        "Continuing with strict tooltip geometry and unique item matching."
                    )
            if not detected:
                save_item_lookup_debug_images(
                    hover_search=hover_search_image,
                    item_name=item_image,
                    inventory_tab=inventory_image,
                    character_header=character_header_image,
                )
                self.item_price_label.setText("Price: inventory tab not detected")
                if self.price_overlay is not None:
                    self.price_overlay.clear_prices()
                self._log_event("已拒绝查价：没有检测到装备/背包页面。")
                self._log(f"Inventory tab not detected. Keywords: {', '.join(found) or 'none'}")
                self._log_price_lookup_timings(timings, pipeline_started)
                return
            self._log(f"Inventory tab detected: {', '.join(found)}")

        if item_mode == "Hover tooltip":
            stage_started = time.perf_counter()
            try:
                tooltip_gap = scale_metric(
                    int(self.config.get("tooltip_cursor_bottom_gap", 20)),
                    size[1],
                    int(self.config.get("tooltip_cursor_reference_height", 2160)),
                    minimum=6,
                )
                tooltip_left_gap = scale_metric(
                    int(self.config.get("tooltip_cursor_left_gap", 18)),
                    size[1],
                    int(self.config.get("tooltip_cursor_reference_height", 2160)),
                    minimum=5,
                )
                tooltip_horizontal_tolerance = scale_metric(
                    int(self.config.get("tooltip_cursor_horizontal_tolerance", 12)),
                    size[1],
                    int(self.config.get("tooltip_cursor_reference_height", 2160)),
                    minimum=4,
                )
                tooltip_tolerance = scale_metric(
                    int(self.config.get("tooltip_cursor_gap_tolerance", 36)),
                    size[1],
                    int(self.config.get("tooltip_cursor_reference_height", 2160)),
                    minimum=14,
                )
                tooltip_max_width = scale_metric(
                    int(self.config.get("tooltip_max_width", 640)),
                    size[1],
                    int(self.config.get("tooltip_cursor_reference_height", 2160)),
                    minimum=120,
                )
                tooltip_edge_tolerance = scale_metric(
                    int(self.config.get("tooltip_client_edge_tolerance", 12)),
                    size[1],
                    int(self.config.get("tooltip_cursor_reference_height", 2160)),
                    minimum=4,
                )
                item_image, refined, words = refine_tooltip_name_image(
                    hover_search_image,
                    tuple(self.config.get("hover_name_padding", [10, 8, 10, 8])),
                    hover_cursor_anchor,
                    tooltip_gap,
                    tooltip_tolerance,
                    tooltip_left_gap,
                    tooltip_horizontal_tolerance,
                    tooltip_max_width,
                    hover_client_right_edge,
                    hover_client_top_edge,
                    tooltip_edge_tolerance,
                )
            except Exception as exc:
                refined = False
                words = []
                self._log(f"Tooltip box location failed; falling back to wider OCR crop: {exc}")
            if refined:
                self._log("Tooltip name box located: " + (" ".join(words) or "no text"))
                item_line_count_hint = tooltip_line_count_hint(
                    item_image.height,
                    size[1],
                    int(self.config.get("tooltip_cursor_reference_height", 2160)),
                )
                self._log(
                    f"Tooltip OCR layout: {item_line_count_hint} line(s), "
                    f"crop {item_image.width}x{item_image.height}."
                )
            else:
                save_item_lookup_debug_images(
                    hover_search=hover_search_image,
                    item_name=item_image,
                    inventory_tab=inventory_image,
                    character_header=character_header_image,
                )
                timings.append(("Tooltip定位", _elapsed_ms(stage_started)))
                self.item_price_label.setText("Price: tooltip not detected")
                self._log_event("未查价：没有定位到鼠标附近的物品提示框。")
                self._log(
                    "Tooltip name box not located; rejected the wider UI crop to avoid "
                    "matching navigation labels as items."
                )
                self._log_price_lookup_timings(timings, pipeline_started)
                return
            timings.append(("Tooltip定位", _elapsed_ms(stage_started)))

        stage_started = time.perf_counter()
        matched_price = None
        matched_result = None
        best_confidence = -1.0
        equally_good_item_ids: set[str] = set()
        saw_candidates = False
        try:
            mode = self.price_client.set_game_mode(self._selected_price_game_mode())
            self.current_price_game_mode = mode
            self.config["price_game_mode_default"] = mode
            for result in iter_item_name_ocr_image_attempts(
                item_image,
                line_count_hint=item_line_count_hint,
            ):
                self._log(f"Item OCR preprocessing: {result.variant_name}")
                self._log(
                    "Item candidate names: "
                    + (", ".join(result.candidates) or "none")
                )
                if not result.candidates:
                    continue
                saw_candidates = True
                try:
                    attempt_price = self.price_client.lookup_candidates(
                        result.candidates,
                        mode,
                    )
                except PriceLookupError:
                    continue
                confidence = float(getattr(attempt_price, "confidence", 0.0) or 0.0)
                item_id = str(getattr(attempt_price, "item_id", "") or "")
                if confidence > best_confidence + 1e-9:
                    best_confidence = confidence
                    matched_price = attempt_price
                    matched_result = result
                    equally_good_item_ids = {item_id}
                elif abs(confidence - best_confidence) <= 1e-9:
                    equally_good_item_ids.add(item_id)
                if confidence >= 0.999:
                    break
        except OcrUnavailableError as exc:
            timings.append(("物品OCR失败", _elapsed_ms(stage_started)))
            save_item_lookup_debug_images(
                hover_search=hover_search_image,
                item_name=item_image,
                inventory_tab=inventory_image,
                character_header=character_header_image,
            )
            self._log(str(exc))
            self._log_price_lookup_timings(timings, pipeline_started)
            QMessageBox.warning(self, "OCR 不可用", str(exc))
            return
        except Exception as exc:
            timings.append(("物品OCR失败", _elapsed_ms(stage_started)))
            save_item_lookup_debug_images(
                hover_search=hover_search_image,
                item_name=item_image,
                inventory_tab=inventory_image,
                character_header=character_header_image,
            )
            self._log(f"物品 OCR 失败：{exc}")
            self._log_price_lookup_timings(timings, pipeline_started)
            QMessageBox.warning(self, "物品 OCR 失败", str(exc))
            return
        timings.append(("自适应OCR+本地匹配", _elapsed_ms(stage_started)))

        if matched_price is None or matched_result is None or len(equally_good_item_ids) != 1:
            save_item_lookup_debug_images(
                hover_search=hover_search_image,
                item_name=item_image,
                inventory_tab=inventory_image,
                character_header=character_header_image,
            )
            if saw_candidates:
                self.item_price_label.setText("Price: no unique item match")
                self._log_event("无匹配物品：OCR 候选无法唯一匹配本地物品。")
            else:
                self.item_price_label.setText("Price: no item name detected")
                self._log_event("无匹配物品：没有识别到可用的物品名。")
            self._log_price_lookup_timings(timings, pipeline_started)
            return

        self.item_name_field.setText(matched_result.candidates[0])
        self._log_price_lookup_timings(timings, pipeline_started)
        self.price_result_ready.emit(matched_price, "")

    def capture_item_price_after_delay(self) -> None:
        if not self._feature_enabled("price_lookup") or self.price_client is None:
            self._log("查价模块未启用，已跳过延迟查价。")
            return
        seconds = int(self.config.get("button_capture_delay_seconds", 0))
        if seconds <= 0:
            self._log("即将截图。hover 模式建议在游戏中等名称框出现后按热键触发。")
            self.capture_item_price()
            return
        self._log(f"请在 {seconds} 秒内切回游戏，把鼠标悬停到物品上。建议平时直接用热键。")
        self.item_price_label.setText(f"价格: {seconds} 秒后截图，请切回游戏并悬停物品")
        QTimer.singleShot(seconds * 1000, self.capture_item_price)

    def lookup_manual_item_name(self) -> None:
        if self._closing or not self._feature_enabled("price_lookup") or self.price_client is None:
            self._log("查价模块未启用，已跳过手动查价。")
            return
        name = self.item_name_field.text().strip()
        lookup_name = self.item_completion_lookup.get(name, name)
        if lookup_name != name:
            name = lookup_name
            self.item_name_field.setText(name)
        if not name:
            self.item_price_label.setText("价格: 请先输入物品名")
            self._log_event("已跳过查价：物品名为空。")
            return

        mode_started = time.perf_counter()
        mode = self.price_client.set_game_mode(self._selected_price_game_mode())
        self._on_price_lookup_timing_ready("价格模式准备", _elapsed_ms(mode_started))
        self.current_price_game_mode = mode
        self.config["price_game_mode_default"] = mode
        label = _game_mode_label(mode)
        self.item_price_label.setText(f"价格: 正在查询 {label} / {name}...")
        self._log(f"正在从本地 {label} 缓存查价：{name}")
        self._start_worker("price-lookup", self._lookup_price_worker, name, mode)

    def _refresh_item_completer(self) -> None:
        if not hasattr(self, "item_completion_model"):
            return
        if self.price_client is None:
            self.item_completion_lookup = {}
            self.item_completion_model.clear()
            return
        entries = self.price_client.completion_entries(self._selected_price_game_mode())
        self.item_completion_lookup = {}
        self.item_completion_model.clear()
        self.item_completion_model.setColumnCount(2)
        for entry in entries:
            self.item_completion_lookup.setdefault(entry.display, entry.lookup)
            name_item = QStandardItem(entry.display)
            tag_item = QStandardItem(entry.tag)
            for item in (name_item, tag_item):
                item.setEditable(False)
            name_item.setData(entry.lookup, Qt.ItemDataRole.UserRole)
            tag_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tag_item.setBackground(QBrush(QColor(entry.tag_color)))
            tag_item.setForeground(QBrush(QColor(entry.tag_text_color)))
            self.item_completion_model.appendRow([name_item, tag_item])
        self._configure_item_completion_popup()

    def _on_item_completion_activated(self, value: str) -> None:
        lookup = self.item_completion_lookup.get(value, value)
        self.item_name_field.setText(lookup)

    def _configure_item_completion_popup(self, popup: QTreeView | None = None) -> None:
        if popup is None:
            completer = self.item_name_field.completer() if hasattr(self, "item_name_field") else None
            popup = completer.popup() if completer is not None else None
        if not isinstance(popup, QTreeView):
            return
        header = popup.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        popup.setColumnWidth(1, 86)
        popup.setMinimumWidth(max(620, self.item_name_field.width() + 260))

    def _on_item_completion_index_activated(self, index: QModelIndex) -> None:
        lookup = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(lookup, str) and lookup.strip():
            self.item_name_field.setText(lookup.strip())
            return
        value = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        self._on_item_completion_activated(value)

    def _lookup_item_candidates(
        self,
        names: list[str],
        *,
        timings: list[tuple[str, float]] | None = None,
        pipeline_started: float | None = None,
    ) -> None:
        if not self._feature_enabled("price_lookup") or self.price_client is None:
            self._log("查价模块未启用，已跳过候选查价。")
            return
        candidates: list[str] = []
        seen: set[str] = set()
        for name in names:
            value = name.strip()
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                candidates.append(value)
        if not candidates:
            self.item_price_label.setText("Price: no item name detected")
            self._log_event("无匹配物品：没有识别到可用的物品名。")
            return
        mode_started = time.perf_counter()
        mode = self.price_client.set_game_mode(self._selected_price_game_mode())
        mode_elapsed_ms = _elapsed_ms(mode_started)
        if timings is not None:
            timings.append(("价格模式准备", mode_elapsed_ms))
            if pipeline_started is not None:
                self._log_price_lookup_timings(timings, pipeline_started)
        else:
            self._on_price_lookup_timing_ready("价格模式准备", mode_elapsed_ms)
        self.current_price_game_mode = mode
        self.config["price_game_mode_default"] = mode
        label = _game_mode_label(mode)
        self.item_price_label.setText(f"价格: 正在查询 {label} / {candidates[0]}...")
        self._log(f"正在从本地 {label} 缓存查价候选：{', '.join(candidates)}")
        self._start_worker("price-lookup", self._lookup_price_candidates_worker, candidates, mode)

    def _lookup_price_worker(self, name: str, game_mode: str) -> None:
        if self._closing or self.price_client is None:
            return
        started = time.perf_counter()
        try:
            price = self.price_client.lookup(name, game_mode)
        except PriceLookupError as exc:
            price = None
            error = str(exc)
        except Exception as exc:
            price = None
            error = f"查价异常：{exc}"
        else:
            error = ""
        if not self._closing:
            self.price_lookup_timing_ready.emit("本地价格匹配", _elapsed_ms(started))
            self.price_result_ready.emit(price, error)

    def _lookup_price_candidates_worker(self, names: list[str], game_mode: str) -> None:
        if self._closing or self.price_client is None:
            return
        started = time.perf_counter()
        try:
            price = self.price_client.lookup_candidates(names, game_mode)
        except PriceLookupError as exc:
            price = None
            error = str(exc)
        except Exception as exc:
            price = None
            error = f"查价异常：{exc}"
        else:
            error = ""
        if not self._closing:
            self.price_lookup_timing_ready.emit("本地候选匹配", _elapsed_ms(started))
            self.price_result_ready.emit(price, error)

    def _price_timing_logs_enabled(self) -> bool:
        return bool(self.config.get("performance_price_timing_logs", True))

    def _log_price_lookup_timings(
        self,
        timings: list[tuple[str, float]],
        pipeline_started: float,
    ) -> None:
        if not self._price_timing_logs_enabled():
            return
        parts = [f"{label} {elapsed:.1f}ms" for label, elapsed in timings]
        parts.append(f"前台合计 {_elapsed_ms(pipeline_started):.1f}ms")
        self._log("查价性能：" + " · ".join(parts))

    def _on_price_lookup_timing_ready(self, label: str, elapsed_ms: float) -> None:
        if self._price_timing_logs_enabled():
            self._log(f"查价性能：{label} {elapsed_ms:.2f}ms")

    def _price_history_worker(self, price: object, source: str = "json") -> None:
        if self._closing or self.price_client is None:
            return
        try:
            summary = self.price_client.smart_listing_estimate(
                price,
                days=2,
                source=source,
            )
        except Exception as exc:
            if not self._closing:
                if source == "json":
                    self.price_history_json_failed.emit(price, str(exc))
                else:
                    self.price_history_ready.emit(price, None, str(exc))
            return
        if not self._closing:
            self.price_history_ready.emit(price, summary, "")

    def _on_price_history_json_failed(self, price: object, error: str) -> None:
        if self._closing or not self._feature_enabled("price_lookup"):
            return
        if _price_overlay_key(price) != self._active_price_key:
            return
        self._log(f"JSON historical price lookup failed: {error}")
        # Smart pricing is optional enrichment after the fast local card. A
        # transient history failure must not steal focus or delay an in-raid
        # lookup with a modal fallback prompt.
        self.price_history_ready.emit(price, None, error)

    def _detect_inventory_from_capture(
        self,
        capture_mode: str,
        manual_size: tuple[int, int] | None,
        capture_region: Region | None,
    ) -> tuple[bool, list[str], Image.Image | None]:
        signature = _region_size_signature(capture_region)
        cached = self._inventory_check_cache
        if cached is not None:
            cached_at, cached_signature, cached_detected, cached_found = cached
            if cached_signature == signature and self._state_detection_cache_is_fresh(cached_at):
                self._log("Using cached inventory tab state.")
                return cached_detected, cached_found, None

        inventory_image: Image.Image | None = None
        detected = False
        found: list[str] = []
        configured_roi = self.config.get(
            "inventory_tab_roi_base",
            list(INVENTORY_TAB_ROI_BASE),
        )
        for candidate_index, roi in enumerate(inventory_tab_roi_candidates(configured_roi)):
            candidate_image, _, _ = capture_inventory_tab_region(
                capture_mode,
                manual_size,
                roi,
                capture_region,
                save_debug_image=False,
            )
            if inventory_image is None:
                inventory_image = candidate_image
            candidate_detected, candidate_found, _ = detect_inventory_tab_image(candidate_image)
            if not candidate_detected:
                continue
            detected = True
            found = candidate_found
            inventory_image = candidate_image
            if candidate_index > 0:
                self._log(f"Inventory tab fallback ROI matched: {roi}.")
            break
        self._inventory_check_cache = (time.monotonic(), signature, detected, found)
        return detected, found, inventory_image

    def _detect_character_header_from_capture(
        self,
        capture_mode: str,
        manual_size: tuple[int, int] | None,
        capture_region: Region | None,
    ) -> tuple[bool, list[str], Image.Image | None]:
        signature = _region_size_signature(capture_region)
        cached = self._character_header_check_cache
        if cached is not None:
            cached_at, cached_signature, cached_detected, cached_found = cached
            if cached_signature == signature and self._state_detection_cache_is_fresh(cached_at):
                self._log("Using cached character header state.")
                return cached_detected, cached_found, None

        header_image: Image.Image | None = None
        detected = False
        found: list[str] = []
        for candidate_index, roi in enumerate(achievements_tab_roi_candidates()):
            candidate_image, _, _ = capture_inventory_tab_region(
                capture_mode,
                manual_size,
                roi,
                capture_region,
                save_debug_image=False,
            )
            if header_image is None:
                header_image = candidate_image
            candidate_detected, candidate_found, _ = detect_character_header_image(
                candidate_image
            )
            if not candidate_detected:
                continue
            detected = True
            found = candidate_found
            header_image = candidate_image
            if candidate_index > 0:
                self._log(f"Character header fallback ROI matched: {roi}.")
            break
        self._character_header_check_cache = (
            time.monotonic(),
            signature,
            detected,
            found,
        )
        return detected, found, header_image

    def _state_detection_cache_is_fresh(self, cached_at: float) -> bool:
        ttl = max(0.0, float(self.config.get("state_detection_cache_seconds", 2)))
        return ttl > 0 and time.monotonic() - cached_at <= ttl

    def _clear_state_detection_cache(self) -> None:
        self._inventory_check_cache = None
        self._character_header_check_cache = None

    def _start_worker(
        self,
        name: str,
        target: Callable[..., None],
        *args: object,
    ) -> None:
        if self._closing:
            return
        if bool(self.config.get("performance_mode_enabled", True)):
            max_workers = self._max_concurrent_workers()
            active_workers = self._active_worker_count()
            if active_workers >= max_workers:
                self._log_event(
                    f"性能模式：已有 {active_workers} 个后台任务运行，已暂缓 {name}。"
                )
                return

        def run() -> None:
            try:
                target(*args)
            finally:
                current = threading.current_thread()
                with self._workers_lock:
                    self._workers.discard(current)

        thread = threading.Thread(target=run, name=name, daemon=True)
        with self._workers_lock:
            self._workers.add(thread)
        thread.start()

    def _active_worker_count(self) -> int:
        with self._workers_lock:
            workers = [worker for worker in self._workers if worker.is_alive()]
            self._workers = set(workers)
            return len(workers)

    def _max_concurrent_workers(self) -> int:
        try:
            value = int(self.config.get("performance_max_concurrent_workers", 2))
        except (TypeError, ValueError):
            value = 2
        return max(1, value)

    def _on_resource_cleanup_timer(self) -> None:
        if self._closing or self._active_worker_count() > 0:
            return
        tarkov_active, _ = is_tarkov_foreground()
        if tarkov_active:
            return
        self._cleanup_memory()

    def _cleanup_memory(self) -> None:
        if not bool(self.config.get("performance_mode_enabled", True)):
            return
        gc.collect()

    def _join_workers(self, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._workers_lock:
                workers = [
                    worker
                    for worker in self._workers
                    if worker.is_alive() and worker is not threading.current_thread()
                ]
            if not workers:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            workers[0].join(timeout=min(0.2, remaining))

    def _on_price_result_ready(self, price: object, error: str) -> None:
        if self._closing or not self._feature_enabled("price_lookup"):
            return
        if error:
            self.item_price_label.setText(f"价格: {error}")
            self._log_event(error)
            if self.price_overlay is not None:
                self.price_overlay.clear_prices()
            return

        price_key = _price_overlay_key(price)
        self._active_price_key = price_key
        display_language = str(self.config.get("item_display_language", "zh"))
        raw_tiers = self.config.get("price_value_tiers", [])
        tiers = raw_tiers if isinstance(raw_tiers, list) else []
        basis = str(self.config.get("price_value_basis", "slot"))
        firearm_color = str(self.config.get("firearm_value_color", "#00D1D1"))
        firearm_accent = str(self.config.get("firearm_value_accent", firearm_color))
        hideout_lines = (
            self.hideout_tracker.item_demand_lines(str(getattr(price, "item_id", "")))
            if self._feature_enabled("hideout") and self.hideout_tracker is not None
            else []
        )
        recipe_notices = self._tracked_recipe_requirement_notices(price)
        needs_history = bool(self.config.get("smart_price_enabled", False)) and (
            not isinstance(getattr(price, "ammo_properties", None), dict)
        )
        view = _build_price_view(
            price,
            display_language,
            tiers,
            basis,
            firearm_color,
            firearm_accent,
            hideout_lines,
            flea_intelligence_center_level=(
                _safe_int(self.config.get("flea_intelligence_center_level")) or 0
            ),
            flea_hideout_management_level=(
                _safe_int(self.config.get("flea_hideout_management_level")) or 0
            ),
            recipe_notices=recipe_notices,
            recipe_accent_color=self._recipe_overlay_color(),
            smart_pending=needs_history,
            toast_key=price_key,
        )
        self.item_price_label.setText(view.label_html)
        self.item_price_label.setTextFormat(Qt.TextFormat.RichText)
        self._log_event(view.log_text)
        if self.price_overlay is not None and bool(self.config.get("price_overlay_enabled", True)):
            try:
                seconds = int(self.config.get("price_overlay_seconds", 10))
            except (TypeError, ValueError):
                seconds = 10
            self.price_overlay.show_price(view, seconds)
        elif self.price_overlay is not None:
            self.price_overlay.clear_prices()
        if needs_history:
            self._start_worker("price-history", self._price_history_worker, price)

    def _on_price_history_ready(self, price: object, summary: object, error: str) -> None:
        if self._closing or not self._feature_enabled("price_lookup"):
            return
        if not bool(self.config.get("smart_price_enabled", False)):
            return
        price_key = _price_overlay_key(price)
        if price_key != self._active_price_key:
            return
        if error:
            self._log(f"Historical price lookup failed: {error}")
            summary = SmartPriceEstimate(
                suggested_price=None,
                lower_price=None,
                upper_price=None,
                confidence="low",
                basis="智能挂价",
                risk_notice="历史价格暂不可用，建议价回退使用API最近低价",
                sample_count=0,
                effective_sample_size=0.0,
                current_offer_count=_safe_int(
                    getattr(price, "last_offer_count", None)
                ),
            )

        display_language = str(self.config.get("item_display_language", "zh"))
        raw_tiers = self.config.get("price_value_tiers", [])
        tiers = raw_tiers if isinstance(raw_tiers, list) else []
        basis = str(self.config.get("price_value_basis", "slot"))
        firearm_color = str(self.config.get("firearm_value_color", "#00D1D1"))
        firearm_accent = str(self.config.get("firearm_value_accent", firearm_color))
        hideout_lines = (
            self.hideout_tracker.item_demand_lines(str(getattr(price, "item_id", "")))
            if self._feature_enabled("hideout") and self.hideout_tracker is not None
            else []
        )
        recipe_notices = self._tracked_recipe_requirement_notices(price)
        enhanced = _build_price_view(
            price,
            display_language,
            tiers,
            basis,
            firearm_color,
            firearm_accent,
            hideout_lines,
            flea_intelligence_center_level=(
                _safe_int(self.config.get("flea_intelligence_center_level")) or 0
            ),
            flea_hideout_management_level=(
                _safe_int(self.config.get("flea_hideout_management_level")) or 0
            ),
            recipe_notices=recipe_notices,
            recipe_accent_color=self._recipe_overlay_color(),
            smart_estimate=summary,
            toast_key=price_key,
        )
        self.item_price_label.setText(enhanced.label_html)
        self.item_price_label.setTextFormat(Qt.TextFormat.RichText)
        self._log_event(enhanced.log_text)
        if self.price_overlay is not None and bool(self.config.get("price_overlay_enabled", True)):
            try:
                seconds = int(self.config.get("price_overlay_seconds", 10))
            except (TypeError, ValueError):
                seconds = 10
            self.price_overlay.show_price(enhanced, seconds, replace_key=price_key)

    def _tracked_recipe_requirement_notices(self, price: object) -> list[RecipeNotice]:
        if (
            not self._feature_enabled("recipe_tracking")
            or self.recipe_catalog is None
            or not self.recipe_catalog.available
        ):
            return []
        return self.recipe_catalog.tracked_requirement_notices(
            str(getattr(price, "item_id", "")),
            self._tracked_recipe_ids(),
            str(getattr(price, "game_mode", self.current_price_game_mode)),
        )

    def _schedule_selected_reminders(
        self,
    ) -> tuple[list[tuple[str, TraderReminder]], list[tuple[str, str]]]:
        if not self._feature_enabled("trader_reminders") or self.reminders is None:
            self._log("商人补货模块未启用，已跳过提醒设置。")
            return [], []
        self._save_config()
        schedules: list[tuple[str, int, int, int]] = []
        invalid: list[tuple[str, str]] = []
        for trader in TRADERS:
            if not self.watch_checks[trader].isChecked():
                if self.countdown_items[trader].text() != "-":
                    self.status_items[trader].setText("未选择")
                continue

            value = self.countdown_items[trader].text().strip()
            seconds = timer_to_seconds(value)
            if seconds is None:
                self.status_items[trader].setText("倒计时无效")
                invalid.append((trader, value))
                self._log(f"已跳过 {trader}：倒计时无效 '{value}'。")
                continue
            schedules.append(
                (
                    trader,
                    seconds,
                    int(self.config.get("lead_time_seconds", 10)),
                    int(self.config.get("repeat_alert_seconds", 0)),
                )
            )

        reminders = self.reminders.replace(schedules)
        scheduled: list[tuple[str, TraderReminder]] = []
        for trader, reminder in reminders.items():
            self._log(
                f"已设置 {trader}：补货 {reminder.restock_at.strftime('%H:%M:%S')}，"
                f"提醒 {reminder.notify_at.strftime('%H:%M:%S')}。"
            )
            scheduled.append((trader, reminder))

        if not scheduled:
            self._log("没有设置任何提醒。请勾选商人后重新识别倒计时。")
        return scheduled, invalid

    def _show_trader_capture_feedback(
        self,
        timers: list[str],
        scheduled: list[tuple[str, TraderReminder]],
        invalid: list[tuple[str, str]],
    ) -> None:
        if scheduled:
            self._show_trader_schedule_feedback(scheduled, invalid)
            return
        detail_lines = [f"已识别 {len(timers)} 个倒计时，但没有设置提醒。"]
        if invalid:
            detail_lines.append("无效倒计时：" + "；".join(f"{trader} {value or '-'}" for trader, value in invalid))
        else:
            detail_lines.append("请勾选要提醒的商人后重新识别。")
        self._show_operation_feedback(
            "商人倒计时已识别",
            "未设置提醒",
            "\n".join(detail_lines),
            accent_color="#F2C14E",
        )

    def _show_trader_schedule_feedback(
        self,
        scheduled: list[tuple[str, TraderReminder]],
        invalid: list[tuple[str, str]],
    ) -> None:
        if scheduled:
            detail_lines = [
                f"{trader} {reminder.restock_at:%H:%M:%S}"
                for trader, reminder in scheduled
            ]
            if invalid:
                detail_lines.append(
                    "未设置："
                    + "；".join(f"{trader} {value or '-'}" for trader, value in invalid)
                )
            self._show_operation_feedback(
                "已记录并设置提醒",
                f"{len(scheduled)} 个商人",
                "\n".join(
                    [
                        *detail_lines,
                        f"按 {self.config.get('reminder_hold_hotkey', 'F7')} 查看实时倒计时。",
                    ]
                ),
                accent_color="#36D27F",
            )
            return
        title = "商人倒计时已识别"
        detail = "没有勾选商人，或勾选商人的倒计时无效。"
        if invalid:
            detail = "无效倒计时：" + "；".join(
                f"{trader} {value or '-'}" for trader, value in invalid
            )
        self._show_operation_feedback(
            title,
            "0 个商人",
            detail,
            accent_color="#F2C14E",
        )

    def _show_operation_feedback(
        self,
        title: str,
        value_text: str,
        detail: str,
        *,
        accent_color: str = "#5DA8FF",
        seconds: int | None = None,
    ) -> None:
        if self.feedback_overlay is None:
            self._log(f"{title}: {value_text} / {detail}")
            return
        if seconds is None:
            seconds = self._feedback_overlay_seconds()
        self.feedback_overlay.show_feedback(
            ReminderView(
                title=title,
                value_text=value_text,
                detail=detail,
                accent_color=accent_color,
            ),
            seconds=seconds,
        )

    def _feedback_overlay_seconds(self) -> int:
        try:
            return int(self.config.get("feedback_overlay_seconds", 6))
        except (TypeError, ValueError):
            return 6

    def _on_reminders_updated(self, reminders: object) -> None:
        if not isinstance(reminders, dict):
            return
        active = {
            str(trader): reminder
            for trader, reminder in reminders.items()
            if isinstance(reminder, TraderReminder)
        }
        if self.reminder_overlay is not None:
            self.reminder_overlay.set_reminders(active)
        if not self.countdown_items:
            return
        for trader, reminder in active.items():
            if trader not in self.countdown_items:
                continue
            remaining = remaining_countdown_seconds(reminder)
            self.countdown_items[trader].setText(format_countdown(remaining))
            self.restock_items[trader].setText(reminder.restock_at.strftime("%H:%M:%S"))
            if remaining <= 0:
                status = "已补货"
            elif reminder.triggered:
                status = "即将补货"
            else:
                status = "倒计时中"
            self.status_items[trader].setText(status)

    def clear_reminders(self) -> None:
        if self.reminders is None or self.reminder_overlay is None:
            self._log("商人补货模块未启用，已跳过清空提醒。")
            return
        self.reminders.clear()
        self.reminder_overlay.clear_reminders()
        for trader in TRADERS:
            self.status_items[trader].setText("未启用")
            self.restock_items[trader].setText("")
            self.countdown_items[trader].setText("-")
        self._log("提醒已清空。")

    def open_debug_crop(self) -> None:
        _, crop_path = debug_paths()
        if not crop_path.exists():
            self._log("还没有倒计时截图。")
            return
        os.startfile(crop_path)  # type: ignore[attr-defined]

    def open_item_crop(self) -> None:
        crop_path = item_debug_path()
        if not crop_path.exists():
            self._log("还没有物品截图。")
            return
        os.startfile(crop_path)  # type: ignore[attr-defined]

    def _on_reminder_triggered(self, trader: str, reminder: TraderReminder) -> None:
        if not self._feature_enabled("trader_reminders") or self.reminder_overlay is None:
            return
        remaining = remaining_countdown_seconds(reminder)
        self.status_items[trader].setText("已补货" if remaining <= 0 else "即将补货")
        self._log(f"{trader} 的提醒已触发。")
        if bool(self.config.get("sound_enabled", True)):
            QApplication.beep()
        if bool(self.config.get("popup_enabled", True)):
            self.reminder_overlay.show_triggered(trader)

    def toggle_reminder_hold(self) -> None:
        if self.reminder_overlay is None:
            self._log("商人补货模块未启用，已跳过倒计时悬浮窗切换。")
            return
        state = self.reminder_overlay.toggle_visibility()
        if state is None:
            self._log("当前没有已设置的商人补货倒计时。")
        elif state:
            self._log("商人补货倒计时悬浮窗已显示。")
        else:
            self._log("商人补货倒计时悬浮窗已隐藏；再次按热键显示。")

    def _manual_size(self) -> tuple[int, int] | None:
        if not bool(self.config.get("manual_resolution_enabled", False)):
            return None
        return int(self.config.get("manual_width", 2048)), int(self.config.get("manual_height", 1152))

    def _ensure_tarkov_foreground(self, action_name: str) -> bool:
        if not bool(self.config.get("require_tarkov_foreground", True)):
            return True
        is_foreground, title = is_tarkov_foreground()
        if is_foreground:
            return True
        message = f"已拒绝{action_name}：当前前台窗口不是 Tarkov，而是「{title}」。"
        self._log(message, visible=False)
        if hasattr(self, "item_price_label"):
            self.item_price_label.setText("价格: 当前前台窗口不是 Tarkov，未截图")
        return False

    def _reset_run_log(self) -> None:
        try:
            self._run_log_path.parent.mkdir(exist_ok=True)
            self._run_log_path.write_text(
                f"EFT Raid Assistant latest run\nStarted at {datetime.now():%Y-%m-%d %H:%M:%S}\n\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    def _log(self, message: str, visible: bool = False) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        try:
            self._run_log_path.parent.mkdir(exist_ok=True)
            with self._run_log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass
        if hasattr(self, "log_bus"):
            self.log_bus.publish(line, visible=visible)

    def _append_main_log_line(self, line: str) -> None:
        if not hasattr(self, "log"):
            return
        self.log.append(line)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _log_event(self, message: str) -> None:
        self._log(message, visible=True)


def _format_hideout_item_summary(record: dict[str, object]) -> str:
    items = record.get("items")
    if not isinstance(items, list):
        return "无材料记录"

    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("short_name") or "未知材料")
        required = _safe_int(item.get("required"))
        owned = _safe_int(item.get("owned"))
        remaining = _safe_int(item.get("remaining"))
        required_text = "?" if required is None else str(required)
        owned_text = "?" if owned is None else str(owned)
        if remaining is None:
            detail = "未识别已有数量" if owned is None else ""
        elif remaining > 0:
            detail = f"缺 {remaining}"
        else:
            detail = "已够"
        if detail:
            parts.append(f"{name}: {owned_text}/{required_text}（{detail}）")
        else:
            parts.append(f"{name}: {owned_text}/{required_text}")
    return "；".join(parts) if parts else "无材料记录"


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _preset_float(preset: dict[str, object], key: str, fallback: float) -> float:
    try:
        return float(preset.get(key, fallback))
    except (TypeError, ValueError):
        return fallback


def _format_display_filter_value(key: str, value: float) -> str:
    if key == "black_lift":
        return f"{value * 100:.0f}%"
    return f"{value:.2f}"


class GammaCurvePreview(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(220, 150)
        self.setStyleSheet("background: #050505; border: 1px solid rgba(255, 255, 255, 60);")
        self.set_preset({})

    def set_preset(self, preset: dict[str, object]) -> None:
        width = max(1, self.width())
        height = max(1, self.height())
        pixmap = QPixmap(width, height)
        pixmap.fill(QColor("#050505"))
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor(50, 50, 50), 1))
            for fraction in (0.25, 0.5, 0.75):
                x = int(fraction * (width - 1))
                y = int(fraction * (height - 1))
                painter.drawLine(x, 0, x, height)
                painter.drawLine(0, y, width, y)
            ramp = build_gamma_ramp(preset)[0]
            painter.setPen(QPen(QColor("#F2F2F2"), 2))
            last_x = 0
            last_y = height - 1 - int((ramp[0] / 65535) * (height - 1))
            for index, value in enumerate(ramp[1:], start=1):
                x = int((index / 255) * (width - 1))
                y = height - 1 - int((value / 65535) * (height - 1))
                painter.drawLine(last_x, last_y, x, y)
                last_x, last_y = x, y
        finally:
            painter.end()
        self.setPixmap(pixmap)


class DisplayFilterControlDialog(QDialog):
    def __init__(self, main_window: MainWindow) -> None:
        super().__init__(main_window)
        self.main_window = main_window
        self._loading = False
        self.sliders: dict[str, QSlider] = {}
        self.value_labels: dict[str, QLabel] = {}
        self.setWindowTitle("Gamma 局内调节")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(520, 360)

        layout = QVBoxLayout(self)
        target_row = QFormLayout()
        self.target_combo = QComboBox()
        self.main_window._populate_display_target_combo(self.target_combo, refresh=True)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        target_row.addRow("目标显示器", self.target_combo)
        layout.addLayout(target_row)
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_preset_changed)
        layout.addWidget(self.combo)

        editor = QWidget()
        editor_layout = QHBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        for key, (label, minimum, maximum, _scale, _decimals) in DISPLAY_FILTER_SLIDERS.items():
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(minimum, maximum)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            slider.setTickInterval(max(1, (maximum - minimum) // 5))
            value_label = QLabel("")
            value_label.setMinimumWidth(56)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(value_label)
            self.sliders[key] = slider
            self.value_labels[key] = value_label
            slider.valueChanged.connect(self._on_slider_changed)
            form.addRow(label, row)
        self.curve = GammaCurvePreview()
        editor_layout.addLayout(form, 1)
        editor_layout.addWidget(self.curve)
        layout.addWidget(editor)

        self.live_preview = QCheckBox("实时应用")
        self.live_preview.setChecked(True)
        layout.addWidget(self.live_preview)

        buttons = QWidget()
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        apply_button = QPushButton("应用")
        apply_button.clicked.connect(self.apply_current)
        new_button = QPushButton("新建方案")
        new_button.clicked.connect(self.create_new)
        save_button = QPushButton("保存为方案")
        save_button.clicked.connect(self.save_current)
        restore_button = QPushButton("恢复")
        restore_button.clicked.connect(
            lambda checked=False: self.main_window.restore_display_filter(show_feedback=False)
        )
        close_button = QPushButton("隐藏")
        close_button.clicked.connect(self.hide)
        button_layout.addWidget(apply_button)
        button_layout.addWidget(new_button)
        button_layout.addWidget(save_button)
        button_layout.addWidget(restore_button)
        button_layout.addWidget(close_button)
        layout.addWidget(buttons)
        self.reload_presets()

    def reload_presets(self, *, select_name: str = "") -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        presets = self.main_window._display_filter_presets()
        for index, preset in enumerate(presets):
            self.combo.addItem(str(preset.get("name", f"Preset {index + 1}")), index)
        selected = 0
        if select_name:
            for index, preset in enumerate(presets):
                if str(preset.get("name", "")) == select_name:
                    selected = index
                    break
        if self.combo.count() > 0:
            self.combo.setCurrentIndex(selected)
        self.combo.blockSignals(False)
        self._on_preset_changed()

    def _selected_preset(self) -> dict[str, object] | None:
        presets = self.main_window._display_filter_presets()
        if not presets:
            return None
        return presets[max(0, self.combo.currentIndex()) % len(presets)]

    def _preset_from_controls(self) -> dict[str, object]:
        preset = self._selected_preset() or {}
        result: dict[str, object] = {
            "name": str(preset.get("name", "Custom")),
            "description": str(preset.get("description", "自定义 Gamma 曲线")),
            "hotkey": str(preset.get("hotkey", "")),
        }
        for key, (_label, _minimum, _maximum, scale, decimals) in DISPLAY_FILTER_SLIDERS.items():
            result[key] = round(self.sliders[key].value() / scale, decimals)
        return result

    def _load_controls(self, preset: dict[str, object]) -> None:
        self._loading = True
        try:
            for key, (_label, minimum, maximum, scale, _decimals) in DISPLAY_FILTER_SLIDERS.items():
                value = int(round(_preset_float(preset, key, self.sliders[key].value() / scale) * scale))
                self.sliders[key].setValue(min(max(value, minimum), maximum))
        finally:
            self._loading = False
        self._update_preview()

    def _on_preset_changed(self) -> None:
        preset = self._selected_preset()
        if preset is not None:
            self._load_controls(preset)

    def _on_slider_changed(self) -> None:
        if self._loading:
            return
        self._update_preview()
        if self.live_preview.isChecked():
            self.apply_current()

    def _update_preview(self) -> None:
        preset = self._preset_from_controls()
        for key, label in self.value_labels.items():
            label.setText(_format_display_filter_value(key, _preset_float(preset, key, 1.0)))
        self.curve.set_preset(preset)

    def apply_current(self) -> None:
        self.main_window._apply_display_filter_preset(self._preset_from_controls(), notify=False)

    def _on_target_changed(self) -> None:
        target_id = str(self.target_combo.currentData() or "")
        active = self.main_window._display_filter_baseline is not None
        self.main_window._set_display_filter_target(target_id, reapply=False)
        if active:
            self.apply_current()

    def create_new(self) -> None:
        default_name = self.main_window._unique_display_filter_preset_name("自定义方案")
        name, ok = QInputDialog.getText(
            self,
            "新建 Gamma 方案",
            "方案名称：",
            text=default_name,
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if self.main_window._display_filter_preset_name_exists(name):
            QMessageBox.warning(
                self,
                "方案名称已存在",
                "这个 Gamma 方案名称已经存在。请换一个名称，或使用“保存为方案”。",
            )
            return
        preset = self._preset_from_controls()
        preset["name"] = name
        preset["description"] = "自定义 Gamma 曲线"
        preset["hotkey"] = ""
        self.main_window._upsert_display_filter_preset(preset)
        self.reload_presets(select_name=name)
        self.main_window._log_event(f"Gamma 方案已新建：{name}")

    def save_current(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "保存 Gamma 方案",
            "方案名称：",
            text=str((self._selected_preset() or {}).get("name", "")),
        )
        if not ok or not name.strip():
            return
        preset = self._preset_from_controls()
        preset["name"] = name.strip()
        preset["description"] = "自定义 Gamma 曲线"
        self.main_window._upsert_display_filter_preset(preset)
        self.reload_presets(select_name=name.strip())


class FeatureSetupDialog(QDialog):
    def __init__(self, config: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("首次启动设置")
        self.resize(500, 500)
        self._config = copy.deepcopy(config)
        self.feature_checks: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)
        title = QLabel("选择要启用的功能")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        detail = QLabel("软件会根据选择显示对应的主界面面板和热键；之后也可以在设置里随时修改。")
        detail.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail)

        initial = set(DEFAULT_ENABLED_FEATURES)
        if bool(config.get("feature_setup_complete", False)):
            raw_enabled = config.get("enabled_features", DEFAULT_ENABLED_FEATURES)
            if isinstance(raw_enabled, list):
                initial = {str(item) for item in raw_enabled}
        for feature_id, label in FEATURE_DEFINITIONS.items():
            check = QCheckBox(label)
            check.setObjectName("featureChoice")
            check.setChecked(feature_id in initial)
            self.feature_checks[feature_id] = check
            layout.addWidget(check)

        fee_group = QGroupBox("跳蚤手续费资料")
        fee_layout = QFormLayout(fee_group)
        self.flea_intelligence_center_level = QComboBox()
        self.flea_intelligence_center_level.addItem("0 级 / 未建造", 0)
        self.flea_intelligence_center_level.addItem("1 级", 1)
        self.flea_intelligence_center_level.addItem("2 级", 2)
        self.flea_intelligence_center_level.addItem("3 级（启用手续费折扣）", 3)
        intelligence_center_level = max(
            0,
            min(3, _safe_int(config.get("flea_intelligence_center_level")) or 0),
        )
        self.flea_intelligence_center_level.setCurrentIndex(
            max(0, self.flea_intelligence_center_level.findData(intelligence_center_level))
        )

        self.flea_hideout_management_level = QSpinBox()
        self.flea_hideout_management_level.setRange(0, 50)
        self.flea_hideout_management_level.setSuffix(" 级")
        self.flea_hideout_management_level.setValue(
            max(
                0,
                min(
                    50,
                    _safe_int(config.get("flea_hideout_management_level")) or 0,
                ),
            )
        )
        fee_layout.addRow("情报中心等级", self.flea_intelligence_center_level)
        fee_layout.addRow("藏身处管理技能", self.flea_hideout_management_level)
        fee_note = QLabel(
            "这些等级只用于估算挂单手续费和跳蚤净收益，不会上传。"
            "情报中心 3 级才会启用折扣，之后可在“设置 → 查价”修改。"
        )
        fee_note.setWordWrap(True)
        fee_layout.addRow(fee_note)
        layout.addWidget(fee_group)
        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, object]:
        enabled = [
            feature_id for feature_id, check in self.feature_checks.items() if check.isChecked()
        ]
        return {
            "enabled_features": enabled,
            "feature_setup_complete": True,
            "flea_intelligence_center_level": (
                self.flea_intelligence_center_level.currentData() or 0
            ),
            "flea_hideout_management_level": self.flea_hideout_management_level.value(),
        }


class SettingsDialog(QDialog):
    def __init__(self, config: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(720, 600)
        self.setMinimumSize(640, 520)
        self._config = config
        self.roi_fields: list[QSpinBox] = []
        self.item_roi_fields: list[QSpinBox] = []
        self.inventory_tab_roi_fields: list[QSpinBox] = []
        self.hover_offset_fields: list[QSpinBox] = []
        self.hover_size_fields: list[QSpinBox] = []
        self.hover_search_margin_fields: list[QSpinBox] = []
        self.hover_name_padding_fields: list[QSpinBox] = []
        self.feature_checks: dict[str, QCheckBox] = {}
        self.hotkey_fields: dict[str, HotkeyLineEdit] = {}
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.addTab(self._build_general_tab(), "常规")
        self.settings_tabs.addTab(self._build_features_tab(), "功能")
        self.settings_tabs.addTab(self._build_prices_tab(), "查价")
        self.settings_tabs.addTab(self._build_notifications_tab(), "提醒与浮窗")
        self.settings_tabs.addTab(self._build_hotkeys_tab(), "快捷键")
        self.settings_tabs.addTab(self._build_advanced_tab(), "高级")
        self.settings_tabs.setCurrentIndex(0)
        layout.addWidget(self.settings_tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        appearance = QGroupBox("外观")
        appearance_layout = QFormLayout(appearance)
        self.ui_theme = QComboBox()
        for theme_id, label in THEME_LABELS.items():
            self.ui_theme.addItem(label, theme_id)
        self.ui_font_size = QSpinBox()
        self.ui_font_size.setRange(9, 18)
        self.ui_font_size.setSuffix(" pt")
        appearance_layout.addRow("界面主题", self.ui_theme)
        appearance_layout.addRow("主界面字体大小", self.ui_font_size)
        layout.addWidget(appearance)

        content = QGroupBox("内容与语言")
        content_layout = QFormLayout(content)
        self.item_display_language = QComboBox()
        self.item_display_language.addItem("中文", "zh")
        self.item_display_language.addItem("English", "en")
        content_layout.addRow("物品与任务名称", self.item_display_language)
        layout.addWidget(content)

        behavior = QGroupBox("应用行为")
        behavior_layout = QVBoxLayout(behavior)
        self.close_to_tray = QCheckBox("点击关闭按钮时询问最小化到托盘或退出")
        behavior_layout.addWidget(self.close_to_tray)
        layout.addWidget(behavior)

        note = QLabel(
            "主题和字体保存后立即应用到主窗口与设置界面；局内半透明提示继续使用"
            "独立暗色样式和字号，避免遮挡游戏画面。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return tab

    def _build_capture_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        basic = QFormLayout()

        self.capture_mode = QComboBox()
        for label, value in [
            ("自动", "Auto"),
            ("塔科夫窗口", "Tarkov window"),
            ("鼠标所在显示器", "Monitor under cursor"),
            ("主显示器", "Primary monitor"),
        ]:
            self.capture_mode.addItem(label, value)
        self.manual_resolution = QCheckBox("手动指定分辨率")
        self.resolution_preset = QComboBox()
        self.resolution_preset.addItems(["2048x1152", "1920x1080", "2560x1440", "3440x1440"])
        self.resolution_preset.currentTextChanged.connect(self._apply_resolution_preset)
        self.manual_width = QSpinBox()
        self.manual_width.setRange(640, 10000)
        self.manual_height = QSpinBox()
        self.manual_height.setRange(480, 10000)
        self.item_capture_mode = QComboBox()
        self.item_capture_mode.addItem("鼠标悬停提示", "Hover tooltip")
        self.item_capture_mode.addItem("固定物品名 ROI", "Fixed ROI")
        self.hover_wait_ms = QSpinBox()
        self.hover_wait_ms.setRange(0, 5000)
        self.hover_wait_ms.setSuffix(" ms")

        timer_roi = self._build_roi_fields(self.roi_fields)
        item_roi = self._build_roi_fields(self.item_roi_fields)
        inventory_tab_roi = self._build_roi_fields(self.inventory_tab_roi_fields)
        hover_offset = self._build_number_fields(self.hover_offset_fields, ["x", "y"], -2000, 2000)
        hover_size = self._build_number_fields(self.hover_size_fields, ["宽", "高"], 20, 2000)
        hover_search_margins = self._build_number_fields(
            self.hover_search_margin_fields,
            ["左", "右", "上", "下"],
            0,
            3000,
        )
        hover_name_padding = self._build_number_fields(
            self.hover_name_padding_fields,
            ["左", "上", "右", "下"],
            0,
            200,
        )

        basic.addRow("截图模式", self.capture_mode)
        basic.addRow("物品识别方式", self.item_capture_mode)
        content_layout.addLayout(basic)

        advanced = QGroupBox("手动识别校准（仅排错时使用）")
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_layout = QVBoxLayout(advanced)
        advanced_body = QWidget()
        advanced_form = QFormLayout(advanced_body)
        advanced_form.addRow(self.manual_resolution)
        advanced_form.addRow("分辨率预设", self.resolution_preset)
        advanced_form.addRow("宽度", self.manual_width)
        advanced_form.addRow("高度", self.manual_height)
        advanced_form.addRow("悬停等待毫秒", self.hover_wait_ms)
        advanced_form.addRow("悬停搜索边距", hover_search_margins)
        advanced_form.addRow("名称框留白", hover_name_padding)
        advanced_form.addRow("悬停提示偏移", hover_offset)
        advanced_form.addRow("悬停提示尺寸", hover_size)
        advanced_form.addRow("装备页签 ROI", inventory_tab_roi)
        advanced_form.addRow("倒计时 ROI", timer_roi)
        advanced_form.addRow("物品名 ROI", item_roi)
        advanced_layout.addWidget(advanced_body)
        advanced_body.setVisible(False)
        advanced.toggled.connect(advanced_body.setVisible)
        content_layout.addWidget(advanced)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        return tab

    def _make_hotkey_field(self, label: str) -> HotkeyLineEdit:
        field = HotkeyLineEdit(label)
        field.set_conflict_checker(self._check_hotkey_conflict)
        self.hotkey_fields[label] = field
        return field

    def _check_hotkey_conflict(self, field: HotkeyLineEdit, hotkey: str) -> bool:
        try:
            normalized = normalize_hotkey(hotkey)
        except ValueError as exc:
            QMessageBox.warning(self, "热键无效", str(exc))
            return False

        conflict = self._find_settings_hotkey_conflict(normalized, source_field=field)
        if conflict is None:
            return True

        kind, label, target = conflict
        answer = QMessageBox.question(
            self,
            "快捷键冲突",
            f"{hotkey} 已被“{label}”使用。是否替代？选择“是”会清空原绑定。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

        if kind == "field":
            target.clear()  # type: ignore[attr-defined]
        elif kind == "preset":
            target["hotkey"] = ""  # type: ignore[index]
        return True

    def _find_settings_hotkey_conflict(
        self, normalized: str, *, source_field: HotkeyLineEdit
    ) -> tuple[str, str, object] | None:
        for label, field in self.hotkey_fields.items():
            if field is source_field:
                continue
            text = field.text().strip()
            if not text:
                continue
            try:
                if normalize_hotkey(text) == normalized:
                    return ("field", label, field)
            except ValueError:
                continue

        presets = self._config.get("display_filter_presets", [])
        if isinstance(presets, list):
            for preset in presets:
                if not isinstance(preset, dict):
                    continue
                text = str(preset.get("hotkey", "")).strip()
                if not text:
                    continue
                try:
                    if normalize_hotkey(text) == normalized:
                        name = str(preset.get("name", "")).strip() or "未命名"
                        return ("preset", f"Gamma 方案：{name}", preset)
                except ValueError:
                    continue
        return None

    def _build_hotkeys_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.capture_hotkey = self._make_hotkey_field("识别倒计时")
        self.item_lookup_hotkey = self._make_hotkey_field("物品查价")
        self.hideout_scan_hotkey = self._make_hotkey_field("识别藏身处")
        self.reminder_hold_hotkey = self._make_hotkey_field("显示/隐藏补货倒计时")
        self.raid_panel_hotkey = self._make_hotkey_field("打开/关闭局内控制")
        self.raid_log_hotkey = self._make_hotkey_field("打开/关闭局内日志")
        self.display_filter_restore_hotkey = self._make_hotkey_field("恢复 Gamma")

        lookup_group = QGroupBox("识别与查价")
        lookup_layout = QFormLayout(lookup_group)
        lookup_layout.addRow("物品查价", self.item_lookup_hotkey)
        lookup_layout.addRow("识别商人倒计时", self.capture_hotkey)
        lookup_layout.addRow("识别藏身处", self.hideout_scan_hotkey)
        layout.addWidget(lookup_group)

        overlay_group = QGroupBox("局内操作")
        overlay_layout = QFormLayout(overlay_group)
        overlay_layout.addRow("显示/隐藏补货倒计时", self.reminder_hold_hotkey)
        overlay_layout.addRow("打开/关闭局内控制", self.raid_panel_hotkey)
        overlay_layout.addRow("打开/关闭局内日志", self.raid_log_hotkey)
        overlay_layout.addRow("恢复 Gamma", self.display_filter_restore_hotkey)
        layout.addWidget(overlay_group)

        note = QLabel("未启用对应功能时，其专用热键不会注册，也不会占用键位。")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return tab

    def _build_features_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        intro = QLabel(
            "这里只决定软件要加载哪些模块；保存后立即生效。各模块的具体选项已按用途"
            "放到其他页面，标注 Beta 的功能仍在持续完善。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        for feature_id, label in FEATURE_DEFINITIONS.items():
            check = QCheckBox(label)
            check.setObjectName("featureChoice")
            self.feature_checks[feature_id] = check
            layout.addWidget(check)
        layout.addStretch(1)
        return tab

    def _build_prices_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.price_overlay_enabled = QCheckBox("显示置顶价格浮窗")
        self.require_tarkov_foreground = QCheckBox("截图前要求 Tarkov 是前台窗口")
        self.require_inventory_check = QCheckBox("查价前先检测背包/详情界面")
        self.refresh_prices_on_startup = QCheckBox(
            "启动时检查价格更新（ETag，变化时才下载）"
        )
        self.smart_price_enabled = QCheckBox("启用智能挂价建议")
        self.price_overlay_seconds = QSpinBox()
        self.price_overlay_seconds.setRange(1, 120)
        self.price_overlay_seconds.setSuffix(" 秒")
        self.price_game_mode_default = QComboBox()
        for label, mode in GAME_MODE_CHOICES:
            self.price_game_mode_default.addItem(label, mode)
        self.flea_intelligence_center_level = QComboBox()
        self.flea_intelligence_center_level.addItem("0 级 / 未建造", 0)
        self.flea_intelligence_center_level.addItem("1 级", 1)
        self.flea_intelligence_center_level.addItem("2 级", 2)
        self.flea_intelligence_center_level.addItem("3 级（启用手续费折扣）", 3)
        self.flea_hideout_management_level = QSpinBox()
        self.flea_hideout_management_level.setRange(0, 50)
        self.flea_hideout_management_level.setSuffix(" 级")

        display_group = QGroupBox("结果显示")
        display_layout = QFormLayout(display_group)
        display_layout.addRow("默认价格模式", self.price_game_mode_default)
        display_layout.addRow(self.price_overlay_enabled)
        display_layout.addRow("浮窗显示时间", self.price_overlay_seconds)
        layout.addWidget(display_group)

        fee_group = QGroupBox("跳蚤手续费与净收益")
        fee_layout = QFormLayout(fee_group)
        fee_layout.addRow("情报中心等级", self.flea_intelligence_center_level)
        fee_layout.addRow("藏身处管理技能", self.flea_hideout_management_level)
        fee_note = QLabel(
            "按 Tarkov 1.1 的 5% + 5% 非线性公式计算；情报中心 3 级提供 30% "
            "折扣，藏身处管理每级再增加 0.3 个百分点。"
        )
        fee_note.setWordWrap(True)
        fee_layout.addRow(fee_note)
        layout.addWidget(fee_group)

        safety_group = QGroupBox("识别保护")
        safety_layout = QVBoxLayout(safety_group)
        safety_layout.addWidget(self.require_tarkov_foreground)
        safety_layout.addWidget(self.require_inventory_check)
        layout.addWidget(safety_group)

        data_group = QGroupBox("价格数据")
        data_layout = QVBoxLayout(data_group)
        data_layout.addWidget(self.refresh_prices_on_startup)
        data_layout.addWidget(self.smart_price_enabled)
        smart_price_note = QLabel(
            "关闭时直接使用本地缓存的API最近低价作为建议挂单价；开启后会先显示该结果，"
            "再按当前物品异步读取近期历史并更新建议挂单价，不会批量预取。"
        )
        smart_price_note.setWordWrap(True)
        data_layout.addWidget(smart_price_note)
        layout.addWidget(data_group)
        layout.addStretch(1)
        return tab

    def _build_notifications_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.lead_seconds = QSpinBox()
        self.lead_seconds.setRange(0, 3600)
        self.lead_seconds.setSuffix(" 秒")
        self.repeat_seconds = QSpinBox()
        self.repeat_seconds.setRange(0, 3600)
        self.repeat_seconds.setSuffix(" 秒")
        self.feedback_overlay_seconds = QSpinBox()
        self.feedback_overlay_seconds.setRange(1, 120)
        self.feedback_overlay_seconds.setSuffix(" 秒")
        self.sound_enabled = QCheckBox("声音")
        self.popup_enabled = QCheckBox("提醒触发时自动显示倒计时悬浮窗")
        self.raid_panel_opacity = QSpinBox()
        self.raid_panel_opacity.setRange(55, 100)
        self.raid_panel_opacity.setSuffix(" %")
        self.raid_log_opacity = QSpinBox()
        self.raid_log_opacity.setRange(45, 100)
        self.raid_log_opacity.setSuffix(" %")
        self.raid_log_max_lines = QSpinBox()
        self.raid_log_max_lines.setRange(20, 2000)
        self.raid_log_max_lines.setSuffix(" 行")

        reminder_group = QGroupBox("商人补货提醒")
        reminder_layout = QFormLayout(reminder_group)
        reminder_layout.addRow("提前提醒", self.lead_seconds)
        reminder_layout.addRow("重复提醒间隔", self.repeat_seconds)
        reminder_layout.addRow(self.sound_enabled)
        reminder_layout.addRow(self.popup_enabled)
        reminder_note = QLabel(
            "主界面按钮或对应热键可随时显示全部活动倒计时。若用户主动隐藏，"
            "后续提醒只更新状态和声音，不会强行重新打开悬浮窗。"
        )
        reminder_note.setWordWrap(True)
        reminder_layout.addRow(reminder_note)
        layout.addWidget(reminder_group)

        feedback_group = QGroupBox("通用操作提示")
        feedback_layout = QFormLayout(feedback_group)
        feedback_layout.addRow("显示时间", self.feedback_overlay_seconds)
        layout.addWidget(feedback_group)

        overlay_group = QGroupBox("局内控制与日志")
        overlay_layout = QFormLayout(overlay_group)
        overlay_layout.addRow("右上控制窗透明度", self.raid_panel_opacity)
        overlay_layout.addRow("左下日志窗透明度", self.raid_log_opacity)
        overlay_layout.addRow("日志保留行数", self.raid_log_max_lines)
        note = QLabel(
            "控制窗会接收键盘和鼠标；日志窗显示时不主动抢焦点，点击后可滚动和拖动。"
        )
        note.setWordWrap(True)
        overlay_layout.addRow(note)
        layout.addWidget(overlay_group)
        layout.addStretch(1)
        return tab

    def _build_advanced_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        intro = QLabel(
            "这些选项主要用于兼容特殊设备、控制网络行为或排查识别问题。"
            "正常使用建议保持默认值。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.advanced_tabs = QTabWidget()
        self.advanced_tabs.addTab(self._build_performance_tab(), "性能与诊断")
        self.advanced_tabs.addTab(self._build_capture_tab(), "截图与识别")
        self.advanced_tabs.addTab(self._build_display_filter_safety_tab(), "画面增强")
        layout.addWidget(self.advanced_tabs)
        return tab

    def _build_performance_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.performance_mode_enabled = QCheckBox("性能模式：限制后台任务并在非游戏时定期整理内存")
        self.performance_ocr_threads = QComboBox()
        self.performance_ocr_threads.addItem("低占用（1 线程）", 1)
        self.performance_ocr_threads.addItem("推荐（2 线程）", 2)
        self.performance_ocr_threads.addItem("快速（4 线程）", 4)
        self.performance_price_timing_logs = QCheckBox("在运行日志中记录查价分阶段耗时")
        self.performance_skip_auto_price_refresh = QCheckBox(
            "性能模式下仅在价格缓存过期时检查更新"
        )
        self.performance_log_max_lines = QSpinBox()
        self.performance_log_max_lines.setRange(100, 5000)
        self.performance_log_max_lines.setSuffix(" 行")
        self.performance_cleanup_interval_seconds = QSpinBox()
        self.performance_cleanup_interval_seconds.setRange(15, 600)
        self.performance_cleanup_interval_seconds.setSuffix(" 秒")
        self.performance_max_concurrent_workers = QSpinBox()
        self.performance_max_concurrent_workers.setRange(1, 4)
        self.price_cache_stale_hours = QSpinBox()
        self.price_cache_stale_hours.setRange(1, 168)
        self.price_cache_stale_hours.setSuffix(" 小时")

        resource_group = QGroupBox("资源占用")
        resource_layout = QFormLayout(resource_group)
        resource_layout.addRow(self.performance_mode_enabled)
        resource_layout.addRow("OCR CPU 占用", self.performance_ocr_threads)
        resource_layout.addRow("后台任务并发上限", self.performance_max_concurrent_workers)
        resource_layout.addRow("空闲清理间隔", self.performance_cleanup_interval_seconds)
        layout.addWidget(resource_group)

        data_group = QGroupBox("数据与网络")
        data_layout = QFormLayout(data_group)
        data_layout.addRow(self.performance_skip_auto_price_refresh)
        data_layout.addRow("缓存过期阈值", self.price_cache_stale_hours)
        layout.addWidget(data_group)

        diagnostics_group = QGroupBox("诊断日志")
        diagnostics_layout = QFormLayout(diagnostics_group)
        diagnostics_layout.addRow(self.performance_price_timing_logs)
        diagnostics_layout.addRow("可见日志最多行数", self.performance_log_max_lines)
        layout.addWidget(diagnostics_group)
        layout.addStretch(1)
        return tab

    def _build_display_filter_safety_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.display_filter_restore_on_exit = QCheckBox(
            "退出软件时关闭画面增强并恢复原始画面"
        )
        self.display_filter_eye_care_enabled = QCheckBox(
            "离开 Tarkov 和本助手后自动关闭画面增强"
        )
        self.display_filter_eye_care_check_seconds = QSpinBox()
        self.display_filter_eye_care_check_seconds.setRange(1, 30)
        self.display_filter_eye_care_check_seconds.setSuffix(" 秒")

        safety_group = QGroupBox("自动恢复")
        safety_layout = QFormLayout(safety_group)
        safety_layout.addRow(self.display_filter_restore_on_exit)
        safety_layout.addRow(self.display_filter_eye_care_enabled)
        safety_layout.addRow("状态检测间隔", self.display_filter_eye_care_check_seconds)
        layout.addWidget(safety_group)
        note = QLabel(
            "只有启用“画面增强 / Gamma”模块时这些选项才会生效；保留自动恢复可以"
            "避免退出或切换应用后继续沿用游戏内亮度。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return tab

    def _build_roi_fields(self, fields: list[QSpinBox]) -> QWidget:
        return self._build_number_fields(fields, ["x0", "y0", "x1", "y1"], 0, 10000)

    def _build_number_fields(
        self,
        fields: list[QSpinBox],
        labels: list[str],
        minimum: int,
        maximum: int,
    ) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        for label in labels:
            spin = QSpinBox()
            spin.setRange(minimum, maximum)
            fields.append(spin)
            layout.addWidget(QLabel(label))
            layout.addWidget(spin)
        return widget

    def _load(self) -> None:
        capture_index = self.capture_mode.findData(str(self._config.get("capture_mode", "Auto")))
        self.capture_mode.setCurrentIndex(max(0, capture_index))
        item_capture_index = self.item_capture_mode.findData(
            str(self._config.get("item_capture_mode", "Hover tooltip"))
        )
        self.item_capture_mode.setCurrentIndex(max(0, item_capture_index))
        self.manual_resolution.setChecked(bool(self._config.get("manual_resolution_enabled", False)))
        self.manual_width.setValue(int(self._config.get("manual_width", 2048)))
        self.manual_height.setValue(int(self._config.get("manual_height", 1152)))
        self.hover_wait_ms.setValue(int(self._config.get("hover_wait_ms", 0)))

        for spin, value in zip(self.roi_fields, self._config.get("roi_base", [0, 150, 1500, 240])):
            spin.setValue(int(value))
        for spin, value in zip(
            self.item_roi_fields,
            self._config.get("item_roi_base", [670, 120, 1420, 260]),
        ):
            spin.setValue(int(value))
        for spin, value in zip(
            self.inventory_tab_roi_fields,
            self._config.get("inventory_tab_roi_base", [105, 0, 235, 48]),
        ):
            spin.setValue(int(value))
        for spin, value in zip(
            self.hover_offset_fields,
            self._config.get("hover_tooltip_offset", [12, -60]),
        ):
            spin.setValue(int(value))
        for spin, value in zip(
            self.hover_size_fields,
            self._config.get("hover_tooltip_size", [360, 110]),
        ):
            spin.setValue(int(value))
        for spin, value in zip(
            self.hover_search_margin_fields,
            self._config.get("hover_search_margins", [560, 560, 240, 45]),
        ):
            spin.setValue(int(value))
        for spin, value in zip(
            self.hover_name_padding_fields,
            self._config.get("hover_name_padding", [10, 8, 10, 8]),
        ):
            spin.setValue(int(value))

        self.capture_hotkey.setText(str(self._config.get("capture_hotkey", "F8")))
        self.item_lookup_hotkey.setText(str(self._config.get("item_lookup_hotkey", "Q")))
        self.hideout_scan_hotkey.setText(str(self._config.get("hideout_scan_hotkey", "F6")))
        self.reminder_hold_hotkey.setText(str(self._config.get("reminder_hold_hotkey", "F7")))
        self.raid_panel_hotkey.setText(str(self._config.get("raid_panel_hotkey", "F9")))
        self.raid_log_hotkey.setText(str(self._config.get("raid_log_hotkey", "F10")))
        self.display_filter_restore_hotkey.setText(
            str(self._config.get("display_filter_restore_hotkey", "Ctrl+F9"))
        )
        enabled_features = self._config.get("enabled_features", DEFAULT_ENABLED_FEATURES)
        if not isinstance(enabled_features, list):
            enabled_features = DEFAULT_ENABLED_FEATURES
        enabled_set = {str(item) for item in enabled_features}
        for feature_id, check in self.feature_checks.items():
            check.setChecked(feature_id in enabled_set)
        self.display_filter_restore_on_exit.setChecked(
            bool(self._config.get("display_filter_restore_on_exit", True))
        )
        self.display_filter_eye_care_enabled.setChecked(
            bool(self._config.get("display_filter_eye_care_enabled", True))
        )
        self.display_filter_eye_care_check_seconds.setValue(
            int(self._config.get("display_filter_eye_care_check_seconds", 2))
        )

        self.price_overlay_enabled.setChecked(bool(self._config.get("price_overlay_enabled", True)))
        self.close_to_tray.setChecked(bool(self._config.get("close_to_tray", True)))
        self.require_tarkov_foreground.setChecked(
            bool(self._config.get("require_tarkov_foreground", True))
        )
        self.require_inventory_check.setChecked(bool(self._config.get("require_inventory_check", True)))
        self.refresh_prices_on_startup.setChecked(
            bool(self._config.get("refresh_prices_on_startup", True))
        )
        self.smart_price_enabled.setChecked(
            bool(self._config.get("smart_price_enabled", False))
        )
        self.price_cache_stale_hours.setValue(
            _safe_int(self._config.get("price_cache_stale_hours")) or 24
        )
        self.price_overlay_seconds.setValue(int(self._config.get("price_overlay_seconds", 10)))
        theme_index = self.ui_theme.findData(str(self._config.get("ui_theme", "light")))
        self.ui_theme.setCurrentIndex(max(0, theme_index))
        self.ui_font_size.setValue(_safe_int(self._config.get("ui_font_size")) or 11)
        display_language_index = self.item_display_language.findData(
            str(self._config.get("item_display_language", "zh"))
        )
        self.item_display_language.setCurrentIndex(max(0, display_language_index))
        game_mode_index = self.price_game_mode_default.findData(
            str(self._config.get("price_game_mode_default", "pve"))
        )
        self.price_game_mode_default.setCurrentIndex(max(0, game_mode_index))
        intelligence_center_level = (
            _safe_int(self._config.get("flea_intelligence_center_level")) or 0
        )
        intelligence_center_level = max(0, min(3, intelligence_center_level))
        self.flea_intelligence_center_level.setCurrentIndex(
            max(0, self.flea_intelligence_center_level.findData(intelligence_center_level))
        )
        self.flea_hideout_management_level.setValue(
            max(
                0,
                min(
                    50,
                    _safe_int(self._config.get("flea_hideout_management_level")) or 0,
                ),
            )
        )

        self.lead_seconds.setValue(int(self._config.get("lead_time_seconds", 10)))
        self.repeat_seconds.setValue(int(self._config.get("repeat_alert_seconds", 0)))
        self.feedback_overlay_seconds.setValue(int(self._config.get("feedback_overlay_seconds", 6)))
        self.sound_enabled.setChecked(bool(self._config.get("sound_enabled", True)))
        self.popup_enabled.setChecked(bool(self._config.get("popup_enabled", True)))
        self.raid_panel_opacity.setValue(int(self._config.get("raid_panel_opacity", 84)))
        self.raid_log_opacity.setValue(int(self._config.get("raid_log_opacity", 72)))
        self.raid_log_max_lines.setValue(int(self._config.get("raid_log_max_lines", 200)))
        self.performance_mode_enabled.setChecked(
            bool(self._config.get("performance_mode_enabled", True))
        )
        ocr_threads_index = self.performance_ocr_threads.findData(
            _safe_int(self._config.get("performance_ocr_threads")) or 2
        )
        self.performance_ocr_threads.setCurrentIndex(max(0, ocr_threads_index))
        self.performance_price_timing_logs.setChecked(
            bool(self._config.get("performance_price_timing_logs", True))
        )
        self.performance_skip_auto_price_refresh.setChecked(
            bool(self._config.get("performance_skip_auto_price_refresh", True))
        )
        self.performance_log_max_lines.setValue(
            int(self._config.get("performance_log_max_lines", 600))
        )
        self.performance_cleanup_interval_seconds.setValue(
            int(self._config.get("performance_cleanup_interval_seconds", 60))
        )
        self.performance_max_concurrent_workers.setValue(
            int(self._config.get("performance_max_concurrent_workers", 2))
        )

    def values(self) -> dict[str, object]:
        return {
            "capture_hotkey": self.capture_hotkey.text().strip(),
            "item_lookup_hotkey": self.item_lookup_hotkey.text().strip(),
            "hideout_scan_hotkey": self.hideout_scan_hotkey.text().strip(),
            "reminder_hold_hotkey": self.reminder_hold_hotkey.text().strip(),
            "raid_panel_hotkey": self.raid_panel_hotkey.text().strip(),
            "raid_log_hotkey": self.raid_log_hotkey.text().strip(),
            "display_filter_restore_hotkey": self.display_filter_restore_hotkey.text().strip(),
            "display_filter_presets": self._config.get("display_filter_presets", []),
            "enabled_features": [
                feature_id for feature_id, check in self.feature_checks.items() if check.isChecked()
            ],
            "feature_setup_complete": True,
            "display_filter_restore_on_exit": self.display_filter_restore_on_exit.isChecked(),
            "display_filter_eye_care_enabled": self.display_filter_eye_care_enabled.isChecked(),
            "display_filter_eye_care_check_seconds": (
                self.display_filter_eye_care_check_seconds.value()
            ),
            "capture_mode": self.capture_mode.currentData() or "Auto",
            "item_capture_mode": self.item_capture_mode.currentData() or "Hover tooltip",
            "manual_resolution_enabled": self.manual_resolution.isChecked(),
            "manual_width": self.manual_width.value(),
            "manual_height": self.manual_height.value(),
            "roi_base": [spin.value() for spin in self.roi_fields],
            "item_roi_base": [spin.value() for spin in self.item_roi_fields],
            "inventory_tab_roi_base": [spin.value() for spin in self.inventory_tab_roi_fields],
            "hover_tooltip_offset": [spin.value() for spin in self.hover_offset_fields],
            "hover_tooltip_size": [spin.value() for spin in self.hover_size_fields],
            "hover_search_margins": [spin.value() for spin in self.hover_search_margin_fields],
            "hover_name_padding": [spin.value() for spin in self.hover_name_padding_fields],
            "hover_wait_ms": self.hover_wait_ms.value(),
            "price_overlay_enabled": self.price_overlay_enabled.isChecked(),
            "price_overlay_seconds": self.price_overlay_seconds.value(),
            "close_to_tray": self.close_to_tray.isChecked(),
            "ui_theme": self.ui_theme.currentData() or "light",
            "ui_font_size": self.ui_font_size.value(),
            "item_display_language": self.item_display_language.currentData() or "zh",
            "require_tarkov_foreground": self.require_tarkov_foreground.isChecked(),
            "require_inventory_check": self.require_inventory_check.isChecked(),
            "refresh_prices_on_startup": self.refresh_prices_on_startup.isChecked(),
            "smart_price_enabled": self.smart_price_enabled.isChecked(),
            "price_cache_stale_hours": self.price_cache_stale_hours.value(),
            "price_game_mode_default": self.price_game_mode_default.currentData() or "pve",
            "flea_intelligence_center_level": (
                self.flea_intelligence_center_level.currentData() or 0
            ),
            "flea_hideout_management_level": self.flea_hideout_management_level.value(),
            "lead_time_seconds": self.lead_seconds.value(),
            "repeat_alert_seconds": self.repeat_seconds.value(),
            "feedback_overlay_seconds": self.feedback_overlay_seconds.value(),
            "sound_enabled": self.sound_enabled.isChecked(),
            "popup_enabled": self.popup_enabled.isChecked(),
            "raid_panel_opacity": self.raid_panel_opacity.value(),
            "raid_log_opacity": self.raid_log_opacity.value(),
            "raid_log_max_lines": self.raid_log_max_lines.value(),
            "performance_mode_enabled": self.performance_mode_enabled.isChecked(),
            "performance_ocr_threads": self.performance_ocr_threads.currentData() or 2,
            "performance_price_timing_logs": (
                self.performance_price_timing_logs.isChecked()
            ),
            "performance_skip_auto_price_refresh": (
                self.performance_skip_auto_price_refresh.isChecked()
            ),
            "performance_log_max_lines": self.performance_log_max_lines.value(),
            "performance_cleanup_interval_seconds": (
                self.performance_cleanup_interval_seconds.value()
            ),
            "performance_max_concurrent_workers": self.performance_max_concurrent_workers.value(),
        }

    def _apply_resolution_preset(self, value: str) -> None:
        try:
            width, height = value.split("x", 1)
            self.manual_width.setValue(int(width))
            self.manual_height.setValue(int(height))
        except ValueError:
            return


def _centered(widget: QWidget) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget)
    layout.setAlignment(widget, Qt.AlignmentFlag.AlignCenter)
    return container


def _load_app_icon(widget: QWidget) -> QIcon:
    for name in ("app_icon.ico", "app_icon.png"):
        path = RESOURCE_DIR / "assets" / name
        if path.exists():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return widget.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)


@dataclass(frozen=True)
class PriceView:
    title: str
    subtitle: str
    detail: str
    value_text: str
    secondary_value_text: str
    tier_label: str
    tier_color: str
    tier_accent: str
    label_html: str
    log_text: str
    toast_key: str = ""
    recipe_notices: tuple[RecipeNotice, ...] = ()
    recipe_accent_color: str = "#E8C47A"
    card_border_color: str = ""


@dataclass(frozen=True)
class ReminderView:
    title: str
    value_text: str
    detail: str
    accent_color: str = "#F2C14E"


def _recipe_product_name(record: dict[str, object]) -> str:
    product = record.get("product")
    if not isinstance(product, dict):
        return "未知产物"
    return str(product.get("name") or product.get("short_name") or "未知产物")


def _recipe_product_count_text(record: dict[str, object]) -> str:
    product = record.get("product")
    value = product.get("count") if isinstance(product, dict) else None
    try:
        count = float(value)
    except (TypeError, ValueError):
        return "产出 ×?"
    count_text = f"{int(count):,}" if count.is_integer() else f"{count:,.2f}".rstrip("0").rstrip(".")
    return f"产出 ×{count_text}"


def _build_ammo_price_view(
    price: object,
    display_language: str,
    toast_key: str,
) -> PriceView:
    properties = getattr(price, "ammo_properties", None)
    if not isinstance(properties, dict):
        raise ValueError("Ammo price view requires ItemPropertiesAmmo data.")
    title = _display_item_name(price, display_language)
    damage = _safe_int(properties.get("damage"))
    penetration = _safe_int(properties.get("penetrationPower"))
    projectile_count = _safe_int(properties.get("projectileCount")) or 1
    damage_text = str(damage) if damage is not None else "-"
    if projectile_count > 1:
        damage_text = f"{damage_text} × {projectile_count}"
    value_text = f"伤害 {damage_text} · 穿深 {penetration if penetration is not None else '-'}"

    armor_damage = _safe_int(properties.get("armorDamage"))
    speed = _safe_int(properties.get("initialSpeed"))
    secondary_parts = [
        f"甲伤 {armor_damage}%" if armor_damage is not None else "甲伤 -",
        f"初速 {speed} m/s" if speed is not None else "初速 -",
    ]
    pack_count = _safe_int(getattr(price, "ammo_pack_count", None))
    if pack_count is not None:
        ammo_name = (
            str(getattr(price, "ammo_zh_name", "") or "")
            if display_language.casefold() == "zh"
            else str(getattr(price, "ammo_name", "") or "")
        )
        secondary_parts.insert(0, f"内含 {pack_count} 发 {ammo_name}".strip())
    secondary_value_text = " · ".join(secondary_parts)

    detail_parts: list[str] = []
    recoil = _safe_float(properties.get("recoilModifier"))
    accuracy = _safe_float(properties.get("accuracyModifier"))
    if recoil:
        detail_parts.append(f"后座 {recoil * 100:+.0f}%")
    if accuracy:
        detail_parts.append(f"精度 {accuracy * 100:+.0f}%")
    if bool(properties.get("tracer")):
        tracer_color = str(properties.get("tracerColor") or "").strip()
        detail_parts.append(f"曳光弹{f'（{tracer_color}）' if tracer_color else ''}")
    detail = " · ".join(detail_parts) or "无后座或精度修正"

    tier_label, tier_color, tier_accent = _ammo_penetration_tier(penetration)
    label_html = (
        f"<div style='line-height:1.35;'>"
        f"<b>{html.escape(title)}</b><br>"
        f"<span style='color:{tier_color}; font-size:18px; font-weight:800;'>"
        f"{html.escape(value_text)}</span><br>"
        f"<span style='color:{tier_color}; font-size:14px; font-weight:700;'>"
        f"{html.escape(secondary_value_text)}</span><br>"
        f"<span>{html.escape(detail)}</span>"
        f"</div>"
    )
    return PriceView(
        title=title,
        subtitle="",
        detail=detail,
        value_text=value_text,
        secondary_value_text=secondary_value_text,
        tier_label=tier_label,
        tier_color=tier_color,
        tier_accent=tier_accent,
        label_html=label_html,
        log_text=f"{title} | {value_text} | {secondary_value_text} | {detail}",
        toast_key=toast_key,
        card_border_color=tier_color,
    )


def _ammo_penetration_tier(penetration: int | None) -> tuple[str, str, str]:
    colors = {
        1: "#F5F7FA",
        2: "#57D37C",
        3: "#4DA3FF",
        4: "#B47CFF",
        5: "#F2C14E",
        6: "#FF5D5D",
    }
    if penetration is None:
        return "穿透未知", "#D8D8D8", "#D8D8D8"
    if penetration >= 70:
        return (
            "特殊穿透",
            "#FF7AE7",
            "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF3B5C, "
            "stop:0.2 #FFB000, stop:0.4 #45D483, stop:0.6 #46B7FF, "
            "stop:0.8 #9B72FF, stop:1 #FF4FD8)",
        )
    armor_class = max(1, min(6, penetration // 10))
    color = colors[armor_class]
    return f"穿透 {armor_class} 级", color, color


def _build_price_view(
    price: object,
    display_language: str,
    tiers: list[object],
    value_basis: str,
    firearm_color: str = "#00D1D1",
    firearm_accent: str = "#00D1D1",
    hideout_lines: list[str] | None = None,
    flea_intelligence_center_level: int = 0,
    flea_hideout_management_level: int = 0,
    recipe_notices: list[RecipeNotice] | None = None,
    recipe_accent_color: str = "#E8C47A",
    smart_estimate: SmartPriceEstimate | object | None = None,
    smart_pending: bool = False,
    toast_key: str = "",
) -> PriceView:
    if isinstance(getattr(price, "ammo_properties", None), dict):
        return _build_ammo_price_view(price, display_language, toast_key)
    game_mode = _game_mode_label(str(getattr(price, "game_mode", "regular")))
    title = f"{_display_item_name(price, display_language)} · {game_mode}"
    vendor_name = getattr(price, "best_vendor_name", None)
    vendor_currency = getattr(price, "best_vendor_currency", "RUB")
    vendor_price = _money(_safe_int(getattr(price, "best_vendor_price", None)), vendor_currency)
    vendor = f"{vendor_name}: {vendor_price}" if vendor_name else vendor_price
    slots = _safe_int(getattr(price, "slots", None))
    avg_value = _safe_int(getattr(price, "avg_24h_price", None))
    last_low = _safe_int(getattr(price, "last_low_price", None))
    offer_count = _safe_int(getattr(price, "last_offer_count", None))
    fast_estimate = build_fast_price_estimate(last_low, avg_value, offer_count)
    fallback_listing_price = last_low if last_low is not None else avg_value

    def flea_values(listing_price: int | None) -> tuple[int | None, int | None]:
        fee = calculate_flea_market_fee(
            getattr(price, "base_price", None),
            listing_price,
            intelligence_center_level=flea_intelligence_center_level,
            hideout_management_level=flea_hideout_management_level,
        )
        net = (
            listing_price - fee
            if listing_price is not None and fee is not None
            else None
        )
        return fee, net

    vendor_rub = _safe_int(getattr(price, "best_vendor_price_rub", None))
    _last_low_fee, last_low_net = flea_values(last_low)
    _avg_fee, avg_net = flea_values(avg_value)
    has_market_reference = last_low is not None or avg_value is not None
    if has_market_reference and last_low_net is None and avg_net is None:
        # A gross market price is not comparable to a trader's guaranteed RUB
        # return when the fee inputs are unavailable.
        sale_region = classify_sale_region(None, None, None)
    else:
        sale_region = classify_sale_region(
            last_low_net,
            avg_net,
            vendor_rub,
        )
    conservative_values = [
        value
        for value in (sale_region.flea_lower_net, vendor_rub)
        if value is not None
    ]
    conservative_total_value = max(conservative_values) if conservative_values else None
    conservative_value_per_slot = _slot_value(conservative_total_value, slots)
    is_firearm = bool(getattr(price, "is_firearm", False))

    if is_firearm:
        tier_label = "枪械"
        tier_color = _safe_color(firearm_color, "#00D1D1")
        tier_accent = _safe_accent(firearm_accent, tier_color)
    else:
        value_for_tier = (
            conservative_value_per_slot
            if value_basis == "slot"
            else conservative_total_value
        )
        if value_for_tier is None and value_basis == "slot":
            value_for_tier = conservative_total_value
        tier_label, tier_color, tier_accent = _price_tier(value_for_tier, tiers)

    smart_price = _safe_int(getattr(smart_estimate, "suggested_price", None))
    smart_confidence = str(getattr(smart_estimate, "confidence", "low") or "low")
    smart_requested = smart_pending or smart_estimate is not None
    smart_usable = smart_requested and smart_price is not None
    listing_price = smart_price if smart_usable else fallback_listing_price
    flea_fee, flea_net_value = flea_values(listing_price)
    if sale_region.region == "flea":
        value_text = "跳蚤更优"
    elif sale_region.region == "trader":
        value_text = f"商人更优 · {vendor_name or '商人'}"
    elif sale_region.region == "close":
        value_text = "收益接近"
    else:
        value_text = "出售判断数据不足"

    if listing_price is not None and flea_net_value is not None:
        secondary_value_text = (
            f"建议挂 {_money(listing_price, 'RUB')} · "
            f"净到手 {_money(flea_net_value, 'RUB')}"
        )
    elif listing_price is not None:
        secondary_value_text = f"建议挂 {_money(listing_price, 'RUB')}"
    else:
        secondary_value_text = "挂价与净收益数据不足"

    detail_lines: list[str] = []
    detail_lines.append(
        f"API最近低价 {_money(last_low, 'RUB')} · "
        f"24h均价 {_money(avg_value, 'RUB')}"
    )

    if sale_region.region == "trader" and vendor_rub is not None:
        detail_lines.append(
            f"{vendor_name or '商人'}收购 {_money(vendor_rub, 'RUB')}"
        )
    elif sale_region.region == "close" and vendor_rub is not None:
        detail_lines.append(
            f"{vendor_name or '商人'}收购 {_money(vendor_rub, 'RUB')}"
        )
    elif sale_region.region == "unknown" and vendor_rub is not None:
        detail_lines.append(
            f"{vendor_name or '商人'}收购 {_money(vendor_rub, 'RUB')}"
        )

    smart_confidence_label = {"high": "高", "medium": "中", "low": "低"}.get(
        smart_confidence,
        "低",
    )
    metadata_parts: list[str] = []
    if smart_usable:
        metadata_parts.append(f"智能可信度 {smart_confidence_label}")
    elif smart_pending:
        metadata_parts.append("智能分析中…")
    sample_age = _format_api_sample_age(getattr(price, "updated", None))
    if sample_age:
        metadata_parts.append(sample_age)
    if metadata_parts:
        detail_lines.append(" · ".join(metadata_parts))

    risk_parts: list[str] = []
    if listing_price is not None and flea_fee is None:
        risk_parts.append("手续费数据不足，无法准确估算跳蚤净收益")
    elif not has_market_reference:
        risk_parts.append("跳蚤市场参考缺失，无法比较出售渠道")
    if vendor_rub is None:
        risk_parts.append("商人收购价缺失，无法比较出售渠道")
    if fast_estimate.risk_notice:
        risk_parts.append(fast_estimate.risk_notice)
    smart_risk = str(getattr(smart_estimate, "risk_notice", "") or "")
    if smart_risk and smart_risk not in risk_parts:
        risk_parts.append(smart_risk)
    if risk_parts:
        detail_lines.append("风险：" + "；".join(risk_parts[:2]))
    detail = "\n".join(detail_lines)

    hideout_text = "；".join(hideout_lines or [])
    display_detail = detail
    hideout_html = ""
    if hideout_text:
        display_detail = f"{detail}\n藏身处: {hideout_text}"
        hideout_html = (
            f"<br><span style='color:#9EE6A8;'>"
            f"藏身处: {html.escape(hideout_text)}"
            f"</span>"
        )
    safe_recipe_color = _safe_color(recipe_accent_color, "#E8C47A")
    notices = tuple(recipe_notices or [])
    recipe_html = ""
    if notices:
        visible_notices = notices[:MAX_VISIBLE_RECIPE_NOTICES]
        notice_rows = "<div style='height:5px;'></div>".join(
            f"<div style='margin-top:4px;'>"
            f"<span style='color:#9AA5B2;'>可用于</span> "
            f"<span style='color:#FBFAF4; font-size:14px; font-weight:800;'>"
            f"{html.escape(notice.product_text)}</span><br>"
            f"<span style='color:#9AA5B2;'>需要</span> "
            f"<span style='color:{safe_recipe_color}; font-weight:800;'>"
            f"{html.escape(_recipe_material_text(notice))}</span> · "
            f"<span style='color:#AEB7C2;'>{html.escape(notice.source_text)}</span>"
            f"</div>"
            for notice in visible_notices
        )
        remaining = len(notices) - len(visible_notices)
        if remaining > 0:
            notice_rows += (
                f"<div style='height:5px;'></div>"
                f"<div style='color:#AEB7C2;'>另有 {remaining} 个关注用途</div>"
            )
        recipe_background = _blend_hex_color(safe_recipe_color, "#080A0D", 0.22)
        recipe_html = (
            f"<div style='margin-top:8px; padding:7px 9px; "
            f"background-color:{recipe_background}; border-radius:6px;'>"
            f"<span style='color:{safe_recipe_color}; font-weight:800;'>"
            f"★ 关注用途物品 · {len(notices)}</span><br>{notice_rows}</div>"
        )
    detail_html = "<br>".join(html.escape(line) for line in detail.splitlines())
    label_html = (
        f"<div style='line-height:1.35;'>"
        f"<b>{html.escape(title)}</b><br>"
        f"<span style='color:{tier_color}; font-size:18px; font-weight:800;'>{html.escape(value_text)}</span><br>"
        f"<span style='color:{tier_color}; font-size:14px; font-weight:700;'>{html.escape(secondary_value_text)}</span><br>"
        f"{recipe_html}"
        f"<span>{detail_html}</span>"
        f"{hideout_html}"
        f"</div>"
    )
    log_text = f"{title} | {value_text} | {secondary_value_text} | 商人 {vendor}"
    if smart_pending:
        log_text = f"{log_text} | 智能挂价分析中"
    if hideout_text:
        log_text = f"{log_text} | 藏身处 {hideout_text}"
    if notices:
        log_text = (
            f"{log_text} | 关注用途 "
            + "；".join(notice.compact_text for notice in notices)
        )
    return PriceView(
        title=title,
        subtitle="",
        detail=display_detail,
        value_text=value_text,
        secondary_value_text=secondary_value_text,
        tier_label=tier_label,
        tier_color=tier_color,
        tier_accent=tier_accent,
        label_html=label_html,
        log_text=log_text,
        toast_key=toast_key,
        recipe_notices=notices,
        recipe_accent_color=safe_recipe_color,
        card_border_color=tier_color,
    )

def _display_item_name(price: object, display_language: str) -> str:
    name = str(getattr(price, "name", "") or "")
    short_name = str(getattr(price, "short_name", "") or "")
    zh_name = str(getattr(price, "zh_name", "") or "")
    zh_short_name = str(getattr(price, "zh_short_name", "") or "")
    if display_language.casefold() == "zh" and zh_name:
        suffix = short_name or zh_short_name
        return f"{zh_name} ({suffix})" if suffix and suffix != zh_name else zh_name
    return f"{name} ({short_name})" if short_name and short_name != name else name


def _money(value: int | None, currency: str | None = "RUB") -> str:
    if value is None:
        return "-"
    return f"{value:,} {currency or 'RUB'}"


def _format_api_sample_age(value: object, now: float | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        numeric = float(text)
    except ValueError:
        try:
            sampled_at = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return ""
        if sampled_at.tzinfo is None:
            sampled_at = sampled_at.replace(tzinfo=timezone.utc)
        timestamp = sampled_at.timestamp()
    else:
        timestamp = numeric / 1000.0 if numeric > 10_000_000_000 else numeric

    try:
        reference = time.time() if now is None else float(now)
    except (TypeError, ValueError, OverflowError):
        return ""
    if (
        not math.isfinite(timestamp)
        or not math.isfinite(reference)
        or timestamp <= 0
        or timestamp > reference + 86400
    ):
        return ""
    age_seconds = max(0, round(reference - timestamp))
    if age_seconds < 60:
        return "API采样 刚刚"
    if age_seconds < 3600:
        return f"API采样 {age_seconds // 60}分钟前"
    if age_seconds < 86400:
        hours, remainder = divmod(age_seconds, 3600)
        minutes = remainder // 60
        if minutes:
            return f"API采样 {hours}小时{minutes}分钟前"
        return f"API采样 {hours}小时前"
    try:
        sampled_local = datetime.fromtimestamp(timestamp)
    except (OSError, OverflowError, ValueError):
        return ""
    return f"API采样 {sampled_local:%m-%d %H:%M}"


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slot_value(value: int | None, slots: int | None) -> int | None:
    if value is None or slots is None or slots <= 0:
        return None
    return round(value / slots)


def _price_overlay_key(price: object) -> str:
    item_id = str(getattr(price, "item_id", "") or "")
    mode = str(getattr(price, "game_mode", "") or "")
    return f"price:{mode}:{item_id}"


def _safe_color(value: str, fallback: str) -> str:
    if re.match(r"^#[0-9A-Fa-f]{6}$", value):
        return value
    return fallback


def _blend_hex_color(
    foreground: str,
    background: str,
    foreground_ratio: float,
) -> str:
    foreground_color = QColor(_safe_color(foreground, "#E8C47A"))
    background_color = QColor(_safe_color(background, "#080A0D"))
    ratio = max(0.0, min(1.0, float(foreground_ratio)))
    red = round(
        background_color.red() * (1.0 - ratio) + foreground_color.red() * ratio
    )
    green = round(
        background_color.green() * (1.0 - ratio) + foreground_color.green() * ratio
    )
    blue = round(
        background_color.blue() * (1.0 - ratio) + foreground_color.blue() * ratio
    )
    return QColor(red, green, blue).name().upper()


def _recipe_material_text(notice: RecipeNotice | object) -> str:
    material_text = str(getattr(notice, "material_text", "") or "").strip()
    if material_text:
        return material_text
    fallback = str(getattr(notice, "requirement_text", "") or "").strip()
    if fallback.startswith("需求："):
        return fallback.removeprefix("需求：").strip()
    return fallback or "数量未知"


def _safe_accent(value: str, fallback: str) -> str:
    if value.startswith("qlineargradient(") or re.match(r"^#[0-9A-Fa-f]{6}$", value):
        return value
    return fallback


def _price_tier(value: int | None, tiers: list[object]) -> tuple[str, str, str]:
    if value is None:
        return "未知", "#D8D8D8", "#D8D8D8"
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        try:
            minimum = int(tier.get("min", 0) or 0)
        except (TypeError, ValueError):
            minimum = 0
        maximum_raw = tier.get("max")
        try:
            maximum = int(maximum_raw) if maximum_raw is not None else None
        except (TypeError, ValueError):
            maximum = None
        if value < minimum:
            continue
        if maximum is not None and value >= maximum:
            continue
        color = _safe_color(str(tier.get("color") or "#F2F2F2"), "#F2F2F2")
        accent = _safe_accent(str(tier.get("accent") or color), color)
        return str(tier.get("label") or ""), color, accent
    return "未知", "#F2F2F2", "#F2F2F2"


def _game_mode_label(game_mode: str) -> str:
    return game_mode_label(game_mode)


def _region_size_signature(region: Region | None) -> tuple[int, int] | None:
    if region is None:
        return None
    return region.width, region.height


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _interpolate_point(start: QPoint, end: QPoint, fraction: float) -> QPoint:
    value = max(0.0, min(1.0, fraction))
    return QPoint(
        round(start.x() + (end.x() - start.x()) * value),
        round(start.y() + (end.y() - start.y()) * value),
    )


PRICE_CAPTURE_COMPOSITOR_SETTLE_SECONDS = 0.034


def _capture_window_rect(widget: QWidget | object) -> QRect:
    """Return a top-level window rectangle in native capture pixels when possible."""
    try:
        import win32gui  # type: ignore

        left, top, right, bottom = win32gui.GetWindowRect(int(widget.winId()))
        if right > left and bottom > top:
            return QRect(left, top, right - left, bottom - top)
    except Exception:
        pass
    return widget.frameGeometry()


class PriceOverlay(QWidget):
    MAX_VISIBLE_TOASTS = 3
    MOVE_DURATION_MS = 360
    NEW_TOAST_FADE_DELAY_MS = 140
    NEW_TOAST_FADE_MS = 360

    def __init__(self) -> None:
        super().__init__()
        self._toasts: list[PriceToast] = []

    def show_price(self, view: PriceView, seconds: int = 10, replace_key: str = "") -> None:
        if replace_key:
            for toast in self._toasts:
                if toast.toast_key == replace_key:
                    toast.update_view(view)
                    toast.show_for(seconds)
                    self._animate_layout()
                    return
        toast = PriceToast(view)
        toast.closed_callback = lambda item=toast: self._forget_toast(item)
        self._toasts.insert(0, toast)
        overflow: PriceToast | None = None
        if len(self._toasts) > self.MAX_VISIBLE_TOASTS:
            overflow = self._toasts.pop()

        layout_toasts = list(self._toasts)
        if overflow is not None:
            layout_toasts.append(overflow)
        targets = self._toast_targets(layout_toasts)
        if targets:
            for item, target in targets:
                if item is toast:
                    item.move(target)
                elif item is overflow:
                    item.fade_out(self.MOVE_DURATION_MS, move_target=target)
                else:
                    item.animate_to(target, self.MOVE_DURATION_MS)
        toast.show_for(
            seconds,
            fade_in=True,
            fade_delay_ms=self.NEW_TOAST_FADE_DELAY_MS,
            fade_duration_ms=self.NEW_TOAST_FADE_MS,
        )

    def clear_prices(self) -> None:
        toasts = list(self._toasts)
        self._toasts.clear()
        for toast in toasts:
            toast.close()

    @contextmanager
    def capture_guard(self, region: Region) -> Iterator[None]:
        """Briefly remove only toast windows that would cover a screenshot."""
        capture_rect = QRect(region.left, region.top, region.width, region.height)
        hidden = [
            toast
            for toast in self._toasts
            if toast.isVisible() and _capture_window_rect(toast).intersects(capture_rect)
        ]
        for toast in hidden:
            toast.hide()
        if hidden:
            QApplication.processEvents()
            # MSS captures native desktop pixels, while Qt geometry is expressed in
            # device-independent coordinates on a scaled display.  GetWindowRect
            # above keeps the intersection test in native pixels; this short pause
            # then gives DWM enough time to present the hidden window before capture.
            time.sleep(PRICE_CAPTURE_COMPOSITOR_SETTLE_SECONDS)
            QApplication.processEvents()
        try:
            yield
        finally:
            for toast in hidden:
                if toast in self._toasts and not toast._closing:
                    toast.show()
                    toast.raise_()
            if hidden:
                QApplication.processEvents()

    def hide(self) -> None:
        self.clear_prices()
        super().hide()

    def _forget_toast(self, toast: "PriceToast") -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            self._animate_layout()

    def _toast_targets(
        self,
        toasts: list["PriceToast"],
    ) -> list[tuple["PriceToast", QPoint]]:
        screen = QApplication.primaryScreen()
        if screen is None:
            return []
        rect = screen.availableGeometry()
        top = rect.top() + 80
        targets: list[tuple[PriceToast, QPoint]] = []
        for toast in toasts:
            toast.adjustSize()
            target = QPoint(rect.right() - toast.width() - 24, top)
            targets.append((toast, target))
            top += toast.height() + 10
        return targets

    def _animate_layout(self) -> None:
        for toast, target in self._toast_targets(self._toasts):
            toast.animate_to(target, self.MOVE_DURATION_MS)


class PriceToast(QWidget):
    def __init__(self, view: PriceView) -> None:
        super().__init__()
        self.toast_key = view.toast_key
        self.closed_callback: object | None = None
        self._closing = False
        self._opacity_animation: QPropertyAnimation | None = None
        self._position_animation: QSequentialAnimationGroup | None = None
        self._timer_generation = 0
        self.setWindowTitle("塔科夫物品价格")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget()
        card.setObjectName("priceToastCard")
        card.setMinimumWidth(460)
        card.setMaximumWidth(640)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        accent = QWidget()
        accent.setFixedWidth(5)
        accent.setStyleSheet(
            f"background: {view.tier_accent};"
            "border-top-left-radius: 8px;"
            "border-bottom-left-radius: 8px;"
        )
        card_layout.addWidget(accent)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(13, 10, 14, 11)
        content_layout.setSpacing(4)

        self._accent = accent
        self._card = card
        self._title_label = QLabel()
        self._title_label.setWordWrap(True)
        self._value_label = QLabel()
        self._secondary_value_label = QLabel()
        self._detail_label = QLabel()
        self._detail_label.setWordWrap(True)

        self._recipe_box = QFrame()
        self._recipe_box.setObjectName("recipeNoticeBox")
        recipe_layout = QVBoxLayout(self._recipe_box)
        recipe_layout.setContentsMargins(10, 8, 10, 9)
        recipe_layout.setSpacing(5)
        recipe_header = QHBoxLayout()
        recipe_header.setContentsMargins(0, 0, 0, 0)
        recipe_header.setSpacing(8)
        self._recipe_title_label = QLabel("★ 关注用途物品")
        self._recipe_count_label = QLabel("0")
        self._recipe_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        recipe_header.addWidget(self._recipe_title_label)
        recipe_header.addStretch(1)
        recipe_header.addWidget(self._recipe_count_label)
        self._recipe_content_label = QLabel()
        self._recipe_content_label.setWordWrap(True)
        self._recipe_content_label.setTextFormat(Qt.TextFormat.RichText)
        recipe_layout.addLayout(recipe_header)
        recipe_layout.addWidget(self._recipe_content_label)

        content_layout.addWidget(self._title_label)
        content_layout.addWidget(self._value_label)
        content_layout.addWidget(self._secondary_value_label)
        content_layout.addWidget(self._recipe_box)
        content_layout.addWidget(self._detail_label)
        card_layout.addWidget(content, 1)
        outer.addWidget(card)

        self.update_view(view)

    def update_view(self, view: PriceView) -> None:
        self.toast_key = view.toast_key or self.toast_key
        border_color = _safe_color(
            view.card_border_color,
            "rgba(255, 255, 255, 38)",
        )
        self._card.setStyleSheet(
            "QWidget#priceToastCard {"
            "background: rgba(18, 20, 24, 226);"
            f"border: 1px solid {border_color};"
            "border-radius: 8px;"
            "}"
        )
        self._accent.setStyleSheet(
            f"background: {view.tier_accent};"
            "border-top-left-radius: 8px;"
            "border-bottom-left-radius: 8px;"
        )
        self._title_label.setText(view.title)
        self._title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #FBFAF4;")
        self._value_label.setText(view.value_text)
        self._value_label.setStyleSheet(
            f"font-size: 18px; font-weight: 800; color: {view.tier_color};"
        )
        self._secondary_value_label.setText(view.secondary_value_text)
        self._secondary_value_label.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {view.tier_color};"
        )
        self._detail_label.setText(view.detail)
        self._detail_label.setStyleSheet("font-size: 12px; color: rgba(245, 242, 232, 0.68);")
        if view.recipe_notices:
            color = _safe_color(view.recipe_accent_color, "#E8C47A")
            tint = QColor(color)
            self._recipe_box.setStyleSheet(
                "QFrame#recipeNoticeBox {"
                f"background: rgba({tint.red()}, {tint.green()}, {tint.blue()}, 48);"
                "border: none;"
                "border-radius: 6px;"
                "}"
            )
            self._recipe_title_label.setStyleSheet(
                f"font-size: 12px; font-weight: 800; color: {color};"
            )
            self._recipe_count_label.setText(str(len(view.recipe_notices)))
            self._recipe_count_label.setStyleSheet(
                f"font-size: 11px; font-weight: 800; color: #FBFAF4; "
                f"background: rgba({tint.red()}, {tint.green()}, {tint.blue()}, 110); "
                "padding: 1px 6px; border-radius: 7px;"
            )
            visible_notices = view.recipe_notices[:MAX_VISIBLE_RECIPE_NOTICES]
            rows = "<div style='height:7px;'></div>".join(
                f"<div>"
                f"<span style='color:#929CAA;'>可用于</span> "
                f"<span style='font-size:14px; font-weight:800; color:#FBFAF4;'>"
                f"{html.escape(notice.product_text)}</span><br>"
                f"<span style='color:#929CAA;'>需要</span> "
                f"<span style='font-weight:800; color:{color};'>"
                f"{html.escape(_recipe_material_text(notice))}</span> · "
                f"<span style='color:#BFC3C8;'>{html.escape(notice.source_text)}</span>"
                f"</div>"
                for notice in visible_notices
            )
            remaining = len(view.recipe_notices) - len(visible_notices)
            if remaining > 0:
                rows += (
                    "<div style='height:7px;'></div>"
                    f"<div style='color:#BFC3C8;'>另有 {remaining} 个关注用途</div>"
                )
            self._recipe_content_label.setText(rows)
            self._recipe_content_label.setStyleSheet(
                "font-size: 12px; color: rgba(245, 242, 232, 0.90);"
            )
            self._recipe_box.show()
        else:
            self._recipe_count_label.clear()
            self._recipe_content_label.clear()
            self._recipe_box.hide()
        self.adjustSize()

    def show_for(
        self,
        seconds: int,
        *,
        fade_in: bool = False,
        fade_delay_ms: int = 0,
        fade_duration_ms: int = 240,
    ) -> None:
        self._closing = False
        self._timer_generation += 1
        generation = self._timer_generation
        self._stop_opacity_animation()
        self._opacity.setOpacity(0.0 if fade_in else 1.0)
        self.show()
        self.raise_()
        if fade_in:
            delay_ms = max(0, int(fade_delay_ms))
            if delay_ms:
                QTimer.singleShot(
                    delay_ms,
                    lambda: self._fade_in_if_current(generation, fade_duration_ms),
                )
            else:
                self._fade_in_if_current(generation, fade_duration_ms)
        duration_ms = max(1, int(seconds)) * 1000
        QTimer.singleShot(duration_ms, lambda: self._fade_out_if_current(generation))

    def _fade_in_if_current(self, generation: int, duration_ms: int) -> None:
        if generation != self._timer_generation or self._closing:
            return
        self._animate_opacity(
            1.0,
            duration_ms,
            QEasingCurve.Type.InOutCubic,
        )

    def _fade_out_if_current(self, generation: int) -> None:
        if generation == self._timer_generation:
            self.fade_out()

    def animate_to(self, target: QPoint, duration_ms: int = 360) -> None:
        target = QPoint(target)
        start = self.pos()
        if start == target:
            return
        if self._position_animation is not None:
            self._position_animation.stop()

        duration = max(120, int(duration_ms))
        accelerate_ms = max(1, round(duration * 0.25))
        cruise_ms = max(1, round(duration * 0.50))
        decelerate_ms = max(1, duration - accelerate_ms - cruise_ms)
        accelerate_end = _interpolate_point(start, target, 1 / 6)
        cruise_end = _interpolate_point(start, target, 5 / 6)

        group = QSequentialAnimationGroup(self)
        segments = (
            (start, accelerate_end, accelerate_ms, QEasingCurve.Type.InQuad),
            (accelerate_end, cruise_end, cruise_ms, QEasingCurve.Type.Linear),
            (cruise_end, target, decelerate_ms, QEasingCurve.Type.OutQuad),
        )
        for segment_start, segment_end, segment_ms, easing in segments:
            animation = QPropertyAnimation(self, b"pos", group)
            animation.setDuration(segment_ms)
            animation.setStartValue(segment_start)
            animation.setEndValue(segment_end)
            animation.setEasingCurve(easing)
            group.addAnimation(animation)

        self._position_animation = group

        def clear_animation() -> None:
            if self._position_animation is group:
                self._position_animation = None

        group.finished.connect(clear_animation)
        group.start()

    def fade_out(self, duration_ms: int = 450, move_target: QPoint | None = None) -> None:
        if self._closing:
            return
        self._closing = True
        duration = max(80, duration_ms)
        if move_target is not None:
            self.animate_to(move_target, duration)
        self._animate_opacity(
            0.0,
            duration,
            QEasingCurve.Type.InCubic,
            finished=self.close,
        )

    def _animate_opacity(
        self,
        target: float,
        duration_ms: int,
        easing: QEasingCurve.Type,
        *,
        finished: Callable[[], None] | None = None,
    ) -> None:
        self._stop_opacity_animation()
        animation = QPropertyAnimation(self._opacity, b"opacity", self)
        self._opacity_animation = animation
        animation.setDuration(max(80, int(duration_ms)))
        animation.setStartValue(self._opacity.opacity())
        animation.setEndValue(max(0.0, min(1.0, target)))
        animation.setEasingCurve(easing)

        def finish_animation() -> None:
            if self._opacity_animation is animation:
                self._opacity_animation = None
            if finished is not None:
                finished()

        animation.finished.connect(finish_animation)
        animation.start()

    def _stop_opacity_animation(self) -> None:
        if self._opacity_animation is not None:
            self._opacity_animation.stop()
            self._opacity_animation = None

    def closeEvent(self, event: QCloseEvent) -> None:
        self._timer_generation += 1
        self._stop_opacity_animation()
        if self._position_animation is not None:
            self._position_animation.stop()
            self._position_animation = None
        callback = self.closed_callback
        self.closed_callback = None
        if callable(callback):
            callback()
        super().closeEvent(event)


class FeedbackOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._toasts: list[ReminderToast] = []

    def show_feedback(self, view: ReminderView, seconds: int = 6) -> None:
        toast = ReminderToast(view)
        toast.closed_callback = lambda item=toast: self._forget_toast(item)
        self._toasts.insert(0, toast)
        while len(self._toasts) > 3:
            old_toast = self._toasts.pop()
            old_toast.close()
        self._position_toasts()
        toast.show_for(seconds)

    def clear_feedback(self) -> None:
        toasts = list(self._toasts)
        self._toasts.clear()
        for toast in toasts:
            toast.close()

    def hide(self) -> None:
        self.clear_feedback()
        super().hide()

    def _forget_toast(self, toast: "ReminderToast") -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)

    def _position_toasts(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        left = rect.left() + 32
        top = rect.top() + 80
        for toast in self._toasts:
            toast.adjustSize()
            toast.move(left, top)
            top += toast.height() + 12


class ReminderOverlay(QWidget):
    def __init__(self, toggle_hotkey: str = "F7") -> None:
        super().__init__()
        self._reminders: dict[str, TraderReminder] = {}
        self._countdown_labels: dict[str, QLabel] = {}
        self._status_labels: dict[str, QLabel] = {}
        self._hidden = False

        self.setWindowTitle("商人补货倒计时")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._card = QWidget()
        self._card.setObjectName("reminderCountdownCard")
        self._card.setMinimumWidth(440)
        self._card.setMaximumWidth(560)
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(16, 13, 16, 13)
        card_layout.setSpacing(9)

        header = QHBoxLayout()
        title = QLabel("商人补货倒计时")
        title.setObjectName("reminderCountdownTitle")
        self._count_label = QLabel("0 个")
        self._count_label.setObjectName("reminderCountdownCount")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._count_label)
        card_layout.addLayout(header)

        self._rows_widget = QWidget()
        self._rows_layout = QGridLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setHorizontalSpacing(14)
        self._rows_layout.setVerticalSpacing(6)
        self._rows_layout.setColumnStretch(1, 1)
        card_layout.addWidget(self._rows_widget)

        self._footer_label = QLabel()
        self._footer_label.setObjectName("reminderCountdownFooter")
        card_layout.addWidget(self._footer_label)
        outer.addWidget(self._card)
        self.set_toggle_hotkey(toggle_hotkey)

        self.setStyleSheet(
            "QWidget#reminderCountdownCard {"
            "background: rgba(18, 20, 24, 238);"
            "border: 1px solid rgba(242, 193, 78, 115);"
            "border-radius: 10px;"
            "}"
            "QLabel#reminderCountdownTitle {"
            "font-size: 18px; font-weight: 800; color: #FBFAF4;"
            "}"
            "QLabel#reminderCountdownCount {"
            "font-size: 13px; font-weight: 700; color: #F2C14E;"
            "}"
            "QLabel#reminderCountdownTrader {"
            "font-size: 14px; font-weight: 700; color: #FBFAF4;"
            "}"
            "QLabel#reminderCountdownStatus {"
            "font-size: 12px; color: rgba(245, 242, 232, 0.68);"
            "}"
            "QLabel#reminderCountdownFooter {"
            "font-size: 11px; color: rgba(245, 242, 232, 0.52);"
            "}"
        )

    def set_toggle_hotkey(self, hotkey: str) -> None:
        self._footer_label.setText(
            f"{hotkey.strip() or 'F7'} 显示/隐藏 · 提醒触发后在此高亮"
        )

    def set_reminders(self, reminders: dict[str, TraderReminder]) -> None:
        keys_changed = tuple(self._reminders) != tuple(reminders)
        self._reminders = dict(reminders)
        if keys_changed:
            self._rebuild_rows()
        self._update_rows()
        if not self._reminders:
            super().hide()
            return
        if self.isVisible() and not self._hidden:
            self._position_on_screen()

    def show_triggered(self, trader: str) -> None:
        if trader not in self._reminders or self._hidden:
            return
        self._update_rows()
        self._show_panel()

    def toggle_visibility(self) -> bool | None:
        if not self._reminders:
            return None
        if self.isVisible() and not self._hidden:
            self._hidden = True
            super().hide()
            return False
        self._hidden = False
        self._show_panel()
        return True

    def clear_reminders(self) -> None:
        self._hidden = False
        self._reminders.clear()
        self._rebuild_rows()
        super().hide()

    def _rebuild_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._countdown_labels.clear()
        self._status_labels.clear()

        ordered = [trader for trader in TRADERS if trader in self._reminders]
        ordered.extend(trader for trader in self._reminders if trader not in ordered)
        for row, trader in enumerate(ordered):
            name = QLabel(trader)
            name.setObjectName("reminderCountdownTrader")
            countdown = QLabel("00:00:00")
            countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status = QLabel("")
            status.setObjectName("reminderCountdownStatus")
            status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._countdown_labels[trader] = countdown
            self._status_labels[trader] = status
            self._rows_layout.addWidget(name, row, 0)
            self._rows_layout.addWidget(countdown, row, 1)
            self._rows_layout.addWidget(status, row, 2)
        self._count_label.setText(f"{len(ordered)} 个")

    def _update_rows(self) -> None:
        for trader, reminder in self._reminders.items():
            countdown = self._countdown_labels.get(trader)
            status = self._status_labels.get(trader)
            if countdown is None or status is None:
                continue
            remaining = remaining_countdown_seconds(reminder)
            countdown.setText(format_countdown(remaining))
            if remaining <= 0:
                state = "已补货"
                color = "#36D27F"
            elif reminder.triggered:
                state = "即将补货"
                color = "#F2C14E"
            else:
                state = f"补货 {reminder.restock_at:%H:%M:%S}"
                color = "#5DA8FF"
            countdown.setStyleSheet(
                f"font-size: 20px; font-weight: 900; color: {color};"
            )
            status.setText(state)

    def _show_panel(self) -> None:
        self._position_on_screen()
        self.show()
        self.raise_()

    def _position_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        self.adjustSize()
        self.move(rect.left() + 32, rect.top() + 220)


class ReminderToast(QWidget):
    def __init__(self, view: ReminderView) -> None:
        super().__init__()
        self.closed_callback: object | None = None
        self._closing = False
        self._animation: QPropertyAnimation | None = None
        self._timer_generation = 0
        self.setWindowTitle("商人补货提醒")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget()
        card.setObjectName("reminderToastCard")
        card.setMinimumWidth(480)
        card.setMaximumWidth(640)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        accent = QWidget()
        accent.setFixedWidth(7)
        accent.setStyleSheet(
            f"background: {view.accent_color};"
            "border-top-left-radius: 8px;"
            "border-bottom-left-radius: 8px;"
        )
        card_layout.addWidget(accent)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(15, 12, 16, 13)
        content_layout.setSpacing(5)

        self._title_label = QLabel(view.title)
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet("font-size: 18px; font-weight: 800; color: #FBFAF4;")
        self._value_label = QLabel(view.value_text)
        self._value_label.setStyleSheet(
            f"font-size: 24px; font-weight: 900; color: {view.accent_color};"
        )
        self._detail_label = QLabel(view.detail)
        self._detail_label.setWordWrap(True)
        self._detail_label.setStyleSheet("font-size: 13px; color: rgba(245, 242, 232, 0.72);")

        content_layout.addWidget(self._title_label)
        content_layout.addWidget(self._value_label)
        content_layout.addWidget(self._detail_label)
        card_layout.addWidget(content, 1)
        outer.addWidget(card)

        self.setStyleSheet(
            "QWidget#reminderToastCard {"
            "background: rgba(18, 20, 24, 234);"
            "border: 1px solid rgba(242, 193, 78, 90);"
            "border-radius: 8px;"
            "}"
        )

    def show_for(self, seconds: int) -> None:
        self._closing = False
        self._timer_generation += 1
        generation = self._timer_generation
        if self._animation is not None:
            self._animation.stop()
        self._opacity.setOpacity(1.0)
        self.show()
        self.raise_()
        duration_ms = max(1, int(seconds)) * 1000
        QTimer.singleShot(duration_ms, lambda: self._fade_out_if_current(generation))

    def show_persistent(self) -> None:
        self._closing = False
        self._timer_generation += 1
        if self._animation is not None:
            self._animation.stop()
        self._opacity.setOpacity(0.62)
        self.show()
        self.raise_()

    def _fade_out_if_current(self, generation: int) -> None:
        if generation == self._timer_generation:
            self.fade_out()

    def fade_out(self, duration_ms: int = 450) -> None:
        if self._closing:
            return
        self._closing = True
        animation = QPropertyAnimation(self._opacity, b"opacity", self)
        self._animation = animation
        animation.setDuration(max(80, duration_ms))
        animation.setStartValue(float(self._opacity.opacity()))
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(self.close)
        animation.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        callback = self.closed_callback
        self.closed_callback = None
        if callable(callback):
            callback()
        super().closeEvent(event)
