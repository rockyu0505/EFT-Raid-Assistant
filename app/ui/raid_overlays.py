from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QCloseEvent, QCursor, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


GAMMA_CONTROLS = {
    "gamma": ("Gamma", 40, 160, 100, 2),
    "black_lift": ("暗部抬升", 0, 35, 100, 2),
    "gain": ("亮度 / Gain", 50, 125, 100, 2),
    "contrast": ("对比度", 65, 145, 100, 2),
}


RAID_OVERLAY_STYLESHEET = """
QFrame#raidPanelCard {
    background-color: rgba(13, 17, 23, 236);
    border: 1px solid rgba(201, 173, 120, 125);
    border-radius: 12px;
}
QLabel#raidPanelEyebrow {
    color: #C9AD78;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#raidPanelTitle {
    color: #F5F2EB;
    font-size: 20px;
    font-weight: 750;
}
QLabel#raidPanelHint, QLabel#raidPanelMeta {
    color: #8F9AA8;
    font-size: 11px;
}
QLabel#raidSectionTitle {
    color: #E5D5B4;
    font-size: 12px;
    font-weight: 700;
}
QFrame#raidSection {
    background-color: rgba(25, 33, 43, 205);
    border: 1px solid rgba(94, 108, 124, 75);
    border-radius: 9px;
}
QPushButton#raidCloseButton {
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
    border: none;
    background: transparent;
    color: #84909E;
    font-size: 17px;
}
QPushButton#raidCloseButton:hover {
    background-color: rgba(255, 255, 255, 20);
    color: #FFFFFF;
}
QPlainTextEdit#raidLogText {
    background: transparent;
    border: none;
    padding: 0;
    color: #D8DEE8;
    font-family: "Consolas", "Microsoft YaHei UI";
    font-size: 12px;
    selection-background-color: rgba(201, 173, 120, 100);
}
"""


