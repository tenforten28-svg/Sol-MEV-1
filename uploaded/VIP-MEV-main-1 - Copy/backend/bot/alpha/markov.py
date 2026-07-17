"""
MARKOV STATE MODEL - Self-Learning Transitions
===============================================
Step 10: State-based success probability estimation.

States are defined by:
- EV_net bucket
- Crowding bucket
- Recent failure cluster
- Volatility/churn bucket

Uses transition probabilities to compute:
P_success(state, fingerprint) from recent outcomes

Then: EV_adj = P_success * profit_est - (1 - P_success) * loss_est - fees

Execute only if EV_adj > threshold.
"""

import os
import time
import math
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

logger = logging.getLogger('markov')

# ============================================================================
# CONFIG
# ============================================================================

# Feature flag
MARKOV_POLICY_ENABLED = os.environ.get('MARKOV_POLICY', 'true').lower() == 'true'

# State buckets
EV_BUCKETS = ['EV_NEG', 'EV_LOW', 'EV_MED', 'EV_HIGH']  # <0, 0-0.1, 0.1-0.5, >0.5
CROWDING_BUCKETS = ['CROWD_LOW', 'CROWD_MED', 'CROWD_HIGH']  # <0.3, 0.3-0.6, >0.6
FAILURE_BUCKETS = ['FAIL_LOW', 'FAIL_MED', 'FAIL_HIGH']  # <0.2, 0.2-0.5, >0.5
VOLATILITY_BUCKETS = ['VOL_LOW', 'VOL_MED', 'VOL_HIGH']  # Based on price change rate

# Smoothing for probability estimates
LAPLACE_SMOOTHING = 1.0

# Minimum observations for reliable estimate
MIN_OBSERVATIONS = 5

# Default success probability when no data
DEFAULT_P_SUCCESS = 0.5

# EV_adj threshold for execution
EV_ADJ_THRESHOLD = 0.01  # $0.01 minimum

# ============================================================================
# DATA CLASSES
# ============================================================================

class MarkovState(Enum):
    """Composite state for Markov model"""
    # Format: EV_CROWD_FAIL_VOL
    # We'll use a simplified 3-state model based on overall conditions
    FAVORABLE = "FAVORABLE"      # Good conditions
    NEUTRAL = "NEUTRAL"          # Mixed conditions
    UNFAVORABLE = "UNFAVORABLE"  # Poor conditions


@dataclass
class StateFeatures:
    """Features used to determine state"""
    ev_net: float
    crowding_score: float
    recent_failure_rate: float
    volatility_score: float
    fingerprint: str
    
    def to_dict(self) -> Dict:
        return {
            'ev_net': self.ev_net,
            'crowding_score': self.crowding_score,
            'recent_failure_rate': self.recent_failure_rate,
            'volatility_score': self.volatility_score,
            'fingerprint': self.fingerprint
        }


@dataclass
class StateTransition:
    """Record of a state transition"""
    from_state: MarkovState
    to_state: MarkovState
    fingerprint: str
    success: bool
    ts_ms: int


@dataclass
class MarkovDecision:
    """Decision from Markov policy"""
    should_execute: bool
    p_success: float
    ev_adj: float
    state: MarkovState
    reason: str
    breakdown: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'should_execute': self.should_execute,
            'p_success': self.p_success,
            'ev_adj': self.ev_adj,
            'state': self.state.value,
            'reason': self.reason,
            'breakdown': self.breakdown
        }


# ============================================================================
# STATE CLASSIFIER
# ============================================================================

def classify_ev_bucket(ev_net: float) -> str:
    """Classify EV into bucket"""
    if ev_net < 0:
        return 'EV_NEG'
    elif ev_net < 0.1:
        return 'EV_LOW'
    elif ev_net < 0.5:
        return 'EV_MED'
    else:
        return 'EV_HIGH'


def classify_crowding_bucket(crowding: float) -> str:
    """Classify crowding into bucket"""
    if crowding < 0.3:
        return 'CROWD_LOW'
    elif crowding < 0.6:
        return 'CROWD_MED'
    else:
        return 'CROWD_HIGH'


def classify_failure_bucket(failure_rate: float) -> str:
    """Classify failure rate into bucket"""
    if failure_rate < 0.2:
        return 'FAIL_LOW'
    elif failure_rate < 0.5:
        return 'FAIL_MED'
    else:
        return 'FAIL_HIGH'


def classify_volatility_bucket(volatility: float) -> str:
    """Classify volatility into bucket"""
    if volatility < 0.3:
        return 'VOL_LOW'
    elif volatility < 0.6:
        return 'VOL_MED'
    else:
        return 'VOL_HIGH'


