"""Chrome Client's theme system, shared look: Modrinth-style dark UI, fully recolorable, glass buttons."""
from string import Template

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

import config

ICON_DIR = config.BASE / "theme_icons"

DEFAULT_THEME = {"bg": "#16181c", "surface": "#26292f", "accent": "#1bd96a", "text": "#ecf0f1"}
ACCENTS = {"Green": "#1bd96a", "Pink": "#ff5fa8", "Blue": "#3b9bff",
           "Orange": "#ff8a2b", "Red": "#ff4d4d", "Purple": "#a56bff"}


def tinted_theme(accent):
    h = QColor(accent).hsvHueF()
    return {"bg": QColor.fromHsvF(h, 0.40, 0.10).name(),
            "surface": QColor.fromHsvF(h, 0.32, 0.17).name(),
            "accent": accent, "text": "#f3eef0"}


PRESETS = {"Classic": dict(DEFAULT_THEME), **{n: tinted_theme(c) for n, c in ACCENTS.items()}}


def mix(a, b, t):
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() * (1 - t) + cb.red() * t),
                  round(ca.green() * (1 - t) + cb.green() * t),
                  round(ca.blue() * (1 - t) + cb.blue() * t)).name()


def rgba(c, a):
    c = QColor(c)
    return f"rgba({c.red()},{c.green()},{c.blue()},{a})"


def luminance(c):
    c = QColor(c)
    return 0.2126 * c.red() / 255 + 0.7152 * c.green() / 255 + 0.0722 * c.blue() / 255


def clean_theme(t):
    out = dict(DEFAULT_THEME)
    for k in out:
        if isinstance(t, dict) and QColor(str(t.get(k, ""))).isValid():
            out[k] = QColor(t[k]).name()
    return out


def _draw_icon(path, draw):
    pm = QPixmap(48, 48)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(p)
    p.end()
    pm.save(str(path))


