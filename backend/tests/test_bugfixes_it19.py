"""
Iteration 19 — production bug-fix verification.

BUG 1 (module: pumpfun_sniper)
  * _handle_log_notification now resolves candidate_mint via getTransaction
    (vanity 'pump' suffix, else accountKeys[1] fallback).
  * autobuy only dispatched when candidate_mint is truthy.
  * no http_url  -> extraction skipped, no crash, detection still recorded.

BUG 2 (module: graduation_executor)
  * sell failure counter + abandon-after-N + retry backoff + reset on success.
  * sell_failed record carries failure_count; abandoned record carries full context.

SAFETY: no live gates enabled. All RPC / swap calls are fakes.
"""
import asyncio
import os
import sys
import time
from types import SimpleNamespace

import aiohttp
import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

import pumpfun_sniper as sniper_mod  # noqa: E402
import graduation_executor as ge_mod  # noqa: E402

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

PUMP_MINT = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApump"      # 40 chars, ends with 'pump'
OTHER_KEY_0 = "1" * 44
OTHER_KEY_1 = "2" * 44
OTHER_KEY_2 = "3" * 44

CREATE_LOGS = [
    "Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [1]",
    "Program log: Instruction: Create",
]
SWAP_LOGS = [
    "Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [1]",
    "Program log: Instruction: Buy",
]


# ---------------- fake mongo ----------------
class _FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    async def to_list(self, n=None):
        return self.docs


class _FakeColl:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(doc)
        return SimpleNamespace(inserted_id="x")

    async def count_documents(self, q=None):
        return len(self.docs)

    def find(self, q=None):
        return _FakeCursor(list(self.docs))

    async def delete_many(self, q):
        return SimpleNamespace(deleted_count=0)

    async def create_index(self, *a, **k):
        return "idx"


class _FakeDB:
    def __init__(self):
        self.pumpfun_detections = _FakeColl()
        self.graduation_events = _FakeColl()
        self.graduation_positions = _FakeColl()
        self.trades = _FakeColl()


def _make_notification(logs, sig="SIG_IT19_" + "a" * 40, slot=99):
    return {
        "jsonrpc": "2.0",
        "method": "logsNotification",
        "params": {
            "result": {
                "context": {"slot": slot},
                "value": {"signature": sig, "err": None, "logs": logs},
            },
            "subscription": 1,
        },
    }


# ---------------- fake aiohttp session for getTransaction ----------------
class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSessionFactory:
    """Callable that mimics aiohttp.ClientSession() as async ctx manager."""

    def __init__(self, responses):
        # responses: list of payloads returned in order (last is repeated)
        self.responses = responses
        self.post_calls = []

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, url, json=None, timeout=None):
        self.post_calls.append({"url": url, "json": json})
        idx = min(len(self.post_calls) - 1, len(self.responses) - 1)
        return _FakeResp(self.responses[idx])


def _tx_payload(keys):
    return {"result": {"transaction": {"message": {"accountKeys": keys}}}}


def _make_sniper(monkeypatch, http_url="https://rpc.test/it19"):
    s = sniper_mod.PumpFunSniper(_FakeDB())
    s.http_url = http_url
    return s


def _patch_session(monkeypatch, factory):
    # NOTE: pumpfun_sniper re-imports aiohttp INSIDE the function, so the patch
    # must target the aiohttp module attribute itself.
    monkeypatch.setattr(aiohttp, "ClientSession", factory)


def _patch_autobuy(monkeypatch, calls):
    class _AB:
        async def maybe_buy(self, mint, signature=None):
            calls.append({"mint": mint, "signature": signature})
            return {"ok": True}

    mod = SimpleNamespace(get_pumpfun_autobuyer=lambda db: _AB())
    monkeypatch.setitem(sys.modules, "pumpfun_autobuy", mod)


