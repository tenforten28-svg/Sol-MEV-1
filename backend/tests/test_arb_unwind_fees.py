"""
Iteration 7 tests — live_arb_monitor unwind retry, fee-deducted PnL,
last_decision on not-ready skip, and exclusion of 'live_auto_arb_stuck'
from /api/live/trades + /api/live/summary.

Modules under test:
  * live_arb_monitor._evaluate_pair  (unwind retry, fees_deducted_usd,
    unwind_attempted/unwind_succeeded, jito_tip_lamports, stuck type)
  * live_arb_monitor._scan_once      (last_decision set when trader not ready)
  * GET /api/live/trades, GET /api/live/summary  (stuck records excluded)
"""
import sys
import inspect
import asyncio
from datetime import datetime, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")

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
def mod():
    import live_arb_monitor
    return live_arb_monitor


# =========================================================
# Fakes
# =========================================================
class FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(doc)
        return type("R", (), {"inserted_id": "fake"})()

    async def count_documents(self, q):
        return len(self.docs)

    def find(self, *a, **k):
        raise AssertionError("find() should not be needed in these tests")


class FakeDB:
    def __init__(self):
        self.trades = FakeCollection()
        self.arb_decisions = FakeCollection()


class FakeJupiter:
    def __init__(self, out1, out2):
        self.out1, self.out2 = out1, out2
        self.calls = 0

    async def get_quote(self, in_mint, out_mint, amount, slippage_bps):
        self.calls += 1
        out = self.out1 if self.calls == 1 else self.out2
        return {"outAmount": str(out), "priceImpactPct": "0.001"}


class FakeRisk:
    def __init__(self):
        self.recorded = []

    def can_trade(self, usd):
        return True, "ok"

    def record_trade(self, pnl):
        self.recorded.append(pnl)


class FakeTrader:
    """leg_results: list of dicts returned by successive execute_swap calls."""

    def __init__(self, leg_results, out1, out2, ready=True):
        self.leg_results = list(leg_results)
        self.swap_calls = []
        self.jupiter = FakeJupiter(out1, out2)
        self.risk = FakeRisk()
        self.ready = ready
        self.cfg = type("C", (), {"slippage_bps": 50})()

    async def execute_swap(self, in_mint, out_mint, amount, **kw):
        self.swap_calls.append((in_mint, out_mint, amount))
        if self.leg_results:
            return self.leg_results.pop(0)
        return {"success": False, "error": "no more fake results"}


def _make_monitor(mod, trader, min_profit_bps=1, size=1.0):
    cfg = mod.ArbMonitorConfig()
    cfg.enabled = False
    cfg.min_profit_bps = min_profit_bps
    cfg.trade_size_usd = size
    cfg.pairs = [("USDC", "SOL")]
    m = mod.LiveArbMonitor.__new__(mod.LiveArbMonitor)
    m.cfg = cfg
    m.db = FakeDB()
    m.lt = trader
    m.task = None
    m.running = False
    m.last_scan_at = None
    m.total_scans = 0
    m.total_opps_found = 0
    m.total_fired = 0
    m.total_fired_successful = 0
    m.last_decision = None
    return m


# =========================================================
# 1. Static code inspection
# =========================================================
def test_evaluate_pair_source_contains_unwind_logic(mod):
    src = inspect.getsource(mod.LiveArbMonitor._evaluate_pair)
    low = src.lower()
    assert "unwind" in low, "_evaluate_pair must contain unwind logic"
    assert src.count("execute_swap(") >= 3, \
        f"_evaluate_pair must call execute_swap for leg1, leg2 and unwind retry (found {src.count('execute_swap(')})"
    assert "asyncio.sleep(2)" in src.replace(" ", "") or "sleep(2)" in src, \
        "unwind retry should sleep briefly before retrying"


def test_pnl_formula_subtracts_fees(mod):
    src = inspect.getsource(mod.LiveArbMonitor._evaluate_pair)
    assert "pnl_usd = round(realized_usd - start_usd - fee_usd, 6)" in src, \
        "PnL must subtract fee_usd"
    assert "jito_tip_lamports" in src


def test_scan_once_sets_last_decision_on_not_ready(mod):
    src = inspect.getsource(mod.LiveArbMonitor._scan_once)
    assert "self.last_decision" in src and "not ready" in src


