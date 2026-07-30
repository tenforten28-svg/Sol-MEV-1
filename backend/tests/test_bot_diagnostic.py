"""
Iteration 4 tests — NEW GET /api/bot_diagnostic endpoint + regression on live endpoints.

Default safe env expected in sandbox:
  SIMULATION_MODE=true, LIVE_TRADING_ENABLED unset, SOLANA_PRIVATE_KEY unset.
"""
import time

import pytest
import requests

BASE_URL = ""
with open("/app/frontend/.env") as f:
    for line in f:
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL missing from /app/frontend/.env"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def diag(api):
    r = api.get(f"{BASE_URL}/api/bot_diagnostic", timeout=30)
    assert r.status_code == 200, f"bot_diagnostic status {r.status_code}: {r.text[:300]}"
    return r.json()


# ---------- module: /api/bot_diagnostic — schema ----------

def test_diagnostic_status_200(api):
    r = api.get(f"{BASE_URL}/api/bot_diagnostic", timeout=30)
    assert r.status_code == 200


def test_diagnostic_top_level_keys(diag):
    expected = {
        "generated_at", "verdict_short", "env_vars", "mongo_config",
        "config_mismatch_warning", "activity_last_hour", "trades_last_24h",
        "live_trader_state", "reasons_no_live_trades", "what_to_do_next",
    }
    missing = expected - set(diag.keys())
    assert not missing, f"missing keys: {missing}"


def test_generated_at_is_iso_datetime(diag):
    from datetime import datetime
    dt = datetime.fromisoformat(diag["generated_at"])
    assert dt.tzinfo is not None, "generated_at must be timezone-aware ISO"


def test_env_vars_shape(diag):
    ev = diag["env_vars"]
    for k in ("SIMULATION_MODE", "LIVE_TRADING_ENABLED", "SOLANA_RPC_URL_set", "SOLANA_PRIVATE_KEY_set"):
        assert k in ev, f"env_vars missing {k}"
    assert isinstance(ev["SOLANA_RPC_URL_set"], bool)
    assert isinstance(ev["SOLANA_PRIVATE_KEY_set"], bool)
    assert ev["SOLANA_PRIVATE_KEY_set"] is False, "default env must not have a private key"


def test_mongo_config_shape_and_note(diag):
    mc = diag["mongo_config"]
    assert isinstance(mc.get("simulation_mode"), bool)
    assert isinstance(mc.get("auto_execute"), bool)
    note = mc.get("note") or ""
    low = note.lower()
    assert "mongo" in low and "env" in low, f"note must warn about env-vs-Mongo mismatch: {note}"
    assert "simulation_mode" in low or "sim-bot" in low


def test_config_mismatch_warning_nullable_string(diag):
    v = diag["config_mismatch_warning"]
    assert v is None or isinstance(v, str)


def test_activity_last_hour_shape(diag):
    a = diag["activity_last_hour"]
    assert isinstance(a["opportunities_found"], int)
    assert isinstance(a["opportunities_risk_approved"], int)
    assert a["opportunities_found"] >= 0
    assert a["opportunities_risk_approved"] <= a["opportunities_found"]


def test_trades_last_24h_shape(diag):
    t = diag["trades_last_24h"]
    for k in ("simulation_trades", "live_manual_swap_trades", "live_manual_swap_successful"):
        assert isinstance(t[k], int), f"{k} not int"


def test_live_trader_state_shape(diag):
    s = diag["live_trader_state"]
    assert isinstance(s["ready"], bool)
    assert isinstance(s["wallet_configured"], bool)
    assert s["wallet_pubkey"] is None or isinstance(s["wallet_pubkey"], str)
    assert isinstance(s["risk_snapshot"], dict)
    assert s["wallet_configured"] is False, "default env has no wallet"
    assert s["ready"] is False


# ---------- module: /api/bot_diagnostic — diagnosis content ----------

