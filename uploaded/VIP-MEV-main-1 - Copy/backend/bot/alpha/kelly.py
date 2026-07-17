"""
FRACTIONAL KELLY SIZING - Risk Engine
=====================================
Step 12: Position sizing and fee aggressiveness using Kelly criterion.

Kelly criterion gives optimal bet size for maximizing long-term growth:
f* = (p * b - q) / b

Where:
- p = probability of winning
- q = probability of losing (1 - p)
- b = win/loss ratio (profit if win / loss if lose)

We use fractional Kelly (0.1-0.25x) to reduce variance.

Outputs:
- size_multiplier: Scale factor for trade size (0.0 - 1.0)
- fee_multiplier: Scale factor for priority fee (0.5 - 2.0)
"""

import os
import math
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger('kelly')

# ============================================================================
# CONFIG
# ============================================================================

# Feature flag
KELLY_SIZING_ENABLED = os.environ.get('KELLY_SIZING', 'true').lower() == 'true'

# Kelly fraction (use 10-25% of full Kelly for safety)
KELLY_FRACTION = 0.15  # 15% of full Kelly

# Bounds
MIN_SIZE_MULTIPLIER = 0.1   # Never go below 10% of base size
MAX_SIZE_MULTIPLIER = 1.0   # Never exceed base size
MIN_FEE_MULTIPLIER = 0.5    # Minimum fee is 50% of base
MAX_FEE_MULTIPLIER = 2.0    # Maximum fee is 200% of base

# Risk limits
MAX_POSITION_USD = 5000     # Absolute maximum position
MAX_DAILY_LOSS_USD = 100    # Stop trading after this much daily loss
MAX_CONSECUTIVE_LOSSES = 5  # Reduce size after consecutive losses

# Drawdown protection
DRAWDOWN_REDUCTION_THRESHOLD = 0.1  # 10% drawdown triggers size reduction
DRAWDOWN_SIZE_REDUCTION = 0.5       # Reduce size by 50% during drawdown

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class KellyResult:
    """Result of Kelly sizing calculation"""
    full_kelly: float           # Full Kelly fraction
    fractional_kelly: float     # Adjusted Kelly (with fraction)
    size_multiplier: float      # Final size multiplier
    fee_multiplier: float       # Fee aggressiveness multiplier
    recommended_size_usd: float # Recommended trade size in USD
    recommended_fee_lamports: int # Recommended priority fee
    reason: str
    breakdown: Dict
    
    def to_dict(self) -> Dict:
        return {
            'full_kelly': self.full_kelly,
            'fractional_kelly': self.fractional_kelly,
            'size_multiplier': self.size_multiplier,
            'fee_multiplier': self.fee_multiplier,
            'recommended_size_usd': self.recommended_size_usd,
            'recommended_fee_lamports': self.recommended_fee_lamports,
            'reason': self.reason,
            'breakdown': self.breakdown
        }


@dataclass
class RiskState:
    """Current risk state"""
    daily_pnl_usd: float = 0.0
    consecutive_losses: int = 0
    peak_balance_usd: float = 0.0
    current_balance_usd: float = 0.0
    trades_today: int = 0
    wins_today: int = 0
    losses_today: int = 0
    
    @property
    def drawdown_pct(self) -> float:
        """Current drawdown as percentage"""
        if self.peak_balance_usd <= 0:
            return 0.0
        return (self.peak_balance_usd - self.current_balance_usd) / self.peak_balance_usd
    
    @property
    def win_rate_today(self) -> float:
        """Win rate for today"""
        if self.trades_today == 0:
            return 0.5
        return self.wins_today / self.trades_today
    
    def to_dict(self) -> Dict:
        return {
            'daily_pnl_usd': self.daily_pnl_usd,
            'consecutive_losses': self.consecutive_losses,
            'drawdown_pct': self.drawdown_pct,
            'trades_today': self.trades_today,
            'win_rate_today': self.win_rate_today
        }


# ============================================================================
# KELLY CALCULATIONS
# ============================================================================

def calculate_kelly_fraction(
    p_success: float,
    profit_if_win: float,
    loss_if_lose: float
) -> float:
    """
    Calculate Kelly criterion fraction.
    
    f* = (p * b - q) / b
    
    Where b = profit_if_win / loss_if_lose
    
    Args:
        p_success: Probability of success (0-1)
        profit_if_win: Expected profit in USD if successful
        loss_if_lose: Expected loss in USD if failed (positive number)
    
    Returns:
        Kelly fraction (can be negative if edge is negative)
    """
    if loss_if_lose <= 0:
        return 0.0
    
    q = 1 - p_success
    b = profit_if_win / loss_if_lose
    
    if b <= 0:
        return 0.0
    
    kelly = (p_success * b - q) / b
    
    return kelly


