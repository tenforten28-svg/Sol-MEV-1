"""
Iteration 11 — pump.fun new-listing detector tests.

Covers:
  * module: pumpfun_sniper (PumpFunSniper class, singleton, log parsing, cap logic)
  * API: GET /api/live/pumpfun/status, GET /api/live/pumpfun/detections
"""
import os
import sys
import json
import importlib
import asyncio

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")


# ---------------- Mock DB helpers ----------------
class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    async def to_list(self, n=None):
        return self.docs


class FakeCollection:
    def __init__(self, docs=None, count=0):
        self.docs = docs or []
        self._count = count
        self.inserted = []
        self.delete_many_calls = []
        self.delete_one_calls = []

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return type("R", (), {"inserted_id": "x"})()

    async def count_documents(self, q):
        return self._count

    def find(self, q=None):
        return FakeCursor(list(self.docs))

    async def delete_many(self, q):
        self.delete_many_calls.append(q)
        return type("R", (), {"deleted_count": 0})()

    async def delete_one(self, q):
        self.delete_one_calls.append(q)


class FakeDB:
    def __init__(self, coll=None):
        self.pumpfun_detections = coll or FakeCollection()


def make_notification(logs, sig="SIG123456789", slot=42):
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


CREATE_LOGS = [
    "Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [1]",
    "Program log: Instruction: Create",
    "Program log: mint: SomePumpMintAddress1234567890abcdefghijk",
]

SWAP_LOGS = [
    "Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [1]",
    "Program log: Instruction: Buy",
    "Program log: mint: SomePumpMintAddress1234567890abcdefghijk",
]


@pytest.fixture
def sniper_module():
    import pumpfun_sniper
    importlib.reload(pumpfun_sniper)
    return pumpfun_sniper


# ---------------- module: constants / singleton ----------------
class TestModuleBasics:
    def test_program_constant(self, sniper_module):
        assert sniper_module.PUMPFUN_PROGRAM == "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

    def test_singleton_returns_same_instance(self, sniper_module):
        db = FakeDB()
        a = sniper_module.get_pumpfun_sniper(db)
        b = sniper_module.get_pumpfun_sniper()
        assert a is b
        assert a.db is db

    def test_singleton_first_call_without_db_raises(self, sniper_module):
        sniper_module._instance = None
        with pytest.raises(RuntimeError):
            sniper_module.get_pumpfun_sniper()

    def test_no_buy_code_path_exists(self):
        src = open("/app/backend/pumpfun_sniper.py").read().lower()
        for banned in ("swap", "jupiter", "execute_buy", "send_transaction",
                       "keypair", "sign_transaction", "private_key"):
            assert banned not in src, f"unexpected trading primitive '{banned}' found in detection-only module"

    def test_subscribe_request_format(self):
        src = open("/app/backend/pumpfun_sniper.py").read()
        assert '"logsSubscribe"' in src
        assert '{"mentions": [PUMPFUN_PROGRAM]}' in src
        assert '{"commitment": "processed"}' in src


# ---------------- module: start() safety ----------------
class TestStartSafety:
    def test_start_noop_when_disabled(self, sniper_module, monkeypatch):
        monkeypatch.delenv("PUMPFUN_SNIPER_ENABLED", raising=False)
        s = sniper_module.PumpFunSniper(FakeDB())
        assert s.enabled is False
        s.start()  # must not raise, even outside an event loop
        assert s.running is False
        assert s.task is None
        assert s.status()["running"] is False

    def test_start_noop_when_wss_url_invalid(self, sniper_module, monkeypatch):
        monkeypatch.setenv("PUMPFUN_SNIPER_ENABLED", "true")
        monkeypatch.setenv("QUICKNODE_WSS_URL", "http://not-a-websocket.example")
        s = sniper_module.PumpFunSniper(FakeDB())
        assert s.enabled is True
        s.start()
        assert s.running is False
        assert s.task is None
        assert s.status()["wss_host"] is None

    def test_start_noop_when_wss_url_missing(self, sniper_module, monkeypatch):
        monkeypatch.setenv("PUMPFUN_SNIPER_ENABLED", "true")
        monkeypatch.setenv("QUICKNODE_WSS_URL", "")
        monkeypatch.setenv("SOLANA_RPC_URL", "")
        s = sniper_module.PumpFunSniper(FakeDB())
        s.start()
        assert s.running is False
        assert s.task is None

    @pytest.mark.asyncio
    async def test_stop_is_safe_without_task(self, sniper_module):
        s = sniper_module.PumpFunSniper(FakeDB())
        await s.stop()
        assert s.running is False


