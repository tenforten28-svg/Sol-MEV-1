"""
EV NET - Cost-Aware Execution Gating
====================================
Calculate expected value accounting for all costs.
Only execute when EV_net > 0.
"""

import os
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

# ============================================================================
# CONFIG
# ============================================================================

# Default cost estimates
DEFAULT_BASE_FEE_LAMPORTS = 5000  # ~0.000005 SOL
DEFAULT_PRIORITY_FEE_LAMPORTS = 50000  # ~0.00005 SOL
DEFAULT_JITO_TIP_LAMPORTS = 10000  # ~0.00001 SOL

# Slippage estimates (in BPS)
DEFAULT_SLIPPAGE_BPS = 30  # 0.3% expected slippage

# Failure cost (average loss when trade fails)
DEFAULT_FAIL_COST_USD = 0.01  # Gas wasted on failed tx

# SOL price for USD conversion
SOL_PRICE_USD = float(os.environ.get('SOL_PRICE_USD', '180'))

# Feature flag
EV_NET_GATE_ENABLED = os.environ.get('EV_NET_GATE', 'true').lower() == 'true'
EV_NET_THRESHOLD = float(os.environ.get('EV_NET_THRESHOLD', '0.0'))

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class CostBreakdown:
    """Breakdown of all trade costs"""
    base_fee_usd: float
    priority_fee_usd: float
    jito_tip_usd: float
    slippage_usd: float
    fail_cost_usd: float
    total_cost_usd: float
    
    def to_dict(self) -> Dict:
        return {
            'base_fee_usd': self.base_fee_usd,
            'priority_fee_usd': self.priority_fee_usd,
            'jito_tip_usd': self.jito_tip_usd,
            'slippage_usd': self.slippage_usd,
            'fail_cost_usd': self.fail_cost_usd,
            'total_cost_usd': self.total_cost_usd,
        }


@dataclass
class EVCalculation:
    """EV calculation result"""
    ev_raw: float          # Gross expected profit
    ev_net: float          # Net expected profit after costs
    costs: CostBreakdown   # Cost breakdown
    p_success: float       # Probability of success
    should_execute: bool   # Final decision
    reasons: list          # Decision reasons
    
    def to_dict(self) -> Dict:
        return {
            'ev_raw': self.ev_raw,
            'ev_net': self.ev_net,
            'costs': self.costs.to_dict(),
            'p_success': self.p_success,
            'should_execute': self.should_execute,
            'reasons': self.reasons,
        }


# ============================================================================
# COST MODEL
# ============================================================================

def lamports_to_usd(lamports: int, sol_price: float = SOL_PRICE_USD) -> float:
    """Convert lamports to USD"""
    return (lamports / 1e9) * sol_price


def estimate_fees(
    priority_fee_lamports: int = DEFAULT_PRIORITY_FEE_LAMPORTS,
    jito_tip_lamports: int = DEFAULT_JITO_TIP_LAMPORTS,
    sol_price: float = SOL_PRICE_USD
) -> Tuple[float, float, float]:
    """
    Estimate transaction fees in USD.
    
    Returns:
        (base_fee_usd, priority_fee_usd, jito_tip_usd)
    """
    base_fee_usd = lamports_to_usd(DEFAULT_BASE_FEE_LAMPORTS, sol_price)
    priority_fee_usd = lamports_to_usd(priority_fee_lamports, sol_price)
    jito_tip_usd = lamports_to_usd(jito_tip_lamports, sol_price)
    
    return base_fee_usd, priority_fee_usd, jito_tip_usd


def estimate_slippage(
    trade_size_usd: float,
    spread_bps: float,
    liquidity_depth_usd: float,
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS
) -> float:
    """
    Estimate slippage cost in USD.
    
    More conservative estimate when:
    - Trade is larger relative to liquidity
    - Spread is thin (more competition)
    """
    # Base slippage
    base_slippage = trade_size_usd * (slippage_bps / 10000)
    
    # Adjust for trade size vs liquidity
    if liquidity_depth_usd > 0:
        size_ratio = trade_size_usd / liquidity_depth_usd
        if size_ratio > 0.01:  # More than 1% of liquidity
            base_slippage *= (1 + size_ratio * 10)  # Scale up slippage estimate
    
    # Adjust for thin spreads (more competition)
    if spread_bps < 15:
        base_slippage *= 1.5  # More conservative on thin spreads
    
    return base_slippage


def estimate_fail_cost(
    p_success: float,
    priority_fee_lamports: int = DEFAULT_PRIORITY_FEE_LAMPORTS,
    sol_price: float = SOL_PRICE_USD
) -> float:
    """
    Estimate expected cost of failure.
    
    When we fail, we lose gas fees but not the trade.
    """
    # Gas cost of failed transaction
    gas_cost = lamports_to_usd(
        DEFAULT_BASE_FEE_LAMPORTS + priority_fee_lamports // 2,  # Partial priority fee
        sol_price
    )
    
    # Expected fail cost = P(fail) * cost_if_fail
    return (1 - p_success) * gas_cost


# ============================================================================
# EV CALCULATION
# ============================================================================