def calculate_optimal_size(
    p_success: float,
    profit_if_win: float,
    loss_if_lose: float,
    base_size_usd: float,
    risk_state: Optional[RiskState] = None
) -> KellyResult:
    """
    Calculate optimal position size using fractional Kelly.
    
    Args:
        p_success: Probability of success
        profit_if_win: Expected profit if successful
        loss_if_lose: Expected loss if failed
        base_size_usd: Base trade size in USD
        risk_state: Current risk state (optional)
    
    Returns:
        KellyResult with sizing recommendations
    """
    if not KELLY_SIZING_ENABLED:
        return KellyResult(
            full_kelly=0.0,
            fractional_kelly=0.0,
            size_multiplier=1.0,
            fee_multiplier=1.0,
            recommended_size_usd=base_size_usd,
            recommended_fee_lamports=50000,
            reason="KELLY_SIZING disabled",
            breakdown={}
        )
    
    # Calculate full Kelly
    full_kelly = calculate_kelly_fraction(p_success, profit_if_win, loss_if_lose)
    
    # Apply fractional Kelly
    fractional_kelly = full_kelly * KELLY_FRACTION
    
    # Start with fractional Kelly as size multiplier
    size_multiplier = fractional_kelly
    
    # Apply risk state adjustments
    adjustments = []
    
    if risk_state:
        # Drawdown protection
        if risk_state.drawdown_pct >= DRAWDOWN_REDUCTION_THRESHOLD:
            size_multiplier *= DRAWDOWN_SIZE_REDUCTION
            adjustments.append(f"drawdown_reduction_{DRAWDOWN_SIZE_REDUCTION}")
        
        # Consecutive loss protection
        if risk_state.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            size_multiplier *= 0.5
            adjustments.append("consecutive_loss_reduction")
        
        # Daily loss limit
        if risk_state.daily_pnl_usd <= -MAX_DAILY_LOSS_USD:
            size_multiplier = 0.0
            adjustments.append("daily_loss_limit_hit")
    
    # Apply bounds
    size_multiplier = max(MIN_SIZE_MULTIPLIER, min(MAX_SIZE_MULTIPLIER, size_multiplier))
    
    # Handle negative Kelly (no edge)
    if full_kelly <= 0:
        size_multiplier = 0.0
        adjustments.append("no_edge")
    
    # Calculate fee multiplier based on edge quality
    if full_kelly > 0.1:  # Strong edge
        fee_multiplier = 1.5
    elif full_kelly > 0.05:  # Moderate edge
        fee_multiplier = 1.2
    elif full_kelly > 0:  # Weak edge
        fee_multiplier = 1.0
    else:  # No edge
        fee_multiplier = 0.5
    
    # Adjust fee for competition
    if risk_state and risk_state.consecutive_losses >= 3:
        fee_multiplier *= 1.2  # Increase fee after losses (might be competition)
    
    fee_multiplier = max(MIN_FEE_MULTIPLIER, min(MAX_FEE_MULTIPLIER, fee_multiplier))
    
    # Calculate final values
    recommended_size = base_size_usd * size_multiplier
    recommended_size = min(recommended_size, MAX_POSITION_USD)
    
    # Base fee is 50,000 lamports
    base_fee = 50000
    recommended_fee = int(base_fee * fee_multiplier)
    
    # Build reason string
    if size_multiplier == 0:
        reason = "SKIP: " + ", ".join(adjustments) if adjustments else "no edge"
    elif adjustments:
        reason = f"Adjusted: {', '.join(adjustments)}"
    else:
        reason = f"Kelly sizing: {fractional_kelly:.3f}"
    
    return KellyResult(
        full_kelly=full_kelly,
        fractional_kelly=fractional_kelly,
        size_multiplier=size_multiplier,
        fee_multiplier=fee_multiplier,
        recommended_size_usd=recommended_size,
        recommended_fee_lamports=recommended_fee,
        reason=reason,
        breakdown={
            'p_success': p_success,
            'profit_if_win': profit_if_win,
            'loss_if_lose': loss_if_lose,
            'base_size_usd': base_size_usd,
            'adjustments': adjustments,
            'risk_state': risk_state.to_dict() if risk_state else None
        }
    )


# ============================================================================
# RISK STATE MANAGEMENT
# ============================================================================

_risk_state: Optional[RiskState] = None


def get_risk_state() -> RiskState:
    """Get current risk state"""
    global _risk_state
    if _risk_state is None:
        _risk_state = RiskState()
    return _risk_state


