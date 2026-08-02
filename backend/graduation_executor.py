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
from exit_ladder import (
    parse_ladder, evaluate_ladder, record_milestone_hit,
    LadderState, LadderActionType, DEFAULT_LADDER_CFG, DEFAULT_RUG_STOP,
)

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
        # Legacy TP/SL retained as observability but ladder overrides them.
        self.take_profit_mult = _fflt("GRADUATION_TAKE_PROFIT", 1.5)
        self.stop_loss_mult = _fflt("GRADUATION_STOP_LOSS", 0.7)
        # Laddered exit config: "mult:pct_of_remaining:floor_after,..." (ascending mult)
        self.ladder_cfg = os.environ.get("GRADUATION_LADDER", DEFAULT_LADDER_CFG).strip()
        self.rug_stop_mult = _fflt("GRADUATION_RUG_STOP", DEFAULT_RUG_STOP)
        self.ladder = parse_ladder(self.ladder_cfg)
        # Sell-retry protection — abandons a position after N consecutive sell failures
        # (illiquid / rugged / Jupiter no-route). Prevents infinite retry loops.
        self.max_sell_failures = _fint("GRADUATION_MAX_SELL_FAILURES", 5)
        self.sell_retry_backoff_sec = _fint("GRADUATION_SELL_RETRY_BACKOFF_SEC", 30)
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
        self.tokens_out = tokens_out    # base units of the token we hold (mutable — decreases on partial sells)
        self.tokens_original = tokens_out  # never changed; for pct-of-original accounting
        self.buy_signature = buy_signature
        self.opened_at = opened_at
        self.closed = False
        # Ladder state
        self.ladder_state = LadderState()
        # For UI: history of partial-sell events
        self.partial_sells: list = []  # list of dicts with {milestone, ratio, sol_received, signature, ts}
        # Sell-retry tracking — prevents infinite retry loop when Jupiter can't route
        # (illiquid, rugged, or graduated further). After MAX_SELL_FAILS the position
        # is abandoned (removed from positions dict and recorded as abandoned).
        self.sell_failures = 0
        self.last_sell_attempt_at = 0.0


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
        self.rejects_filter = 0        # low-liquidity rejects
        self.rejects_gate = 0          # cooldown / budget / max_concurrent / disabled
        self.last_reason: Optional[str] = None
        self._monitor_task: Optional[asyncio.Task] = None
        # Serialize all buy attempts so max_concurrent/budget/cooldown checks
        # can't race with concurrent detections in the same settle window.
        self._buy_lock = asyncio.Lock()

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
        """Called for every detected graduation. Returns decision dict.
        Serialized by _buy_lock so max_concurrent/budget/cooldown checks are
        race-free even when multiple graduations arrive within the settle window."""
        async with self._buy_lock:
            return await self._on_event_locked(event)

    async def _on_event_locked(self, event: Dict[str, Any]) -> Dict[str, Any]:
        self.events_seen += 1
        self._reset_day_if_needed()

        # Gate checks
        if not self.cfg.enabled:
            self.rejects_gate += 1
            self.last_reason = "exec disabled (GRADUATION_EXEC_ENABLED=false)"
            return {"ok": False, "reason": self.last_reason}
        if not self.lt.ready:
            self.rejects_gate += 1
            self.last_reason = "live_trader not ready"
            return {"ok": False, "reason": self.last_reason}

        source = event.get("source")
        if source == "pumpswap" and not self.cfg.pumpswap_enabled:
            self.rejects_gate += 1
            self.last_reason = "pumpswap exec disabled"
            return {"ok": False, "reason": self.last_reason}
        if source == "bonk_cpmm" and not self.cfg.bonk_enabled:
            self.rejects_gate += 1
            self.last_reason = "bonk exec disabled"
            return {"ok": False, "reason": self.last_reason}

        if len(self.positions) >= self.cfg.max_concurrent:
            self.rejects_gate += 1
            self.last_reason = f"max_concurrent {self.cfg.max_concurrent} open"
            return {"ok": False, "reason": self.last_reason}
        if self.day_spent_sol + self.cfg.buy_sol > self.cfg.daily_budget_sol:
            self.rejects_gate += 1
            self.last_reason = f"daily budget {self.cfg.daily_budget_sol} SOL exhausted"
            return {"ok": False, "reason": self.last_reason}
        elapsed = time.time() - self.last_buy_at
        if elapsed < self.cfg.cooldown_sec:
            self.rejects_gate += 1
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

        # Pre-reserve slot BEFORE settle so a concurrent event can't pass max_concurrent
        mint = event["mint"]
        # Sentinel placeholder — takes a max_concurrent slot until real buy resolves
        self.positions[mint] = GraduationPosition(
            mint=mint, pool=event.get("pool_address", ""), source=source,
            buy_sol=self.cfg.buy_sol, tokens_out=0,
            buy_signature="pending", opened_at=time.time(),
        )
        self.last_buy_at = time.time()
        self.day_spent_sol += self.cfg.buy_sol

        # FADE THE DUMP — settle
        await asyncio.sleep(self.cfg.settle_delay_sec)

        # Re-check kill switch after sleep (in case emergency_stop fired during settle)
        if not self.cfg.enabled:
            self.positions.pop(mint, None)
            self.day_spent_sol -= self.cfg.buy_sol  # refund
            self.rejects_gate += 1
            self.last_reason = "kill_switch_during_settle"
            await self._record_event(mint, "rejected",
                                     {"reason": self.last_reason, "event": event})
            return {"ok": False, "reason": self.last_reason}
        if not self.lt.ready:
            self.positions.pop(mint, None)
            self.day_spent_sol -= self.cfg.buy_sol
            self.rejects_gate += 1
            self.last_reason = "live_trader_disarmed_during_settle"
            return {"ok": False, "reason": self.last_reason}

        # Fire buy via Jupiter
        from tx_landings import get_tracker
        tracker = get_tracker(self.db)
        amount_lamports = int(self.cfg.buy_sol * LAMPORTS_PER_SOL)
        prev_slip = self.lt.cfg.slippage_bps
        self.lt.cfg.slippage_bps = self.cfg.slippage_bps
        submitted_at = time.time()
        try:
            result = await self.lt.execute_swap(SOL_MINT, mint, amount_lamports)
        finally:
            self.lt.cfg.slippage_bps = prev_slip

        landed_at = time.time() if result.get("success") else None
        await tracker.record(
            "graduation_buy", result.get("signature"), submitted_at, landed_at,
            bool(result.get("success")), result.get("error"),
            extra={"mint": mint, "source": source, "reserves_sol": reserves},
        )

        self.buys_fired += 1

        if not result.get("success"):
            # Refund slot; buy failed
            self.positions.pop(mint, None)
            self.day_spent_sol -= self.cfg.buy_sol  # refund unspent budget on hard failure
            self.last_reason = f"buy_failed: {result.get('error')}"
            await self._record_event(mint, "buy_failed", {
                "reason": self.last_reason, "signature": result.get("signature"),
                "solscan_url": f"https://solscan.io/tx/{result.get('signature')}" if result.get("signature") else None,
                "event": event,
            })
            return {"ok": False, "reason": self.last_reason, "signature": result.get("signature")}

        # Fill in real position
        tokens_out = 0
        try:
            tokens_out = int(result.get("out_amount") or result.get("outAmount") or 0)
        except Exception:
            tokens_out = 0
        pos = self.positions.get(mint)
        if pos:
            pos.tokens_out = tokens_out
            pos.buy_signature = result["signature"]
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
                    # Respect sell-retry backoff — if we recently failed a sell, wait
                    # before attempting again (Jupiter routing / liquidity may recover)
                    if pos.sell_failures > 0:
                        since_last = time.time() - pos.last_sell_attempt_at
                        if since_last < self.cfg.sell_retry_backoff_sec:
                            continue
                    decision = await self._evaluate(pos)
                    if decision:
                        await self._sell(mint, decision)
                    elif pos.sell_failures > 0:
                        # Position returned HOLD — clear the retry counter so future
                        # exits (e.g. rug_stop) aren't gated by the backoff window.
                        pos.sell_failures = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[grad-monitor] loop error: {e}")

    async def _evaluate(self, pos: GraduationPosition) -> Optional[Dict[str, Any]]:
        """Returns {action, ratio, ...} for the position, or None to hold.

        Uses Jupiter reverse quote on a UNIT probe (all our current tokens) to
        determine current price relative to entry. Feeds into the exit ladder."""
        age = time.time() - pos.opened_at
        hold_expired = age >= self.cfg.hold_max_seconds
        if pos.tokens_out <= 0:
            if hold_expired:
                return {"action": "sell_all", "sell_pct": 100.0, "reason": "time_limit",
                        "ratio": None, "milestone_index": None}
            return None
        try:
            quote = await self.lt.jupiter.get_quote(
                pos.mint, SOL_MINT, pos.tokens_out, self.cfg.slippage_bps
            )
            sol_out = int(quote.get("outAmount") or 0) / LAMPORTS_PER_SOL
            if pos.buy_sol <= 0 or sol_out <= 0:
                return None
            # Value ratio: current-SOL-out (from remaining tokens) / SOL-value at entry (for that same fraction)
            # Since tokens_out shrinks after partial sells, we normalize:
            #   entry_value_of_remaining = buy_sol * (tokens_out / tokens_original)
            frac_remaining = pos.tokens_out / pos.tokens_original if pos.tokens_original else 1.0
            entry_value = pos.buy_sol * frac_remaining
            ratio = sol_out / entry_value if entry_value > 0 else 0.0
        except Exception as e:
            logger.debug(f"[grad-eval] quote failed for {pos.mint[:6]}: {e}")
            if hold_expired:
                return {"action": "sell_all", "sell_pct": 100.0, "reason": "time_limit",
                        "ratio": None, "milestone_index": None}
            return None

        action = evaluate_ladder(
            ratio=ratio,
            milestones=self.cfg.ladder,
            state=pos.ladder_state,
            rug_stop_mult=self.cfg.rug_stop_mult,
            hold_expired=hold_expired,
        )
        if action.type == LadderActionType.HOLD:
            return None
        return {
            "action": "sell_all" if action.type == LadderActionType.SELL_ALL else "sell_partial",
            "sell_pct": action.sell_pct,
            "reason": action.reason,
            "ratio": ratio,
            "milestone_index": action.milestone_index,
        }

    async def _sell(self, mint: str, decision: Dict[str, Any]):
        """Execute a partial or full sell based on ladder decision."""
        pos = self.positions.get(mint)
        if not pos or pos.closed:
            return
        if pos.tokens_out <= 0:
            pos.closed = True
            self.positions.pop(mint, None)
            return

        sell_pct = decision.get("sell_pct", 100.0)
        reason = decision.get("reason", "")
        ratio = decision.get("ratio")
        milestone_index = decision.get("milestone_index")
        is_partial = decision.get("action") == "sell_partial"

        tokens_to_sell = int(pos.tokens_out * sell_pct / 100.0)
        if tokens_to_sell <= 0:
            return

        logger.info(f"[grad-sell] {mint[:6]} {reason} sell_pct={sell_pct:.1f}% ratio={ratio}")
        from tx_landings import get_tracker
        tracker = get_tracker(self.db)
        prev_slip = self.lt.cfg.slippage_bps
        self.lt.cfg.slippage_bps = self.cfg.slippage_bps
        submitted_at = time.time()
        try:
            result = await self.lt.execute_swap(mint, SOL_MINT, tokens_to_sell)
        finally:
            self.lt.cfg.slippage_bps = prev_slip

        landed_at = time.time() if result.get("success") else None
        await tracker.record(
            "graduation_sell", result.get("signature"), submitted_at, landed_at,
            bool(result.get("success")), result.get("error"),
            extra={"mint": mint, "sell_pct": sell_pct, "reason": reason},
        )

        self.sells_fired += 1
        sol_received = 0.0
        try:
            sol_received = int(result.get("out_amount") or result.get("outAmount") or 0) / LAMPORTS_PER_SOL
        except Exception:
            pass

        if not result.get("success"):
            # Do NOT mark milestone hit — retry later, but track failures to avoid infinite loops
            pos.sell_failures += 1
            pos.last_sell_attempt_at = time.time()
            await self._record_event(mint, "sell_failed", {
                "reason": reason, "sell_pct": sell_pct, "ratio": ratio,
                "signature": result.get("signature"),
                "error": result.get("error"),
                "failure_count": pos.sell_failures,
                "solscan_url": f"https://solscan.io/tx/{result.get('signature')}" if result.get("signature") else None,
            })
            # Abandon position after MAX_SELL_FAILURES consecutive failures — token
            # is likely illiquid/rugged; keep retrying wastes RPC + spams logs.
            if pos.sell_failures >= self.cfg.max_sell_failures:
                pos.closed = True
                total_sold_sol = sum(p.get("sol_received", 0.0) for p in pos.partial_sells)
                pnl_sol = total_sold_sol - pos.buy_sol
                pnl_pct = (pnl_sol / pos.buy_sol * 100) if pos.buy_sol > 0 else 0.0
                await self._record_event(mint, "abandoned", {
                    "reason": f"exceeded {self.cfg.max_sell_failures} sell failures",
                    "last_error": result.get("error"),
                    "ratio": ratio,
                    "buy_signature": pos.buy_signature,
                    "buy_sol": pos.buy_sol,
                    "sell_sol_received": round(total_sold_sol, 6),
                    "pnl_sol": round(pnl_sol, 6),
                    "pnl_pct": round(pnl_pct, 2),
                    "hold_seconds": round(time.time() - pos.opened_at, 1),
                    "partial_sells": pos.partial_sells,
                })
                # Realized-loss trade row so cumulative PnL stays accurate
                try:
                    await self.db.trades.insert_one({
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "pair": f"SOL->{mint[:6]}..->STUCK",
                        "type": "live_graduation_snipe",
                        "source": pos.source,
                        "amount_sol": pos.buy_sol,
                        "sell_sol_received": round(total_sold_sol, 6),
                        "pnl_sol": round(pnl_sol, 6),
                        "pnl_pct": round(pnl_pct, 2),
                        "success": False,
                        "buy_signature": pos.buy_signature,
                        "simulation": False,
                        "mint": mint,
                        "verdict": "abandoned",
                        "abandoned": True,
                        "sell_failures": pos.sell_failures,
                    })
                except Exception as e:
                    logger.warning(f"[grad-sell] mongo trades insert on abandon: {e}")
                self.positions.pop(mint, None)
                logger.warning(f"[grad-sell] {mint[:6]} ABANDONED after {pos.sell_failures} sell failures")
            return

        # Success — advance state
        pos.tokens_out -= tokens_to_sell
        pos.sell_failures = 0  # reset retry counter on successful sell
        if is_partial and milestone_index is not None:
            record_milestone_hit(pos.ladder_state, self.cfg.ladder, milestone_index)

        pos.partial_sells.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "ratio": round(ratio, 3) if ratio else None,
            "sell_pct_of_current": round(sell_pct, 2),
            "sol_received": round(sol_received, 6),
            "signature": result["signature"],
            "milestone_index": milestone_index,
        })

        # If fully closed OR sell_all, finalize
        fully_closed = (not is_partial) or pos.tokens_out <= 0
        if fully_closed:
            pos.closed = True

            # Aggregate PnL from all partial sells + this final one
            total_sold_sol = sum(p["sol_received"] for p in pos.partial_sells)
            pnl_sol = total_sold_sol - pos.buy_sol
            pnl_pct = (pnl_sol / pos.buy_sol * 100) if pos.buy_sol > 0 else 0.0

            await self._record_event(mint, "closed", {
                "verdict": reason,
                "buy_signature": pos.buy_signature,
                "sell_signature": result["signature"],
                "buy_sol": pos.buy_sol,
                "sell_sol_received": round(total_sold_sol, 6),
                "pnl_sol": round(pnl_sol, 6),
                "pnl_pct": round(pnl_pct, 2),
                "peak_ratio": round(pos.ladder_state.peak_ratio, 3),
                "milestones_hit": pos.ladder_state.milestones_hit,
                "partial_sells": pos.partial_sells,
                "hold_seconds": round(time.time() - pos.opened_at, 1),
                "solscan_sell": f"https://solscan.io/tx/{result['signature']}",
                "sell_success": True,
            })
            try:
                await self.db.trades.insert_one({
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "pair": f"SOL->{mint[:6]}..->SOL",
                    "type": "live_graduation_snipe",
                    "source": pos.source,
                    "amount_sol": pos.buy_sol,
                    "sell_sol_received": round(total_sold_sol, 6),
                    "pnl_sol": round(pnl_sol, 6),
                    "pnl_pct": round(pnl_pct, 2),
                    "success": True,
                    "signature": result["signature"],
                    "buy_signature": pos.buy_signature,
                    "solscan_url": f"https://solscan.io/tx/{result['signature']}",
                    "simulation": False,
                    "mint": mint,
                    "verdict": reason,
                    "peak_ratio": round(pos.ladder_state.peak_ratio, 3),
                    "milestones_hit": len(pos.ladder_state.milestones_hit),
                })
            except Exception as e:
                logger.warning(f"[grad-sell] mongo insert: {e}")
            self.positions.pop(mint, None)
        else:
            # Partial sell — position stays open
            await self._record_event(mint, "partial_sell", {
                "reason": reason,
                "ratio": round(ratio, 3) if ratio else None,
                "sell_pct_of_current": round(sell_pct, 2),
                "sell_signature": result["signature"],
                "sol_received": round(sol_received, 6),
                "solscan_sell": f"https://solscan.io/tx/{result['signature']}",
                "milestone_index": milestone_index,
                "milestones_hit": list(pos.ladder_state.milestones_hit),
                "current_floor": pos.ladder_state.current_floor,
                "peak_ratio": round(pos.ladder_state.peak_ratio, 3),
                "tokens_remaining": pos.tokens_out,
            })

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
                "ladder": [
                    {"mult": m.mult, "sell_pct": m.sell_pct_of_remaining, "floor_after": m.floor_after}
                    for m in self.cfg.ladder
                ],
                "rug_stop_mult": self.cfg.rug_stop_mult,
                "max_sell_failures": self.cfg.max_sell_failures,
                "sell_retry_backoff_sec": self.cfg.sell_retry_backoff_sec,
            },
            "counters": {
                "events_seen": self.events_seen,
                "buys_fired": self.buys_fired,
                "buys_successful": self.buys_successful,
                "sells_fired": self.sells_fired,
                "rejects_filter": self.rejects_filter,
                "rejects_gate": self.rejects_gate,
            },
            "day_spent_sol": round(self.day_spent_sol, 6),
            "day_budget_remaining_sol": round(self.cfg.daily_budget_sol - self.day_spent_sol, 6),
            "open_positions": len(self.positions),
            "position_mints": list(self.positions.keys()),
            "last_reason": self.last_reason,
            "live_trader_ready": self.lt.ready,
            "strategy": "fade_the_dump",
            "note": "graduation buys skip pump.fun anti-rug filters — post-graduation tokens have already price-discovered on the bonding curve, so mint/freeze/dev-hold/holder-concentration checks are intentionally not applied here. Only pool-liquidity + budget/concurrency/cooldown gates run.",
        }


_instance: Optional[GraduationExecutor] = None


def get_graduation_executor(db=None) -> GraduationExecutor:
    global _instance
    if _instance is None:
        if db is None:
            raise RuntimeError("first call must pass db")
        _instance = GraduationExecutor(db)
    return _instance
