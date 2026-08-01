"""
Iteration 16 — Graduation snipe system tests.

Modules under test:
- graduation_monitor.py (program IDs, status shape)
- graduation_executor.py (on_event safety gates — fail-closed)
- server.py graduation endpoints + /api/live/emergency_stop kill switch
- regression sweep of existing live endpoints

SAFETY: never enables GRADUATION_ENABLED / GRADUATION_EXEC_ENABLED via env or
touches live trading config globally. Executor gates are exercised on locally
constructed instances with a stub live_trader whose execute_swap raises.
"""
import asyncio
import os
import sys
import time
from types import SimpleNamespace

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

import graduation_monitor as gm_mod  # noqa: E402
import graduation_executor as ge_mod  # noqa: E402

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

EVENT = {
    "source": "pumpswap",
    "mint": "TEST_MINT_1111111111111111111111111111111111",
    "pool_address": "TEST_POOL_1111111111111111111111111111111",
    "reserves_sol": 120.0,
    "signature": "T" * 64,
    "dex": "pumpswap",
}


class _FakeColl:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(doc)
        return SimpleNamespace(inserted_id="x")

    async def create_index(self, *a, **k):
        return "idx"


class _FakeDB:
    def __init__(self):
        self.graduation_positions = _FakeColl()
        self.graduation_events = _FakeColl()
        self.trades = _FakeColl()


def _make_executor(monkeypatch, *, enabled, lt_ready, min_pool=50.0):
    """Build an isolated executor with a booby-trapped live_trader."""
    def _boom(*a, **k):
        raise AssertionError("live_trader.execute_swap MUST NOT be called")

    fake_lt = SimpleNamespace(
        ready=lt_ready,
        cfg=SimpleNamespace(slippage_bps=100),
        execute_swap=_boom,
        jupiter=SimpleNamespace(get_quote=_boom),
    )
    monkeypatch.setattr(ge_mod, "get_live_trader", lambda: fake_lt)
    # never actually wait the settle delay
    monkeypatch.setattr(ge_mod.asyncio, "sleep", lambda *_a, **_k: asyncio.sleep(0))
    ex = ge_mod.GraduationExecutor(_FakeDB())
    ex.cfg.enabled = enabled
    ex.cfg.min_pool_sol = min_pool
    return ex


# ---------------- graduation_monitor module constants / status ----------------
class TestMonitorModule:
    def test_program_ids(self):
        assert gm_mod.PUMPSWAP_PROGRAM_ID == "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
        assert gm_mod.LAUNCHLAB_PROGRAM_ID == "LanMV9UNbk6iCfu4pVeMxKUKQg3jTsA9F5Ke8V5nJ8t"
        assert gm_mod.RAYDIUM_CPMM_PROGRAM_ID == "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
        assert gm_mod.SOL_MINT == "So11111111111111111111111111111111111111112"

    def test_monitor_disabled_start_is_noop(self):
        mon = gm_mod.GraduationMonitor(_FakeDB())
        mon.cfg.enabled = False
        asyncio.run(mon.start())
        assert mon.running() is False
        st = mon.status()
        assert st["enabled"] is False
        for key in ("running", "wss_configured", "http_configured", "pumpswap", "bonk_cpmm", "last_error"):
            assert key in st


# ---------------- executor safety gates (fail-closed) ----------------
class TestExecutorGates:
    def test_disabled_executor_no_buy(self, monkeypatch):
        ex = _make_executor(monkeypatch, enabled=False, lt_ready=True)
        res = asyncio.run(ex.on_event(dict(EVENT)))
        assert res["ok"] is False
        assert "exec disabled" in res["reason"]
        assert ex.buys_fired == 0

    def test_live_trader_not_ready(self, monkeypatch):
        ex = _make_executor(monkeypatch, enabled=True, lt_ready=False)
        res = asyncio.run(ex.on_event(dict(EVENT)))
        assert res["ok"] is False
        assert res["reason"] == "live_trader not ready"
        assert ex.buys_fired == 0

    def test_low_liquidity_reject(self, monkeypatch):
        ex = _make_executor(monkeypatch, enabled=True, lt_ready=True, min_pool=50.0)
        ev = dict(EVENT, reserves_sol=10.0)
        res = asyncio.run(ex.on_event(ev))
        assert res["ok"] is False
        assert res["reason"].startswith("low_liquidity:")
        assert ex.rejects_filter == 1
        assert ex.buys_fired == 0

    def test_daily_budget_cap(self, monkeypatch):
        ex = _make_executor(monkeypatch, enabled=True, lt_ready=True)
        ex.day_spent_sol = ex.cfg.daily_budget_sol
        res = asyncio.run(ex.on_event(dict(EVENT)))
        assert res["ok"] is False
        assert "daily budget" in res["reason"]
        assert ex.buys_fired == 0

    def test_max_concurrent_cap(self, monkeypatch):
        ex = _make_executor(monkeypatch, enabled=True, lt_ready=True)
        for i in range(ex.cfg.max_concurrent):
            ex.positions[f"m{i}"] = object()
        res = asyncio.run(ex.on_event(dict(EVENT)))
        assert res["ok"] is False
        assert "max_concurrent" in res["reason"]
        assert ex.buys_fired == 0

    def test_cooldown(self, monkeypatch):
        ex = _make_executor(monkeypatch, enabled=True, lt_ready=True)
        ex.last_buy_at = time.time()
        res = asyncio.run(ex.on_event(dict(EVENT)))
        assert res["ok"] is False
        assert "cooldown" in res["reason"]
        assert ex.buys_fired == 0

    def test_per_source_disable(self, monkeypatch):
        ex = _make_executor(monkeypatch, enabled=True, lt_ready=True)
        ex.cfg.pumpswap_enabled = False
        res = asyncio.run(ex.on_event(dict(EVENT)))
        assert res["ok"] is False and "pumpswap exec disabled" in res["reason"]
        ex2 = _make_executor(monkeypatch, enabled=True, lt_ready=True)
        ex2.cfg.bonk_enabled = False
        res2 = asyncio.run(ex2.on_event(dict(EVENT, source="bonk_cpmm")))
        assert res2["ok"] is False and "bonk exec disabled" in res2["reason"]

    def test_status_shape_defaults(self, monkeypatch):
        ex = _make_executor(monkeypatch, enabled=False, lt_ready=False)
        st = ex.status()
        assert st["strategy"] == "fade_the_dump"
        assert st["enabled"] is False
        assert st["open_positions"] == 0
        assert set(st["counters"]) == {
            "events_seen", "buys_fired", "buys_successful", "sells_fired", "rejects_filter"}


