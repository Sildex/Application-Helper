# Data Model
**Project:** AutoApply  
**Version:** 0.1  
**Date:** 2026-05-19

---

## Entity-Relationship-Übersicht

```
┌─────────────┐       ┌─────────────────┐       ┌──────────────┐
│    jobs     │──1:1──│  cover_letters  │       │    config    │
│             │       └─────────────────┘       │  (1 Zeile)   │
│             │──1:1──┌─────────────────┐       └──────────────┘
│             │       │  applications   │
└─────────────┘       └─────────────────┘
```

---

## Tabellen

### jobs
| Feld | Typ | Beschreibung |
|---|---|---|
| id | INTEGER PK | Auto-Increment |
| external_id | TEXT UNIQUE | ID aus Quell-API (Deduplizierung) |
| source | TEXT | `"ba"` \| `"adzuna"` |
| title | TEXT | Stellentitel |
| company | TEXT | Unternehmen |
| location | TEXT | Standort |
| description | TEXT | Vollständige Stellenbeschreibung |
| url | TEXT | Link zur Original-Anzeige |
| category | TEXT | `"it"` \| `"wirtschaft"` \| `"unknown"` |
| relevance_score | INTEGER | 0–100, NULL bis bewertet |
| relevance_reason | TEXT | KI-Begründung (1–2 Sätze) |
| posted_at | DATETIME | Veröffentlichungsdatum (aus API) |
| fetched_at | DATETIME | Zeitpunkt des Abrufs |

### applications
| Feld | Typ | Beschreibung |
|---|---|---|
| id | INTEGER PK | Auto-Increment |
| job_id | INTEGER FK | → jobs.id |
| status | TEXT | `"new"` \| `"prepared"` \| `"applied"` \| `"rejected"` \| `"interview"` |
| notes | TEXT | Optionale Notizen |
| created_at | DATETIME | Erstellzeitpunkt |
| applied_at | DATETIME | Zeitpunkt der Bewerbung (NULL bis versendet) |

### cover_letters
| Feld | Typ | Beschreibung |
|---|---|---|
| id | INTEGER PK | Auto-Increment |
| job_id | INTEGER FK UNIQUE | → jobs.id (1 Brief pro Stelle) |
| content | TEXT | Anschreiben-Text |
| is_edited | BOOLEAN | Wurde vom User bearbeitet? |
| generated_at | DATETIME | Zeitpunkt der KI-Generierung |
| edited_at | DATETIME | Letzter Bearbeitungszeitpunkt (NULL wenn unbearbeitet) |

### config
| Feld | Typ | Beschreibung |
|---|---|---|
| id | INTEGER PK | Immer 1 (Singleton) |
| profile_json | TEXT | User-Profil als JSON |
| preferences_json | TEXT | Suchpräferenzen als JSON |

---

## Status-Übergänge (applications.status)

```
new → prepared → applied → interview
               ↘ rejected
```
