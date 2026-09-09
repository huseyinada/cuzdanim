# Cüzdanım — Personal Finance Tracker (API + PWA)

> 🇹🇷 Türkçe kurulum ve **telefona yükleme** rehberi: **[KURULUM_REHBERI.md](KURULUM_REHBERI.md)**
> Hızlı başlangıç: `basla.bat` dosyasına çift tıkla → http://localhost:8000

A production-grade personal finance backend (**FastAPI**, **SQLAlchemy 2.0 async**,
**Alembic**, **JWT**, **APScheduler**, **Web Push**) with a mobile-first Turkish
**PWA frontend** that installs on Android like a native app and receives a daily
motivational push notification with the day's spending allowance.

## Features

| Area | What you get |
|---|---|
| Auth | Signup / OAuth2 login / typed access + refresh JWTs |
| Transactions | CRUD, filters, pagination; category↔type consistency enforced; local-timezone dates |
| Budgets | Monthly caps per expense category, `/budgets/status` with 80 % threshold flags |
| **Daily plan** | Adaptive daily allowance over a **monthly or weekly** pay period, fixed costs reserved up front, day-by-day schedule, chart-ready |
| **Recurring rules** | "Lunch 150 ₺ every day 12:30" — daily / selected weekdays / monthly, auto-posted as real transactions (idempotent), 7-day catch-up, delete keeps history |
| **Wallet** | All-time balance, period remaining, reserved vs. free money, today's upcoming deductions, "post now" |
| **Motivation** | Personalized Turkish daily message (yesterday's verdict + today's free allowance + quote) |
| **Push** | VAPID Web Push to every subscribed device; stale subscriptions auto-pruned; push on auto-deductions |
| Analytics | Monthly summary, category breakdown %, 6-month trend as `{labels, datasets}` |
| Jobs | every minute: post due recurring · 08:00 motivation · 20:00 budget check · 03:30 SQLite backup · monthly snapshot on the 1st |
| DB robustness | Alembic runs at startup (legacy DBs auto-stamped), SQLite FK enforcement + WAL, UNIQUE (rule, slot) idempotency, FK SET NULL provenance, `VACUUM INTO` backups (keep 14) |
| PWA | Offline app shell, installable, notification click deep-links (`/#today`, `/#plan`) |

## Architecture

```
routers/        HTTP layer (thin)           app/static/      PWA: index.html, app.js, styles.css,
services.py     business logic                               sw.js, manifest.webmanifest, icons/
repositories.py all SQLAlchemy queries      scheduler.py     APScheduler jobs (lifespan-managed)
models.py       ORM entities                push.py          VAPID keys + Web Push send
schemas.py      Pydantic v2 contracts       motivation_texts.py  Turkish copy
timeutils.py    "today" in Europe/Istanbul  tools/           vapid key printer, icon generator
alembic/        migrations (initial schema included, Postgres-safe enums)
```

## Run locally

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Or just double-click **`basla.bat`** (creates venv, installs, starts with `--reload`, opens browser,
prints the LAN URL for your phone). Opening the workspace in VS Code runs `kur.ps1` automatically and
activates the venv in every terminal (`.vscode/`).

**Windows EXE (no Python needed):** `derle.bat` → `dist\Cüzdanım.exe` (PyInstaller one-file,
recipe in `cuzdanim.spec`, entry point `run_desktop.py`). Data lives next to the exe.
Set `CUZDANIM_NO_BROWSER=1` to suppress the browser launch (autostart/headless).

- App: http://localhost:8000 · Swagger: http://localhost:8000/docs · Health: `/health`
- SQLite tables are auto-created on startup for local use. Postgres uses Alembic:
  `alembic upgrade head` (the Docker image runs this on boot).

## Tests

```bash
python scripts/smoke_test.py
```
End-to-end against the in-process ASGI app: assets, auth, transactions (incl. timezone
normalization), plan math, motivation idempotency, push subscribe/send path, budgets,
all three scheduler jobs, analytics, validation error shape.

## Deploy (free HTTPS — needed for push + install on phones)

`Dockerfile` + `render.yaml` are ready. Steps (Neon Postgres + Render) are in
[KURULUM_REHBERI.md §3](KURULUM_REHBERI.md). Key env vars:

| Var | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host/db?ssl=require` |
| `SECRET_KEY` | JWT signing key |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | `python -m app.tools.vapid` prints them |
| `SCHEDULER_TIMEZONE` | default `Europe/Istanbul` |
| `DAILY_MESSAGE_HOUR`, `BUDGET_CHECK_HOUR` | job times (local tz) |

## Design notes

- Money is `Decimal` / `Numeric(12,2)` everywhere — never float.
- `transaction_date` is stored as **naive local wall-clock time** in the app timezone so
  "today's spend" matches the user's calendar day even on a UTC server (`timeutils.py`).
- All jobs are idempotent (upserts keyed by user/period), so restarts never duplicate
  alerts, messages or snapshots.
- User-facing strings (API errors, messages, UI) are Turkish; code and logs are English.
