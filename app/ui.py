"""Application Helper – main window, debug console, settings dialog."""
import asyncio
import csv
import html
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import webbrowser
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, QRect, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QIcon, QLinearGradient,
    QPainter, QPen, QPixmap, QPalette,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSplitter, QSystemTrayIcon,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from app import db, search_engine, ai_score_engine
from app.log import _ACTIVITY_LOG, _log_activity
from app.theme import (
    CAT, MONO_FONT, P, _btn, _card, _label, _mono, _pill,
    _pipe_qss, _section_header, _section_toggle_btn, _sep, _qss, score_col, strip_html,
)
from app.widgets import JobCard, MiniGraph, ViewToggle
from backend.database import init_db
from backend.services import llm_service


# ── search progress helper ───────────────────────────────────────────────────

def _search_progress_pct(phase: str) -> int:
    if not phase or phase in ("Ready", "IDLE", "Initialising…"):
        return 2
    if "BA API" in phase:
        m = re.search(r'(\d+)/(\d+)', phase)
        if m:
            return max(2, int(int(m.group(1)) / max(int(m.group(2)), 1) * 58))
        return 5
    if "Arbeitnow" in phase:
        return 62
    if "Filtering" in phase:
        return 76
    if "Saving" in phase:
        return 88
    if "Done" in phase:
        return 100
    if "Cancelled" in phase or "Error" in phase:
        return 0
    return 10


# ── description renderer ─────────────────────────────────────────────────────

_SECTION_ACCENTS = {
    "aufgaben":      P["indigo"],
    "tätigkeiten":   P["indigo"],
    "profil":        P["amber"],
    "anforderungen": P["amber"],
    "qualifikation": P["amber"],
    "bieten":        P["green"],
    "benefits":      P["green"],
    "kontakt":       P["text3"],
    "ansprechpartner": P["text3"],
}

def _format_desc_html(desc_plain: str, c: dict, title: str = "") -> str:
    """Render plain-text job description as structured HTML (sections, bullets, highlights)."""
    # Build keyword regex from job title words (> 3 chars)
    kw_pattern = None
    title_words = sorted(
        {w.lower() for w in re.split(r'\W+', title) if len(w) > 3},
        key=len, reverse=True,
    )
    if title_words:
        try:
            kw_pattern = re.compile(
                r'\b(' + '|'.join(re.escape(w) for w in title_words) + r')\b',
                re.IGNORECASE,
            )
        except re.error:
            pass

    def hl(escaped: str) -> str:
        if not kw_pattern:
            return escaped
        return kw_pattern.sub(
            f'<b style="color:{c["text"]};font-weight:600;">\\1</b>', escaped
        )

    def _section_accent(header_text: str) -> str:
        low = header_text.lower()
        for key, col in _SECTION_ACCENTS.items():
            if key in low:
                return col
        return c["indigo"]

    out: list[str] = []
    bullet_buf: list[str] = []
    first_paragraph = True

    def flush_bullets() -> None:
        if not bullet_buf:
            return
        items = "".join(
            f'<li style="margin:4px 0;line-height:1.65;">{hl(b)}</li>'
            for b in bullet_buf
        )
        out.append(
            f'<div style="margin:2px 0 14px 0;padding:8px 12px 8px 8px;'
            f'background:{c["card2"]};border-radius:8px;">'
            f'<ul style="margin:0;padding-left:22px;color:{c["text2"]};font-size:13px;">'
            f'{items}</ul></div>'
        )
        bullet_buf.clear()

    for line in desc_plain.split('\n'):
        s = line.strip()
        if not s:
            flush_bullets()
            continue

        if s.startswith('•'):
            bullet_buf.append(html.escape(s[1:].strip()))
            continue

        flush_bullets()

        # Section header: short line ending with ':', no mid-sentence punctuation
        is_header = (
            s.endswith(':')
            and len(s) < 65
            and s.count('.') == 0
            and s.count(',') == 0
        )
        if is_header:
            accent = _section_accent(s)
            out.append(
                f'<div style="margin:20px 0 7px 0;padding:4px 0 4px 12px;'
                f'border-left:3px solid {accent};'
                f'color:{c["text"]};font-size:13px;font-weight:700;'
                f'letter-spacing:0.2px;">{html.escape(s)}</div>'
            )
        else:
            size = "14px" if first_paragraph else "13px"
            out.append(
                f'<p style="margin:0 0 8px 0;color:{c["text2"]};'
                f'font-size:{size};line-height:1.75;">'
                f'{hl(html.escape(s))}</p>'
            )
            first_paragraph = False

    flush_bullets()
    return "".join(out)


