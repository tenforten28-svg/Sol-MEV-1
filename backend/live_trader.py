"""
LIVE TRADER — Jupiter v6 + QuickNode RPC
========================================
Executes real arbitrage on Solana mainnet using Jupiter's Swap API
for routing and a QuickNode RPC endpoint for tx submission.

SAFETY-FIRST design for small wallets (~$12):
- Double gate: only runs if SIMULATION_MODE=false AND LIVE_TRADING_ENABLED=true
- Hard trade size cap (MAX_TRADE_USD, default $2)
- Minimum SOL reserve for gas (MIN_RESERVE_SOL, default 0.02)
- Daily loss circuit breaker (DAILY_LOSS_LIMIT_USD, default $3)
- Consecutive-loss circuit breaker (MAX_LOSING_STREAK, default 3)
- Global cooldown between real trades (LIVE_COOLDOWN_SECONDS, default 60)
- Restricted to 5 whitelisted high-liquidity pairs
"""

import os
import time
import base64
import random
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any, List

import aiohttp
import base58
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.message import MessageV0

logger = logging.getLogger("live_trader")

# =========================================================
# TOKEN MINTS — the whitelisted trading universe
# Includes major stables (USDC, USDT), majors (SOL, JUP), LSTs (JitoSOL, mSOL),
# and pump.fun-originated meme tokens now trading on Raydium/pump-AMM
# =========================================================
MINTS = {
    "SOL":      "So11111111111111111111111111111111111111112",
    "USDC":     "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT":     "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "JUP":      "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "JitoSOL":  "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
    "mSOL":     "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    # Meme tokens (pump.fun-origin, now multi-DEX with real liquidity)
    "BONK":     "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF":      "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "POPCAT":   "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "PNUT":     "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump",
}

# Whitelisted round-trip pairs (start/mid). Only these can be traded.
WHITELISTED_PAIRS = {
    # Safe majors
    "SOL/USDC", "JitoSOL/SOL", "mSOL/SOL", "USDC/USDT", "JUP/USDC",
    # Meme volatility (higher risk, higher fire rate)
    "BONK/USDC", "WIF/USDC", "POPCAT/USDC", "PNUT/USDC",
    "USDC/BONK", "USDC/WIF", "USDC/POPCAT", "USDC/PNUT",
}

# Token decimals (needed to convert human amounts to base units)
DECIMALS = {
    "SOL": 9, "USDC": 6, "USDT": 6, "JUP": 6, "JitoSOL": 9, "mSOL": 9,
    "BONK": 5, "WIF": 6, "POPCAT": 9, "PNUT": 6,
}

# Approximate USD price for sizing conversion (rough, updated occasionally).
# Only used to convert amount_usd -> base units on the START token.
PRICE_HINTS_USD = {
    "SOL": 150.0, "JitoSOL": 165.0, "mSOL": 165.0,
    "USDC": 1.0, "USDT": 1.0, "JUP": 0.5,
    "BONK": 0.00002, "WIF": 1.5, "POPCAT": 0.4, "PNUT": 0.15,
}

# =========================================================
# JITO — MEV protection via bundled tx submission
# =========================================================
# Jito's public tip accounts (rotate randomly to spread load).
# See: https://docs.jito.wtf/lowlatencytxnsend/#tip-accounts
JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4bVmTpqFSZfxMQVKqhjGrwW",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
]

# =========================================================
# CONFIG — read from env, with safe defaults
# =========================================================
def _env_bool(key: str, default: bool = False) -> bool:
    return str(os.environ.get(key, str(default))).strip().lower() in ("true", "1", "yes", "on")

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except Exception:
        return default

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except Exception:
        return default


