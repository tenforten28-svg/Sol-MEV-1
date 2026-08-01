"""
TX LANDINGS — shared submission/landing metrics for both bots.

Records every attempted transaction submission so we have real numbers on:
- submitted vs actually confirmed on-chain
- submit→land latency
- per-module success rate under real conditions

This is DIAGNOSTIC data. It doesn't gate anything. Use it to decide
whether Jito bundles / SWQoS / Yellowstone are worth adding later.
"""
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger("tx_landings")


class LandingTracker:
    def __init__(self, db):
        self.db = db
        # In-process rolling counters (survive until process restart)
        self.by_module: Dict[str, Dict[str, int]] = {}
        self.recent_latencies: Dict[str, list] = {}   # last 50 landings per module

    def _ctr(self, module: str) -> Dict[str, int]:
        if module not in self.by_module:
            self.by_module[module] = {
                "submits": 0,
                "landed": 0,
                "failed": 0,
                "timed_out": 0,
            }
            self.recent_latencies[module] = []
        return self.by_module[module]

    async def record(
        self,
        module: str,
        signature: Optional[str],
        submitted_at: float,
        landed_at: Optional[float],
        success: bool,
        error: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        """Persist one submission outcome. Call after your confirmation loop
        finishes (either landed, errored, or timed out).

        Classification:
          success=True + landed_at set → 'landed'
          success=False + error set    → 'failed' (submit rejected or execution reverted)
          success=False + no error     → 'timed_out' (never confirmed within deadline)"""
        ctr = self._ctr(module)
        ctr["submits"] += 1
        latency_ms = None
        if success and landed_at:
            ctr["landed"] += 1
            latency_ms = int((landed_at - submitted_at) * 1000)
            self.recent_latencies[module].append(latency_ms)
            if len(self.recent_latencies[module]) > 50:
                self.recent_latencies[module].pop(0)
        elif error:
            ctr["failed"] += 1
        else:
            ctr["timed_out"] += 1

        try:
            await self.db.tx_landings.insert_one({
                "module": module,
                "signature": signature,
                "submitted_at": datetime.fromtimestamp(submitted_at, tz=timezone.utc).isoformat(),
                "landed_at": datetime.fromtimestamp(landed_at, tz=timezone.utc).isoformat() if landed_at else None,
                "latency_ms": latency_ms,
                "success": success,
                "error": error,
                **(extra or {}),
            })
        except Exception as e:
            logger.debug(f"[tx_landings] persist failed: {e}")

    def status(self) -> Dict[str, Any]:
        out = {"modules": {}}
        for m, c in self.by_module.items():
            lat = self.recent_latencies.get(m) or []
            landing_rate = round(c["landed"] / c["submits"] * 100, 1) if c["submits"] else None
            avg_latency = round(sum(lat) / len(lat)) if lat else None
            out["modules"][m] = {
                **c,
                "landing_rate_pct": landing_rate,
                "avg_land_latency_ms": avg_latency,
                "recent_samples": len(lat),
            }
        return out


_instance: Optional[LandingTracker] = None


def get_tracker(db=None) -> LandingTracker:
    global _instance
    if _instance is None:
        if db is None:
            raise RuntimeError("first call must pass db")
        _instance = LandingTracker(db)
    return _instance
