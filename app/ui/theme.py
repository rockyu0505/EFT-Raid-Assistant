from __future__ import annotations

from typing import Final

from PySide6.QtCore import QDir

from app.config import RESOURCE_DIR


THEME_LABELS: Final[dict[str, str]] = {
    "light": "浅色",
    "dark": "深色",
    "night_blue": "夜蓝",
    "sakura_pink": "樱粉",
    "high_contrast": "高对比度",
}


_THEME_COLORS: Final[dict[str, dict[str, str]]] = {
    "light": {
        "window": "#F2F4F7",
        "sidebar": "#FFFFFF",
        "surface": "#FFFFFF",
        "surface_alt": "#F7F8FA",
        "input": "#FFFFFF",
        "header": "#E8ECF1",
        "text": "#1C2530",
        "text_strong": "#101720",
        "muted": "#667281",
        "subtle": "#4D5968",
        "border": "#C8D0DA",
        "border_strong": "#AAB5C2",
        "accent": "#8A641F",
        "accent_soft": "#F0E2C3",
        "accent_text": "#5E4212",
        "hover": "#E9EEF4",
        "selected": "#D8E4F2",
        "disabled": "#929CA8",
        "disabled_bg": "#E8EBEF",
        "error": "#9B4A00",
        "scroll": "#A3ADBA",
        "tooltip": "#FFFFFF",
    },
    "dark": {
        "window": "#0D1117",
        "sidebar": "#0A0F15",
        "surface": "#121821",
        "surface_alt": "#131B25",
        "input": "#0F151D",
        "header": "#18212C",
        "text": "#E8ECF2",
        "text_strong": "#F4F1EA",
        "muted": "#8F9AA8",
        "subtle": "#AEB7C2",
        "border": "#283240",
        "border_strong": "#354252",
        "accent": "#C9AD78",
        "accent_soft": "#202A36",
        "accent_text": "#F5E8CF",
        "hover": "#253140",
        "selected": "#344355",
        "disabled": "#687483",
        "disabled_bg": "#141A22",
        "error": "#E8C47A",
        "scroll": "#3C4857",
        "tooltip": "#171E27",
    },
    "night_blue": {
        "window": "#0C1624",
        "sidebar": "#091321",
        "surface": "#112238",
        "surface_alt": "#162A43",
        "input": "#0E1B2C",
        "header": "#1A3150",
        "text": "#EAF3FF",
        "text_strong": "#FFFFFF",
        "muted": "#9BB0C8",
        "subtle": "#BDD0E6",
        "border": "#294868",
        "border_strong": "#3A5E82",
        "accent": "#66B6FF",
        "accent_soft": "#173B61",
        "accent_text": "#DDF1FF",
        "hover": "#203C5B",
        "selected": "#2B5278",
        "disabled": "#71869B",
        "disabled_bg": "#122033",
        "error": "#FF9B9B",
        "scroll": "#41698D",
        "tooltip": "#102033",
    },
    "sakura_pink": {
        "window": "#F9F1F5",
        "sidebar": "#FFF9FC",
        "surface": "#FFF9FC",
        "surface_alt": "#FBEFF5",
        "input": "#FFFBFD",
        "header": "#F3DDE8",
        "text": "#3A2430",
        "text_strong": "#24151D",
        "muted": "#7A6170",
        "subtle": "#654856",
        "border": "#DFC5D2",
        "border_strong": "#CFA8BB",
        "accent": "#B94F7E",
        "accent_soft": "#F4D7E5",
        "accent_text": "#742344",
        "hover": "#F5E2EB",
        "selected": "#EBC8D8",
        "disabled": "#A48B98",
        "disabled_bg": "#EFE2E8",
        "error": "#A33B42",
        "scroll": "#C797AE",
        "tooltip": "#FFF9FC",
    },
    "high_contrast": {
        "window": "#000000",
        "sidebar": "#000000",
        "surface": "#000000",
        "surface_alt": "#101010",
        "input": "#000000",
        "header": "#000000",
        "text": "#FFFFFF",
        "text_strong": "#FFFFFF",
        "muted": "#E6E6E6",
        "subtle": "#FFFFFF",
        "border": "#FFFFFF",
        "border_strong": "#FFFFFF",
        "accent": "#FFD800",
        "accent_soft": "#242000",
        "accent_text": "#FFD800",
        "hover": "#222222",
        "selected": "#004C99",
        "disabled": "#B0B0B0",
        "disabled_bg": "#171717",
        "error": "#FFEA00",
        "scroll": "#FFFFFF",
        "tooltip": "#000000",
    },
}