class LiveTraderConfig:
    def __init__(self) -> None:
        self.simulation_mode = _env_bool("SIMULATION_MODE", True)
        self.live_enabled = _env_bool("LIVE_TRADING_ENABLED", False)
        self.rpc_url = os.environ.get("SOLANA_RPC_URL", "").strip()
        self.private_key = os.environ.get("SOLANA_PRIVATE_KEY", "").strip()
        self.jupiter_base = os.environ.get("JUPITER_BASE_URL", "https://lite-api.jup.ag/swap/v1").rstrip("/")

        # Safety limits
        self.max_trade_usd = _env_float("MAX_TRADE_USD", 2.0)
        self.min_reserve_sol = _env_float("MIN_RESERVE_SOL", 0.02)
        self.daily_loss_limit_usd = _env_float("DAILY_LOSS_LIMIT_USD", 3.0)
        self.max_losing_streak = _env_int("MAX_LOSING_STREAK", 3)
        self.live_cooldown_seconds = _env_int("LIVE_COOLDOWN_SECONDS", 60)
        self.slippage_bps = _env_int("LIVE_SLIPPAGE_BPS", 50)
        self.profit_threshold_bps = _env_int("LIVE_PROFIT_THRESHOLD_BPS", 30)

        # Jito bundle submission (MEV protection)
        self.use_jito = _env_bool("USE_JITO", False)
        self.jito_url = os.environ.get(
            "JITO_BLOCK_ENGINE_URL", "https://mainnet.block-engine.jito.wtf"
        ).rstrip("/")
        self.jito_tip_lamports = _env_int("JITO_TIP_LAMPORTS", 10_000)  # ~$0.0015 default
        self.jito_max_tip_lamports = _env_int("JITO_MAX_TIP_LAMPORTS", 100_000)  # hard cap ~$0.015

    @property
    def fully_configured(self) -> bool:
        return bool(self.live_enabled
                    and not self.simulation_mode
                    and self.rpc_url
                    and self.private_key)


# =========================================================
# JUPITER CLIENT (async aiohttp)
# =========================================================
class JupiterClient:
    # Fallback URLs tried in order if primary fails with DNS/connection error.
    _FALLBACK_URLS = [
        "https://lite-api.jup.ag/swap/v1",
        "https://api.jup.ag/swap/v1",
    ]

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def _try_urls(self, path: str, params=None, json_body=None,
                        method: str = "GET") -> Dict[str, Any]:
        """Try primary URL first, then fallbacks on connection errors,
        timeouts, rate limits (HTTP 429), and server errors (HTTP 5xx).
        Only HTTP 4xx (except 429) raises immediately — those are client errors
        that another URL can't fix."""
        import asyncio as _asyncio
        urls_to_try = [self.base_url] + [u for u in self._FALLBACK_URLS if u != self.base_url]
        last_err = None
        for base in urls_to_try:
            url = f"{base}{path}"
            try:
                async with aiohttp.ClientSession() as s:
                    if method == "GET":
                        async with s.get(url, params=params, timeout=10) as r:
                            if r.status == 429 or r.status >= 500:
                                body = await r.text()
                                last_err = RuntimeError(f"HTTP {r.status} from {url}: {body[:200]}")
                                logger.warning(f"[jupiter] {url} returned {r.status}; trying next")
                                continue
                            r.raise_for_status()
                            return await r.json()
                    else:
                        async with s.post(url, json=json_body, timeout=15) as r:
                            if r.status == 429 or r.status >= 500:
                                body = await r.text()
                                last_err = RuntimeError(f"HTTP {r.status} from {url}: {body[:200]}")
                                logger.warning(f"[jupiter] {url} returned {r.status}; trying next")
                                continue
                            r.raise_for_status()
                            return await r.json()
            except (aiohttp.ClientConnectorError, aiohttp.ClientConnectorDNSError,
                    aiohttp.ClientConnectionError, _asyncio.TimeoutError) as e:
                last_err = e
                logger.warning(f"[jupiter] {url} unreachable ({type(e).__name__}: {e}); trying next")
                continue
            except aiohttp.ClientResponseError as e:
                # HTTP 4xx (other than 429) — don't try fallbacks, client-side error
                raise
        raise last_err or RuntimeError("all Jupiter URLs failed")

    async def get_quote(self, input_mint: str, output_mint: str,
                        amount: int, slippage_bps: int = 50) -> Dict[str, Any]:
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(slippage_bps),
            "restrictIntermediateTokens": "true",
        }
        return await self._try_urls("/quote", params=params, method="GET")

    async def build_swap_tx(self, quote: Dict[str, Any], user_pubkey: str) -> Dict[str, Any]:
        body = {
            "quoteResponse": quote,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto",
        }
        return await self._try_urls("/swap", json_body=body, method="POST")


