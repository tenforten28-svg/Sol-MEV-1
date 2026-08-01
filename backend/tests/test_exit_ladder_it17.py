"""
Iteration 17 — Laddered moonbag exit with ratcheting trailing floor.

Modules under test:
- exit_ladder.py  (pure state machine: parse_ladder / evaluate_ladder / record_milestone_hit)
- graduation_executor.py  (_evaluate + _sell partial/full via mocked Jupiter + execute_swap)
- pumpfun_autobuy.py      (Position ladder fields, _current_curve_price, _evaluate_position, _sell)
- server.py endpoints: /api/live/graduation/status, /api/live/pumpfun/autobuy_status + regression sweep

SAFETY: no live flags enabled globally; no real PumpPortal/Jupiter/RPC calls.
All network paths are monkeypatched on locally-built instances.
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

import exit_ladder as el  # noqa: E402
import graduation_executor as ge_mod  # noqa: E402
import pumpfun_autobuy as pf_mod  # noqa: E402

frontend_env = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = _base.rstrip("/")

LAMPORTS = 1_000_000_000
CFG = "5:80:5,20:50:10,100:100:50"


# ---------------------------------------------------------------- fake infra
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
        self.pumpfun_positions = _FakeColl()
        self.pumpfun_detections = _FakeColl()
        self.trades = _FakeColl()


# ============================================================ PURE LOGIC
class TestParseLadder:
    def test_parse_default(self):
        ms = el.parse_ladder(CFG)
        assert len(ms) == 3
        assert [m.mult for m in ms] == [5.0, 20.0, 100.0]
        assert [m.sell_pct_of_remaining for m in ms] == [80.0, 50.0, 100.0]
        assert [m.floor_after for m in ms] == [5.0, 10.0, 50.0]

    def test_default_const_matches(self):
        assert el.DEFAULT_LADDER_CFG == CFG
        assert el.DEFAULT_RUG_STOP == 0.5

    def test_sorted_ascending_from_unsorted_input(self):
        ms = el.parse_ladder("100:100:50,5:80:5,20:50:10")
        assert [m.mult for m in ms] == [5.0, 20.0, 100.0]

    def test_malformed_entries_skipped(self):
        ms = el.parse_ladder("5:80:5,garbage,20:50,abc:1:2,30:0:1,40:200:1,50:50:1")
        assert [m.mult for m in ms] == [5.0, 50.0]

    def test_empty_string(self):
        assert el.parse_ladder("") == []
        assert el.parse_ladder(None) == []


class TestEvaluateLadder:
    def setup_method(self):
        self.ms = el.parse_ladder(CFG)
        self.st = el.LadderState()

    def test_hold_at_1x(self):
        a = el.evaluate_ladder(1.0, self.ms, self.st)
        assert a.type == el.LadderActionType.HOLD
        assert a.sell_pct == 0.0

    def test_rug_stop_before_milestone(self):
        a = el.evaluate_ladder(0.4, self.ms, self.st)
        assert a.type == el.LadderActionType.SELL_ALL
        assert a.sell_pct == 100.0
        assert a.reason.startswith("rug_stop")

    def test_rug_stop_disabled_after_milestone_hit(self):
        a = el.evaluate_ladder(5.0, self.ms, self.st)
        assert a.type == el.LadderActionType.SELL_PARTIAL
        el.record_milestone_hit(self.st, self.ms, 0)
        a2 = el.evaluate_ladder(0.4, self.ms, self.st)
        assert "rug_stop" not in a2.reason
        # floor not armed (no peak >= 5.25) so it holds
        assert a2.type == el.LadderActionType.HOLD

    def test_milestone_0_hit(self):
        a = el.evaluate_ladder(5.0, self.ms, self.st)
        assert a.type == el.LadderActionType.SELL_PARTIAL
        assert a.sell_pct == 80.0
        assert a.milestone_index == 0
        # not auto-recorded
        assert self.st.milestones_hit == []
        el.record_milestone_hit(self.st, self.ms, 0)
        assert self.st.milestones_hit == [0]
        assert self.st.current_floor == 5.0
        assert self.st.floor_armed is False

    def test_one_step_at_a_time_on_big_jump(self):
        a = el.evaluate_ladder(25.0, self.ms, self.st)
        assert a.milestone_index == 0 and a.sell_pct == 80.0
        el.record_milestone_hit(self.st, self.ms, 0)
        a2 = el.evaluate_ladder(25.0, self.ms, self.st)
        assert a2.type == el.LadderActionType.SELL_PARTIAL
        assert a2.milestone_index == 1 and a2.sell_pct == 50.0

    def test_ratchet_floor_moves_up_only(self):
        el.record_milestone_hit(self.st, self.ms, 0)
        assert self.st.current_floor == 5.0
        el.record_milestone_hit(self.st, self.ms, 1)
        assert self.st.current_floor == 10.0
        assert self.st.milestones_hit == [0, 1]
        # re-recording an old (lower-floor) milestone must not lower the floor
        el.record_milestone_hit(self.st, self.ms, 0)
        assert self.st.current_floor == 10.0
        assert self.st.milestones_hit == [0, 1]
        el.record_milestone_hit(self.st, self.ms, 2)
        assert self.st.current_floor == 50.0

    def test_floor_arming_sequence(self):
        el.evaluate_ladder(5.0, self.ms, self.st)
        el.record_milestone_hit(self.st, self.ms, 0)
        self.st.peak_ratio = 5.0  # only just touched the milestone
        # 1) immediate dip below floor with no arm -> HOLD
        a = el.evaluate_ladder(4.9, self.ms, self.st)
        assert self.st.floor_armed is False
        assert a.type == el.LadderActionType.HOLD, a
        # 2) push above 5.25 -> arms
        el.evaluate_ladder(6.0, self.ms, self.st)
        assert self.st.floor_armed is True
        assert self.st.peak_ratio == 6.0
        # 3) dip below floor -> SELL_ALL trailing_floor
        a3 = el.evaluate_ladder(4.9, self.ms, self.st)
        assert a3.type == el.LadderActionType.SELL_ALL
        assert a3.sell_pct == 100.0
        assert "trailing_floor" in a3.reason

    def test_hold_expired_short_circuits(self):
        a = el.evaluate_ladder(50.0, self.ms, self.st, hold_expired=True)
        assert a.type == el.LadderActionType.SELL_ALL
        assert a.reason == "time_limit"
        assert self.st.milestones_hit == []

    def test_peak_tracking(self):
        el.evaluate_ladder(3.0, self.ms, self.st)
        assert self.st.peak_ratio == 3.0
        el.evaluate_ladder(2.0, self.ms, self.st)
        assert self.st.peak_ratio == 3.0

    def test_empty_ladder_still_rug_stops_and_holds(self):
        st = el.LadderState()
        assert el.evaluate_ladder(50.0, [], st).type == el.LadderActionType.HOLD
        assert el.evaluate_ladder(0.3, [], st).type == el.LadderActionType.SELL_ALL

    def test_second_floor_arming_gap(self):
        """After ratchet: new floor is auto-armed immediately because peak
        already satisfies floor * arm_bonus (10 * 1.05 = 10.5 < peak 20).
        This is the FIXED behavior — previously the new floor required
        peak > new_milestone.mult * 1.05 which was a bug."""
        el.record_milestone_hit(self.st, self.ms, 0)
        el.record_milestone_hit(self.st, self.ms, 1)
        self.st.peak_ratio = 20.0
        # After milestone 1 ratchet floor=10; peak=20 >> 10*1.05=10.5 → auto-armed
        el.evaluate_ladder(20.0, self.ms, self.st)
        assert self.st.floor_armed is True
        assert self.st.current_floor == 10.0
        # If price now dumps to 9.5 the trailing floor fires
        a = el.evaluate_ladder(9.5, self.ms, self.st)
        assert a.type == el.LadderActionType.SELL_ALL and "trailing_floor" in a.reason


# ============================================ GRADUATION EXECUTOR INTEGRATION
def _make_grad_executor(monkeypatch, *, quote_ratio=5.0, swap_ok=True, buy_sol=0.003,
                        tokens=1_000_000):
    calls = {"quotes": [], "swaps": []}

    async def _get_quote(inp, out, amount, slippage_bps):
        calls["quotes"].append((inp, out, amount, slippage_bps))
        frac = amount / tokens if tokens else 1.0
        return {"outAmount": str(int(quote_ratio * buy_sol * frac * LAMPORTS))}

    async def _execute_swap(inp, out, amount):
        calls["swaps"].append((inp, out, amount))
        if not swap_ok:
            return {"success": False, "error": "sim failed", "signature": None}
        return {"success": True, "signature": "S" * 64,
                "out_amount": int(quote_ratio * buy_sol * LAMPORTS)}

    fake_lt = SimpleNamespace(
        ready=True,
        cfg=SimpleNamespace(slippage_bps=100),
        execute_swap=_execute_swap,
        jupiter=SimpleNamespace(get_quote=_get_quote),
    )
    monkeypatch.setattr(ge_mod, "get_live_trader", lambda: fake_lt)
    ex = ge_mod.GraduationExecutor(_FakeDB())
    ex.cfg.enabled = True
    pos = ge_mod.GraduationPosition("MINT_TEST_1", "POOL_1", "pumpswap", buy_sol,
                                    tokens, "B" * 64, time.time())
    ex.positions["MINT_TEST_1"] = pos
    return ex, pos, calls


class TestGraduationLadderIntegration:
    def test_ladder_config_parsed(self, monkeypatch):
        ex, _, _ = _make_grad_executor(monkeypatch)
        assert len(ex.cfg.ladder) == 3
        assert ex.cfg.rug_stop_mult == 0.5

    def test_partial_sell_at_5x(self, monkeypatch):
        ex, pos, calls = _make_grad_executor(monkeypatch, quote_ratio=5.0)

        async def go():
            d = await ex._evaluate(pos)
            assert d is not None, "expected a decision at 5x"
            assert d["action"] == "sell_partial"
            assert d["sell_pct"] == 80.0
            assert d["milestone_index"] == 0
            assert abs(d["ratio"] - 5.0) < 1e-6
            await ex._sell("MINT_TEST_1", d)

        asyncio.run(go())
        assert len(calls["swaps"]) == 1
        assert calls["swaps"][0][2] == int(1_000_000 * 0.8)
        assert pos.tokens_out == 1_000_000 - 800_000
        assert pos.ladder_state.milestones_hit == [0]
        assert pos.ladder_state.current_floor == 5.0
        assert pos.closed is False
        assert "MINT_TEST_1" in ex.positions
        events = [d["event"] for d in ex.db.graduation_positions.docs]
        assert "partial_sell" in events
        assert "closed" not in events

    def test_failed_partial_sell_does_not_record_milestone(self, monkeypatch):
        ex, pos, calls = _make_grad_executor(monkeypatch, quote_ratio=5.0, swap_ok=False)

        async def go():
            d = await ex._evaluate(pos)
            await ex._sell("MINT_TEST_1", d)

        asyncio.run(go())
        assert pos.ladder_state.milestones_hit == []
        assert pos.ladder_state.current_floor is None
        assert pos.tokens_out == 1_000_000
        events = [d["event"] for d in ex.db.graduation_positions.docs]
        assert events == ["sell_failed"]

    def test_ratio_normalized_after_partial(self, monkeypatch):
        """After selling 80%, a flat price must still read ~5x (not 1x)."""
        ex, pos, _ = _make_grad_executor(monkeypatch, quote_ratio=5.0)

        async def go():
            d = await ex._evaluate(pos)
            await ex._sell("MINT_TEST_1", d)
            d2 = await ex._evaluate(pos)
            return d2

        d2 = asyncio.run(go())
        # still 5x -> milestone 1 (20x) not reached, floor not armed -> HOLD (None)
        assert d2 is None
        assert abs(pos.ladder_state.peak_ratio - 5.0) < 1e-6

    def test_rug_stop_full_close(self, monkeypatch):
        ex, pos, calls = _make_grad_executor(monkeypatch, quote_ratio=0.4)

        async def go():
            d = await ex._evaluate(pos)
            assert d["action"] == "sell_all"
            assert d["reason"].startswith("rug_stop")
            await ex._sell("MINT_TEST_1", d)

        asyncio.run(go())
        assert calls["swaps"][0][2] == 1_000_000
        assert pos.closed is True
        assert "MINT_TEST_1" not in ex.positions
        events = [d["event"] for d in ex.db.graduation_positions.docs]
        assert "closed" in events
        assert len(ex.db.trades.docs) == 1

    def test_time_limit_exit(self, monkeypatch):
        ex, pos, _ = _make_grad_executor(monkeypatch, quote_ratio=2.0)
        pos.opened_at = time.time() - (ex.cfg.hold_max_seconds + 10)

        async def go():
            return await ex._evaluate(pos)

        d = asyncio.run(go())
        assert d["action"] == "sell_all" and d["reason"] == "time_limit"

    def test_full_ladder_progression_closes_position(self, monkeypatch):
        ex, pos, calls = _make_grad_executor(monkeypatch, quote_ratio=150.0)

        async def go():
            for _ in range(6):
                d = await ex._evaluate(pos)
                if d is None:
                    break
                await ex._sell("MINT_TEST_1", d)

        asyncio.run(go())
        assert pos.ladder_state.milestones_hit == [0, 1, 2]
        assert pos.closed is True
        assert pos.tokens_out == 0
        assert len(calls["swaps"]) == 3


# ============================================ PUMPFUN AUTOBUY INTEGRATION
def _make_pf(monkeypatch, *, price=None, send_ok=True, entry_price=1e-9):
    calls = {"builds": [], "sends": 0}
    fake_lt = SimpleNamespace(ready=True, cfg=SimpleNamespace(rpc_url="http://rpc.invalid",
                                                              slippage_bps=100))
    monkeypatch.setattr(pf_mod, "get_live_trader", lambda: fake_lt)
    pf = pf_mod.PumpFunAutoBuyer(_FakeDB())
    pf.cfg.enabled = True

    async def _build(action, mint, amount, denominated_in_sol=False, **k):
        calls["builds"].append((action, mint, amount, denominated_in_sol))
        return b"\x00" * 10

    async def _send(tx):
        calls["sends"] += 1
        if not send_ok:
            return {"success": False, "error": "blockhash expired", "signature": None}
        return {"success": True, "signature": "P" * 64}

    async def _curve_price(mint):
        return price

    pf._pumpportal_build_tx = _build
    pf._sign_and_send = _send
    pf._current_curve_price = _curve_price

    pos = pf_mod.Position("MINT_PF_1", 0.01, 1000.0, "B" * 64, time.time(),
                          entry_price=entry_price)
    pf.positions["MINT_PF_1"] = pos
    return pf, pos, calls


class TestPumpfunLadderIntegration:
    def test_position_new_fields(self):
        pos = pf_mod.Position("M", 0.01, 100.0, "sig", time.time(), entry_price=1.5e-9)
        assert pos.entry_price == 1.5e-9
        assert pos.remaining_pct_of_original == 100.0
        assert isinstance(pos.ladder_state, el.LadderState)
        assert pos.partial_sells == []

    def test_cfg_ladder(self, monkeypatch):
        pf, _, _ = _make_pf(monkeypatch)
        assert len(pf.cfg.ladder) == 3
        assert pf.cfg.rug_stop_mult == 0.5

    def test_partial_sell_pct_string(self, monkeypatch):
        pf, pos, calls = _make_pf(monkeypatch, price=5e-9, entry_price=1e-9)

        async def go():
            d = await pf._evaluate_position(pos)
            assert d["action"] == "sell_partial" and d["sell_pct"] == 80.0
            await pf._sell("MINT_PF_1", d)

        asyncio.run(go())
        assert calls["builds"][0][0] == "sell"
        assert calls["builds"][0][2] == "80%"
        assert calls["builds"][0][3] is False
        assert abs(pos.remaining_pct_of_original - 20.0) < 1e-9
        assert pos.ladder_state.milestones_hit == [0]
        assert pos.ladder_state.current_floor == 5.0
        assert pos.closed is False
        events = [d["event"] for d in pf.db.pumpfun_positions.docs]
        assert "partial_sell" in events and "closed" not in events

    def test_failed_sell_keeps_state(self, monkeypatch):
        pf, pos, _ = _make_pf(monkeypatch, price=5e-9, send_ok=False)

        async def go():
            d = await pf._evaluate_position(pos)
            await pf._sell("MINT_PF_1", d)

        asyncio.run(go())
        assert pos.ladder_state.milestones_hit == []
        assert pos.remaining_pct_of_original == 100.0
        assert [d["event"] for d in pf.db.pumpfun_positions.docs] == ["sell_failed"]

    def test_rug_stop(self, monkeypatch):
        pf, pos, calls = _make_pf(monkeypatch, price=0.4e-9)

        async def go():
            d = await pf._evaluate_position(pos)
            assert d["reason"].startswith("rug_stop")
            await pf._sell("MINT_PF_1", d)

        asyncio.run(go())
        assert calls["builds"][0][2] == "100%"
        assert pos.closed is True
        assert "MINT_PF_1" not in pf.positions
        assert len(pf.db.trades.docs) == 1

    def test_no_quote_no_exit_until_time_limit(self, monkeypatch):
        pf, pos, _ = _make_pf(monkeypatch, price=None)

        async def go():
            assert await pf._evaluate_position(pos) is None
            pos.opened_at = time.time() - (pf.cfg.hold_max_seconds + 5)
            return await pf._evaluate_position(pos)

        d = asyncio.run(go())
        assert d["action"] == "sell_all" and d["reason"] == "time_limit_no_quote"

    def test_full_progression_closes(self, monkeypatch):
        pf, pos, calls = _make_pf(monkeypatch, price=150e-9)

        async def go():
            for _ in range(6):
                d = await pf._evaluate_position(pos)
                if d is None:
                    break
                await pf._sell("MINT_PF_1", d)

        asyncio.run(go())
        assert pos.ladder_state.milestones_hit == [0, 1, 2]
        assert pos.closed is True
        assert [b[2] for b in calls["builds"]] == ["80%", "50%", "100%"]

    def test_curve_price_from_reserves(self, monkeypatch):
        """_current_curve_price = virtual_sol_reserves / virtual_token_reserves."""
        fake_lt = SimpleNamespace(ready=True,
                                  cfg=SimpleNamespace(rpc_url="http://rpc.invalid"))
        monkeypatch.setattr(pf_mod, "get_live_trader", lambda: fake_lt)
        pf = pf_mod.PumpFunAutoBuyer(_FakeDB())

        async def _cs(mint):
            return {"ok": True, "virtual_sol_reserves": 30_000_000_000}

        async def _csf(mint):
            return {"ok": True, "virtual_token_reserves": 1_000_000_000_000_000,
                    "virtual_sol_reserves": 30_000_000_000, "complete": False}

        pf._check_curve_state = _cs
        pf._check_curve_state_full = _csf
        price = asyncio.run(pf._current_curve_price("M"))
        assert abs(price - (30_000_000_000 / 1_000_000_000_000_000)) < 1e-18

    def test_curve_price_none_on_failure(self, monkeypatch):
        fake_lt = SimpleNamespace(ready=True,
                                  cfg=SimpleNamespace(rpc_url="http://rpc.invalid"))
        monkeypatch.setattr(pf_mod, "get_live_trader", lambda: fake_lt)
        pf = pf_mod.PumpFunAutoBuyer(_FakeDB())

        async def _bad(mint):
            return {"ok": False, "reason": "no data"}

        pf._check_curve_state = _bad
        pf._check_curve_state_full = _bad
        assert asyncio.run(pf._current_curve_price("M")) is None


# ============================================================ API ENDPOINTS
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


EXPECTED_LADDER = [
    {"mult": 5.0, "sell_pct": 80.0, "floor_after": 5.0},
    {"mult": 20.0, "sell_pct": 50.0, "floor_after": 10.0},
    {"mult": 100.0, "sell_pct": 100.0, "floor_after": 50.0},
]


class TestApiLadderShape:
    def test_graduation_status_ladder(self, api):
        r = api.get(f"{BASE_URL}/api/live/graduation/status", timeout=30)
        assert r.status_code == 200, r.text[:300]
        cfg = r.json()["executor"]["config"]
        assert cfg["rug_stop_mult"] == 0.5
        ladder = cfg["ladder"]
        assert len(ladder) == 3
        for got, exp in zip(ladder, EXPECTED_LADDER):
            assert float(got["mult"]) == exp["mult"]
            assert float(got["sell_pct"]) == exp["sell_pct"]
            assert float(got["floor_after"]) == exp["floor_after"]

    def test_pumpfun_autobuy_status_ladder(self, api):
        r = api.get(f"{BASE_URL}/api/live/pumpfun/autobuy_status", timeout=30)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        node = body.get("autobuy") or body
        assert node.get("tp_sl_enforced") is True, node.get("tp_sl_enforced")
        assert "laddered exits" in (node.get("exit_policy") or "")
        assert node.get("rug_stop_mult") == 0.5
        ladder = node.get("ladder")
        assert isinstance(ladder, list) and len(ladder) == 3
        for got, exp in zip(ladder, EXPECTED_LADDER):
            assert float(got["mult"]) == exp["mult"]
            assert float(got["sell_pct"]) == exp["sell_pct"]
            assert float(got["floor_after"]) == exp["floor_after"]

    def test_no_live_flags_enabled(self, api):
        g = api.get(f"{BASE_URL}/api/live/graduation/status", timeout=30).json()
        assert g["executor"]["enabled"] is False
        p = api.get(f"{BASE_URL}/api/live/pumpfun/autobuy_status", timeout=30).json()
        node = p.get("autobuy") or p
        assert node.get("enabled") is False


REGRESSION_ENDPOINTS = [
    "/api/health",
    "/api/live/status",
    "/api/live/pumpfun/status",
    "/api/live/pumpfun/detections",
    "/api/live/pumpfun/positions",
    "/api/live/graduation/status",
    "/api/live/graduation/events",
    "/api/live/graduation/positions",
    "/api/live/summary",
    "/api/live/auto_arb/status",
    "/api/bot_diagnostic",
    "/api/stats",
    "/api/opportunities",
    "/api/trades",
]


class TestRegressionEndpoints:
    @pytest.mark.parametrize("path", REGRESSION_ENDPOINTS)
    def test_get_200(self, api, path):
        r = api.get(f"{BASE_URL}{path}", timeout=45)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
        assert isinstance(r.json(), (dict, list))

    def test_graduation_replay_post(self, api):
        r = api.post(f"{BASE_URL}/api/live/graduation/replay",
                     params={"signature": "T" * 64, "source": "pumpswap"}, timeout=45)
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json(), dict)

    def test_emergency_stop(self, api):
        r = api.post(f"{BASE_URL}/api/live/emergency_stop", json={}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("ok") is True or "stopped" in str(r.json()).lower()
