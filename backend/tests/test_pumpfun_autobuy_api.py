"""
Backend tests for Pump.fun sniper + auto-buy endpoints (iteration 12)
+ regression sweep across core /api endpoints.

SAFETY: these tests only READ. No flag is ever enabled.
"""
import os
import inspect

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL is missing from env and /app/frontend/.env")
BASE_URL = base_url.rstrip("/")


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- Pump.fun sniper status ----------------
class TestPumpfunSniperStatus:
    def test_status_shape_and_safe_defaults(self, api):
        r = api.get(f"{BASE_URL}/api/live/pumpfun/status", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "error" not in d, f"endpoint returned handled error: {d.get('error')}"
        for k in ["enabled", "running", "wss_host", "total_events_received",
                  "new_mint_detections", "last_detection_at", "connection_count",
                  "last_error", "note"]:
            assert k in d, f"missing field {k} in {sorted(d)}"
        assert d["enabled"] is False, "SAFETY: sniper enabled by default"
        assert d["running"] is False, "SAFETY: sniper running by default"
        assert isinstance(d["total_events_received"], int)
        assert isinstance(d["new_mint_detections"], int)

    def test_detections_list(self, api):
        r = api.get(f"{BASE_URL}/api/live/pumpfun/detections?limit=5", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "error" not in d, d.get("error")
        assert set(["count", "detections"]).issubset(d)
        assert isinstance(d["detections"], list)
        assert d["count"] == len(d["detections"])
        assert len(d["detections"]) <= 5
        for doc in d["detections"]:
            assert "_id" not in doc, "MongoDB _id leaked in response"


# ---------------- Pump.fun auto-buy status ----------------
REQUIRED_CFG = [
    "buy_sol", "daily_budget_sol", "max_concurrent", "cooldown_sec",
    "require_authorities_revoked", "hold_max_seconds", "take_profit_mult",
    "stop_loss_mult", "settle_delay_sec", "slippage_pct", "priority_fee_sol",
]


class TestPumpfunAutobuyStatus:
    def test_autobuy_status_shape(self, api):
        r = api.get(f"{BASE_URL}/api/live/pumpfun/autobuy_status", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "error" not in d, d.get("error")
        for k in ["enabled", "config", "day_spent_sol", "day_budget_remaining_sol",
                  "open_positions", "position_mints", "counters", "last_reason",
                  "live_trader_ready", "execution_backend"]:
            assert k in d, f"missing field {k} in {sorted(d)}"
        assert d["enabled"] is False, "SAFETY: auto-buy enabled by default!"
        assert d["execution_backend"] == "pumpportal_local_tx + quicknode_rpc"
        assert d["open_positions"] == 0
        assert d["position_mints"] == []
        for k in REQUIRED_CFG:
            assert k in d["config"], f"config missing {k}"
        for k in ["attempts", "buys_fired", "buys_successful", "sells_fired", "rejects_safety"]:
            assert k in d["counters"], f"counters missing {k}"

    def test_autobuy_config_caps_are_small(self, api):
        cfg = api.get(f"{BASE_URL}/api/live/pumpfun/autobuy_status", timeout=30).json()["config"]
        assert cfg["buy_sol"] <= 0.01, f"buy_sol default too large: {cfg['buy_sol']}"
        assert cfg["daily_budget_sol"] <= 0.05, f"daily budget too large: {cfg['daily_budget_sol']}"
        assert cfg["require_authorities_revoked"] is True
        assert cfg["max_concurrent"] >= 1

    def test_budget_math(self, api):
        d = api.get(f"{BASE_URL}/api/live/pumpfun/autobuy_status", timeout=30).json()
        assert abs((d["config"]["daily_budget_sol"] - d["day_spent_sol"])
                   - d["day_budget_remaining_sol"]) < 1e-6

    def test_positions_endpoint(self, api):
        r = api.get(f"{BASE_URL}/api/live/pumpfun/positions?limit=5", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "error" not in d, d.get("error")
        assert set(["count", "events"]).issubset(d)
        assert isinstance(d["events"], list)
        assert d["count"] == len(d["events"])
        for doc in d["events"]:
            assert "_id" not in doc, "MongoDB _id leaked in response"


# ---------------- Safety: static verification of maybe_buy gate ----------------
class TestAutoBuySafetyGate:
    def test_maybe_buy_first_branch_is_disabled_gate(self):
        import sys
        sys.path.insert(0, "/app/backend")
        import pumpfun_autobuy
        src = inspect.getsource(pumpfun_autobuy.PumpFunAutoBuyer.maybe_buy)
        # locate first conditional return
        lines = [ln.strip() for ln in src.splitlines() if ln.strip()]
        idx = next(i for i, ln in enumerate(lines) if ln.startswith("if "))
        assert "self.cfg.enabled" in lines[idx], f"first gate is not the enabled check: {lines[idx]}"
        assert "not self.cfg.enabled" in lines[idx]
        assert "auto-buy disabled" in lines[idx + 1]
        assert '"ok": False' in lines[idx + 2] or "'ok': False" in lines[idx + 2]

    def test_env_flags_default_off(self):
        assert os.environ.get("PUMPFUN_AUTO_BUY_ENABLED", "false").lower() in ("false", "0", "no", "off")

    def test_dotenv_file_does_not_arm_autobuy(self):
        env = dotenv_values("/app/backend/.env")
        for key in ["PUMPFUN_AUTO_BUY_ENABLED", "PUMPFUN_SNIPER_ENABLED", "LIVE_TRADING_ENABLED"]:
            val = (env.get(key) or "false").strip().lower()
            assert val in ("false", "0", "no", "off", ""), f"{key}={val} is armed in backend/.env"

    def test_maybe_buy_returns_disabled_without_network(self):
        """Call maybe_buy directly with autobuy disabled - must short-circuit."""
        import sys
        import asyncio
        sys.path.insert(0, "/app/backend")
        from pumpfun_autobuy import PumpFunAutoBuyer
        ab = PumpFunAutoBuyer(db=None)
        assert ab.cfg.enabled is False
        res = asyncio.run(ab.maybe_buy("So11111111111111111111111111111111111111112"))
        assert res["ok"] is False
        assert "auto-buy disabled" in res["reason"]
        assert ab.buys_fired == 0


# ---------------- Regression sweep ----------------
REGRESSION_ENDPOINTS = [
    "/api/health",
    "/api/live/status",
    "/api/live/balance",
    "/api/live/summary",
    "/api/live/auto_arb/status",
    "/api/live/auto_arb/decisions",
    "/api/bot_diagnostic",
    "/api/stats",
    "/api/opportunities",
    "/api/trades",
]


class TestRegression:
    @pytest.mark.parametrize("path", REGRESSION_ENDPOINTS)
    def test_endpoint_200(self, api, path):
        r = api.get(f"{BASE_URL}{path}", timeout=60)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body is not None
        if isinstance(body, list):
            for doc in body[:20]:
                if isinstance(doc, dict):
                    assert "_id" not in doc, f"{path} leaked mongo _id"