def features_to_state(features: StateFeatures) -> MarkovState:
    """
    Convert features to a Markov state.
    
    Uses a scoring system to determine overall state:
    - FAVORABLE: Good EV, low crowding, low failures
    - NEUTRAL: Mixed signals
    - UNFAVORABLE: Poor EV, high crowding, high failures
    """
    score = 0
    
    # EV contribution (+2 to -2)
    if features.ev_net > 0.5:
        score += 2
    elif features.ev_net > 0.1:
        score += 1
    elif features.ev_net < 0:
        score -= 2
    
    # Crowding contribution (-2 to +1)
    if features.crowding_score < 0.3:
        score += 1
    elif features.crowding_score > 0.6:
        score -= 2
    elif features.crowding_score > 0.4:
        score -= 1
    
    # Failure rate contribution (-2 to +1)
    if features.recent_failure_rate < 0.2:
        score += 1
    elif features.recent_failure_rate > 0.5:
        score -= 2
    elif features.recent_failure_rate > 0.3:
        score -= 1
    
    # Volatility contribution (-1 to +1)
    if features.volatility_score < 0.3:
        score += 1
    elif features.volatility_score > 0.6:
        score -= 1
    
    # Map score to state
    if score >= 2:
        return MarkovState.FAVORABLE
    elif score <= -2:
        return MarkovState.UNFAVORABLE
    else:
        return MarkovState.NEUTRAL


# ============================================================================
# MARKOV MODEL
# ============================================================================

class MarkovModel:
    """
    Markov state model for success probability estimation.
    
    Tracks state transitions and outcomes to learn:
    - P(success | state, fingerprint)
    - Transition probabilities between states
    """
    
    def __init__(self):
        # Success counts per (state, fingerprint)
        self._success_counts: Dict[str, int] = defaultdict(int)
        self._total_counts: Dict[str, int] = defaultdict(int)
        
        # Global success counts per state (for fallback)
        self._global_success: Dict[MarkovState, int] = defaultdict(int)
        self._global_total: Dict[MarkovState, int] = defaultdict(int)
        
        # State transition counts
        self._transitions: Dict[str, int] = defaultdict(int)
        
        # Recent outcomes for quick stats
        self._recent_outcomes: List[Tuple[MarkovState, str, bool, int]] = []
        self._max_recent = 1000
        
        # Last state per fingerprint
        self._last_state: Dict[str, MarkovState] = {}
    
    def record_outcome(
        self,
        features: StateFeatures,
        success: bool,
        ts_ms: Optional[int] = None
    ):
        """
        Record an outcome for learning.
        
        Args:
            features: State features at decision time
            success: Whether trade succeeded
            ts_ms: Timestamp (optional)
        """
        if ts_ms is None:
            ts_ms = int(time.time() * 1000)
        
        state = features_to_state(features)
        fingerprint = features.fingerprint
        
        # Update counts
        key = f"{state.value}:{fingerprint}"
        self._total_counts[key] += 1
        if success:
            self._success_counts[key] += 1
        
        # Update global counts
        self._global_total[state] += 1
        if success:
            self._global_success[state] += 1
        
        # Record transition
        if fingerprint in self._last_state:
            prev_state = self._last_state[fingerprint]
            trans_key = f"{prev_state.value}->{state.value}"
            self._transitions[trans_key] += 1
        
        self._last_state[fingerprint] = state
        
        # Store recent outcome
        self._recent_outcomes.append((state, fingerprint, success, ts_ms))
        if len(self._recent_outcomes) > self._max_recent:
            self._recent_outcomes = self._recent_outcomes[-self._max_recent:]
    
    def get_p_success(
        self,
        state: MarkovState,
        fingerprint: str
    ) -> Tuple[float, int]:
        """
        Get success probability for state and fingerprint.
        
        Returns:
            Tuple of (probability, sample_count)
        """
        key = f"{state.value}:{fingerprint}"
        
        total = self._total_counts[key]
        successes = self._success_counts[key]
        
        if total >= MIN_OBSERVATIONS:
            # Enough fingerprint-specific data
            p = (successes + LAPLACE_SMOOTHING) / (total + 2 * LAPLACE_SMOOTHING)
            return p, total
        
        # Fall back to global state probability
        global_total = self._global_total[state]
        global_successes = self._global_success[state]
        
        if global_total >= MIN_OBSERVATIONS:
            p = (global_successes + LAPLACE_SMOOTHING) / (global_total + 2 * LAPLACE_SMOOTHING)
            return p, global_total
        
        # Not enough data - return default
        return DEFAULT_P_SUCCESS, 0
    
    def get_transition_probability(
        self,
        from_state: MarkovState,
        to_state: MarkovState
    ) -> float:
        """Get probability of transitioning between states"""
        # Count all transitions from from_state
        total = 0
        target = 0
        
        for key, count in self._transitions.items():
            if key.startswith(from_state.value):
                total += count
                if key == f"{from_state.value}->{to_state.value}":
                    target = count
        
        if total < MIN_OBSERVATIONS:
            # Equal probability
            return 1.0 / len(MarkovState)
        
        return (target + LAPLACE_SMOOTHING) / (total + len(MarkovState) * LAPLACE_SMOOTHING)
    
    def get_stats(self) -> Dict:
        """Get model statistics"""
        stats = {
            'total_outcomes': sum(self._global_total.values()),
            'by_state': {},
            'recent_count': len(self._recent_outcomes)
        }
        
        for state in MarkovState:
            total = self._global_total[state]
            successes = self._global_success[state]
            p = successes / total if total > 0 else 0
            stats['by_state'][state.value] = {
                'total': total,
                'successes': successes,
                'p_success': p
            }
        
        return stats


