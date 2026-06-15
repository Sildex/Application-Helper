"""Shared title-exclusion filter used by db.py, search_engine.py and db cleanup."""
import re

RE_TITLE_EXCLUDE = re.compile(
    r'\b(werkstudent\w*|studiengang\w*|studiengäng\w*|referent\w*|studium\b|'
    r'praktikum\w*|praktikant\w*|'
    r'duales?\s+studi\w*|duale[rs]?\s+ausbildung|'
    r'steuerberater\w*|steuerfachangestellte\w*|buchhalter\w*|'
    r'ausbildung\s+zum|auszubildende\w*|azubi\w*|'
    r'bachelorarbeit\w*|masterarbeit\w*|abschlussarbeit\w*|'
    r'bachelor\s*thesis|master\s*thesis|'
    r'für\s+deine\s+bachelorarbeit|für\s+deine\s+masterarbeit|'
    r'senior\b|head\s+of|'
    r'koch\w*|köch\w*|küche\w*|küchen\w*|'
    r'arzt\w*|ärztin\w*|apothek\w*|'
    r'pflege\w*|altenpflege\w*|krankenpflege\w*|'
    r'lehrer\w*|lehrerin\w*|reinigung\w*)\b',
    re.IGNORECASE,
)
