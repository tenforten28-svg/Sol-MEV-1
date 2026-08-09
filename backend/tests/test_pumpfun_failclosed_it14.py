"""
Iteration 14 — verify the 3 CRITICAL fail-open bugs from iteration 13 are closed,
plus the 2 minor fixes (min_curve_sol default, defaultAccountState state-aware check).

All tests use a throw-away PumpFunAutoBuyer with a stubbed live-trader and patched
on-chain helpers. The real singleton / .env are never mutated and PumpPortal is
booby-trapped so any buy attempt raises.
"""
import os
import sys
import asyncio
from types import SimpleNamespace

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

import pumpfun_autobuy as pa  # noqa: E402
from pumpfun_autobuy import PumpFunAutoBuyer  # noqa: E402

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

KNOWN_MINT = "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump"
DEAD_RPC = "http://127.0.0.1:1/"
SIG = "5" * 64

GOOD_SAFETY = {
    "ok": True, "mint_authority_revoked": True, "freeze_authority_revoked": True,
    "authorities_safe": True, "decimals": 6, "supply": "1000000000000000",
    "is_token_2022": False, "dangerous_extensions": [], "extensions_safe": True,
}
GOOD_DEV = {"ok": True, "dev_hold_pct": 1.0, "within_limit": True}
GOOD_CURVE = {"ok": True, "complete": False, "liquidity_ok": True, "real_sol_reserves": 5.0}
GOOD_HOLDERS = {"ok": True, "top1_pct": 5.0, "top10_pct": 20.0,
                "top1_within_limit": True, "top10_within_limit": True}


def _armed_buyer():
    ab = PumpFunAutoBuyer(db=None)
    ab.cfg.enabled = True
    ab.cfg.settle_delay_sec = 0
    ab.cfg.cooldown_sec = 0
    ab.lt = SimpleNamespace(ready=True, cfg=SimpleNamespace(rpc_url=DEAD_RPC),
                            wallet_pubkey=None, wallet=None)

    async def _boom(*a, **k):
        raise AssertionError("PumpPortal must not be reached when a filter cannot verify")

    ab._pumpportal_build_tx = _boom
    ab._sign_and_send = _boom
    return ab


def _patch(ab, safety=GOOD_SAFETY, dev=GOOD_DEV, curve=GOOD_CURVE, holders=GOOD_HOLDERS):
    async def _s(*a, **k):
        return safety

    async def _d(*a, **k):
        return dev

    async def _c(*a, **k):
        return curve

    async def _h(*a, **k):
        return holders

    ab._check_mint_safety = _s
    ab._check_dev_hold = _d
    ab._check_curve_state = _c
    ab._check_holders_concentration = _h
    return ab


# ---------- CRITICAL 1: holders concentration fail-closed ----------
class TestHoldersFailClosed:
    def test_holders_unverifiable_rejects(self):
        ab = _patch(_armed_buyer(), holders={"ok": False, "reason": "holders lookup failed: boom"})
        res = asyncio.run(ab.maybe_buy(KNOWN_MINT, SIG))
        assert res["ok"] is False, f"FAIL-OPEN: buy proceeded despite unverifiable holders: {res}"
        assert "holders_unverifiable" in res["reason"], res["reason"]
        assert ab.buys_fired == 0

    def test_holders_over_limit_still_rejects(self):
        ab = _patch(_armed_buyer(), holders={**GOOD_HOLDERS, "top1_within_limit": False, "top1_pct": 90.0})
        res = asyncio.run(ab.maybe_buy(KNOWN_MINT, SIG))
        assert res["ok"] is False and "top1_holder_fail" in res["reason"]


