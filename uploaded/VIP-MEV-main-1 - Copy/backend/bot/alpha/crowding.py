"""
CROWDING SCORE - Detect Bot Competition
=======================================
Step 9: Compute crowding score to detect when other bots are competing.

High crowding = many bots competing = lower success probability.

Inputs:
- Spread decay rate over last 250-1000ms
- Pool churn (updates/sec, reserve delta/sec)
- Recent failure cluster for fingerprint

Output:
- crowding_score 0..1 (0 = low competition, 1 = highly crowded)

Gates:
- If crowding_score > 0.7 → SKIP unless EV_net is very high
- If 0.4-0.7 → reduce size / raise fee carefully
"""

import os
import time
import math
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, deque
from datetime import datetime, timedelta

logger = logging.getLogger('crowding')

# ============================================================================
# CONFIG
# ============================================================================

# Feature flag
CROWDING_GATE_ENABLED = os.environ.get('CROWDING_GATE', 'true').lower() == 'true'

# Thresholds
HIGH_CROWDING_THRESHOLD = 0.7   # Skip if above this
MEDIUM_CROWDING_THRESHOLD = 0.4  # Be cautious if above this

# Weights for crowding score components
WEIGHT_SPREAD_DECAY = 0.35
WEIGHT_POOL_CHURN = 0.25
WEIGHT_FAILURE_RATE = 0.40

# Time windows
SPREAD_DECAY_WINDOW_MS = 1000  # 1 second
POOL_CHURN_WINDOW_MS = 5000   # 5 seconds
FAILURE_WINDOW_MS = 60000     # 1 minute

# Thresholds for normalization
FAST_DECAY_RATE = 0.1         # bps/ms considered fast decay
HIGH_CHURN_UPDATES_PER_SEC = 5
HIGH_FAILURE_RATE = 0.5       # 50% failure rate

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class PoolUpdate:
    """Single pool update observation"""
    ts_ms: int
    pool_name: str
    reserve_delta: int  # Change in reserves
    price_delta: float  # Change in price


@dataclass
class SpreadDecay:
    """Spread decay observation"""
    ts_ms: int
    spread_bps: float
    fingerprint: str


@dataclass
class TradeOutcome:
    """Trade outcome for failure tracking"""
    ts_ms: int
    fingerprint: str
    success: bool
    failure_tag: Optional[str] = None


@dataclass
class CrowdingScore:
    """Crowding score result"""
    score: float  # 0-1
    spread_decay_component: float
    pool_churn_component: float
    failure_rate_component: float
    recommendation: str  # "EXECUTE", "CAUTION", "SKIP"
    details: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'score': self.score,
            'spread_decay_component': self.spread_decay_component,
            'pool_churn_component': self.pool_churn_component,
            'failure_rate_component': self.failure_rate_component,
            'recommendation': self.recommendation,
            'details': self.details
        }


@dataclass
class CrowdingDecision:
    """Crowding gate decision"""
    should_skip: bool
    should_reduce_size: bool
    should_raise_fee: bool
    score: float
    reason: str
    
    def to_dict(self) -> Dict:
        return {
            'should_skip': self.should_skip,
            'should_reduce_size': self.should_reduce_size,
            'should_raise_fee': self.should_raise_fee,
            'score': self.score,
            'reason': self.reason
        }


# ============================================================================
# CROWDING CALCULATOR
# ============================================================================

