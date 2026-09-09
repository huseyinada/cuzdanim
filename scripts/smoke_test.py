"""End-to-end smoke test against the ASGI app in-process (no server needed).

    python scripts/smoke_test.py

Uses a throwaway SQLite DB and VAPID key file; cleans up after itself.
Exercises: incremental Alembic migration on SQLite (rev1 -> head), static
PWA assets, auth, transactions (incl. timezone normalization), weekly daily
plan with reserved fixed costs, recurring rules (create -> auto-post ->
idempotent re-run -> edit -> delete keeps history), wallet, motivation, push
crypto path, budgets + every scheduler job, backup, analytics, validation.
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

DB_FILE = "_smoke.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///./{DB_FILE}"
os.environ["VAPID_KEYS_FILE"] = "_smoke_vapid.json"
os.environ["ENABLE_SCHEDULER"] = "false"

import base64  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import httpx  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from pywebpush import WebPusher  # noqa: E402


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


BACKUP_DIR = ROOT / "backups"
BACKUPS_BEFORE = set(BACKUP_DIR.glob("finance_*.db")) if BACKUP_DIR.exists() else set()


def _cleanup() -> None:
    for f in (DB_FILE, f"{DB_FILE}-wal", f"{DB_FILE}-shm", "_smoke_vapid.json"):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
    # Remove only the backups this run created; never touch the user's real ones.
    if BACKUP_DIR.exists():
        for p in set(BACKUP_DIR.glob("finance_*.db")) - BACKUPS_BEFORE:
            p.unlink(missing_ok=True)
        if not any(BACKUP_DIR.iterdir()):
            BACKUP_DIR.rmdir()


def prepare_rev1_database() -> None:
    """Create the DB at the *first* revision so app startup must run the
    incremental migration (batch ALTERs on SQLite) to reach head."""
    _cleanup()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "319ece25826e"],
        check=True, env={**os.environ}, capture_output=True, text=True,
    )
    print("db prepared at revision 319ece25826e (app must migrate to head)")


_client_key = ec.generate_private_key(ec.SECP256R1())
FAKE_SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/fake-endpoint-123",
    "keys": {
        "p256dh": _b64url(_client_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
        "auth": _b64url(os.urandom(16)),
    },
}


async def main() -> None:
    from app.main import app
    from app.push import get_vapid_signer, send_web_push
    from app.scheduler import (
        backup_database, check_budget_alerts, generate_monthly_snapshots,
        post_due_recurring, send_daily_motivation,
    )
    from app.timeutils import local_now_naive, local_today

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            # --- migration reached head? -------------------------------------------
            import sqlite3
            con = sqlite3.connect(DB_FILE)
            version = con.execute("select version_num from alembic_version").fetchone()[0]
            cols = {r[1] for r in con.execute("pragma table_info(transactions)")}
            con.close()
            assert version == "a7c41e9b2d30", version
            assert {"source", "recurring_rule_id", "scheduled_for"} <= cols, cols
            print("migration OK -> head", version, "| new transaction columns present")

            # --- PWA assets -----------------------------------------------------------
            for path, needle in [("/", "Cüzdanım"), ("/sw.js", "addEventListener('push'"),
                                 ("/manifest.webmanifest", "short_name"), ("/static/app.js", "cuzdanim_access"),
                                 ("/static/styles.css", "tabbar"), ("/static/icons/icon-192.png", None)]:
                r = await c.get(path)
                assert r.status_code == 200, (path, r.status_code)
                if needle:
                    assert needle in r.text, path
            print("frontend assets OK")

            # --- Auth -------------------------------------------------------------------
            r = await c.post("/api/v1/auth/signup", json={"email": "demo@example.com", "password": "Password123", "full_name": "Huseyin Demo"})
            assert r.status_code == 201, r.text
            r = await c.post("/api/v1/auth/login", data={"username": "demo@example.com", "password": "Password123"})
            assert r.status_code == 200, r.text
            h = {"Authorization": f"Bearer {r.json()['access_token']}"}

            # --- Transactions -------------------------------------------------------------
            today = local_today()
            now = local_now_naive()

            def tx(type_, cat, amount, when=None):
                body = {"type": type_, "category": cat, "amount": str(amount), "payment_method": "cash"}
                if when:
                    body["transaction_date"] = when
                return c.post("/api/v1/transactions", headers=h, json=body)

            r = await tx("income", "salary", 3500, f"{today.isoformat()}T09:00:00")
            assert r.status_code == 201, r.text
            assert r.json()["source"] == "manual"
            r = await tx("expense", "groceries", 200, f"{today.isoformat()}T12:30:00")
            assert r.status_code == 201, r.text
            r = await tx("expense", "transportation", 30, f"{today.isoformat()}T05:00:00Z")
            assert r.status_code == 201, r.text
            assert r.json()["transaction_date"].startswith(f"{today.isoformat()}T08:00:00"), "05:00Z -> 08:00 Istanbul"
            print("transactions OK (timezone normalization verified)")

            # --- Weekly plan ------------------------------------------------------------
            r = await c.put("/api/v1/planning", headers=h, json={"period_type": "weekly", "period": today.isoformat(), "savings_goal": "500", "income_override": "3500"})
            assert r.status_code == 200, r.text
            assert r.json()["period_type"] == "weekly"
            monday = today - timedelta(days=today.weekday())
            assert r.json()["period"] == monday.isoformat(), r.json()

            # --- Recurring rule: lunch every day, time already passed today -> auto-posts ------
            slot_time = (now - timedelta(minutes=2)).time().replace(second=0, microsecond=0)
            rule_body = {"name": "Öğle yemeği", "type": "expense", "category": "food_dining", "amount": "150",
                         "frequency": "daily", "time_of_day": slot_time.strftime("%H:%M"),
                         "start_date": today.isoformat(), "auto_post": True}
            r = await c.post("/api/v1/recurring", headers=h, json=rule_body)
            assert r.status_code == 201, r.text
            rule = r.json()
            assert rule["next_run_at"] is not None
            due_today = datetime.fromisoformat(rule["next_run_at"]) <= now
            print("rule created; next_run_at:", rule["next_run_at"], "| due now:", due_today)

            # a weekly rule (Mon-Fri 09:00) and a monthly rule too — schedule math only
            r = await c.post("/api/v1/recurring", headers=h, json={**rule_body, "name": "Servis", "amount": "40", "frequency": "weekly", "weekdays": [0, 1, 2, 3, 4], "time_of_day": "09:00", "category": "transportation"})
            assert r.status_code == 201, r.text
            weekly_rule = r.json()
            assert all(datetime.fromisoformat(weekly_rule["next_run_at"]).weekday() < 5 for _ in [0])
            r = await c.post("/api/v1/recurring", headers=h, json={**rule_body, "name": "Kira", "amount": "1000", "frequency": "monthly", "day_of_month": 1, "time_of_day": "10:00", "category": "housing", "auto_post": False})
            assert r.status_code == 201, r.text
            # invalid: weekly with no days
            r = await c.post("/api/v1/recurring", headers=h, json={**rule_body, "frequency": "weekly", "weekdays": []})
            assert r.status_code == 422, r.text

            # run the minute job twice -> posts once, never duplicates
            await post_due_recurring()
            r = await c.get("/api/v1/transactions?category=food_dining", headers=h)
            first = r.json()["total"]
            await post_due_recurring()
            r = await c.get("/api/v1/transactions?category=food_dining", headers=h)
            assert r.json()["total"] == first, "second run must not duplicate"
            if due_today:
                assert first >= 1, "due slot should have been auto-posted"
                item = r.json()["items"][0]
                assert item["source"] == "recurring" and item["recurring_rule_id"] == rule["id"], item
                print("auto-post OK:", item["description"], item["amount"], "at", item["transaction_date"], "| idempotent re-run OK")
            else:
                print("(slot crossed midnight edge; auto-post assertion skipped)")

            # daily plan reflects weekly period + reserved fixed costs
            r = await c.get("/api/v1/planning/daily", headers=h)
            assert r.status_code == 200, r.text
            p = r.json()
            assert p["period_type"] == "weekly" and p["days_in_period"] == 7 and len(p["schedule"]) == 7, p["period_type"]
            assert p["chart"]["labels"][0].startswith("Pzt"), p["chart"]["labels"]
            print("weekly plan:", {k: p[k] for k in ["period_label", "spendable_total", "reserved_total", "spent_so_far", "free_remaining", "today_allowance", "remaining_today", "days_remaining", "status"]})
            assert float(p["reserved_total"]) >= 0
            assert abs(float(p["free_remaining"]) - (float(p["remaining_total"]) - float(p["reserved_total"]))) < 0.011

            # switch back to monthly view on demand
            r = await c.get("/api/v1/planning/daily?period_type=monthly", headers=h)
            assert r.status_code == 200 and r.json()["period_type"] == "monthly" and len(r.json()["schedule"]) >= 28

            # --- Wallet ---------------------------------------------------------------------
            r = await c.get("/api/v1/wallet", headers=h)
            assert r.status_code == 200, r.text
            w = r.json()
            # Balance must equal the signed sum of every posted row (manual + auto-posted,
            # including any weekly-rule slot that was already due today).
            r = await c.get("/api/v1/transactions?page_size=200", headers=h)
            rows = r.json()["items"]
            expected_balance = sum(float(t["amount"]) * (1 if t["type"] == "income" else -1) for t in rows)
            assert abs(float(w["balance_total"]) - expected_balance) < 0.011, (w["balance_total"], expected_balance)
            auto_rows = [t for t in rows if t["source"] == "recurring"]
            print(f"auto-posted rows so far: {len(auto_rows)} ->", [(t['description'], t['amount']) for t in auto_rows])
            print("wallet:", {k: w[k] for k in ["balance_total", "period_remaining", "reserved_upcoming", "free_remaining", "auto_posted_today"]}, "| upcoming:", len(w["upcoming"]))

            # post-now, then edit (time change -> next_run in future), then delete keeps history
            r = await c.post(f"/api/v1/recurring/{rule['id']}/post-now", headers=h)
            assert r.status_code == 201 and r.json()["source"] == "recurring", r.text
            r = await c.patch(f"/api/v1/recurring/{rule['id']}", headers=h, json={"time_of_day": "23:59", "amount": "175"})
            assert r.status_code == 200, r.text
            assert datetime.fromisoformat(r.json()["next_run_at"]) > now and r.json()["amount"] == "175.00"
            r = await c.get("/api/v1/recurring/upcoming?days=7", headers=h)
            assert r.status_code == 200 and len(r.json()) >= 5, len(r.json())
            r = await c.delete(f"/api/v1/recurring/{rule['id']}", headers=h)
            assert r.status_code == 204
            r = await c.get("/api/v1/transactions?category=food_dining", headers=h)
            kept = r.json()["items"]
            assert len(kept) == first + 1 and all(t["source"] == "recurring" and t["recurring_rule_id"] is None for t in kept), kept
            print("post-now / edit / delete-keeps-history OK (rule id was nulled -> FK ON DELETE SET NULL is enforced on the app's connections)")

            # --- Motivation ------------------------------------------------------------------
            r = await c.get("/api/v1/motivation/today", headers=h)
            assert r.status_code == 200, r.text
            m = r.json()
            print("MOTIVATION:", m["title"], "|", m["body"], "|", m["quote"])
            assert "Hafta" in m["body"] or "hafta" in m["body"], m["body"]

            # --- Push crypto path ---------------------------------------------------------------
            headers = get_vapid_signer().sign({"sub": "mailto:test@example.com", "aud": "https://fcm.googleapis.com"})
            assert headers.get("Authorization", "").startswith("vapid "), headers
            assert "body" in WebPusher(FAKE_SUBSCRIPTION).encode("merhaba")
            ok, stale, status_code = send_web_push(endpoint=FAKE_SUBSCRIPTION["endpoint"], p256dh=FAKE_SUBSCRIPTION["keys"]["p256dh"], auth=FAKE_SUBSCRIPTION["keys"]["auth"], payload={"title": "t", "body": "b"})
            print("push: signing OK, encryption OK, fake endpoint ->", f"ok={ok} stale={stale} http={status_code}")
            r = await c.post("/api/v1/push/subscribe", headers=h, json=FAKE_SUBSCRIPTION)
            assert r.status_code == 201, r.text

            # --- Budgets + remaining jobs ----------------------------------------------------------
            r = await c.post("/api/v1/budgets", headers=h, json={"category": "groceries", "monthly_limit": "220", "period": today.isoformat()})
            assert r.status_code == 201, r.text
            await check_budget_alerts()
            await send_daily_motivation()
            await generate_monthly_snapshots()
            r = await c.get("/api/v1/alerts", headers=h)
            assert r.status_code == 200 and len(r.json()) == 1, r.text
            print("ALERT:", r.json()[0]["message"])

            # --- Backup ---------------------------------------------------------------------------
            r = await c.post("/api/v1/system/backup", headers=h)
            assert r.status_code == 200, r.text
            backup_path = Path(r.json()["path"])
            assert backup_path.exists() and backup_path.stat().st_size > 0
            con = sqlite3.connect(str(backup_path))
            n_users = con.execute("select count(*) from users").fetchone()[0]
            con.close()
            assert n_users == 1
            r = await c.get("/api/v1/system/backups", headers=h)
            assert r.status_code == 200 and any(Path(b["path"]) == backup_path for b in r.json())
            await backup_database()  # scheduler job path (same second as the manual one -> unique names)
            r = await c.get("/api/v1/system/backups", headers=h)
            assert len(r.json()) - len(BACKUPS_BEFORE) == 2, [b["path"] for b in r.json()]
            print("backup OK:", backup_path.name, backup_path.stat().st_size, "bytes (restorable: users =", n_users, ") | 2 backups in the same second got distinct names")

            # --- Analytics / health / validation ---------------------------------------------------
            r = await c.get("/api/v1/analytics/summary", headers=h)
            assert r.status_code == 200, r.text
            r = await c.get("/api/v1/analytics/trend?months=3", headers=h)
            assert r.status_code == 200
            r = await c.get("/health")
            assert {j["id"] for j in r.json()["jobs"]} >= {"post_due_recurring", "backup_database", "send_daily_motivation"}
            print("health:", r.json()["status"], "| jobs:", [j["id"] for j in r.json()["jobs"]])
            r = await c.post("/api/v1/auth/signup", json={"email": "x@y.com", "password": "short"})
            assert r.status_code == 422
            print("422 detail:", r.json()["detail"])

    print("\nALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    prepare_rev1_database()
    try:
        asyncio.run(main())
    finally:
        _cleanup()