def calculate_ev_net(
    expected_profit_usd: float,
    trade_size_usd: float,
    spread_bps: float,
    liquidity_depth_usd: float = 100000,
    p_success: float = 0.7,
    priority_fee_lamports: int = DEFAULT_PRIORITY_FEE_LAMPORTS,
    jito_tip_lamports: int = DEFAULT_JITO_TIP_LAMPORTS,
    sol_price: float = SOL_PRICE_USD
) -> EVCalculation:
    """
    Calculate net expected value for a trade.
    
    EV_net = EV_raw - fees - slippage - fail_cost
    
    Args:
        expected_profit_usd: Gross expected profit
        trade_size_usd: Trade size in USD
        spread_bps: Spread in basis points
        liquidity_depth_usd: Available liquidity
        p_success: Probability of successful execution
        priority_fee_lamports: Priority fee in lamports
        jito_tip_lamports: Jito tip in lamports
        sol_price: SOL price in USD
    
    Returns:
        EVCalculation with decision and breakdown
    """
    reasons = []
    
    # Calculate fees
    base_fee_usd, priority_fee_usd, jito_tip_usd = estimate_fees(
        priority_fee_lamports, jito_tip_lamports, sol_price
    )
    
    # Calculate slippage
    slippage_usd = estimate_slippage(
        trade_size_usd, spread_bps, liquidity_depth_usd
    )
    
    # Calculate fail cost
    fail_cost_usd = estimate_fail_cost(p_success, priority_fee_lamports, sol_price)
    
    # Total costs
    total_cost_usd = base_fee_usd + priority_fee_usd + jito_tip_usd + slippage_usd + fail_cost_usd
    
    costs = CostBreakdown(
        base_fee_usd=base_fee_usd,
        priority_fee_usd=priority_fee_usd,
        jito_tip_usd=jito_tip_usd,
        slippage_usd=slippage_usd,
        fail_cost_usd=fail_cost_usd,
        total_cost_usd=total_cost_usd
    )
    
    # Calculate EV
    ev_raw = expected_profit_usd
    ev_net = ev_raw - total_cost_usd
    
    # Adjust for success probability
    ev_net_adjusted = (p_success * ev_net) - ((1 - p_success) * fail_cost_usd)
    
    # Decision
    should_execute = True
    
    if not EV_NET_GATE_ENABLED:
        reasons.append("EV_NET_GATE disabled")
    else:
        if ev_net_adjusted <= EV_NET_THRESHOLD:
            should_execute = False
            reasons.append(f"EV_net ({ev_net_adjusted:.4f}) <= threshold ({EV_NET_THRESHOLD})")
        else:
            reasons.append(f"EV_net ({ev_net_adjusted:.4f}) > threshold ({EV_NET_THRESHOLD})")
        
        if p_success < 0.3:
            should_execute = False
            reasons.append(f"P_success ({p_success:.2f}) too low")
        
        if slippage_usd > ev_raw * 0.5:
            should_execute = False
            reasons.append(f"Slippage ({slippage_usd:.4f}) > 50% of profit")
    
    if should_execute:
        reasons.append("EXECUTE")
    else:
        reasons.append("SKIP")
    
    return EVCalculation(
        ev_raw=ev_raw,
        ev_net=ev_net_adjusted,
        costs=costs,
        p_success=p_success,
        should_execute=should_execute,
        reasons=reasons
    )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def quick_ev_check(
    expected_profit_usd: float,
    trade_size_usd: float,
    spread_bps: float,
    p_success: float = 0.7
) -> bool:
    """
    Quick EV check without full calculation.
    Use for initial filtering before detailed analysis.
    """
    # Rough cost estimate
    estimated_cost = 0.02 + (trade_size_usd * 0.003)  # $0.02 base + 0.3% slippage
    
    # Quick EV
    quick_ev = (expected_profit_usd * p_success) - estimated_cost
    
    return quick_ev > 0


def optimal_priority_fee(
    expected_profit_usd: float,
    p_success: float,
    competition_level: float = 0.5  # 0 = low, 1 = high
) -> int:
    """
    Calculate optimal priority fee based on expected profit.
    
    Higher profit -> can afford higher priority
    Higher competition -> need higher priority
    """
    # Base priority fee
    base_fee = 10000  # 0.00001 SOL
    
    # Scale by profit (up to 10x)
    profit_multiplier = min(10, max(1, expected_profit_usd / 0.10))
    
    # Scale by competition (up to 5x)
    competition_multiplier = 1 + (competition_level * 4)
    
    # Scale by success probability (lower p -> higher fee needed)
    success_multiplier = 1 / max(0.3, p_success)
    
    optimal = int(base_fee * profit_multiplier * competition_multiplier * success_multiplier)
    
    # Cap at reasonable maximum
    return min(optimal, 500000)  # Max 0.0005 SOL


# ============================================================================
# TESTS
# ============================================================================

def test_ev_calculation():
    """Test EV calculation"""
    # Profitable trade
    result = calculate_ev_net(
        expected_profit_usd=0.50,
        trade_size_usd=1000,
        spread_bps=15,
        p_success=0.8
    )
    print(f"Profitable trade:")
    print(f"  EV_raw: ${result.ev_raw:.4f}")
    print(f"  EV_net: ${result.ev_net:.4f}")
    print(f"  Costs: ${result.costs.total_cost_usd:.4f}")
    print(f"  Should execute: {result.should_execute}")
    print(f"  Reasons: {result.reasons}")
    print()
    
    # Marginal trade
    result = calculate_ev_net(
        expected_profit_usd=0.05,
        trade_size_usd=1000,
        spread_bps=8,
        p_success=0.5
    )
    print(f"Marginal trade:")
    print(f"  EV_raw: ${result.ev_raw:.4f}")
    print(f"  EV_net: ${result.ev_net:.4f}")
    print(f"  Should execute: {result.should_execute}")
    print(f"  Reasons: {result.reasons}")


if __name__ == "__main__":
    test_ev_calculation()