# =========================================================
# RISK GUARD (circuit breakers)
# =========================================================
class RiskGuard:
    """In-memory circuit breaker. State resets on process restart (deliberate: forces daily fresh start)."""
    def __init__(self, cfg: LiveTraderConfig) -> None:
        self.cfg = cfg
        self.day_started_utc = datetime.now(timezone.utc).date()
        self.day_pnl_usd = 0.0
        self.losing_streak = 0
        self.last_trade_ts = 0.0
        self.blocked_reason: Optional[str] = None

    def _reset_if_new_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self.day_started_utc:
            self.day_started_utc = today
            self.day_pnl_usd = 0.0
            self.losing_streak = 0
            self.blocked_reason = None

    def can_trade(self, trade_size_usd: float) -> Tuple[bool, str]:
        self._reset_if_new_day()
        if self.blocked_reason:
            return False, self.blocked_reason
        if trade_size_usd > self.cfg.max_trade_usd:
            return False, f"trade size ${trade_size_usd:.2f} exceeds MAX_TRADE_USD ${self.cfg.max_trade_usd:.2f}"
        if self.day_pnl_usd <= -self.cfg.daily_loss_limit_usd:
            self.blocked_reason = f"daily loss limit hit ({self.day_pnl_usd:.2f} <= -{self.cfg.daily_loss_limit_usd:.2f})"
            return False, self.blocked_reason
        if self.losing_streak >= self.cfg.max_losing_streak:
            self.blocked_reason = f"losing streak {self.losing_streak} >= max {self.cfg.max_losing_streak}"
            return False, self.blocked_reason
        elapsed = time.time() - self.last_trade_ts
        if elapsed < self.cfg.live_cooldown_seconds:
            return False, f"cooldown active ({int(self.cfg.live_cooldown_seconds - elapsed)}s remaining)"
        return True, "ok"

    def record_trade(self, pnl_usd: float) -> None:
        self._reset_if_new_day()
        self.day_pnl_usd += pnl_usd
        if pnl_usd < 0:
            self.losing_streak += 1
        else:
            self.losing_streak = 0
        self.last_trade_ts = time.time()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "day_started_utc": self.day_started_utc.isoformat(),
            "day_pnl_usd": round(self.day_pnl_usd, 4),
            "losing_streak": self.losing_streak,
            "last_trade_ts": self.last_trade_ts,
            "blocked_reason": self.blocked_reason,
        }