def test_reasons_contains_all_four_default_items(diag):
    reasons = " || ".join(diag["reasons_no_live_trades"]).lower()
    assert "live_trading_enabled" in reasons
    assert "simulation_mode" in reasons
    assert "solana_private_key" in reasons
    assert "auto-execution" in reasons and "not wired" in reasons, \
        "CRITICAL: must state auto-execution is NOT wired"


def test_verdict_short_says_not_active(diag):
    v = diag["verdict_short"]
    assert isinstance(v, str) and v
    assert "not active" in v.lower(), f"verdict_short must say bot is NOT active: {v}"


def test_no_live_manual_swap_trades_in_default_state(diag):
    assert diag["trades_last_24h"]["live_manual_swap_trades"] == 0
    assert diag["trades_last_24h"]["live_manual_swap_successful"] == 0


def test_sim_trades_present(diag):
    assert diag["trades_last_24h"]["simulation_trades"] > 0, \
        "sim loop should have produced simulated trades in last 24h"


def test_what_to_do_next_is_nonempty_list(diag):
    w = diag["what_to_do_next"]
    assert isinstance(w, list) and len(w) >= 3
    assert all(isinstance(x, str) and x for x in w)


def test_no_mongo_objectid_leak(api):
    raw = api.get(f"{BASE_URL}/api/bot_diagnostic", timeout=30).text
    assert '"_id"' not in raw


def test_diagnostic_is_fast_no_rpc_calls(api):
    """Endpoint must not make Solana RPC calls -> should be fast."""
    timings = []
    for _ in range(3):
        t0 = time.time()
        r = api.get(f"{BASE_URL}/api/bot_diagnostic", timeout=30)
        timings.append(time.time() - t0)
        assert r.status_code == 200
    best = min(timings)
    assert best < 0.5, f"bot_diagnostic too slow ({timings}); may be doing RPC calls"


# ---------- regression: previously tested endpoints ----------

def test_health(api):
    r = api.get(f"{BASE_URL}/api/health", timeout=30)
    assert r.status_code == 200
    assert r.json().get("status") in ("ok", "healthy")


def test_live_status(api):
    r = api.get(f"{BASE_URL}/api/live/status", timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert "ready" in d and "wallet_configured" in d


@pytest.mark.xfail(reason="KNOWN ISSUE (iteration 4): /api/live/balance omits rpc_ok in the "
                          "wallet-not-configured early-return branch -> inconsistent response shape",
                   strict=False)
def test_live_balance_has_rpc_ok(api):
    r = api.get(f"{BASE_URL}/api/live/balance", timeout=45)
    assert r.status_code == 200
    d = r.json()
    assert "rpc_ok" in d, f"balance missing rpc_ok field: {d}"
    assert d.get("wallet_configured") is False


def test_live_rpc_ping(api):
    r = api.get(f"{BASE_URL}/api/live/rpc_ping", timeout=45)
    assert r.status_code == 200
    d = r.json()
    assert "ok" in d and "rpc_reachable" in d


def test_live_trades(api):
    r = api.get(f"{BASE_URL}/api/live/trades", timeout=30)
    assert r.status_code == 200
    d = r.json()
    trades = d if isinstance(d, list) else d.get("trades")
    assert isinstance(trades, list)


def test_live_summary(api):
    r = api.get(f"{BASE_URL}/api/live/summary", timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_test_swap_still_refuses(api):
    r = api.post(f"{BASE_URL}/api/live/test_swap", json={
        "input_symbol": "SOL", "output_symbol": "USDC",
        "amount_usd": 0.30, "dry_run": True,
    }, timeout=45)
    assert r.status_code in (200, 400, 403, 409, 503), r.status_code
    body = r.text.lower()
    assert ("not" in body and ("ready" in body or "enabled" in body or "configured" in body)) \
        or "refus" in body or "disabled" in body, f"test_swap should refuse: {r.text[:300]}"


def test_stats(api):
    r = api.get(f"{BASE_URL}/api/stats", timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