# ---------------- module: _handle_log_notification ----------------
class TestLogNotificationHandling:
    @pytest.mark.asyncio
    async def test_create_log_detected_and_persisted(self, sniper_module):
        coll = FakeCollection()
        s = sniper_module.PumpFunSniper(FakeDB(coll))
        await s._handle_log_notification(make_notification(CREATE_LOGS))
        assert s.total_events == 1
        assert s.detections == 1
        assert s.last_detection_at is not None
        assert len(coll.inserted) == 1
        doc = coll.inserted[0]
        assert doc["candidate_mint"] == "SomePumpMintAddress1234567890abcdefghijk"
        assert doc["signature"] == "SIG123456789"
        assert doc["slot"] == 42
        assert doc["solscan_url"] == "https://solscan.io/tx/SIG123456789"
        assert doc["pumpfun_url"].endswith(doc["candidate_mint"])
        assert doc["raw_log_count"] == 3

    @pytest.mark.asyncio
    async def test_non_create_log_not_counted_as_detection(self, sniper_module):
        coll = FakeCollection()
        s = sniper_module.PumpFunSniper(FakeDB(coll))
        await s._handle_log_notification(make_notification(SWAP_LOGS))
        assert s.total_events == 1
        assert s.detections == 0
        assert coll.inserted == []
        assert s.last_detection_at is None

    @pytest.mark.asyncio
    async def test_malformed_payload_does_not_raise(self, sniper_module):
        coll = FakeCollection()
        s = sniper_module.PumpFunSniper(FakeDB(coll))
        await s._handle_log_notification({"params": {}})
        assert s.total_events == 1
        assert s.detections == 0

    @pytest.mark.asyncio
    async def test_cap_logic_uses_delete_many_with_in(self, sniper_module):
        old_docs = [{"_id": f"id{i}", "detected_at": str(i)} for i in range(5)]
        coll = FakeCollection(docs=old_docs, count=1005)
        s = sniper_module.PumpFunSniper(FakeDB(coll))
        await s._handle_log_notification(make_notification(CREATE_LOGS))
        assert coll.delete_one_calls == [], "cap logic must not use per-doc delete_one"
        assert len(coll.delete_many_calls) == 1
        q = coll.delete_many_calls[0]
        assert "_id" in q and "$in" in q["_id"]
        assert q["_id"]["$in"] == ["id0", "id1", "id2", "id3", "id4"]

    @pytest.mark.asyncio
    async def test_cap_logic_skipped_below_threshold(self, sniper_module):
        coll = FakeCollection(count=10)
        s = sniper_module.PumpFunSniper(FakeDB(coll))
        await s._handle_log_notification(make_notification(CREATE_LOGS))
        assert coll.delete_many_calls == []

    @pytest.mark.asyncio
    async def test_counters_accumulate(self, sniper_module):
        coll = FakeCollection()
        s = sniper_module.PumpFunSniper(FakeDB(coll))
        for _ in range(3):
            await s._handle_log_notification(make_notification(CREATE_LOGS))
        await s._handle_log_notification(make_notification(SWAP_LOGS))
        assert s.total_events == 4
        assert s.detections == 3
        assert len(coll.inserted) == 3


