"""
Iteration 6 tests — autonomous live arbitrage monitor.

Modules under test:
  * GET /api/live/auto_arb/status
  * GET /api/live/auto_arb/decisions
  * GET /api/bot_diagnostic (AUTO_ARB_ENABLED reason replaces old 'not wired')
  * GET /api/live/trades + /api/live/summary include type 'live_auto_arb'
  * live_arb_monitor.get_arb_monitor singleton + default-safe config
"""
import sys
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


@pytest.fixture(scope="module")
def arb_status(api):
    r = api.get(f"{BASE_URL}/api/live/auto_arb/status", timeout=30)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    return r.json()


# ---------- module: /api/live/auto_arb/status ----------

def test_status_no_error_key(arb_status):
    assert "error" not in arb_status, f"status returned error: {arb_status.get('error')}"


def test_status_disabled_and_not_running_in_default_env(arb_status):
    assert arb_status["enabled"] is False
    assert arb_status["running"] is False


def test_status_config_shape(arb_status):
    cfg = arb_status["config"]
    assert isinstance(cfg["scan_interval_seconds"], (int, float)) and cfg["scan_interval_seconds"] > 0
    assert isinstance(cfg["trade_size_usd"], (int, float)) and cfg["trade_size_usd"] > 0
    assert cfg["min_profit_bps"] == 30, f"default min_profit_bps must be 30, got {cfg['min_profit_bps']}"
    assert isinstance(cfg["pairs"], list) and cfg["pairs"]
    for p in cfg["pairs"]:
        assert isinstance(p, str)
        parts = p.split("->")
        assert len(parts) == 3 and parts[0] == parts[2], f"bad round-trip label {p}"
    assert "USDC->SOL->USDC" in cfg["pairs"]


def test_status_counters_shape(arb_status):
    c = arb_status["counters"]
    for k in ("total_scans", "opportunities_found", "trades_fired", "trades_fired_successful"):
        assert isinstance(c[k], int), f"{k} must be int"
        assert c[k] == 0, f"{k} must be 0 when monitor disabled, got {c[k]}"
    assert c["last_scan_at"] is None


def test_status_last_decision_and_trader_ready(arb_status):
    assert arb_status["last_decision"] is None
    assert isinstance(arb_status["live_trader_ready"], bool)
    assert arb_status["live_trader_ready"] is False, "default env has no wallet -> not ready"


def test_status_is_idempotent(api, arb_status):
    r = api.get(f"{BASE_URL}/api/live/auto_arb/status", timeout=30)
    assert r.status_code == 200
    assert r.json()["config"] == arb_status["config"]


# ---------- module: /api/live/auto_arb/decisions ----------

def test_decisions_default_empty(api):
    r = api.get(f"{BASE_URL}/api/live/auto_arb/decisions", params={"limit": 20}, timeout=30)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    d = r.json()
    assert "error" not in d, d.get("error")
    assert d["count"] == 0, f"monitor disabled -> no decisions, got {d['count']}"
    assert d["decisions"] == []


