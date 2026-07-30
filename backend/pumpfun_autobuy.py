"""
PUMP.FUN AUTO-SNIPER
====================
Detects new pump.fun mints and (when PUMPFUN_AUTO_BUY_ENABLED=true) fires a small buy
via Jupiter (which routes bonding-curve trades through pump.fun's AMM).
Then monitors position and auto-sells on time-limit, profit target, or stop-loss.

SAFETY (non-negotiable):
- Hard-capped buy size (PUMPFUN_BUY_USD default $0.30)
- Daily budget cap (PUMPFUN_DAILY_BUDGET_USD default $2)
- Min quote-liquidity filter (rejects thin pools via price_impact check)
- Position cap (PUMPFUN_MAX_CONCURRENT default 3)
- Auto-exit on stop-loss (default -50%) or take-profit (default 2x) or time (5min)
- Cooldown between buys
- Reuses existing LiveTrader (all its guards apply)
"""
import os
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from live_trader import get_live_trader, MINTS, DECIMALS

logger = logging.getLogger("pumpfun_autobuy")

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6


def _fbool(k, d=False): return str(os.environ.get(k, str(d))).strip().lower() in ("true", "1", "yes", "on")
def _fflt(k, d): 
    try: return float(os.environ.get(k, d))
    except: return d
def _fint(k, d):
    try: return int(os.environ.get(k, d))
    except: return d


class AutoBuyConfig:
    def __init__(self):
        self.enabled = _fbool("PUMPFUN_AUTO_BUY_ENABLED", False)
        self.buy_usd = _fflt("PUMPFUN_BUY_USD", 0.30)              # ~$0.30 per buy
        self.daily_budget_usd = _fflt("PUMPFUN_DAILY_BUDGET_USD", 2.0)  # $2/day max
        self.max_concurrent = _fint("PUMPFUN_MAX_CONCURRENT", 3)   # max positions open
        self.cooldown_sec = _fint("PUMPFUN_COOLDOWN_SEC", 30)      # min sec between buys
        self.max_price_impact_pct = _fflt("PUMPFUN_MAX_PRICE_IMPACT", 5.0)  # skip thin pools
        self.hold_max_seconds = _fint("PUMPFUN_HOLD_MAX_SEC", 300)  # 5 min max hold
        self.take_profit_mult = _fflt("PUMPFUN_TAKE_PROFIT", 2.0)  # sell at 2x
        self.stop_loss_mult = _fflt("PUMPFUN_STOP_LOSS", 0.5)      # sell at -50%
        self.settle_delay_sec = _fint("PUMPFUN_SETTLE_DELAY", 4)   # wait after mint before buying
        self.check_interval_sec = _fint("PUMPFUN_CHECK_INTERVAL", 10)  # position check freq
        self.slippage_bps = _fint("PUMPFUN_SLIPPAGE_BPS", 500)     # 5% for pump.fun volatility


class Position:
    def __init__(self, mint: str, buy_amount_usdc: float, buy_out_amount: int,
                  buy_signature: str, opened_at: float):
        self.mint = mint
        self.buy_amount_usdc = buy_amount_usdc          # USDC spent
        self.token_balance = buy_out_amount             # base units of token held
        self.buy_signature = buy_signature
        self.opened_at = opened_at
        self.entry_price_usdc_per_token = buy_amount_usdc / (buy_out_amount or 1)
        self.closed = False