# ---------- CRITICAL 2: dev-hold fail-closed + required signature ----------
class TestDevHoldFailClosed:
    def test_missing_signature_hard_rejects(self):
        ab = _patch(_armed_buyer())
        assert ab.cfg.max_dev_hold_pct < 100.0
        res = asyncio.run(ab.maybe_buy(KNOWN_MINT, None))
        assert res["ok"] is False
        assert res["reason"].startswith("dev_hold_unknown"), res["reason"]
        assert "no detection signature" in res["reason"]
        assert ab.buys_fired == 0

    def test_dev_hold_unverifiable_rejects(self):
        ab = _patch(_armed_buyer(), dev={"ok": False, "reason": "tx not found"})
        res = asyncio.run(ab.maybe_buy(KNOWN_MINT, SIG))
        assert res["ok"] is False
        assert "dev_hold_unverifiable" in res["reason"], res["reason"]
        assert ab.buys_fired == 0

    def test_dev_hold_retries_six_times(self):
        ab = _armed_buyer()
        calls = {"n": 0}

        async def _dev(*a, **k):
            calls["n"] += 1
            return {"ok": False, "reason": "tx not found"}

        _patch(ab)
        ab._check_dev_hold = _dev
        # keep the retry sleep from slowing the suite
        real_sleep = asyncio.sleep

        async def _fast_sleep(sec, *a, **k):
            return await real_sleep(0)

        pa.asyncio.sleep = _fast_sleep
        try:
            res = asyncio.run(ab.maybe_buy(KNOWN_MINT, SIG))
        finally:
            pa.asyncio.sleep = real_sleep
        assert calls["n"] == 6, f"expected 6 dev-hold attempts, got {calls['n']}"
        assert res["ok"] is False and "dev_hold_unverifiable" in res["reason"]

    def test_dev_hold_retry_succeeds_on_second_attempt(self):
        ab = _armed_buyer()
        _patch(ab)
        calls = {"n": 0}

        async def _dev(*a, **k):
            calls["n"] += 1
            if calls["n"] < 2:
                return {"ok": False, "reason": "tx not found"}
            return GOOD_DEV

        ab._check_dev_hold = _dev
        real_sleep = asyncio.sleep

        async def _fast_sleep(sec, *a, **k):
            return await real_sleep(0)

        pa.asyncio.sleep = _fast_sleep
        try:
            res = asyncio.run(ab.maybe_buy(KNOWN_MINT, SIG))
        finally:
            pa.asyncio.sleep = real_sleep
        assert calls["n"] == 2
        # dev-hold passed -> the flow continues; PumpPortal is booby-trapped so
        # the only acceptable outcomes are a later filter reject or the build error.
        assert res["ok"] is False
        assert "dev_hold" not in res["reason"], res["reason"]


# ---------- CRITICAL 3: _amt strict parser ----------
class TestAmtStrict:
    def test_amt_raises_on_missing_amount(self):
        """_amt is a closure inside _check_holders_concentration; exercise it through
        the public helper with a patched HTTP layer returning a malformed entry."""
        ab = PumpFunAutoBuyer(db=None)
        ab.lt = SimpleNamespace(ready=True, cfg=SimpleNamespace(rpc_url="http://rpc.test/"),
                                wallet_pubkey=None, wallet=None)

        class _Resp:
            async def json(self):
                return {"result": {"value": [
                    {"address": "PoolAtaPlaceholder"},
                    {"address": "WhaleNoAmount", "uiTokenAmount": {"uiAmountString": "1234.56"}},
                ]}}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _Sess:
            def post(self, *a, **k):
                return _Resp()

        async def _http():
            return _Sess()

        ab._http = _http
        res = asyncio.run(ab._check_holders_concentration(KNOWN_MINT, 1_000_000_000, False))
        assert res.get("ok") is False, f"expected fail-closed, got {res}"
        assert "holders lookup failed" in str(res.get("reason")), res
        assert res.get("top1_within_limit") is not True

    def test_amt_parse_failure_rejects_buy(self):
        ab = _patch(_armed_buyer(), holders={"ok": False, "reason": "holders lookup failed: holder entry has no amount"})
        res = asyncio.run(ab.maybe_buy(KNOWN_MINT, SIG))
        assert res["ok"] is False and "holders_unverifiable" in res["reason"], res["reason"]


# ---------- minor 1: min_curve_sol default ----------
class TestMinCurveSolDefault:
    def test_config_default_is_001(self):
        prev = os.environ.pop("PUMPFUN_MIN_CURVE_SOL", None)
        try:
            ab = PumpFunAutoBuyer(db=None)
            assert ab.cfg.min_curve_sol == 0.01, ab.cfg.min_curve_sol
        finally:
            if prev is not None:
                os.environ["PUMPFUN_MIN_CURVE_SOL"] = prev

    def test_env_example_documents_001(self):
        env = dotenv_values("/app/backend/.env.example")
        assert env.get("PUMPFUN_MIN_CURVE_SOL") == "0.01", env.get("PUMPFUN_MIN_CURVE_SOL")

    def test_api_reports_min_curve_sol(self):
        r = requests.get(f"{BASE_URL}/api/live/pumpfun/autobuy_status", timeout=30)
        assert r.status_code == 200, r.text[:300]
        cfg = r.json().get("config") or {}
        assert cfg.get("min_curve_sol") == 0.01, cfg


