"""
Backend tests for the new LIVE trading endpoints and safety gates.
Verifies:
  - GET  /api/live/status
  - GET  /api/live/summary
  - GET  /api/live/trades
  - GET  /api/live/balance
  - POST /api/live/test_swap (safety gate)
  - GET  /api/health
  - GET  /api/stats (regression: not broken by new additions)

Default env: SIMULATION_MODE=true, LIVE_TRADING_ENABLED=false
so live trader must NOT be ready and test_swap must refuse.
"""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
if not BASE_URL:
    # frontend/.env is source of truth per system prompt
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- Health & simulation stats regression ----------

def test_health(api):
    r = api.get(f"{BASE_URL}/api/health", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["db"] is True
    assert str(d["simulation_mode"]).lower() == "true"


def test_stats_still_works(api):
    r = api.get(f"{BASE_URL}/api/stats", timeout=15)
    assert r.status_code == 200
    d = r.json()
    for k in ["total_opportunities", "executed_trades", "total_profit", "success_rate", "active_pairs"]:
        assert k in d, f"missing key {k}"


# ---------- Live status ----------

def test_live_status_shape_and_defaults(api):
    r = api.get(f"{BASE_URL}/api/live/status", timeout=15)
    assert r.status_code == 200
    d = r.json()
    # Top-level keys
    for k in ["ready", "simulation_mode", "live_enabled", "has_rpc_url",
              "has_private_key", "wallet_pubkey", "limits", "jito",
              "whitelisted_pairs", "risk"]:
        assert k in d, f"missing top-level key: {k}"
    # Default env expectations
    assert d["ready"] is False
    assert d["simulation_mode"] is True
    # limits sub-keys
    for k in ["max_trade_usd", "min_reserve_sol", "daily_loss_limit_usd",
              "max_losing_streak", "cooldown_seconds", "slippage_bps",
              "profit_threshold_bps"]:
        assert k in d["limits"], f"missing limits key: {k}"
    # jito sub-keys
    for k in ["enabled", "block_engine_url", "tip_lamports", "tip_sol", "max_tip_lamports"]:
        assert k in d["jito"], f"missing jito key: {k}"
    assert isinstance(d["whitelisted_pairs"], list)


# ---------- Live summary ----------

def test_live_summary_defaults(api):
    r = api.get(f"{BASE_URL}/api/live/summary", timeout=15)
    assert r.status_code == 200
    d = r.json()
    for k in ["ready", "wallet", "sol_balance", "sol_balance_usd_estimate",
              "meets_min_reserve", "today", "risk", "limits", "jito_enabled"]:
        assert k in d, f"missing summary key {k}"
    assert d["ready"] is False
    for k in ["date_utc", "total_trades", "successful_trades",
              "success_rate_pct", "total_volume_usd", "total_jito_tips_sol"]:
        assert k in d["today"], f"missing today.{k}"
    assert d["today"]["total_trades"] == 0


# ---------- Live trades ----------

def test_live_trades_empty(api):
    r = api.get(f"{BASE_URL}/api/live/trades", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "count" in d and "trades" in d
    assert d["count"] == 0
    assert d["trades"] == []


# ---------- Live balance ----------

def test_live_balance_not_configured(api):
    r = api.get(f"{BASE_URL}/api/live/balance", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["ready"] is False
    assert d["sol"] == 0.0


# ---------- Safety gate: test_swap ----------

def test_live_test_swap_safety_gate_dry_run(api):
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


def test_live_test_swap_safety_gate_wet_run(api):
    """CRITICAL: even if dry_run=false, must refuse when trader not configured."""
    r = api.post(
        f"{BASE_URL}/api/live/test_swap",
        json={"input_symbol": "SOL", "output_symbol": "USDC",
              "amount_usd": 0.5, "dry_run": False},
        timeout=15,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False, f"UNSAFE: gate did not block real trade: {d}"
    assert "live trader not ready" in d["reason"].lower()