# ============================================================================
# MARKOV POLICY
# ============================================================================

# Global model instance
_model: Optional[MarkovModel] = None


def get_model() -> MarkovModel:
    """Get the global Markov model"""
    global _model
    if _model is None:
        _model = MarkovModel()
    return _model


def calculate_ev_adj(
    features: StateFeatures,
    profit_est: float,
    loss_est: float,
    fees: float
) -> MarkovDecision:
    """
    Calculate EV_adj using Markov model.
    
    EV_adj = P_success * profit_est - (1 - P_success) * loss_est - fees
    
    Args:
        features: Current state features
        profit_est: Expected profit if successful
        loss_est: Expected loss if failed (positive number)
        fees: Total fees
    
    Returns:
        MarkovDecision with execution recommendation
    """
    if not MARKOV_POLICY_ENABLED:
        return MarkovDecision(
            should_execute=features.ev_net > 0,
            p_success=DEFAULT_P_SUCCESS,
            ev_adj=features.ev_net,
            state=MarkovState.NEUTRAL,
            reason="MARKOV_POLICY disabled"
        )
    
    model = get_model()
    state = features_to_state(features)
    
    # Get success probability
    p_success, sample_count = model.get_p_success(state, features.fingerprint)
    
    # Calculate EV_adj
    ev_adj = p_success * profit_est - (1 - p_success) * loss_est - fees
    
    # Decision
    should_execute = ev_adj > EV_ADJ_THRESHOLD
    
    if should_execute:
        reason = f"EV_adj ${ev_adj:.3f} > threshold (P_success={p_success:.2f}, state={state.value})"
    else:
        reason = f"EV_adj ${ev_adj:.3f} <= threshold (P_success={p_success:.2f}, state={state.value})"
    
    return MarkovDecision(
        should_execute=should_execute,
        p_success=p_success,
        ev_adj=ev_adj,
        state=state,
        reason=reason,
        breakdown={
            'profit_est': profit_est,
            'loss_est': loss_est,
            'fees': fees,
            'sample_count': sample_count,
            'features': features.to_dict()
        }
    )


def record_trade_outcome(
    ev_net: float,
    crowding_score: float,
    failure_rate: float,
    volatility: float,
    fingerprint: str,
    success: bool
):
    """Record a trade outcome for learning"""
    features = StateFeatures(
        ev_net=ev_net,
        crowding_score=crowding_score,
        recent_failure_rate=failure_rate,
        volatility_score=volatility,
        fingerprint=fingerprint
    )
    get_model().record_outcome(features, success)


def get_markov_stats() -> Dict:
    """Get Markov model statistics"""
    return get_model().get_stats()


# ============================================================================
# TESTS
# ============================================================================

def test_markov():
    """Test Markov model"""
    model = MarkovModel()
    
    # Simulate some outcomes
    fingerprint = "TEST::SOL->USDC"
    
    # Favorable conditions - mostly success
    for i in range(20):
        features = StateFeatures(
            ev_net=0.6,
            crowding_score=0.2,
            recent_failure_rate=0.1,
            volatility_score=0.2,
            fingerprint=fingerprint
        )
        model.record_outcome(features, success=(i % 5 != 0))  # 80% success
    
    # Unfavorable conditions - mostly fail
    for i in range(20):
        features = StateFeatures(
            ev_net=-0.1,
            crowding_score=0.8,
            recent_failure_rate=0.6,
            volatility_score=0.7,
            fingerprint=fingerprint
        )
        model.record_outcome(features, success=(i % 5 == 0))  # 20% success
    
    # Test predictions
    favorable_features = StateFeatures(
        ev_net=0.5,
        crowding_score=0.2,
        recent_failure_rate=0.1,
        volatility_score=0.2,
        fingerprint=fingerprint
    )
    
    decision = calculate_ev_adj(
        features=favorable_features,
        profit_est=0.50,
        loss_est=0.05,
        fees=0.02
    )
    
    print(f"State: {decision.state.value}")
    print(f"P_success: {decision.p_success:.2f}")
    print(f"EV_adj: ${decision.ev_adj:.4f}")
    print(f"Should execute: {decision.should_execute}")
    print(f"Reason: {decision.reason}")
    
    # Print stats
    stats = model.get_stats()
    print(f"\nModel stats:")
    print(f"  Total outcomes: {stats['total_outcomes']}")
    for state, data in stats['by_state'].items():
        print(f"  {state}: {data['successes']}/{data['total']} = {data['p_success']:.2f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_markov()
