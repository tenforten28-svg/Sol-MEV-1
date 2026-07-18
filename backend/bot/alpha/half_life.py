"""
HALF-LIFE & TTL - Mean Reversion Statistics
============================================
Step 8: Compute empirical half-life per fingerprint and add TTL gating.

Half-life measures how quickly spread decays after detection.
If our latency > half_life, we're likely too late to capture the opportunity.

Gate: If latency_p90 > half_life_ms then SKIP.
"""

import os
import time
import math
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger('half_life')

# ============================================================================
# CONFIG
# ============================================================================

# Feature flag
TTL_GATE_ENABLED = os.environ.get('TTL_GATE', 'true').lower() == 'true'

# Minimum samples needed to compute half-life
MIN_SAMPLES_FOR_HALFLIFE = 10

# Default half-life if not enough data (conservative)
DEFAULT_HALF_LIFE_MS = 500

# Maximum half-life cap
MAX_HALF_LIFE_MS = 5000

# Decay measurement window (ms)
DECAY_WINDOW_MS = 2000

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class SpreadObservation:
    """Single spread observation at a point in time"""
    ts_ms: int
    spread_bps: float
    fingerprint: str
    slot: int = 0


@dataclass
class HalfLifeStats:
    """Half-life statistics for a fingerprint"""
    fingerprint: str
    half_life_ms: float
    decay_slope: float  # Spread decay rate (bps/ms)
    samples: int
    confidence: float  # 0-1, higher = more reliable
    last_updated_ts: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'fingerprint': self.fingerprint,
            'half_life_ms': self.half_life_ms,
            'decay_slope': self.decay_slope,
            'samples': self.samples,
            'confidence': self.confidence,
            'last_updated_ts': self.last_updated_ts
        }


@dataclass 
class TTLDecision:
    """TTL gate decision result"""
    should_skip: bool
    reason: str
    half_life_ms: float
    latency_p90_ms: float
    ttl_ratio: float  # latency / half_life
    
    def to_dict(self) -> Dict:
        return {
            'should_skip': self.should_skip,
            'reason': self.reason,
            'half_life_ms': self.half_life_ms,
            'latency_p90_ms': self.latency_p90_ms,
            'ttl_ratio': self.ttl_ratio
        }


# ============================================================================
# HALF-LIFE CALCULATOR
# ============================================================================