# =========================================================
# 2. _scan_once behaviour when live_trader not ready
# =========================================================
def test_scan_once_populates_last_decision(mod):
    trader = FakeTrader([], 1, 1, ready=False)
    m = _make_monitor(mod, trader)
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(m._scan_once())
    assert m.last_decision is not None, "last_decision must be set when trader not ready"
    assert m.last_decision["verdict"] == "skipped"
    assert "not ready" in m.last_decision["reason"]
    assert m.total_scans == 1
    assert m.last_scan_at is not None
    assert len(m.db.arb_decisions.docs) == 1
    assert len(m.db.trades.docs) == 0, "no trade should be written when trader not ready"


# =========================================================
# 3. Happy-path round trip: fees deducted, unwind not attempted
# =========================================================
def test_successful_round_trip_deducts_fees_and_no_unwind(mod):
    start_base = 1_000_000            # 1 USDC
    mid_out = 6_600_000              # SOL base units (irrelevant to math)
    final_out = 1_020_000            # 1.02 USDC -> +200 bps
    leg1 = {"success": True, "signature": "sig1", "out_amount": mid_out,
            "submission_method": "jito", "jito_tip_lamports": 20_000}
    leg2 = {"success": True, "signature": "sig2", "out_amount": final_out,
            "submission_method": "jito", "jito_tip_lamports": 30_000}
    trader = FakeTrader([leg1, leg2], mid_out, final_out)
    m = _make_monitor(mod, trader)

    loop = asyncio.new_event_loop()
    decision = loop.run_until_complete(m._evaluate_pair("USDC", "SOL"))
    loop.close()

    assert decision["verdict"] == "fired", decision
    assert len(trader.swap_calls) == 2, "no unwind retry expected on success"
    doc = m.db.trades.docs[0]
    assert doc["type"] == "live_auto_arb"
    assert doc["unwind_attempted"] is False
    assert doc["unwind_succeeded"] is False
    assert doc["jito_tip_lamports"] == 50_000
    # fee = (50000 tips + 10000 gas)/1e9 SOL * $150
    expected_fee = round((60_000 / 1_000_000_000) * 150.0, 6)
    assert doc["fees_deducted_usd"] == expected_fee, doc["fees_deducted_usd"]
    assert isinstance(doc["fees_deducted_usd"], float)
    expected_pnl = round(1.02 - 1.0 - expected_fee, 6)
    assert doc["realized_pnl_usd"] == expected_pnl, (doc["realized_pnl_usd"], expected_pnl)
    assert doc["success"] is True
    assert doc["simulation"] is False
    assert trader.risk.recorded == [expected_pnl]
    assert m.total_fired == 1 and m.total_fired_successful == 1
    assert start_base == 1_000_000  # sanity on sizing assumption


# =========================================================
# 4. leg2 fails -> unwind retry succeeds
# =========================================================
def test_leg2_failure_triggers_unwind_retry_success(mod):
    mid_out = 6_600_000
    final_out = 1_020_000
    leg1 = {"success": True, "signature": "sig1", "out_amount": mid_out,
            "jito_tip_lamports": 0, "submission_method": "rpc"}
    leg2_fail = {"success": False, "error": "blockhash expired"}
    unwind_ok = {"success": True, "signature": "sig_unwind", "out_amount": final_out,
                 "jito_tip_lamports": 0, "submission_method": "rpc"}
    trader = FakeTrader([leg1, leg2_fail, unwind_ok], mid_out, final_out)
    m = _make_monitor(mod, trader)

    loop = asyncio.new_event_loop()
    decision = loop.run_until_complete(m._evaluate_pair("USDC", "SOL"))
    loop.close()

    assert len(trader.swap_calls) == 3, f"unwind retry must call execute_swap a 3rd time: {trader.swap_calls}"
    # unwind uses mid -> start with leg1 actual out
    assert trader.swap_calls[2] == trader.swap_calls[1], "unwind must repeat the leg2 direction/amount"
    assert decision["verdict"] == "fired"
    doc = m.db.trades.docs[0]
    assert doc["type"] == "live_auto_arb", "successful unwind should count as a completed round trip"
    assert doc["unwind_attempted"] is True
    assert doc["unwind_succeeded"] is True
    assert doc["leg2"]["signature"] == "sig_unwind"
    assert doc["success"] is True
    expected_fee = round((10_000 / 1_000_000_000) * 150.0, 6)
    assert doc["fees_deducted_usd"] == expected_fee
    assert doc["realized_pnl_usd"] == round(1.02 - 1.0 - expected_fee, 6)


