"""Iteration 8 — JupiterClient URL fallback logic (live_trader.py).

Jupiter deprecated quote-api.jup.ag/v6. Default is now lite-api.jup.ag/swap/v1 with a
fallback list. The Emergent sandbox blocks jup.ag DNS, so aiohttp.ClientSession is mocked.
"""
import inspect
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
import pytest

sys.path.insert(0, "/app/backend")

import live_trader  # noqa: E402
from live_trader import JupiterClient, LiveTraderConfig  # noqa: E402

PRIMARY = "https://lite-api.jup.ag/swap/v1"
SECONDARY = "https://api.jup.ag/swap/v1"


# ---------------------------------------------------------------- fake aiohttp
def _conn_error(host="lite-api.jup.ag", dns=False):
    key = SimpleNamespace(ssl=None, host=host, port=443, is_ssl=True)
    exc_cls = aiohttp.ClientConnectorDNSError if dns else aiohttp.ClientConnectorError
    return exc_cls(key, OSError(-2, "No address associated with hostname"))


def _http_error(status=400):
    ri = SimpleNamespace(real_url="https://lite-api.jup.ag/swap/v1/quote", method="GET")
    return aiohttp.ClientResponseError(ri, (), status=status, message="HTTP error")


class _FakeResponse:
    def __init__(self, payload=None, raise_exc=None):
        self._payload = payload
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise is not None:
            raise self._raise

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeRequestCM:
    """Returned by session.get()/post(); raises connect error on __aenter__."""

    def __init__(self, behaviour, recorder, url, method, params, json_body):
        self._behaviour = behaviour
        recorder.append({"url": url, "method": method, "params": params, "json": json_body})

    async def __aenter__(self):
        kind = self._behaviour[0]
        if kind == "conn":
            raise self._behaviour[1]
        if kind == "http":
            return _FakeResponse(raise_exc=self._behaviour[1])
        return _FakeResponse(payload=self._behaviour[1])

    async def __aexit__(self, *a):
        return False


class FakeSessionFactory:
    """Patch target for aiohttp.ClientSession.

    behaviours: dict mapping base-url substring -> ("conn"|"http"|"ok", value)
    """

    def __init__(self, behaviours, default=None):
        self.behaviours = behaviours
        self.default = default or ("conn", _conn_error())
        self.calls = []

    def __call__(self, *a, **kw):
        return self._Session(self)

    def _resolve(self, url):
        for key, beh in self.behaviours.items():
            if key in url:
                return beh
        return self.default

    class _Session:
        def __init__(self, factory):
            self.f = factory

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, params=None, **kw):
            return _FakeRequestCM(self.f._resolve(url), self.f.calls, url, "GET", params, None)

        def post(self, url, json=None, **kw):
            return _FakeRequestCM(self.f._resolve(url), self.f.calls, url, "POST", None, json)


# ---------------------------------------------------------------- static checks
class TestStaticStructure:
    def test_fallback_urls_attribute(self):
        assert hasattr(JupiterClient, "_FALLBACK_URLS")
        urls = JupiterClient._FALLBACK_URLS
        assert isinstance(urls, (list, tuple))
        assert len(urls) >= 2
        assert PRIMARY in urls
        assert SECONDARY in urls
        assert not any("quote-api.jup.ag" in u for u in urls)

    def test_try_urls_exists_and_signature(self):
        assert hasattr(JupiterClient, "_try_urls")
        params = inspect.signature(JupiterClient._try_urls).parameters
        for name in ("path", "params", "json_body", "method"):
            assert name in params, f"missing param {name}"

    def test_get_quote_and_build_swap_delegate_to_try_urls(self):
        for fn, expected_path in ((JupiterClient.get_quote, "/quote"),
                                  (JupiterClient.build_swap_tx, "/swap")):
            src = inspect.getsource(fn)
            assert "_try_urls" in src, f"{fn.__name__} does not use _try_urls"
            assert "ClientSession" not in src, f"{fn.__name__} still opens its own session"
            assert expected_path in src

    def test_default_jupiter_base_is_new_url(self):
        env = dict(os.environ)
        env.pop("JUPITER_BASE_URL", None)
        with patch.dict(os.environ, env, clear=True):
            cfg = LiveTraderConfig()
        assert cfg.jupiter_base == PRIMARY
        assert "quote-api.jup.ag" not in cfg.jupiter_base

    def test_env_override_still_respected(self):
        with patch.dict(os.environ, {"JUPITER_BASE_URL": "https://custom.example.com/v1/"}):
            cfg = LiveTraderConfig()
        assert cfg.jupiter_base == "https://custom.example.com/v1"

    def test_source_has_no_deprecated_url(self):
        src = inspect.getsource(live_trader)
        assert "quote-api.jup.ag" not in src


