# System Architecture
**Project:** AutoApply  
**Version:** 0.2  
**Date:** 2026-05-19  
**Status:** Final

---

## 1. Architekturstil

**Gewählt: Python-Backend (FastAPI) + React-Frontend – lokal im Browser**

### Warum kein Electron?
Electron = ~150MB Overhead, komplexer Build-Prozess, npm + Python parallel managen.  
Für ein persönliches lokales Tool unnötig. Stattdessen:

```
python start.py
→ FastAPI startet auf localhost:8000
→ React-Build wird als statische Files von FastAPI ausgeliefert
→ Browser öffnet automatisch (webbrowser.open)
```

Ergebnis: Ein Befehl, läuft im Browser, keine Installation außer Python + npm build einmalig.

### Warum nicht SerpAPI / kostenpflichtige APIs?
→ Bundesagentur für Arbeit API ist kostenlos, kein Key, beste DE-Abdeckung.  
→ Adzuna als kostenloser Fallback (250 calls/Tag, Key-Registrierung nötig).

---

## 2. Systemübersicht

```
  Browser (localhost:8000)
  ┌─────────────────────────────────────────────────┐
  │           React Frontend (Vite-Build)            │
  │  Dashboard │ Stellendetail │ Einstellungen       │
  └──────────────────┬──────────────────────────────┘
                     │ HTTP REST
  ┌──────────────────▼──────────────────────────────┐
  │           FastAPI Backend (Python)               │
  │  /jobs  /cover-letter  /profile  /apply          │
  └───┬──────────────────────────┬───────────────────┘
      │                          │
  ┌───▼──────────────┐  ┌────────▼─────────────┐
  │  BA Jobsuche API │  │   Claude API          │
  │  Adzuna API      │  │   (Anthropic SDK)     │
  │  (kostenlos)     │  │   Relevanz + Anschreiben│
  └──────────────────┘  └───────────────────────┘
      │
  ┌───▼──────────────────────────────────────────┐
  │         SQLite (lokal, persistent)            │
  │  jobs │ applications │ cover_letters │ config │
  └───────────────────────────────────────────────┘
```

---

## 3. Tech Stack (nach Kosten-Nutzen gewählt)

| Schicht | Technologie | Begründung |
|---|---|---|
| Backend | Python 3.12 + FastAPI | Async, schnell, auto-Docs, beste KI-SDK-Unterstützung |
| KI | Anthropic Python SDK (claude-sonnet-4-6) | Bestes Verhältnis Qualität/Kosten, Prompt Caching |
| Job-APIs | BA Arbeitsagentur API + Adzuna | 100% kostenlos, DE-Markt optimal abgedeckt |
| Datenbank | SQLite via SQLModel | Keine Installation, lokal, ausreichend für persönlichen Einsatz |
| Frontend | React 18 + Vite + TypeScript | Standard, schnell, komponentenbasiert |
| UI | shadcn/ui + Tailwind CSS | Fertige Komponenten, kein Design-Aufwand |
| State | TanStack Query | Server-State-Management, kein Redux |
| Start | `python start.py` | Startet Backend + öffnet Browser automatisch |

---

## 4. API-Endpunkte

```
GET  /api/jobs                    → Stellenliste (gefiltert, sortiert)
POST /api/jobs/search             → Neue Suche starten (async)
GET  /api/jobs/{id}               → Stellendetail
GET  /api/jobs/search/status      → Fortschritt der laufenden Suche

POST /api/cover-letter/{job_id}   → Anschreiben generieren (Claude)
PUT  /api/cover-letter/{job_id}   → Anschreiben speichern (editiert)

GET  /api/profile                 → Profil + Präferenzen laden
PUT  /api/profile                 → Profil speichern

POST /api/applications/{id}/apply → Status → "Versendet", gibt Job-URL zurück
```

---

## 5. Datenfluss: Stellensuche

```
User klickt "Suche starten"
    → POST /api/jobs/search (keywords, location, radius)
    → Background Task: BA API abrufen → normalisieren → SQLite
    → Pro Job (async): Claude bewertet Relevanz → Score + Reason
    → GET /api/jobs → gefiltert nach Score ≥ 60
    → Frontend pollt /search/status bis done
    → Dashboard aktualisiert sich
```

---

## 6. Datenfluss: Anschreiben

```
User klickt "Anschreiben generieren"
    → POST /api/cover-letter/{id}
    → Backend lädt Job-Beschreibung + User-Profil aus SQLite
    → Claude API: strukturierter Prompt → Anschreiben
    → Gespeichert in cover_letters-Tabelle
    → Frontend zeigt editierbaren Text-Editor
    → User bearbeitet → PUT speichert Änderungen
```

---

## 7. Projektstruktur

```
AutoApply/
├── start.py                  ← Einstiegspunkt: Backend + Browser
├── backend/
│   ├── main.py               ← FastAPI App
│   ├── models.py             ← SQLModel DB-Modelle
│   ├── database.py           ← SQLite-Verbindung
│   ├── routers/
│   │   ├── jobs.py
│   │   ├── cover_letter.py
│   │   └── profile.py
│   ├── services/
│   │   ├── ba_api.py         ← Bundesagentur API Client
│   │   ├── adzuna_api.py     ← Adzuna Client
│   │   ├── claude_service.py ← Anschreiben + Scoring
│   │   └── job_search.py     ← Orchestrierung
│   └── config.py             ← API-Keys, Einstellungen
├── frontend/
│   ├── src/
│   │   ├── pages/            ← Dashboard, Detail, Settings
│   │   ├── components/
│   │   └── api/              ← API-Client-Funktionen
│   └── package.json
├── docs/                     ← SE-Dokumentation
└── requirements.txt
```

---

## 8. Entschiedene offene Punkte

| Punkt | Entscheidung |
|---|---|
| Electron vs. Browser | Browser (FastAPI serviert React-Build) |
| Job-APIs | BA API (primär) + Adzuna (fallback), beide kostenlos |
| CV-Extraktion | Profil manuell/einmalig in `docs/06_user_profile.md` gepflegt; bereits aus PDF extrahiert |
| KI-Modell | claude-sonnet-4-6 (Kosten/Qualität optimal) |
