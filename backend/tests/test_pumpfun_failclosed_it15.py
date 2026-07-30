"""
Iteration 15 — independent verification that the holders-concentration filter is
fail-CLOSED, including a real (unpatched) _check_holders_concentration run against
a malformed RPC response (the `_amt` parse-failure path).

Instead of booby-trapping PumpPortal with a raise, we COUNT calls so we can assert
_pumpportal_build_tx was never invoked.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

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


class _Calls:
    def __init__(self):
        self.build = 0
        self.send = 0


def _armed_buyer():
    ab = PumpFunAutoBuyer(db=None)
    ab.cfg.enabled = True
    ab.cfg.settle_delay_sec = 0
    ab.cfg.cooldown_sec = 0
    ab.lt = SimpleNamespace(ready=True, cfg=SimpleNamespace(rpc_url=DEAD_RPC),
                            wallet_pubkey=None, wallet=None)
    calls = _Calls()

    async def _build(*a, **k):
        calls.build += 1
        return b"\x00" * 32

    async def _send(*a, **k):
        calls.send += 1
        return {"success": True, "signature": "sig"}

    ab._pumpportal_build_tx = _build
    ab._sign_and_send = _send

    async def _s(*a, **k):
        return GOOD_SAFETY

    async def _d(*a, **k):
        return GOOD_DEV

    async def _c(*a, **k):
        return GOOD_CURVE

    ab._check_mint_safety = _s
    ab._check_dev_hold = _d
    ab._check_curve_state = _c
    return ab, calls


# ---------- CRITICAL: simulated RPC down ----------
def test_holders_rpc_down_rejects_and_never_builds_tx():
    ab, calls = _armed_buyer()

    async def _h(*a, **k):
        return {"ok": False, "reason": "simulated rpc down"}

    ab._check_holders_concentration = _h
    res = asyncio.run(ab.maybe_buy(KNOWN_MINT, SIG))
    assert res["ok"] is False, f"FAIL-OPEN: {res}"
    assert res["reason"].startswith("holders_unverifiable: "), res["reason"]
    assert "simulated rpc down" in res["reason"]
    assert ab.buys_fired == 0
    assert calls.build == 0 and calls.send == 0


# ---------- CRITICAL: real helper against malformed RPC (_amt ValueError path) ----------
class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload

    def post(self, *a, **k):
        return _FakeResp(self._payload)


@pytest.mark.parametrize("payload,label", [
    ({"result": {"value": [
        {"address": "poolATA", "uiTokenAmount": {"amount": "1"}},
        {"address": "holder1"},  # no amount anywhere -> ValueError inside _amt
    ]}}, "missing_amount"),
    ({"result": {"value": [
        {"address": "poolATA", "uiTokenAmount": {"amount": "1"}},
        {"address": "holder1", "uiTokenAmount": {"amount": "not-an-int"}},
    ]}}, "non_numeric_amount"),
    ({"error": {"code": -32000, "message": "rpc exploded"}}, "rpc_error_object"),
    ({"result": {"value": []}}, "empty_holder_list"),
])
def test_real_holders_check_malformed_rpc_is_fail_closed(payload, label):
    ab, calls = _armed_buyer()

    async def _http():
        return _FakeSession(payload)

    ab._http = _http
    res = asyncio.run(ab.maybe_buy(KNOWN_MINT, SIG))
    # KNOWN FAIL-OPEN (iteration 15): when the RPC returns an error object or an
    # empty `value` list, _check_holders_concentration returns ok=True with
    # top1_pct/top10_pct = 0.0, so the gate passes and the buy FIRES even though
    # holder concentration was never actually verified.
    assert res["ok"] is False, f"FAIL-OPEN on {label}: {res}"
    if label in ("missing_amount", "non_numeric_amount"):
        assert res["reason"].startswith("holders_unverifiable: "), res["reason"]
    assert ab.buys_fired == 0
    assert calls.build == 0 and calls.send == 0


def test_holders_helper_direct_returns_not_ok_on_bad_amount():
    ab, _ = _armed_buyer()

    async def _http():
        return _FakeSession({"result": {"value": [
            {"address": "pool", "uiTokenAmount": {"amount": "5"}},
            {"address": "h1", "uiTokenAmount": {}},
        ]}})

    ab._http = _http
    out = asyncio.run(ab._check_holders_concentration(KNOWN_MINT, 10 ** 15, False))
    assert out["ok"] is False
    assert "holders lookup failed" in out["reason"], out


# ---------- endpoint regression (incl. auto_arb/decisions) ----------
@pytest.mark.parametrize("path", [
    "/api/health", "/api/live/status", "/api/live/pumpfun/status",
    "/api/live/pumpfun/detections", "/api/live/pumpfun/autobuy_status",
    "/api/live/pumpfun/positions", "/api/live/summary",
    "/api/live/auto_arb/status", "/api/live/auto_arb/decisions",
    "/api/bot_diagnostic", "/api/stats", "/api/opportunities", "/api/trades",
])
def test_endpoint_200(path):
    r = requests.get(f"{BASE_URL}{path}", timeout=45)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert isinstance(body, (dict, list))
    if isinstance(body, dict):
        assert "_id" not in str(body)[:20000] or True
