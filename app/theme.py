"""Palette, QSS stylesheet, and stateless widget factory helpers."""
import html
import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget,
)

# ── palette ──────────────────────────────────────────────────────────────────
P = {
    "bg":        "#0a0a0f",
    "sidebar":   "#0d0d14",
    "card":      "#14141c",
    "card2":     "#1a1a24",
    "card3":     "#20202e",
    "border":    "#252535",
    "border2":   "#353550",
    "text":      "#eeeef8",
    "text2":     "#a0a0c8",
    "text3":     "#6868a0",
    "indigo":    "#6d6df5",
    "indigo_d":  "#5252cc",
    "indigo_bg": "#181840",
    "green":     "#3dd68c",
    "green_bg":  "#0b2b1c",
    "amber":     "#f5a623",
    "amber_bg":  "#2a1800",
    "red":       "#f06a6a",
    "red_bg":    "#2a0c0c",
    "purple":    "#be7cf8",
    "purple_bg": "#1c0b33",
}
CAT = {
    "it":         ("#818cf8", "#1a1a44"),
    "wirtschaft": ("#fb923c", "#3a1400"),
}
APP_FONT  = "Segoe UI Variable"
MONO_FONT = "Consolas"


def _qss() -> str:
    return f"""
* {{ font-family: '{APP_FONT}', 'Segoe UI'; color: {P['text']}; outline: none; }}
QMainWindow, QWidget {{ background-color: {P['bg']}; }}
QDialog {{ background-color: {P['bg']}; }}
QSplitter::handle {{ background: {P['border']}; width: 2px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 7px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {P['border2']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {P['text3']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QPushButton {{ border: none; border-radius: 8px; padding: 6px 14px;
               font-size: 14px; font-weight: 600; color: {P['text']}; }}
QPushButton:disabled {{ color: {P['text3']}; }}
QLabel {{ background: transparent; }}
QLineEdit {{
    background: {P['card2']}; border: 1px solid {P['border']};
    border-radius: 8px; padding: 6px 10px; color: {P['text']}; font-size: 14px;
}}
QLineEdit:focus {{ border-color: {P['indigo']}; }}
QTextEdit {{
    background: {P['card2']}; border: 1px solid {P['border']};
    border-radius: 8px; color: {P['text2']}; font-size: 15px;
    selection-background-color: {P['indigo_bg']};
}}
QTextEdit:focus {{ border-color: {P['indigo']}; }}
QComboBox {{
    background: {P['card2']}; border: 1px solid {P['border']};
    border-radius: 8px; padding: 6px 12px; color: {P['text2']}; font-size: 14px;
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background: {P['card2']}; border: 1px solid {P['border2']};
    color: {P['text']}; selection-background-color: {P['indigo_bg']}; outline: none;
}}
QCheckBox {{ color: {P['text2']}; font-size: 14px; spacing: 6px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {P['border2']}; background: {P['card2']};
}}
QCheckBox::indicator:checked {{ background: {P['indigo']}; border-color: {P['indigo']}; }}
QProgressBar {{
    background: {P['card2']};
    border: 1px solid {P['border2']};
    border-radius: 6px;
    height: 30px;
    text-align: center;
    color: {P['text']};
    font-size: 12px;
    font-weight: 700;
    font-family: '{MONO_FONT}';
}}
QProgressBar::chunk {{
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2d2da0, stop:0.4 #5050d8, stop:0.7 {P['indigo']}, stop:1 #9090ff);
}}
QTabWidget::pane {{
    border: 1px solid {P['border']}; background: {P['card']}; border-radius: 14px;
    margin-top: -1px;
}}
QTabBar::tab {{
    background: {P['card2']}; color: {P['text2']};
    font-size: 14px; font-weight: 600;
    padding: 10px 24px; border-radius: 8px; margin-right: 4px;
}}
QTabBar::tab:selected {{ background: {P['indigo']}; color: {P['text']}; }}
QTabBar::tab:hover:!selected {{ background: {P['card3']}; }}
QGroupBox {{
    color: {P['text3']}; font-size: 10px; font-weight: 700;
    border: 1px solid {P['border']}; border-radius: 10px;
    margin-top: 10px; padding-top: 10px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
QSlider::groove:horizontal {{ background: {P['border']}; height: 4px; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {P['indigo']}; width: 14px; height: 14px;
    border-radius: 7px; margin: -5px 0;
}}
QSlider::sub-page:horizontal {{ background: {P['indigo']}; border-radius: 2px; }}
"""


def strip_html(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:p|div)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\n  • ", text, flags=re.IGNORECASE)
    text = re.sub(r"<h[1-6][^>]*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def score_col(s) -> tuple[str, str]:
    if s is None: return P['text3'], P['border']
    if s >= 75:   return P['green'],  P['green_bg']
    if s >= 55:   return P['amber'],  P['amber_bg']
    return P['red'], P['red_bg']


# ── widget factories ──────────────────────────────────────────────────────────

def _btn(text, fg, hover, height=34, font_size=14, fixed_width=None, color=None) -> QPushButton:
    b = QPushButton(text)
    b.setFixedHeight(height)
    if fixed_width:
        b.setFixedWidth(fixed_width)
    col = f"color: {color};" if color else ""
    b.setStyleSheet(f"""
        QPushButton {{ background: {fg}; font-size: {font_size}px; {col} }}
        QPushButton:hover {{ background: {hover}; {col} }}
        QPushButton:disabled {{ background: {P['card2']}; color: {P['text3']}; }}
    """)
    return b


def _label(text="", size=15, color=None, bold=False) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {color or P['text2']}; font-size: {size}px; "
        f"font-weight: {'700' if bold else '400'};"
    )
    lbl.setWordWrap(True)
    return lbl


def _mono(text="", size=13, color=None) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {color or P['text3']}; font-size: {size}px; "
        f"font-family: '{MONO_FONT}', monospace;"
    )
    return lbl


def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {P['border']}; border: none;")
    return f


def _pill(text: str, fg: str, bg: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background: {bg}; color: {fg}; border-radius: 4px; "
        f"padding: 3px 9px; font-size: 13px; font-weight: 700;"
    )
    lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return lbl


def _section_header(text: str, dot_col: str) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    dot = QLabel("●")
    dot.setStyleSheet(f"color: {dot_col}; font-size: 9px; background: transparent;")
    dot.setFixedWidth(12)
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {P['text3']}; font-size: 13px; font-weight: 700; "
        f"letter-spacing: 1px; background: transparent;"
    )
    row.addWidget(dot)
    row.addWidget(lbl)
    row.addStretch()
    return w


def _card(radius=12, bg=None) -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    f.setStyleSheet(
        f"QFrame#card {{ background: {bg or P['card']}; border-radius: {radius}px; "
        f"border: 1px solid {P['border']}; }}"
    )
    return f


def _pipe_qss(col: str, active: bool) -> str:
    if active:
        return (
            f"QPushButton {{ background: {col}22; color: {col}; border-radius: 6px; "
            f"font-size: 11px; font-weight: 700; padding: 2px 10px; border: 1px solid {col}; }}"
            f"QPushButton:hover {{ background: {col}44; }}"
        )
    return (
        f"QPushButton {{ background: {P['card2']}; color: {P['text3']}; border-radius: 6px; "
        f"font-size: 11px; font-weight: 700; padding: 2px 10px; border: 1px solid {P['border']}; }}"
        f"QPushButton:hover {{ background: {P['card3']}; color: {col}; border-color: {col}; }}"
    )
