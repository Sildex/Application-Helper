"""Custom Qt widgets: JobCard, ViewToggle, MiniGraph."""
from collections import deque
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.theme import CAT, MONO_FONT, P, _label, _pill, score_col


def _age_str(posted_at) -> str:
    if not posted_at:
        return ""
    try:
        now = datetime.utcnow()
        delta = now - posted_at.replace(tzinfo=None) if hasattr(posted_at, 'replace') else now - posted_at
        days = delta.days
        if days < 0:
            return ""
        if days == 0:
            h = delta.seconds // 3600
            return f"{h}h ago" if h > 0 else "just now"
        if days == 1:
            return "yesterday"
        if days < 30:
            return f"{days}d ago"
        if days < 365:
            return f"{days // 30}mo ago"
        return f"{days // 365}y ago"
    except Exception:
        return ""


class JobCard(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, job: dict, parent=None):
        super().__init__(parent)
        self.job = job
        self._selected = False
        self.setObjectName("jcard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        score = self.job.get("relevance_score")
        ai_scored = (self.job.get("relevance_reason") or "").startswith("[AI]")
        fg, bg = score_col(score)
        score_text = (f"✦ {score}" if ai_scored else str(score)) if score is not None else "—"
        score_lbl = QLabel(score_text)
        score_lbl.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 6px; "
            f"padding: 3px 10px; font-size: 14px; font-weight: 700; font-family: '{MONO_FONT}';"
        )
        score_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        viewed = self.job.get("viewed", False)
        title_col = P['text3'] if viewed else P['text']
        title_lbl = QLabel(self.job["title"])
        title_lbl.setStyleSheet(f"color: {title_col}; font-size: 15px; font-weight: 700;")
        title_lbl.setWordWrap(True)
        top.addWidget(title_lbl, 1)
        top.addWidget(score_lbl, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        parts = [p for p in [self.job.get("company"), self.job.get("location")] if p]
        age = _age_str(self.job.get("posted_at"))
        if age:
            parts.append(age)
        comp = QLabel("  ·  ".join(parts))
        comp.setStyleSheet(f"color: {P['text2']}; font-size: 13px;")
        comp.setWordWrap(True)
        lay.addWidget(comp)

        self._tags_layout = QHBoxLayout()
        self._tags_layout.setSpacing(5)
        self._tags_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._rebuild_tags(ai_scored)
        lay.addLayout(self._tags_layout)

    def _rebuild_tags(self, ai_scored: bool | None = None):
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if ai_scored is None:
            ai_scored = (self.job.get("relevance_reason") or "").startswith("[AI]")
        cat    = self.job.get("category", "")
        src    = self.job.get("source", "")
        status = self.job.get("status", "new")
        add    = self._tags_layout.addWidget
        if cat in CAT:            add(_pill(cat.upper(), *CAT[cat]))
        if src:                   add(_pill(src.upper(), P['text3'], P['border']))
        if self.job.get("is_new"):add(_pill("● NEW",  "#2dd4bf", "#0a2622"))
        if ai_scored:             add(_pill("✦ AI",   P['purple'], P['purple_bg']))
        if self.job.get("saved"): add(_pill("● SAVED",P['green'],  P['green_bg']))
        _STATUS_PILLS = {
            "applied":   ("✓ APPLIED",   P['indigo'], P['indigo_bg']),
            "interview": ("◈ INTERVIEW", P['amber'],  P['amber_bg']),
            "offer":     ("★ OFFER",     P['green'],  P['green_bg']),
            "rejected":  ("✕ REJECTED",  P['red'],    P['red_bg']),
        }
        if status in _STATUS_PILLS: add(_pill(*_STATUS_PILLS[status]))
        if self.job.get("notes"):   add(_pill("📝", P['text3'], P['border']))

    def set_selected(self, sel: bool):
        self._selected = sel
        self._apply_style()

    def _apply_style(self):
        cat = self.job.get("category", "")
        accent = "#2dd4bf" if self.job.get("is_new") else (CAT[cat][0] if cat in CAT else P['border2'])
        bg_base = P['card'] if self.job.get("viewed") else P['card2']
        bg_hover = P['card2'] if self.job.get("viewed") else P['card3']
        if self._selected:
            self.setStyleSheet(f"""
                QFrame#jcard {{
                    background: {P['card3']}; border-radius: 10px;
                    border-top: 1px solid {P['indigo']};
                    border-right: 1px solid {P['indigo']};
                    border-bottom: 1px solid {P['indigo']};
                    border-left: 4px solid {accent};
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#jcard {{
                    background: {bg_base}; border-radius: 10px;
                    border-top: 1px solid {P['border']};
                    border-right: 1px solid {P['border']};
                    border-bottom: 1px solid {P['border']};
                    border-left: 4px solid {accent};
                }}
                QFrame#jcard:hover {{
                    background: {bg_hover};
                    border-top: 1px solid {P['border2']};
                    border-right: 1px solid {P['border2']};
                    border-bottom: 1px solid {P['border2']};
                    border-left: 4px solid {accent};
                }}
            """)

    def mousePressEvent(self, _):
        self.clicked.emit(self.job)


class ViewToggle(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, options: list[str], parent=None):
        super().__init__(parent)
        self._current = options[0]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self._btns: dict[str, QPushButton] = {}
        for opt in options:
            b = QPushButton(opt)
            b.setFixedHeight(34)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, o=opt: self._select(o))
            self._btns[opt] = b
            lay.addWidget(b)
        self._select(options[0])

    def _select(self, opt: str):
        self._current = opt
        for key, b in self._btns.items():
            if key == opt:
                b.setStyleSheet(
                    f"QPushButton {{ background: {P['indigo']}; color: {P['text']}; "
                    f"border-radius: 6px; font-size: 13px; font-weight: 700; }}"
                )
            else:
                b.setStyleSheet(
                    f"QPushButton {{ background: {P['card2']}; color: {P['text2']}; "
                    f"border-radius: 6px; font-size: 11px; font-weight: 600; }}"
                    f"QPushButton:hover {{ background: {P['card3']}; }}"
                )
        self.changed.emit(opt)

    def value(self) -> str:
        return self._current


