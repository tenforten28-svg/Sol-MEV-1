"""
Backend tests for LIVE trading endpoints — Iteration 2 focus:
  (a) wallet_configured field on status / balance / summary
  (b) /api/live/trades filter no longer includes sim-bot pollution
  (c) Regression: /api/health, /api/stats, /api/opportunities, /api/trades still work
"""
import os
import asyncio
from datetime import datetime, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

# Resolve BASE_URL from frontend/.env (source of truth)
BASE_URL = ""
with open("/app/frontend/.env") as f:
    for line in f:
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

# Load backend Mongo config for seed insertion (test isolation via TEST_ marker)
MONGO_URL = ""
DB_NAME = ""
with open("/app/backend/.env") as f:
    for line in f:
        line = line.strip()
        if line.startswith("MONGO_URL="):
            MONGO_URL = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("DB_NAME="):
            DB_NAME = line.split("=", 1)[1].strip().strip('"')


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def seeded_trades(event_loop):
    """Insert two trades:
       (a) garbage sim-bot-style record — must NOT be returned by /api/live/trades
       (b) real live_manual_swap record — must be returned
    Cleanup after class."""
    today_iso = datetime.now(timezone.utc).isoformat()
    garbage = {
        "TEST_marker": "iteration_2_garbage",
        "created_at": today_iso,
        "simulation": False,
        "type": "other",
        "signature": None,
        "amount_usd": 0,
        "pair": "SOL/USDC",
    }
    real = {
        "TEST_marker": "iteration_2_real",
        "created_at": today_iso,
        "simulation": False,
        "type": "live_manual_swap",
        "signature": "TESTabc123SIGNATUREvalue",
        "amount_usd": 1.5,
        "success": True,
        "submission_method": "direct_rpc",
        "pair": "SOL/USDC",
    }

    async def _seed():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        await db.trades.insert_one(garbage)
        await db.trades.insert_one(real)
        client.close()

    async def _cleanup():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        await db.trades.delete_many({"TEST_marker": {"$in": ["iteration_2_garbage", "iteration_2_real"]}})
        client.close()

    event_loop.run_until_complete(_seed())
    yield {"garbage": garbage, "real": real}
    event_loop.run_until_complete(_cleanup())


# ---------- Regression: base endpoints ----------

def test_health(api):
    r = api.get(f"{BASE_URL}/api/health", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["db"] is True


def test_stats_regression(api):
    r = api.get(f"{BASE_URL}/api/stats", timeout=15)
    assert r.status_code == 200
    d = r.json()
    for k in ["total_opportunities", "executed_trades", "total_profit", "success_rate", "active_pairs"]:
        assert k in d


def test_opportunities_regression(api):
    r = api.get(f"{BASE_URL}/api/opportunities", timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_trades_regression(api):
    r = api.get(f"{BASE_URL}/api/trades", timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------- (a) wallet_configured on status ----------

def test_live_status_wallet_configured_field(api):
    r = api.get(f"{BASE_URL}/api/live/status", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "wallet_configured" in d, "wallet_configured field missing at top level"
    assert isinstance(d["wallet_configured"], bool)
    # Default env: no private key/RPC
    assert d["wallet_configured"] is False
    assert d["ready"] is False  # independent


# ---------- (a) wallet_configured on balance ----------

def test_live_balance_wallet_not_configured(api):
    r = api.get(f"{BASE_URL}/api/live/balance", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["ready"] is False
    assert d["wallet_configured"] is False
    assert d["sol"] == 0.0
    assert "reason" in d
    assert "SOLANA_PRIVATE_KEY" in d["reason"] or "SOLANA_RPC_URL" in d["reason"]


# ---------- (a) wallet_configured on summary ----------

def test_live_summary_wallet_configured_and_defaults(api, seeded_trades):
    r = api.get(f"{BASE_URL}/api/live/summary", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "wallet_configured" in d
    assert d["wallet_configured"] is False
    assert d["ready"] is False
    assert d["sol_balance"] == 0.0
    # Only the seeded live_manual_swap should count today
    assert d["today"]["total_trades"] == 1, f"expected 1 live trade in today aggregate, got: {d['today']}"
    assert d["today"]["total_volume_usd"] == 1.5
    assert d["today"]["successful_trades"] == 1


# ---------- (b) trades filter — sim-bot garbage excluded ----------

def test_live_trades_filter_excludes_garbage(api, seeded_trades):
    r = api.get(f"{BASE_URL}/api/live/trades?limit=50", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "trades" in d and "count" in d
    # All returned trades must have type=live_manual_swap and non-null signature
    for t in d["trades"]:
        assert t.get("type") == "live_manual_swap", f"garbage type leaked: {t.get('type')}"
        assert t.get("signature") is not None, f"null-signature leaked: {t}"
    # The real seeded record must appear
    sigs = [t.get("signature") for t in d["trades"]]
    assert "TESTabc123SIGNATUREvalue" in sigs, "seeded live_manual_swap not returned"
    # The garbage seeded record must NOT appear (identified by TEST_marker)
    markers = [t.get("TEST_marker") for t in d["trades"]]
    assert "iteration_2_garbage" not in markers, "sim-bot garbage leaked into /api/live/trades"


# ---------- (c) Safety gate unchanged ----------

def test_live_test_swap_still_blocked(api):
    r = api.post(
        f"{BASE_URL}/api/live/test_swap",
        json={"input_symbol": "SOL", "output_symbol": "USDC",
              "amount_usd": 0.5, "dry_run": True},
        timeout=15,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert "live trader not ready" in d["reason"].lower()
