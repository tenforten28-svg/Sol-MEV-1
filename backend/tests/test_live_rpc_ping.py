"""
Iteration 3 tests — diagnostic /api/live/rpc_ping endpoint and enhanced /api/live/balance.

Env in Emergent sandbox:
  SOLANA_RPC_URL = https://api.mainnet-beta.solana.com  (set, reachable)
  SOLANA_PRIVATE_KEY = ""                                (unset)

So rpc_ping should succeed with a real slot; balance should say wallet_configured=false.
"""
import os
import pytest
import requests

BASE_URL = ""
with open("/app/frontend/.env") as f:
    for line in f:
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- /api/live/rpc_ping ----------

def test_rpc_ping_returns_200(api):
    r = api.get(f"{BASE_URL}/api/live/rpc_ping", timeout=30)
    assert r.status_code == 200


def test_rpc_ping_success_shape(api):
    """When SOLANA_RPC_URL is set (public mainnet), rpc_ping must return ok=true
    with a large positive current_slot proving the real RPC call worked."""
    r = api.get(f"{BASE_URL}/api/live/rpc_ping", timeout=30)
    d = r.json()
    assert d.get("ok") is True, f"rpc_ping failed: {d}"
    assert d.get("rpc_reachable") is True
    assert "current_slot" in d
    slot = d["current_slot"]
    assert isinstance(slot, int), f"current_slot must be int, got {type(slot).__name__}"
    # Solana mainnet slot as of Jan 2026 is well above 300M
    assert slot > 300_000_000, f"current_slot suspiciously low ({slot}); RPC likely not really called"
    # solana_core version string (e.g. "1.18.22")
    assert "solana_core" in d
    assert d["solana_core"] is None or isinstance(d["solana_core"], str)
    assert "rpc_host" in d
    assert "credits_used_by_this_call" in d


# ---------- /api/live/balance (enhanced) ----------

def test_balance_wallet_not_configured_returns_reason(api):
    """SOLANA_PRIVATE_KEY is empty in default env — must report wallet_configured=false."""
    r = api.get(f"{BASE_URL}/api/live/balance", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["wallet_configured"] is False
    assert d["ready"] is False
    assert d["sol"] == 0.0
    assert "reason" in d
    assert "SOLANA_PRIVATE_KEY" in d["reason"] or "SOLANA_RPC_URL" in d["reason"]


# ---------- Regressions ----------

def test_live_status_regression_fields(api):
    r = api.get(f"{BASE_URL}/api/live/status", timeout=15)
    assert r.status_code == 200
    d = r.json()
    for k in ["ready", "wallet_configured", "simulation_mode", "live_enabled",
              "has_rpc_url", "has_private_key", "wallet_pubkey",
              "limits", "jito", "whitelisted_pairs", "risk"]:
        assert k in d, f"missing key {k} in /api/live/status"
    assert d["has_rpc_url"] is True     # sandbox has public mainnet URL
    assert d["has_private_key"] is False
    assert d["wallet_configured"] is False


def test_live_summary_still_works(api):
    r = api.get(f"{BASE_URL}/api/live/summary", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "wallet_configured" in d
    assert "sol_balance" in d
    assert "today" in d
    assert "risk" in d


def test_live_trades_filter_regression(api):
    r = api.get(f"{BASE_URL}/api/live/trades?limit=25", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "count" in d
    assert "trades" in d
    for t in d["trades"]:
        assert t.get("type") == "live_manual_swap"
        assert t.get("signature") is not None


def test_test_swap_still_blocked_default_env(api):
    r = api.post(
        f"{BASE_URL}/api/live/test_swap",
        json={"input_symbol": "SOL", "output_symbol": "USDC",
              "amount_usd": 0.5, "dry_run": True},
        timeout=15,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False
    assert "not ready" in d["reason"].lower()


# ---------- Method-level check for exception non-swallow ----------

def test_rpc_ping_reports_error_on_bad_url(monkeypatch):
    """If we point the trader at an unreachable RPC, rpc_ping must return
    ok=false, rpc_reachable=false, and an `error` field (NOT silently succeed)."""
    import sys
    sys.path.insert(0, "/app/backend")
    from live_trader import LiveTrader, LiveTraderConfig
    import asyncio

    cfg = LiveTraderConfig()
    cfg.rpc_url = "https://this-host-does-not-exist-xyz.invalid/"
    trader = LiveTrader.__new__(LiveTrader)  # bypass __init__ side effects
    trader.cfg = cfg
    trader.wallet = None
    trader.wallet_pubkey = None

    result = asyncio.get_event_loop().run_until_complete(trader.rpc_ping())
    assert result["ok"] is False
    assert result["rpc_reachable"] is False
    assert "error" in result  # key must be present (may be empty string on DNS errors)


def test_rpc_ping_reports_reason_when_rpc_url_unset():
    """Empty SOLANA_RPC_URL must yield ok=false with reason 'SOLANA_RPC_URL not set'."""
    import sys
    sys.path.insert(0, "/app/backend")
    from live_trader import LiveTrader, LiveTraderConfig
    import asyncio

    cfg = LiveTraderConfig()
    cfg.rpc_url = ""
    trader = LiveTrader.__new__(LiveTrader)
    trader.cfg = cfg
    trader.wallet = None
    trader.wallet_pubkey = None

    result = asyncio.get_event_loop().run_until_complete(trader.rpc_ping())
    assert result["ok"] is False
    assert result.get("reason") == "SOLANA_RPC_URL not set"