class CrowdingCalculator:
    """
    Calculates crowding score from multiple signals.
    
    High crowding indicates many bots competing for same opportunity,
    which reduces success probability and increases costs.
    """
    
    def __init__(self):
        # Recent spread observations per fingerprint
        self._spreads: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        
        # Recent pool updates per pool
        self._pool_updates: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        
        # Recent trade outcomes per fingerprint
        self._outcomes: Dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        
        # Cached scores
        self._cached_scores: Dict[str, Tuple[float, CrowdingScore]] = {}
        
        # Cache TTL (ms)
        self._cache_ttl_ms = 500
    
    def add_spread_observation(self, fingerprint: str, spread_bps: float, ts_ms: Optional[int] = None):
        """Record spread observation"""
        if ts_ms is None:
            ts_ms = int(time.time() * 1000)
        
        self._spreads[fingerprint].append(SpreadDecay(
            ts_ms=ts_ms,
            spread_bps=spread_bps,
            fingerprint=fingerprint
        ))
    
    def add_pool_update(self, pool_name: str, reserve_delta: int, price_delta: float, ts_ms: Optional[int] = None):
        """Record pool update"""
        if ts_ms is None:
            ts_ms = int(time.time() * 1000)
        
        self._pool_updates[pool_name].append(PoolUpdate(
            ts_ms=ts_ms,
            pool_name=pool_name,
            reserve_delta=reserve_delta,
            price_delta=price_delta
        ))
    
    def add_trade_outcome(self, fingerprint: str, success: bool, failure_tag: Optional[str] = None, ts_ms: Optional[int] = None):
        """Record trade outcome"""
        if ts_ms is None:
            ts_ms = int(time.time() * 1000)
        
        self._outcomes[fingerprint].append(TradeOutcome(
            ts_ms=ts_ms,
            fingerprint=fingerprint,
            success=success,
            failure_tag=failure_tag
        ))
    
    def _calculate_spread_decay_score(self, fingerprint: str, now_ms: int) -> Tuple[float, Dict]:
        """
        Calculate spread decay component.
        
        Fast spread decay = high competition = high score.
        """
        spreads = list(self._spreads.get(fingerprint, []))
        
        if len(spreads) < 3:
            return 0.0, {'reason': 'insufficient_data', 'samples': len(spreads)}
        
        # Filter to recent window
        cutoff = now_ms - SPREAD_DECAY_WINDOW_MS
        recent = [s for s in spreads if s.ts_ms >= cutoff]
        
        if len(recent) < 2:
            return 0.0, {'reason': 'no_recent_data'}
        
        # Sort by time
        recent.sort(key=lambda x: x.ts_ms)
        
        # Calculate decay rate
        first = recent[0]
        last = recent[-1]
        
        dt_ms = last.ts_ms - first.ts_ms
        if dt_ms <= 0:
            return 0.0, {'reason': 'zero_time_delta'}
        
        spread_change = first.spread_bps - last.spread_bps
        decay_rate = spread_change / dt_ms  # bps/ms
        
        # Normalize to 0-1 score
        # Fast decay (>= FAST_DECAY_RATE) = score 1.0
        score = min(1.0, max(0.0, decay_rate / FAST_DECAY_RATE))
        
        return score, {
            'decay_rate_bps_ms': decay_rate,
            'spread_start': first.spread_bps,
            'spread_end': last.spread_bps,
            'window_ms': dt_ms
        }
    
    def _calculate_pool_churn_score(self, pool_names: List[str], now_ms: int) -> Tuple[float, Dict]:
        """
        Calculate pool churn component.
        
        High update frequency = many traders = high score.
        """
        total_updates = 0
        total_reserve_delta = 0
        
        cutoff = now_ms - POOL_CHURN_WINDOW_MS
        
        for pool_name in pool_names:
            updates = list(self._pool_updates.get(pool_name, []))
            recent = [u for u in updates if u.ts_ms >= cutoff]
            
            total_updates += len(recent)
            total_reserve_delta += sum(abs(u.reserve_delta) for u in recent)
        
        # Calculate updates per second
        window_seconds = POOL_CHURN_WINDOW_MS / 1000
        updates_per_sec = total_updates / window_seconds if window_seconds > 0 else 0
        
        # Normalize to 0-1 score
        score = min(1.0, updates_per_sec / HIGH_CHURN_UPDATES_PER_SEC)
        
        return score, {
            'updates_per_sec': updates_per_sec,
            'total_updates': total_updates,
            'total_reserve_delta': total_reserve_delta,
            'window_ms': POOL_CHURN_WINDOW_MS
        }
    
    def _calculate_failure_rate_score(self, fingerprint: str, now_ms: int) -> Tuple[float, Dict]:
        """
        Calculate recent failure rate component.
        
        High recent failure rate = crowded = high score.
        """
        outcomes = list(self._outcomes.get(fingerprint, []))
        
        if len(outcomes) < 3:
            return 0.0, {'reason': 'insufficient_data', 'samples': len(outcomes)}
        
        # Filter to recent window
        cutoff = now_ms - FAILURE_WINDOW_MS
        recent = [o for o in outcomes if o.ts_ms >= cutoff]
        
        if len(recent) < 2:
            return 0.0, {'reason': 'no_recent_data'}
        
        # Calculate failure rate
        failures = sum(1 for o in recent if not o.success)
        failure_rate = failures / len(recent)
        
        # Count specific failure types that indicate competition
        competition_failures = sum(
            1 for o in recent 
            if not o.success and o.failure_tag in ['PRIORITY_LOST', 'ACCOUNT_IN_USE', 'SLIPPAGE']
        )
        competition_rate = competition_failures / len(recent)
        
        # Weight competition-related failures higher
        weighted_rate = (failure_rate * 0.5) + (competition_rate * 0.5)
        
        # Normalize to 0-1 score
        score = min(1.0, weighted_rate / HIGH_FAILURE_RATE)
        
        return score, {
            'failure_rate': failure_rate,
            'competition_rate': competition_rate,
            'total_outcomes': len(recent),
            'failures': failures,
            'competition_failures': competition_failures
        }
    
    def calculate_crowding_score(
        self,
        fingerprint: str,
        pool_names: List[str],
        force_recalculate: bool = False
    ) -> CrowdingScore:
        """
        Calculate overall crowding score.
        
        Args:
            fingerprint: Route fingerprint
            pool_names: List of pool names involved
            force_recalculate: Bypass cache
        
        Returns:
            CrowdingScore with components and recommendation
        """
        now_ms = int(time.time() * 1000)
        
        # Check cache
        cache_key = f"{fingerprint}_{','.join(sorted(pool_names))}"
        if not force_recalculate and cache_key in self._cached_scores:
            cached_ts, cached_score = self._cached_scores[cache_key]
            if now_ms - cached_ts < self._cache_ttl_ms:
                return cached_score
        
        # Calculate components
        spread_score, spread_details = self._calculate_spread_decay_score(fingerprint, now_ms)
        churn_score, churn_details = self._calculate_pool_churn_score(pool_names, now_ms)
        failure_score, failure_details = self._calculate_failure_rate_score(fingerprint, now_ms)
        
        # Weighted combination
        total_score = (
            WEIGHT_SPREAD_DECAY * spread_score +
            WEIGHT_POOL_CHURN * churn_score +
            WEIGHT_FAILURE_RATE * failure_score
        )
        
        # Determine recommendation
        if total_score >= HIGH_CROWDING_THRESHOLD:
            recommendation = "SKIP"
        elif total_score >= MEDIUM_CROWDING_THRESHOLD:
            recommendation = "CAUTION"
        else:
            recommendation = "EXECUTE"
        
        result = CrowdingScore(
            score=total_score,
            spread_decay_component=spread_score,
            pool_churn_component=churn_score,
            failure_rate_component=failure_score,
            recommendation=recommendation,
            details={
                'spread': spread_details,
                'churn': churn_details,
                'failure': failure_details
            }
        )
        
        # Cache result
        self._cached_scores[cache_key] = (now_ms, result)
        
        return result