def make_icons(color_chev, color_check):
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    chev = ICON_DIR / f"chev_{color_chev[1:]}.png"
    check = ICON_DIR / f"check_{color_check[1:]}.png"

    def d_chev(p):
        p.setPen(QPen(QColor(color_chev), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(11, 18), QPointF(24, 31))
        p.drawLine(QPointF(24, 31), QPointF(37, 18))

    def d_check(p):
        p.setPen(QPen(QColor(color_check), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(12, 25), QPointF(21, 34))
        p.drawLine(QPointF(21, 34), QPointF(37, 15))

    if not chev.exists():
        _draw_icon(chev, d_chev)
    if not check.exists():
        _draw_icon(check, d_check)
    return chev.as_posix(), check.as_posix()


QSS = Template("""
* { color: $text; font-size: ${fsize}px; font-family: '$font', 'Segoe UI', sans-serif; }
QMainWindow { background: $bg; }
QWidget#sidebar { background: $sidebar; border-right: 1px solid $border; }
QLabel { background: transparent; border: none; }
QLabel[muted="true"] { color: $muted; }
QLabel[h1="true"] { font-size: 24px; font-weight: 700; }
QLabel[h2="true"] { font-size: 15px; font-weight: 600; }
QLabel[brand="true"] { font-size: 18px; font-weight: 800; color: $accent; }
QLabel[small="true"] { font-size: 11px; font-weight: 700; color: $accent; letter-spacing: 1px; }
QLabel#gameicon { background: $surface_hi; border-radius: 10px; }
QLabel#avatar { background: $accent; color: $accent_text; border-radius: 18px; font-weight: 700; font-size: 15px; }
QFrame[card="true"] { background: $card; border: 1px solid $border; border-radius: 12px; }
QFrame[chip="true"] { background: $chip; border: 1px solid $border; border-radius: 10px; }
QPushButton { background: $glass; border: 1px solid $glass_border; border-radius: 8px; padding: 8px 16px; font-weight: 600; }
QPushButton:hover { background: $glass_hover; }
QPushButton:pressed { background: $glass_press; }
QPushButton:disabled { color: $muted; }
QPushButton[primary="true"] { background: $accent_glass; border: 1px solid $accent_glass_border; color: $text; font-size: 17px; }
QPushButton[primary="true"]:hover { background: $accent_glass_hover; }
QPushButton[primary="true"]:disabled { background: $glass; border-color: $glass_border; color: $muted; }
QPushButton[nav="true"] { background: transparent; border: 1px solid transparent; text-align: left; padding: 10px 14px; color: $muted; }
QPushButton[nav="true"]:hover { background: $glass; color: $text; }
QPushButton[nav="true"]:checked { background: $accent_soft; border: 1px solid $accent_soft_border; color: $accent; }
QPushButton[ghost="true"] { background: transparent; border: 1px solid $glass_border; }
QPushButton[ghost="true"]:hover { background: $glass; }
QLineEdit, QPlainTextEdit, QComboBox { background: $field; border: 1px solid $border; border-radius: 8px; padding: 8px 12px; selection-background-color: $accent; selection-color: $accent_text; }
QPlainTextEdit { font-family: 'Cascadia Mono', 'Consolas', monospace; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border: 1px solid $accent; }
QComboBox { padding-right: 30px; }
QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow { image: url("$chev"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border; selection-background-color: $accent_soft; selection-color: $accent; outline: 0; padding: 4px; }
QCheckBox { spacing: 10px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 6px; border: 2px solid $border2; background: $field; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }
QProgressBar { background: $field; border: none; border-radius: 5px; max-height: 10px; min-height: 10px; color: transparent; }
QProgressBar::chunk { background: $accent; border-radius: 5px; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border2; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSlider::groove:horizontal { height: 8px; background: $field; border-radius: 4px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 4px; }
QSlider::handle:horizontal { background: $accent; width: 18px; height: 18px; margin: -5px 0; border-radius: 9px; }
QMenu { background: $surface; border: 1px solid $border; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: $accent_soft; color: $accent; }
QFrame[tile="true"] { background: $card; border: 1px solid $border; border-radius: 12px; }
QFrame[tile="true"]:hover { border: 1px solid $accent; background: $tile_hover; }
QFrame[tile="true"][selected="true"] { border: 2px solid $accent; }
QFrame[server="true"] { background: $card; border: 1px solid $border; border-radius: 12px; }
QFrame[server="true"]:hover { border: 1px solid $accent_soft_border; background: $tile_hover; }
QLabel[pill="true"] { background: $accent_soft; color: $accent; border-radius: 10px; padding: 3px 10px; font-weight: 600; }
QLabel[stat="true"] { background: $glass; border: 1px solid $glass_border; border-radius: 8px; padding: 3px 9px; color: $muted; font-weight: 600; }
QLabel#render { background: qradialgradient(cx:0.5, cy:0.42, radius:0.62, fx:0.5, fy:0.42, stop:0 $accent_glow, stop:1 transparent); border-radius: 12px; }
QLabel#gamebig { background: $surface_hi; border-radius: 14px; }
QPushButton[seg="true"] { padding: 6px 18px; }
QPushButton[seg="true"]:checked { background: $accent_glass; border: 1px solid $accent_glass_border; }
QPushButton[join="true"] { background: $accent_glass; border: 1px solid $accent_glass_border; padding: 8px 22px; }
QPushButton[join="true"]:hover { background: $accent_glass_hover; }
QProgressBar[thin="true"] { max-height: 6px; min-height: 6px; border-radius: 3px; }
QProgressBar[thin="true"]::chunk { border-radius: 3px; }
QFrame[overlay="true"] { background: $bg; border: 1px solid $border2; }
QToolTip, QMessageBox, QDialog { background: $surface; color: $text; border: 1px solid $border; }
""")


def build_qss(theme, has_image=False, font="Segoe UI", size=13):
    t = clean_theme(theme)
    bg, surf, acc, text = t["bg"], t["surface"], t["accent"], t["text"]
    accent_text = "#0b0b0d" if luminance(acc) > 0.5 else "#ffffff"
    chev, check = make_icons(text, accent_text)
    # with a background image, panels go see-through so the image shows
    a_card, a_side = (0.72, 0.80) if has_image else (1.0, 1.0)
    font = (font or "Segoe UI").replace("'", "")
    return QSS.substitute(
        font=font, fsize=max(10, min(18, int(size or 13))),
        bg=bg, surface=surf, text=text, accent=acc, accent_text=accent_text,
        sidebar=rgba(surf, a_side), card=rgba(surf, a_card), chip=rgba(bg, 0.6 if has_image else 1.0),
        field=rgba(bg, 0.75), surface_hi=mix(surf, text, 0.07),
        border=mix(surf, text, 0.12), border2=mix(surf, text, 0.28),
        muted=mix(text, bg, 0.45),
        glass=rgba(text, 0.07), glass_hover=rgba(text, 0.12), glass_press=rgba(text, 0.04),
        glass_border=rgba(text, 0.16),
        accent_glass=rgba(acc, 0.42), accent_glass_hover=rgba(acc, 0.56), accent_glass_border=rgba(acc, 0.85),
        overlay_bg=rgba(bg, 0.97),
        tile_hover=rgba(mix(surf, text, 0.05), a_card), accent_glow=rgba(acc, 0.30),
        accent_soft=rgba(acc, 0.16), accent_soft_border=rgba(acc, 0.35),
        chev=chev, check=check)