class PumpFunAutoBuyer:
    def __init__(self, db):
        self.db = db
        self.cfg = AutoBuyConfig()
        self.lt = get_live_trader()
        self.positions: Dict[str, Position] = {}
        self.last_buy_at = 0.0
        self.day_start = datetime.now(timezone.utc).date()
        self.day_spent_usd = 0.0
        # Counters
        self.attempts = 0
        self.buys_fired = 0
        self.buys_successful = 0
        self.sells_fired = 0
        self.last_reason: Optional[str] = None

    def _reset_day_if_needed(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day_start:
            self.day_start = today
            self.day_spent_usd = 0.0

    async def maybe_buy(self, mint: str) -> Dict[str, Any]:
        """Called by pumpfun_sniper when a new mint is detected."""
        self.attempts += 1
        self._reset_day_if_needed()

        if not self.cfg.enabled:
            self.last_reason = "auto-buy disabled"
            return {"ok": False, "reason": self.last_reason}
        if not self.lt.ready:
            self.last_reason = "live_trader not ready"
            return {"ok": False, "reason": self.last_reason}
        if len(self.positions) >= self.cfg.max_concurrent:
            self.last_reason = f"max_concurrent {self.cfg.max_concurrent} positions open"
            return {"ok": False, "reason": self.last_reason}
        if self.day_spent_usd + self.cfg.buy_usd > self.cfg.daily_budget_usd:
            self.last_reason = f"daily budget ${self.cfg.daily_budget_usd} exhausted"
            return {"ok": False, "reason": self.last_reason}
        elapsed = time.time() - self.last_buy_at
        if elapsed < self.cfg.cooldown_sec:
            self.last_reason = f"cooldown {int(self.cfg.cooldown_sec - elapsed)}s"
            return {"ok": False, "reason": self.last_reason}
        if not mint or len(mint) < 40:
            self.last_reason = "invalid mint address"
            return {"ok": False, "reason": self.last_reason}

        # Wait for the pool to settle (creator initial buy)
        await asyncio.sleep(self.cfg.settle_delay_sec)

        # Get quote first — if this fails, pool doesn't have liquidity yet
        amount_base = int(self.cfg.buy_usd * (10 ** USDC_DECIMALS))
        try:
            quote = await self.lt.jupiter.get_quote(
                USDC_MINT, mint, amount_base, self.cfg.slippage_bps
            )
        except Exception as e:
            self.last_reason = f"quote failed: {str(e)[:100]}"
            return {"ok": False, "reason": self.last_reason}

        if "outAmount" not in quote:
            self.last_reason = f"no route (bonding curve may not be indexed yet)"
            return {"ok": False, "reason": self.last_reason}

        # Reject if price impact too high (thin pool = likely rug or micro-cap)
        try:
            price_impact = float(quote.get("priceImpactPct") or 0) * 100.0
        except Exception:
            price_impact = 0.0
        if price_impact > self.cfg.max_price_impact_pct:
            self.last_reason = f"price_impact {price_impact:.2f}% > {self.cfg.max_price_impact_pct}%"
            return {"ok": False, "reason": self.last_reason}

        # FIRE THE BUY
        logger.info(f"[pumpfun-buy] FIRING {mint[:8]}... amount=${self.cfg.buy_usd} impact={price_impact:.2f}%")
        result = await self.lt.execute_swap(USDC_MINT, mint, amount_base)
        self.buys_fired += 1
        self.last_buy_at = time.time()
        self.day_spent_usd += self.cfg.buy_usd
        self.last_reason = f"BUY fired for {mint[:8]}..."

        if not result.get("success"):
            # Record failed buy attempt
            await self._record_position_event(mint, "buy_failed", result)
            return {"ok": False, "reason": f"buy tx failed: {result.get('error')}", "result": result}

        # Position opened
        out_amount = int(result.get("out_amount") or quote["outAmount"])
        pos = Position(mint=mint, buy_amount_usdc=self.cfg.buy_usd,
                        buy_out_amount=out_amount,
                        buy_signature=result.get("signature"),
                        opened_at=time.time())
        self.positions[mint] = pos
        self.buys_successful += 1

        await self._record_position_event(mint, "opened", {
            "buy_signature": result.get("signature"),
            "buy_amount_usdc": self.cfg.buy_usd,
            "token_balance": out_amount,
            "entry_price": pos.entry_price_usdc_per_token,
            "solscan_url": f"https://solscan.io/tx/{result.get('signature')}",
            "pumpfun_url": f"https://pump.fun/coin/{mint}",
        })
        return {"ok": True, "signature": result.get("signature"), "mint": mint}

    async def monitor_positions(self):
        """Background loop — check every open position and auto-sell when triggered."""
        while True:
            try:
                await asyncio.sleep(self.cfg.check_interval_sec)
                if not self.positions or not self.lt.ready:
                    continue
                to_close = []
                for mint, pos in list(self.positions.items()):
                    verdict = await self._evaluate_position(pos)
                    if verdict:
                        to_close.append((mint, verdict))
                for mint, verdict in to_close:
                    await self._sell(mint, verdict)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[pumpfun-monitor] loop error: {e}")

    async def _evaluate_position(self, pos: Position) -> Optional[str]:
        """Return exit reason string if the position should be closed, else None."""
        age = time.time() - pos.opened_at
        # Time-based exit (hard limit)
        if age >= self.cfg.hold_max_seconds:
            return "time_limit"

        # Get sell quote to check current price
        try:
            q = await self.lt.jupiter.get_quote(
                pos.mint, USDC_MINT, pos.token_balance, self.cfg.slippage_bps
            )
        except Exception as e:
            logger.debug(f"[pumpfun-monitor] quote fail {pos.mint[:8]}: {e}")
            return None
        if "outAmount" not in q:
            return None

        current_usdc = int(q["outAmount"]) / (10 ** USDC_DECIMALS)
        pnl_mult = current_usdc / pos.buy_amount_usdc if pos.buy_amount_usdc else 0

        if pnl_mult >= self.cfg.take_profit_mult:
            return f"take_profit_{pnl_mult:.2f}x"
        if pnl_mult <= self.cfg.stop_loss_mult:
            return f"stop_loss_{pnl_mult:.2f}x"
        return None

    async def _sell(self, mint: str, verdict: str):
        pos = self.positions.get(mint)
        if not pos or pos.closed:
            return
        logger.info(f"[pumpfun-sell] {mint[:8]} verdict={verdict}")
        result = await self.lt.execute_swap(mint, USDC_MINT, pos.token_balance)
        self.sells_fired += 1
        pos.closed = True
        received_usdc = 0.0
        if result.get("success"):
            received_usdc = int(result.get("out_amount") or 0) / (10 ** USDC_DECIMALS)
        pnl_usd = round(received_usdc - pos.buy_amount_usdc, 6)
        await self._record_position_event(mint, "closed", {
            "verdict": verdict,
            "sell_signature": result.get("signature"),
            "buy_signature": pos.buy_signature,
            "received_usdc": received_usdc,
            "buy_usdc": pos.buy_amount_usdc,
            "pnl_usd": pnl_usd,
            "hold_seconds": time.time() - pos.opened_at,
            "solscan_sell": f"https://solscan.io/tx/{result.get('signature')}" if result.get("signature") else None,
            "success": result.get("success", False),
        })
        # Persist trade row too so LiveTradingPanel picks it up
        try:
            await self.db.trades.insert_one({
                "created_at": datetime.now(timezone.utc).isoformat(),
                "pair": f"USDC->{mint[:6]}..->USDC",
                "type": "live_pumpfun_snipe",
                "amount_usd": pos.buy_amount_usdc,
                "realized_pnl_usd": pnl_usd,
                "success": result.get("success", False) and pnl_usd > -pos.buy_amount_usdc,
                "signature": result.get("signature"),
                "solscan_url": f"https://solscan.io/tx/{result.get('signature')}" if result.get("signature") else None,
                "simulation": False,
                "mint": mint,
                "verdict": verdict,
            })
        except Exception as e:
            logger.warning(f"[pumpfun-sell] mongo insert failed: {e}")
        self.positions.pop(mint, None)

    async def _record_position_event(self, mint: str, event: str, data: Dict):
        try:
            await self.db.pumpfun_positions.insert_one({
                "at": datetime.now(timezone.utc).isoformat(),
                "mint": mint,
                "event": event,
                **data,
            })
        except Exception:
            pass

    def status(self) -> Dict[str, Any]:
        self._reset_day_if_needed()
        return {
            "enabled": self.cfg.enabled,
            "config": {
                "buy_usd": self.cfg.buy_usd,
                "daily_budget_usd": self.cfg.daily_budget_usd,
                "max_concurrent": self.cfg.max_concurrent,
                "cooldown_sec": self.cfg.cooldown_sec,
                "max_price_impact_pct": self.cfg.max_price_impact_pct,
                "hold_max_seconds": self.cfg.hold_max_seconds,
                "take_profit_mult": self.cfg.take_profit_mult,
                "stop_loss_mult": self.cfg.stop_loss_mult,
                "settle_delay_sec": self.cfg.settle_delay_sec,
                "slippage_bps": self.cfg.slippage_bps,
            },
            "day_spent_usd": round(self.day_spent_usd, 4),
            "day_budget_remaining_usd": round(self.cfg.daily_budget_usd - self.day_spent_usd, 4),
            "open_positions": len(self.positions),
            "position_mints": list(self.positions.keys()),
            "counters": {
                "attempts": self.attempts,
                "buys_fired": self.buys_fired,
                "buys_successful": self.buys_successful,
                "sells_fired": self.sells_fired,
            },
            "last_reason": self.last_reason,
            "live_trader_ready": self.lt.ready,
        }


_instance: Optional[PumpFunAutoBuyer] = None
def get_pumpfun_autobuyer(db=None) -> PumpFunAutoBuyer:
    global _instance
    if _instance is None:
        if db is None: raise RuntimeError("first call must pass db")
        _instance = PumpFunAutoBuyer(db)
    return _instance
