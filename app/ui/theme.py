from __future__ import annotations


APP_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #0D1117;
    color: #E8ECF2;
}
QWidget#appSidebar {
    background-color: #0A0F15;
    border: 1px solid #202A35;
    border-radius: 11px;
}
QLabel#brandEyebrow {
    color: #C9AD78;
    font-size: 10px;
    font-weight: 700;
}
QLabel#brandTitle {
    color: #F4F1EA;
    font-size: 18px;
    font-weight: 700;
}
QLabel#brandMeta {
    color: #6F7B89;
    font-size: 10px;
}
QPushButton#navButton {
    min-height: 34px;
    padding-left: 13px;
    text-align: left;
    color: #AEB7C2;
    background-color: transparent;
    border-color: transparent;
}
QPushButton#navButton:hover {
    color: #F1F3F6;
    background-color: #151D27;
    border-color: #293544;
}
QPushButton#navButton:checked {
    color: #F5E8CF;
    background-color: #202A36;
    border: 1px solid #6D5D41;
}
QMenuBar, QMenu {
    background-color: #111720;
    color: #E8ECF2;
    border: 1px solid #283240;
}
QMenu::item:selected {
    background-color: #26303C;
}
QLabel, QCheckBox, QRadioButton, QGroupBox {
    color: #E8ECF2;
}
QGroupBox {
    margin-top: 12px;
    padding: 14px 12px 12px 12px;
    border: 1px solid #283240;
    border-radius: 9px;
    background-color: #121821;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #C9AD78;
}
QPushButton {
    min-height: 30px;
    padding: 3px 12px;
    border: 1px solid #354252;
    border-radius: 7px;
    background-color: #1A222D;
    color: #F2F4F7;
}
QPushButton:hover {
    background-color: #253140;
    border-color: #C9AD78;
}
QPushButton:pressed, QPushButton:checked {
    background-color: #344154;
}
QPushButton:disabled {
    color: #687483;
    background-color: #141A22;
    border-color: #222B36;
}
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {
    min-height: 28px;
    padding: 2px 8px;
    border: 1px solid #313D4C;
    border-radius: 6px;
    background-color: #0F151D;
    color: #EEF1F5;
    selection-background-color: #8D7346;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #121923;
    color: #EEF1F5;
    selection-background-color: #364354;
    border: 1px solid #313D4C;
}
QTableWidget, QTreeView {
    background-color: #0F151D;
    alternate-background-color: #131B25;
    color: #E6EAF0;
    gridline-color: #26313E;
    border: 1px solid #2C3846;
    border-radius: 7px;
    selection-background-color: #344355;
}
QHeaderView::section {
    padding: 6px 8px;
    color: #C9D0DA;
    background-color: #18212C;
    border: none;
    border-right: 1px solid #2B3744;
    border-bottom: 1px solid #2B3744;
}
QTabWidget::pane {
    border: 1px solid #283240;
    border-radius: 8px;
    background-color: #111720;
}
QTabBar::tab {
    padding: 8px 15px;
    color: #9EA8B5;
    background-color: #111720;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #F1E2C2;
    border-bottom-color: #C9AD78;
}
QSlider::groove:horizontal {
    height: 4px;
    border-radius: 2px;
    background: #303A47;
}
QSlider::sub-page:horizontal {
    border-radius: 2px;
    background: #B79A67;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: #E7D4AC;
}
QScrollBar:vertical {
    width: 9px;
    background: transparent;
}
QScrollBar::handle:vertical {
    min-height: 28px;
    border-radius: 4px;
    background: #3C4857;
}
QToolTip {
    padding: 5px 7px;
    color: #F4F0E8;
    background-color: #171E27;
    border: 1px solid #596779;
}
"""


def apply_app_theme(application: object, font_size: object = 11) -> None:
    try:
        safe_font_size = max(9, min(18, int(font_size)))
    except (TypeError, ValueError):
        safe_font_size = 11
    set_style = getattr(application, "setStyle", None)
    if callable(set_style):
        set_style("Fusion")
    get_font = getattr(application, "font", None)
    set_font = getattr(application, "setFont", None)
    if callable(get_font) and callable(set_font):
        font = get_font()
        set_point_size = getattr(font, "setPointSize", None)
        if callable(set_point_size):
            set_point_size(safe_font_size)
            set_font(font)
    set_stylesheet = getattr(application, "setStyleSheet", None)
    if callable(set_stylesheet):
        set_stylesheet(APP_STYLESHEET)
