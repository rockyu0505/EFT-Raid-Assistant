from __future__ import annotations

import html
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.capture import (
    Region,
    capture_hover_item_name_region,
    capture_inventory_tab_region,
    capture_item_name_region,
    capture_timer_strip,
    debug_paths,
    hover_search_debug_path,
    inventory_tab_debug_path,
    is_tarkov_foreground,
    item_debug_path,
    resolve_capture_region,
    scale_metric,
)
from app.config import APP_DIR, load_config, save_config
from app.hotkeys import HotkeyManager
from app.item_ocr import (
    detect_inventory_screen,
    detect_inventory_tab_crop,
    refine_tooltip_name_crop,
    run_item_name_ocr,
)
from app.models import TRADERS, TraderReminder
from app.ocr import OcrUnavailableError, run_ocr, timer_to_seconds
from app.prices import CHINESE_ALIASES_PATH, PriceLookupError, TarkovPriceClient
from app.reminders import ReminderManager


class MainWindow(QMainWindow):
    capture_requested = Signal()
    item_lookup_requested = Signal()
    schedule_requested = Signal()
    price_result_ready = Signal(object, str)
    cache_refresh_ready = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("塔科夫局内助手")
        self.resize(980, 720)

        self.config = load_config()
        self.hotkeys = HotkeyManager()
        self.reminders = ReminderManager()
        self.price_client = TarkovPriceClient()
        self.current_price_game_mode = str(self.config.get("price_game_mode_default", "pve"))
        self.price_client.set_game_mode(self.current_price_game_mode)
        self.price_overlay = PriceOverlay()
        self._run_log_path = APP_DIR / "debug" / "latest_run.log"
        self._reset_run_log()
        self._cached_item_region: Region | None = None
        self._item_region_calibrated = False
        self._inventory_check_cache: (
            tuple[float, tuple[int, int] | None, bool, list[str]] | None
        ) = None
        self._closing = False
        self._workers: set[threading.Thread] = set()
        self._workers_lock = threading.Lock()
        self.panel_buttons: list[QPushButton] = []

        self.watch_checks: dict[str, QCheckBox] = {}
        self.timer_fields: dict[str, QLineEdit] = {}
        self.restock_items: dict[str, QTableWidgetItem] = {}
        self.status_items: dict[str, QTableWidgetItem] = {}

        self.reminders.reminder_triggered.connect(self._on_reminder_triggered)
        self.capture_requested.connect(self.capture_and_ocr)
        self.item_lookup_requested.connect(self.capture_item_price)
        self.schedule_requested.connect(self.schedule_selected)
        self.price_result_ready.connect(self._on_price_result_ready)
        self.cache_refresh_ready.connect(self._on_cache_refresh_ready)

        self._build_ui()
        self._register_hotkeys()
        self._update_cache_status_label()
        if bool(self.config.get("refresh_prices_on_startup", True)):
            self.refresh_price_cache(background=True)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._save_config()
        self.hotkeys.unregister(join_timeout=1.0)
        self.reminders.shutdown()
        self.price_overlay.hide()
        self._join_workers(timeout=1.0)

    def _build_ui(self) -> None:
        self._build_menu()

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        sidebar = self._build_sidebar()
        self.panel_stack = QStackedWidget()
        self.panel_stack.addWidget(self._build_price_panel())
        self.panel_stack.addWidget(self._build_trader_panel())
        self.panel_stack.addWidget(self._build_data_panel())
        self.panel_stack.setCurrentIndex(0)
        self._select_panel(0)

        layout.addWidget(sidebar)
        layout.addWidget(self.panel_stack, 1)
        self.setCentralWidget(root)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(150)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        for index, title in enumerate(["局内查价", "商人补货", "数据"]):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setMinimumHeight(38)
            button.clicked.connect(lambda checked=False, page=index: self._select_panel(page))
            self.panel_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)

        settings_button = QPushButton("设置")
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
        layout.addWidget(self._build_log_panel(), 1)
        return panel

    def _build_trader_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(self._build_trader_group())
        return panel

    def _build_data_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        actions = QGroupBox("数据")
        actions_layout = QVBoxLayout(actions)
        refresh_button = QPushButton("刷新价格缓存")
        refresh_button.clicked.connect(lambda: self.refresh_price_cache(background=True))
        reload_button = QPushButton("重新加载中文别名")
        reload_button.clicked.connect(self.reload_chinese_aliases)
        open_alias_button = QPushButton("打开中文别名文件")
        open_alias_button.clicked.connect(self.open_chinese_aliases)
        actions_layout.addWidget(refresh_button)
        actions_layout.addWidget(reload_button)
        actions_layout.addWidget(open_alias_button)
        actions_layout.addStretch(1)

        layout.addWidget(actions)
        layout.addStretch(1)
        return panel

    def _build_menu(self) -> None:
        settings_action = QAction("打开设置", self)
        settings_action.triggered.connect(self.open_settings)
        refresh_action = QAction("刷新价格缓存", self)
        refresh_action.triggered.connect(lambda: self.refresh_price_cache(background=True))
        reload_aliases_action = QAction("重新加载中文别名", self)
        reload_aliases_action.triggered.connect(self.reload_chinese_aliases)
        open_aliases_action = QAction("打开中文别名文件", self)
        open_aliases_action.triggered.connect(self.open_chinese_aliases)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close)

        settings_menu = self.menuBar().addMenu("设置")
        settings_menu.addAction(settings_action)

        data_menu = self.menuBar().addMenu("数据")
        data_menu.addAction(refresh_action)
        data_menu.addAction(reload_aliases_action)
        data_menu.addAction(open_aliases_action)

        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(quit_action)

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
        self.price_mode_combo = QComboBox()
        self.price_mode_combo.addItem("PvE", "pve")
        self.price_mode_combo.addItem("PvP", "regular")
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
        layout.addWidget(self._build_trader_table())

        buttons = QHBoxLayout()
        self.capture_button = QPushButton("识别倒计时")
        self.capture_button.clicked.connect(self.capture_and_ocr)
        self.schedule_button = QPushButton("设置选中提醒")
        self.schedule_button.clicked.connect(self.schedule_selected)
        self.clear_button = QPushButton("清空提醒")
        self.clear_button.clicked.connect(self.clear_reminders)
        self.open_crop_button = QPushButton("打开倒计时截图")
        self.open_crop_button.clicked.connect(self.open_debug_crop)

        buttons.addWidget(self.capture_button)
        buttons.addWidget(self.schedule_button)
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.open_crop_button)
        layout.addLayout(buttons)
        return group

    def _build_trader_table(self) -> QTableWidget:
        table = QTableWidget(len(TRADERS), 5)
        self.table = table
        table.setHorizontalHeaderLabels(
            ["商人", "提醒", "倒计时 / 手动修正", "补货时间", "状态"]
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

            timer = QLineEdit()
            timer.setPlaceholderText("HH:MM:SS")
            self.timer_fields[trader] = timer
            table.setCellWidget(row, 2, timer)

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
        return self.log

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.config.update(dialog.values())
        if hasattr(self, "price_mode_combo"):
            mode_index = self.price_mode_combo.findData(
                str(self.config.get("price_game_mode_default", "pve"))
            )
            self.price_mode_combo.setCurrentIndex(max(0, mode_index))
        self._save_config()
        self._register_hotkeys()
        self._log("设置已更新。")
        self._update_cache_status_label()
        if bool(self.config.get("refresh_prices_on_startup", True)):
            self.refresh_price_cache(background=True)

    def reload_chinese_aliases(self) -> None:
        count = self.price_client.reload_aliases()
        self._update_cache_status_label()
        self._log(f"中文别名已重新加载：{count} 条。")

    def open_chinese_aliases(self) -> None:
        CHINESE_ALIASES_PATH.parent.mkdir(exist_ok=True)
        if not CHINESE_ALIASES_PATH.exists():
            CHINESE_ALIASES_PATH.write_text("{}\n", encoding="utf-8")
        os.startfile(CHINESE_ALIASES_PATH)  # type: ignore[attr-defined]

    def _save_config(self) -> None:
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
        mode = self._selected_price_game_mode()
        self.current_price_game_mode = self.price_client.set_game_mode(mode)
        self.config["price_game_mode_default"] = self.current_price_game_mode
        save_config(self.config)
        self._update_cache_status_label()
        self._log(f"Price mode set manually: {_game_mode_label(self.current_price_game_mode)}.")

    def _register_hotkeys(self) -> None:
        try:
            self.hotkeys.register(
                str(self.config.get("capture_hotkey", "F8")),
                str(self.config.get("schedule_hotkey", "F10")),
                lambda: self.capture_requested.emit(),
                lambda: self.schedule_requested.emit(),
                str(self.config.get("item_lookup_hotkey", "Q")),
                lambda: self.item_lookup_requested.emit(),
            )
        except Exception as exc:
            self._log(f"热键注册失败：{exc}")
            return
        self._log(
            "热键已注册："
            f"倒计时={self.config.get('capture_hotkey', 'F8')}，"
            f"物品查价={self.config.get('item_lookup_hotkey', 'Q')}，"
            f"设置提醒={self.config.get('schedule_hotkey', 'F10')}"
        )

    def refresh_price_cache(self, background: bool = False) -> None:
        if background:
            self.cache_status_label.setText("价格: 正在刷新...")
            self._start_worker("price-cache-refresh", self._refresh_price_cache_worker)
            return
        self._refresh_price_cache_worker()

    def _refresh_price_cache_worker(self) -> None:
        if self._closing:
            return
        try:
            counts = self.price_client.refresh_all_modes()
        except PriceLookupError as exc:
            status = f"价格缓存刷新失败：{exc}"
        except Exception as exc:
            status = f"价格缓存刷新异常：{exc}"
        else:
            status = (
                "价格缓存已就绪："
                f"PvP {counts.get('regular', 0)} 个物品，"
                f"PvE {counts.get('pve', 0)} 个物品"
            )
        if not self._closing:
            self.cache_refresh_ready.emit(status)

    def _on_cache_refresh_ready(self, status: str) -> None:
        if self._closing:
            return
        self._log(status)
        self._update_cache_status_label()

    def _update_cache_status_label(self) -> None:
        self.cache_status_label.setText(
            f"价格: {self.price_client.cache_status()} / 中文别名: {self.price_client.alias_status()}"
        )

    def capture_and_ocr(self) -> None:
        if self._closing:
            return
        self._save_config()
        if not self._ensure_tarkov_foreground("倒计时识别"):
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
            QMessageBox.warning(self, "截图失败", str(exc))
            return

        self.detected_size_label.setText(f"截图: {size[0]}x{size[1]} ({region_name})")
        self._log(f"已截图：{size[0]}x{size[1]}，来源：{region_name}。")

        _, crop_path = debug_paths()
        try:
            result = run_ocr(crop_path, str(self.config.get("tesseract_cmd", "")))
        except OcrUnavailableError as exc:
            self._log(str(exc))
            QMessageBox.warning(self, "OCR 不可用", str(exc))
            return
        except Exception as exc:
            self._log(f"OCR 失败：{exc}")
            QMessageBox.warning(self, "OCR 失败", str(exc))
            return

        self._log(f"OCR 预处理：{result.variant_name}")
        self._log("识别到的倒计时：" + (", ".join(result.timers) or "无"))

        for index, trader in enumerate(TRADERS):
            if index < len(result.timers):
                self.timer_fields[trader].setText(result.timers[index])
                self.status_items[trader].setText("已识别")
            else:
                self.status_items[trader].setText("OCR 失败")

        if len(result.timers) < len(TRADERS):
            self._log(
                f"注意：只识别到 {len(result.timers)} 个倒计时，商人数量为 {len(TRADERS)}。"
                "请使用手动修正输入框。"
            )

    def capture_item_price(self) -> None:
        if self._closing:
            return
        self._save_config()
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
        save_full_screenshot = False
        hover_cursor_anchor: tuple[int, int] | None = None
        try:
            previous_region = self._cached_item_region
            capture_region = resolve_capture_region(capture_mode)
            resolution_changed = _region_size_signature(previous_region) != _region_size_signature(
                capture_region
            )
            save_full_screenshot = not self._item_region_calibrated or resolution_changed
            self._cached_item_region = capture_region
            self._item_region_calibrated = True
            if resolution_changed:
                self._clear_state_detection_cache()

            if item_mode == "Hover tooltip":
                _, _, size, region_name, hover_cursor_anchor = capture_hover_item_name_region(
                    capture_mode,
                    offset=tuple(self.config.get("hover_tooltip_offset", [12, -60])),
                    crop_size=tuple(self.config.get("hover_tooltip_size", [360, 110])),
                    search_margins=tuple(
                        self.config.get("hover_search_margins", [560, 560, 240, 45])
                    ),
                    region=capture_region,
                    save_full_screenshot=save_full_screenshot,
                )
            else:
                _, _, size, region_name = capture_item_name_region(
                    capture_mode,
                    manual_size=manual_size,
                    roi_base=tuple(self.config.get("item_roi_base", [670, 120, 1420, 260])),
                )
        except Exception as exc:
            self._cached_item_region = None
            self._item_region_calibrated = False
            self._log(f"Item screenshot failed: {exc}")
            QMessageBox.warning(self, "Item screenshot failed", str(exc))
            return

        self.detected_size_label.setText(f"Capture: {size[0]}x{size[1]} ({region_name})")
        self._log(f"Captured item region: {size[0]}x{size[1]}, source: {region_name}.")
        if save_full_screenshot:
            self._log("Capture region calibrated; subsequent item lookups use ROI-only crops.")
        else:
            self._log("Using ROI-only capture: tooltip + inventory tab.")

        if bool(self.config.get("require_inventory_check", True)):
            try:
                detected, found = self._detect_inventory_from_capture(
                    capture_mode,
                    manual_size,
                    capture_region,
                )
            except OcrUnavailableError as exc:
                self._log(str(exc))
                QMessageBox.warning(self, "OCR unavailable", str(exc))
                return
            except Exception as exc:
                self._log(f"Inventory tab check failed: {exc}")
                return
            if not detected:
                self.item_price_label.setText("Price: inventory tab not detected")
                self.price_overlay.clear_prices()
                self._log_event("已拒绝查价：没有检测到装备/背包页面。")
                self._log(f"Inventory tab not detected. Keywords: {', '.join(found) or 'none'}")
                return
            self._log(f"Inventory tab detected: {', '.join(found)}")

        if item_mode == "Hover tooltip":
            try:
                tooltip_gap = scale_metric(
                    int(self.config.get("tooltip_cursor_bottom_gap", 20)),
                    size[1],
                    int(self.config.get("tooltip_cursor_reference_height", 2160)),
                    minimum=6,
                )
                tooltip_tolerance = scale_metric(
                    int(self.config.get("tooltip_cursor_gap_tolerance", 36)),
                    size[1],
                    int(self.config.get("tooltip_cursor_reference_height", 2160)),
                    minimum=14,
                )
                refined, words = refine_tooltip_name_crop(
                    hover_search_debug_path(),
                    item_debug_path(),
                    str(self.config.get("tesseract_cmd", "")),
                    str(self.config.get("item_ocr_language", "chi_sim+eng")),
                    tuple(self.config.get("hover_name_padding", [10, 8, 10, 8])),
                    hover_cursor_anchor,
                    tooltip_gap,
                    tooltip_tolerance,
                )
            except Exception as exc:
                refined = False
                words = []
                self._log(f"Tooltip box location failed; falling back to wider OCR crop: {exc}")
            if refined:
                self._log("Tooltip name box located: " + (" ".join(words) or "no text"))
            else:
                self._log("Tooltip name box not located; using wider OCR crop.")

        try:
            result = run_item_name_ocr(
                item_debug_path(),
                str(self.config.get("tesseract_cmd", "")),
                str(self.config.get("item_ocr_language", "chi_sim+eng")),
                str(self.config.get("item_ocr_engine", "tesseract")),
            )
        except OcrUnavailableError as exc:
            self._log(str(exc))
            QMessageBox.warning(self, "OCR unavailable", str(exc))
            return
        except Exception as exc:
            self._log(f"Item OCR failed: {exc}")
            QMessageBox.warning(self, "Item OCR failed", str(exc))
            return

        self._log(f"Item OCR preprocessing: {result.variant_name}")
        self._log("Item candidate names: " + (", ".join(result.candidates) or "none"))

        if not result.candidates:
            self.item_price_label.setText("Price: no item name detected")
            self._log_event("无匹配物品：没有识别到可用的物品名。")
            return

        self.item_name_field.setText(result.candidates[0])
        self._lookup_item_candidates(result.candidates)

    def capture_item_price_after_delay(self) -> None:
        seconds = int(self.config.get("button_capture_delay_seconds", 0))
        if seconds <= 0:
            self._log("即将截图。hover 模式建议在游戏中等名称框出现后按热键触发。")
            self.capture_item_price()
            return
        self._log(f"请在 {seconds} 秒内切回游戏，把鼠标悬停到物品上。建议平时直接用热键。")
        self.item_price_label.setText(f"价格: {seconds} 秒后截图，请切回游戏并悬停物品")
        QTimer.singleShot(seconds * 1000, self.capture_item_price)

    def lookup_manual_item_name(self) -> None:
        if self._closing:
            return
        name = self.item_name_field.text().strip()
        if not name:
            self.item_price_label.setText("价格: 请先输入物品名")
            self._log_event("已跳过查价：物品名为空。")
            return

        mode = self.price_client.set_game_mode(self._selected_price_game_mode())
        self.current_price_game_mode = mode
        self.config["price_game_mode_default"] = mode
        label = _game_mode_label(mode)
        self.item_price_label.setText(f"价格: 正在查询 {label} / {name}...")
        self._log(f"正在从本地 {label} 缓存查价：{name}")
        self._start_worker("price-lookup", self._lookup_price_worker, name, mode)

    def _lookup_item_candidates(self, names: list[str]) -> None:
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
        mode = self.price_client.set_game_mode(self._selected_price_game_mode())
        self.current_price_game_mode = mode
        self.config["price_game_mode_default"] = mode
        label = _game_mode_label(mode)
        self.item_price_label.setText(f"价格: 正在查询 {label} / {candidates[0]}...")
        self._log(f"正在从本地 {label} 缓存查价候选：{', '.join(candidates)}")
        self._start_worker("price-lookup", self._lookup_price_candidates_worker, candidates, mode)

    def _lookup_price_worker(self, name: str, game_mode: str) -> None:
        if self._closing:
            return
        try:
            price = self.price_client.lookup(name, game_mode)
        except PriceLookupError as exc:
            if not self._closing:
                self.price_result_ready.emit(None, str(exc))
        except Exception as exc:
            if not self._closing:
                self.price_result_ready.emit(None, f"查价异常：{exc}")
        else:
            if not self._closing:
                self.price_result_ready.emit(price, "")

    def _lookup_price_candidates_worker(self, names: list[str], game_mode: str) -> None:
        if self._closing:
            return
        try:
            price = self.price_client.lookup_candidates(names, game_mode)
        except PriceLookupError as exc:
            if not self._closing:
                self.price_result_ready.emit(None, str(exc))
            return
        except Exception as exc:
            if not self._closing:
                self.price_result_ready.emit(None, f"查价异常：{exc}")
            return
        if not self._closing:
            self.price_result_ready.emit(price, "")

    def _detect_inventory_from_capture(
        self,
        capture_mode: str,
        manual_size: tuple[int, int] | None,
        capture_region: Region | None,
    ) -> tuple[bool, list[str]]:
        signature = _region_size_signature(capture_region)
        cached = self._inventory_check_cache
        if cached is not None:
            cached_at, cached_signature, cached_detected, cached_found = cached
            if cached_signature == signature and self._state_detection_cache_is_fresh(cached_at):
                self._log("Using cached inventory tab state.")
                return cached_detected, cached_found

        capture_inventory_tab_region(
            capture_mode,
            manual_size,
            tuple(self.config.get("inventory_tab_roi_base", [105, 0, 235, 48])),
            capture_region,
        )
        detected, found, _ = detect_inventory_tab_crop(
            inventory_tab_debug_path(),
            str(self.config.get("tesseract_cmd", "")),
            str(self.config.get("item_ocr_language", "chi_sim+eng")),
        )
        self._inventory_check_cache = (time.monotonic(), signature, detected, found)
        return detected, found

    def _state_detection_cache_is_fresh(self, cached_at: float) -> bool:
        ttl = max(0.0, float(self.config.get("state_detection_cache_seconds", 2)))
        return ttl > 0 and time.monotonic() - cached_at <= ttl

    def _clear_state_detection_cache(self) -> None:
        self._inventory_check_cache = None

    def _start_worker(
        self,
        name: str,
        target: Callable[..., None],
        *args: object,
    ) -> None:
        if self._closing:
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
        if self._closing:
            return
        if error:
            self.item_price_label.setText(f"价格: {error}")
            self._log_event(error)
            self.price_overlay.clear_prices()
            return

        display_language = str(self.config.get("item_display_language", "zh"))
        raw_tiers = self.config.get("price_value_tiers", [])
        tiers = raw_tiers if isinstance(raw_tiers, list) else []
        basis = str(self.config.get("price_value_basis", "slot"))
        firearm_color = str(self.config.get("firearm_value_color", "#00D1D1"))
        firearm_accent = str(self.config.get("firearm_value_accent", firearm_color))
        view = _build_price_view(price, display_language, tiers, basis, firearm_color, firearm_accent)
        self.item_price_label.setText(view.label_html)
        self.item_price_label.setTextFormat(Qt.TextFormat.RichText)
        self._log_event(view.log_text)
        if bool(self.config.get("price_overlay_enabled", True)):
            try:
                seconds = int(self.config.get("price_overlay_seconds", 10))
            except (TypeError, ValueError):
                seconds = 10
            self.price_overlay.show_price(view, seconds)
        else:
            self.price_overlay.clear_prices()

    def schedule_selected(self) -> None:
        self._save_config()
        scheduled = 0
        for trader in TRADERS:
            if not self.watch_checks[trader].isChecked():
                continue

            value = self.timer_fields[trader].text().strip()
            seconds = timer_to_seconds(value)
            if seconds is None:
                self.status_items[trader].setText("倒计时无效")
                self._log(f"已跳过 {trader}：倒计时无效 '{value}'。")
                continue

            reminder = self.reminders.schedule(
                trader=trader,
                countdown_seconds=seconds,
                lead_seconds=int(self.config.get("lead_time_seconds", 10)),
                repeat_seconds=int(self.config.get("repeat_alert_seconds", 0)),
            )
            self.restock_items[trader].setText(reminder.restock_at.strftime("%H:%M:%S"))
            self.status_items[trader].setText("已设置")
            self._log(
                f"已设置 {trader}：补货 {reminder.restock_at.strftime('%H:%M:%S')}，"
                f"提醒 {reminder.notify_at.strftime('%H:%M:%S')}。"
            )
            scheduled += 1

        if scheduled == 0:
            self._log("没有设置任何提醒。请选择商人并输入有效的 HH:MM:SS 倒计时。")

    def clear_reminders(self) -> None:
        self.reminders.clear()
        for trader in TRADERS:
            self.status_items[trader].setText("未启用")
            self.restock_items[trader].setText("")
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
        self.status_items[trader].setText("已触发")
        self._log(f"{trader} 的提醒已触发。")
        if bool(self.config.get("sound_enabled", True)):
            QApplication.beep()
        if bool(self.config.get("popup_enabled", True)):
            QMessageBox.information(
                self,
                "商人补货提醒",
                f"{trader} 即将补货。\n补货时间：{reminder.restock_at:%H:%M:%S}",
            )

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
        message = f"已拒绝查价：当前前台窗口不是 Tarkov，而是「{title}」。"
        self._log_event(message)
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
        if visible and hasattr(self, "log"):
            self.log.append(line)

    def _log_event(self, message: str) -> None:
        self._log(message, visible=True)


class SettingsDialog(QDialog):
    def __init__(self, config: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(640, 520)
        self._config = config
        self.roi_fields: list[QSpinBox] = []
        self.item_roi_fields: list[QSpinBox] = []
        self.inventory_tab_roi_fields: list[QSpinBox] = []
        self.hover_offset_fields: list[QSpinBox] = []
        self.hover_size_fields: list[QSpinBox] = []
        self.hover_search_margin_fields: list[QSpinBox] = []
        self.hover_name_padding_fields: list[QSpinBox] = []
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_capture_tab(), "截图")
        tabs.addTab(self._build_hotkeys_tab(), "热键")
        tabs.addTab(self._build_prices_tab(), "价格")
        tabs.addTab(self._build_reminders_tab(), "提醒")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_capture_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)

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

        layout.addRow("截图模式", self.capture_mode)
        layout.addRow(self.manual_resolution)
        layout.addRow("分辨率预设", self.resolution_preset)
        layout.addRow("宽度", self.manual_width)
        layout.addRow("高度", self.manual_height)
        layout.addRow("物品识别方式", self.item_capture_mode)
        layout.addRow("悬停等待毫秒", self.hover_wait_ms)
        layout.addRow("悬停搜索边距", hover_search_margins)
        layout.addRow("名称框留白", hover_name_padding)
        layout.addRow("悬停提示偏移", hover_offset)
        layout.addRow("悬停提示尺寸", hover_size)
        layout.addRow("装备页签 ROI", inventory_tab_roi)
        layout.addRow("倒计时 ROI", timer_roi)
        layout.addRow("物品名 ROI", item_roi)
        return tab

    def _build_hotkeys_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        self.capture_hotkey = QLineEdit()
        self.item_lookup_hotkey = QLineEdit()
        self.schedule_hotkey = QLineEdit()
        self.tesseract_cmd = QLineEdit()
        self.item_ocr_engine = QComboBox()
        self.item_ocr_engine.addItem("RapidOCR only", "rapidocr")
        self.item_ocr_engine.addItem("RapidOCR v5 only", "rapidocr_v5")
        self.item_ocr_engine.addItem("RapidOCR + Tesseract fallback", "rapidocr+tesseract")
        self.item_ocr_engine.addItem("Tesseract only", "tesseract")
        self.item_ocr_language = QLineEdit()
        layout.addRow("识别倒计时", self.capture_hotkey)
        layout.addRow("物品查价", self.item_lookup_hotkey)
        layout.addRow("设置提醒", self.schedule_hotkey)
        layout.addRow("Tesseract 路径", self.tesseract_cmd)
        layout.addRow("物品 OCR 引擎", self.item_ocr_engine)
        layout.addRow("物品 OCR 语言", self.item_ocr_language)
        return tab

    def _build_prices_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        self.price_overlay_enabled = QCheckBox("显示置顶价格浮窗")
        self.require_tarkov_foreground = QCheckBox("截图前要求 Tarkov 是前台窗口")
        self.require_inventory_check = QCheckBox("查价前先检测背包/详情界面")
        self.refresh_prices_on_startup = QCheckBox("启动时刷新全量物品价格缓存")
        self.price_overlay_seconds = QSpinBox()
        self.price_overlay_seconds.setRange(1, 120)
        self.item_display_language = QComboBox()
        self.item_display_language.addItem("中文", "zh")
        self.item_display_language.addItem("English", "en")
        self.price_game_mode_default = QComboBox()
        self.price_game_mode_default.addItem("PvE", "pve")
        self.price_game_mode_default.addItem("PvP", "regular")
        layout.addRow(self.price_overlay_enabled)
        layout.addRow(self.require_tarkov_foreground)
        layout.addRow(self.require_inventory_check)
        layout.addRow(self.refresh_prices_on_startup)
        layout.addRow("浮窗显示秒数", self.price_overlay_seconds)
        layout.addRow("物品名称语言", self.item_display_language)
        layout.addRow("默认价格模式", self.price_game_mode_default)
        return tab

    def _build_reminders_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)
        self.lead_seconds = QSpinBox()
        self.lead_seconds.setRange(0, 3600)
        self.repeat_seconds = QSpinBox()
        self.repeat_seconds.setRange(0, 3600)
        self.sound_enabled = QCheckBox("声音")
        self.popup_enabled = QCheckBox("弹窗")
        layout.addRow("提前提醒秒数", self.lead_seconds)
        layout.addRow("重复提醒间隔", self.repeat_seconds)
        layout.addRow(self.sound_enabled)
        layout.addRow(self.popup_enabled)
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
        self.schedule_hotkey.setText(str(self._config.get("schedule_hotkey", "F10")))
        self.tesseract_cmd.setText(str(self._config.get("tesseract_cmd", "")))
        ocr_engine_index = self.item_ocr_engine.findData(
            str(self._config.get("item_ocr_engine", "tesseract"))
        )
        self.item_ocr_engine.setCurrentIndex(max(0, ocr_engine_index))
        self.item_ocr_language.setText(str(self._config.get("item_ocr_language", "chi_sim+eng")))

        self.price_overlay_enabled.setChecked(bool(self._config.get("price_overlay_enabled", True)))
        self.require_tarkov_foreground.setChecked(
            bool(self._config.get("require_tarkov_foreground", True))
        )
        self.require_inventory_check.setChecked(bool(self._config.get("require_inventory_check", True)))
        self.refresh_prices_on_startup.setChecked(
            bool(self._config.get("refresh_prices_on_startup", True))
        )
        self.price_overlay_seconds.setValue(int(self._config.get("price_overlay_seconds", 10)))
        display_language_index = self.item_display_language.findData(
            str(self._config.get("item_display_language", "zh"))
        )
        self.item_display_language.setCurrentIndex(max(0, display_language_index))
        game_mode_index = self.price_game_mode_default.findData(
            str(self._config.get("price_game_mode_default", "pve"))
        )
        self.price_game_mode_default.setCurrentIndex(max(0, game_mode_index))

        self.lead_seconds.setValue(int(self._config.get("lead_time_seconds", 10)))
        self.repeat_seconds.setValue(int(self._config.get("repeat_alert_seconds", 0)))
        self.sound_enabled.setChecked(bool(self._config.get("sound_enabled", True)))
        self.popup_enabled.setChecked(bool(self._config.get("popup_enabled", True)))

    def values(self) -> dict[str, object]:
        return {
            "capture_hotkey": self.capture_hotkey.text().strip() or "F8",
            "item_lookup_hotkey": self.item_lookup_hotkey.text().strip() or "Q",
            "schedule_hotkey": self.schedule_hotkey.text().strip() or "F10",
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
            "item_ocr_engine": self.item_ocr_engine.currentData() or "tesseract",
            "item_ocr_language": self.item_ocr_language.text().strip() or "chi_sim+eng",
            "price_overlay_enabled": self.price_overlay_enabled.isChecked(),
            "price_overlay_seconds": self.price_overlay_seconds.value(),
            "item_display_language": self.item_display_language.currentData() or "zh",
            "require_tarkov_foreground": self.require_tarkov_foreground.isChecked(),
            "require_inventory_check": self.require_inventory_check.isChecked(),
            "refresh_prices_on_startup": self.refresh_prices_on_startup.isChecked(),
            "price_game_mode_default": self.price_game_mode_default.currentData() or "pve",
            "lead_time_seconds": self.lead_seconds.value(),
            "repeat_alert_seconds": self.repeat_seconds.value(),
            "sound_enabled": self.sound_enabled.isChecked(),
            "popup_enabled": self.popup_enabled.isChecked(),
            "tesseract_cmd": self.tesseract_cmd.text().strip(),
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


@dataclass(frozen=True)
class PriceView:
    title: str
    subtitle: str
    detail: str
    value_text: str
    tier_label: str
    tier_color: str
    tier_accent: str
    label_html: str
    log_text: str


def _build_price_view(
    price: object,
    display_language: str,
    tiers: list[object],
    value_basis: str,
    firearm_color: str = "#00D1D1",
    firearm_accent: str = "#00D1D1",
) -> PriceView:
    game_mode = _game_mode_label(str(getattr(price, "game_mode", "regular")))
    title = _display_item_name(price, display_language)
    confidence = getattr(price, "confidence", 0.0)
    avg_24h = _money(getattr(price, "avg_24h_price", None), "RUB")
    vendor_name = getattr(price, "best_vendor_name", None)
    vendor_currency = getattr(price, "best_vendor_currency", "RUB")
    vendor_price = _money(getattr(price, "best_vendor_price", None), vendor_currency)
    vendor = f"{vendor_name}: {vendor_price}" if vendor_name else vendor_price
    slots = getattr(price, "slots", None)
    value_per_slot = getattr(price, "value_per_slot", None)
    avg_value = getattr(price, "avg_24h_price", None)
    is_firearm = bool(getattr(price, "is_firearm", False))
    if is_firearm:
        tier_label = "枪械"
        tier_color = _safe_color(firearm_color, "#00D1D1")
        tier_accent = _safe_accent(firearm_accent, tier_color)
    else:
        value_for_tier = value_per_slot if value_basis == "slot" else avg_value
        value_basis_label = "单格"
        if value_for_tier is None and value_basis == "slot":
            value_for_tier = avg_value
            value_basis_label = "总价"
        tier_label, tier_color, tier_accent = _price_tier(value_for_tier, tiers)

    slot_suffix = f" / {slots} 格" if slots else ""
    if is_firearm:
        value_text = "枪械：按配件评估"
    elif value_per_slot is not None:
        value_text = f"{_money(value_per_slot, 'RUB')}/格"
    elif avg_value is not None:
        value_text = f"总价 {_money(avg_value, 'RUB')}"
    else:
        value_text = "价值: -"
    subtitle = f"[{game_mode}] 24h 均价 {avg_24h}{slot_suffix}"
    detail = (
        f"枪械价格包含配件 · 商人 {vendor} · 匹配 {confidence:.0%}"
        if is_firearm
        else f"{value_basis_label}分级 · 商人 {vendor} · 匹配 {confidence:.0%}"
    )
    label_html = (
        f"<div style='line-height:1.35;'>"
        f"<b>{html.escape(title)}</b> "
        f"<span style='color:{tier_color}; font-weight:700;'>{html.escape(value_text)}</span><br>"
        f"<span>{html.escape(subtitle)}</span><br>"
        f"<span>{html.escape(detail)}</span>"
        f"</div>"
    )
    if is_firearm:
        value_log = "枪械按配件评估"
    else:
        value_log = f"单格 {value_text}" if value_per_slot is not None else value_text
    log_text = f"[{game_mode}] {title} | 24h {avg_24h} | {value_log} | 商人 {vendor}"
    return PriceView(
        title=title,
        subtitle=subtitle,
        detail=detail,
        value_text=value_text,
        tier_label=tier_label,
        tier_color=tier_color,
        tier_accent=tier_accent,
        label_html=label_html,
        log_text=log_text,
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


def _safe_color(value: str, fallback: str) -> str:
    if re.match(r"^#[0-9A-Fa-f]{6}$", value):
        return value
    return fallback


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
    return "PvE" if str(game_mode).strip().casefold() == "pve" else "PvP"


def _region_size_signature(region: Region | None) -> tuple[int, int] | None:
    if region is None:
        return None
    return region.width, region.height


class PriceOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._toasts: list[PriceToast] = []

    def show_price(self, view: PriceView, seconds: int = 10) -> None:
        toast = PriceToast(view)
        toast.closed_callback = lambda item=toast: self._forget_toast(item)
        self._toasts.insert(0, toast)
        while len(self._toasts) > 3:
            old_toast = self._toasts.pop()
            old_toast.close()
        self._position_toasts()
        toast.show_for(seconds)

    def clear_prices(self) -> None:
        toasts = list(self._toasts)
        self._toasts.clear()
        for toast in toasts:
            toast.close()

    def hide(self) -> None:
        self.clear_prices()
        super().hide()

    def _forget_toast(self, toast: "PriceToast") -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)

    def _position_toasts(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        top = rect.top() + 80
        for toast in self._toasts:
            toast.adjustSize()
            toast.move(rect.right() - toast.width() - 24, top)
            top += toast.height() + 10


class PriceToast(QWidget):
    def __init__(self, view: PriceView) -> None:
        super().__init__()
        self.closed_callback: object | None = None
        self._closing = False
        self._animation: QPropertyAnimation | None = None
        self.setWindowTitle("塔科夫物品价格")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget()
        card.setObjectName("priceToastCard")
        card.setMinimumWidth(430)
        card.setMaximumWidth(540)
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

        title = QLabel(view.title)
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #FBFAF4;")
        value = QLabel(view.value_text)
        value.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {view.tier_color};")
        subtitle = QLabel(view.subtitle)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 12px; color: rgba(245, 242, 232, 0.82);")
        detail = QLabel(view.detail)
        detail.setWordWrap(True)
        detail.setStyleSheet("font-size: 12px; color: rgba(245, 242, 232, 0.68);")

        content_layout.addWidget(title)
        content_layout.addWidget(value)
        content_layout.addWidget(subtitle)
        content_layout.addWidget(detail)
        card_layout.addWidget(content, 1)
        outer.addWidget(card)

        self.setStyleSheet(
            "QWidget#priceToastCard {"
            "background: rgba(18, 20, 24, 226);"
            "border: 1px solid rgba(255, 255, 255, 38);"
            "border-radius: 8px;"
            "}"
        )

    def show_for(self, seconds: int) -> None:
        self.show()
        self.raise_()
        duration_ms = max(1, int(seconds)) * 1000
        QTimer.singleShot(duration_ms, self.fade_out)

    def fade_out(self, duration_ms: int = 450) -> None:
        if self._closing:
            return
        self._closing = True
        animation = QPropertyAnimation(self._opacity, b"opacity", self)
        self._animation = animation
        animation.setDuration(max(80, duration_ms))
        animation.setStartValue(1.0)
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
