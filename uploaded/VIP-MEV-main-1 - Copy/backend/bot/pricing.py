"""
PRICING ENGINE - Local Price Calculation
=========================================
Calculate prices from on-chain reserves
NO external API calls - pure math
"""

from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class SwapQuote:
    """Result of a swap calculation"""
    amount_in: int
    amount_out: int
    price_impact_bps: float
    effective_price: float


# =============================================================================
# CONSTANT PRODUCT AMM (Raydium, Orca Legacy)
# =============================================================================
def constant_product_price(reserve_base: int, reserve_quote: int, 
                           base_decimals: int = 9, quote_decimals: int = 6) -> float:
    """
    Calculate spot price for constant product AMM (x * y = k)
    Price = quote_reserve / base_reserve (adjusted for decimals)
    """
    if reserve_base == 0:
        return 0.0
    
    base_amount = reserve_base / (10 ** base_decimals)
    quote_amount = reserve_quote / (10 ** quote_decimals)
    
    return quote_amount / base_amount


def constant_product_swap_out(amount_in: int, reserve_in: int, reserve_out: int, 
                               fee_bps: int = 25) -> int:
    """
    Calculate output amount for constant product swap
    Formula: out = (reserve_out * amount_in_after_fee) / (reserve_in + amount_in_after_fee)
    """
    if reserve_in == 0 or reserve_out == 0:
        return 0
    
    # Apply fee
    amount_after_fee = amount_in * (10000 - fee_bps) // 10000
    
    # Constant product formula
    numerator = reserve_out * amount_after_fee
    denominator = reserve_in + amount_after_fee
    
    return numerator // denominator