# ================= BUG 1 =================
class TestBug1MintExtraction:
    @pytest.mark.asyncio
    async def test_pump_suffix_key_selected(self, monkeypatch):
        s = _make_sniper(monkeypatch)
        factory = _FakeSessionFactory([_tx_payload([OTHER_KEY_0, PUMP_MINT, OTHER_KEY_2])])
        _patch_session(monkeypatch, factory)
        calls = []
        _patch_autobuy(monkeypatch, calls)

        await s._handle_log_notification(_make_notification(CREATE_LOGS))
        await asyncio.sleep(0.05)

        doc = s.db.pumpfun_detections.docs[-1]
        assert doc["candidate_mint"] == PUMP_MINT
        assert doc["pumpfun_url"].endswith(PUMP_MINT)
        assert len(factory.post_calls) == 1
        assert factory.post_calls[0]["json"]["method"] == "getTransaction"
        # autobuy dispatched with resolved mint
        assert calls and calls[0]["mint"] == PUMP_MINT

    @pytest.mark.asyncio
    async def test_pump_suffix_found_even_when_not_index1(self, monkeypatch):
        s = _make_sniper(monkeypatch)
        keys = [{"pubkey": OTHER_KEY_0}, {"pubkey": OTHER_KEY_1}, {"pubkey": PUMP_MINT}]
        _patch_session(monkeypatch, _FakeSessionFactory([_tx_payload(keys)]))
        _patch_autobuy(monkeypatch, [])
        await s._handle_log_notification(_make_notification(CREATE_LOGS))
        assert s.db.pumpfun_detections.docs[-1]["candidate_mint"] == PUMP_MINT

    @pytest.mark.asyncio
    async def test_fallback_to_accountkeys_index1(self, monkeypatch):
        s = _make_sniper(monkeypatch)
        _patch_session(monkeypatch, _FakeSessionFactory(
            [_tx_payload([OTHER_KEY_0, OTHER_KEY_1, OTHER_KEY_2])]))
        _patch_autobuy(monkeypatch, [])
        await s._handle_log_notification(_make_notification(CREATE_LOGS))
        assert s.db.pumpfun_detections.docs[-1]["candidate_mint"] == OTHER_KEY_1

    @pytest.mark.asyncio
    async def test_retries_until_tx_indexed(self, monkeypatch):
        s = _make_sniper(monkeypatch)
        factory = _FakeSessionFactory([
            {"result": None},
            _tx_payload([OTHER_KEY_0, PUMP_MINT]),
        ])
        _patch_session(monkeypatch, factory)
        _patch_autobuy(monkeypatch, [])
        slept = []

        async def _fast_sleep(d):
            slept.append(d)

        monkeypatch.setattr(sniper_mod.asyncio, "sleep", _fast_sleep)
        await s._handle_log_notification(_make_notification(CREATE_LOGS))
        assert s.db.pumpfun_detections.docs[-1]["candidate_mint"] == PUMP_MINT
        assert len(factory.post_calls) == 2
        assert slept and slept[0] == 0.8

    @pytest.mark.asyncio
    async def test_tx_never_found_gives_none_and_no_autobuy(self, monkeypatch):
        s = _make_sniper(monkeypatch)
        factory = _FakeSessionFactory([{"result": None}])
        _patch_session(monkeypatch, factory)
        calls = []
        _patch_autobuy(monkeypatch, calls)

        async def _fast_sleep(d):
            return None

        monkeypatch.setattr(sniper_mod.asyncio, "sleep", _fast_sleep)
        await s._handle_log_notification(_make_notification(CREATE_LOGS))
        doc = s.db.pumpfun_detections.docs[-1]
        assert doc["candidate_mint"] is None
        assert doc["pumpfun_url"] is None
        assert len(factory.post_calls) == 3  # 3 retries
        assert calls == []  # no buy attempt on unknown mint

    @pytest.mark.asyncio
    async def test_rpc_exception_does_not_crash(self, monkeypatch):
        s = _make_sniper(monkeypatch)

        class _Boom:
            def __call__(self, *a, **k):
                return self

            async def __aenter__(self):
                raise RuntimeError("rpc down")

            async def __aexit__(self, *a):
                return False

        _patch_session(monkeypatch, _Boom())
        calls = []
        _patch_autobuy(monkeypatch, calls)
        await s._handle_log_notification(_make_notification(CREATE_LOGS))
        assert s.detections == 1
        assert s.db.pumpfun_detections.docs[-1]["candidate_mint"] is None
        assert calls == []

    @pytest.mark.asyncio
    async def test_no_http_url_skips_extraction_no_crash(self, monkeypatch):
        s = _make_sniper(monkeypatch, http_url="")

        def _boom(*a, **k):
            raise AssertionError("must not hit RPC without http_url")

        _patch_session(monkeypatch, _boom)
        calls = []
        _patch_autobuy(monkeypatch, calls)
        await s._handle_log_notification(_make_notification(CREATE_LOGS))
        assert s.total_events == 1
        assert s.detections == 1
        doc = s.db.pumpfun_detections.docs[-1]
        assert doc["candidate_mint"] is None
        assert doc["signature"] and doc["slot"] == 99
        assert calls == []

    @pytest.mark.asyncio
    async def test_non_create_log_ignored(self, monkeypatch):
        s = _make_sniper(monkeypatch)

        def _boom(*a, **k):
            raise AssertionError("must not hit RPC for non-create logs")

        _patch_session(monkeypatch, _boom)
        await s._handle_log_notification(_make_notification(SWAP_LOGS))
        assert s.total_events == 1
        assert s.detections == 0
        assert s.db.pumpfun_detections.docs == []

    def test_http_url_from_env(self, monkeypatch):
        monkeypatch.setenv("SOLANA_RPC_URL", "https://env.rpc.test/xyz")
        s = sniper_mod.PumpFunSniper(_FakeDB())
        assert s.http_url == "https://env.rpc.test/xyz"
        monkeypatch.delenv("SOLANA_RPC_URL", raising=False)
        monkeypatch.delenv("QUICKNODE_WSS_URL", raising=False)
        s2 = sniper_mod.PumpFunSniper(_FakeDB())
        assert s2.http_url == ""


