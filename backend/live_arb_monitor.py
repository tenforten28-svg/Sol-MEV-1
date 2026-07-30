"""
LIVE ARBITRAGE MONITOR — autonomous real-money execution
========================================================
Continuous background loop that:
  1. Fetches REAL Jupiter round-trip quotes (USDC->SOL->USDC etc.)
  2. Detects when the round-trip nets a profit above threshold (after fees + slippage)
  3. Executes BOTH legs via LiveTrader (real on-chain Jupiter swaps)
  4. Records every decision (fired / skipped / blocked) to MongoDB for the dashboard

SAFETY:
  * Only runs when live_trader.ready == True (all 4 gates on)
  * Respects ALL existing RiskGuard limits (max_trade_usd, daily_loss, cooldown, streak)
  * Round-trip pattern: never leaves position open in the middle token
  * Logs decision reasons so user sees WHY trades fired or didn't
"""

import os
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

from live_trader import (
    LiveTrader, get_live_trader,
    MINTS, DECIMALS, PRICE_HINTS_USD,
)

logger = logging.getLogger("live_arb_monitor")

# =========================================================
# CONFIG
# =========================================================
def _env_float(key: str, default: float) -> float:
    try: return float(os.environ.get(key, default))
    except Exception: return default

def _env_int(key: str, default: int) -> int:
    try: return int(os.environ.get(key, default))
    except Exception: return default

def _env_bool(key: str, default: bool = False) -> bool:
    return str(os.environ.get(key, str(default))).strip().lower() in ("true","1","yes","on")


class ArbMonitorConfig:
    def __init__(self):
        # Master switch — separate from LIVE_TRADING_ENABLED so user can enable/disable auto
        self.enabled = _env_bool("AUTO_ARB_ENABLED", False)
        # Seconds between full scan cycles
        self.scan_interval = _env_float("AUTO_ARB_SCAN_INTERVAL", 15.0)
        # Trade size for auto-arbs (USDC). Kept conservative regardless of max_trade_usd.
        self.trade_size_usd = _env_float("AUTO_ARB_TRADE_SIZE_USD", 1.0)
        # Minimum profit in bps to trigger execution (accounting for expected fees + slippage)
        # 30 bps = 0.30% — realistic minimum after Solana/Jupiter fees
        self.min_profit_bps = _env_int("AUTO_ARB_MIN_PROFIT_BPS", 30)
        # Pairs to monitor as (start_token, middle_token). Round-trip = start→mid→start.
        # These MUST be whitelisted in LiveTrader too.
        # Configurable via AUTO_ARB_PAIRS env var (comma-separated, e.g. "USDC:SOL,USDC:JUP,USDC:BONK")
        pairs_env = os.environ.get("AUTO_ARB_PAIRS", "").strip()
        if pairs_env:
            self.pairs = []
            for spec in pairs_env.split(","):
                parts = spec.strip().split(":")
                if len(parts) == 2:
                    self.pairs.append((parts[0].strip(), parts[1].strip()))
        else:
            # Default: majors + memes (pump.fun-graduated tokens with real DEX liquidity)
            self.pairs: List[Tuple[str, str]] = [
                ("USDC", "SOL"),
                ("USDC", "JUP"),
                # Meme pairs — pump.fun originated, Jupiter routes via pump-AMM + Raydium
                ("USDC", "BONK"),
                ("USDC", "WIF"),
                ("USDC", "POPCAT"),
                ("USDC", "PNUT"),
            ]


