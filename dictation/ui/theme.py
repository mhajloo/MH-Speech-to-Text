"""Colors, fonts and the Qt stylesheet. Light and dark palettes follow Windows
unless the user picks one; every widget reads colors from the active palette."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication

from ..paths import FONTS_DIR

FONT_FAMILY = "Vazirmatn"
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

LIGHT = {
    "bg": "#F5F4FA", "surface": "#FFFFFF", "surface2": "#F1EFF8", "border": "#E6E3F1",
    "text": "#1C1A29", "muted": "#6E6A86", "faint": "#A6A2BD",
    "primary": "#6C4DFF", "primary_hover": "#5B3DF0", "primary_soft": "#EFEBFF",
    "accent": "#21C3E6", "success": "#1FAF6A", "warning": "#E89B0C", "danger": "#E5484D",
    "sidebar": "#FFFFFF", "input": "#FFFFFF", "track": "#E3E0EF",
}
DARK = {
    "bg": "#131120", "surface": "#1C192C", "surface2": "#252237", "border": "#2F2B45",
    "text": "#EEEDF7", "muted": "#A7A3C2", "faint": "#6E6A86",
    "primary": "#8B73FF", "primary_hover": "#9D89FF", "primary_soft": "#2A2447",
    "accent": "#2CCBEF", "success": "#2BC77D", "warning": "#F5B32B", "danger": "#FF6369",
    "sidebar": "#171527", "input": "#221F34", "track": "#35304D",
}

_palette = LIGHT


def fa(value) -> str:
    """Persian digits for display."""
    return str(value).translate(FA_DIGITS)


def c(name: str) -> str:
    return _palette[name]


def is_dark() -> bool:
    return _palette is DARK


def load_fonts():
    for f in sorted(FONTS_DIR.glob("Vazirmatn-*.ttf")):
        QFontDatabase.addApplicationFont(str(f))


def font(size=10.0, weight=400) -> QFont:
    """weight: CSS-style number (400 regular, 500 medium, 600 semibold, 700 bold)."""
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def system_is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    return hasattr(hints, "colorScheme") and hints.colorScheme() == Qt.ColorScheme.Dark


def apply(app, theme="system"):
    """Activate a palette and install the stylesheet on the application."""
    global _palette
    dark = theme == "dark" or (theme == "system" and system_is_dark())
    _palette = DARK if dark else LIGHT
    app.setFont(font(10))
    app.setStyleSheet(stylesheet())


def stylesheet() -> str:
    p = _palette
    return f"""
    * {{ font-family: "{FONT_FAMILY}"; }}
    QWidget {{ color: {p['text']}; font-size: 10pt; }}
    QMainWindow, QDialog, #Window {{ background: {p['bg']}; }}
    QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']};
               border-radius: 8px; padding: 6px 10px; }}

    #Sidebar {{ background: {p['sidebar']}; border-left: 1px solid {p['border']}; }}
    #AppName {{ font-size: 12.5pt; font-weight: 700; }}
    #AppTagline, #Muted {{ color: {p['muted']}; }}
    #Faint {{ color: {p['faint']}; font-size: 9pt; }}
    #PageTitle {{ font-size: 16pt; font-weight: 700; }}
    #PageSubtitle {{ color: {p['muted']}; font-size: 10pt; }}
    #CardTitle {{ font-size: 11pt; font-weight: 600; }}
    #CardText {{ color: {p['muted']}; font-size: 9.5pt; }}
    #Hint {{ color: {p['muted']}; font-size: 9pt; }}
    #Warning {{ color: {p['warning']}; font-size: 9.5pt; }}
    #Danger {{ color: {p['danger']}; font-size: 9.5pt; }}
    #Success {{ color: {p['success']}; font-size: 9.5pt; }}

    #Card {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px; }}
    #Separator {{ background: {p['border']}; max-height: 1px; min-height: 1px; }}

    QPushButton {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 10px;
                  padding: 7px 16px; font-weight: 500; }}
    QPushButton:hover {{ border-color: {p['primary']}; }}
    QPushButton:pressed {{ background: {p['primary_soft']}; }}
    QPushButton:disabled {{ color: {p['faint']}; }}
    QPushButton#Primary {{ color: #ffffff; border: none; font-weight: 600;
        background: qlineargradient(x1:1, y1:0, x2:0, y2:1, stop:0 {p['primary']}, stop:1 {p['accent']}); }}
    QPushButton#Primary:hover {{ background: qlineargradient(x1:1, y1:0, x2:0, y2:1,
        stop:0 {p['primary_hover']}, stop:1 {p['accent']}); }}
    QPushButton#Primary:disabled {{ background: {p['track']}; color: {p['faint']}; }}
    QPushButton#Link {{ background: transparent; border: none; color: {p['primary']}; padding: 2px 4px; }}
    QPushButton#Link:hover {{ text-decoration: underline; }}
    QPushButton#Danger {{ color: {p['danger']}; }}

    QPushButton#Nav {{ background: transparent; border: none; border-radius: 10px; padding: 10px 14px;
                      text-align: right; color: {p['muted']}; font-size: 10.5pt; }}
    QPushButton#Nav:hover {{ background: {p['surface2']}; color: {p['text']}; }}
    QPushButton#Nav:checked {{ background: {p['primary_soft']}; color: {p['primary']}; font-weight: 600; }}

    QPushButton#Segment {{ background: transparent; border: none; border-radius: 8px; padding: 6px 14px;
                          color: {p['muted']}; }}
    QPushButton#Segment:checked {{ background: {p['surface']}; color: {p['text']}; font-weight: 600; }}
    #SegmentBar {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 10px; }}

    QLineEdit, QComboBox, QSpinBox {{ background: {p['input']}; border: 1px solid {p['border']};
        border-radius: 9px; padding: 6px 10px; selection-background-color: {p['primary']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {p['primary']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox QAbstractItemView {{ background: {p['surface']}; border: 1px solid {p['border']};
        border-radius: 8px; padding: 4px; selection-background-color: {p['primary_soft']};
        selection-color: {p['text']}; outline: none; }}

    QTableWidget {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px;
        gridline-color: {p['border']}; selection-background-color: {p['primary_soft']};
        selection-color: {p['text']}; }}
    QHeaderView::section {{ background: {p['surface2']}; border: none; border-bottom: 1px solid {p['border']};
        padding: 6px; font-weight: 600; color: {p['muted']}; }}
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ border-radius: 10px; }}

    QProgressBar {{ background: {p['track']}; border: none; border-radius: 6px; height: 12px;
        text-align: center; color: transparent; }}
    QProgressBar::chunk {{ border-radius: 6px;
        background: qlineargradient(x1:1, y1:0, x2:0, y2:0, stop:0 {p['primary']}, stop:1 {p['accent']}); }}

    QRadioButton {{ spacing: 8px; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 9px; border: 2px solid {p['faint']};
        background: {p['input']}; }}
    QRadioButton::indicator:checked {{ border: 2px solid {p['primary']};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                    stop:0 {p['primary']}, stop:0.55 {p['primary']}, stop:0.62 {p['input']}, stop:1 {p['input']}); }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 2px solid {p['faint']};
        background: {p['input']}; }}
    QCheckBox::indicator:checked {{ background: {p['primary']}; border-color: {p['primary']}; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p['track']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p['faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QMenu {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px; padding: 6px; }}
    QMenu::item {{ padding: 8px 18px 8px 22px; border-radius: 8px; }}
    QMenu::item:selected {{ background: {p['primary_soft']}; color: {p['text']}; }}
    QMenu::item:disabled {{ color: {p['muted']}; }}
    QMenu::separator {{ height: 1px; background: {p['border']}; margin: 5px 8px; }}
    QMenu::icon {{ padding-right: 10px; }}
    """