class HalfLifeCalculator:
    """
    Calculates spread half-life from historical observations.
    
    Half-life is the time for spread to decay to 50% of initial value.
    Uses exponential decay model: spread(t) = spread_0 * e^(-λt)
    Half-life = ln(2) / λ
    """
    
    def __init__(self):
        # Store recent observations per fingerprint
        self._observations: Dict[str, List[SpreadObservation]] = defaultdict(list)
        
        # Computed half-life stats
        self._stats: Dict[str, HalfLifeStats] = {}
        
        # Latency observations per fingerprint
        self._latencies: Dict[str, List[float]] = defaultdict(list)
        
        # Max observations to keep per fingerprint
        self._max_observations = 1000
    
    def add_observation(self, fingerprint: str, spread_bps: float, ts_ms: int, slot: int = 0):
        """Add a spread observation"""
        obs = SpreadObservation(
            ts_ms=ts_ms,
            spread_bps=spread_bps,
            fingerprint=fingerprint,
            slot=slot
        )
        
        self._observations[fingerprint].append(obs)
        
        # Trim if too many
        if len(self._observations[fingerprint]) > self._max_observations:
            self._observations[fingerprint] = self._observations[fingerprint][-self._max_observations:]
    
    def add_latency(self, fingerprint: str, latency_ms: float):
        """Add a latency observation for p90 calculation"""
        self._latencies[fingerprint].append(latency_ms)
        
        # Keep last 100 latencies
        if len(self._latencies[fingerprint]) > 100:
            self._latencies[fingerprint] = self._latencies[fingerprint][-100:]
    
    def compute_half_life(self, fingerprint: str) -> Optional[HalfLifeStats]:
        """
        Compute half-life for a fingerprint from observations.
        
        Uses pairs of consecutive observations to estimate decay rate.
        """
        observations = self._observations.get(fingerprint, [])
        
        if len(observations) < MIN_SAMPLES_FOR_HALFLIFE:
            return None
        
        # Sort by timestamp
        sorted_obs = sorted(observations, key=lambda x: x.ts_ms)
        
        # Calculate decay rates between consecutive observations
        decay_rates = []
        
        for i in range(1, len(sorted_obs)):
            prev = sorted_obs[i - 1]
            curr = sorted_obs[i]
            
            dt_ms = curr.ts_ms - prev.ts_ms
            
            # Skip if same timestamp or too far apart
            if dt_ms <= 0 or dt_ms > DECAY_WINDOW_MS:
                continue
            
            # Skip if spread increased (not decay)
            if curr.spread_bps >= prev.spread_bps:
                continue
            
            # Calculate decay rate (bps per ms)
            if prev.spread_bps > 0:
                # Exponential decay: spread_t = spread_0 * e^(-λt)
                # λ = -ln(spread_t / spread_0) / t
                ratio = curr.spread_bps / prev.spread_bps
                if ratio > 0 and ratio < 1:
                    lambda_rate = -math.log(ratio) / dt_ms
                    decay_rates.append(lambda_rate)
        
        if len(decay_rates) < 3:
            # Not enough decay data
            return HalfLifeStats(
                fingerprint=fingerprint,
                half_life_ms=DEFAULT_HALF_LIFE_MS,
                decay_slope=0,
                samples=len(observations),
                confidence=0.1,
                last_updated_ts=int(time.time() * 1000)
            )
        
        # Use median decay rate for robustness
        decay_rates.sort()
        median_lambda = decay_rates[len(decay_rates) // 2]
        
        # Half-life = ln(2) / λ
        if median_lambda > 0:
            half_life = math.log(2) / median_lambda
        else:
            half_life = DEFAULT_HALF_LIFE_MS
        
        # Cap half-life
        half_life = min(half_life, MAX_HALF_LIFE_MS)
        half_life = max(half_life, 50)  # Minimum 50ms
        
        # Calculate decay slope (bps/ms) for display
        if len(sorted_obs) >= 2:
            total_decay = sorted_obs[0].spread_bps - sorted_obs[-1].spread_bps
            total_time = sorted_obs[-1].ts_ms - sorted_obs[0].ts_ms
            decay_slope = total_decay / max(total_time, 1)
        else:
            decay_slope = 0
        
        # Confidence based on sample count
        confidence = min(1.0, len(decay_rates) / 50)
        
        stats = HalfLifeStats(
            fingerprint=fingerprint,
            half_life_ms=half_life,
            decay_slope=decay_slope,
            samples=len(observations),
            confidence=confidence,
            last_updated_ts=int(time.time() * 1000)
        )
        
        self._stats[fingerprint] = stats
        return stats
    
    def get_latency_p90(self, fingerprint: str) -> float:
        """Get p90 latency for a fingerprint"""
        latencies = self._latencies.get(fingerprint, [])
        
        if len(latencies) < 5:
            # Not enough data, return conservative estimate
            return 200.0  # 200ms default
        
        sorted_latencies = sorted(latencies)
        p90_idx = int(len(sorted_latencies) * 0.9)
        return sorted_latencies[p90_idx]
    
    def get_stats(self, fingerprint: str) -> Optional[HalfLifeStats]:
        """Get cached stats or compute if needed"""
        if fingerprint not in self._stats:
            return self.compute_half_life(fingerprint)
        return self._stats.get(fingerprint)


# ============================================================================
# TTL GATE
# ============================================================================

# Global calculator instance
_calculator: Optional[HalfLifeCalculator] = None


def get_calculator() -> HalfLifeCalculator:
    """Get the global half-life calculator"""
    global _calculator
    if _calculator is None:
        _calculator = HalfLifeCalculator()
    return _calculator


def check_ttl_gate(
    fingerprint: str,
    current_latency_ms: Optional[float] = None
) -> TTLDecision:
    """
    Check if opportunity should be skipped due to TTL.
    
    Gate: If latency_p90 > half_life_ms then SKIP.
    
    Args:
        fingerprint: Route fingerprint
        current_latency_ms: Current detection latency (optional)
    
    Returns:
        TTLDecision with skip recommendation
    """
    if not TTL_GATE_ENABLED:
        return TTLDecision(
            should_skip=False,
            reason="TTL_GATE disabled",
            half_life_ms=0,
            latency_p90_ms=0,
            ttl_ratio=0
        )
    
    calc = get_calculator()
    
    # Get half-life stats
    stats = calc.get_stats(fingerprint)
    half_life_ms = stats.half_life_ms if stats else DEFAULT_HALF_LIFE_MS
    
    # Get p90 latency
    latency_p90 = calc.get_latency_p90(fingerprint)
    
    # Use current latency if provided and higher
    if current_latency_ms and current_latency_ms > latency_p90:
        latency_p90 = current_latency_ms
    
    # Calculate ratio
    ttl_ratio = latency_p90 / half_life_ms if half_life_ms > 0 else 999
    
    # Decision: skip if latency > half_life
    should_skip = ttl_ratio > 1.0
    
    if should_skip:
        reason = f"TTL exceeded: latency_p90 ({latency_p90:.0f}ms) > half_life ({half_life_ms:.0f}ms)"
    else:
        reason = f"TTL OK: latency_p90 ({latency_p90:.0f}ms) <= half_life ({half_life_ms:.0f}ms)"
    
    return TTLDecision(
        should_skip=should_skip,
        reason=reason,
        half_life_ms=half_life_ms,
        latency_p90_ms=latency_p90,
        ttl_ratio=ttl_ratio
    )


def record_spread_observation(fingerprint: str, spread_bps: float, ts_ms: Optional[int] = None):
    """Record a spread observation for half-life calculation"""
    calc = get_calculator()
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
    calc.add_observation(fingerprint, spread_bps, ts_ms)


def record_latency(fingerprint: str, latency_ms: float):
    """Record a latency observation for p90 calculation"""
    calc = get_calculator()
    calc.add_latency(fingerprint, latency_ms)


def get_half_life_stats(fingerprint: str) -> Optional[Dict]:
    """Get half-life stats for a fingerprint"""
    calc = get_calculator()
    stats = calc.get_stats(fingerprint)
    return stats.to_dict() if stats else None


# ============================================================================
# TESTS
# ============================================================================

def test_half_life():
    """Test half-life calculation"""
    calc = HalfLifeCalculator()
    fingerprint = "TEST::SOL->USDC->SOL"
    
    # Simulate decaying spread over time
    base_time = int(time.time() * 1000)
    spreads = [
        (0, 50.0),    # t=0, spread=50 bps
        (100, 35.0),  # t=100ms, spread=35 bps
        (200, 25.0),  # t=200ms, spread=25 bps
        (300, 18.0),  # t=300ms, spread=18 bps
        (400, 13.0),  # t=400ms, spread=13 bps
        (500, 10.0),  # t=500ms, spread=10 bps
    ]
    
    for dt, spread in spreads:
        calc.add_observation(fingerprint, spread, base_time + dt)
    
    # Need more samples
    for i in range(20):
        calc.add_observation(fingerprint, 50 - i * 2, base_time + i * 50)
    
    stats = calc.compute_half_life(fingerprint)
    
    if stats:
        print(f"Half-life: {stats.half_life_ms:.1f} ms")
        print(f"Decay slope: {stats.decay_slope:.4f} bps/ms")
        print(f"Samples: {stats.samples}")
        print(f"Confidence: {stats.confidence:.2f}")
    else:
        print("Not enough data for half-life calculation")
    
    # Test TTL gate
    calc.add_latency(fingerprint, 150)
    calc.add_latency(fingerprint, 180)
    calc.add_latency(fingerprint, 200)
    calc.add_latency(fingerprint, 250)
    calc.add_latency(fingerprint, 300)
    
    decision = check_ttl_gate(fingerprint)
    print(f"\nTTL Decision: {'SKIP' if decision.should_skip else 'OK'}")
    print(f"Reason: {decision.reason}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_half_life()