# ---------------- API endpoints ----------------
@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


class TestGraduationAPI:
    def test_status(self, client):
        r = client.get(f"{BASE_URL}/api/live/graduation/status", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "error" not in d, d
        mon, ex = d["monitor"], d["executor"]
        assert mon["enabled"] is False
        assert ex["enabled"] is False
        assert ex["strategy"] == "fade_the_dump"
        for k in ("running", "wss_configured", "http_configured", "last_error"):
            assert k in mon
        for k in ("enabled", "events_received", "graduations_detected", "last_at"):
            assert k in mon["pumpswap"] and k in mon["bonk_cpmm"]
        cfg = ex["config"]
        assert cfg["buy_sol"] == 0.003
        assert cfg["daily_budget_sol"] == 0.02
        assert cfg["max_concurrent"] == 2
        assert cfg["cooldown_sec"] == 20
        assert cfg["settle_delay_sec"] == 3
        assert cfg["hold_max_seconds"] == 180
        assert cfg["take_profit_mult"] == 1.5
        assert cfg["stop_loss_mult"] == 0.7
        assert cfg["min_pool_sol"] == 50.0
        assert cfg["slippage_bps"] == 1500
        assert ex["counters"]["buys_fired"] == 0
        assert ex["open_positions"] == 0
        assert isinstance(ex["position_mints"], list)
        assert "day_spent_sol" in ex and "day_budget_remaining_sol" in ex
        assert "live_trader_ready" in ex

    def test_events(self, client):
        r = client.get(f"{BASE_URL}/api/live/graduation/events?limit=5", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "error" not in d, d
        assert isinstance(d["events"], list) and d["count"] == len(d["events"])
        assert len(d["events"]) <= 5

    def test_events_source_filter(self, client):
        r = client.get(f"{BASE_URL}/api/live/graduation/events?limit=5&source=pumpswap", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "error" not in d, d
        assert all(e.get("source") == "pumpswap" for e in d["events"])

    def test_positions(self, client):
        r = client.get(f"{BASE_URL}/api/live/graduation/positions?limit=5", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "error" not in d, d
        assert isinstance(d["events"], list) and d["count"] == len(d["events"])

    def test_replay_invalid_sig(self, client):
        r = client.post(f"{BASE_URL}/api/live/graduation/replay?signature=INVALID_SIG&source=pumpswap",
                        timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is False
        assert "reason" in d or "error" in d

    def test_replay_invalid_source(self, client):
        r = client.post(f"{BASE_URL}/api/live/graduation/replay?signature=abc&source=invalid", timeout=30)
        assert r.status_code == 200
        assert "source must be" in r.json().get("error", "")


class TestEmergencyStop:
    def test_emergency_stop(self, client):
        r = client.post(f"{BASE_URL}/api/live/emergency_stop", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True, d
        for name in ("live_trader", "pumpfun_autobuy", "graduation_executor"):
            assert name in d["stopped"], d
        assert "note" in d

    def test_gates_off_after_stop(self, client):
        ls = client.get(f"{BASE_URL}/api/live/status", timeout=30).json()
        blob = str(ls)
        assert "live_enabled" in blob or "simulation" in blob
        gs = client.get(f"{BASE_URL}/api/live/graduation/status", timeout=30).json()
        assert gs["executor"]["enabled"] is False
        ab = client.get(f"{BASE_URL}/api/live/pumpfun/autobuy_status", timeout=30).json()
        assert ab.get("enabled") is False, ab


# ---------------- regression sweep ----------------
REGRESSION = [
    "/api/health", "/api/live/status", "/api/live/pumpfun/status",
    "/api/live/pumpfun/autobuy_status", "/api/live/summary",
    "/api/live/auto_arb/status", "/api/bot_diagnostic", "/api/stats",
    "/api/opportunities", "/api/trades",
]


@pytest.mark.parametrize("path", REGRESSION)
def test_regression_endpoints(client, path):
    r = client.get(f"{BASE_URL}{path}", timeout=60)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:300]}"