# ================= BUG 2 =================
def _make_executor(monkeypatch, *, swap_results, quote_out_lamports=None):
    """Executor with a scripted execute_swap. swap_results = list of dicts."""
    seq = list(swap_results)
    calls = []

    async def _swap(a, b, amt):
        calls.append({"in": a, "out": b, "amount": amt})
        return seq.pop(0) if seq else {"success": False, "error": "exhausted"}

    async def _quote(inp, outp, amt, slip):
        if quote_out_lamports is None:
            raise RuntimeError("no route")
        return {"outAmount": str(quote_out_lamports)}

    fake_lt = SimpleNamespace(
        ready=True,
        cfg=SimpleNamespace(slippage_bps=100),
        execute_swap=_swap,
        jupiter=SimpleNamespace(get_quote=_quote),
    )
    monkeypatch.setattr(ge_mod, "get_live_trader", lambda: fake_lt)
    ex = ge_mod.GraduationExecutor(_FakeDB())
    ex.calls = calls
    return ex


def _open_position(ex, mint="9SP2" + "z" * 36 + "pump", tokens=1_000_000):
    pos = ge_mod.GraduationPosition(
        mint=mint, pool="POOL", source="pumpswap", buy_sol=0.003,
        tokens_out=tokens, buy_signature="BUYSIG", opened_at=time.time(),
    )
    ex.positions[mint] = pos
    return pos


SELL_DECISION = {"action": "sell_all", "sell_pct": 100.0, "reason": "rug_stop",
                 "ratio": 0.0212, "milestone_index": None}