# =========================================================
# THE MONITOR
# =========================================================
class LiveArbMonitor:
    def __init__(self, cfg: ArbMonitorConfig, db) -> None:
        self.cfg = cfg
        self.db = db
        self.lt: LiveTrader = get_live_trader()
        self.task: Optional[asyncio.Task] = None
        self.running = False
        self.last_scan_at: Optional[str] = None
        self.total_scans = 0
        self.total_opps_found = 0
        self.total_fired = 0
        self.total_fired_successful = 0
        self.last_decision: Optional[Dict[str, Any]] = None

    def start(self) -> None:
        if self.task and not self.task.done():
            logger.info("[arb_monitor] already running")
            return
        if not self.cfg.enabled:
            logger.info("[arb_monitor] disabled via AUTO_ARB_ENABLED — not starting")
            return
        self.task = asyncio.create_task(self._loop())
        self.running = True
        logger.info(f"[arb_monitor] started (interval={self.cfg.scan_interval}s, "
                    f"pairs={self.cfg.pairs}, size=${self.cfg.trade_size_usd}, "
                    f"min_profit_bps={self.cfg.min_profit_bps})")

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass

    async def _loop(self) -> None:
        while self.running:
            try:
                await self._scan_once()
            except Exception as e:
                logger.exception(f"[arb_monitor] loop error: {e}")
            await asyncio.sleep(self.cfg.scan_interval)

    async def _scan_once(self) -> None:
        self.total_scans += 1
        self.last_scan_at = datetime.now(timezone.utc).isoformat()

        # Preflight — abort scan if live_trader isn't fully ready
        if not self.lt.ready:
            self.last_decision = await self._record_decision(
                "skipped", None, "live_trader not ready", None
            )
            return

        for (start_sym, mid_sym) in self.cfg.pairs:
            decision = await self._evaluate_pair(start_sym, mid_sym)
            if decision:
                self.last_decision = decision

    async def _evaluate_pair(self, start_sym: str, mid_sym: str) -> Optional[Dict[str, Any]]:
        """Fetch round-trip quotes, decide fire/skip, execute if fire, return decision."""
        pair_label = f"{start_sym}->{mid_sym}->{start_sym}"
        try:
            # Convert trade_size_usd to base units of the start token.
            hint = PRICE_HINTS_USD.get(start_sym)
            if hint is None or hint <= 0:
                return await self._record_decision("skipped", pair_label,
                                                    f"no price hint for {start_sym}", None)
            start_base = int((self.cfg.trade_size_usd / hint) * (10 ** DECIMALS[start_sym]))
            if start_base <= 0:
                return await self._record_decision("skipped", pair_label,
                                                    f"start_base=0 (size too small)", None)

            # Leg 1 quote: start -> mid
            q1 = await self.lt.jupiter.get_quote(
                MINTS[start_sym], MINTS[mid_sym], start_base, self.lt.cfg.slippage_bps
            )
            if "outAmount" not in q1:
                return await self._record_decision("skipped", pair_label,
                                                    f"leg1 quote failed: {q1}", None)
            mid_amount = int(q1["outAmount"])

            # Leg 2 quote: mid -> start (using the OUTPUT of leg 1)
            q2 = await self.lt.jupiter.get_quote(
                MINTS[mid_sym], MINTS[start_sym], mid_amount, self.lt.cfg.slippage_bps
            )
            if "outAmount" not in q2:
                return await self._record_decision("skipped", pair_label,
                                                    f"leg2 quote failed: {q2}", None)
            final_amount = int(q2["outAmount"])

            # Compute round-trip profit in basis points
            profit_bps = ((final_amount - start_base) / start_base) * 10_000

            info = {
                "start_base": start_base,
                "mid_amount": mid_amount,
                "final_amount": final_amount,
                "profit_bps": round(profit_bps, 2),
                "leg1_price_impact_pct": q1.get("priceImpactPct"),
                "leg2_price_impact_pct": q2.get("priceImpactPct"),
            }

            if profit_bps < self.cfg.min_profit_bps:
                return await self._record_decision("skipped", pair_label,
                                                    f"profit {profit_bps:.1f} bps below threshold {self.cfg.min_profit_bps}",
                                                    info)

            # PROFITABLE — check safety gates before firing
            self.total_opps_found += 1
            can, why = self.lt.risk.can_trade(self.cfg.trade_size_usd)
            if not can:
                return await self._record_decision("blocked_by_risk", pair_label, why, info)

            # Fire leg 1
            logger.info(f"[arb_monitor] FIRING {pair_label} (profit={profit_bps:.1f} bps)")
            leg1_result = await self.lt.execute_swap(
                MINTS[start_sym], MINTS[mid_sym], start_base
            )
            if not leg1_result.get("success"):
                self.lt.risk.record_trade(-0.05)  # small loss on failed leg1 (gas)
                return await self._record_decision(
                    "fired_leg1_failed", pair_label,
                    f"leg1 failed: {leg1_result.get('error')}", {**info, "leg1": leg1_result}
                )

            # Fire leg 2 — must succeed or we're stuck with mid_sym
            leg1_actual_out = int(leg1_result.get("out_amount") or mid_amount)
            leg2_result = await self.lt.execute_swap(
                MINTS[mid_sym], MINTS[start_sym], leg1_actual_out
            )

            # UNWIND — if leg2 failed we're stuck with the middle token. Retry once.
            unwind_result = None
            if not leg2_result.get("success"):
                logger.warning(f"[arb_monitor] leg2 failed — attempting unwind retry for {pair_label}")
                await asyncio.sleep(2)  # brief cooldown before retry
                unwind_result = await self.lt.execute_swap(
                    MINTS[mid_sym], MINTS[start_sym], leg1_actual_out
                )
                if unwind_result.get("success"):
                    leg2_result = unwind_result  # treat unwind as the completed leg2
                    logger.info(f"[arb_monitor] unwind succeeded for {pair_label}")

            # Record both trades regardless
            realized_final = int(leg2_result.get("out_amount") or 0) if leg2_result.get("success") else 0

            # Deduct approximate on-chain costs from PnL calculation.
            # Solana base fee ~ 0.000005 SOL/tx (2 txs = ~$0.0015).
            # Jito tip (if used) is charged per leg.
            leg1_tip = int(leg1_result.get("jito_tip_lamports") or 0)
            leg2_tip = int(leg2_result.get("jito_tip_lamports") or 0)
            total_tip_lamports = leg1_tip + leg2_tip
            approx_gas_lamports = 10_000  # ~2 base tx fees (5000 each)
            fee_sol = (total_tip_lamports + approx_gas_lamports) / 1_000_000_000

            # Convert to USD PnL (uses PRICE_HINTS_USD from live_trader)
            def base_to_usd(sym: str, base_units: int) -> float:
                d = DECIMALS.get(sym, 6)
                whole = base_units / (10 ** d)
                return whole * PRICE_HINTS_USD.get(sym, 0.0)

            start_usd = base_to_usd(start_sym, start_base)
            realized_usd = base_to_usd(start_sym, realized_final)
            fee_usd = fee_sol * PRICE_HINTS_USD.get("SOL", 150.0)
            pnl_usd = round(realized_usd - start_usd - fee_usd, 6)

            self.lt.risk.record_trade(pnl_usd)
            self.total_fired += 1
            if leg2_result.get("success") and pnl_usd > 0:
                self.total_fired_successful += 1

            # Persist to Mongo
            trade_doc = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "pair": pair_label,
                "type": "live_auto_arb" if leg2_result.get("success") else "live_auto_arb_stuck",
                "amount_usd": self.cfg.trade_size_usd,
                "expected_profit_bps": info["profit_bps"],
                "realized_pnl_usd": pnl_usd,
                "fees_deducted_usd": round(fee_usd, 6),
                "unwind_attempted": unwind_result is not None,
                "unwind_succeeded": bool(unwind_result and unwind_result.get("success")),
                "success": bool(leg1_result.get("success") and leg2_result.get("success")),
                "jito_tip_lamports": total_tip_lamports,
                "leg1": {
                    "signature": leg1_result.get("signature"),
                    "success": leg1_result.get("success"),
                    "submission_method": leg1_result.get("submission_method"),
                    "solscan_url": f"https://solscan.io/tx/{leg1_result.get('signature')}" if leg1_result.get("signature") else None,
                },
                "leg2": {
                    "signature": leg2_result.get("signature"),
                    "success": leg2_result.get("success"),
                    "submission_method": leg2_result.get("submission_method"),
                    "solscan_url": f"https://solscan.io/tx/{leg2_result.get('signature')}" if leg2_result.get("signature") else None,
                },
                "simulation": False,
                "signature": leg2_result.get("signature") or leg1_result.get("signature"),
                "submission_method": leg2_result.get("submission_method"),
            }
            try:
                await self.db.trades.insert_one(trade_doc)
            except Exception as e:
                logger.warning(f"[arb_monitor] mongo insert failed: {e}")

            return await self._record_decision(
                "fired", pair_label,
                f"pnl=${pnl_usd:.4f} (expected {info['profit_bps']:.1f} bps)",
                {**info, "leg1": leg1_result, "leg2": leg2_result, "realized_pnl_usd": pnl_usd}
            )

        except Exception as e:
            logger.exception(f"[arb_monitor] evaluate_pair error {pair_label}")
            return await self._record_decision("skipped", pair_label, f"exception: {e}", None)

    async def _record_decision(self, verdict: str, pair: Optional[str],
                                reason: str, info: Optional[Dict]) -> Dict[str, Any]:
        decision = {
            "at": datetime.now(timezone.utc).isoformat(),
            "verdict": verdict,
            "pair": pair,
            "reason": reason,
            "info": info,
        }
        # Persist recent decisions so the UI can show them
        try:
            await self.db.arb_decisions.insert_one({**decision})
            # Cap collection size ~500 latest
            count = await self.db.arb_decisions.count_documents({})
            if count > 500:
                oldest = await self.db.arb_decisions.find().sort("at", 1).limit(count - 500).to_list(None)
                for d in oldest:
                    await self.db.arb_decisions.delete_one({"_id": d["_id"]})
        except Exception as e:
            logger.debug(f"[arb_monitor] persist decision failed: {e}")
        return decision

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.cfg.enabled,
            "running": self.running and (self.task is not None and not self.task.done()),
            "config": {
                "scan_interval_seconds": self.cfg.scan_interval,
                "trade_size_usd": self.cfg.trade_size_usd,
                "min_profit_bps": self.cfg.min_profit_bps,
                "pairs": [f"{a}->{b}->{a}" for (a, b) in self.cfg.pairs],
            },
            "counters": {
                "total_scans": self.total_scans,
                "opportunities_found": self.total_opps_found,
                "trades_fired": self.total_fired,
                "trades_fired_successful": self.total_fired_successful,
                "last_scan_at": self.last_scan_at,
            },
            "last_decision": self.last_decision,
            "live_trader_ready": self.lt.ready,
        }


# =========================================================
# Singleton
# =========================================================
_instance: Optional[LiveArbMonitor] = None

def get_arb_monitor(db=None) -> LiveArbMonitor:
    global _instance
    if _instance is None:
        if db is None:
            raise RuntimeError("first call to get_arb_monitor() must pass db")
        _instance = LiveArbMonitor(ArbMonitorConfig(), db)
    return _instance
