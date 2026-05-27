"""LLM-based job relevance scoring. Short prompt, structured output."""
import re
import time

import ollama

_SYSTEM_TEMPLATE = """\
Du bewertest Stellenangebote für folgenden Bewerber:
{profile}

{custom_prompt}

Antworte NUR in exakt diesem Format (keine anderen Zeichen):
SCORE: [0-100]
REASON: [max. 1 Satz auf Deutsch]

SCORE-Skala: 0-20 unpassend · 20-50 schwach · 50-75 geeignet · 75-100 sehr gut\
"""

_DEFAULT_CUSTOM = """\
Du hilfst beim Bewerten und Aussortieren von Stellenangeboten für einen Bewerber mit B.Sc. Wirtschaftsinformatik (Hochschule Flensburg, ~06/2026). Hintergrund: KFZ-Meister mit Ausbilderschein, danach Studium – technisch-handwerkliche Praxis + betriebswirtschaftliches Studium.

GESUCHTE STELLEN: IT-nahe ODER wirtschaftsnahe Positionen – eines von beiden reicht. Beispiele: IT-Projektmanagement, Business Analyst, Prozessmanagement, Digitalisierung, Requirements Engineering, Controlling, Einkauf, Logistikmanagement, Verwaltung, Sachbearbeitung mit IT-Bezug, Wirtschaftsinformatik-nahe Rollen.

QUALIFIKATION: Stellen die eine Ausbildung, Berufsausbildung oder Berufserfahrung ohne Studium erfordern sind völlig in Ordnung – der Bewerber ist dann ggf. leicht überqualifiziert, aber bewerbbar. Nur wenn explizit ein Masterabschluss oder mehrjähriges Studium gefordert wird → leichter Abzug.

SCORING-REGELN (0–100):
• Einstiegsjobs / Berufseinsteiger / Junior / Trainee / Absolvent / Quereinsteiger → bevorzugen (+10)
• Öffentlicher Dienst, Behörden, Bundesagentur, Kommunen, Hochschulen → positiver bewerten (+15)
• Standort Deutschland, Österreich, Schweiz, Luxemburg → Bonus (+10); andere EU-Länder → neutral; außerhalb EU → Abzug (−15)
• Unternehmen mit ca. 50–5000 Mitarbeitern → bevorzugen; Kleinstunternehmen <10 MA → leichter Abzug (−5)
• Reine Programmierstellen (Software Developer, Full Stack, Java/Python-Entwickler, DevOps, SysAdmin) → aussortieren (Score 5–15)
• Jobs die Berufserfahrung von mehreren Jahren fordern oder als "wünschenswert" nennen (Formulierungen wie "mehrjährige Berufserfahrung", "mehrere Jahre Erfahrung", "3+ Jahre", "mindestens 2 Jahre") → aussortieren (Score 5–20) – auch wenn es nur "wünschenswert" heißt, da Berufseinsteiger hier nicht konkurrenzfähig sind
• Jobs im gehobenen/höheren Verwaltungsdienst, Leitungsfunktionen oder mit spezifischen Fachbereichserfahrungen (z.B. "Verwaltungssteuerung", "Hauptamt", Beamtenlaufbahn) → aussortieren (Score 5–20)
• Vertrieb (Außendienst), Call Center, Pflege, Handwerk, Logistik (Fahrer/Lager), Gastronomie → Score 0–10
• SAP-Beratung / ERP-Spezialist ohne klaren Business-Analyst-Fokus → Score 10–25
• Kaufmännische Sachbearbeitung, Bürokaufmann, Verwaltungsfachangestellte, Assistenz → Score 30–55 (machbar aber unter Qualifikation)

Sei fair aber realistisch. Bewirb dich nicht unter Wert, aber schließ auch nichts aus das passt.\
"""


def score_job_ai(
    title: str,
    company: str,
    description: str,
    profile: str,
    model: str = "qwen2.5:14b",
    custom_prompt: str = "",
) -> dict:
    system = _SYSTEM_TEMPLATE.format(
        profile=profile,
        custom_prompt=custom_prompt.strip() or _DEFAULT_CUSTOM,
    )
    desc_excerpt = (description or "")[:2000] or "—"
    user = f"STELLE: {title}\nFIRMA: {company or '—'}\nBESCHREIBUNG:\n{desc_excerpt}"

    t0 = time.time()
    try:
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            options={"temperature": 0.1, "num_predict": 100, "num_ctx": 4096},
        )
        text = resp["message"]["content"].strip()
        sm = re.search(r"SCORE:\s*(\d+)", text)
        rm = re.search(r"REASON:\s*(.+)", text, re.DOTALL)
        score  = min(100, max(0, int(sm.group(1)))) if sm else 25
        reason = rm.group(1).strip().split("\n")[0] if rm else "—"
        from backend.services.llm_service import log_call as _log_call
        _log_call(f"score · {title[:35]}", round(time.time() - t0, 1), model)
        return {"score": score, "reason": f"[AI] {reason}", "ok": True}
    except Exception as exc:
        return {"score": -1, "reason": f"[AI_ERR] {exc}", "ok": False}