class RaidControlOverlay(QWidget):
    game_mode_changed = Signal(str)
    language_changed = Signal(str)
    price_duration_changed = Signal(int)
    feedback_duration_changed = Signal(int)
    panel_opacity_changed = Signal(int)
    gamma_enabled_changed = Signal(bool)
    gamma_values_changed = Signal(object)
    gamma_restore_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._drag_offset: QPoint | None = None
        self._loading = False
        self._presets: list[dict[str, Any]] = []
        self._gamma_sliders: dict[str, QSlider] = {}
        self._gamma_values: dict[str, QLabel] = {}
        self.setWindowTitle("Raid Control")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(420)
        self.setMaximumWidth(480)
        self._build_ui()
        self.setStyleSheet(RAID_OVERLAY_STYLESHEET)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("raidPanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 17)
        layout.setSpacing(11)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(1)
        eyebrow = QLabel("EFT RAID ASSISTANT")
        eyebrow.setObjectName("raidPanelEyebrow")
        title = QLabel("局内控制")
        title.setObjectName("raidPanelTitle")
        self.status_label = QLabel("本地状态载入中")
        self.status_label.setObjectName("raidPanelMeta")
        heading.addWidget(eyebrow)
        heading.addWidget(title)
        heading.addWidget(self.status_label)
        close_button = QPushButton("×")
        close_button.setObjectName("raidCloseButton")
        close_button.setToolTip("关闭局内控制窗（Esc）")
        close_button.clicked.connect(self.hide)
        header.addLayout(heading, 1)
        header.addWidget(close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        session_section, session_layout = self._section("本次游戏")
        self.game_mode_combo = QComboBox()
        self.game_mode_combo.addItem("PvE", "pve")
        self.game_mode_combo.addItem("PvP", "regular")
        self.language_combo = QComboBox()
        self.language_combo.addItem("中文", "zh")
        self.language_combo.addItem("English", "en")
        session_layout.addWidget(QLabel("价格模式"), 0, 0)
        session_layout.addWidget(self.game_mode_combo, 0, 1)
        session_layout.addWidget(QLabel("物品名称"), 1, 0)
        session_layout.addWidget(self.language_combo, 1, 1)
        layout.addWidget(session_section)

        timing_section, timing_layout = self._section("悬浮提示")
        self.price_duration = QSpinBox()
        self.price_duration.setRange(1, 120)
        self.price_duration.setSuffix(" 秒")
        self.feedback_duration = QSpinBox()
        self.feedback_duration.setRange(1, 120)
        self.feedback_duration.setSuffix(" 秒")
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(55, 100)
        self.opacity_value = QLabel("84%")
        timing_layout.addWidget(QLabel("查价显示"), 0, 0)
        timing_layout.addWidget(self.price_duration, 0, 1)
        timing_layout.addWidget(QLabel("操作反馈"), 1, 0)
        timing_layout.addWidget(self.feedback_duration, 1, 1)
        timing_layout.addWidget(QLabel("面板透明度"), 2, 0)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_value)
        timing_layout.addLayout(opacity_row, 2, 1)
        layout.addWidget(timing_section)

        gamma_section, gamma_layout = self._section("实时画面")
        self.gamma_toggle_button = QPushButton("画面增强：已关闭")
        self.gamma_toggle_button.setCheckable(True)
        self.gamma_toggle_button.clicked.connect(self._on_gamma_enabled_changed)
        gamma_layout.addWidget(self.gamma_toggle_button, 0, 0, 1, 2)
        self.gamma_status_label = QLabel("点击开启后，方案和滑条才会修改画面。")
        self.gamma_status_label.setObjectName("raidPanelMeta")
        self.gamma_status_label.setWordWrap(True)
        gamma_layout.addWidget(self.gamma_status_label, 1, 0, 1, 2)
        self.gamma_preset_combo = QComboBox()
        gamma_layout.addWidget(QLabel("Gamma 方案"), 2, 0)
        gamma_layout.addWidget(self.gamma_preset_combo, 2, 1)
        for row, (key, definition) in enumerate(GAMMA_CONTROLS.items(), start=3):
            label, minimum, maximum, _scale, _decimals = definition
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(minimum, maximum)
            value_label = QLabel("")
            value_label.setMinimumWidth(42)
            slider_row = QHBoxLayout()
            slider_row.addWidget(slider, 1)
            slider_row.addWidget(value_label)
            gamma_layout.addWidget(QLabel(label), row, 0)
            gamma_layout.addLayout(slider_row, row, 1)
            self._gamma_sliders[key] = slider
            self._gamma_values[key] = value_label
            slider.valueChanged.connect(self._on_gamma_slider_changed)
        self.gamma_restore_button = QPushButton("恢复系统原始画面")
        self.gamma_restore_button.clicked.connect(
            lambda: self.gamma_restore_requested.emit()
        )
        gamma_layout.addWidget(
            self.gamma_restore_button,
            len(GAMMA_CONTROLS) + 3,
            0,
            1,
            2,
        )
        layout.addWidget(gamma_section)

        hint = QLabel("快捷键再次关闭 · Esc 关闭 · 拖动空白区域移动")
        hint.setObjectName("raidPanelHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        outer.addWidget(card)

        self.game_mode_combo.currentIndexChanged.connect(
            lambda: self.game_mode_changed.emit(str(self.game_mode_combo.currentData()))
        )
        self.language_combo.currentIndexChanged.connect(
            lambda: self.language_changed.emit(str(self.language_combo.currentData()))
        )
        self.price_duration.valueChanged.connect(self._on_price_duration_changed)
        self.feedback_duration.valueChanged.connect(self._on_feedback_duration_changed)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.gamma_preset_combo.currentIndexChanged.connect(self._on_gamma_preset_changed)

    def _section(self, title: str) -> tuple[QFrame, QGridLayout]:
        frame = QFrame()
        frame.setObjectName("raidSection")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(12, 10, 12, 11)
        outer.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("raidSectionTitle")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(1, 1)
        outer.addWidget(label)
        outer.addLayout(grid)
        return frame, grid

    def sync(
        self,
        config: dict[str, Any],
        presets: list[dict[str, Any]],
        status: str,
        gamma_active: bool = False,
    ) -> None:
        self._loading = True
        try:
            self.status_label.setText(status)
            self._set_combo_data(
                self.game_mode_combo,
                str(config.get("price_game_mode_default", "pve")),
            )
            self._set_combo_data(
                self.language_combo,
                str(config.get("item_display_language", "zh")),
            )
            self.price_duration.setValue(int(config.get("price_overlay_seconds", 10)))
            self.feedback_duration.setValue(int(config.get("feedback_overlay_seconds", 6)))
            opacity = int(config.get("raid_panel_opacity", 84))
            self.opacity_slider.setValue(max(55, min(100, opacity)))
            self._presets = [dict(preset) for preset in presets]
            with QSignalBlocker(self.gamma_preset_combo):
                self.gamma_preset_combo.clear()
                for preset in self._presets:
                    self.gamma_preset_combo.addItem(str(preset.get("name", "Unnamed")))
                active = str(config.get("display_filter_active_preset", ""))
                index = self.gamma_preset_combo.findText(active)
                self.gamma_preset_combo.setCurrentIndex(max(0, index))
            gamma_enabled = bool(self._presets)
            self.gamma_preset_combo.setEnabled(gamma_enabled)
            for slider in self._gamma_sliders.values():
                slider.setEnabled(gamma_enabled)
            self.gamma_restore_button.setEnabled(gamma_enabled)
            self.gamma_toggle_button.setEnabled(gamma_enabled)
            with QSignalBlocker(self.gamma_toggle_button):
                self.gamma_toggle_button.setChecked(gamma_enabled and gamma_active)
            self._update_gamma_toggle_text()
            if not gamma_enabled:
                self.set_gamma_status("Gamma 功能未启用或没有可用方案。", error=True)
            elif gamma_active:
                self.set_gamma_status("画面增强已开启；方案和滑条会实时生效。")
            else:
                self.set_gamma_status("点击开启后，方案和滑条才会修改画面。")
            self._load_selected_gamma_preset()
            self._set_window_opacity(opacity)
        finally:
            self._loading = False

    def toggle(self) -> bool:
        if self.isVisible():
            self.hide()
            return False
        self._position_on_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        return True

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        with QSignalBlocker(combo):
            index = combo.findData(value)
            combo.setCurrentIndex(max(0, index))

    def _on_opacity_changed(self, value: int) -> None:
        self.opacity_value.setText(f"{value}%")
        self._set_window_opacity(value)
        if not self._loading:
            self.panel_opacity_changed.emit(value)

    def _on_price_duration_changed(self, value: int) -> None:
        if not self._loading:
            self.price_duration_changed.emit(value)

    def _on_feedback_duration_changed(self, value: int) -> None:
        if not self._loading:
            self.feedback_duration_changed.emit(value)

    def _set_window_opacity(self, value: int) -> None:
        self.setWindowOpacity(max(0.55, min(1.0, value / 100.0)))

    def _on_gamma_preset_changed(self) -> None:
        self._load_selected_gamma_preset()
        if not self._loading and self.gamma_toggle_button.isChecked():
            self.gamma_values_changed.emit(self.gamma_values())

    def _load_selected_gamma_preset(self) -> None:
        index = self.gamma_preset_combo.currentIndex()
        if index < 0 or index >= len(self._presets):
            return
        preset = self._presets[index]
        blockers = [QSignalBlocker(slider) for slider in self._gamma_sliders.values()]
        try:
            for key, (_label, minimum, maximum, scale, _decimals) in GAMMA_CONTROLS.items():
                value = _float_value(preset.get(key), 1.0 if key != "black_lift" else 0.0)
                self._gamma_sliders[key].setValue(
                    max(minimum, min(maximum, int(round(value * scale))))
                )
                self._update_gamma_label(key)
        finally:
            del blockers

    def _on_gamma_slider_changed(self) -> None:
        for key in self._gamma_sliders:
            self._update_gamma_label(key)
        if not self._loading and self.gamma_toggle_button.isChecked():
            self.gamma_values_changed.emit(self.gamma_values())

    def _on_gamma_enabled_changed(self, checked: bool) -> None:
        self._update_gamma_toggle_text()
        if not self._loading:
            self.gamma_enabled_changed.emit(bool(checked))

    def _update_gamma_toggle_text(self) -> None:
        if self.gamma_toggle_button.isChecked():
            self.gamma_toggle_button.setText("画面增强：已开启（滑条实时生效）")
        else:
            self.gamma_toggle_button.setText("画面增强：已关闭（点击开启）")

    def set_gamma_active(self, active: bool) -> None:
        with QSignalBlocker(self.gamma_toggle_button):
            self.gamma_toggle_button.setChecked(bool(active))
        self._update_gamma_toggle_text()

    def set_gamma_status(self, message: str, *, error: bool = False) -> None:
        self.gamma_status_label.setText(str(message))
        color = "#FF8C8C" if error else "#8F9AA8"
        self.gamma_status_label.setStyleSheet(f"color: {color};")

    def _update_gamma_label(self, key: str) -> None:
        _label, _minimum, _maximum, scale, decimals = GAMMA_CONTROLS[key]
        value = self._gamma_sliders[key].value() / scale
        self._gamma_values[key].setText(f"{value:.{decimals}f}")

    def gamma_values(self) -> dict[str, object]:
        values: dict[str, object] = {
            "name": self.gamma_preset_combo.currentText() or "Raid Custom",
            "description": "局内控制窗实时调节",
        }
        for key, (_label, _minimum, _maximum, scale, decimals) in GAMMA_CONTROLS.items():
            values[key] = round(self._gamma_sliders[key].value() / scale, decimals)
        return values

    def _position_on_screen(self) -> None:
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return
        self.adjustSize()
        rect = screen.availableGeometry()
        self.move(rect.right() - self.width() - 28, rect.top() + 70)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()


class RaidLogOverlay(QWidget):
    def __init__(self, max_lines: int = 200) -> None:
        super().__init__()
        self.setWindowTitle("Raid Log")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(620, 250)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("raidPanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 11)
        layout.setSpacing(4)
        header = _DragHandle()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel("SYSTEM  /  RAID LOG")
        title.setObjectName("raidPanelEyebrow")
        hint = QLabel("滚轮查看 · 拖动标题移动")
        hint.setObjectName("raidPanelMeta")
        close_button = QPushButton("×")
        close_button.setObjectName("raidCloseButton")
        close_button.setToolTip("关闭局内日志窗")
        close_button.clicked.connect(self.hide)
        header_layout.addWidget(title)
        header_layout.addWidget(hint, 1)
        header_layout.addWidget(close_button)
        self.text = QPlainTextEdit()
        self.text.setObjectName("raidLogText")
        self.text.setReadOnly(True)
        self.text.document().setMaximumBlockCount(max(20, int(max_lines)))
        layout.addWidget(header)
        layout.addWidget(self.text, 1)
        outer.addWidget(card)
        self.setStyleSheet(RAID_OVERLAY_STYLESHEET)

    def append_line(self, line: str) -> None:
        bar = self.text.verticalScrollBar()
        previous_position = bar.value()
        follow_tail = bar.value() >= bar.maximum() - 4
        self.text.appendPlainText(str(line))
        if follow_tail:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(previous_position)

    def set_max_lines(self, value: int) -> None:
        self.text.document().setMaximumBlockCount(max(20, int(value)))

    def set_opacity_percent(self, value: int) -> None:
        self.setWindowOpacity(max(0.45, min(1.0, int(value) / 100.0)))

    def toggle(self) -> bool:
        if self.isVisible():
            self.hide()
            return False
        self._position_on_screen()
        self.show()
        self.raise_()
        return True

    def _position_on_screen(self) -> None:
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        self.move(rect.left() + 24, rect.bottom() - self.height() - 54)


class _DragHandle(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self._drag_offset: QPoint | None = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            )
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


def _float_value(value: object, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
