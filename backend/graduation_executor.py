"""
GRADUATION EXECUTOR
===================
Consumes normalized graduation events from graduation_monitor and, when armed,
fires a real Jupiter buy via live_trader — because both PumpSwap and Raydium CPMM
graduation pools are routable through Jupiter (unlike pre-graduation pump.fun
bonding curves), so we reuse all existing safety gates + wallet + Jito support.

Strategy: FADE-THE-DUMP.
- Wait GRADUATION_SETTLE_DELAY seconds after detection (default 3s) so first-slot
  MEV bots dump into the initial liquidity BEFORE we enter.
- Buy at the resulting local low.
- Real price-based TP/SL via Jupiter reverse quotes every N seconds.

All disabled by default. Requires:
  GRADUATION_ENABLED=true                 (monitor gate)
  GRADUATION_EXEC_ENABLED=true            (executor gate)
  LIVE_TRADING_ENABLED=true + SIMULATION_MODE=false + wallet loaded
"""
import os
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from live_trader import get_live_trader
from graduation_monitor import SOL_MINT

logger = logging.getLogger("graduation_executor")

LAMPORTS_PER_SOL = 1_000_000_000


def _fbool(k, d=False):
    return str(os.environ.get(k, str(d))).strip().lower() in ("true", "1", "yes", "on")


def _fflt(k, d):
    try:
        return float(os.environ.get(k, d))
    except Exception:
        return d


def _fint(k, d):
    try:
        return int(os.environ.get(k, d))
    except Exception:
        return d


class GraduationExecutorConfig:
    def __init__(self):
        self.enabled = _fbool("GRADUATION_EXEC_ENABLED", False)
        self.buy_sol = _fflt("GRADUATION_BUY_SOL", 0.003)
        self.daily_budget_sol = _fflt("GRADUATION_DAILY_BUDGET_SOL", 0.02)
        self.max_concurrent = _fint("GRADUATION_MAX_CONCURRENT", 2)
        self.cooldown_sec = _fint("GRADUATION_COOLDOWN_SEC", 20)
        self.settle_delay_sec = _fint("GRADUATION_SETTLE_DELAY", 3)
        self.hold_max_seconds = _fint("GRADUATION_HOLD_MAX_SEC", 180)
        self.take_profit_mult = _fflt("GRADUATION_TAKE_PROFIT", 1.5)
        self.stop_loss_mult = _fflt("GRADUATION_STOP_LOSS", 0.7)
        self.check_interval_sec = _fint("GRADUATION_CHECK_INTERVAL", 5)
        self.min_pool_sol = _fflt("GRADUATION_MIN_POOL_SOL", 50.0)
        self.slippage_bps = _fint("GRADUATION_SLIPPAGE_BPS", 1500)  # 15% (volatile snipes)
        # Per-source enable
        self.pumpswap_enabled = _fbool("GRADUATION_EXEC_PUMPSWAP", True)
        self.bonk_enabled = _fbool("GRADUATION_EXEC_BONK", True)


class GraduationPosition:
    def __init__(self, mint: str, pool: str, source: str, buy_sol: float,
                 tokens_out: int, buy_signature: str, opened_at: float):
        self.mint = mint
        self.pool = pool
        self.source = source
        self.buy_sol = buy_sol
        self.tokens_out = tokens_out    # base units of the token we hold
        self.buy_signature = buy_signature
        self.opened_at = opened_at
        self.closed = False


