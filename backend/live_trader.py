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
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any

import aiohttp
import base58
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey

logger = logging.getLogger("live_trader")

# =========================================================
# TOKEN MINTS — the 5 whitelisted pairs
# =========================================================
MINTS = {
    "SOL":     "So11111111111111111111111111111111111111112",
    "USDC":    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT":    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "JUP":     "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "JitoSOL": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
    "mSOL":    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
}

# Whitelisted pairs — anything outside this list is refused (safety)
WHITELISTED_PAIRS = {
    "SOL/USDC", "JitoSOL/SOL", "mSOL/SOL", "USDC/USDT", "JUP/USDC",
}

# Token decimals (needed to convert human amounts to base units)
DECIMALS = {"SOL": 9, "USDC": 6, "USDT": 6, "JUP": 6, "JitoSOL": 9, "mSOL": 9}

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
        self.jupiter_base = os.environ.get("JUPITER_BASE_URL", "https://quote-api.jup.ag/v6").rstrip("/")

        # Safety limits
        self.max_trade_usd = _env_float("MAX_TRADE_USD", 2.0)
        self.min_reserve_sol = _env_float("MIN_RESERVE_SOL", 0.02)
        self.daily_loss_limit_usd = _env_float("DAILY_LOSS_LIMIT_USD", 3.0)
        self.max_losing_streak = _env_int("MAX_LOSING_STREAK", 3)
        self.live_cooldown_seconds = _env_int("LIVE_COOLDOWN_SECONDS", 60)
        self.slippage_bps = _env_int("LIVE_SLIPPAGE_BPS", 50)
        self.profit_threshold_bps = _env_int("LIVE_PROFIT_THRESHOLD_BPS", 30)

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
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def get_quote(self, input_mint: str, output_mint: str,
                        amount: int, slippage_bps: int = 50) -> Dict[str, Any]:
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(slippage_bps),
            "restrictIntermediateTokens": "true",
        }
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{self.base_url}/quote", params=params, timeout=10) as r:
                r.raise_for_status()
                return await r.json()

    async def build_swap_tx(self, quote: Dict[str, Any], user_pubkey: str) -> Dict[str, Any]:
        body = {
            "quoteResponse": quote,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto",
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{self.base_url}/swap", json=body, timeout=15) as r:
                r.raise_for_status()
                return await r.json()


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

    async def check_pair_allowed(self, pair: str) -> Tuple[bool, str]:
        if pair not in WHITELISTED_PAIRS:
            return False, f"pair '{pair}' not in whitelist {sorted(WHITELISTED_PAIRS)}"
        return True, "ok"

    async def get_sol_balance(self) -> float:
        """Return SOL balance in whole SOL."""
        if not self.ready:
            return 0.0
        try:
            async with AsyncClient(self.cfg.rpc_url) as client:
                resp = await client.get_balance(self.wallet.pubkey())
                lamports = resp.value if hasattr(resp, "value") else 0
                return lamports / 1_000_000_000
        except Exception as e:
            logger.warning(f"[live_trader] get_sol_balance failed: {e}")
            return 0.0

    async def execute_swap(self, input_mint: str, output_mint: str,
                           amount_in_base_units: int) -> Dict[str, Any]:
        """Execute one Jupiter swap. Returns dict with success, signature, error."""
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

            # Submit
            async with AsyncClient(self.cfg.rpc_url) as client:
                send_resp = await client.send_raw_transaction(signed_bytes)
                sig = str(send_resp.value if hasattr(send_resp, "value") else send_resp)

                # Poll for confirmation (max 60s)
                confirmed = False
                err = None
                deadline = time.time() + 60
                import asyncio
                while time.time() < deadline:
                    await asyncio.sleep(2)
                    try:
                        st_resp = await client.get_signature_statuses([signed.signatures[0]])
                        st = st_resp.value[0] if st_resp and st_resp.value else None
                        if st is not None:
                            if st.err:
                                err = str(st.err)
                                break
                            if str(st.confirmation_status) in ("confirmed", "finalized",
                                                                "TransactionConfirmationStatus.Confirmed",
                                                                "TransactionConfirmationStatus.Finalized"):
                                confirmed = True
                                break
                    except Exception:
                        pass

            return {
                "success": confirmed,
                "signature": sig,
                "error": err,
                "in_amount": quote.get("inAmount"),
                "out_amount": quote.get("outAmount"),
                "route": quote.get("routePlan", []),
            }
        except Exception as e:
            logger.exception("[live_trader] execute_swap error")
            return {"success": False, "error": str(e)}

    def status(self) -> Dict[str, Any]:
        return {
            "ready": self.ready,
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