def test_decisions_seeded_shape_and_order(api, mongo):
    """Seed 2 decisions, verify newest-first order, required keys and no _id leak."""
    seeded = [
        {"at": "2026-07-01T00:00:00+00:00", "verdict": "skipped",
         "pair": "USDC->SOL->USDC", "reason": "TEST_older", "info": None,
         "_test_marker": "TEST_ARB_DECISION"},
        {"at": "2026-07-02T00:00:00+00:00", "verdict": "blocked_by_risk",
         "pair": "USDC->JUP->USDC", "reason": "TEST_newer", "info": {"profit_bps": 55.0},
         "_test_marker": "TEST_ARB_DECISION"},
    ]
    mongo.arb_decisions.insert_many([dict(s) for s in seeded])
    try:
        r = api.get(f"{BASE_URL}/api/live/auto_arb/decisions", params={"limit": 20}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["count"] == 2, d
        first = d["decisions"][0]
        assert first["reason"] == "TEST_newer", f"must be newest-first: {d['decisions']}"
        for dec in d["decisions"]:
            assert "_id" not in dec, "MongoDB _id leaked into response"
            for k in ("at", "verdict", "pair", "reason", "info"):
                assert k in dec, f"missing key {k}"
            assert dec["verdict"] in ("skipped", "blocked_by_risk", "fired", "fired_leg1_failed")
    finally:
        mongo.arb_decisions.delete_many({"_test_marker": "TEST_ARB_DECISION"})
    assert mongo.arb_decisions.count_documents({"_test_marker": "TEST_ARB_DECISION"}) == 0


def test_decisions_limit_param_respected(api, mongo):
    docs = [{"at": f"2026-07-0{i}T00:00:00+00:00", "verdict": "skipped", "pair": "USDC->SOL->USDC",
             "reason": f"TEST_{i}", "info": None, "_test_marker": "TEST_ARB_DECISION"}
            for i in range(1, 6)]
    mongo.arb_decisions.insert_many(docs)
    try:
        r = api.get(f"{BASE_URL}/api/live/auto_arb/decisions", params={"limit": 2}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["count"] == 2 and len(d["decisions"]) == 2, d
    finally:
        mongo.arb_decisions.delete_many({"_test_marker": "TEST_ARB_DECISION"})


# ---------- module: /api/bot_diagnostic AUTO_ARB_ENABLED reason ----------

def test_diagnostic_has_auto_arb_reason_and_not_old_wording(api):
    r = api.get(f"{BASE_URL}/api/bot_diagnostic", timeout=30)
    assert r.status_code == 200
    reasons = r.json()["reasons_no_live_trades"]
    joined = " || ".join(reasons).lower()
    assert "auto_arb_enabled" in joined, f"missing AUTO_ARB_ENABLED reason: {reasons}"
    assert "monitor is disabled" in joined, f"reason must say monitor is disabled: {reasons}"
    assert "auto-execution is not wired" not in joined, \
        "old 'auto-execution is NOT wired' wording must be replaced"


# ---------- module: /api/live/trades + /api/live/summary with live_auto_arb ----------

def test_auto_arb_trade_appears_in_trades_and_summary(api, mongo):
    marker = "auto_sig_123"
    doc = {
        "type": "live_auto_arb",
        "signature": marker,
        "pair": "USDC->SOL->USDC",
        "amount_usd": 1.0,
        "realized_pnl_usd": 0.003,
        "success": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    mongo.trades.insert_one(dict(doc))
    try:
        r = api.get(f"{BASE_URL}/api/live/trades", timeout=30)
        assert r.status_code == 200
        t = r.json()
        sigs = [x.get("signature") for x in t["trades"]]
        assert marker in sigs, f"seeded live_auto_arb trade missing from /api/live/trades: {t}"
        seeded = next(x for x in t["trades"] if x.get("signature") == marker)
        assert seeded["type"] == "live_auto_arb"
        assert seeded["amount_usd"] == 1.0
        assert seeded["realized_pnl_usd"] == 0.003
        assert "_id" not in seeded

        r2 = api.get(f"{BASE_URL}/api/live/summary", timeout=60)
        assert r2.status_code == 200, r2.text[:300]
        today = r2.json()["today"]
        assert today["total_trades"] == 1, today
        assert today["total_volume_usd"] == 1.0, today
        assert today["successful_trades"] == 1, today
        assert today["success_rate_pct"] == 100.0, today
    finally:
        mongo.trades.delete_many({"signature": marker})
    assert mongo.trades.count_documents({"signature": marker}) == 0
    r3 = api.get(f"{BASE_URL}/api/live/trades", timeout=30)
    assert marker not in [x.get("signature") for x in r3.json()["trades"]]


def test_summary_aggregates_both_live_types(api, mongo):
    docs = [
        {"type": "live_manual_swap", "signature": "TEST_manual_sig", "amount_usd": 2.0,
         "success": True, "created_at": datetime.now(timezone.utc).isoformat()},
        {"type": "live_auto_arb", "signature": "TEST_auto_sig", "amount_usd": 3.0,
         "success": False, "created_at": datetime.now(timezone.utc).isoformat()},
    ]
    mongo.trades.insert_many([dict(d) for d in docs])
    try:
        today = api.get(f"{BASE_URL}/api/live/summary", timeout=60).json()["today"]
        assert today["total_trades"] == 2, today
        assert today["total_volume_usd"] == 5.0, today
        assert today["successful_trades"] == 1, today
    finally:
        mongo.trades.delete_many({"signature": {"$in": ["TEST_manual_sig", "TEST_auto_sig"]}})


# ---------- module: live_arb_monitor singleton + safety ----------

@pytest.fixture(scope="module")
def monitor_module():
    sys.path.insert(0, "/app/backend")
    import live_arb_monitor
    return live_arb_monitor


def test_singleton_requires_db_on_first_call(monitor_module):
    monitor_module._instance = None
    with pytest.raises(RuntimeError):
        monitor_module.get_arb_monitor()


def test_singleton_returns_same_instance(monitor_module):
    monitor_module._instance = None
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    m1 = monitor_module.get_arb_monitor(db)
    m2 = monitor_module.get_arb_monitor()
    assert m1 is m2
    client.close()


def test_config_disabled_in_default_env(monitor_module):
    monitor_module._instance = None
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    m = monitor_module.get_arb_monitor(client[DB_NAME])
    assert m.cfg.enabled is False, "SAFETY: monitor must be disabled when AUTO_ARB_ENABLED unset"
    assert m.running is False
    assert m.task is None
    client.close()


def test_start_is_noop_when_disabled(monitor_module):
    monitor_module._instance = None
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    m = monitor_module.get_arb_monitor(client[DB_NAME])
    m.start()
    assert m.running is False and m.task is None, "SAFETY: start() must not launch loop when disabled"
    assert m.status()["running"] is False
    client.close()


def test_config_parses_env_overrides(monkeypatch, monitor_module):
    monkeypatch.setenv("AUTO_ARB_ENABLED", "true")
    monkeypatch.setenv("AUTO_ARB_MIN_PROFIT_BPS", "77")
    monkeypatch.setenv("AUTO_ARB_TRADE_SIZE_USD", "2.5")
    monkeypatch.setenv("AUTO_ARB_SCAN_INTERVAL", "9")
    cfg = monitor_module.ArbMonitorConfig()
    assert cfg.enabled is True
    assert cfg.min_profit_bps == 77
    assert cfg.trade_size_usd == 2.5
    assert cfg.scan_interval == 9.0


def test_config_bad_env_values_fall_back(monkeypatch, monitor_module):
    monkeypatch.setenv("AUTO_ARB_MIN_PROFIT_BPS", "abc")
    monkeypatch.setenv("AUTO_ARB_TRADE_SIZE_USD", "xyz")
    cfg = monitor_module.ArbMonitorConfig()
    assert cfg.min_profit_bps == 30
    assert cfg.trade_size_usd == 1.0


def test_pairs_whitelisted_in_live_trader(monitor_module):
    from live_trader import MINTS, DECIMALS
    cfg = monitor_module.ArbMonitorConfig()
    for (a, b) in cfg.pairs:
        assert a in MINTS and b in MINTS, f"pair token missing from MINTS: {a}/{b}"
        assert a in DECIMALS and b in DECIMALS, f"pair token missing from DECIMALS: {a}/{b}"
