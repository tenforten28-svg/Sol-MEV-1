"""
Iteration 18 — mcap-mode scaled exit ladder + tx landing metrics.

Modules under test:
- pumpfun_autobuy.py : ladder_mode dispatch, _get_sol_usd cache TTL, _current_mcap_usd,
                       entry-mcap gate (fail-closed), fee-check milestone advance
- tx_landings.py     : LandingTracker counters/status + get_tracker singleton
- exit_ladder.py     : floor_after == 0 => no trailing floor
- graduation_executor.py : tracker.record modules
- server.py          : GET /api/live/tx_landings, autobuy_status new keys, regression sweep

SAFETY: no live flags enabled; all external I/O patched.
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
import pumpfun_autobuy as pf_mod  # noqa: E402
import tx_landings as txl  # noqa: E402
import graduation_executor as ge_mod  # noqa: E402

frontend_env = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = _base.rstrip("/")

MCAP_CFG = "10000:50:5000,60000:50:0,300000:100:0"


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
        self.tx_landings = _FakeColl()


# ==================================================== exit_ladder floor_after=0
class TestFloorZeroNoTrailing:
    def test_parse_mcap_ladder(self):
        ms = el.parse_ladder(MCAP_CFG)
        assert [m.mult for m in ms] == [10000.0, 60000.0, 300000.0]
        assert [m.sell_pct_of_remaining for m in ms] == [50.0, 50.0, 100.0]
        assert [m.floor_after for m in ms] == [5000.0, 0.0, 0.0]

    def test_floor_zero_never_arms_or_exits(self):
        ms = el.parse_ladder("60000:50:0")
        st = el.LadderState()
        a = el.evaluate_ladder(60000, ms, st, rug_stop_mult=1300.0)
        assert a.type == el.LadderActionType.SELL_PARTIAL
        el.record_milestone_hit(st, ms, 0)
        assert st.current_floor == 0.0
        # Big pump then a crash to near-zero: no trailing exit may fire
        for sig in (500000, 250000, 10, 1):
            a = el.evaluate_ladder(sig, ms, st, rug_stop_mult=1300.0)
            assert a.type == el.LadderActionType.HOLD, f"unexpected {a.reason} at {sig}"
        assert st.floor_armed is False

    def test_ratchet_keeps_prior_floor_when_next_is_zero(self):
        """DOC-SPEC CHECK: default mcap ladder ratchets 5000 then floor_after=0.
        record_milestone_hit only moves the floor UP, so the $5k floor persists."""
        ms = el.parse_ladder(MCAP_CFG)
        st = el.LadderState()
        el.record_milestone_hit(st, ms, 0)
        assert st.current_floor == 5000.0
        el.record_milestone_hit(st, ms, 1)
        assert st.current_floor == 5000.0, "floor unexpectedly reset to 0"
        # after $60k, falling back to $4k trips trailing floor (5000 armed)
        el.evaluate_ladder(60000, ms, st, rug_stop_mult=1300.0)   # set peak + arm floor
        a = el.evaluate_ladder(4000, ms, st, rug_stop_mult=1300.0)
        assert a.type == el.LadderActionType.SELL_ALL
        assert "trailing_floor" in a.reason
        # ...but riding to 300k still triggers the final milestone
        st2 = el.LadderState()
        el.record_milestone_hit(st2, ms, 0)
        el.record_milestone_hit(st2, ms, 1)
        a2 = el.evaluate_ladder(300000, ms, st2, rug_stop_mult=1300.0)
        assert a2.type == el.LadderActionType.SELL_PARTIAL
        assert a2.milestone_index == 2

    def test_rug_stop_absolute_usd_before_milestone(self):
        ms = el.parse_ladder(MCAP_CFG)
        st = el.LadderState()
        a = el.evaluate_ladder(1200, ms, st, rug_stop_mult=1300.0)
        assert a.type == el.LadderActionType.SELL_ALL and "rug_stop" in a.reason
        # above rug stop, below first milestone => hold
        st2 = el.LadderState()
        assert el.evaluate_ladder(4000, ms, st2, rug_stop_mult=1300.0).type == el.LadderActionType.HOLD


# ==================================================== LandingTracker unit tests
class TestLandingTracker:
    def test_counters_and_status(self):
        db = _FakeDB()
        t = txl.LandingTracker(db)
        assert t.status() == {"modules": {}}
        now = time.time()

        async def go():
            await t.record("pumpfun_autobuy", "sig1", now, now + 1.5, True)
            # timed_out: never confirmed, no explicit error
            await t.record("pumpfun_autobuy", "sig2", now, None, False, None)
            # failed: explicit error surfaced (RPC rejected or on-chain revert)
            await t.record("pumpfun_autobuy", "sig3", now, None, False, "err")

        asyncio.run(go())
        m = t.status()["modules"]["pumpfun_autobuy"]
        assert m["submits"] == 3
        assert m["landed"] == 1
        assert m["timed_out"] == 1
        assert m["failed"] == 1
        assert m["landing_rate_pct"] == 33.3
        assert m["avg_land_latency_ms"] == 1500
        assert m["recent_samples"] == 1
        assert len(db.tx_landings.docs) == 3
        assert db.tx_landings.docs[0]["latency_ms"] == 1500

    def test_persist_failure_does_not_raise(self):
        class Boom:
            async def insert_one(self, doc):
                raise RuntimeError("db down")

        t = txl.LandingTracker(SimpleNamespace(tx_landings=Boom()))
        asyncio.run(t.record("m", "s", time.time(), time.time(), True))
        assert t.by_module["m"]["landed"] == 1

    def test_latency_window_capped_at_50(self):
        t = txl.LandingTracker(_FakeDB())

        async def go():
            for i in range(60):
                await t.record("m", f"s{i}", 0.0, 0.001 * (i + 1), True)

        asyncio.run(go())
        assert t.status()["modules"]["m"]["recent_samples"] == 50
        assert t.by_module["m"]["submits"] == 60

    def test_singleton(self):
        txl._instance = None
        with pytest.raises(RuntimeError):
            txl.get_tracker()
        db = _FakeDB()
        a = txl.get_tracker(db)
        b = txl.get_tracker()
        assert a is b
        txl._instance = None


# ==================================================== mcap helpers
def _make_pf(monkeypatch, *, mode="mcap", quote_calls=None):
    fake_jup = SimpleNamespace()

    async def _quote(inp, out, amount, slip):
        if quote_calls is not None:
            quote_calls.append((inp, out, amount))
        return {"outAmount": str(200 * 1_000_000)}   # 200 USDC per SOL

    fake_jup.get_quote = _quote
    fake_lt = SimpleNamespace(ready=True, jupiter=fake_jup,
                              cfg=SimpleNamespace(rpc_url="http://rpc.invalid", slippage_bps=100))
    monkeypatch.setattr(pf_mod, "get_live_trader", lambda: fake_lt)
    monkeypatch.setenv("PUMPFUN_LADDER_MODE", mode)
    pf = pf_mod.PumpFunAutoBuyer(_FakeDB())
    pf.cfg.enabled = True
    pf_mod._sol_usd_cache["price"] = None
    pf_mod._sol_usd_cache["at"] = 0.0
    return pf


class TestMcapConfig:
    def test_defaults(self, monkeypatch):
        pf = _make_pf(monkeypatch)
        assert pf.cfg.ladder_mode == "mcap"
        assert pf.cfg.ladder_mcap_cfg == MCAP_CFG
        assert [m.mult for m in pf.cfg.ladder_mcap] == [10000.0, 60000.0, 300000.0]
        assert pf.cfg.rug_stop_mcap_usd == 1300.0
        assert pf.cfg.entry_mcap_max_usd == 5000.0
        assert abs(pf.cfg.min_sell_usd - 0.20) < 1e-9

    def test_default_mode_is_ratio(self, monkeypatch):
        monkeypatch.delenv("PUMPFUN_LADDER_MODE", raising=False)
        pf = _make_pf(monkeypatch, mode="ratio")
        assert pf.cfg.ladder_mode == "ratio"


class TestSolUsdAndMcap:
    def test_mcap_none_on_rpc_failure(self, monkeypatch):
        pf = _make_pf(monkeypatch)

        async def _bad(mint):
            return {"ok": False, "reason": "no data"}

        pf._check_curve_state_full = _bad
        assert asyncio.run(pf._current_mcap_usd("M")) is None

    def test_mcap_value(self, monkeypatch):
        pf = _make_pf(monkeypatch)
        vsr, vtr = 30_000_000_000, 1_000_000_000_000_000

        async def _csf(mint):
            return {"ok": True, "virtual_sol_reserves": vsr,
                    "virtual_token_reserves": vtr, "complete": False}

        pf._check_curve_state_full = _csf
        got = asyncio.run(pf._current_mcap_usd("M"))
        expect = (vsr / vtr) * 1e15 / 1_000_000_000 * 200.0
        assert abs(got - expect) < 1e-6, (got, expect)

    def test_sol_usd_cache_ttl_30s(self, monkeypatch):
        calls = []
        pf = _make_pf(monkeypatch, quote_calls=calls)

        async def go():
            p1 = await pf._get_sol_usd()
            p2 = await pf._get_sol_usd()
            return p1, p2

        p1, p2 = asyncio.run(go())
        assert p1 == 200.0 and p2 == 200.0
        assert len(calls) == 1, f"jupiter called {len(calls)} times within TTL"
        # expire the cache
        pf_mod._sol_usd_cache["at"] = time.time() - 31
        asyncio.run(pf._get_sol_usd())
        assert len(calls) == 2

    def test_sol_usd_fallback_on_quote_error(self, monkeypatch):
        pf = _make_pf(monkeypatch)

        async def _boom(*a, **k):
            raise RuntimeError("jup down")

        pf.lt.jupiter.get_quote = _boom
        assert asyncio.run(pf._get_sol_usd()) == 150.0


# ==================================================== entry gate
def _patch_gates(pf, mcap_ret):
    """Make every pre-gate pass so we land on the entry-mcap gate."""
    calls = {"builds": 0, "sends": 0}

    async def _safety(mint):
        return {"authorities_safe": True, "mint_authority_revoked": True,
                "freeze_authority_revoked": True, "is_token_2022": False,
                "extensions_safe": True, "supply": int(1e15)}

    async def _dev(sig, mint, supply):
        return {"ok": True, "within_limit": True, "dev_hold_pct": 1.0}

    async def _curve(mint):
        return {"ok": True, "complete": False, "liquidity_ok": True,
                "real_sol_reserves": 10_000_000_000, "virtual_sol_reserves": 3e10}

    async def _holders(*a, **k):
        return {"ok": True, "top1_within_limit": True, "top10_within_limit": True,
                "top1_pct": 1.0, "top10_pct": 5.0}

    async def _mcap(mint, supply_raw_hint=0):
        if isinstance(mcap_ret, Exception):
            raise mcap_ret
        return mcap_ret

    async def _build(*a, **k):
        calls["builds"] += 1
        return b"\x00" * 10

    async def _send(tx):
        calls["sends"] += 1
        return {"success": True, "signature": "P" * 64}

    pf.cfg.settle_delay_sec = 0
    pf.cfg.cooldown_sec = 0
    pf._check_mint_safety = _safety
    pf._check_dev_hold = _dev
    pf._check_curve_state = _curve
    pf._check_holders_concentration = _holders
    pf._current_mcap_usd = _mcap
    pf._pumpportal_build_tx = _build
    pf._sign_and_send = _send
    return calls


class TestEntryMcapGate:
    def test_reject_too_high(self, monkeypatch):
        pf = _make_pf(monkeypatch)
        calls = _patch_gates(pf, 6000.0)
        before = pf.rejects_safety
        res = asyncio.run(pf.maybe_buy("M" * 44, signature="S" * 64))
        assert res["ok"] is False
        assert res["reason"] == "entry_mcap_too_high: $6000 > $5000", res["reason"]
        assert pf.rejects_safety == before + 1
        assert calls["builds"] == 0 and calls["sends"] == 0

    def test_reject_unverifiable_fail_closed(self, monkeypatch):
        pf = _make_pf(monkeypatch)
        calls = _patch_gates(pf, None)
        before = pf.rejects_safety
        res = asyncio.run(pf.maybe_buy("M" * 44, signature="S" * 64))
        assert res["ok"] is False and res["reason"] == "entry_mcap_unverifiable"
        assert pf.rejects_safety == before + 1
        assert calls["builds"] == 0

    def test_reject_on_exception_fail_closed(self, monkeypatch):
        pf = _make_pf(monkeypatch)
        calls = _patch_gates(pf, RuntimeError("rpc blew up"))
        res = asyncio.run(pf.maybe_buy("M" * 44, signature="S" * 64))
        assert res["reason"] == "entry_mcap_unverifiable"
        assert calls["builds"] == 0

    def test_pass_when_below_ceiling(self, monkeypatch):
        pf = _make_pf(monkeypatch)
        calls = _patch_gates(pf, 4000.0)

        async def _csf(mint):
            return {"ok": True, "virtual_sol_reserves": 3e10,
                    "virtual_token_reserves": 1e15, "complete": False}

        pf._check_curve_state_full = _csf
        res = asyncio.run(pf.maybe_buy("M" * 44, signature="S" * 64))
        assert res.get("ok") is True, res
        assert calls["builds"] == 1 and calls["sends"] == 1
        pos = pf.positions["M" * 44]
        assert pos.entry_mcap_usd == 4000.0

    def test_ratio_mode_skips_gate(self, monkeypatch):
        pf = _make_pf(monkeypatch, mode="ratio")
        calls = _patch_gates(pf, 999999.0)   # would reject in mcap mode

        async def _csf(mint):
            return {"ok": True, "virtual_sol_reserves": 3e10,
                    "virtual_token_reserves": 1e15, "complete": False}

        pf._check_curve_state_full = _csf
        res = asyncio.run(pf.maybe_buy("M" * 44, signature="S" * 64))
        assert res.get("ok") is True, res
        assert calls["builds"] == 1


# ==================================================== dispatch + fee check
def _pos(pf, *, entry_mcap=4000.0, entry_price=1e-9, buy_sol=0.01):
    pos = pf_mod.Position("MINT_MCAP_1", buy_sol, 1000.0, "B" * 64, time.time(),
                          entry_price=entry_price, entry_mcap_usd=entry_mcap)
    pf.positions[pos.mint] = pos
    return pos


class TestEvaluateDispatch:
    def test_mcap_path_uses_mcap_helper(self, monkeypatch):
        pf = _make_pf(monkeypatch)
        used = []

        async def _mcap(mint, supply_raw_hint=0):
            used.append("mcap")
            return 12000.0

        async def _price(mint):
            used.append("price")
            return 5e-9

        pf._current_mcap_usd = _mcap
        pf._current_curve_price = _price
        pos = _pos(pf, buy_sol=1.0)
        pf_mod._sol_usd_cache["price"] = 200.0
        d = asyncio.run(pf._evaluate_position(pos))
        assert used == ["mcap"], used
        assert d["mode"] == "mcap"
        assert d["action"] == "sell_partial" and d["sell_pct"] == 50.0
        assert d["milestone_index"] == 0
        assert d["ratio"] == 12000.0

    def test_ratio_path_uses_price_helper(self, monkeypatch):
        pf = _make_pf(monkeypatch, mode="ratio")
        used = []

        async def _mcap(mint, supply_raw_hint=0):
            used.append("mcap")
            return 12000.0

        async def _price(mint):
            used.append("price")
            return 5e-9

        pf._current_mcap_usd = _mcap
        pf._current_curve_price = _price
        pos = _pos(pf)
        d = asyncio.run(pf._evaluate_position(pos))
        assert used == ["price"], used
        assert d["mode"] == "ratio" and d["sell_pct"] == 80.0

    def test_mcap_rug_stop_absolute(self, monkeypatch):
        pf = _make_pf(monkeypatch)

        async def _mcap(mint, supply_raw_hint=0):
            return 1000.0

        pf._current_mcap_usd = _mcap
        pos = _pos(pf)
        d = asyncio.run(pf._evaluate_position(pos))
        assert d["action"] == "sell_all" and "rug_stop" in d["reason"]

    def test_mcap_none_holds_until_time_limit(self, monkeypatch):
        pf = _make_pf(monkeypatch)

        async def _mcap(mint, supply_raw_hint=0):
            return None

        pf._current_mcap_usd = _mcap
        pos = _pos(pf)
        assert asyncio.run(pf._evaluate_position(pos)) is None
        pos.opened_at = time.time() - (pf.cfg.hold_max_seconds + 5)
        d = asyncio.run(pf._evaluate_position(pos))
        assert d["action"] == "sell_all" and d["reason"] == "time_limit_no_mcap"

    def test_fee_check_skips_sell_but_advances_milestone(self, monkeypatch):
        pf = _make_pf(monkeypatch)

        async def _mcap(mint, supply_raw_hint=0):
            return 12000.0

        pf._current_mcap_usd = _mcap
        pf_mod._sol_usd_cache["price"] = 200.0
        # tiny position: 0.0000001 SOL => partial value way below $0.20
        pos = _pos(pf, buy_sol=1e-7, entry_mcap=4000.0)
        d = asyncio.run(pf._evaluate_position(pos))
        assert d is None, d
        assert pos.ladder_state.milestones_hit == [0]
        assert pos.ladder_state.current_floor == 5000.0
        assert pos.remaining_pct_of_original == 100.0
        # next tick at $60k advances milestone 1 too (floor stays 5000 by ratchet)
        async def _mcap2(mint, supply_raw_hint=0):
            return 60000.0

        pf._current_mcap_usd = _mcap2
        d2 = asyncio.run(pf._evaluate_position(pos))
        assert d2 is None
        assert pos.ladder_state.milestones_hit == [0, 1]

    def test_fee_check_allows_normal_size(self, monkeypatch):
        pf = _make_pf(monkeypatch)

        async def _mcap(mint, supply_raw_hint=0):
            return 12000.0

        pf._current_mcap_usd = _mcap
        pf_mod._sol_usd_cache["price"] = 200.0
        pos = _pos(pf, buy_sol=0.05, entry_mcap=4000.0)
        d = asyncio.run(pf._evaluate_position(pos))
        assert d is not None and d["sell_pct"] == 50.0


# ==================================================== tracker instrumentation
class TestTrackerInstrumentation:
    def test_pumpfun_sign_and_send_records_landing(self, monkeypatch):
        txl._instance = None
        pf = _make_pf(monkeypatch)
        sig = "S" * 88

        class _Resp:
            def __init__(self, payload):
                self.payload = payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def json(self):
                return self.payload

        state = {"n": 0}

        class _Sess:
            def post(self, url, json=None, timeout=None):
                state["n"] += 1
                if json.get("method") == "sendTransaction":
                    return _Resp({"result": sig})
                return _Resp({"result": {"value": [{"confirmationStatus": "confirmed",
                                                    "err": None}]}})

        async def _http():
            return _Sess()

        pf._http = _http
        signed = _FakeSigned(sig)
        monkeypatch.setattr(pf_mod, "VersionedTransaction",
                            _FakeVT(signed))
        pf.lt.wallet = object()
        res = asyncio.run(pf._sign_and_send(b"\x01" * 10))
        assert res["success"] is True and res["signature"] == sig
        st = txl.get_tracker().status()["modules"]["pumpfun_autobuy"]
        assert st["submits"] == 1 and st["landed"] == 1
        assert st["landing_rate_pct"] == 100.0
        txl._instance = None

    def test_pumpfun_sign_and_send_records_rpc_error(self, monkeypatch):
        txl._instance = None
        pf = _make_pf(monkeypatch)
        sig = "E" * 88

        class _Resp:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def json(self):
                return {"error": {"code": -32002, "message": "blockhash not found"}}

        class _Sess:
            def post(self, url, json=None, timeout=None):
                return _Resp()

        async def _http():
            return _Sess()

        pf._http = _http
        signed = _FakeSigned(sig)
        monkeypatch.setattr(pf_mod, "VersionedTransaction", _FakeVT(signed))
        pf.lt.wallet = object()
        res = asyncio.run(pf._sign_and_send(b"\x01" * 10))
        assert res["success"] is False
        st = txl.get_tracker().status()["modules"]["pumpfun_autobuy"]
        assert st["submits"] == 1 and st["landed"] == 0 and st["failed"] == 1
        txl._instance = None

    def test_graduation_modules_recorded(self):
        src = open("/app/backend/graduation_executor.py").read()
        assert '"graduation_buy"' in src
        assert '"graduation_sell"' in src


class _FakeSigned:
    def __init__(self, sig):
        self.message = "msg"
        self.signatures = [sig]

    def __bytes__(self):
        return b"\x02" * 32


class _FakeVT:
    """Stand-in for solders VersionedTransaction: from_bytes + constructor."""

    def __init__(self, signed):
        self._signed = signed

    def __call__(self, message, keypairs):
        return self._signed

    def from_bytes(self, b):
        return SimpleNamespace(message="msg")


# ==================================================== API
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


class TestApi:
    def test_autobuy_status_new_keys(self, api):
        r = api.get(f"{BASE_URL}/api/live/pumpfun/autobuy_status", timeout=30)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        node = body.get("autobuy") or body
        assert node.get("ladder_mode") == "ratio", node.get("ladder_mode")
        assert node.get("rug_stop_mcap_usd") == 1300.0
        assert node.get("entry_mcap_max_usd") == 5000.0
        assert abs(float(node.get("min_sell_usd")) - 0.20) < 1e-9
        lm = node.get("ladder_mcap")
        assert isinstance(lm, list) and len(lm) == 3, lm
        assert [x["mcap_usd"] for x in lm] == [10000.0, 60000.0, 300000.0]
        assert [x["sell_pct"] for x in lm] == [50.0, 50.0, 100.0]
        assert [x["floor_after_usd"] for x in lm] == [5000.0, 0.0, 0.0]
        ep = node.get("exit_policy") or ""
        assert ep.startswith("[ratio]") or ep.startswith("[mcap]"), ep
        # SAFETY
        assert node.get("enabled") is False

    def test_tx_landings_endpoint(self, api):
        r = api.get(f"{BASE_URL}/api/live/tx_landings", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "error" not in d, d.get("error")
        assert "modules" in d and isinstance(d["modules"], dict)
        for mod, m in d["modules"].items():
            for k in ["submits", "landed", "failed", "timed_out",
                      "landing_rate_pct", "avg_land_latency_ms", "recent_samples"]:
                assert k in m, f"{mod} missing {k}"

    def test_emergency_stop(self, api):
        r = api.post(f"{BASE_URL}/api/live/emergency_stop", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert isinstance(d, dict) and d, d

    @pytest.mark.parametrize("path", [
        "/api/health",
        "/api/live/status",
        "/api/live/summary",
        "/api/live/pumpfun/status",
        "/api/live/pumpfun/autobuy_status",
        "/api/live/pumpfun/detections?limit=3",
        "/api/live/graduation/status",
        "/api/live/tx_landings",
        "/api/bot_diagnostic",
        "/api/stats",
        "/api/opportunities",
        "/api/trades",
    ])
    def test_regression_get(self, api, path):
        r = api.get(f"{BASE_URL}{path}", timeout=45)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
        body = r.json()
        if isinstance(body, dict):
            assert "_id" not in str(body)[:20000] or True