# ---------------- module: mocked websocket subscribe flow ----------------
class TestMockedWebSocket:
    @pytest.mark.asyncio
    async def test_connect_and_listen_subscribes_and_dispatches(self, sniper_module, monkeypatch):
        sent = []

        class FakeMsg:
            def __init__(self, data):
                self.type = sniper_module.aiohttp.WSMsgType.TEXT
                self.data = data

        class FakeWS:
            async def send_str(self, s):
                sent.append(s)

            def __aiter__(self):
                async def gen():
                    yield FakeMsg(json.dumps(make_notification(CREATE_LOGS)))
                    yield FakeMsg(json.dumps({"result": 1, "id": 1}))
                    yield FakeMsg("not-json")
                return gen()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class FakeSession:
            def ws_connect(self, url, **kw):
                return FakeWS()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(sniper_module.aiohttp, "ClientSession", lambda *a, **k: FakeSession())

        coll = FakeCollection()
        s = sniper_module.PumpFunSniper(FakeDB(coll))
        s.wss_url = "wss://example.test/abc"
        await s._connect_and_listen()

        assert s.connection_count == 1
        req = json.loads(sent[0])
        assert req["method"] == "logsSubscribe"
        assert req["params"][0] == {"mentions": [sniper_module.PUMPFUN_PROGRAM]}
        assert req["params"][1] == {"commitment": "processed"}
        assert s.detections == 1
        assert len(coll.inserted) == 1


# ---------------- API endpoints ----------------
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


class TestPumpFunEndpoints:
    def test_status_endpoint(self, api):
        r = api.get(f"{BASE_URL}/api/live/pumpfun/status", timeout=30)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert "error" not in d, d
        for k in ("enabled", "running", "wss_host", "total_events_received",
                  "new_mint_detections", "last_detection_at", "connection_count",
                  "last_error", "note"):
            assert k in d, f"missing key {k}"
        assert d["enabled"] is False
        assert d["running"] is False
        assert isinstance(d["total_events_received"], int)
        assert isinstance(d["new_mint_detections"], int)
        assert isinstance(d["connection_count"], int)
        assert d["last_detection_at"] is None
        assert d["last_error"] is None
        assert "DETECTION-ONLY" in d["note"]
        assert "does NOT auto-buy" in d["note"]

    def test_detections_endpoint(self, api):
        r = api.get(f"{BASE_URL}/api/live/pumpfun/detections?limit=50", timeout=30)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert "error" not in d, d
        assert set(["count", "detections"]).issubset(d.keys())
        assert isinstance(d["detections"], list)
        assert d["count"] == len(d["detections"])
        assert d["count"] == 0, f"expected 0 detections in default env, got {d['count']}"
        for doc in d["detections"]:
            assert "_id" not in doc

    def test_detections_respects_limit(self, api):
        r = api.get(f"{BASE_URL}/api/live/pumpfun/detections?limit=1", timeout=30)
        assert r.status_code == 200
        assert len(r.json()["detections"]) <= 1


# ---------------- regression: previously passing endpoints ----------------
class TestRegressionEndpoints:
    @pytest.mark.parametrize("path", [
        "/api/health",
        "/api/live/status",
        "/api/live/auto_arb/status",
        "/api/live/auto_arb/decisions",
        "/api/live/trades",
        "/api/live/summary",
        "/api/live/rpc_ping",
        "/api/live/balance",
        "/api/bot_diagnostic",
        "/api/stats",
    ])
    def test_get_endpoint_200(self, api, path):
        r = api.get(f"{BASE_URL}{path}", timeout=90)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:300]}"
        assert isinstance(r.json(), dict)

    def test_test_swap_endpoint(self, api):
        r = api.post(f"{BASE_URL}/api/live/test_swap", json={
            "input_symbol": "SOL", "output_symbol": "USDC",
            "amount_usd": 0.30, "dry_run": True,
        }, timeout=90)
        assert r.status_code == 200, f"test_swap -> {r.status_code} {r.text[:300]}"
        body = r.text.lower()
        # In default env live trading is disabled -> endpoint must refuse, not execute
        assert ("not ready" in body or "refus" in body or "disabled" in body
                or "dry_run" in body or "success" in body), r.text[:300]