# =========================================================
# 5. leg2 fails and unwind fails -> stuck
# =========================================================
def test_leg2_and_unwind_failure_marks_trade_stuck(mod):
    mid_out = 6_600_000
    final_out = 1_020_000
    leg1 = {"success": True, "signature": "sig1", "out_amount": mid_out,
            "jito_tip_lamports": 5_000}
    fail = {"success": False, "error": "slippage exceeded"}
    trader = FakeTrader([leg1, dict(fail), dict(fail)], mid_out, final_out)
    m = _make_monitor(mod, trader)

    loop = asyncio.new_event_loop()
    decision = loop.run_until_complete(m._evaluate_pair("USDC", "SOL"))
    loop.close()

    assert len(trader.swap_calls) == 3
    doc = m.db.trades.docs[0]
    assert doc["type"] == "live_auto_arb_stuck", doc["type"]
    assert doc["unwind_attempted"] is True
    assert doc["unwind_succeeded"] is False
    assert doc["success"] is False
    assert doc["realized_pnl_usd"] < 0, "stuck trade must show a loss"
    assert doc["fees_deducted_usd"] > 0
    assert doc["jito_tip_lamports"] == 5_000
    assert m.total_fired_successful == 0
    assert decision["verdict"] == "fired"


# =========================================================
# 6. leg1 failure: no unwind, no trade doc
# =========================================================
def test_leg1_failure_records_decision_only(mod):
    trader = FakeTrader([{"success": False, "error": "sim failed"}], 6_600_000, 1_020_000)
    m = _make_monitor(mod, trader)
    loop = asyncio.new_event_loop()
    decision = loop.run_until_complete(m._evaluate_pair("USDC", "SOL"))
    loop.close()
    assert decision["verdict"] == "fired_leg1_failed"
    assert len(trader.swap_calls) == 1, "no unwind when leg1 fails"
    assert len(m.db.trades.docs) == 0


# =========================================================
# 7. API: stuck trades excluded from /api/live/trades & summary
# =========================================================
def test_stuck_trade_excluded_normal_included(api, mongo):
    now = datetime.now(timezone.utc).isoformat()
    stuck = {"type": "live_auto_arb_stuck", "signature": "stuck_sig_x", "amount_usd": 1.0,
             "realized_pnl_usd": -1.0, "success": False, "created_at": now,
             "_test_marker": "TEST_ITER7"}
    normal = {"type": "live_auto_arb", "signature": "normal_sig_y", "amount_usd": 2.0,
              "realized_pnl_usd": 0.01, "success": True, "created_at": now,
              "fees_deducted_usd": 0.0015, "jito_tip_lamports": 40_000,
              "unwind_attempted": False, "unwind_succeeded": False,
              "_test_marker": "TEST_ITER7"}
    mongo.trades.insert_many([dict(stuck), dict(normal)])
    try:
        r = api.get(f"{BASE_URL}/api/live/trades", timeout=30)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert "error" not in body, body.get("error")
        sigs = [t.get("signature") for t in body["trades"]]
        assert "normal_sig_y" in sigs, f"live_auto_arb trade must appear: {sigs}"
        assert "stuck_sig_x" not in sigs, "live_auto_arb_stuck must NOT appear in /api/live/trades"
        seeded = next(t for t in body["trades"] if t.get("signature") == "normal_sig_y")
        assert "_id" not in seeded
        assert seeded["fees_deducted_usd"] == 0.0015

        s = api.get(f"{BASE_URL}/api/live/summary", timeout=60)
        assert s.status_code == 200, s.text[:300]
        today = s.json()["today"]
        assert today["total_trades"] == 1, f"stuck trade must not be aggregated: {today}"
        assert today["total_volume_usd"] == 2.0, today
        assert today["successful_trades"] == 1, today
        assert today.get("total_jito_tips_sol", 0) == pytest.approx(40_000 / 1e9, rel=1e-6), today
    finally:
        mongo.trades.delete_many({"_test_marker": "TEST_ITER7"})
    assert mongo.trades.count_documents({"_test_marker": "TEST_ITER7"}) == 0
    r2 = api.get(f"{BASE_URL}/api/live/trades", timeout=30)
    assert "normal_sig_y" not in [t.get("signature") for t in r2.json()["trades"]]


def test_status_endpoint_still_healthy(api):
    r = api.get(f"{BASE_URL}/api/live/auto_arb/status", timeout=30)
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert "error" not in d
    assert d["enabled"] is False and d["running"] is False
    assert d["last_decision"] is None, "monitor disabled -> no scan -> last_decision null"