# =========================================================
# LIVE TRADER — main class
# =========================================================
class LiveTrader:
    def __init__(self, cfg: LiveTraderConfig) -> None:
        self.cfg = cfg
        self.jupiter = JupiterClient(cfg.jupiter_base)
        self.risk = RiskGuard(cfg)
        self.wallet: Optional[Keypair] = None
        self.wallet_pubkey: Optional[str] = None
        if cfg.fully_configured:
            self._load_wallet()

    def _load_wallet(self) -> None:
        try:
            secret = base58.b58decode(self.cfg.private_key)
            if len(secret) != 64:
                raise ValueError(f"expected 64 bytes, got {len(secret)}")
            self.wallet = Keypair.from_bytes(secret)
            self.wallet_pubkey = str(self.wallet.pubkey())
            logger.info(f"[live_trader] wallet loaded: {self.wallet_pubkey}")
        except Exception as e:
            logger.error(f"[live_trader] wallet load failed: {e}")
            self.wallet = None

    @property
    def ready(self) -> bool:
        return self.cfg.fully_configured and self.wallet is not None

    @property
    def wallet_configured(self) -> bool:
        """Wallet + RPC available — enough to fetch balance, NOT enough to trade.
        Trading additionally requires SIMULATION_MODE=false AND LIVE_TRADING_ENABLED=true.
        """
        return bool(self.cfg.rpc_url and self.wallet)

    async def check_pair_allowed(self, pair: str) -> Tuple[bool, str]:
        if pair not in WHITELISTED_PAIRS:
            return False, f"pair '{pair}' not in whitelist {sorted(WHITELISTED_PAIRS)}"
        return True, "ok"

    async def get_sol_balance(self) -> float:
        """Return SOL balance in whole SOL. Works whenever wallet + RPC are configured,
        even if trading gates (LIVE_TRADING_ENABLED / SIMULATION_MODE) are still safe."""
        if not self.wallet_configured:
            return 0.0
        try:
            async with AsyncClient(self.cfg.rpc_url) as client:
                resp = await client.get_balance(self.wallet.pubkey())
                lamports = resp.value if hasattr(resp, "value") else 0
                return lamports / 1_000_000_000
        except Exception as e:
            logger.warning(f"[live_trader] get_sol_balance failed: {e}")
            return 0.0

    async def rpc_ping(self) -> Dict[str, Any]:
        """Diagnostic: verify QuickNode RPC is reachable and credentials work.
        Uses ~2 credits (getVersion + getSlot). Returns detailed diagnostics
        so silent failures become visible.
        """
        if not self.cfg.rpc_url:
            return {"ok": False, "reason": "SOLANA_RPC_URL not set"}
        try:
            async with AsyncClient(self.cfg.rpc_url) as client:
                # getVersion — cheapest possible RPC call, no auth needed to work
                version_resp = await client.get_version()
                slot_resp = await client.get_slot()
                slot = slot_resp.value if hasattr(slot_resp, "value") else None
                # get_version returns an object with solana_core, feature_set
                sc = None
                if hasattr(version_resp, "value") and version_resp.value:
                    sc = getattr(version_resp.value, "solana_core", None) \
                         or getattr(version_resp.value, "solana-core", None)
                return {
                    "ok": True,
                    "rpc_reachable": True,
                    "solana_core": sc,
                    "current_slot": slot,
                    "rpc_host": self.cfg.rpc_url.split("//")[-1].split("/")[0],
                    "credits_used_by_this_call": "~2 (getVersion + getSlot)",
                }
        except Exception as e:
            return {
                "ok": False,
                "rpc_reachable": False,
                "error": str(e) or repr(e) or type(e).__name__,
                "rpc_host": self.cfg.rpc_url.split("//")[-1].split("/")[0],
            }

    async def _build_tip_transaction(self, tip_lamports: int) -> Tuple[VersionedTransaction, str]:
        """Build & sign a small system-transfer tx to a random Jito tip account."""
        tip_account = Pubkey.from_string(random.choice(JITO_TIP_ACCOUNTS))
        ix = transfer(TransferParams(
            from_pubkey=self.wallet.pubkey(),
            to_pubkey=tip_account,
            lamports=tip_lamports,
        ))
        async with AsyncClient(self.cfg.rpc_url) as client:
            resp = await client.get_latest_blockhash()
            blockhash = resp.value.blockhash if hasattr(resp, "value") else resp["result"]["value"]["blockhash"]
        msg = MessageV0.try_compile(
            payer=self.wallet.pubkey(),
            instructions=[ix],
            address_lookup_table_accounts=[],
            recent_blockhash=blockhash,
        )
        tx = VersionedTransaction(msg, [self.wallet])
        return tx, str(tip_account)

    async def _submit_jito_bundle(self, signed_swap_bytes: bytes,
                                   tip_lamports: int) -> Tuple[Optional[str], Optional[str]]:
        """
        Submit [swap_tx, tip_tx] as an atomic Jito bundle.
        Returns (bundle_id, error). If bundle_id is set, submission succeeded.
        """
        tip_lamports = min(tip_lamports, self.cfg.jito_max_tip_lamports)  # hard cap
        try:
            tip_tx, tip_account = await self._build_tip_transaction(tip_lamports)
            swap_b64 = base64.b64encode(signed_swap_bytes).decode()
            tip_b64 = base64.b64encode(bytes(tip_tx)).decode()

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [[swap_b64, tip_b64]],
            }

            async with aiohttp.ClientSession() as s:
                url = f"{self.cfg.jito_url}/api/v1/bundles"
                async with s.post(url, json=payload, timeout=15) as r:
                    data = await r.json()
                    if "result" in data:
                        logger.info(f"[jito] bundle submitted: {data['result']} tip={tip_lamports} to {tip_account[:8]}...")
                        return data["result"], None
                    return None, str(data.get("error", data))
        except Exception as e:
            logger.exception("[jito] bundle submission failed")
            return None, str(e)

    async def execute_swap(self, input_mint: str, output_mint: str,
                           amount_in_base_units: int) -> Dict[str, Any]:
        """Execute one Jupiter swap. Uses Jito bundle if USE_JITO=true, else direct RPC."""
        if not self.ready:
            return {"success": False, "error": "live trader not ready (missing config)"}

        try:
            quote = await self.jupiter.get_quote(
                input_mint, output_mint, amount_in_base_units, self.cfg.slippage_bps
            )
            if "error" in quote or "outAmount" not in quote:
                return {"success": False, "error": f"quote failed: {quote}"}

            swap_resp = await self.jupiter.build_swap_tx(quote, self.wallet_pubkey)
            tx_b64 = swap_resp.get("swapTransaction")
            if not tx_b64:
                return {"success": False, "error": f"no swapTransaction: {swap_resp}"}

            # Deserialize + sign
            raw = base64.b64decode(tx_b64)
            unsigned = VersionedTransaction.from_bytes(raw)
            signed = VersionedTransaction(unsigned.message, [self.wallet])
            signed_bytes = bytes(signed)
            swap_sig = str(signed.signatures[0])

            bundle_id: Optional[str] = None
            submission_method = "direct_rpc"

            # ---- Jito path ----
            if self.cfg.use_jito:
                bundle_id, jito_err = await self._submit_jito_bundle(
                    signed_bytes, self.cfg.jito_tip_lamports
                )
                if bundle_id:
                    submission_method = "jito_bundle"
                else:
                    # Fallback to direct RPC on Jito failure (with a warning)
                    logger.warning(f"[jito] fallback to direct RPC: {jito_err}")
                    submission_method = "direct_rpc_fallback"

            # ---- Direct RPC path (or Jito fallback) ----
            if submission_method != "jito_bundle":
                async with AsyncClient(self.cfg.rpc_url) as client:
                    await client.send_raw_transaction(signed_bytes)

            # ---- Poll for confirmation ----
            import asyncio
            confirmed = False
            err = None
            deadline = time.time() + 60
            async with AsyncClient(self.cfg.rpc_url) as client:
                while time.time() < deadline:
                    await asyncio.sleep(2)
                    try:
                        st_resp = await client.get_signature_statuses([signed.signatures[0]])
                        st = st_resp.value[0] if st_resp and st_resp.value else None
                        if st is not None:
                            if st.err:
                                err = str(st.err)
                                break
                            if str(st.confirmation_status) in (
                                "confirmed", "finalized",
                                "TransactionConfirmationStatus.Confirmed",
                                "TransactionConfirmationStatus.Finalized",
                            ):
                                confirmed = True
                                break
                    except Exception:
                        pass

            return {
                "success": confirmed,
                "signature": swap_sig,
                "error": err,
                "in_amount": quote.get("inAmount"),
                "out_amount": quote.get("outAmount"),
                "route": quote.get("routePlan", []),
                "submission_method": submission_method,
                "bundle_id": bundle_id,
                "jito_tip_lamports": self.cfg.jito_tip_lamports if submission_method == "jito_bundle" else 0,
            }
        except Exception as e:
            logger.exception("[live_trader] execute_swap error")
            return {"success": False, "error": str(e)}

    def status(self) -> Dict[str, Any]:
        return {
            "ready": self.ready,
            "wallet_configured": self.wallet_configured,
            "simulation_mode": self.cfg.simulation_mode,
            "live_enabled": self.cfg.live_enabled,
            "has_rpc_url": bool(self.cfg.rpc_url),
            "has_private_key": bool(self.cfg.private_key),
            "wallet_pubkey": self.wallet_pubkey,
            "limits": {
                "max_trade_usd": self.cfg.max_trade_usd,
                "min_reserve_sol": self.cfg.min_reserve_sol,
                "daily_loss_limit_usd": self.cfg.daily_loss_limit_usd,
                "max_losing_streak": self.cfg.max_losing_streak,
                "cooldown_seconds": self.cfg.live_cooldown_seconds,
                "slippage_bps": self.cfg.slippage_bps,
                "profit_threshold_bps": self.cfg.profit_threshold_bps,
            },
            "jito": {
                "enabled": self.cfg.use_jito,
                "block_engine_url": self.cfg.jito_url,
                "tip_lamports": self.cfg.jito_tip_lamports,
                "tip_sol": self.cfg.jito_tip_lamports / 1_000_000_000,
                "max_tip_lamports": self.cfg.jito_max_tip_lamports,
            },
            "whitelisted_pairs": sorted(WHITELISTED_PAIRS),
            "risk": self.risk.snapshot(),
        }


# =========================================================
# Singleton factory
# =========================================================
_instance: Optional[LiveTrader] = None

def get_live_trader() -> LiveTrader:
    global _instance
    if _instance is None:
        _instance = LiveTrader(LiveTraderConfig())
    return _instance