# ============================================================================
# CROWDING GATE
# ============================================================================

# Global calculator instance
_calculator: Optional[CrowdingCalculator] = None


def get_calculator() -> CrowdingCalculator:
    """Get the global crowding calculator"""
    global _calculator
    if _calculator is None:
        _calculator = CrowdingCalculator()
    return _calculator


def check_crowding_gate(
    fingerprint: str,
    pool_names: List[str],
    ev_net: float = 0.0
) -> CrowdingDecision:
    """
    Check if opportunity should be skipped/modified due to crowding.
    
    Args:
        fingerprint: Route fingerprint
        pool_names: List of pool names involved
        ev_net: Current EV_net estimate (high EV can override crowding)
    
    Returns:
        CrowdingDecision with actions
    """
    if not CROWDING_GATE_ENABLED:
        return CrowdingDecision(
            should_skip=False,
            should_reduce_size=False,
            should_raise_fee=False,
            score=0.0,
            reason="CROWDING_GATE disabled"
        )
    
    calc = get_calculator()
    score = calc.calculate_crowding_score(fingerprint, pool_names)
    
    # High EV can override high crowding
    high_ev_threshold = 1.0  # $1 profit
    ev_override = ev_net > high_ev_threshold
    
    if score.score >= HIGH_CROWDING_THRESHOLD:
        if ev_override:
            return CrowdingDecision(
                should_skip=False,
                should_reduce_size=True,
                should_raise_fee=True,
                score=score.score,
                reason=f"High crowding ({score.score:.2f}) but high EV (${ev_net:.2f}) - proceed with caution"
            )
        else:
            return CrowdingDecision(
                should_skip=True,
                should_reduce_size=False,
                should_raise_fee=False,
                score=score.score,
                reason=f"High crowding ({score.score:.2f}) - SKIP"
            )
    
    elif score.score >= MEDIUM_CROWDING_THRESHOLD:
        return CrowdingDecision(
            should_skip=False,
            should_reduce_size=True,
            should_raise_fee=True,
            score=score.score,
            reason=f"Medium crowding ({score.score:.2f}) - reduce size and raise fee"
        )
    
    else:
        return CrowdingDecision(
            should_skip=False,
            should_reduce_size=False,
            should_raise_fee=False,
            score=score.score,
            reason=f"Low crowding ({score.score:.2f}) - proceed normally"
        )


