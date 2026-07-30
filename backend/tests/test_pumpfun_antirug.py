"""
Iteration 13 — Pump.fun anti-rug filter suite tests.

Covers:
  * module import + new constants / helpers exist
  * deterministic bonding-curve PDA + pool ATA derivation (known-vector)
  * new config keys + defaults
  * FAIL-CLOSED behaviour of every on-chain filter (no rpc / dead rpc)
  * maybe_buy() disabled-gate short-circuit (no network, no buy)
  * maybe_buy() rejects (never buys) when RPC is unreachable

SAFETY: no env flag is ever mutated. The only place cfg.enabled is forced True is on a
throw-away instance whose RPC points at a dead localhost port, so the very first
on-chain filter fails closed and the PumpPortal path is unreachable.
"""
import os
import sys
import asyncio

import pytest
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
KNOWN_CURVE_PDA = "2JUXSuq1A1EdBzZj757cXFYuALPxv6vee4X981ajpzo8"
KNOWN_CURVE_ATA = "7a7EGMd1moVtGsUJuJAgbaqW2zi7e91Phu7dakkFoHna"

DEAD_RPC = "http://127.0.0.1:1/"


# ---------------- module surface ----------------
class TestModuleSurface:
    def test_constants_exist(self):
        assert str(pa.PUMPFUN_PROGRAM_ID) == "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
        assert str(pa.TOKEN_PROGRAM) == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        assert str(pa.TOKEN_2022_PROGRAM) == "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
        assert str(pa.ATA_PROGRAM) == "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"

    def test_dangerous_t22_extension_set(self):
        expected = {
            "transferFeeConfig", "permanentDelegate", "defaultAccountState",
            "nonTransferable", "transferHook", "mintCloseAuthority",
        }
        assert expected.issubset(pa.DANGEROUS_T22_EXTENSIONS)

    @pytest.mark.parametrize("name", [
        "_check_holders_concentration", "_check_curve_state",
        "_bonding_curve_pda", "_bonding_curve_ata",
        "_check_mint_safety", "_check_dev_hold",
    ])
    def test_helpers_exist(self, name):
        assert callable(getattr(PumpFunAutoBuyer, name, None)), f"missing {name}"


# ---------------- PDA derivation ----------------
class TestPdaDerivation:
    @pytest.fixture(scope="class")
    def ab(self):
        return PumpFunAutoBuyer(db=None)

    def test_bonding_curve_pda_known_vector(self, ab):
        assert str(ab._bonding_curve_pda(KNOWN_MINT)) == KNOWN_CURVE_PDA

    def test_bonding_curve_ata_known_vector(self, ab):
        assert str(ab._bonding_curve_ata(KNOWN_MINT, False)) == KNOWN_CURVE_ATA

    def test_pda_deterministic(self, ab):
        assert ab._bonding_curve_pda(KNOWN_MINT) == ab._bonding_curve_pda(KNOWN_MINT)
        assert ab._bonding_curve_ata(KNOWN_MINT, False) == ab._bonding_curve_ata(KNOWN_MINT, False)

    def test_t22_ata_differs_from_spl_ata(self, ab):
        assert str(ab._bonding_curve_ata(KNOWN_MINT, True)) != KNOWN_CURVE_ATA

    def test_bad_mint_raises(self, ab):
        with pytest.raises(Exception):
            ab._bonding_curve_pda("not-a-pubkey")


# ---------------- config defaults ----------------
class TestConfigDefaults:
    def test_new_config_defaults(self):
        cfg = pa.AutoBuyConfig()
        assert cfg.max_top10_pct == 30.0
        assert cfg.max_holder_pct == 20.0
        assert cfg.min_curve_sol == 0.5
        assert cfg.reject_dangerous_t22 is True
        assert cfg.max_dev_hold_pct == 15.0
        assert cfg.require_authorities_revoked is True
        assert cfg.enabled is False

    def test_env_example_documents_new_keys(self):
        env = dotenv_values("/app/backend/.env.example")
        for k in ["PUMPFUN_MAX_TOP10_PCT", "PUMPFUN_MAX_HOLDER_PCT",
                  "PUMPFUN_MIN_CURVE_SOL", "PUMPFUN_REJECT_DANGEROUS_T22"]:
            assert k in env, f"{k} not documented in backend/.env.example"


# ---------------- fail-closed behaviour ----------------
def _instance_with_rpc(rpc_url):
    """Throw-away buyer whose live-trader is a stub (never mutate the real singleton)."""
    from types import SimpleNamespace
    ab = PumpFunAutoBuyer(db=None)
    ab.lt = SimpleNamespace(ready=False, cfg=SimpleNamespace(rpc_url=rpc_url),
                            wallet_pubkey=None, wallet=None)
    return ab


