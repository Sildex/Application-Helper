# Job API Evaluation
**Date:** 2026-05-19

---

## Entscheidung: Bundesagentur für Arbeit API (primär) + Adzuna (fallback)

---

## Kandidaten

### 1. Bundesagentur für Arbeit – Jobsuche API ✅ PRIMÄR
- **Kosten:** Komplett kostenlos, keine Registrierung
- **Abdeckung:** Beste Abdeckung für Deutschland (offiziell)
- **Endpoint:** `https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs`
- **Auth:** Kein API-Key nötig (öffentlich zugänglich)
- **Filter:** Berufsfeld, PLZ/Umkreis, Vollzeit/Teilzeit, Eintrittsdatum
- **Datenqualität:** Hoch – strukturierte, validierte Daten
- **Limit:** Keine bekannte Rate-Limit-Beschränkung für moderaten Einsatz
- **Bewertung:** ⭐⭐⭐⭐⭐ – perfekt für deutschen Markt, komplett kostenlos

### 2. Adzuna API ✅ FALLBACK
- **Kosten:** Kostenlos – 250 calls/Tag (reicht für persönlichen Einsatz)
- **Abdeckung:** Deutschland gut abgedeckt
- **Auth:** API-Key + App-ID (kostenlose Registrierung)
- **Endpoint:** `https://api.adzuna.com/v1/api/jobs/de/search/`
- **Bewertung:** ⭐⭐⭐⭐ – gute Ergänzung, deckt andere Quellen ab

### 3. Arbeitnow API ⚠️ OPTIONAL
- **Kosten:** Kostenlos, kein Key
- **Abdeckung:** Fokus auf Remote & Tech-Jobs (gut für IT)
- **Endpoint:** `https://www.arbeitnow.com/api/job-board-api`
- **Bewertung:** ⭐⭐⭐ – niche, aber kostenlos und einfach

### 4. LinkedIn / Indeed ❌ AUSGESCHLOSSEN
- Kein offizielles API, Scraping verstößt gegen ToS

---

## Implementierungsstrategie

```
Phase MVP: Nur BA API (reicht vollständig für deutschen Markt)
Phase 2:   Adzuna als zweite Quelle hinzufügen
Phase 3:   Arbeitnow für Remote/IT-Jobs
```

Deduplizierung via (title + company + location) Hash.