# ---------- minor 2: defaultAccountState is state-aware ----------
class TestDefaultAccountState:
    def _safety_with_ext(self, ext):
        ab = PumpFunAutoBuyer(db=None)
        ab.lt = SimpleNamespace(ready=True, cfg=SimpleNamespace(rpc_url="http://rpc.test/"),
                                wallet_pubkey=None, wallet=None)

        payload = {"result": {"value": {
            "owner": str(pa.TOKEN_2022_PROGRAM),
            "data": {"parsed": {"info": {
                "mintAuthority": None, "freezeAuthority": None,
                "decimals": 6, "supply": "1000", "extensions": [ext],
            }}},
        }}}

        class _Resp:
            async def json(self):
                return payload

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _Sess:
            def post(self, *a, **k):
                return _Resp()

        async def _http():
            return _Sess()

        ab._http = _http
        return asyncio.run(ab._check_mint_safety(KNOWN_MINT))

    def test_constant_no_longer_contains_default_account_state(self):
        assert "defaultAccountState" not in pa.DANGEROUS_T22_EXTENSIONS

    def test_initialized_state_is_safe(self):
        res = self._safety_with_ext({"extension": "defaultAccountState",
                                     "state": {"accountState": "Initialized"}})
        assert res.get("ok") is True, res
        assert res.get("extensions_safe") is True, res
        assert res.get("dangerous_extensions") == []

    @pytest.mark.parametrize("state", ["Frozen", "frozen", "FROZEN"])
    def test_frozen_state_is_dangerous(self, state):
        res = self._safety_with_ext({"extension": "defaultAccountState",
                                     "state": {"accountState": state}})
        assert res.get("ok") is True, res
        assert res.get("extensions_safe") is False, res
        assert res.get("dangerous_extensions") == ["defaultAccountState=Frozen"], res

    def test_other_dangerous_extension_still_flagged(self):
        res = self._safety_with_ext({"extension": "permanentDelegate"})
        assert res.get("extensions_safe") is False
        assert "permanentDelegate" in res.get("dangerous_extensions")


# ---------- gate short-circuit regression ----------
class TestDisabledGate:
    def test_disabled_short_circuits_before_any_filter(self):
        ab = PumpFunAutoBuyer(db=None)
        assert ab.cfg.enabled is False
        touched = {"n": 0}

        async def _tripwire(*a, **k):
            touched["n"] += 1
            raise AssertionError("no filter/RPC may be touched when auto-buy is disabled")

        for name in ("_check_mint_safety", "_check_dev_hold", "_check_curve_state",
                     "_check_holders_concentration", "_pumpportal_build_tx", "_sign_and_send"):
            setattr(ab, name, _tripwire)

        res = asyncio.run(ab.maybe_buy(KNOWN_MINT, SIG))
        assert res["ok"] is False
        assert "auto-buy disabled" in res["reason"]
        assert touched["n"] == 0
        assert ab.buys_fired == 0


# ---------- backend API regression ----------
class TestApiRegression:
    @pytest.mark.parametrize("path", [
        "/api/health", "/api/live/status", "/api/live/summary",
        "/api/live/pumpfun/status", "/api/live/pumpfun/detections",
        "/api/live/pumpfun/autobuy_status", "/api/live/pumpfun/positions",
        "/api/live/auto_arb/status", "/api/bot_diagnostic",
        "/api/stats", "/api/opportunities", "/api/trades",
    ])
    def test_endpoint_200(self, path):
        r = requests.get(f"{BASE_URL}{path}", timeout=45)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
        body = r.json()
        assert body is not None
        if isinstance(body, dict):
            assert "error" not in body or body.get("error") in (None, ""), f"{path} body error: {str(body)[:200]}"