def update_risk_state(
    pnl_usd: float,
    success: bool,
    current_balance_usd: Optional[float] = None
):
    """
    Update risk state after a trade.
    
    Args:
        pnl_usd: Profit/loss from the trade
        success: Whether trade was successful
        current_balance_usd: Current balance (optional)
    """
    state = get_risk_state()
    
    state.daily_pnl_usd += pnl_usd
    state.trades_today += 1
    
    if success:
        state.wins_today += 1
        state.consecutive_losses = 0
    else:
        state.losses_today += 1
        state.consecutive_losses += 1
    
    if current_balance_usd is not None:
        state.current_balance_usd = current_balance_usd
        state.peak_balance_usd = max(state.peak_balance_usd, current_balance_usd)


def reset_daily_risk_state():
    """Reset daily counters (call at start of day)"""
    state = get_risk_state()
    state.daily_pnl_usd = 0.0
    state.trades_today = 0
    state.wins_today = 0
    state.losses_today = 0
    # Don't reset consecutive_losses or drawdown


def should_stop_trading() -> Tuple[bool, str]:
    """
    Check if trading should stop due to risk limits.
    
    Returns:
        Tuple of (should_stop, reason)
    """
    state = get_risk_state()
    
    if state.daily_pnl_usd <= -MAX_DAILY_LOSS_USD:
        return True, f"Daily loss limit hit: ${state.daily_pnl_usd:.2f}"
    
    if state.consecutive_losses >= MAX_CONSECUTIVE_LOSSES * 2:
        return True, f"Too many consecutive losses: {state.consecutive_losses}"
    
    if state.drawdown_pct >= 0.2:  # 20% drawdown
        return True, f"Drawdown too high: {state.drawdown_pct:.1%}"
    
    return False, "OK"


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def get_kelly_sizing(
    p_success: float,
    expected_profit_usd: float,
    expected_loss_usd: float,
    base_size_usd: float = 1000
) -> KellyResult:
    """
    Convenience function for Kelly sizing.
    
    Args:
        p_success: Probability of success
        expected_profit_usd: Expected profit if successful
        expected_loss_usd: Expected loss if failed
        base_size_usd: Base trade size
    
    Returns:
        KellyResult with recommendations
    """
    return calculate_optimal_size(
        p_success=p_success,
        profit_if_win=expected_profit_usd,
        loss_if_lose=expected_loss_usd,
        base_size_usd=base_size_usd,
        risk_state=get_risk_state()
    )


# ============================================================================
# TESTS
# ============================================================================

def test_kelly():
    """Test Kelly sizing"""
    
    # Test 1: Strong edge
    result = calculate_optimal_size(
        p_success=0.7,
        profit_if_win=0.50,
        loss_if_lose=0.05,
        base_size_usd=1000
    )
    print("Test 1 - Strong edge:")
    print(f"  Full Kelly: {result.full_kelly:.3f}")
    print(f"  Fractional Kelly: {result.fractional_kelly:.3f}")
    print(f"  Size multiplier: {result.size_multiplier:.3f}")
    print(f"  Recommended size: ${result.recommended_size_usd:.2f}")
    print(f"  Fee multiplier: {result.fee_multiplier:.2f}")
    print(f"  Reason: {result.reason}")
    
    # Test 2: Weak edge
    result = calculate_optimal_size(
        p_success=0.55,
        profit_if_win=0.10,
        loss_if_lose=0.08,
        base_size_usd=1000
    )
    print("\nTest 2 - Weak edge:")
    print(f"  Full Kelly: {result.full_kelly:.3f}")
    print(f"  Size multiplier: {result.size_multiplier:.3f}")
    print(f"  Recommended size: ${result.recommended_size_usd:.2f}")
    
    # Test 3: No edge
    result = calculate_optimal_size(
        p_success=0.4,
        profit_if_win=0.10,
        loss_if_lose=0.10,
        base_size_usd=1000
    )
    print("\nTest 3 - No edge:")
    print(f"  Full Kelly: {result.full_kelly:.3f}")
    print(f"  Size multiplier: {result.size_multiplier:.3f}")
    print(f"  Recommended size: ${result.recommended_size_usd:.2f}")
    print(f"  Reason: {result.reason}")
    
    # Test 4: With risk state
    risk_state = RiskState(
        daily_pnl_usd=-50,
        consecutive_losses=3,
        peak_balance_usd=1000,
        current_balance_usd=900,
        trades_today=10,
        wins_today=4,
        losses_today=6
    )
    
    result = calculate_optimal_size(
        p_success=0.65,
        profit_if_win=0.30,
        loss_if_lose=0.05,
        base_size_usd=1000,
        risk_state=risk_state
    )
    print("\nTest 4 - With risk state (10% drawdown):")
    print(f"  Full Kelly: {result.full_kelly:.3f}")
    print(f"  Size multiplier: {result.size_multiplier:.3f}")
    print(f"  Recommended size: ${result.recommended_size_usd:.2f}")
    print(f"  Reason: {result.reason}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_kelly()
