"""
Iteration 10 tests — pump.fun-graduated meme token support (BONK/WIF/POPCAT/PNUT).

Modules under test:
  * live_trader: MINTS / DECIMALS / PRICE_HINTS_USD / WHITELISTED_PAIRS
  * live_arb_monitor.ArbMonitorConfig: AUTO_ARB_PAIRS env override + defaults
  * live_arb_monitor.LiveArbMonitor._evaluate_pair: PRICE_HINTS_USD sizing + skip path
  * API: GET /api/live/status (whitelisted_pairs), GET /api/live/auto_arb/status (config.pairs)
"""
import os
import sys
import asyncio
import importlib
import inspect

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

fe_env = dotenv_values("/app/frontend/.env")
BASE_URL = (fe_env.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL missing from /app/frontend/.env"

MEMES = ["BONK", "WIF", "POPCAT", "PNUT"]
ALL_TOKENS = ["SOL", "USDC", "USDT", "JUP", "JitoSOL", "mSOL"] + MEMES


@pytest.fixture(scope="module")
def lt_mod():
    import live_trader
    return importlib.reload(live_trader) if False else live_trader


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- module: live_trader MINTS ----------

def test_mints_has_exactly_10_entries(lt_mod):
    assert len(lt_mod.MINTS) == 10, f"expected 10 mints, got {sorted(lt_mod.MINTS)}"
    assert sorted(lt_mod.MINTS.keys()) == sorted(ALL_TOKENS)


@pytest.mark.parametrize("sym,mint", [
    ("BONK", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"),
    ("WIF", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"),
    ("POPCAT", "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"),
    ("PNUT", "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump"),
])
def test_meme_mint_addresses_exact(lt_mod, sym, mint):
    assert lt_mod.MINTS[sym] == mint


def test_legacy_mints_unchanged(lt_mod):
    assert lt_mod.MINTS["SOL"] == "So11111111111111111111111111111111111111112"
    assert lt_mod.MINTS["USDC"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    assert lt_mod.MINTS["USDT"] == "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    assert lt_mod.MINTS["JUP"] == "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"


def test_all_mints_are_valid_base58_pubkeys(lt_mod):
    from solders.pubkey import Pubkey
    for sym, mint in lt_mod.MINTS.items():
        Pubkey.from_string(mint)  # raises if invalid


# ---------- module: live_trader DECIMALS ----------

@pytest.mark.parametrize("sym,dec", [("BONK", 5), ("WIF", 6), ("POPCAT", 9), ("PNUT", 6)])
def test_meme_decimals(lt_mod, sym, dec):
    assert lt_mod.DECIMALS[sym] == dec


def test_decimals_cover_every_mint(lt_mod):
    missing = [s for s in lt_mod.MINTS if s not in lt_mod.DECIMALS]
    assert not missing, f"DECIMALS missing: {missing}"


# ---------- module: live_trader PRICE_HINTS_USD ----------

def test_price_hints_exists_and_covers_all_10(lt_mod):
    hints = lt_mod.PRICE_HINTS_USD
    assert isinstance(hints, dict)
    missing = [s for s in ALL_TOKENS if s not in hints]
    assert not missing, f"PRICE_HINTS_USD missing: {missing}"
    assert len(hints) == 10


def test_price_hints_all_positive_floats(lt_mod):
    for sym, v in lt_mod.PRICE_HINTS_USD.items():
        assert isinstance(v, (int, float)) and v > 0, f"{sym} hint invalid: {v}"


def test_price_hints_stables_are_one(lt_mod):
    assert lt_mod.PRICE_HINTS_USD["USDC"] == 1.0
    assert lt_mod.PRICE_HINTS_USD["USDT"] == 1.0


def test_price_hints_meme_sizing_produces_nonzero_base_units(lt_mod):
    """$1 of each meme must convert to > 0 base units (guards decimals/hint mismatch)."""
    for sym in MEMES:
        base = int((1.0 / lt_mod.PRICE_HINTS_USD[sym]) * (10 ** lt_mod.DECIMALS[sym]))
        assert base > 0, f"{sym} -> {base} base units for $1"


# ---------- module: live_trader WHITELISTED_PAIRS ----------

def test_whitelist_has_13_pairs(lt_mod):
    assert len(lt_mod.WHITELISTED_PAIRS) == 13, sorted(lt_mod.WHITELISTED_PAIRS)


def test_whitelist_contains_meme_pairs_both_directions(lt_mod):
    for sym in MEMES:
        assert f"{sym}/USDC" in lt_mod.WHITELISTED_PAIRS
        assert f"USDC/{sym}" in lt_mod.WHITELISTED_PAIRS


def test_whitelist_keeps_original_5(lt_mod):
    for p in ["SOL/USDC", "JitoSOL/SOL", "mSOL/SOL", "USDC/USDT", "JUP/USDC"]:
        assert p in lt_mod.WHITELISTED_PAIRS


def test_whitelist_symbols_all_known(lt_mod):
    for pair in lt_mod.WHITELISTED_PAIRS:
        a, b = pair.split("/")
        assert a in lt_mod.MINTS and b in lt_mod.MINTS, pair


# ---------- API: GET /api/live/status ----------

def test_api_live_status_returns_13_whitelisted_pairs(api):
    r = api.get(f"{BASE_URL}/api/live/status", timeout=30)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    data = r.json()
    pairs = data.get("whitelisted_pairs")
    assert isinstance(pairs, list)
    assert len(pairs) == 13, pairs
    for sym in MEMES:
        assert f"{sym}/USDC" in pairs and f"USDC/{sym}" in pairs


# ---------- API: GET /api/live/auto_arb/status ----------

def test_api_auto_arb_status_default_pairs(api):
    r = api.get(f"{BASE_URL}/api/live/auto_arb/status", timeout=30)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    data = r.json()
    assert "error" not in data, data.get("error")
    pairs = data["config"]["pairs"]
    assert pairs == [
        "USDC->SOL->USDC", "USDC->JUP->USDC", "USDC->BONK->USDC",
        "USDC->WIF->USDC", "USDC->POPCAT->USDC", "USDC->PNUT->USDC",
    ], pairs


# ---------- module: ArbMonitorConfig AUTO_ARB_PAIRS ----------

def _fresh_config(env_value):
    """Reload live_arb_monitor with AUTO_ARB_PAIRS set/unset and return a config."""
    prev = os.environ.get("AUTO_ARB_PAIRS")
    try:
        if env_value is None:
            os.environ.pop("AUTO_ARB_PAIRS", None)
        else:
            os.environ["AUTO_ARB_PAIRS"] = env_value
        import live_arb_monitor
        mod = importlib.reload(live_arb_monitor)
        return mod.ArbMonitorConfig()
    finally:
        if prev is None:
            os.environ.pop("AUTO_ARB_PAIRS", None)
        else:
            os.environ["AUTO_ARB_PAIRS"] = prev
        import live_arb_monitor
        importlib.reload(live_arb_monitor)


def test_config_defaults_when_env_unset():
    cfg = _fresh_config(None)
    assert cfg.pairs == [("USDC", "SOL"), ("USDC", "JUP"), ("USDC", "BONK"),
                         ("USDC", "WIF"), ("USDC", "POPCAT"), ("USDC", "PNUT")]


def test_config_defaults_when_env_empty_string():
    cfg = _fresh_config("   ")
    assert len(cfg.pairs) == 6


def test_config_env_override_two_pairs():
    cfg = _fresh_config("USDC:SOL,USDC:BONK")
    assert cfg.pairs == [("USDC", "SOL"), ("USDC", "BONK")], cfg.pairs


def test_config_env_override_tolerates_whitespace_and_bad_specs():
    cfg = _fresh_config(" USDC : WIF , garbage , USDC:PNUT ")
    assert cfg.pairs == [("USDC", "WIF"), ("USDC", "PNUT")], cfg.pairs


def test_config_env_override_all_invalid_gives_empty_list():
    cfg = _fresh_config("junk,also-junk")
    assert cfg.pairs == [], cfg.pairs


# ---------- code inspection: PRICE_HINTS_USD used in _evaluate_pair ----------

def test_evaluate_pair_uses_price_hints_and_no_hardcoded_branches():
    import live_arb_monitor
    src = inspect.getsource(live_arb_monitor.LiveArbMonitor._evaluate_pair)
    assert "PRICE_HINTS_USD.get(start_sym)" in src
    # no per-symbol if/elif sizing branches left
    assert 'start_sym == "USDC"' not in src and "start_sym == 'USDC'" not in src
    # 150.0 may only appear as the .get() fallback default, never as a direct multiplier
    assert "fee_sol * 150.0" not in src, "hardcoded SOL price still multiplied in _evaluate_pair"


def test_pnl_fee_conversion_uses_price_hints_for_sol():
    import live_arb_monitor
    src = inspect.getsource(live_arb_monitor.LiveArbMonitor._evaluate_pair)
    assert 'fee_sol * PRICE_HINTS_USD.get("SOL"' in src


# ---------- behaviour: unsupported token -> skipped decision ----------

class _DummyDB:
    def __init__(self):
        self.arb_decisions = self

    async def insert_one(self, doc):
        return None


def _monitor():
    import live_arb_monitor
    cfg = live_arb_monitor.ArbMonitorConfig()
    return live_arb_monitor.LiveArbMonitor(cfg, _DummyDB())


def test_evaluate_pair_skips_when_no_price_hint():
    mon = _monitor()
    dec = asyncio.run(mon._evaluate_pair("FAKECOIN", "USDC"))
    assert dec is not None
    assert dec["verdict"] == "skipped", dec
    assert "no price hint for FAKECOIN" in dec["reason"], dec


def test_evaluate_pair_meme_sizing_reaches_quote_stage(monkeypatch):
    """With a mocked Jupiter quote, a meme pair should size correctly and skip on low profit."""
    mon = _monitor()

    calls = []

    async def fake_get_quote(in_mint, out_mint, amount, slippage_bps):
        calls.append((in_mint, out_mint, amount))
        return {"outAmount": str(int(amount * 0.999)), "priceImpactPct": "0.001"}

    monkeypatch.setattr(mon.lt.jupiter, "get_quote", fake_get_quote)
    monkeypatch.setattr(type(mon.lt), "ready", property(lambda self: True), raising=False)

    dec = asyncio.run(mon._evaluate_pair("USDC", "BONK"))
    assert dec["verdict"] == "skipped", dec
    assert "below threshold" in dec["reason"], dec
    assert len(calls) == 2
    import live_trader
    assert calls[0][1] == live_trader.MINTS["BONK"]
    # $1 of USDC at hint 1.0 with 6 decimals = 1_000_000 base units
    assert calls[0][2] == int(mon.cfg.trade_size_usd * 1_000_000)