class GraduationExecutor:
    def __init__(self, db):
        self.db = db
        self.cfg = GraduationExecutorConfig()
        self.lt = get_live_trader()
        self.positions: Dict[str, GraduationPosition] = {}
        self.last_buy_at = 0.0
        self.day_start = datetime.now(timezone.utc).date()
        self.day_spent_sol = 0.0
        # Metrics
        self.events_seen = 0
        self.buys_fired = 0
        self.buys_successful = 0
        self.sells_fired = 0
        self.rejects_filter = 0
        self.last_reason: Optional[str] = None
        self._monitor_task: Optional[asyncio.Task] = None

    def _reset_day_if_needed(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day_start:
            self.day_start = today
            self.day_spent_sol = 0.0

    async def start_monitor(self):
        if self._monitor_task and not self._monitor_task.done():
            return
        self._monitor_task = asyncio.create_task(self._position_loop())

    async def stop(self):
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()

    # ---------- entry point called by graduation_monitor ----------
    async def on_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Called for every detected graduation. Returns decision dict."""
        self.events_seen += 1
        self._reset_day_if_needed()

        # Gate checks
        if not self.cfg.enabled:
            self.last_reason = "exec disabled (GRADUATION_EXEC_ENABLED=false)"
            return {"ok": False, "reason": self.last_reason}
        if not self.lt.ready:
            self.last_reason = "live_trader not ready"
            return {"ok": False, "reason": self.last_reason}

        source = event.get("source")
        if source == "pumpswap" and not self.cfg.pumpswap_enabled:
            self.last_reason = "pumpswap exec disabled"
            return {"ok": False, "reason": self.last_reason}
        if source == "bonk_cpmm" and not self.cfg.bonk_enabled:
            self.last_reason = "bonk exec disabled"
            return {"ok": False, "reason": self.last_reason}

        if len(self.positions) >= self.cfg.max_concurrent:
            self.last_reason = f"max_concurrent {self.cfg.max_concurrent} open"
            return {"ok": False, "reason": self.last_reason}
        if self.day_spent_sol + self.cfg.buy_sol > self.cfg.daily_budget_sol:
            self.last_reason = f"daily budget {self.cfg.daily_budget_sol} SOL exhausted"
            return {"ok": False, "reason": self.last_reason}
        elapsed = time.time() - self.last_buy_at
        if elapsed < self.cfg.cooldown_sec:
            self.last_reason = f"cooldown {int(self.cfg.cooldown_sec - elapsed)}s"
            return {"ok": False, "reason": self.last_reason}

        # Liquidity filter
        reserves = float(event.get("reserves_sol") or 0)
        if reserves < self.cfg.min_pool_sol:
            self.rejects_filter += 1
            self.last_reason = f"low_liquidity: {reserves} SOL < min {self.cfg.min_pool_sol}"
            await self._record_event(event["mint"], "rejected",
                                     {"reason": self.last_reason, "event": event})
            return {"ok": False, "reason": self.last_reason}

        # FADE THE DUMP — settle
        await asyncio.sleep(self.cfg.settle_delay_sec)

        # Fire buy via Jupiter (works because post-graduation the mint is on a public AMM)
        mint = event["mint"]
        amount_lamports = int(self.cfg.buy_sol * LAMPORTS_PER_SOL)
        # Temporarily override slippage for volatile graduation snipes
        prev_slip = self.lt.cfg.slippage_bps
        self.lt.cfg.slippage_bps = self.cfg.slippage_bps
        try:
            result = await self.lt.execute_swap(SOL_MINT, mint, amount_lamports)
        finally:
            self.lt.cfg.slippage_bps = prev_slip

        self.buys_fired += 1
        self.last_buy_at = time.time()
        self.day_spent_sol += self.cfg.buy_sol

        if not result.get("success"):
            self.last_reason = f"buy_failed: {result.get('error')}"
            await self._record_event(mint, "buy_failed", {
                "reason": self.last_reason, "signature": result.get("signature"),
                "solscan_url": f"https://solscan.io/tx/{result.get('signature')}" if result.get("signature") else None,
                "event": event,
            })
            return {"ok": False, "reason": self.last_reason, "signature": result.get("signature")}

        # Extract tokens received from quote (we asked for slippage_bps tolerance)
        # Jupiter's execute_swap returns 'out_amount' when success
        tokens_out = 0
        try:
            tokens_out = int(result.get("out_amount") or result.get("outAmount") or 0)
        except Exception:
            tokens_out = 0

        pos = GraduationPosition(
            mint=mint, pool=event.get("pool_address", ""), source=source,
            buy_sol=self.cfg.buy_sol, tokens_out=tokens_out,
            buy_signature=result["signature"], opened_at=time.time(),
        )
        self.positions[mint] = pos
        self.buys_successful += 1
        self.last_reason = f"opened {mint[:6]}.. from {source}"

        await self._record_event(mint, "opened", {
            "source": source,
            "pool": event.get("pool_address"),
            "buy_signature": result["signature"],
            "buy_sol": self.cfg.buy_sol,
            "tokens_out": tokens_out,
            "solscan_url": f"https://solscan.io/tx/{result['signature']}",
            "reserves_sol": reserves,
        })
        return {"ok": True, "signature": result["signature"], "mint": mint}

    # ---------- position monitor loop ----------
    async def _position_loop(self):
        while True:
            try:
                await asyncio.sleep(self.cfg.check_interval_sec)
                if not self.positions or not self.lt.ready:
                    continue
                for mint, pos in list(self.positions.items()):
                    verdict = await self._evaluate(pos)
                    if verdict:
                        await self._sell(mint, verdict)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[grad-monitor] loop error: {e}")

    async def _evaluate(self, pos: GraduationPosition) -> Optional[str]:
        age = time.time() - pos.opened_at
        if age >= self.cfg.hold_max_seconds:
            return "time_limit"
        # Real price check via Jupiter reverse quote
        if pos.tokens_out <= 0:
            return None  # can't evaluate — will exit on time_limit
        try:
            quote = await self.lt.jupiter.get_quote(
                pos.mint, SOL_MINT, pos.tokens_out, self.cfg.slippage_bps
            )
            out_amount = int(quote.get("outAmount") or 0)
            sol_now = out_amount / LAMPORTS_PER_SOL
            if pos.buy_sol <= 0:
                return None
            ratio = sol_now / pos.buy_sol
            if ratio >= self.cfg.take_profit_mult:
                return f"take_profit ({ratio:.2f}x)"
            if ratio <= self.cfg.stop_loss_mult:
                return f"stop_loss ({ratio:.2f}x)"
        except Exception as e:
            logger.debug(f"[grad-eval] quote failed for {pos.mint[:6]}: {e}")
        return None

    async def _sell(self, mint: str, verdict: str):
        pos = self.positions.get(mint)
        if not pos or pos.closed:
            return
        if pos.tokens_out <= 0:
            # Nothing to sell — mark closed and record
            pos.closed = True
            self.positions.pop(mint, None)
            await self._record_event(mint, "closed", {
                "verdict": verdict + " (no tokens tracked)",
                "buy_signature": pos.buy_signature, "buy_sol": pos.buy_sol,
                "hold_seconds": time.time() - pos.opened_at,
            })
            return
        logger.info(f"[grad-sell] {mint[:6]} verdict={verdict}")
        prev_slip = self.lt.cfg.slippage_bps
        self.lt.cfg.slippage_bps = self.cfg.slippage_bps
        try:
            result = await self.lt.execute_swap(mint, SOL_MINT, pos.tokens_out)
        finally:
            self.lt.cfg.slippage_bps = prev_slip

        self.sells_fired += 1
        pos.closed = True
        sell_sig = result.get("signature")
        sol_received = 0.0
        try:
            sol_received = int(result.get("out_amount") or result.get("outAmount") or 0) / LAMPORTS_PER_SOL
        except Exception:
            pass
        pnl_sol = sol_received - pos.buy_sol
        pnl_pct = (pnl_sol / pos.buy_sol * 100) if pos.buy_sol > 0 else 0.0

        await self._record_event(mint, "closed", {
            "verdict": verdict,
            "buy_signature": pos.buy_signature,
            "sell_signature": sell_sig,
            "buy_sol": pos.buy_sol,
            "sell_sol_received": round(sol_received, 6),
            "pnl_sol": round(pnl_sol, 6),
            "pnl_pct": round(pnl_pct, 2),
            "hold_seconds": round(time.time() - pos.opened_at, 1),
            "solscan_sell": f"https://solscan.io/tx/{sell_sig}" if sell_sig else None,
            "sell_success": result.get("success", False),
        })
        # Trade row (for LiveTradingPanel visibility)
        try:
            await self.db.trades.insert_one({
                "created_at": datetime.now(timezone.utc).isoformat(),
                "pair": f"SOL->{mint[:6]}..->SOL",
                "type": "live_graduation_snipe",
                "source": pos.source,
                "amount_sol": pos.buy_sol,
                "sell_sol_received": round(sol_received, 6),
                "pnl_sol": round(pnl_sol, 6),
                "pnl_pct": round(pnl_pct, 2),
                "success": bool(result.get("success")),
                "signature": sell_sig,
                "buy_signature": pos.buy_signature,
                "solscan_url": f"https://solscan.io/tx/{sell_sig}" if sell_sig else None,
                "simulation": False,
                "mint": mint,
                "verdict": verdict,
            })
        except Exception as e:
            logger.warning(f"[grad-sell] mongo insert: {e}")
        self.positions.pop(mint, None)

    async def _record_event(self, mint: str, event: str, data: Dict):
        try:
            await self.db.graduation_positions.insert_one({
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
                "buy_sol": self.cfg.buy_sol,
                "daily_budget_sol": self.cfg.daily_budget_sol,
                "max_concurrent": self.cfg.max_concurrent,
                "cooldown_sec": self.cfg.cooldown_sec,
                "settle_delay_sec": self.cfg.settle_delay_sec,
                "hold_max_seconds": self.cfg.hold_max_seconds,
                "take_profit_mult": self.cfg.take_profit_mult,
                "stop_loss_mult": self.cfg.stop_loss_mult,
                "min_pool_sol": self.cfg.min_pool_sol,
                "slippage_bps": self.cfg.slippage_bps,
                "pumpswap_enabled": self.cfg.pumpswap_enabled,
                "bonk_enabled": self.cfg.bonk_enabled,
            },
            "counters": {
                "events_seen": self.events_seen,
                "buys_fired": self.buys_fired,
                "buys_successful": self.buys_successful,
                "sells_fired": self.sells_fired,
                "rejects_filter": self.rejects_filter,
            },
            "day_spent_sol": round(self.day_spent_sol, 6),
            "day_budget_remaining_sol": round(self.cfg.daily_budget_sol - self.day_spent_sol, 6),
            "open_positions": len(self.positions),
            "position_mints": list(self.positions.keys()),
            "last_reason": self.last_reason,
            "live_trader_ready": self.lt.ready,
            "strategy": "fade_the_dump",
        }


_instance: Optional[GraduationExecutor] = None


def get_graduation_executor(db=None) -> GraduationExecutor:
    global _instance
    if _instance is None:
        if db is None:
            raise RuntimeError("first call must pass db")
        _instance = GraduationExecutor(db)
    return _instance