class TestFailClosedNoRpc:
    """Every on-chain filter must return ok=False when there is no RPC configured."""

    @pytest.fixture
    def ab(self):
        return _instance_with_rpc("")

    def test_mint_safety_fails_closed(self, ab):
        res = asyncio.run(ab._check_mint_safety(KNOWN_MINT))
        assert res.get("ok") is False and res.get("reason")
        assert res.get("authorities_safe") is not True

    def test_dev_hold_fails_closed(self, ab):
        res = asyncio.run(ab._check_dev_hold("sig", KNOWN_MINT, "1000000000"))
        assert res.get("ok") is False and res.get("reason")
        assert res.get("within_limit") is not True

    def test_curve_state_fails_closed(self, ab):
        res = asyncio.run(ab._check_curve_state(KNOWN_MINT))
        assert res.get("ok") is False and res.get("reason")
        assert res.get("liquidity_ok") is not True

    def test_holders_fails_closed(self, ab):
        res = asyncio.run(ab._check_holders_concentration(KNOWN_MINT, 1_000_000_000, False))
        assert res.get("ok") is False and res.get("reason")
        assert res.get("top1_within_limit") is not True
        assert res.get("top10_within_limit") is not True

    def test_holders_fails_closed_on_zero_supply(self):
        ab = _instance_with_rpc("http://example.invalid/")
        res = asyncio.run(ab._check_holders_concentration(KNOWN_MINT, 0, False))
        assert res.get("ok") is False


class TestFailClosedDeadRpc:
    """Unreachable RPC -> exception path must also fail closed, never ok=True."""

    @pytest.fixture(scope="class")
    def ab(self):
        return _instance_with_rpc(DEAD_RPC)

    @pytest.mark.parametrize("coro_name,args", [
        ("_check_mint_safety", (KNOWN_MINT,)),
        ("_check_dev_hold", ("5" * 64, KNOWN_MINT, "1000000000")),
        ("_check_curve_state", (KNOWN_MINT,)),
        ("_check_holders_concentration", (KNOWN_MINT, 1_000_000_000, False)),
    ])
    def test_dead_rpc_fails_closed(self, ab, coro_name, args):
        res = asyncio.run(getattr(ab, coro_name)(*args))
        assert res.get("ok") is False, f"{coro_name} returned ok=True with dead RPC: {res}"
        assert isinstance(res.get("reason"), str) and res["reason"]


# ---------------- maybe_buy gating ----------------
class TestMaybeBuyGate:
    def test_disabled_gate_short_circuits(self):
        ab = PumpFunAutoBuyer(db=None)
        assert ab.cfg.enabled is False
        called = {"n": 0}

        async def _boom(*a, **k):
            called["n"] += 1
            raise AssertionError("PumpPortal must not be called")

        ab._pumpportal_build_tx = _boom
        res = asyncio.run(ab.maybe_buy(KNOWN_MINT, "sig"))
        assert res["ok"] is False
        assert "auto-buy disabled" in res["reason"]
        assert ab.buys_fired == 0
        assert ab.attempts == 1
        assert called["n"] == 0

    def test_dead_rpc_causes_reject_not_buy(self):
        """Forced-enabled throw-away instance with dead RPC: must reject on the
        first fail-closed filter and never reach the PumpPortal build step."""
        from types import SimpleNamespace
        ab = PumpFunAutoBuyer(db=None)
        ab.cfg.enabled = True
        ab.cfg.settle_delay_sec = 0
        ab.cfg.cooldown_sec = 0
        # stub live-trader: "ready" but pointed at a dead RPC (env untouched)
        ab.lt = SimpleNamespace(ready=True, cfg=SimpleNamespace(rpc_url=DEAD_RPC),
                                wallet_pubkey=None, wallet=None)

        async def _boom(*a, **k):
            raise AssertionError("PumpPortal must not be called when filters fail closed")

        ab._pumpportal_build_tx = _boom
        res = asyncio.run(ab.maybe_buy(KNOWN_MINT, "5" * 64))
        assert res["ok"] is False, res
        assert ab.buys_fired == 0
        assert ab.rejects_safety >= 1
        assert "safety_fail" in res["reason"] or "curve_read_fail" in res["reason"]

    def test_invalid_mint_rejected(self):
        ab = PumpFunAutoBuyer(db=None)
        res = asyncio.run(ab.maybe_buy("abc"))
        assert res["ok"] is False
        assert ab.buys_fired == 0


# ---------------- API surface for new keys ----------------
class TestAutobuyStatusNewKeys:
    @pytest.fixture(scope="class")
    def cfg(self):
        import requests
        r = requests.get(f"{BASE_URL}/api/live/pumpfun/autobuy_status", timeout=30)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert "error" not in body, body.get("error")
        return body

    def test_new_filter_keys_present_with_defaults(self, cfg):
        c = cfg["config"]
        assert c["max_top10_pct"] == 30.0
        assert c["max_holder_pct"] == 20.0
        assert c["min_curve_sol"] == 0.5
        assert c["reject_dangerous_t22"] is True
        assert c["max_dev_hold_pct"] == 15.0
        assert c["require_authorities_revoked"] is True

    def test_existing_keys_intact(self, cfg):
        assert cfg["tp_sl_enforced"] is False
        assert cfg["execution_backend"] == "pumpportal_local_tx + quicknode_rpc"
        assert cfg["enabled"] is False
        assert cfg["counters"]["buys_fired"] == 0

    def test_holder_limits_are_sane(self, cfg):
        c = cfg["config"]
        assert c["max_holder_pct"] <= c["max_top10_pct"], "top-1 limit must be <= top-10 limit"