def normalize_theme(value: object) -> str:
    theme = str(value or "").strip().casefold()
    return theme if theme in THEME_LABELS else "light"


def _base_stylesheet(theme: str) -> str:
    normalized_theme = normalize_theme(theme)
    c = _THEME_COLORS[normalized_theme]
    checkmark_name = (
        "checkbox_check_light.xpm"
        if normalized_theme in {"light", "sakura_pink"}
        else "checkbox_check_dark.xpm"
    )
    QDir.addSearchPath("eftassets", str((RESOURCE_DIR / "assets").resolve()))
    checkmark_url = f"eftassets:{checkmark_name}"
    return f"""
QMainWindow, QDialog {{
    background-color: {c['window']};
    color: {c['text']};
}}
QWidget#appSidebar {{
    background-color: {c['sidebar']};
    border: 1px solid {c['border']};
    border-radius: 11px;
}}
QLabel#brandEyebrow {{
    color: {c['accent']};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#brandTitle {{
    color: {c['text_strong']};
    font-size: 18px;
    font-weight: 700;
}}
QLabel#brandMeta {{
    color: {c['muted']};
    font-size: 10px;
}}
QLabel#dataErrorLabel {{ color: {c['error']}; }}
QPushButton#navButton {{
    min-height: 34px;
    padding-left: 13px;
    text-align: left;
    color: {c['subtle']};
    background-color: transparent;
    border-color: transparent;
}}
QPushButton#navButton:hover {{
    color: {c['text_strong']};
    background-color: {c['hover']};
    border-color: {c['border']};
}}
QPushButton#navButton:checked {{
    color: {c['accent_text']};
    background-color: {c['accent_soft']};
    border: 1px solid {c['accent']};
}}
QMenuBar, QMenu {{
    background-color: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['border']};
}}
QMenu::item:selected {{ background-color: {c['selected']}; }}
QLabel, QCheckBox, QRadioButton, QGroupBox {{ color: {c['text']}; }}
QCheckBox {{
    min-height: 24px;
    spacing: 9px;
}}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {c['border_strong']};
    border-radius: 5px;
    background-color: {c['input']};
}}
QCheckBox::indicator:unchecked:hover {{
    border-color: {c['accent']};
    background-color: {c['hover']};
}}
QCheckBox::indicator:checked {{
    border-color: {c['accent']};
    background-color: {c['accent']};
    image: url({checkmark_url});
}}
QCheckBox::indicator:checked:hover {{
    border-color: {c['accent_text']};
}}
QCheckBox::indicator:disabled {{
    border-color: {c['border']};
    background-color: {c['disabled_bg']};
}}
QCheckBox#featureChoice {{
    min-height: 32px;
    padding: 5px 10px;
    border: 1px solid {c['border']};
    border-radius: 8px;
    background-color: {c['surface_alt']};
}}
QCheckBox#featureChoice:hover {{
    border-color: {c['accent']};
    background-color: {c['hover']};
}}
QCheckBox#featureChoice:checked {{
    color: {c['accent_text']};
    background-color: {c['accent_soft']};
    border-color: {c['accent']};
    font-weight: 600;
}}
QGroupBox {{
    margin-top: 12px;
    padding: 14px 12px 12px 12px;
    border: 1px solid {c['border']};
    border-radius: 9px;
    background-color: {c['surface']};
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {c['accent']};
}}
QPushButton {{
    min-height: 30px;
    padding: 3px 12px;
    border: 1px solid {c['border_strong']};
    border-radius: 7px;
    background-color: {c['surface_alt']};
    color: {c['text_strong']};
}}
QPushButton:hover {{
    background-color: {c['hover']};
    border-color: {c['accent']};
}}
QPushButton:pressed, QPushButton:checked {{ background-color: {c['selected']}; }}
QPushButton:disabled {{
    color: {c['disabled']};
    background-color: {c['disabled_bg']};
    border-color: {c['border']};
}}
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {{
    min-height: 28px;
    padding: 2px 8px;
    border: 1px solid {c['border_strong']};
    border-radius: 6px;
    background-color: {c['input']};
    color: {c['text']};
    selection-background-color: {c['selected']};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {c['surface']};
    color: {c['text']};
    selection-background-color: {c['selected']};
    border: 1px solid {c['border_strong']};
}}
QTableWidget, QTreeView {{
    background-color: {c['input']};
    alternate-background-color: {c['surface_alt']};
    color: {c['text']};
    gridline-color: {c['border']};
    border: 1px solid {c['border_strong']};
    border-radius: 7px;
    selection-background-color: {c['selected']};
}}
QHeaderView {{ background-color: {c['header']}; }}
QHeaderView::section {{
    padding: 6px 8px;
    color: {c['text']};
    background-color: {c['header']};
    border: none;
    border-right: 1px solid {c['border']};
    border-bottom: 1px solid {c['border']};
}}
QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: 8px;
    background-color: {c['surface']};
}}
QTabBar::tab {{
    padding: 8px 15px;
    color: {c['muted']};
    background-color: {c['surface']};
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {c['accent_text']};
    border-bottom-color: {c['accent']};
}}
QSlider::groove:horizontal {{
    height: 4px;
    border-radius: 2px;
    background: {c['border_strong']};
}}
QSlider::sub-page:horizontal {{ border-radius: 2px; background: {c['accent']}; }}
QSlider::handle:horizontal {{
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: {c['accent_text']};
    border: 1px solid {c['accent']};
}}
QScrollBar:vertical {{ width: 10px; background: {c['surface']}; }}
QScrollBar:horizontal {{ height: 10px; background: {c['surface']}; }}
QScrollBar::handle:vertical {{
    min-height: 28px;
    border-radius: 4px;
    background: {c['scroll']};
}}
QScrollBar::handle:horizontal {{
    min-width: 28px;
    border-radius: 4px;
    background: {c['scroll']};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
    background: transparent;
}}
QAbstractScrollArea::corner {{
    background-color: {c['input']};
    border: none;
}}
QToolTip {{
    padding: 5px 7px;
    color: {c['text']};
    background-color: {c['tooltip']};
    border: 1px solid {c['border_strong']};
}}
"""


def _stylesheet_for_font_size(font_size: int, theme: str) -> str:
    tree_row_padding = max(3, round(font_size * 0.35))
    return (
        _base_stylesheet(theme)
        + f"""
QTreeView::item {{
    padding-top: {tree_row_padding}px;
    padding-bottom: {tree_row_padding}px;
}}
"""
    )


def apply_app_theme(
    application: object,
    font_size: object = 11,
    theme: object = "light",
) -> None:
    try:
        safe_font_size = max(9, min(18, int(font_size)))
    except (TypeError, ValueError):
        safe_font_size = 11
    safe_theme = normalize_theme(theme)
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
    set_property = getattr(application, "setProperty", None)
    if callable(set_property):
        set_property("uiTheme", safe_theme)
    set_stylesheet = getattr(application, "setStyleSheet", None)
    if callable(set_stylesheet):
        set_stylesheet(_stylesheet_for_font_size(safe_font_size, safe_theme))
