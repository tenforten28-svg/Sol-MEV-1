"""
Iteration 5 tests — verify iteration-4 fixes in /api/bot_diagnostic and /api/live/balance.

1. HIGH: 'auto-execution is NOT wired' reason must ALWAYS be present, even when a
   live_manual_swap trade exists in the last 24h (seeded into Mongo, then cleaned).
2. mongo_config.auto_execute=true -> dedicated NOTE reason present; toggling it false
   removes the note (config restored afterwards).
3. MINOR: /api/live/balance unconfigured branch must include rpc_ok:false + meets_reserve:false.
"""
import time
from datetime import datetime, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

be_env = dotenv_values("/app/backend/.env")
fe_env = dotenv_values("/app/frontend/.env")
BASE_URL = (fe_env.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
MONGO_URL = be_env.get("MONGO_URL")
DB_NAME = be_env.get("DB_NAME")
assert BASE_URL, "REACT_APP_BACKEND_URL missing from /app/frontend/.env"
assert MONGO_URL and DB_NAME, "MONGO_URL/DB_NAME missing from /app/backend/.env"

AUTO_EXEC_MARKERS = ("auto-execution", "not wired")
AUTO_EXEC_NOTE_MARKERS = ("auto_execute=true", "simulated")


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def _reasons(api):
    r = api.get(f"{BASE_URL}/api/bot_diagnostic", timeout=30)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    return r.json()


def _has_auto_exec(reasons):
    return any(all(m in x.lower() for m in AUTO_EXEC_MARKERS) for x in reasons)


def _has_auto_exec_note(reasons):
    return any(all(m in x.lower() for m in AUTO_EXEC_NOTE_MARKERS) for x in reasons)


# ---------- HIGH fix: unconditional auto-exec message ----------

def test_auto_exec_message_present_default_state(api):
    d = _reasons(api)
    assert d["trades_last_24h"]["live_manual_swap_trades"] == 0
    assert _has_auto_exec(d["reasons_no_live_trades"]), d["reasons_no_live_trades"]


def test_auto_exec_message_present_with_seeded_live_trade(api, mongo):
    doc = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pair": "TEST_SOL/USDC",
        "type": "live_manual_swap",
        "amount_usd": 0.3,
        "signature": "TEST_SIG_ITER5",
        "success": True,
        "_test_marker": "TEST_iteration5",
    }
    res = mongo.trades.insert_one(doc)
    try:
        d = _reasons(api)
        assert d["trades_last_24h"]["live_manual_swap_trades"] >= 1, \
            "seeded live_manual_swap trade not counted"
        assert d["trades_last_24h"]["live_manual_swap_successful"] >= 1
        reasons = d["reasons_no_live_trades"]
        assert _has_auto_exec(reasons), \
            f"REGRESSION: auto-exec message missing when live trade exists: {reasons}"
        assert len(reasons) >= 5, reasons
    finally:
        mongo.trades.delete_one({"_id": res.inserted_id})
        assert mongo.trades.count_documents({"_test_marker": "TEST_iteration5"}) == 0


# ---------- auto_execute note ----------

def test_auto_execute_note_present_when_true(api, mongo):
    cfg = mongo.config.find_one({})
    if not cfg or not cfg.get("auto_execute"):
        pytest.skip("mongo config auto_execute is not true in this environment")
    d = _reasons(api)
    assert d["mongo_config"]["auto_execute"] is True
    assert _has_auto_exec_note(d["reasons_no_live_trades"]), d["reasons_no_live_trades"]


def test_auto_execute_note_absent_when_toggled_false(api, mongo):
    cfg = mongo.config.find_one({})
    if not cfg:
        pytest.skip("no mongo config doc")
    original = cfg.get("auto_execute")
    mongo.config.update_one({"_id": cfg["_id"]}, {"$set": {"auto_execute": False}})
    try:
        d = _reasons(api)
        assert d["mongo_config"]["auto_execute"] is False
        reasons = d["reasons_no_live_trades"]
        assert not _has_auto_exec_note(reasons), f"note should disappear: {reasons}"
        # auto-exec 'not wired' message must still be there
        assert _has_auto_exec(reasons), reasons
    finally:
        mongo.config.update_one({"_id": cfg["_id"]}, {"$set": {"auto_execute": original}})
        assert mongo.config.find_one({"_id": cfg["_id"]}).get("auto_execute") == original


# ---------- MINOR fix: /api/live/balance shape ----------

def test_live_balance_unconfigured_shape(api):
    r = api.get(f"{BASE_URL}/api/live/balance", timeout=45)
    assert r.status_code == 200
    d = r.json()
    assert d.get("wallet_configured") is False, d
    assert d.get("ready") is False
    assert d.get("rpc_ok") is False, f"rpc_ok missing/incorrect: {d}"
    assert d.get("meets_reserve") is False, f"meets_reserve missing/incorrect: {d}"
    assert d.get("sol") == 0.0
    assert isinstance(d.get("reason"), str) and d["reason"]


# ---------- regression: latency (no RPC) ----------

def test_bot_diagnostic_still_fast(api):
    timings = []
    for _ in range(3):
        t0 = time.time()
        r = api.get(f"{BASE_URL}/api/bot_diagnostic", timeout=30)
        timings.append(time.time() - t0)
        assert r.status_code == 200
    assert min(timings) < 0.5, f"too slow: {timings}"