class TestBug2SellRetry:
    def test_config_defaults(self):
        cfg = ge_mod.GraduationExecutorConfig()
        assert cfg.max_sell_failures == 5
        assert cfg.sell_retry_backoff_sec == 30

    def test_position_has_failure_fields(self):
        pos = ge_mod.GraduationPosition("M", "P", "pumpswap", 0.003, 10, "S", time.time())
        assert pos.sell_failures == 0
        assert pos.last_sell_attempt_at == 0.0

    @pytest.mark.asyncio
    async def test_failure_increments_and_records_failure_count(self, monkeypatch):
        ex = _make_executor(monkeypatch, swap_results=[{"success": False, "error": "no route"}])
        pos = _open_position(ex)
        before = time.time()
        await ex._sell(pos.mint, SELL_DECISION)
        assert pos.sell_failures == 1
        assert pos.last_sell_attempt_at >= before
        assert not pos.closed
        assert pos.mint in ex.positions
        ev = ex.db.graduation_positions.docs[-1]
        assert ev["event"] == "sell_failed"
        assert ev["failure_count"] == 1

    @pytest.mark.asyncio
    async def test_abandoned_after_max_failures(self, monkeypatch):
        ex = _make_executor(monkeypatch,
                            swap_results=[{"success": False, "error": "no route"}] * 5)
        pos = _open_position(ex)
        ex.cfg.max_sell_failures = 5
        for i in range(5):
            pos.last_sell_attempt_at = 0.0
            await ex._sell(pos.mint, SELL_DECISION)
        assert pos.sell_failures == 5
        assert pos.closed is True
        assert pos.mint not in ex.positions
        events = [d["event"] for d in ex.db.graduation_positions.docs]
        assert events.count("sell_failed") == 5
        assert events[-1] == "abandoned"
        ab = ex.db.graduation_positions.docs[-1]
        for k in ("reason", "last_error", "ratio", "buy_signature", "buy_sol",
                  "hold_seconds", "partial_sells"):
            assert k in ab, f"missing {k} in abandoned record"
        assert ab["last_error"] == "no route"
        assert ab["buy_signature"] == "BUYSIG"

    @pytest.mark.asyncio
    async def test_abandoned_mint_not_iterated_by_position_loop(self, monkeypatch):
        ex = _make_executor(monkeypatch,
                            swap_results=[{"success": False, "error": "no route"}] * 5)
        ex.cfg.max_sell_failures = 5
        ex.cfg.check_interval_sec = 0
        pos = _open_position(ex)
        for _ in range(5):
            pos.last_sell_attempt_at = 0.0
            await ex._sell(pos.mint, SELL_DECISION)
        assert ex.positions == {}

        evaluated = []

        async def _eval(p):
            evaluated.append(p.mint)
            return SELL_DECISION

        monkeypatch.setattr(ex, "_evaluate", _eval)
        task = asyncio.create_task(ex._position_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert evaluated == [], "abandoned mint must not be evaluated again"

    @pytest.mark.asyncio
    async def test_position_loop_skips_within_backoff(self, monkeypatch):
        ex = _make_executor(monkeypatch, swap_results=[])
        ex.cfg.check_interval_sec = 0
        ex.cfg.sell_retry_backoff_sec = 30
        pos = _open_position(ex)
        pos.sell_failures = 1
        pos.last_sell_attempt_at = time.time()

        evaluated = []

        async def _eval(p):
            evaluated.append(p.mint)
            return None

        monkeypatch.setattr(ex, "_evaluate", _eval)
        task = asyncio.create_task(ex._position_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert evaluated == [], "position inside backoff window must be skipped"

    @pytest.mark.asyncio
    async def test_position_loop_retries_after_backoff(self, monkeypatch):
        ex = _make_executor(monkeypatch, swap_results=[{"success": False, "error": "no route"}])
        ex.cfg.check_interval_sec = 0
        ex.cfg.sell_retry_backoff_sec = 30
        pos = _open_position(ex)
        pos.sell_failures = 1
        pos.last_sell_attempt_at = time.time() - 31

        evaluated = []

        async def _eval(p):
            evaluated.append(p.mint)
            return SELL_DECISION

        monkeypatch.setattr(ex, "_evaluate", _eval)
        task = asyncio.create_task(ex._position_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert pos.mint in evaluated
        assert pos.sell_failures >= 2, "retry after backoff should attempt the sell"

    @pytest.mark.asyncio
    async def test_no_backoff_skip_when_no_failures(self, monkeypatch):
        ex = _make_executor(monkeypatch, swap_results=[])
        ex.cfg.check_interval_sec = 0
        pos = _open_position(ex)
        evaluated = []

        async def _eval(p):
            evaluated.append(p.mint)
            return None

        monkeypatch.setattr(ex, "_evaluate", _eval)
        task = asyncio.create_task(ex._position_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert pos.mint in evaluated

    @pytest.mark.asyncio
    async def test_failure_counter_resets_on_successful_partial_sell(self, monkeypatch):
        ex = _make_executor(monkeypatch, swap_results=[
            {"success": False, "error": "no route"},
            {"success": True, "signature": "SELLSIG", "out_amount": 2_000_000},
        ])
        pos = _open_position(ex, tokens=1_000_000)
        await ex._sell(pos.mint, SELL_DECISION)
        assert pos.sell_failures == 1
        partial = {"action": "sell_partial", "sell_pct": 50.0, "reason": "milestone_0",
                   "ratio": 2.0, "milestone_index": 0}
        await ex._sell(pos.mint, partial)
        assert pos.sell_failures == 0, "successful partial sell must reset the counter"
        assert pos.mint in ex.positions
        assert pos.tokens_out == 500_000

    @pytest.mark.asyncio
    async def test_retry_loop_bounded_no_hot_loop(self, monkeypatch):
        """Simulates the live bug: illiquid mint, sell always fails.
        Total swap attempts must be capped at max_sell_failures (was 2335)."""
        ex = _make_executor(monkeypatch,
                            swap_results=[{"success": False, "error": "no route"}] * 50)
        ex.cfg.check_interval_sec = 0
        ex.cfg.sell_retry_backoff_sec = 0
        ex.cfg.max_sell_failures = 5
        _open_position(ex)

        async def _eval(p):
            return SELL_DECISION

        monkeypatch.setattr(ex, "_evaluate", _eval)
        task = asyncio.create_task(ex._position_loop())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(ex.calls) == 5, f"expected 5 bounded sell attempts, got {len(ex.calls)}"
        assert ex.positions == {}


# ================= endpoint regression =================
ENDPOINTS = [
    "/api/health",
    "/api/live/pumpfun/status",
    "/api/live/pumpfun/detections",
    "/api/live/pumpfun/autobuy_status",
    "/api/live/graduation/status",
    "/api/live/graduation/events",
    "/api/live/tx_landings",
    "/api/live/summary",
    "/api/live/auto_arb/status",
    "/api/bot_diagnostic",
]


class TestEndpointRegression:
    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_endpoint_200(self, path):
        r = requests.get(f"{BASE_URL}{path}", timeout=45)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
        assert isinstance(r.json(), (dict, list))

    def test_emergency_stop_post(self):
        r = requests.post(f"{BASE_URL}/api/live/emergency_stop", timeout=45)
        assert r.status_code == 200, r.text[:200]

    def test_no_mongo_object_id_leak(self):
        for path in ("/api/live/pumpfun/detections", "/api/live/graduation/events"):
            r = requests.get(f"{BASE_URL}{path}", timeout=45)
            assert "_id" not in r.text, f"{path} leaks mongo _id"