def constant_product_swap_in(amount_out: int, reserve_in: int, reserve_out: int,
                              fee_bps: int = 25) -> int:
    """
    Calculate input amount needed for desired output (reverse calculation)
    """
    if reserve_out <= amount_out or reserve_in == 0:
        return 0
    
    numerator = reserve_in * amount_out * 10000
    denominator = (reserve_out - amount_out) * (10000 - fee_bps)
    
    return (numerator // denominator) + 1


def calculate_price_impact(amount_in: int, reserve_in: int, reserve_out: int,
                           fee_bps: int = 25) -> float:
    """
    Calculate price impact of a swap in basis points
    """
    if reserve_in == 0 or reserve_out == 0:
        return 10000.0  # 100% impact
    
    # Spot price before swap
    spot_price = reserve_out / reserve_in
    
    # Execute swap
    amount_out = constant_product_swap_out(amount_in, reserve_in, reserve_out, fee_bps)
    
    if amount_out == 0:
        return 10000.0
    
    # Effective price
    effective_price = amount_out / amount_in
    
    # Price impact
    impact = (spot_price - effective_price) / spot_price * 10000
    
    return abs(impact)


# =============================================================================
# CONCENTRATED LIQUIDITY (Orca Whirlpool, Raydium CLMM)
# =============================================================================
def concentrated_liquidity_price(sqrt_price: int, decimals_a: int = 9, decimals_b: int = 6) -> float:
    """
    Calculate price from sqrt_price (Q64.64 format)
    Used by Orca Whirlpool and Raydium CLMM
    """
    if sqrt_price == 0:
        return 0.0
    
    # sqrt_price is in Q64.64 format
    price_x64 = (sqrt_price ** 2) / (2 ** 128)
    
    # Adjust for decimals
    decimal_adjustment = 10 ** (decimals_a - decimals_b)
    
    return price_x64 * decimal_adjustment


def tick_to_price(tick: int, decimals_a: int = 9, decimals_b: int = 6) -> float:
    """
    Convert tick index to price
    price = 1.0001^tick * 10^(decimals_a - decimals_b)
    """
    import math
    price = (1.0001 ** tick) * (10 ** (decimals_a - decimals_b))
    return price


# =============================================================================
# METEORA DLMM (Discrete Liquidity)
# =============================================================================
def dlmm_bin_price(active_bin_id: int, bin_step: int, 
                   decimals_x: int = 9, decimals_y: int = 6) -> float:
    """
    Calculate price from Meteora DLMM bin
    Price = (1 + bin_step/10000)^(active_bin_id - 8388608) * 10^(decimals_x - decimals_y)
    """
    import math
    
    # Bin ID is offset by 2^23 (8388608)
    adjusted_bin = active_bin_id - 8388608
    
    # Price per bin step
    bin_price_factor = 1 + (bin_step / 10000)
    
    price = (bin_price_factor ** adjusted_bin) * (10 ** (decimals_x - decimals_y))
    
    return price


# =============================================================================
# SPREAD CALCULATION
# =============================================================================
def calculate_spread_bps(price_buy: float, price_sell: float) -> float:
    """
    Calculate spread in basis points
    Positive spread = profitable arbitrage (buy low, sell high)
    """
    if price_buy == 0:
        return 0.0
    
    spread = ((price_sell - price_buy) / price_buy) * 10000
    return spread


def calculate_profit(amount_in: int, 
                     buy_reserve_base: int, buy_reserve_quote: int,
                     sell_reserve_base: int, sell_reserve_quote: int,
                     buy_fee_bps: int = 25, sell_fee_bps: int = 25,
                     quote_decimals: int = 6) -> Tuple[float, int]:
    """
    Calculate expected profit from arbitrage
    Returns: (profit_usd, final_amount)
    
    Flow: USDC -> Buy Base -> Sell Base -> USDC
    """
    # Step 1: Buy base token with quote (USDC)
    base_received = constant_product_swap_out(
        amount_in, buy_reserve_quote, buy_reserve_base, buy_fee_bps
    )
    
    if base_received == 0:
        return (0.0, 0)
    
    # Step 2: Sell base token for quote (USDC)
    quote_received = constant_product_swap_out(
        base_received, sell_reserve_base, sell_reserve_quote, sell_fee_bps
    )
    
    # Profit calculation
    profit_raw = quote_received - amount_in
    profit_usd = profit_raw / (10 ** quote_decimals)
    
    return (profit_usd, quote_received)


# =============================================================================
# OPTIMAL TRADE SIZE
# =============================================================================
def optimal_arbitrage_size(buy_reserve_base: int, buy_reserve_quote: int,
                           sell_reserve_base: int, sell_reserve_quote: int,
                           max_size: int, buy_fee_bps: int = 25, 
                           sell_fee_bps: int = 25) -> int:
    """
    Find optimal trade size that maximizes profit
    Uses binary search to find the sweet spot
    """
    if buy_reserve_base == 0 or sell_reserve_base == 0:
        return 0
    
    best_size = 0
    best_profit = 0.0
    
    # Binary search for optimal size
    low = max_size // 100  # Start at 1% of max
    high = max_size
    
    while low <= high:
        mid = (low + high) // 2
        
        profit, _ = calculate_profit(
            mid, buy_reserve_base, buy_reserve_quote,
            sell_reserve_base, sell_reserve_quote,
            buy_fee_bps, sell_fee_bps
        )
        
        if profit > best_profit:
            best_profit = profit
            best_size = mid
        
        # Check neighbors
        profit_lower, _ = calculate_profit(
            mid - max_size // 100 if mid > max_size // 100 else mid,
            buy_reserve_base, buy_reserve_quote,
            sell_reserve_base, sell_reserve_quote,
            buy_fee_bps, sell_fee_bps
        )
        
        profit_higher, _ = calculate_profit(
            mid + max_size // 100 if mid < max_size - max_size // 100 else mid,
            buy_reserve_base, buy_reserve_quote,
            sell_reserve_base, sell_reserve_quote,
            buy_fee_bps, sell_fee_bps
        )
        
        if profit_higher > profit:
            low = mid + 1
        elif profit_lower > profit:
            high = mid - 1
        else:
            break
    
    return best_size