class MiniGraph(QWidget):
    """Scrolling line graph with gradient fill."""

    def __init__(self, color: str, label: str, unit: str = "%", max_val: float = 100, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._label = label
        self._unit  = unit
        self._max   = max_val
        self._data: deque[float] = deque(maxlen=60)
        self._cur   = 0.0
        self.setMinimumHeight(80)

    def push(self, value: float):
        self._cur = value
        self._data.append(value)
        self.update()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(0, 0, w, h, QColor(P['card2']))

        pts = list(self._data)
        if len(pts) >= 2:
            step = w / (len(pts) - 1)
            path = QPainterPath()
            path.moveTo(0.0, float(h))
            for i, v in enumerate(pts):
                path.lineTo(i * step, h - (v / self._max) * (h - 14))
            path.lineTo(float(w), float(h))
            path.closeSubpath()

            grad = QLinearGradient(0, 0, 0, h)
            c1 = QColor(self._color); c1.setAlpha(80)
            c2 = QColor(self._color); c2.setAlpha(8)
            grad.setColorAt(0, c1); grad.setColorAt(1, c2)
            p.fillPath(path, grad)

            pen = QPen(self._color, 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            for i in range(1, len(pts)):
                x0 = int((i - 1) * step); y0 = int(h - (pts[i-1] / self._max) * (h - 14))
                x1 = int(i * step);       y1 = int(h - (pts[i]   / self._max) * (h - 14))
                p.drawLine(x0, y0, x1, y1)

        p.setPen(QColor(P['text3']))
        p.setFont(QFont(MONO_FONT, 8))
        p.drawText(6, 12, self._label)
        p.setPen(self._color)
        p.setFont(QFont(MONO_FONT, 11, QFont.Weight.Bold))
        p.drawText(w - 60, 14, f"{self._cur:.1f}{self._unit}")
        p.end()