# ---------------------------------------------------------------- fallback logic
@pytest.mark.asyncio
class TestTryUrlsFallback:
    async def test_falls_back_to_second_url_on_connection_error(self):
        payload = {"outAmount": "123456", "routePlan": []}
        factory = FakeSessionFactory({
            "lite-api.jup.ag": ("conn", _conn_error("lite-api.jup.ag")),
            "api.jup.ag": ("ok", payload),
        })
        client = JupiterClient(PRIMARY)
        with patch.object(aiohttp, "ClientSession", factory):
            result = await client._try_urls("/quote", params={"amount": "1"}, method="GET")
        assert result == payload
        urls = [c["url"] for c in factory.calls]
        assert len(urls) == 2, urls
        assert urls[0] == f"{PRIMARY}/quote"
        assert urls[1] == f"{SECONDARY}/quote"

    async def test_falls_back_on_dns_error_subclass(self):
        payload = {"ok": True}
        factory = FakeSessionFactory({
            "lite-api.jup.ag": ("conn", _conn_error("lite-api.jup.ag", dns=True)),
            "api.jup.ag": ("ok", payload),
        })
        client = JupiterClient(PRIMARY)
        with patch.object(aiohttp, "ClientSession", factory):
            assert await client._try_urls("/quote", method="GET") == payload
        assert len(factory.calls) == 2

    async def test_http_error_raises_immediately_no_fallback(self):
        factory = FakeSessionFactory({
            "lite-api.jup.ag": ("http", _http_error(400)),
            "api.jup.ag": ("ok", {"should": "not be reached"}),
        })
        client = JupiterClient(PRIMARY)
        with patch.object(aiohttp, "ClientSession", factory):
            with pytest.raises(aiohttp.ClientResponseError) as ei:
                await client._try_urls("/quote", method="GET")
        assert ei.value.status == 400
        assert len(factory.calls) == 1, f"fallback attempted on HTTP error: {factory.calls}"

    async def test_http_500_also_raises_immediately(self):
        factory = FakeSessionFactory({
            "lite-api.jup.ag": ("http", _http_error(500)),
            "api.jup.ag": ("ok", {"unreached": True}),
        })
        client = JupiterClient(PRIMARY)
        with patch.object(aiohttp, "ClientSession", factory):
            with pytest.raises(aiohttp.ClientResponseError):
                await client._try_urls("/quote", method="GET")
        assert len(factory.calls) == 1

    async def test_all_urls_fail_raises_last_connection_error(self):
        factory = FakeSessionFactory({}, default=("conn", _conn_error("api.jup.ag")))
        client = JupiterClient(PRIMARY)
        with patch.object(aiohttp, "ClientSession", factory):
            with pytest.raises(aiohttp.ClientConnectorError) as ei:
                await client._try_urls("/quote", method="GET")
        assert len(factory.calls) == 2
        assert "api.jup.ag" in str(ei.value)

    async def test_custom_primary_is_tried_first_then_both_fallbacks(self):
        payload = {"via": "secondary"}
        factory = FakeSessionFactory({
            "custom.example.com": ("conn", _conn_error("custom.example.com")),
            "lite-api.jup.ag": ("conn", _conn_error("lite-api.jup.ag")),
            "api.jup.ag": ("ok", payload),
        })
        client = JupiterClient("https://custom.example.com/v1")
        with patch.object(aiohttp, "ClientSession", factory):
            assert await client._try_urls("/quote", method="GET") == payload
        urls = [c["url"] for c in factory.calls]
        assert urls == [
            "https://custom.example.com/v1/quote",
            f"{PRIMARY}/quote",
            f"{SECONDARY}/quote",
        ]

    async def test_no_duplicate_attempt_when_primary_equals_fallback(self):
        factory = FakeSessionFactory({}, default=("conn", _conn_error()))
        client = JupiterClient(PRIMARY)
        with patch.object(aiohttp, "ClientSession", factory):
            with pytest.raises(aiohttp.ClientConnectorError):
                await client._try_urls("/quote", method="GET")
        urls = [c["url"] for c in factory.calls]
        assert len(urls) == len(set(urls)) == 2


# ---------------------------------------------------------------- public methods
@pytest.mark.asyncio
class TestPublicMethodsUseFallback:
    async def test_get_quote_params_and_fallback(self):
        payload = {"outAmount": "999"}
        factory = FakeSessionFactory({
            "lite-api.jup.ag": ("conn", _conn_error()),
            "api.jup.ag": ("ok", payload),
        })
        client = JupiterClient(PRIMARY)
        with patch.object(aiohttp, "ClientSession", factory):
            out = await client.get_quote("MINT_A", "MINT_B", 1000000, slippage_bps=75)
        assert out == payload
        first = factory.calls[0]
        assert first["method"] == "GET"
        assert first["url"].endswith("/quote")
        assert first["params"]["inputMint"] == "MINT_A"
        assert first["params"]["outputMint"] == "MINT_B"
        assert first["params"]["amount"] == "1000000"
        assert first["params"]["slippageBps"] == "75"
        assert factory.calls[1]["url"] == f"{SECONDARY}/quote"

    async def test_build_swap_tx_body_and_fallback(self):
        payload = {"swapTransaction": "BASE64=="}
        factory = FakeSessionFactory({
            "lite-api.jup.ag": ("conn", _conn_error()),
            "api.jup.ag": ("ok", payload),
        })
        client = JupiterClient(PRIMARY)
        quote = {"outAmount": "5"}
        with patch.object(aiohttp, "ClientSession", factory):
            out = await client.build_swap_tx(quote, "PUBKEY123")
        assert out == payload
        first = factory.calls[0]
        assert first["method"] == "POST"
        assert first["url"].endswith("/swap")
        assert first["json"]["quoteResponse"] == quote
        assert first["json"]["userPublicKey"] == "PUBKEY123"
        assert factory.calls[1]["url"] == f"{SECONDARY}/swap"

    async def test_get_quote_propagates_http_error_without_fallback(self):
        factory = FakeSessionFactory({"lite-api.jup.ag": ("http", _http_error(422))})
        client = JupiterClient(PRIMARY)
        with patch.object(aiohttp, "ClientSession", factory):
            with pytest.raises(aiohttp.ClientResponseError):
                await client.get_quote("A", "B", 1)
        assert len(factory.calls) == 1