def record_spread(fingerprint: str, spread_bps: float):
    """Record spread observation"""
    get_calculator().add_spread_observation(fingerprint, spread_bps)


def record_pool_update(pool_name: str, reserve_delta: int, price_delta: float):
    """Record pool update"""
    get_calculator().add_pool_update(pool_name, reserve_delta, price_delta)


def record_trade_outcome(fingerprint: str, success: bool, failure_tag: Optional[str] = None):
    """Record trade outcome"""
    get_calculator().add_trade_outcome(fingerprint, success, failure_tag)


def get_crowding_score(fingerprint: str, pool_names: List[str]) -> Dict:
    """Get crowding score for display"""
    calc = get_calculator()
    score = calc.calculate_crowding_score(fingerprint, pool_names)
    return score.to_dict()


# ============================================================================
# TESTS
# ============================================================================

def test_crowding():
    """Test crowding calculation"""
    calc = CrowdingCalculator()
    fingerprint = "TEST::SOL->USDC->SOL"
    pools = ["raydium_sol_usdc", "orca_sol_usdc"]
    
    base_time = int(time.time() * 1000)
    
    # Simulate rapid spread decay (high competition)
    for i in range(20):
        calc.add_spread_observation(fingerprint, 50 - i * 2, base_time + i * 50)
    
    # Simulate high pool churn
    for pool in pools:
        for i in range(30):
            calc.add_pool_update(pool, 1000000, 0.001, base_time + i * 100)
    
    # Simulate some failures
    for i in range(10):
        success = i % 3 != 0  # 33% failure rate
        tag = "PRIORITY_LOST" if not success else None
        calc.add_trade_outcome(fingerprint, success, tag, base_time + i * 5000)
    
    # Calculate score
    score = calc.calculate_crowding_score(fingerprint, pools)
    
    print(f"Crowding Score: {score.score:.2f}")
    print(f"  Spread Decay: {score.spread_decay_component:.2f}")
    print(f"  Pool Churn: {score.pool_churn_component:.2f}")
    print(f"  Failure Rate: {score.failure_rate_component:.2f}")
    print(f"  Recommendation: {score.recommendation}")
    
    # Test gate
    decision = check_crowding_gate(fingerprint, pools, ev_net=0.5)
    print(f"\nGate Decision:")
    print(f"  Skip: {decision.should_skip}")
    print(f"  Reduce Size: {decision.should_reduce_size}")
    print(f"  Raise Fee: {decision.should_raise_fee}")
    print(f"  Reason: {decision.reason}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_crowding()