# ── main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    _ba_desc_ready  = pyqtSignal(int, str)       # job_id, description
    _ai_job_ready   = pyqtSignal(int, int, str)  # job_id, score, reason
    _bew_progress_sig = pyqtSignal(int, str, str)  # pct (-1=indeterminate), step, detail
    _bew_pdf_ready    = pyqtSignal(str)             # pdf path to render

    def __init__(self):
        super().__init__()
        self._ba_desc_ready.connect(self._ba_desc_done)
        self._ai_job_ready.connect(self._ai_job_done)
        self._bew_progress_sig.connect(self._on_bew_progress)
        self._bew_pdf_ready.connect(self._render_bew_pdf)
        self._ai_render_timer = QTimer(self); self._ai_render_timer.setSingleShot(True)
        def _ai_render():
            self._chip_new.setChecked(False)
            self._quick_new_only = False
            self._load_jobs()
            self._update_filter_btn()
        self._ai_render_timer.timeout.connect(_ai_render)
        self.setWindowTitle("Application Helper")
        self.resize(1500, 900)
        self.setMinimumSize(1100, 680)

        self._jobs: list[dict] = []
        self._selected: dict | None = None
        self._cards: dict[int, JobCard] = {}
        self._filter_cat         = "All"
        self._view               = "all"
        self._show_dismissed     = False
        self._active_tab         = 0
        self._top_jobs_tick      = 0
        self._quick_new_only     = False
        self._quick_unviewed     = False
        self._quick_status       = ""
        self._saved_sub_filter   = ""
        self._workspace          = "default"
        self._last_dismissed_id: int | None = None
        self._debug_win          = None
        self._total_jobs_cache   = 0
        self._ai_idle_tick       = 0
        self._ai_unscored_cache  = 0

        # bewerbung state — always use Bewerbungsunterlagen folder
        self._latex_dir = os.path.normpath(os.path.join(
            os.path.expanduser("~"), "Documents", "Claude Code",
            "Application Helper", "Bewerbungsunterlagen"
        ))
        self._bew_creating          = False
        self._bewerbung_paths: dict[int, str] = {}
        self._current_bew_job_id    = 0
        self._current_bew_out_path  = ""
        self._bew_out_dir           = ""

        self._build()
        self._run_auto_dismiss()
        threading.Thread(target=db.cleanup_excluded_titles, daemon=True).start()
        self._load_jobs()
        self._refresh_workspaces()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_search)
        self._poll_timer.timeout.connect(self._poll_ai)
        self._poll_timer.start(400)

        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_search_check)
        self._auto_timer.start(60_000)

        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_make_app_icon())
        tray_menu = QMenu()
        tray_menu.addAction("Show", self.show)
        tray_menu.addAction("Quit", QApplication.quit)
        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(lambda _: (self.show(), self.raise_()))
        self._tray.show()

        self._update_last_search_label()

    def closeEvent(self, ev):
        m = db.get_settings()["prefs"].get("ollama_model", "qwen2.5:14b")
        threading.Thread(target=llm_service.unload_model, args=(m,), daemon=True).start()
        ev.accept()

    # ── layout ────────────────────────────────────────────────────────────────

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(2)
        self._splitter.addWidget(self._build_sidebar())
        self._splitter.addWidget(self._build_detail())
        self._splitter.setSizes([540, 960])
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        root.addWidget(self._splitter, 1)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(38)
        bar.setStyleSheet(f"QWidget {{ background: {P['card']}; border-bottom: 1px solid {P['border']}; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(0)

        # Logo
        px = QPixmap(24, 24); px.fill(QColor(0, 0, 0, 0))
        lp = QPainter(px); lp.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, 0, 24)
        g.setColorAt(0, QColor("#1e1e50")); g.setColorAt(1, QColor("#08081a"))
        lp.setBrush(QBrush(g)); lp.setPen(QPen(QColor("#6d6df5"), 1.5))
        lp.drawRoundedRect(1, 1, 22, 22, 5, 5)
        lp.setPen(QColor("#eeeef8")); lp.setFont(QFont("Segoe UI Variable", 12, QFont.Weight.Bold))
        lp.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "A"); lp.end()
        logo = QLabel(); logo.setFixedSize(24, 24); logo.setPixmap(px)
        logo.setStyleSheet("background: transparent;")
        lay.addWidget(logo)

        self._top_dot = QLabel(" ●")
        self._top_dot.setStyleSheet(f"color: {P['green']}; font-size: 10px; background: transparent;")
        brand = QLabel("APPLICATION HELPER")
        brand.setStyleSheet(
            f"color: {P['text']}; font-size: 11px; font-weight: 700; "
            f"letter-spacing: 3px; font-family: '{MONO_FONT}'; background: transparent;"
        )
        lay.addWidget(self._top_dot)
        lay.addWidget(brand)
        lay.addSpacing(20)

        # Applied counter pill
        self._lbl_applied_count = QLabel("✓  0  APPLIED")
        self._lbl_applied_count.setStyleSheet(
            f"color: {P['green']}; background: {P['green_bg']}; "
            f"font-size: 11px; font-weight: 700; font-family: '{MONO_FONT}'; "
            f"border-radius: 5px; padding: 2px 10px;"
        )
        lay.addWidget(self._lbl_applied_count)
        lay.addSpacing(16)

        # Workspace selector
        self._workspace_combo = QComboBox()
        self._workspace_combo.setFixedHeight(24)
        self._workspace_combo.setMinimumWidth(110)
        self._workspace_combo.setStyleSheet(
            f"QComboBox {{ background: {P['card2']}; color: {P['text2']}; "
            f"border: 1px solid {P['border2']}; border-radius: 5px; "
            f"font-size: 11px; font-family: '{MONO_FONT}'; padding: 0 8px; }}"
            f"QComboBox::drop-down {{ border: none; width: 16px; }}"
            f"QComboBox QAbstractItemView {{ background: {P['card2']}; color: {P['text']}; "
            f"selection-background-color: {P['indigo_bg']}; border: 1px solid {P['border2']}; }}"
        )
        self._workspace_combo.currentTextChanged.connect(self._on_workspace_change)
        lay.addWidget(self._workspace_combo)
        lay.addStretch()

        sep = QLabel("  |  ")
        sep.setStyleSheet(f"color: {P['border2']}; background: transparent;")
        self._top_status = _mono("IDLE",       color=P['text3'])
        self._top_jobs   = _mono("DB  — jobs", color=P['text3'])
        self._top_time   = _mono("",           color=P['text3'])
        for w in (self._top_status, sep, self._top_jobs, self._top_time):
            lay.addWidget(w); lay.addSpacing(16)
        return bar

    def _build_sidebar(self) -> QWidget:
        sb = QWidget()
        sb.setMinimumWidth(380); sb.setMaximumWidth(520)
        sb.setStyleSheet(f"background: {P['sidebar']};")
        lay = QVBoxLayout(sb)
        lay.setContentsMargins(14, 16, 14, 12)
        lay.setSpacing(0)

        # ── Search ────────────────────────────────────────────────────────────
        self._hdr_search = _section_toggle_btn("SEARCH ENGINE", P['indigo'])
        lay.addWidget(self._hdr_search); lay.addSpacing(5)

        self._search_body = QWidget(); self._search_body.setStyleSheet("background: transparent;")
        search_lay = QVBoxLayout(self._search_body); search_lay.setContentsMargins(0, 0, 0, 0); search_lay.setSpacing(0)

        self._btn_search = _btn("Start Search", P['indigo'], P['indigo_d'], height=34, font_size=13)
        self._btn_search.clicked.connect(self._start_search)
        search_lay.addWidget(self._btn_search); search_lay.addSpacing(4)

        self._progress = QProgressBar()
        self._progress.setFixedHeight(26)
        self._progress.setRange(0, 100); self._progress.setValue(0)
        self._progress.setTextVisible(True); self._progress.setFormat("  READY")
        self._btn_cancel = QPushButton("✕")
        self._btn_cancel.setFixedSize(26, 26)
        self._btn_cancel.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {P['red']}; "
            f"border: 1px solid {P['red_bg']}; border-radius: 5px; "
            f"font-size: 11px; font-weight: 700; padding: 0; }}"
            f"QPushButton:hover {{ background: {P['red_bg']}; }}"
        )
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._cancel_search)
        prog_row = QHBoxLayout(); prog_row.setSpacing(4)
        prog_row.addWidget(self._progress, 1); prog_row.addWidget(self._btn_cancel)
        search_lay.addLayout(prog_row); search_lay.addSpacing(3)

        phase_row = QHBoxLayout(); phase_row.setSpacing(0)
        self._lbl_phase = _mono("IDLE", size=10, color=P['text3'])
        self._lbl_search_meta = _mono("", size=10, color=P['text3'])
        self._lbl_search_meta.setAlignment(Qt.AlignmentFlag.AlignRight)
        phase_row.addWidget(self._lbl_phase, 1); phase_row.addWidget(self._lbl_search_meta)
        search_lay.addLayout(phase_row); search_lay.addSpacing(2)
        self._lbl_last_search = _mono("Last search: never", size=10, color=P['text3'])
        search_lay.addWidget(self._lbl_last_search); search_lay.addSpacing(5)

        self._stats_frame = QFrame(); self._stats_frame.setObjectName("sf")
        self._stats_frame.setStyleSheet(
            f"QFrame#sf {{ background: {P['card2']}; border-radius: 8px; border: 1px solid {P['border']}; }}"
        )
        sl = QHBoxLayout(self._stats_frame); sl.setContentsMargins(0, 4, 0, 4)
        self._st_fetched  = self._stat_cell(sl, "FETCHED", "—")
        self._stat_vsep(sl)
        self._st_filtered = self._stat_cell(sl, "FILTERED", "—")
        self._stat_vsep(sl)
        self._st_saved    = self._stat_cell(sl, "NEW", "—")
        self._stat_vsep(sl)
        self._st_total    = self._stat_cell(sl, "TOTAL DB", "—")
        search_lay.addWidget(self._stats_frame)
        self._lbl_idle_db = _mono("", size=11, color=P['text3'])
        search_lay.addWidget(self._lbl_idle_db)
        self._lbl_idle_db.hide()
        search_lay.addSpacing(4)

        self._lbl_funnel = QLabel()
        self._lbl_funnel.setStyleSheet("background: transparent;")
        self._lbl_funnel.setTextFormat(Qt.TextFormat.RichText)
        self._lbl_funnel.setText(self._funnel_html({"new": 0, "applied": 0, "interview": 0, "offer": 0}))
        search_lay.addWidget(self._lbl_funnel); search_lay.addSpacing(4)

        self._hdr_search.toggled.connect(self._search_body.setVisible)
        self._hdr_search.toggled.connect(
            lambda on: self._hdr_search.setText("▾  SEARCH ENGINE" if on else "▸  SEARCH ENGINE")
        )
        lay.addWidget(self._search_body)
        lay.addSpacing(6)
        lay.addWidget(_sep()); lay.addSpacing(6)

        # ── AI Scorer ─────────────────────────────────────────────────────────
        self._hdr_ai = _section_toggle_btn("AI SCORER", P['purple'])
        lay.addWidget(self._hdr_ai); lay.addSpacing(4)

        self._ai_body = QWidget(); self._ai_body.setStyleSheet("background: transparent;")
        ab = QVBoxLayout(self._ai_body); ab.setContentsMargins(0, 0, 0, 0); ab.setSpacing(0)

        self._ai_progress = QProgressBar()
        self._ai_progress.setFixedHeight(22); self._ai_progress.setRange(0, 100)
        self._ai_progress.setValue(0); self._ai_progress.setTextVisible(True)
        self._ai_progress.setFormat("  IDLE")
        self._ai_progress.setStyleSheet(
            f"QProgressBar {{ background: {P['card2']}; border: 1px solid {P['border2']}; "
            f"border-radius: 5px; height: 22px; text-align: center; color: {P['text']}; "
            f"font-size: 11px; font-weight: 700; font-family: '{MONO_FONT}'; }}"
            f"QProgressBar::chunk {{ border-radius: 4px; background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 #4b0082, stop:0.5 #7b2fbe, stop:1 {P['purple']}); }}"
        )
        ab.addWidget(self._ai_progress); ab.addSpacing(3)

        ai_info_row = QHBoxLayout(); ai_info_row.setSpacing(0)
        self._lbl_ai_phase = _mono("idle", size=10, color=P['text3'])
        self._lbl_ai_eta   = _mono("", size=10, color=P['text3'])
        self._lbl_ai_eta.setAlignment(Qt.AlignmentFlag.AlignRight)
        ai_info_row.addWidget(self._lbl_ai_phase, 1); ai_info_row.addWidget(self._lbl_ai_eta)
        ab.addLayout(ai_info_row); ab.addSpacing(4)

        self._ai_auto_enabled = False
        self._btn_ai_toggle = QPushButton("AUTO  OFF")
        self._btn_ai_toggle.setFixedHeight(26)
        self._btn_ai_toggle.setCheckable(True)
        self._btn_ai_toggle.setChecked(False)
        self._btn_ai_toggle.clicked.connect(self._on_ai_toggle)
        self._apply_ai_toggle_style()

        ai_btn_row = QHBoxLayout(); ai_btn_row.setSpacing(4)
        self._btn_ai_start  = _btn("✦  Score now", P['purple_bg'], "#2a0e50",
                                   height=26, font_size=11, color=P['purple'])
        self._btn_ai_cancel = QPushButton("✕ Cancel")
        self._btn_ai_cancel.setFixedHeight(26)
        self._btn_ai_cancel.setStyleSheet(
            f"QPushButton {{ background: {P['red_bg']}; color: {P['red']}; "
            f"border: 1px solid {P['red']}44; border-radius: 5px; font-size: 11px; font-weight: 700; padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {P['red']}33; border-color: {P['red']}; }}"
            f"QPushButton:disabled {{ background: transparent; color: {P['text3']}; border-color: {P['border']}; }}"
        )
        self._btn_ai_cancel.setEnabled(False)
        self._btn_ai_start.clicked.connect(self._start_ai_scoring)
        def _on_cancel():
            ai_score_engine.cancel_scoring()
            self._slbl(self._lbl_ai_phase, "CANCELLING…", P['red'])
            self._btn_ai_cancel.setEnabled(False)
        self._btn_ai_cancel.clicked.connect(_on_cancel)
        ai_btn_row.addWidget(self._btn_ai_toggle)
        ai_btn_row.addWidget(self._btn_ai_start, 1)
        ai_btn_row.addWidget(self._btn_ai_cancel)
        ab.addLayout(ai_btn_row); ab.addSpacing(6)

        self._hdr_ai.toggled.connect(self._ai_body.setVisible)
        self._hdr_ai.toggled.connect(
            lambda on: self._hdr_ai.setText("▾  AI SCORER" if on else "▸  AI SCORER")
        )
        lay.addWidget(self._ai_body)
        lay.addWidget(_sep()); lay.addSpacing(6)

        # ── Filter ────────────────────────────────────────────────────────────
        lay.addWidget(_section_header("FILTER & VIEW", P['amber']))
        lay.addSpacing(4)
        self._view_toggle = ViewToggle(["All", "Saved", "Applied"])
        self._view_toggle.changed.connect(self._on_view_change)
        lay.addWidget(self._view_toggle); lay.addSpacing(4)

        # filter toggle header row
        fhdr = QHBoxLayout(); fhdr.setSpacing(6)
        self._btn_filter_toggle = QPushButton("Filters")
        self._btn_filter_toggle.setFixedHeight(26)
        self._btn_filter_toggle.setCheckable(True)
        self._btn_filter_toggle.setChecked(False)
        self._btn_filter_toggle.setStyleSheet(
            f"QPushButton{{background:{P['card2']};color:{P['text2']};border-radius:5px;"
            f"font-size:11px;font-weight:600;padding:0 12px;border:1px solid {P['border2']};}}"
            f"QPushButton:checked{{background:{P['amber_bg']};color:{P['amber']};"
            f"border-color:{P['amber']}55;}}"
            f"QPushButton:hover{{background:{P['card3']};}}"
        )
        self._btn_filter_toggle.clicked.connect(self._toggle_filter_panel)
        self._lbl_count = _mono("0 jobs", color=P['text3'])
        self._lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        fhdr.addWidget(self._btn_filter_toggle)
        fhdr.addStretch()
        fhdr.addWidget(self._lbl_count)
        lay.addLayout(fhdr); lay.addSpacing(4)

        # collapsible filter panel (hidden by default)
        self._filter_panel = QWidget(); self._filter_panel.setStyleSheet("background: transparent;")
        fp = QVBoxLayout(self._filter_panel); fp.setContentsMargins(0, 0, 0, 4); fp.setSpacing(4)

        # saved sub-filter chips (only visible in Saved view, inside panel)
        self._fp_saved_sub = QWidget(); self._fp_saved_sub.setStyleSheet("background: transparent;")
        ssfl = QHBoxLayout(self._fp_saved_sub); ssfl.setContentsMargins(0, 0, 0, 0); ssfl.setSpacing(4)
        def _sfchip(label):
            b = QPushButton(label); b.setCheckable(True); b.setFixedHeight(26)
            b.setStyleSheet(
                f"QPushButton{{background:{P['card2']};color:{P['text3']};border-radius:5px;"
                f"font-size:10px;font-weight:600;padding:0 8px;}}"
                f"QPushButton:checked{{background:{P['green_bg']};color:{P['green']};"
                f"border:1px solid {P['green']}55;}}"
                f"QPushButton:hover{{background:{P['card3']};}}"
            )
            return b
        self._sfchip_all       = _sfchip("All Saved")
        self._sfchip_pending   = _sfchip("Not Applied")
        self._sfchip_applied   = _sfchip("✓ Applied")
        self._sfchip_interview = _sfchip("Interview")
        self._sfchip_all.setChecked(True)
        self._sfchip_all.clicked.connect(      lambda: self._on_saved_sub(""))
        self._sfchip_pending.clicked.connect(  lambda: self._on_saved_sub("!applied"))
        self._sfchip_applied.clicked.connect(  lambda: self._on_saved_sub("applied"))
        self._sfchip_interview.clicked.connect(lambda: self._on_saved_sub("interview"))
        for chip in (self._sfchip_all, self._sfchip_pending, self._sfchip_applied, self._sfchip_interview):
            ssfl.addWidget(chip)
        ssfl.addStretch()
        self._fp_saved_sub.hide()
        fp.addWidget(self._fp_saved_sub)

        self._fp_chips_row = QWidget(); self._fp_chips_row.setStyleSheet("background: transparent;")
        qf_row = QHBoxLayout(self._fp_chips_row); qf_row.setContentsMargins(0, 0, 0, 0); qf_row.setSpacing(4)
        def _qchip(label, tip=""):
            b = QPushButton(label); b.setCheckable(True); b.setFixedHeight(24)
            b.setToolTip(tip)
            b.setStyleSheet(
                f"QPushButton{{background:{P['card2']};color:{P['text3']};border-radius:5px;"
                f"font-size:10px;font-weight:600;padding:0 8px;}}"
                f"QPushButton:checked{{background:{P['indigo_bg']};color:{P['indigo']};}}"
                f"QPushButton:hover{{background:{P['card3']};}}"
            )
            return b
        self._chip_new       = _qchip("● New",      "Today's new jobs only")
        self._chip_unviewed  = _qchip("Unviewed",   "Only jobs not yet opened")
        self._chip_interview = _qchip("Interview",  "Interview status only")
        self._chip_new.clicked.connect(self._on_chip_new)
        self._chip_unviewed.clicked.connect(self._on_chip_unviewed)
        self._chip_interview.clicked.connect(self._on_chip_interview)
        qf_row.addWidget(self._chip_new)
        qf_row.addWidget(self._chip_unviewed)
        qf_row.addWidget(self._chip_interview)
        qf_row.addStretch()
        fp.addWidget(self._fp_chips_row)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search title or company…")
        self._search_input.setFixedHeight(30)
        self._search_input.textChanged.connect(self._on_filter)
        fp.addWidget(self._search_input)

        filter_row = QHBoxLayout(); filter_row.setSpacing(4)
        self._cat_combo = QComboBox()
        self._cat_combo.addItems(["All Categories", "IT", "Wirtschaft", "Unknown"])
        self._cat_combo.currentTextChanged.connect(self._on_filter)
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Score ↓",   "score")
        self._sort_combo.addItem("Date ↓",    "date")
        self._sort_combo.addItem("Company ↑", "company")
        self._sort_combo.currentIndexChanged.connect(self._on_filter)
        filter_row.addWidget(self._cat_combo, 3); filter_row.addWidget(self._sort_combo, 2)
        fp.addLayout(filter_row)

        slider_row = QHBoxLayout(); slider_row.setSpacing(6)
        self._lbl_min_score = _mono("MIN SCORE  0", size=10, color=P['text3'])
        self._score_slider  = QSlider(Qt.Orientation.Horizontal)
        self._score_slider.setRange(0, 100); self._score_slider.setValue(0)
        self._score_slider.setFixedHeight(16)
        self._score_slider.valueChanged.connect(self._on_score_slider)
        slider_row.addWidget(self._lbl_min_score)
        slider_row.addWidget(self._score_slider, 1)
        fp.addLayout(slider_row)

        _chk_style = (
            f"QCheckBox {{ color: {P['text3']}; font-size: 11px; spacing: 5px; }}"
            f"QCheckBox::indicator {{ width: 13px; height: 13px; border-radius: 3px; "
            f"border: 1px solid {P['border2']}; background: {P['card2']}; }}"
            f"QCheckBox::indicator:checked {{ background: {P['indigo']}; border-color: {P['indigo']}; }}"
        )
        chk_row = QHBoxLayout()
        self._chk_dismissed = QCheckBox("Dismissed")
        self._chk_dismissed.setStyleSheet(_chk_style)
        self._chk_dismissed.stateChanged.connect(self._on_filter)
        self._chk_ai_only = QCheckBox("✦ AI only")
        self._chk_ai_only.setStyleSheet(_chk_style)
        self._chk_ai_only.stateChanged.connect(self._on_filter)
        chk_row.addWidget(self._chk_dismissed)
        chk_row.addSpacing(10)
        chk_row.addWidget(self._chk_ai_only)
        chk_row.addStretch()
        fp.addLayout(chk_row)

        self._filter_panel.hide()
        lay.addWidget(self._filter_panel); lay.addSpacing(2)
        lay.addWidget(_sep()); lay.addSpacing(4)

        # ── Job list ──────────────────────────────────────────────────────────
        lay.addSpacing(2)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background: transparent;")
        self._list_widget  = QWidget(); self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout  = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 6, 0); self._list_layout.setSpacing(5)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_widget)
        lay.addWidget(self._scroll, 1); lay.addSpacing(10)
        lay.addWidget(_sep()); lay.addSpacing(8)

        bot = QHBoxLayout(); bot.setSpacing(4)
        self._btn_dismiss_all = _btn("✕ Dismiss",   P['card2'],   P['card3'],    height=28, font_size=11)
        self._btn_dismiss_all.setToolTip("Dismiss all currently visible jobs")
        self._btn_settings    = _btn("⋮",           P['card2'],   P['card3'],    height=28, font_size=14, fixed_width=32)
        self._btn_settings.setToolTip("Menu")
        self._btn_dismiss_all.clicked.connect(self._dismiss_visible)
        self._btn_settings.clicked.connect(self._open_menu)
        bot.addWidget(self._btn_dismiss_all, 1)
        bot.addWidget(self._btn_settings)
        lay.addLayout(bot)
        return sb

    def _stat_cell(self, lay: QHBoxLayout, label: str, value: str) -> QLabel:
        cell = QWidget(); cell.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(cell); vl.setContentsMargins(0, 0, 0, 0); vl.setSpacing(2)
        val = QLabel(value)
        val.setStyleSheet(
            f"color: {P['text']}; font-size: 20px; font-weight: 700; "
            f"font-family: '{MONO_FONT}'; background: transparent;"
        )
        val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = _mono(label, size=11, color=P['text3'])
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vl.addWidget(val); vl.addWidget(lbl)
        lay.addWidget(cell, 1)
        return val

    def _stat_vsep(self, lay: QHBoxLayout):
        line = QFrame(); line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1); line.setStyleSheet(f"background: {P['border']}; border: none;")
        lay.addWidget(line)

    def _build_detail(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)

        # ── header card ───────────────────────────────────────────────────────
        hdr = _card(radius=14)
        hl = QVBoxLayout(hdr); hl.setContentsMargins(20, 16, 20, 14); hl.setSpacing(4)

        tr = QHBoxLayout(); tr.setSpacing(12)
        self._lbl_title = _label("Select a job from the list", size=21, color=P['text'], bold=True)
        self._lbl_score = QLabel("—")
        self._lbl_score.setStyleSheet(
            f"background: {P['border']}; color: {P['text3']}; border-radius: 8px; "
            f"padding: 5px 14px; font-size: 16px; font-weight: 700; font-family: '{MONO_FONT}';"
        )
        self._lbl_score.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._lbl_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tr.addWidget(self._lbl_title, 1); tr.addWidget(self._lbl_score, 0, Qt.AlignmentFlag.AlignTop)
        hl.addLayout(tr)

        self._lbl_meta   = _label("", size=11, color=P['text2'])
        self._lbl_reason = _mono("", size=10, color=P['text3'])
        hl.addWidget(self._lbl_meta); hl.addWidget(self._lbl_reason)

        self._tag_row = QHBoxLayout(); self._tag_row.setSpacing(6)
        self._tag_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        hl.addLayout(self._tag_row)
        hl.addSpacing(6); hl.addWidget(_sep()); hl.addSpacing(6)

        # action buttons
        ab = QHBoxLayout(); ab.setSpacing(8)
        self._btn_open     = _btn("Open Job",    P['indigo'],    P['indigo_d'], height=34)
        self._btn_save     = _btn("Save",        P['card2'],     P['card3'],    height=34)
        self._btn_dismiss  = _btn("Dismiss",     P['card2'],     P['card3'],    height=34)
        self._btn_undo_dis = _btn("↩",           P['amber_bg'],  P['amber_bg'], height=34, fixed_width=40)
        self._btn_undo_dis.setToolTip("Undo last dismiss")
        self._btn_undo_dis.setEnabled(False)
        self._btn_rescore  = _btn("✦ Re-score",  P['purple_bg'], "#2a0e50",    height=34, color=P['purple'])
        self._btn_bew_go   = _btn("📄 Apply", P['card2'],    P['card3'],    height=34)
        self._btn_bew_go.setToolTip("Switch to Application tab and create PDF  [B]")
        for b in (self._btn_open, self._btn_save, self._btn_dismiss,
                  self._btn_undo_dis, self._btn_rescore, self._btn_bew_go):
            ab.addWidget(b)
        ab.addStretch()
        _btn_keys = QPushButton("⌨")
        _btn_keys.setFixedSize(34, 34)
        _btn_keys.setToolTip("Keyboard shortcuts")
        _btn_keys.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {P['text3']}; border: none; "
            f"font-size: 16px; }}"
            f"QPushButton:hover {{ color: {P['text2']}; }}"
        )
        def _show_shortcuts():
            msg = QMessageBox(self)
            msg.setWindowTitle("Keyboard Shortcuts")
            msg.setText(
                "<table cellspacing='8'>"
                "<tr><td><b>S</b></td><td>Save / Unsave</td></tr>"
                "<tr><td><b>D</b></td><td>Dismiss</td></tr>"
                "<tr><td><b>A</b></td><td>Mark as Applied</td></tr>"
                "<tr><td><b>B</b></td><td>Create Application PDF</td></tr>"
                "<tr><td><b>N</b></td><td>Notes tab</td></tr>"
                "<tr><td><b>O</b></td><td>Open job in browser</td></tr>"
                "<tr><td><b>↑ ↓</b></td><td>Navigate job list</td></tr>"
                "<tr><td><b>Tab</b></td><td>Nächster ungelesener Job</td></tr>"
                "</table>"
            )
            msg.setStyleSheet(f"QMessageBox {{ background: {P['bg']}; }} QLabel {{ color: {P['text']}; }}")
            msg.exec()
        _btn_keys.clicked.connect(_show_shortcuts)
        ab.addWidget(_btn_keys)
        hl.addLayout(ab)

        # status pipeline (Applied / Interview / Offer / Rejected)
        pipe = QHBoxLayout(); pipe.setSpacing(6)
        pipe.addWidget(_mono("STATUS", size=10, color=P['text3'])); pipe.addSpacing(4)
        self._btn_applied_pipe = QPushButton("Applied")
        self._btn_interview    = QPushButton("Interview")
        self._btn_offer        = QPushButton("Offer")
        self._btn_rejected     = QPushButton("Rejected")
        for btn, col in [(self._btn_applied_pipe, P['indigo']),
                         (self._btn_interview,    P['amber']),
                         (self._btn_offer,        P['green']),
                         (self._btn_rejected,     P['red'])]:
            btn.setFixedHeight(32)
            btn.setStyleSheet(_pipe_qss(col, False))
        self._btn_applied_pipe.clicked.connect(lambda: self._set_status_pipeline("applied"))
        self._btn_interview.clicked.connect(lambda: self._set_status_pipeline("interview"))
        self._btn_offer.clicked.connect(lambda: self._set_status_pipeline("offer"))
        self._btn_rejected.clicked.connect(lambda: self._set_status_pipeline("rejected"))
        for b in (self._btn_applied_pipe, self._btn_interview, self._btn_offer, self._btn_rejected):
            pipe.addWidget(b)
        pipe.addStretch()
        hl.addLayout(pipe)
        lay.addWidget(hdr)

        self._btn_open.clicked.connect(self._open_job)
        self._btn_save.clicked.connect(self._toggle_save)
        self._btn_dismiss.clicked.connect(self._toggle_dismiss)
        self._btn_undo_dis.clicked.connect(self._undo_dismiss)
        self._btn_rescore.clicked.connect(self._rescore_current)
        self._btn_bew_go.clicked.connect(self._go_to_bewerbung)

        # ── tabs ──────────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.currentChanged.connect(lambda i: setattr(self, "_active_tab", i))

        # Job Profile tab
        desc_w = QWidget(); desc_w.setStyleSheet(f"background: {P['card']};")
        desc_l = QVBoxLayout(desc_w); desc_l.setContentsMargins(0, 0, 0, 0)
        self._txt_desc = QTextEdit()
        self._txt_desc.setReadOnly(True)
        self._txt_desc.setStyleSheet("border: none; padding: 14px;")
        _set_palette(self._txt_desc, P['card'], P['text2'])
        desc_l.addWidget(self._txt_desc, 1)
        self._tabs.addTab(desc_w, "Job Profile")

        # Bewerbung tab (PDF viewer)
        self._tabs.addTab(self._build_bewerbung_tab(), "Application")

        # Notes tab
        notes_w = QWidget(); notes_w.setStyleSheet(f"background: {P['card']};")
        notes_l = QVBoxLayout(notes_w); notes_l.setContentsMargins(16, 14, 16, 14); notes_l.setSpacing(8)
        notes_hdr = QHBoxLayout()
        notes_hdr.addWidget(_label("Notes", size=11, color=P['text2'], bold=True))
        notes_hdr.addStretch()
        self._lbl_notes_saved = _label("", size=9, color=P['text3'])
        notes_hdr.addWidget(self._lbl_notes_saved)
        notes_l.addLayout(notes_hdr)
        self._txt_notes = QTextEdit()
        self._txt_notes.setStyleSheet("border: none;")
        _set_palette(self._txt_notes, P['card'], P['text'])
        self._txt_notes.setPlaceholderText("Your notes for this job… (auto-saved)")
        notes_l.addWidget(self._txt_notes, 1)
        self._tabs.addTab(notes_w, "Notes")
        self._notes_timer = QTimer(self); self._notes_timer.setSingleShot(True)
        self._notes_timer.timeout.connect(self._save_notes)
        self._txt_notes.textChanged.connect(self._on_notes_changed)

        lay.addWidget(self._tabs, 1)
        return panel

    # ── Bewerbung LaTeX tab ───────────────────────────────────────────────────

    def _build_bewerbung_tab(self) -> QWidget:
        w = QWidget(); w.setStyleSheet(f"background: {P['card']};")
        lay = QVBoxLayout(w); lay.setContentsMargins(16, 14, 16, 14); lay.setSpacing(8)

        # ── top bar ──────────────────────────────────────────────────────────
        bar = QHBoxLayout(); bar.setSpacing(6)
        _status = "📄 Application Documents" if self._latex_dir else "⚠ Application Documents folder not found"
        _col    = P['text3'] if self._latex_dir else P['amber']
        lbl_template = _label(_status, size=11, color=_col)
        lbl_template.setWordWrap(False)
        self._btn_create = _btn("📄 Create PDF", P['indigo'], P['indigo_d'], height=32, font_size=11)
        bar.addWidget(lbl_template, 1)
        bar.addWidget(self._btn_create)
        lay.addLayout(bar); lay.addWidget(_sep())

        # ── progress panel ────────────────────────────────────────────────────
        prog_frame = QFrame(); prog_frame.setObjectName("bpf")
        prog_frame.setStyleSheet(
            f"QFrame#bpf {{ background: {P['card2']}; border-radius: 10px; "
            f"border: 1px solid {P['border']}; }}"
        )
        pfl = QVBoxLayout(prog_frame); pfl.setContentsMargins(16, 12, 16, 12); pfl.setSpacing(5)

        step_row = QHBoxLayout(); step_row.setSpacing(0)
        self._lbl_bew_step = _label("Ready", size=12, color=P['text'], bold=True)
        self._lbl_bew_pct  = _mono("", size=10, color=P['text3'])
        self._lbl_bew_pct.setAlignment(Qt.AlignmentFlag.AlignRight)
        step_row.addWidget(self._lbl_bew_step, 1); step_row.addWidget(self._lbl_bew_pct)
        pfl.addLayout(step_row)

        self._bew_progress = QProgressBar()
        self._bew_progress.setFixedHeight(6)
        self._bew_progress.setRange(0, 100); self._bew_progress.setValue(0)
        self._bew_progress.setTextVisible(False)
        self._bew_progress.setStyleSheet(
            f"QProgressBar {{ background: {P['border']}; border-radius: 3px; border: none; }}"
            f"QProgressBar::chunk {{ border-radius: 3px; background: qlineargradient("
            f"x1:0,y1:0,x2:1,y2:0, stop:0 {P['indigo']}, stop:1 {P['purple']}); }}"
        )
        pfl.addWidget(self._bew_progress)

        self._lbl_bew_detail = _label("Select a job and press Create PDF", size=10, color=P['text3'])
        pfl.addWidget(self._lbl_bew_detail)

        self._lbl_bew_target = _label("", size=11, color=P['text2'], bold=True)
        self._lbl_bew_target.setWordWrap(True)
        pfl.addWidget(self._lbl_bew_target)
        lay.addWidget(prog_frame)

        # ── post-creation actions ─────────────────────────────────────────────
        self._bew_action_row = QWidget()
        act_lay = QHBoxLayout(self._bew_action_row)
        act_lay.setContentsMargins(0, 2, 0, 2); act_lay.setSpacing(6)
        self._lbl_bew_job_status = _label("", size=10, color=P['text3'])
        self._btn_open_bew_folder  = _btn("📂 Open Folder",       P['card2'], P['card3'], height=28, font_size=10)
        self._btn_mark_applied_bew = _btn("✓ Mark as applied", P['green'], P['green'], height=28, font_size=10)
        act_lay.addWidget(self._lbl_bew_job_status, 1)
        act_lay.addWidget(self._btn_open_bew_folder)
        act_lay.addWidget(self._btn_mark_applied_bew)
        self._btn_open_bew_folder.hide()
        self._btn_mark_applied_bew.hide()
        lay.addWidget(self._bew_action_row)
        lay.addWidget(_sep())

        def _open_bew_folder():
            folder = self._bew_out_dir or os.path.normpath(os.path.join(os.path.expanduser("~"), "Desktop", "Bewerbungen"))
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)

        def _mark_applied_from_bew():
            jid = self._current_bew_job_id
            if jid:
                db.set_status(jid, "applied")
                if jid in self._cards:
                    self._cards[jid].job["status"] = "applied"
                    self._cards[jid]._rebuild_tags()
                    self._cards[jid]._apply_style()
                self._btn_mark_applied_bew.setEnabled(False)
                self._btn_mark_applied_bew.setText("✓ Applied")

        self._btn_open_bew_folder.clicked.connect(_open_bew_folder)
        self._btn_mark_applied_bew.clicked.connect(_mark_applied_from_bew)

        # ── PDF preview scroll area ───────────────────────────────────────────
        self._bew_scroll = QScrollArea()
        self._bew_scroll.setWidgetResizable(True)
        self._bew_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._bew_scroll.setStyleSheet("background: transparent; border: none;")
        self._bew_page_container = QWidget()
        self._bew_page_container.setStyleSheet("background: transparent;")
        self._bew_page_layout = QVBoxLayout(self._bew_page_container)
        self._bew_page_layout.setContentsMargins(0, 0, 0, 0); self._bew_page_layout.setSpacing(8)
        self._bew_page_layout.addStretch()
        self._bew_scroll.setWidget(self._bew_page_container)
        lay.addWidget(self._bew_scroll, 1)

        # ── show lebenslauf preview on startup ───────────────────────────────
        if self._latex_dir:
            for _f in os.listdir(self._latex_dir) if os.path.isdir(self._latex_dir) else []:
                if _f.lower().endswith(".pdf"):
                    _pdf = os.path.join(self._latex_dir, _f)
                    QTimer.singleShot(300, lambda p=_pdf: self._bew_pdf_ready.emit(p))
                    break

        self._btn_create.clicked.connect(self._create_application_pdf)
        return w

    def _update_bew_status(self):
        """Update status label in Bewerbung tab for currently selected job."""
        job = getattr(self, "_selected", None)
        if not job:
            self._lbl_bew_job_status.setText("")
            self._lbl_bew_target.setText("")
            return
        company = job.get("company") or ""
        target_text = job["title"] + (f"  ·  {company}" if company else "")
        self._lbl_bew_target.setText(target_text)
        jid = job["id"]
        path = self._bewerbung_paths.get(jid, "")
        if path:
            self._lbl_bew_job_status.setText(f"✔ {os.path.basename(path)}")
            self._lbl_bew_job_status.setStyleSheet(f"color: {P['green']}; font-size: 10px;")
            self._btn_open_bew_folder.show()
            self._btn_mark_applied_bew.show()
            already = job.get("status") == "applied"
            self._btn_mark_applied_bew.setEnabled(not already)
            self._btn_mark_applied_bew.setText("✓ Applied" if already else "✓ Mark as applied")
        else:
            self._lbl_bew_job_status.setText("No application created yet")
            self._lbl_bew_job_status.setStyleSheet(f"color: {P['text3']}; font-size: 10px;")
            self._btn_open_bew_folder.hide()
            self._btn_mark_applied_bew.hide()

    def _on_bew_progress(self, pct: int, step: str, detail: str):
        if pct < 0:
            self._bew_progress.setRange(0, 0)  # pulsing indeterminate
        else:
            self._bew_progress.setRange(0, 100)
            self._bew_progress.setValue(pct)
        self._lbl_bew_step.setText(step)
        self._lbl_bew_detail.setText(detail)
        if pct == 100:
            self._lbl_bew_pct.setText("100 %")
            self._btn_create.setEnabled(True)
            if self._bew_creating and self._current_bew_out_path:
                jid = self._current_bew_job_id
                self._bewerbung_paths[jid] = self._current_bew_out_path
                self._update_bew_status()
            self._bew_creating = False
        elif pct > 0:
            self._lbl_bew_pct.setText(f"{pct} %")
        elif pct == 0:
            self._lbl_bew_pct.setText("")
            self._btn_create.setEnabled(True)
            self._bew_creating = False
        else:
            self._lbl_bew_pct.setText("…")

    def _render_bew_pdf(self, pdf_path: str):
        import fitz
        while self._bew_page_layout.count() > 1:
            item = self._bew_page_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        try:
            doc = fitz.open(pdf_path)
            for page in doc:
                pix  = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                qpix = QPixmap(); qpix.loadFromData(pix.tobytes("png"))
                lbl  = QLabel(); lbl.setPixmap(qpix); lbl.setFixedSize(qpix.size())
                lbl.setStyleSheet("background: white; border-radius: 4px;")
                wrapper = QWidget(); wrapper.setStyleSheet("background: transparent;")
                wl = QHBoxLayout(wrapper); wl.setContentsMargins(0, 0, 0, 0)
                wl.addStretch(); wl.addWidget(lbl); wl.addStretch()
                self._bew_page_layout.insertWidget(self._bew_page_layout.count() - 1, wrapper)
            doc.close()
        except Exception as exc:
            self._lbl_bew_detail.setText(f"Preview error: {exc}")

    def _find_soffice(self) -> str | None:
        for p in [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            "soffice",
        ]:
            if os.path.isfile(p) or shutil.which(p):
                return p
        return None

    def _find_pdflatex(self) -> str | None:
        candidates = [
            r"C:\Program Files\MiKTeX\miktex\bin\x64\pdflatex.exe",
            r"C:\texlive\2024\bin\windows\pdflatex.exe",
            r"C:\texlive\2023\bin\windows\pdflatex.exe",
            "pdflatex",
        ]
        for p in candidates:
            if os.path.isfile(p) or shutil.which(p):
                return p
        return None

    def _create_application_pdf(self):
        if self._bew_creating:
            return
        job = self._selected
        if not job:
            QMessageBox.warning(self, "No Job Selected", "Please select a job first."); return
        if not self._latex_dir or not os.path.isdir(self._latex_dir):
            QMessageBox.warning(self, "No Folder Selected", "Please select the application folder first (📂 Select Folder)."); return

        title   = job.get("title", "") or "Position"
        today   = datetime.now().strftime("%d.%m.%Y")
        company = (job.get("company") or "").replace("/", "-").replace("\\", "-") or "Application"
        def _to_latex(s: str) -> str:
            return (s
                .replace("&",  r"\&")
                .replace("%",  r"\%")
                .replace("#",  r"\#")
                .replace("$",  r"\$")
                .replace("{",  r"\{")
                .replace("}",  r"\}")
                .replace("~",  r"\textasciitilde{}")
                .replace("^",  r"\textasciicircum{}")
                .replace("_",  r"\_")
                .replace("ä",  r'\"a').replace("Ä", r'\"A')
                .replace("ö",  r'\"o').replace("Ö", r'\"O')
                .replace("ü",  r'\"u').replace("Ü", r'\"U')
                .replace("ß",  r'\ss{}')
            )
        title_latex = _to_latex(title)

        out_dir = os.path.normpath(os.path.join(
            os.path.expanduser("~"), "Desktop", "Bewerbungen",
            datetime.now().strftime("%Y-%m-%d")
        ))
        os.makedirs(out_dir, exist_ok=True)
        base_name = f"Application_{company}_{datetime.now().strftime('%Y-%m-%d')}"
        out_path  = os.path.join(out_dir, base_name + ".pdf")
        counter   = 1
        while os.path.isfile(out_path):
            out_path = os.path.join(out_dir, f"{base_name}_{counter}.pdf")
            counter += 1

        self._bew_out_dir          = out_dir
        self._current_bew_job_id   = job["id"]
        self._current_bew_out_path = out_path
        self._bew_creating = True
        self._btn_create.setEnabled(False)

        latex_dir = self._latex_dir

        def _work():
            _log_path = os.path.join(os.path.expanduser("~"), "Desktop", "ah_debug.txt")
            def _log(msg):
                with open(_log_path, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")

            try:
                _log(f"=== CREATE PDF ===")
                _work_inner(_log)
            except Exception as exc:
                import traceback
                tb = traceback.format_exc()
                _log(f"EXCEPTION: {tb}")
                self._bew_progress_sig.emit(0, "Error", tb[-400:])
                self._bew_creating = False

        def _work_inner(_log):
            import fitz

            pdflatex = self._find_pdflatex()
            _log(f"pdflatex: {pdflatex}")
            if not pdflatex:
                self._bew_progress_sig.emit(0, "Error", "pdflatex not found — install MiKTeX/TeX Live"); return

            _log(f"latex_dir: {latex_dir}  exists={os.path.isdir(latex_dir)}")
            if not os.path.isdir(latex_dir):
                self._bew_progress_sig.emit(0, "Error", f"Folder not found: {latex_dir}"); return

            # Use fixed _work subfolder — avoids tempfile issues in frozen EXE
            work = os.path.join(latex_dir, "_work")
            if os.path.exists(work):
                shutil.rmtree(work)
            os.makedirs(work)

            self._bew_progress_sig.emit(10, "Preparing…", "Copying files")
            for entry in os.listdir(latex_dir):
                if entry.startswith("_") or entry.lower() in ("applications", "bewerbungen"):
                    continue
                src_e = os.path.join(latex_dir, entry)
                dst_e = os.path.join(work, entry)
                if os.path.isfile(src_e):
                    shutil.copy2(src_e, dst_e)
                elif os.path.isdir(src_e):
                    shutil.copytree(src_e, dst_e)
            _log(f"work files: {os.listdir(work)}")

            self._bew_progress_sig.emit(20, "Replacing placeholders…", title[:60])
            for tex_name in ("deckblatt.tex", "anschreiben.tex"):
                p = os.path.join(work, tex_name)
                if not os.path.isfile(p):
                    continue
                src = open(p, encoding="utf-8").read()
                src = src.replace("{{JOBTITEL}}", title_latex)
                src = src.replace("{{DATUM}}", today)
                open(p, "w", encoding="utf-8").write(src)

            pdfs = []
            for i, tex_name in enumerate(("deckblatt.tex", "anschreiben.tex", "lebenslauf.tex")):
                tex_path = os.path.join(work, tex_name)
                if not os.path.isfile(tex_path):
                    _log(f"MISSING: {tex_name}")
                    self._bew_progress_sig.emit(0, "Error", f"Missing: {tex_name}"); return
                label = os.path.splitext(tex_name)[0].capitalize()
                self._bew_progress_sig.emit(30 + i * 18, f"Compiling {label}…", tex_name)
                result = subprocess.run(
                    [pdflatex, "-interaction=batchmode",
                     "-output-directory", work, tex_path],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=work, timeout=120,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                pdf_out = os.path.join(work, os.path.splitext(tex_name)[0] + ".pdf")
                _log(f"{tex_name}: rc={result.returncode} pdf={os.path.isfile(pdf_out)}")
                if not os.path.isfile(pdf_out):
                    err = result.stdout.decode(errors="ignore")[-400:]
                    _log(f"STDOUT: {err}")
                    self._bew_progress_sig.emit(0, f"pdflatex failed: {label}", err); return
                pdfs.append(pdf_out)

            self._bew_progress_sig.emit(88, "Saving…", out_path)
            merged = fitz.open()
            for pdf_path in pdfs:
                with fitz.open(pdf_path) as doc:
                    merged.insert_pdf(doc)
            merged.save(out_path)
            merged.close()

            shutil.rmtree(work, ignore_errors=True)

            self._bew_progress_sig.emit(100, "✔  Done!", os.path.basename(out_path))
            self._bew_pdf_ready.emit(out_path)

        threading.Thread(target=_work, daemon=True).start()

    # ── job profile HTML ──────────────────────────────────────────────────────

    def _build_desc_html(self, job: dict, loading: bool = False) -> str:
        c = P
        reason = html.escape(job.get("relevance_reason") or "")
        reason_block = (
            f'<div style="margin:0 0 18px 0;padding:10px 14px;background:{c["indigo_bg"]};'
            f'border-radius:8px;border-left:3px solid {c["indigo"]};">'
            f'<div style="color:{c["indigo"]};font-size:9px;font-weight:700;'
            f'letter-spacing:1px;margin-bottom:4px;">RELEVANCE REASON</div>'
            f'<div style="color:{c["text2"]};font-size:12px;">{reason}</div></div>'
        ) if reason else ""

        if loading:
            body = (
                f'<div style="color:{c["text3"]};font-size:13px;font-style:italic;padding:8px 0;">'
                f'● Loading description…</div>'
            )
        else:
            desc_plain = strip_html(job.get("description") or "")
            if len(desc_plain.strip()) > 30:
                body = _format_desc_html(desc_plain, c, job.get("title", ""))
            else:
                url = html.escape(job.get("url") or "")
                body = (
                    f'<div style="color:{c["text3"]};font-size:13px;">'
                    f'No description available.<br><br>'
                    f'<a href="{url}" style="color:{c["indigo"]};">'
                    f'Open job posting →</a></div>'
                )

        return (
            f'<html><body style="margin:16px 20px;font-family:\'Segoe UI\',sans-serif;'
            f'background:{c["card"]};color:{c["text2"]};">'
            f'{reason_block}{body}</body></html>'
        )

    # ── job list ──────────────────────────────────────────────────────────────

    def _funnel_html(self, counts: dict) -> str:
        c = P
        f = f"font-family:{MONO_FONT};font-size:12px;"
        return (
            f'<span style="{f}color:{c["text3"]};">PIPELINE  </span>'
            f'<span style="{f}color:{c["text2"]};">NEW</span> '
            f'<b style="{f}color:{c["text2"]};">{counts.get("new", 0)}</b>'
            f'<span style="{f}color:{c["text3"]};"> · </span>'
            f'<span style="{f}color:{c["indigo"]};">APPLIED</span> '
            f'<b style="{f}color:{c["indigo"]};">{counts.get("applied", 0)}</b>'
            f'<span style="{f}color:{c["text3"]};"> · </span>'
            f'<span style="{f}color:{c["amber"]};">INTERVIEW</span> '
            f'<b style="{f}color:{c["amber"]};">{counts.get("interview", 0)}</b>'
            f'<span style="{f}color:{c["text3"]};"> · </span>'
            f'<span style="{f}color:{c["green"]};">OFFER</span> '
            f'<b style="{f}color:{c["green"]};">{counts.get("offer", 0)}</b>'
        )

    def _load_jobs(self):
        cat = None if self._filter_cat in ("All", "All Categories") else self._filter_cat.lower()
        status_filter = self._saved_sub_filter if self._view == "saved" and self._saved_sub_filter else self._quick_status
        self._jobs = db.get_jobs(
            min_score=self._score_slider.value(),
            category=cat,
            show_dismissed=self._show_dismissed,
            view=self._view,
            search_text=self._search_input.text().strip(),
            sort=self._sort_combo.currentData(),
            ai_only=self._chk_ai_only.isChecked(),
            new_only=self._quick_new_only,
            unviewed_only=self._quick_unviewed,
            status_filter=status_filter,
            workspace=self._workspace,
        )
        counts = db.get_pipeline_counts()
        self._lbl_funnel.setText(self._funnel_html(counts))
        self._lbl_applied_count.setText(f"✓  {counts.get('applied', 0)}  APPLIED")
        self._render_list()
        self._total_jobs_cache = len(db.get_jobs(show_dismissed=True))
        col = P['amber'] if self._total_jobs_cache > 0 else P['text3']
        self._st_total.setText(str(self._total_jobs_cache))
        self._st_total.setStyleSheet(
            f"color: {col}; font-size: 18px; font-weight: 700; "
            f"font-family: '{MONO_FONT}'; background: transparent;"
        )
        saved_last = search_engine.search_status.get("saved", 0)
        self._lbl_idle_db.setText(
            f"DB  {self._total_jobs_cache} jobs" + (f"  ·  {saved_last} new last run" if saved_last else "")
        )

    def _render_list(self):
        sb = self._scroll.verticalScrollBar()
        _saved_scroll = sb.value()
        _had_selected = self._selected is not None

        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._cards.clear()
        n = len(self._jobs)
        self._lbl_count.setText(f"{n} jobs")
        nd = len([j for j in self._jobs if not j.get("dismissed")])
        self._btn_dismiss_all.setText(f"✕ Dismiss ({nd})" if nd else "✕ Dismiss")
        self._lbl_count.setStyleSheet(
            f"color: {P['green'] if n > 0 else P['red']}; "
            f"font-size: 10px; font-family: '{MONO_FONT}';"
        )
        for job in self._jobs:
            card = JobCard(job)
            if self._selected and self._selected["id"] == job["id"]:
                card.set_selected(True)
            card.clicked.connect(self._select)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)
            self._cards[job["id"]] = card
        # auto-select first if none selected or selection gone
        ids = {j["id"] for j in self._jobs}
        if self._jobs and (self._selected is None or self._selected["id"] not in ids):
            self._select(self._jobs[0])
        elif _had_selected and self._selected and self._selected["id"] in self._cards:
            # restore scroll position — don't jump to top when list updates during AI scoring
            QTimer.singleShot(0, lambda: sb.setValue(_saved_scroll))

    # ── selection & detail ────────────────────────────────────────────────────

    def _select(self, job: dict):
        # flush pending notes before switching jobs
        if self._selected and self._selected["id"] != job["id"]:
            if self._notes_timer.isActive():
                self._notes_timer.stop()
                self._save_notes()
        if self._selected and self._selected["id"] in self._cards:
            self._cards[self._selected["id"]].set_selected(False)
        self._selected = job
        if job["id"] in self._cards:
            self._cards[job["id"]].set_selected(True)
            self._scroll.ensureWidgetVisible(self._cards[job["id"]])
        self._show_detail(job)
        self._maybe_fetch_desc(job)
        self._update_bew_status()

    def _maybe_fetch_desc(self, job: dict):
        """For BA jobs with short/empty descriptions, fetch full text in background."""
        if job.get("source") != "ba":
            return
        if len((job.get("description") or "").strip()) > 200:
            return
        refnr = (job.get("url") or "").rstrip("/").split("/")[-1]
        if not refnr or len(refnr) < 5:
            return
        job_id = job["id"]
        self._txt_desc.setHtml(self._build_desc_html(job, loading=True))
        _log_activity(f"Fetching description for {refnr}", "info")

        def _run():
            desc = ""
            try:
                from backend.services.ba_fetch import fetch_description
                desc = asyncio.run(fetch_description(refnr))
                _log_activity(f"BA desc fetched: {len(desc)} chars for {refnr}", "info")
            except Exception as e:
                _log_activity(f"BA desc error ({refnr}): {e}", "info")
            self._ba_desc_ready.emit(job_id, desc)  # thread-safe signal

        threading.Thread(target=_run, daemon=True).start()

    def _ba_desc_done(self, job_id: int, desc: str):
        if desc:
            db.update_job_description(job_id, desc)
        if self._selected and self._selected["id"] == job_id:
            if desc:
                self._selected["description"] = desc
            self._txt_desc.setHtml(self._build_desc_html(self._selected))

    def _update_detail_header(self, job: dict):
        if not job.get("viewed"):
            db.mark_viewed(job["id"])
            job["viewed"] = True
            if job["id"] in self._cards:
                self._cards[job["id"]].job["viewed"] = True
                self._cards[job["id"]]._apply_style()
        self._lbl_title.setText(job["title"])
        parts = [p for p in [job.get("company"), job.get("location")] if p]
        if job.get("posted_at"):
            parts.append(str(job["posted_at"])[:10])
        self._lbl_meta.setText("  ·  ".join(parts))

        score = job.get("relevance_score")
        ai_scored = (job.get("relevance_reason") or "").startswith("[AI]")
        fg, bg = score_col(score)
        score_text = (f"✦ {score}" if ai_scored else str(score)) if score is not None else "—"
        self._lbl_score.setText(score_text)
        self._lbl_score.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 8px; "
            f"padding: 5px 14px; font-size: 16px; font-weight: 700;"
        )
        self._lbl_reason.setText(job.get("relevance_reason") or "")

        while self._tag_row.count():
            item = self._tag_row.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        cat = job.get("category", "")
        if cat in CAT: self._tag_row.addWidget(_pill(cat.upper(), *CAT[cat]))
        src = job.get("source", "")
        if src: self._tag_row.addWidget(_pill(src.upper(), P['text3'], P['border']))
        self._tag_row.addStretch()

        self._txt_desc.setHtml(self._build_desc_html(job))
        self._txt_desc.verticalScrollBar().setValue(0)

    def _update_detail_state(self, job: dict):
        self._tabs.setCurrentIndex(self._active_tab)

        self._refresh_save_btn(job.get("saved", False))
        self._btn_dismiss.setText("Restore" if job.get("dismissed", False) else "Dismiss")
        self._update_status_pipeline(job.get("status", "new"))

        self._txt_notes.blockSignals(True)
        self._txt_notes.setPlainText(db.get_notes(job["id"]) or "")
        self._txt_notes.blockSignals(False)
        self._lbl_notes_saved.setText("")

    def _show_detail(self, job: dict):
        self._update_detail_header(job)
        self._update_detail_state(job)

    def _clear_detail(self):
        self._lbl_title.setText("Select a job from the list")
        self._lbl_meta.setText(""); self._lbl_reason.setText("")
        self._lbl_score.setText("—")
        self._lbl_score.setStyleSheet(
            f"background: {P['border']}; color: {P['text3']}; border-radius: 8px; "
            f"padding: 5px 14px; font-size: 16px; font-weight: 700;"
        )
        while self._tag_row.count():
            item = self._tag_row.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._txt_desc.clear()
        self._update_status_pipeline("new")
        self._txt_notes.blockSignals(True); self._txt_notes.clear(); self._txt_notes.blockSignals(False)

    # ── actions ───────────────────────────────────────────────────────────────

    def _open_job(self):
        if self._selected: webbrowser.open(self._selected["url"])

    def _refresh_save_btn(self, saved: bool):
        self._btn_save.setText("● Saved" if saved else "Save")
        self._btn_save.setStyleSheet(
            f"QPushButton {{ background: {P['green_bg'] if saved else P['card2']}; "
            f"color: {P['green'] if saved else P['text']}; "
            f"border-radius: 8px; font-size: 12px; font-weight: 600; padding: 6px 14px; }}"
            f"QPushButton:hover {{ background: {'#0a2a18' if saved else P['card3']}; }}"
        )

    def _toggle_save(self):
        if not self._selected: return
        saved = db.toggle_save(self._selected["id"])
        self._selected["saved"] = saved
        self._refresh_save_btn(saved)
        jid = self._selected["id"]
        if jid in self._cards:
            self._cards[jid].job["saved"] = saved
            self._cards[jid]._rebuild_tags()
            self._cards[jid]._apply_style()

    def _toggle_dismiss(self):
        if not self._selected: return
        self._last_dismissed_id = self._selected["id"]
        self._btn_undo_dis.setEnabled(True)
        try:
            cur_idx = next(i for i, j in enumerate(self._jobs) if j["id"] == self._selected["id"])
        except StopIteration:
            cur_idx = 0
        db.toggle_dismiss(self._selected["id"])
        self._selected = None
        self._load_jobs()
        if self._jobs:
            self._select(self._jobs[min(cur_idx, len(self._jobs) - 1)])
        else:
            self._clear_detail()

    def _undo_dismiss(self):
        if self._last_dismissed_id is None: return
        db.undo_dismiss(self._last_dismissed_id)
        self._last_dismissed_id = None
        self._btn_undo_dis.setEnabled(False)
        self._load_jobs()

    def _rescore_current(self):
        if not self._selected: return
        if ai_score_engine.ai_score_status["running"]: return
        s = db.get_settings()
        model   = s["prefs"].get("ollama_model", "qwen2.5:14b")
        profile = _profile_text(s["profile"])
        prompt  = s["prefs"].get("ai_score_prompt", "")
        job     = self._selected
        self._btn_rescore.setText("✦ …")
        self._btn_rescore.setEnabled(False)

        def _run():
            from backend.services.ai_scorer import score_job_ai
            result = score_job_ai(
                job.get("title",""), job.get("company",""),
                job.get("description",""), profile, model, prompt,
            )
            if result["ok"]:
                db.update_job_ai_score(job["id"], result["score"], result["reason"])
                self._ai_job_ready.emit(job["id"], result["score"], result["reason"])
            QTimer.singleShot(0, lambda: (
                self._btn_rescore.setText("✦ Re-score"),
                self._btn_rescore.setEnabled(True),
            ))

        threading.Thread(target=_run, daemon=True).start()

    def _update_status_pipeline(self, status: str):
        self._btn_applied_pipe.setStyleSheet(_pipe_qss(P['indigo'], status == "applied"))
        self._btn_interview.setStyleSheet(   _pipe_qss(P['amber'],  status == "interview"))
        self._btn_offer.setStyleSheet(       _pipe_qss(P['green'],  status == "offer"))
        self._btn_rejected.setStyleSheet(    _pipe_qss(P['red'],    status == "rejected"))

    def _set_status_pipeline(self, status: str):
        if not self._selected: return
        new_status = db.set_status(self._selected["id"], status)
        self._selected["status"] = new_status
        self._update_status_pipeline(new_status)
        jid = self._selected["id"]
        if jid in self._cards:
            self._cards[jid].job["status"] = new_status
            self._cards[jid]._rebuild_tags()
            self._cards[jid]._apply_style()

    def _on_notes_changed(self):
        self._notes_timer.start(1000)
        self._lbl_notes_saved.setText("editing…")

    def _save_notes(self):
        if not self._selected: return
        text = self._txt_notes.toPlainText()
        db.save_notes(self._selected["id"], text)
        self._selected["notes"] = text
        self._lbl_notes_saved.setText("Saved")
        QTimer.singleShot(2000, lambda: self._lbl_notes_saved.setText(""))

    # ── search ────────────────────────────────────────────────────────────────

    def _start_search(self):
        if search_engine.search_status["running"]: return
        self._search_start = time.time()
        self._btn_search.setText("Searching…"); self._btn_search.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._progress.setRange(0, 100); self._progress.setValue(0)
        self._progress.setFormat("  ● Initialising…")
        search_engine.start_search(on_done=lambda: QTimer.singleShot(0, self._search_done))

    def _cancel_search(self):
        search_engine.cancel_search(); self._btn_cancel.setEnabled(False)

    # ── AI scoring ────────────────────────────────────────────────────────────

    def _on_ai_toggle(self):
        self._ai_auto_enabled = self._btn_ai_toggle.isChecked()
        self._apply_ai_toggle_style()

    def _apply_ai_toggle_style(self):
        on = self._ai_auto_enabled
        self._btn_ai_toggle.setText("AUTO  ON " if on else "AUTO  OFF")
        self._btn_ai_toggle.setStyleSheet(
            f"QPushButton {{ background: {P['purple_bg'] if on else P['card2']}; "
            f"color: {P['purple'] if on else P['text3']}; border-radius: 6px; "
            f"border: 1px solid {P['purple'] if on else P['border']}; "
            f"font-size: 11px; font-weight: 700; padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {'#2a0e50' if on else P['card3']}; }}"
        )

    def _start_ai_scoring(self):
        if ai_score_engine.ai_score_status["running"]: return
        s    = db.get_settings()
        jobs = db.get_jobs_for_ai_scoring(min_score=int(s["prefs"].get("ai_min_score", 40)))
        if not jobs:
            self._lbl_ai_phase.setText("nothing to score")
            return
        model   = s["prefs"].get("ollama_model", "qwen2.5:14b")
        profile = _profile_text(s["profile"])
        prompt  = s["prefs"].get("ai_score_prompt", "")
        self._btn_ai_start.setEnabled(False)
        self._btn_ai_cancel.setEnabled(True)
        _log_activity(f"AI scoring started: {len(jobs)} jobs queued", "info")
        ai_score_engine.start_scoring(
            jobs, model, profile, prompt,
            on_job_done =lambda jid, sc, rs: self._ai_job_ready.emit(jid, sc, rs),
            on_complete =lambda: QTimer.singleShot(0, self._ai_scoring_done),
        )

    def _ai_job_done(self, job_id: int, score: int, reason: str):
        for j in self._jobs:
            if j["id"] == job_id:
                j["relevance_score"] = score; j["relevance_reason"] = reason; break
        if score < 50:
            db.force_dismiss(job_id)
            for j in self._jobs:
                if j["id"] == job_id:
                    j["dismissed"] = True; break
            if self._selected and self._selected["id"] == job_id:
                self._selected = None
            self._ai_render_timer.start(800)
            return
        if self._selected and self._selected["id"] == job_id:
            self._selected["relevance_score"] = score
            self._selected["relevance_reason"] = reason
            self._show_detail(self._selected)
        self._ai_render_timer.start(800)

    def _ai_scoring_done(self):
        self._btn_ai_start.setEnabled(True)
        self._btn_ai_cancel.setEnabled(False)
        scored = ai_score_engine.ai_score_status.get("scored", 0)
        _log_activity(f"AI scoring complete — {scored} jobs updated", "info")
        # Disable new-only filter so AI-scored jobs from previous searches become visible
        self._chip_new.setChecked(False)
        self._quick_new_only = False
        self._load_jobs()
        self._update_filter_btn()
        if scored > 0:
            self._tray.showMessage(
                "Application Helper", f"AI scoring complete — {scored} jobs rated!",
                QSystemTrayIcon.MessageIcon.Information, 4000,
            )

    def _slbl(self, lbl, text: str, color: str):
        lbl.setText(text)
        lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-family: '{MONO_FONT}';")

    def _poll_ai(self):
        st = ai_score_engine.ai_score_status
        running = st["running"]
        total   = st["total"]
        done    = st["done"]
        phase   = st["phase"]
        eta_s   = st["eta_s"]
        current = st["current"]

        if running and total > 0:
            pct = int(done / total * 100)
            self._ai_progress.setValue(pct)
            self._ai_progress.setFormat(f"  ✦ {done}/{total}  ·  {pct}%")
            self._btn_ai_cancel.setEnabled(True)
            self._btn_ai_start.setEnabled(False)
            if eta_s >= 3600:
                eta_h, eta_rem = divmod(eta_s, 3600)
                eta_m2 = eta_rem // 60
                self._lbl_ai_eta.setText(f"ETA {eta_h}h {eta_m2}m")
            elif eta_s >= 60:
                eta_m, eta_s2 = divmod(eta_s, 60)
                self._lbl_ai_eta.setText(f"ETA {eta_m}m {eta_s2:02d}s")
            else:
                self._lbl_ai_eta.setText(f"ETA {eta_s}s")
            self._slbl(self._lbl_ai_phase, f"✦ {current}" if current else "✦ scoring…", P['purple'])
        elif phase == "done":
            scored = st.get("scored", 0)
            self._ai_progress.setValue(100)
            self._ai_progress.setFormat(f"  ✦ Done · {scored} updated")
            self._lbl_ai_eta.setText("")
            self._slbl(self._lbl_ai_phase, "done", P['green'])
        elif phase == "cancelling":
            self._ai_progress.setFormat("  cancelling…")
            self._slbl(self._lbl_ai_phase, "CANCELLING…", P['red'])
            self._lbl_ai_eta.setText("")
        elif phase == "cancelled":
            self._ai_progress.setFormat("  cancelled")
            self._slbl(self._lbl_ai_phase, "cancelled", P['red'])
            self._lbl_ai_eta.setText("")
        else:
            # throttle idle DB query to every ~5s (poll runs every 400ms → every 12 ticks)
            self._ai_idle_tick += 1
            if self._ai_idle_tick % 12 == 1:
                self._ai_unscored_cache = len(db.get_jobs_for_ai_scoring(40))
            self._ai_progress.setValue(0)
            self._ai_progress.setFormat(f"  IDLE · {self._ai_unscored_cache} queued" if self._ai_unscored_cache else "  IDLE")
            self._lbl_ai_eta.setText("")
            self._slbl(self._lbl_ai_phase, "idle", P['text3'])

    def _search_done(self):
        self._btn_search.setText("Start Search"); self._btn_search.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        saved = search_engine.search_status.get("saved", 0)
        self._progress.setValue(100)
        self._progress.setFormat(f"  ✓  {saved} new jobs saved")
        self._lbl_search_meta.setText("")
        QTimer.singleShot(3000, lambda: (
            self._progress.setValue(0),
            self._progress.setFormat("  READY"),
        ))
        self._run_auto_dismiss()
        if saved > 0:
            self._chip_new.setChecked(True)
            self._quick_new_only = True
            self._score_slider.blockSignals(True)
            self._score_slider.setValue(40)
            self._score_slider.blockSignals(False)
            self._lbl_min_score.setText("MIN SCORE  40")
        self._load_jobs(); self._update_last_search_label()
        self._update_filter_btn()
        if saved > 0:
            self._tray.showMessage("Application Helper", f"Search complete — {saved} new jobs found!",
                                   QSystemTrayIcon.MessageIcon.Information, 4000)
        if self._ai_auto_enabled:
            QTimer.singleShot(2000, self._start_ai_scoring)

    def _poll_search(self):
        st      = search_engine.search_status
        running = st.get("running", False)
        phase   = st.get("phase", "IDLE")
        fetched = st.get("fetched", 0)
        filtered = st.get("filtered", 0)
        saved   = st.get("saved", 0)

        if running:
            pct = _search_progress_pct(phase)
            self._progress.setValue(pct)
            self._progress.setFormat(f"  {pct}%  ·  {fetched} jobs fetched")
            elapsed = int(time.time() - getattr(self, "_search_start", time.time()))
            mins, secs = divmod(elapsed, 60)
            rate = fetched / max(elapsed, 1)
            self._lbl_search_meta.setText(f"{mins}:{secs:02d}  ·  {rate:.1f} j/s")
            self._btn_search.setEnabled(False); self._btn_search.setText("Searching…")
            self._btn_cancel.setEnabled(True)

        self._stats_frame.setVisible(running)
        self._lbl_idle_db.setVisible(not running)

        self._slbl(self._lbl_phase, ("● " if running else "") + phase.upper(),
                   P['green'] if running else P['text3'])

        def _val_style(col):
            return f"color: {col}; font-size: 20px; font-weight: 700; font-family: '{MONO_FONT}'; background: transparent;"

        self._st_fetched.setText(str(fetched) if fetched else "—")
        self._st_fetched.setStyleSheet(_val_style(
            P['green'] if fetched > 0 else (P['red'] if st.get('done') else P['text3'])
        ))
        self._st_filtered.setText(str(filtered) if filtered else "—")
        self._st_filtered.setStyleSheet(_val_style(P['amber'] if filtered > 0 else P['text3']))
        self._st_saved.setText(str(saved) if saved else "—")
        self._st_saved.setStyleSheet(_val_style(P['indigo'] if saved > 0 else P['text3']))
        self._update_topbar(running)

    def _update_topbar(self, running: bool):
        self._top_time.setText(time.strftime("%H:%M:%S"))
        if running:
            self._top_status.setText("● SEARCHING")
            self._top_status.setStyleSheet(f"color: {P['indigo']}; font-size: 10px; font-family: '{MONO_FONT}';")
            self._top_dot.setStyleSheet(f"color: {P['indigo']}; font-size: 10px; background: transparent;")
        else:
            self._top_status.setText("○ IDLE")
            self._top_status.setStyleSheet(f"color: {P['text3']}; font-size: 10px; font-family: '{MONO_FONT}';")
            self._top_dot.setStyleSheet(f"color: {P['green']}; font-size: 10px; background: transparent;")
        self._top_jobs_tick += 1
        if self._top_jobs_tick % 5 == 1:
            self._top_jobs.setText(f"DB  {self._total_jobs_cache} jobs")

    # ── filter / view ─────────────────────────────────────────────────────────

    def _on_score_slider(self, value: int):
        self._lbl_min_score.setText(f"MIN SCORE  {value}")
        self._load_jobs()
        self._update_filter_btn()

    def _on_view_change(self, view: str):
        self._view = view.lower()
        if self._view == "saved":
            self._fp_saved_sub.show()
            self._fp_chips_row.hide()
        else:
            self._fp_saved_sub.hide()
            self._fp_chips_row.show()
            self._saved_sub_filter = ""
        self._btn_filter_toggle.setChecked(False)
        self._filter_panel.hide()
        self._load_jobs()

    def _on_saved_sub(self, sub: str):
        self._saved_sub_filter = sub
        self._sfchip_all.setChecked(sub == "")
        self._sfchip_pending.setChecked(sub == "!applied")
        self._sfchip_applied.setChecked(sub == "applied")
        self._sfchip_interview.setChecked(sub == "interview")
        self._load_jobs()

    def _on_filter(self, *_):
        self._filter_cat     = self._cat_combo.currentText()
        self._show_dismissed = self._chk_dismissed.isChecked()
        self._load_jobs()
        self._update_filter_btn()

    def _on_chip_new(self):
        self._quick_new_only = self._chip_new.isChecked()
        self._load_jobs()
        self._update_filter_btn()

    def _on_chip_unviewed(self):
        self._quick_unviewed = self._chip_unviewed.isChecked()
        self._load_jobs()
        self._update_filter_btn()

    def _on_chip_interview(self):
        self._quick_status = "interview" if self._chip_interview.isChecked() else ""
        self._load_jobs()
        self._update_filter_btn()

    def _toggle_filter_panel(self):
        self._filter_panel.setVisible(self._btn_filter_toggle.isChecked())

    def _update_filter_btn(self):
        n = sum([
            self._chip_new.isChecked(),
            self._chip_unviewed.isChecked(),
            self._chip_interview.isChecked(),
            bool(self._search_input.text().strip()),
            self._cat_combo.currentIndex() > 0,
            self._score_slider.value() > 0,
            self._chk_dismissed.isChecked(),
            self._chk_ai_only.isChecked(),
        ])
        self._btn_filter_toggle.setText(f"Filters ({n})" if n else "Filters")

    def _refresh_workspaces(self):
        workspaces = db.get_workspaces()
        self._workspace_combo.blockSignals(True)
        self._workspace_combo.clear()
        self._workspace_combo.addItem("All", "")
        for ws in workspaces:
            self._workspace_combo.addItem(ws, ws)
        self._workspace_combo.addItem("＋ New…", "__new__")
        idx = self._workspace_combo.findData(self._workspace)
        self._workspace_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self._workspace_combo.blockSignals(False)

    def _on_workspace_change(self, text: str):
        data = self._workspace_combo.currentData()
        if data == "__new__":
            from PyQt6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "New Workspace", "Workspace name:")
            if ok and name.strip():
                self._workspace = name.strip()
                search_engine.current_workspace = self._workspace
                self._refresh_workspaces()
                self._load_jobs()
            else:
                # revert to previous
                self._refresh_workspaces()
            return
        self._workspace = data  # "" = all workspaces
        search_engine.current_workspace = self._workspace or "default"
        self._load_jobs()

    def _run_auto_dismiss(self):
        days = int(db.get_settings()["prefs"].get("auto_dismiss_days", 0))
        if days <= 0:
            return
        n = db.auto_dismiss_old_jobs(days)
        if n > 0:
            _log_activity(f"Auto-dismissed {n} jobs older than {days} days", "db")

    def _dismiss_visible(self):
        to_dismiss = [j for j in self._jobs if not j.get("dismissed")]
        if not to_dismiss:
            return
        reply = QMessageBox.question(
            self, "Dismiss visible jobs",
            f"Dismiss all {len(to_dismiss)} visible jobs?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        db.bulk_dismiss([j["id"] for j in to_dismiss])
        _log_activity(f"Bulk dismissed {len(to_dismiss)} jobs", "db")
        self._load_jobs()

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Jobs", "jobs.csv", "CSV (*.csv)")
        if not path:
            return
        fields = ["title", "company", "location", "relevance_score", "status", "url", "relevance_reason"]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(self._jobs)
        _log_activity(f"Exported {len(self._jobs)} jobs to CSV", "db")

    def _clear_jobs(self):
        reply = QMessageBox.question(
            self, "Clear all jobs?",
            "This will permanently delete all jobs, applications and cover letters.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            db.clear_all_jobs()
            self._selected = None; self._clear_detail(); self._load_jobs()
            _log_activity("Job list cleared by user", "db")

    # ── auto-search & tray ────────────────────────────────────────────────────

    def _auto_search_check(self):
        if search_engine.search_status["running"]: return
        s     = db.get_settings()
        hours = int(s["prefs"].get("auto_search_hours", 0))
        if hours <= 0: return
        last  = s["prefs"].get("last_search_ts", "")
        if not last:
            self._start_search(); return
        try:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    last_dt = datetime.strptime(last, fmt); break
                except ValueError:
                    continue
            else:
                return
            if (datetime.utcnow() - last_dt).total_seconds() / 3600 >= hours:
                self._start_search()
        except Exception:
            pass

    def _update_last_search_label(self):
        s   = db.get_settings()
        ts  = s["prefs"].get("last_search_ts", "")
        new = s["prefs"].get("last_search_new", 0)
        self._lbl_last_search.setText(
            f"Last search: {ts}  ·  {new} new" if ts else "Last search: never"
        )

    # ── keyboard shortcuts ────────────────────────────────────────────────────

    def _next_unviewed(self):
        if not self._jobs: return
        start = 0
        if self._selected:
            try:
                start = next(i for i, j in enumerate(self._jobs) if j["id"] == self._selected["id"]) + 1
            except StopIteration:
                start = 0
        for i in range(start, len(self._jobs)):
            if not self._jobs[i].get("viewed"):
                self._select(self._jobs[i]); return
        for i in range(0, start):
            if not self._jobs[i].get("viewed"):
                self._select(self._jobs[i]); return
        if start < len(self._jobs):
            self._select(self._jobs[start])

    def _go_to_bewerbung(self):
        self._tabs.setCurrentIndex(1)
        self._create_application_pdf()

    def keyPressEvent(self, event):
        key = event.key()
        if   key == Qt.Key.Key_S: self._toggle_save()
        elif key == Qt.Key.Key_D: self._toggle_dismiss()
        elif key == Qt.Key.Key_A: self._set_status_pipeline("applied")
        elif key == Qt.Key.Key_B: self._go_to_bewerbung()
        elif key == Qt.Key.Key_N: self._tabs.setCurrentIndex(2)
        elif key == Qt.Key.Key_O: self._open_job()
        elif key == Qt.Key.Key_Tab: self._next_unviewed()
        elif key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            if not self._jobs: return
            if self._selected is None:
                idx = 0
            else:
                try:
                    cur = next(i for i, j in enumerate(self._jobs) if j["id"] == self._selected["id"])
                    idx = min(cur + 1, len(self._jobs) - 1) if key == Qt.Key.Key_Down else max(cur - 1, 0)
                except StopIteration:
                    idx = 0
            self._select(self._jobs[idx])
        else:
            super().keyPressEvent(event)

    # ── dialogs ───────────────────────────────────────────────────────────────

    def _open_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {P['card2']}; color: {P['text']}; "
            f"border: 1px solid {P['border2']}; border-radius: 8px; padding: 4px; "
            f"font-size: 12px; }}"
            f"QMenu::item {{ padding: 7px 18px; border-radius: 4px; }}"
            f"QMenu::item:selected {{ background: {P['indigo_bg']}; color: {P['indigo']}; }}"
            f"QMenu::separator {{ height: 1px; background: {P['border']}; margin: 4px 8px; }}"
        )
        menu.addAction("📊  Statistics",     self._open_stats)
        menu.addSeparator()
        menu.addAction("⚙  Settings",       self._open_settings)
        menu.addAction("🐛  Debug Console",  self._open_debug)
        menu.addSeparator()
        menu.addAction("📤  Export CSV",     self._export_csv)
        menu.addAction("🗑  Clear all jobs", self._clear_jobs)
        btn = self._btn_settings
        menu.exec(btn.mapToGlobal(btn.rect().topLeft()))

    def _open_stats(self):
        StatsDialog(self).exec()

    def _open_debug(self):
        if self._debug_win is None:
            self._debug_win = DebugWindow()  # no parent → separate taskbar entry
        self._debug_win.showNormal(); self._debug_win.raise_(); self._debug_win.activateWindow()

    def _open_settings(self):
        SettingsDialog(self).exec()


# ── settings dialog ───────────────────────────────────────────────────────────

class StatsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Statistics"); self.resize(520, 520)
        self.setStyleSheet(f"QDialog {{ background: {P['bg']}; }}")
        self._build()

    def _build(self):
        stats = db.get_stats()
        lay = QVBoxLayout(self); lay.setContentsMargins(28, 24, 28, 24); lay.setSpacing(18)
        lay.addWidget(_label("Statistics", size=16, color=P['text'], bold=True))
        lay.addWidget(_sep())

        def _bar_row(label: str, value: int, total: int, color: str):
            w = QWidget(); hl = QHBoxLayout(w); hl.setContentsMargins(0,0,0,0); hl.setSpacing(10)
            lbl = _mono(label, size=11, color=P['text2']); lbl.setFixedWidth(90)
            pct = value / max(total, 1)
            bar_bg = QFrame(); bar_bg.setFixedHeight(16); bar_bg.setStyleSheet(
                f"background:{P['card2']}; border-radius:4px;")
            bar_fill = QFrame(bar_bg); bar_fill.setFixedHeight(16)
            bar_fill.setFixedWidth(max(4, int(260 * pct)))
            bar_fill.setStyleSheet(f"background:{color}; border-radius:4px;")
            cnt = _mono(str(value), size=11, color=color); cnt.setFixedWidth(40)
            hl.addWidget(lbl); hl.addWidget(bar_bg, 1); hl.addWidget(cnt)
            return w

        total = max(stats["total"], 1)

        lay.addWidget(_label("Score distribution", size=12, color=P['text2'], bold=True))
        for band, col in [("0-25", P['red']), ("25-50", P['amber']), ("50-75", P['indigo']), ("75-100", P['green'])]:
            lay.addWidget(_bar_row(band, stats["score_bands"][band], total, col))

        lay.addWidget(_sep())
        lay.addWidget(_label("Categories", size=12, color=P['text2'], bold=True))
        cat_cols = {"it": CAT["it"][0], "wirtschaft": CAT["wirtschaft"][0], "unknown": P['text3']}
        for cat, col in cat_cols.items():
            lay.addWidget(_bar_row(cat.capitalize(), stats["categories"].get(cat, 0), total, col))

        lay.addWidget(_sep())
        lay.addWidget(_label("Application pipeline", size=12, color=P['text2'], bold=True))
        pipe_cols = [("new", P['text3']), ("applied", P['indigo']), ("interview", P['amber']),
                     ("offer", P['green']), ("rejected", P['red'])]
        pipe_total = max(sum(stats["pipeline"].values()), 1)
        for st, col in pipe_cols:
            lay.addWidget(_bar_row(st.capitalize(), stats["pipeline"].get(st, 0), pipe_total, col))

        lay.addWidget(_sep())
        summary_row = QHBoxLayout()
        for lbl, val, col in [
            ("Total jobs", stats["total"], P['text']),
            ("AI scored",  stats["ai_scored"], P['purple']),
            ("Viewed",     stats["viewed"], P['indigo']),
        ]:
            cell = QVBoxLayout()
            cell.addWidget(_label(str(val), size=22, color=col, bold=True))
            cell.addWidget(_label(lbl, size=10, color=P['text3']))
            summary_row.addLayout(cell)
        lay.addLayout(summary_row)
        lay.addStretch()

        close = _btn("Close", P['card2'], P['card3']); close.clicked.connect(self.accept)
        lay.addWidget(close)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings"); self.resize(680, 720)
        self.setStyleSheet(f"QDialog {{ background: {P['bg']}; }}")
        self._s = db.get_settings()
        self._build()

    def _build(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(24, 24, 24, 24); lay.setSpacing(16)
        lay.addWidget(_label("Settings", size=16, color=P['text'], bold=True)); lay.addWidget(_sep())
        tabs = QTabWidget(); tabs.setDocumentMode(True); lay.addWidget(tabs, 1)

        # Profile
        p_w = QWidget(); p_w.setStyleSheet(f"background: {P['card']};")
        p_l = QFormLayout(p_w); p_l.setContentsMargins(20, 20, 20, 20); p_l.setSpacing(12)
        p_l.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        prof = self._s["profile"]
        self._f = {k: QLineEdit(prof.get(k, "")) for k in
                   ["name","email","phone","address","degree","background","motivation"]}
        for lbl, key in [("Name","name"),("Email","email"),("Phone","phone"),("Address","address"),
                          ("Degree","degree"),("Background","background"),("Motivation","motivation")]:
            p_l.addRow(_label(lbl, size=11, color=P['text2']), self._f[key])
        tabs.addTab(p_w, "Profile")

        # AI / Preferences
        ai_w = QWidget(); ai_w.setStyleSheet(f"background: {P['card']};")
        ai_l = QVBoxLayout(ai_w); ai_l.setContentsMargins(20, 20, 20, 20); ai_l.setSpacing(12)
        prefs = self._s["prefs"]

        def _pref_row(title, widget, hint=None, stretch=False):
            ai_l.addWidget(_label(title, size=11, color=P['text2'], bold=True))
            if hint:
                ai_l.addWidget(_label(hint, size=10, color=P['text3']))
            ai_l.addWidget(widget, 1 if stretch else 0)
            ai_l.addWidget(_sep())

        self._f_extra = QTextEdit(); self._f_extra.setPlainText(prefs.get("extra_prompt", ""))
        self._f_extra.setFixedHeight(90)
        _pref_row("Extra instructions for AI", self._f_extra)

        from backend.services.ai_scorer import _DEFAULT_CUSTOM
        self._f_ai_score_prompt = QTextEdit()
        self._f_ai_score_prompt.setPlainText(prefs.get("ai_score_prompt", "") or _DEFAULT_CUSTOM)
        self._f_ai_score_prompt.setFixedHeight(120)
        _pref_row("AI Scorer Prompt", self._f_ai_score_prompt,
                  hint="Additional instructions for the AI when scoring jobs (optional).")

        self._f_model = QLineEdit(prefs.get("ollama_model", "qwen2.5:14b"))
        _pref_row("Ollama model", self._f_model)

        _AUTO_OPTS = ["Off","Every 1h","Every 2h","Every 4h","Every 8h","Every 12h","Every 24h"]
        _AUTO_VALS = [0, 1, 2, 4, 8, 12, 24]
        self._f_auto = QComboBox(); self._f_auto.addItems(_AUTO_OPTS)
        try: self._f_auto.setCurrentIndex(_AUTO_VALS.index(int(prefs.get("auto_search_hours", 0))))
        except ValueError: self._f_auto.setCurrentIndex(0)
        _pref_row("Auto-Search interval", self._f_auto)

        self._f_ai_min_score = QLineEdit(str(prefs.get("ai_min_score", 40)))
        _pref_row("AI Scoring — Min. Rule Score", self._f_ai_min_score,
                  hint="Only jobs with rule score ≥ X will be AI-scored.")

        _DISMISS_OPTS = ["Off", "7 days", "14 days", "30 days", "60 days", "90 days"]
        _DISMISS_VALS = [0, 7, 14, 30, 60, 90]
        self._f_dismiss = QComboBox(); self._f_dismiss.addItems(_DISMISS_OPTS)
        try: self._f_dismiss.setCurrentIndex(_DISMISS_VALS.index(int(prefs.get("auto_dismiss_days", 0))))
        except ValueError: self._f_dismiss.setCurrentIndex(0)
        _pref_row("Auto-dismiss jobs older than", self._f_dismiss,
                  hint="Jobs with status 'new' older than X days are automatically dismissed.")

        tabs.addTab(ai_w, "AI / Preferences")

        # ── Sources tab ──────────────────────────────────────────────────────
        src_w = QWidget(); src_w.setStyleSheet(f"background: {P['card']};")
        src_l = QVBoxLayout(src_w); src_l.setContentsMargins(20, 20, 20, 20); src_l.setSpacing(12)

        def _src_row(title, widget, hint=None):
            src_l.addWidget(_label(title, size=11, color=P['text2'], bold=True))
            if hint: src_l.addWidget(_label(hint, size=10, color=P['text3']))
            src_l.addWidget(widget); src_l.addWidget(_sep())

        src_l.addWidget(_label("Job Sources — API Keys", size=13, color=P['text'], bold=True))
        src_l.addWidget(_sep())

        self._f_adzuna_id  = QLineEdit(prefs.get("adzuna_app_id", ""))
        self._f_adzuna_id.setPlaceholderText("Adzuna App ID")
        _src_row("Adzuna App ID", self._f_adzuna_id,
                 hint="developer.adzuna.com → free 100 req/day")

        self._f_adzuna_key = QLineEdit(prefs.get("adzuna_app_key", ""))
        self._f_adzuna_key.setPlaceholderText("Adzuna App Key")
        self._f_adzuna_key.setEchoMode(QLineEdit.EchoMode.Password)
        _src_row("Adzuna App Key", self._f_adzuna_key)

        src_l.addWidget(_label("Jobicy: no key needed (free, auto-enabled)", size=10, color=P['green']))
        src_l.addStretch()
        tabs.addTab(src_w, "Sources")

        # ── Tools tab ────────────────────────────────────────────────────────
        tools_w = QWidget(); tools_l = QVBoxLayout(tools_w)
        tools_l.setContentsMargins(20, 20, 20, 20); tools_l.setSpacing(10)
        tools_l.addWidget(_label("Tools", size=13, color=P['text'], bold=True))
        tools_l.addWidget(_sep())

        def _tools_btn(label, fn, danger=False):
            bg = P['red_bg'] if danger else P['card2']
            ho = P['red'] + "33" if danger else P['card3']
            b = _btn(label, bg, ho)
            b.clicked.connect(fn)
            tools_l.addWidget(b)

        mw = self.parent()
        _tools_btn("⬡  Debug Console",  mw._open_debug)
        _tools_btn("↓  Export CSV",      mw._export_csv)
        tools_l.addWidget(_sep())

        def _rescore():
            import app.db as _db
            n = _db.rescore_all_jobs()
            mw._load_jobs()
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Re-Score", f"{n} jobs re-scored.")

        def _reset_ai():
            from PyQt6.QtWidgets import QMessageBox
            if QMessageBox.question(self, "Reset AI scores",
                "Reset AI scores for all jobs?\nAll jobs can be re-scored afterwards.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) != QMessageBox.StandardButton.Yes:
                return
            import app.db as _db
            n = _db.reset_ai_scores()
            mw._load_jobs()
            QMessageBox.information(self, "Reset AI scores", f"{n} AI scores reset.")

        _tools_btn("⟳  Re-Score all jobs (Rule)", _rescore)
        _tools_btn("✦  Reset AI scores", _reset_ai)
        tools_l.addWidget(_sep())
        _tools_btn("🗑  Clear all jobs", mw._clear_jobs, danger=True)
        tools_l.addStretch()
        tabs.addTab(tools_w, "Tools")

        btn_row = QHBoxLayout(); btn_row.addStretch()
        cancel = _btn("Cancel", P['card2'], P['card3']); cancel.clicked.connect(self.reject)
        save   = _btn("Save Settings", P['indigo'], P['indigo_d']); save.clicked.connect(self._save)
        btn_row.addWidget(cancel); btn_row.addSpacing(8); btn_row.addWidget(save)
        lay.addLayout(btn_row)

    def _save(self):
        _AUTO_VALS    = [0, 1, 2, 4, 8, 12, 24]
        _DISMISS_VALS = [0, 7, 14, 30, 60, 90]
        profile = {k: self._f[k].text() for k in self._f}
        prefs = {
            **self._s["prefs"],
            "extra_prompt":      self._f_extra.toPlainText(),
            "ai_score_prompt":   self._f_ai_score_prompt.toPlainText(),
            "ollama_model":      self._f_model.text().strip(),
            "auto_search_hours": _AUTO_VALS[self._f_auto.currentIndex()],
            "auto_dismiss_days": _DISMISS_VALS[self._f_dismiss.currentIndex()],
            "ai_min_score":      max(0, min(100, int(self._f_ai_min_score.text() or "40") if self._f_ai_min_score.text().strip().lstrip('-').isdigit() else 40)),
            "adzuna_app_id":     self._f_adzuna_id.text().strip(),
            "adzuna_app_key":    self._f_adzuna_key.text().strip(),
        }
        db.save_settings(profile, prefs)
        import backend.services.llm_service as svc
        lines = [
            f"Applicant: {profile.get('name','')}",
            f"Degree: {profile.get('degree','')}",
            f"Background: {profile.get('background','')}",
            f"Motivation: {profile.get('motivation','')}",
        ]
        ctx = "\n".join(l for l in lines if l.strip())
        svc._PROFILE_CONTEXT = ctx
        svc._SYSTEM_PROMPT = (
            f"You are a job application assistant. You know the following applicant profile:\n\n{ctx}\n\n"
            f"Always reply in English. Be precise and follow the required format."
        )
        self.accept()


# ── debug window ──────────────────────────────────────────────────────────────

class DebugWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(None, Qt.WindowType.Window)  # no parent → own taskbar entry
        self.setWindowTitle("Application Helper  ·  Debug Console")
        self.resize(1000, 740); self.setMinimumSize(800, 600)
        self.setStyleSheet(f"QWidget {{ background: {P['bg']}; }}")
        self._tick = 0; self._dot_state = True
        self._build()
        self._timer = QTimer(self); self._timer.timeout.connect(self._refresh); self._timer.start(1000)
        try:
            import psutil; nc = psutil.net_io_counters()
            self._prev_net = (nc.bytes_sent, nc.bytes_recv)
        except Exception:
            self._prev_net = (0, 0)
        self._prev_llm_count = 0
        self._refresh()

    def showEvent(self, event):
        super().showEvent(event)
        try:
            import ctypes, sys as _sys
            if _sys.platform == "win32":
                hwnd = int(self.winId())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                style = (style | 0x00040000) & ~0x00000080  # WS_EX_APPWINDOW, ~WS_EX_TOOLWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, -20, style)
                ctypes.windll.user32.ShowWindow(hwnd, 0)   # hide
                ctypes.windll.user32.ShowWindow(hwnd, 9)   # restore
        except Exception:
            pass

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(20, 16, 20, 16); root.setSpacing(12)

        hdr = QHBoxLayout()
        title = QLabel("DEBUG CONSOLE")
        title.setStyleSheet(f"color: {P['text']}; font-size: 13px; font-weight: 700; letter-spacing: 2px;")
        hdr.addWidget(title); hdr.addStretch()
        self._lbl_dot  = _label("●  LIVE", size=10, color=P['green'])
        self._lbl_time = _mono("", size=10, color=P['text3'])
        self._lbl_time.setFixedWidth(148)
        self._lbl_time.setAlignment(Qt.AlignmentFlag.AlignRight)
        hdr.addWidget(self._lbl_dot); hdr.addSpacing(14); hdr.addWidget(self._lbl_time)
        root.addLayout(hdr); root.addWidget(_sep())

        # status cards
        cards = QHBoxLayout(); cards.setSpacing(10)
        self._sc_rows = self._status_card(cards, "SEARCH ENGINE", P["indigo"])
        self._ac_rows = self._status_card(cards, "AI / LLM",      P["purple"])
        self._dc_rows = self._status_card(cards, "DATABASE",      P["amber"])
        self._nc_rows = self._status_card(cards, "NETWORK",       P["green"])
        root.addLayout(cards)

        # graphs
        graphs = QHBoxLayout(); graphs.setSpacing(10)
        self._g_cpu   = self._graph_card(graphs, "CPU USAGE", P['indigo'], "%",      100)
        self._g_ram   = self._graph_card(graphs, "RAM USAGE", P['purple'], "%",      100)
        self._g_net_s = self._graph_card(graphs, "NET SEND",  P['green'],  " KB/s", 1024)
        self._g_net_r = self._graph_card(graphs, "NET RECV",  P['amber'],  " KB/s", 1024)
        root.addLayout(graphs)

        # logs
        bottom = QHBoxLayout(); bottom.setSpacing(10)

        act = _card(bg=P['card']); act_l = QVBoxLayout(act)
        act_l.setContentsMargins(14, 12, 14, 12); act_l.setSpacing(6)
        ah = QHBoxLayout()
        ah.addWidget(_label("ACTIVITY LOG", size=11, color=P['text3'], bold=True)); ah.addStretch()
        self._lbl_events = _label("", size=11, color=P['text3']); ah.addWidget(self._lbl_events)
        act_l.addLayout(ah)
        self._txt_activity = QTextEdit(); self._txt_activity.setReadOnly(True)
        self._txt_activity.setStyleSheet(
            f"QTextEdit {{ background: {P['card2']}; border: 1px solid {P['border']}; "
            f"border-radius: 8px; color: {P['green']}; padding: 8px; "
            f"font-family: '{MONO_FONT}'; font-size: 10px; }}"
        )
        act_l.addWidget(self._txt_activity, 1); bottom.addWidget(act, 3)

        # AI decisions panel
        aid = _card(bg=P['card']); aid_l = QVBoxLayout(aid)
        aid_l.setContentsMargins(14, 12, 14, 12); aid_l.setSpacing(6)
        dh = QHBoxLayout()
        dh.addWidget(_label("AI DECISIONS", size=11, color=P['text3'], bold=True)); dh.addStretch()
        self._lbl_ai_dec_count = _label("0 scored", size=11, color=P['purple'])
        btn_clear_ai = _btn("Clear", P['card2'], P['card3'], height=22, font_size=10)
        def _clear_ai_decisions():
            from app.ai_score_engine import _decisions
            _decisions.clear()
            self._txt_ai_dec.clear()
            self._lbl_ai_dec_count.setText("0 scored")
        btn_clear_ai.clicked.connect(_clear_ai_decisions)
        dh.addSpacing(6); dh.addWidget(self._lbl_ai_dec_count)
        dh.addSpacing(6); dh.addWidget(btn_clear_ai)
        aid_l.addLayout(dh)
        self._txt_ai_dec = QTextEdit(); self._txt_ai_dec.setReadOnly(True)
        self._txt_ai_dec.setStyleSheet(
            f"QTextEdit {{ background: {P['card2']}; border: 1px solid {P['border']}; "
            f"border-radius: 8px; color: {P['text2']}; padding: 8px; "
            f"font-family: '{MONO_FONT}'; font-size: 11px; }}"
        )
        aid_l.addWidget(self._txt_ai_dec, 1); bottom.addWidget(aid, 3)

        llm = _card(bg=P['card']); llm_l = QVBoxLayout(llm)
        llm_l.setContentsMargins(14, 12, 14, 12); llm_l.setSpacing(6)
        lh = QHBoxLayout()
        lh.addWidget(_label("LLM CALLS", size=11, color=P['text3'], bold=True)); lh.addStretch()
        self._lbl_llm_count = _label("0 calls", size=11, color=P['purple']); lh.addWidget(self._lbl_llm_count)
        llm_l.addLayout(lh)
        self._txt_llm = QTextEdit(); self._txt_llm.setReadOnly(True)
        self._txt_llm.setStyleSheet(
            f"QTextEdit {{ background: {P['card2']}; border: 1px solid {P['border']}; "
            f"border-radius: 8px; color: {P['text2']}; padding: 8px; "
            f"font-family: '{MONO_FONT}'; font-size: 10px; }}"
        )
        unload = _btn("Unload Model", P['red_bg'], "#400c0c", height=26, font_size=10)
        unload.clicked.connect(lambda: (
            threading.Thread(
                target=llm_service.unload_model,
                args=(db.get_settings()["prefs"].get("ollama_model", "qwen2.5:14b"),),
                daemon=True,
            ).start(),
            _log_activity("LLM model unloaded", "info"),
        ))
        llm_l.addWidget(self._txt_llm, 1); llm_l.addWidget(unload, 0, Qt.AlignmentFlag.AlignRight)
        bottom.addWidget(llm, 2)
        root.addLayout(bottom, 1)

    def _status_card(self, parent_lay: QHBoxLayout, title: str, accent: str) -> list:
        frame = _card(bg=P['card2']); lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(5)
        hdr = QHBoxLayout()
        dot = QLabel("●"); dot.setStyleSheet(f"color: {accent}; font-size: 11px;")
        hdr.addWidget(dot); hdr.addWidget(_label(title, size=11, color=P['text3'], bold=True)); hdr.addStretch()
        lay.addLayout(hdr)
        rows = [_label("—", size=12, color=P['text2']) for _ in range(3)]
        for r in rows: lay.addWidget(r)
        lay.addStretch()
        parent_lay.addWidget(frame, 1)
        return rows

    def _graph_card(self, parent_lay: QHBoxLayout, title: str, color: str, unit: str, max_val=100) -> MiniGraph:
        frame = _card(bg=P['card2']); lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8); lay.setSpacing(4)
        lay.addWidget(_label(title, size=12, color=P['text3'], bold=True))
        g = MiniGraph(color, title, unit, max_val); lay.addWidget(g, 1)
        parent_lay.addWidget(frame, 1)
        return g

    def _refresh(self):
        import psutil
        self._tick += 1
        self._lbl_time.setText(time.strftime("%Y-%m-%d  %H:%M:%S"))
        self._dot_state = not self._dot_state
        self._lbl_dot.setStyleSheet(
            f"color: {P['green'] if self._dot_state else P['text3']}; font-size: 10px;"
        )

        # search card
        st = search_engine.search_status
        running = st.get("running", False); phase = st.get("phase", "Ready")
        r = self._sc_rows
        r[0].setText(f"Status:   {'● RUNNING' if running else '○ idle'}")
        r[0].setStyleSheet(f"color: {P['green'] if running else P['text3']}; font-size: 12px;")
        r[1].setText(f"Phase:    {phase}"); r[1].setStyleSheet(f"color: {P['text2']}; font-size: 12px;")
        r[2].setText(f"Fetched: {st.get('fetched',0)}   New: {st.get('saved',0)}")
        r[2].setStyleSheet(f"color: {P['text3']}; font-size: 12px;")

        # AI / LLM merged card
        ast = ai_score_engine.ai_score_status
        log = llm_service.get_log(); last = log[-1] if log else None
        a = self._ac_rows
        a[0].setText(f"AI: {'● RUNNING' if ast['running'] else '○ ' + ast['phase']}  ·  LLM: {len(log)} calls")
        a[0].setStyleSheet(f"color: {P['purple'] if ast['running'] else P['text3']}; font-size: 12px;")
        eta = ast['eta_s']
        if eta >= 3600:
            eta_str = f"ETA {eta//3600}h {(eta%3600)//60}m"
        elif eta >= 60:
            eta_str = f"ETA {eta//60}m {eta%60:02d}s"
        elif eta > 0:
            eta_str = f"ETA {eta}s"
        else:
            eta_str = f"avg {ast.get('avg_s', 0):.1f}s"
        a[1].setText(f"Scored: {ast.get('scored', 0)}/{ast['total']}  ·  {eta_str}")
        a[1].setStyleSheet(f"color: {P['text2']}; font-size: 12px;")
        last_txt = f"{last['purpose'][:22]}  ({last['duration_s']}s)" if last else "no calls yet"
        a[2].setText(f"Last: {last_txt}")
        a[2].setStyleSheet(f"color: {P['text3']}; font-size: 12px;")

        # db card — fetch once, derive counts from the result
        all_jobs = db.get_jobs(show_dismissed=True)
        total   = len(all_jobs)
        applied = sum(1 for j in all_jobs if j.get("status") == "applied")
        saved   = sum(1 for j in all_jobs if j.get("saved"))
        d = self._dc_rows
        d[0].setText(f"Total:    {total} jobs");  d[0].setStyleSheet(f"color: {P['amber']}; font-size: 12px;")
        d[1].setText(f"Saved:    {saved}");        d[1].setStyleSheet(f"color: {P['text2']}; font-size: 12px;")
        d[2].setText(f"Applied:  {applied}");      d[2].setStyleSheet(f"color: {P['text3']}; font-size: 12px;")

        # network card
        try:
            nc = psutil.net_io_counters()
            sent_kb = (nc.bytes_sent - self._prev_net[0]) / 1024
            recv_kb = (nc.bytes_recv - self._prev_net[1]) / 1024
            self._prev_net = (nc.bytes_sent, nc.bytes_recv)
        except Exception:
            sent_kb = recv_kb = 0.0
        n = self._nc_rows
        n[0].setText(f"↑ Send:   {sent_kb:.1f} KB/s"); n[0].setStyleSheet(f"color: {P['green']}; font-size: 12px;")
        n[1].setText(f"↓ Recv:   {recv_kb:.1f} KB/s"); n[1].setStyleSheet(f"color: {P['text2']}; font-size: 12px;")
        try: conns = len(psutil.net_connections(kind="inet"))
        except Exception: conns = 0
        n[2].setText(f"Conns:    {conns}"); n[2].setStyleSheet(f"color: {P['text3']}; font-size: 12px;")

        # graphs
        try:
            cpu = psutil.cpu_percent(interval=None); ram = psutil.virtual_memory().percent
        except Exception:
            cpu = ram = 0.0
        self._g_cpu.push(cpu); self._g_ram.push(ram)
        self._g_net_s.push(min(sent_kb, 1024)); self._g_net_r.push(min(recv_kb, 1024))

        # activity log auto-entries
        if running and self._tick % 2 == 0:
            _log_activity(f"Search engine: {phase}", "search")
        if self._tick % 5 == 0:
            _log_activity(f"System  CPU={cpu:.1f}%  RAM={ram:.1f}%", "sys")
        if self._tick % 10 == 0:
            _log_activity(f"Database  {total} jobs indexed", "db")

        # LLM new-call detection
        cur_count = len(log)
        if cur_count > self._prev_llm_count and log:
            newest = log[-1]
            _log_activity(f"LLM call: {newest['purpose'][:50]}  ({newest['duration_s']}s)", "info")
        self._prev_llm_count = cur_count
        self._lbl_llm_count.setText(f"{cur_count} calls")
        self._txt_llm.setPlainText("\n".join(
            f"[{e['ts']}] {e['purpose']:<40} {e['duration_s']}s" for e in log
        ))


        # AI decisions
        decisions = ai_score_engine.get_decisions()
        ok_count  = sum(1 for d in decisions if not d.get("error"))
        err_count = sum(1 for d in decisions if d.get("error"))
        count_txt = f"{ok_count} scored"
        if err_count:
            count_txt += f"  ·  {err_count} errors"
        self._lbl_ai_dec_count.setText(count_txt)
        dec_parts = []
        for d in reversed(decisions[-60:]):
            if d.get("error"):
                dec_parts.append(
                    f'<span style="color:{P["text3"]};">[{d["ts"]}]</span> '
                    f'<span style="color:{P["red"]};font-weight:700;">⚠ ERR</span> '
                    f'<span style="color:{P["text3"]};">{d["title"]}</span><br>'
                    f'<span style="color:{P["red"]};font-size:10px;">&nbsp;&nbsp;&nbsp;{d["reason"][:100]}</span>'
                )
                continue
            kept   = d["kept"]
            score  = d["score"]
            icon   = "✦" if kept else "✕"
            s_col  = P['green'] if score >= 60 else P['amber'] if score >= 30 else P['red']
            t_col  = P['text2'] if kept else P['text3']
            dec_parts.append(
                f'<span style="color:{P["text3"]};">[{d["ts"]}]</span> '
                f'<span style="color:{s_col};font-weight:700;">{icon} [{score:>3}]</span> '
                f'<span style="color:{t_col};">{d["title"]}</span>'
                f'<span style="color:{P["text3"]};"> · {d["company"]}</span><br>'
                f'<span style="color:{P["text3"]};font-size:10px;">&nbsp;&nbsp;&nbsp;{d["reason"][:90]}'
                f' &nbsp;<i>({d["time_s"]}s)</i></span>'
            )
        sb2 = self._txt_ai_dec.verticalScrollBar()
        _prev_scroll = sb2.value()
        _at_top = _prev_scroll <= sb2.minimum() + 4
        self._txt_ai_dec.setHtml("<br>".join(dec_parts) or
            f'<span style="color:{P["text3"]};">No AI decisions yet.</span>')
        sb2.setValue(sb2.minimum() if _at_top else _prev_scroll)

        # render activity log
        COLOR = {"search": P['indigo'], "sys": P['green'], "db": P['amber'], "info": P['text2']}
        parts = [
            f'<span style="color:{P["text3"]};">[{e["ts"]}]</span> '
            f'<span style="color:{COLOR.get(e["level"], P["text2"])};">{e["msg"]}</span>'
            for e in reversed(list(_ACTIVITY_LOG)[-60:])
        ]
        self._txt_activity.setHtml("<br>".join(parts))
        sb = self._txt_activity.verticalScrollBar(); sb.setValue(sb.minimum())
        self._lbl_events.setText(f"{len(_ACTIVITY_LOG)} events")


# ── helpers ───────────────────────────────────────────────────────────────────

def _profile_text(profile: dict) -> str:
    lines = [
        f"Name: {profile.get('name', '')}",
        f"Degree: {profile.get('degree', '')}",
        f"Background: {profile.get('background', '')}",
        f"Motivation: {profile.get('motivation', '')}",
    ]
    return "\n".join(l for l in lines if not l.endswith(": "))


def _set_palette(widget, bg: str, fg: str):
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Base, QColor(bg))
    pal.setColor(QPalette.ColorRole.Text, QColor(fg))
    widget.setPalette(pal)


def _make_app_icon() -> QIcon:
    px = QPixmap(256, 256); px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 0, 256)
    grad.setColorAt(0, QColor("#1e1e50")); grad.setColorAt(1, QColor("#08081a"))
    p.setBrush(QBrush(grad)); p.setPen(QPen(QColor("#6d6df5"), 10))
    p.drawRoundedRect(5, 5, 246, 246, 46, 46)
    p.setPen(QColor("#eeeef8")); p.setFont(QFont("Segoe UI Variable", 130, QFont.Weight.Bold))
    p.drawText(QRect(0, -10, 256, 256), Qt.AlignmentFlag.AlignCenter, "A")
    p.setPen(QPen(QColor("#6d6df5"), 14))
    p.drawLine(50, 198, 206, 198); p.drawLine(180, 174, 206, 198); p.drawLine(180, 222, 206, 198)
    p.end()
    return QIcon(px)


# ── entry point ───────────────────────────────────────────────────────────────

def run():
    import sys
    init_db()
    _log_activity("Application Helper started", "info")
    _log_activity("Database initialized", "db")
    _log_activity("UI loaded — waiting for commands", "sys")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(_qss())
    for name in ["Segoe UI Variable", "Segoe UI", "Inter"]:
        if name in QFontDatabase.families():
            app.setFont(QFont(name, 10)); break
    icon = _make_app_icon()
    app.setWindowIcon(icon)
    win = MainWindow(); win.setWindowIcon(icon); win.show()
    sys.exit(app.exec())
