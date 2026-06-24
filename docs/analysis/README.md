# Codebase Analysis — Veent Event Scraper

> Generated: 2026-06-24 · Scope: full repo audit across backend (Django/Python) and frontend (SvelteKit/TypeScript)

## Table of Contents

| Document | What it covers |
|---|---|
| [SECURITY.md](SECURITY.md) | Security vulnerabilities (critical first) |
| [BUGS.md](BUGS.md) | Correctness bugs and logic errors |
| [PERFORMANCE.md](PERFORMANCE.md) | N+1 queries, O(n) scans, unbounded queries |
| [TECHNICAL-DEBT.md](TECHNICAL-DEBT.md) | Code quality, maintainability, architecture |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design overview and cross-cutting concerns |

---

## Severity Legend

| Label | Meaning |
|---|---|
| **CRITICAL** | Data loss, security breach, crash in production |
| **HIGH** | Significant correctness or security risk |
| **MEDIUM** | Correctness risk under load or specific conditions |
| **LOW** | Improvement with no immediate risk |
| **INFO** | Observation; no action required |

---

## Quick Summary

### By Severity

| Severity | Security | Bugs | Performance | Tech Debt |
|---|---|---|---|---|
| CRITICAL | 1 | 1 | — | — |
| HIGH | 4 | 3 | 2 | 3 |
| MEDIUM | 2 | 5 | 3 | 8 |
| LOW | — | 3 | 2 | 6 |

### Top 5 Issues to Fix Now

1. **[SEC-1] Hardcoded `SECRET_KEY`** — exposed in git history, invalid in production
2. **[SEC-2] All action API endpoints unauthenticated** — any anonymous user can trigger scrapers, cancel runs, delete queries, run scripts
3. **[BUG-1] `_resolve_organizer` full-table scan** — O(n) scan on every `save_events` call; will degrade as organizer count grows
4. **[BUG-3] `_unique_slug` TOCTOU race** — concurrent saves can throw unhandled `IntegrityError`
5. **[PERF-2] `api_events_by_category` Python-side aggregation** — loads every event's `agent_categories` JSON into memory for counting

---

## Codebase Overview

```
veent-event-scraper/          monorepo (pnpm + Turborepo)
├── apps/
│   ├── backend/               Django 6.0 + Python
│   │   ├── config/            settings, urls, wsgi, asgi
│   │   └── events/            single Django app
│   │       ├── models.py          Event, Venue, Organizer, ScraperRun, SearchQuery, TrackerNote
│   │       ├── views.py           30+ view functions (HTML + JSON API + webhooks)
│   │       ├── urls.py            URL routing
│   │       ├── runner.py          subprocess-based scraper orchestrator
│   │       ├── ai_categories.py   Claude CLI categorization
│   │       ├── registration_patterns.py  URL-based registration link detection
│   │       ├── scrapers/
│   │       │   ├── base.py        BaseScraper, dataclasses, save_*/dedup helpers (557 lines)
│   │       │   ├── proxy_manager.py    free rotating proxy election
│   │       │   ├── social_proxy.py     DataImpulse residential proxy
│   │       │   ├── facebook_events.py  Playwright-based Facebook scraper (1267 lines)
│   │       │   └── 20+ individual scrapers
│   │       ├── management/commands/
│   │       │   └── run_scraper_job.py  worker subprocess entrypoint
│   │       └── tests.py           1927-line monolithic test file
│   └── frontend/              SvelteKit + TypeScript
│       └── src/
│           ├── lib/api.ts         typed fetch client for Django JSON API
│           ├── lib/types.ts       TypeScript types mirroring Django API shapes
│           └── routes/            page components
├── docs/                      existing docs (deduplication, n8n)
└── process/                   RIPER-5 workflow plans + context
```

**Key tech:**
- Django 6.0 / Python / SQLite (dev) / PostgreSQL (prod via dj_database_url)
- Playwright (synchronous API) for headless browser scraping
- DataImpulse residential proxies + free public proxy list fallback
- Claude CLI (Haiku) for AI event categorization
- SvelteKit frontend communicates via Vite dev-proxy → Django JSON API
- Turbo + pnpm monorepo
