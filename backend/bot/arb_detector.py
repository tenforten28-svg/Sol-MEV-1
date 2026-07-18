"""
ARBITRAGE DETECTOR - Real-Time Opportunity Detection
=====================================================
Triggered ONLY by WebSocket events
NO polling, NO sleeping, NO external APIs
"""

import time
import logging
from typing import Optional, Dict, List, Tuple, Callable
from dataclasses import dataclass

from config import MIN_SPREAD_BPS, MIN_PROFIT_USD, MAX_TRADE_SIZE_USD, POOLS, TOKEN_DECIMALS
from pool_cache import get_pool, get_all_pools, PoolState
from pricing import (
    calculate_spread_bps, 
    calculate_profit, 
    constant_product_swap_out,
    optimal_arbitrage_size
)

logger = logging.getLogger('arb_detector')

# =============================================================================
# ARBITRAGE OPPORTUNITY
# =============================================================================
@dataclass
class ArbitrageOpportunity:
    """Detected arbitrage opportunity"""
    buy_pool: str
    sell_pool: str
    buy_dex: str
    sell_dex: str
    pair_name: str
    spread_bps: float
    expected_profit_usd: float
    optimal_size: int
    buy_price: float
    sell_price: float
    timestamp: float
    slot: int
    
    def is_valid(self, max_age_ms: float = 500) -> bool:
        """Check if opportunity is still valid"""
        age = (time.time() - self.timestamp) * 1000
        return age < max_age_ms and self.expected_profit_usd >= MIN_PROFIT_USD


# =============================================================================
# PAIR GROUPINGS FOR ARBITRAGE
# =============================================================================
# Group pools by trading pair for cross-DEX comparison
ARBITRAGE_PAIRS = {
    "SOL/USDC": ["raydium_sol_usdc", "orca_sol_usdc", "meteora_sol_usdc"],
    "BONK/SOL": ["raydium_bonk_sol", "orca_bonk_sol"],
    "WIF/SOL": ["raydium_wif_sol", "orca_wif_sol"],
}


# Callback for when opportunity is detected
_opportunity_callback: Optional[Callable[[ArbitrageOpportunity], None]] = None


def set_opportunity_callback(callback: Callable[[ArbitrageOpportunity], None]):
    """Set callback function for when arbitrage is detected"""
    global _opportunity_callback
    _opportunity_callback = callback


# =============================================================================
# DETECTION LOGIC
# =============================================================================
def check_arbitrage_for_pair(pair_name: str, pool_names: List[str]) -> Optional[ArbitrageOpportunity]:
    """
    Check arbitrage opportunities for a specific pair
    Compares all pools in the list
    """
    valid_pools = []
    
    for pool_name in pool_names:
        pool = get_pool(pool_name)
        if pool and pool.is_valid() and pool.age_ms() < 2000:
            valid_pools.append((pool_name, pool))
    
    if len(valid_pools) < 2:
        return None
    
    best_opportunity: Optional[ArbitrageOpportunity] = None
    best_profit = 0.0
    
    # Compare all pool combinations
    for i, (buy_name, buy_pool) in enumerate(valid_pools):
        for j, (sell_name, sell_pool) in enumerate(valid_pools):
            if i == j:
                continue
            
            # Calculate spread
            spread_bps = calculate_spread_bps(buy_pool.price, sell_pool.price)
            
            if spread_bps < MIN_SPREAD_BPS:
                continue
            
            # Calculate profit with optimal trade size
            quote_decimals = buy_pool.quote_decimals
            max_trade = int(MAX_TRADE_SIZE_USD * (10 ** quote_decimals))
            
            # Find optimal size
            optimal_size = optimal_arbitrage_size(
                buy_pool.base_reserve, buy_pool.quote_reserve,
                sell_pool.base_reserve, sell_pool.quote_reserve,
                max_trade
            )
            
            if optimal_size == 0:
                continue
            
            # Calculate actual profit
            profit_usd, _ = calculate_profit(
                optimal_size,
                buy_pool.base_reserve, buy_pool.quote_reserve,
                sell_pool.base_reserve, sell_pool.quote_reserve,
                quote_decimals=quote_decimals
            )
            
            if profit_usd < MIN_PROFIT_USD:
                continue
            
            if profit_usd > best_profit:
                best_profit = profit_usd
                best_opportunity = ArbitrageOpportunity(
                    buy_pool=buy_name,
                    sell_pool=sell_name,
                    buy_dex=buy_pool.dex,
                    sell_dex=sell_pool.dex,
                    pair_name=pair_name,
                    spread_bps=spread_bps,
                    expected_profit_usd=profit_usd,
                    optimal_size=optimal_size,
                    buy_price=buy_pool.price,
                    sell_price=sell_pool.price,
                    timestamp=time.time(),
                    slot=max(buy_pool.slot, sell_pool.slot)
                )
    
    return best_opportunity


def check_arbitrage() -> Optional[ArbitrageOpportunity]:
    """
    Main arbitrage detection function
    Called on every pool state update
    Returns best opportunity if found
    """
    best_opportunity: Optional[ArbitrageOpportunity] = None
    best_profit = 0.0
    
    for pair_name, pool_names in ARBITRAGE_PAIRS.items():
        opportunity = check_arbitrage_for_pair(pair_name, pool_names)
        
        if opportunity and opportunity.expected_profit_usd > best_profit:
            best_profit = opportunity.expected_profit_usd
            best_opportunity = opportunity
    
    if best_opportunity:
        logger.info(
            f"⚡ ARB DETECTED | {best_opportunity.pair_name} | "
            f"{best_opportunity.buy_dex} -> {best_opportunity.sell_dex} | "
            f"Spread: {best_opportunity.spread_bps:.1f}bps | "
            f"Profit: ${best_opportunity.expected_profit_usd:.4f}"
        )
        
        # Trigger callback if set
        if _opportunity_callback:
            _opportunity_callback(best_opportunity)
    
    return best_opportunity


def check_single_pool_update(pool_name: str) -> Optional[ArbitrageOpportunity]:
    """
    Check arbitrage when a specific pool is updated
    More efficient than checking all pairs
    """
    # Find which pair this pool belongs to
    for pair_name, pool_names in ARBITRAGE_PAIRS.items():
        if pool_name in pool_names:
            return check_arbitrage_for_pair(pair_name, pool_names)
    
    return None


# =============================================================================
# STATISTICS
# =============================================================================
class ArbitrageStats:
    """Track arbitrage detection statistics"""
    
    def __init__(self):
        self.opportunities_detected = 0
        self.opportunities_executed = 0
        self.total_profit_usd = 0.0
        self.last_opportunity: Optional[ArbitrageOpportunity] = None
        self.start_time = time.time()
    
    def record_opportunity(self, opp: ArbitrageOpportunity):
        self.opportunities_detected += 1
        self.last_opportunity = opp
    
    def record_execution(self, profit: float):
        self.opportunities_executed += 1
        self.total_profit_usd += profit
    
    def get_stats(self) -> Dict:
        runtime_hours = (time.time() - self.start_time) / 3600
        return {
            "runtime_hours": runtime_hours,
            "opportunities_detected": self.opportunities_detected,
            "opportunities_executed": self.opportunities_executed,
            "total_profit_usd": self.total_profit_usd,
            "opportunities_per_hour": self.opportunities_detected / max(runtime_hours, 0.01),
        }


# Global stats instance
stats = ArbitrageStats()


def get_arbitrage_stats() -> Dict:
    """Get current arbitrage statistics"""
    return stats.get_stats()
