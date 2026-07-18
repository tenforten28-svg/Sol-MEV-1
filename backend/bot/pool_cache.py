"""
POOL CACHE - Global In-Memory Pool State
=========================================
Thread-safe storage for real-time pool data
Updated only by WebSocket events
"""

import time
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
import threading

# Thread-safe lock for concurrent updates
_lock = threading.Lock()

# =============================================================================
# POOL STATE DATA STRUCTURE
# =============================================================================
@dataclass
class PoolState:
    """Real-time state of a liquidity pool"""
    pool_name: str
    dex: str
    base_reserve: int = 0
    quote_reserve: int = 0
    base_decimals: int = 9
    quote_decimals: int = 6
    price: float = 0.0
    last_update: float = 0.0
    slot: int = 0
    
    def is_valid(self) -> bool:
        """Check if pool has valid data"""
        return self.base_reserve > 0 and self.quote_reserve > 0
    
    def age_ms(self) -> float:
        """Get age of data in milliseconds"""
        return (time.time() - self.last_update) * 1000


# =============================================================================
# GLOBAL POOL STATE STORAGE
# =============================================================================
pool_state: Dict[str, PoolState] = {}

# Vault to pool mapping (vault_address -> pool_name)
vault_to_pool: Dict[str, tuple] = {}  # vault_address -> (pool_name, "base"|"quote")


def register_vault(vault_address: str, pool_name: str, vault_type: str):
    """Register a vault address to a pool"""
    with _lock:
        vault_to_pool[vault_address] = (pool_name, vault_type)


def update_pool(pool_name: str, data: Dict[str, Any]) -> None:
    """
    Update pool state from WebSocket event
    Called ONLY by websocket_listener on account change events
    """
    with _lock:
        if pool_name not in pool_state:
            pool_state[pool_name] = PoolState(
                pool_name=pool_name,
                dex=data.get("dex", "unknown")
            )
        
        state = pool_state[pool_name]
        
        # Update reserves
        if "base_reserve" in data:
            state.base_reserve = data["base_reserve"]
        if "quote_reserve" in data:
            state.quote_reserve = data["quote_reserve"]
        if "base_decimals" in data:
            state.base_decimals = data["base_decimals"]
        if "quote_decimals" in data:
            state.quote_decimals = data["quote_decimals"]
        if "slot" in data:
            state.slot = data["slot"]
        if "dex" in data:
            state.dex = data["dex"]
            
        # Calculate price
        if state.base_reserve > 0:
            base_amount = state.base_reserve / (10 ** state.base_decimals)
            quote_amount = state.quote_reserve / (10 ** state.quote_decimals)
            state.price = quote_amount / base_amount if base_amount > 0 else 0
        
        state.last_update = time.time()


def update_vault_reserve(vault_address: str, amount: int, slot: int) -> Optional[str]:
    """
    Update reserve from vault token account change
    Returns pool_name if update triggers arb check
    """
    with _lock:
        if vault_address not in vault_to_pool:
            return None
        
        pool_name, vault_type = vault_to_pool[vault_address]
        
        if pool_name not in pool_state:
            return None
        
        state = pool_state[pool_name]
        
        if vault_type == "base":
            state.base_reserve = amount
        elif vault_type == "quote":
            state.quote_reserve = amount
        
        state.slot = slot
        state.last_update = time.time()
        
        # Recalculate price
        if state.base_reserve > 0:
            base_amount = state.base_reserve / (10 ** state.base_decimals)
            quote_amount = state.quote_reserve / (10 ** state.quote_decimals)
            state.price = quote_amount / base_amount if base_amount > 0 else 0
        
        return pool_name


def get_pool(pool_name: str) -> Optional[PoolState]:
    """Get current pool state (read-only)"""
    with _lock:
        return pool_state.get(pool_name)


def get_all_pools() -> Dict[str, PoolState]:
    """Get all pool states (read-only copy)"""
    with _lock:
        return dict(pool_state)


def get_pools_by_pair(base_mint: str, quote_mint: str) -> list:
    """Get all pools for a specific token pair"""
    with _lock:
        result = []
        for name, state in pool_state.items():
            # Check config for mint addresses
            from config import POOLS
            pool_config = POOLS.get(name, {})
            if (pool_config.get("base_mint") == base_mint and 
                pool_config.get("quote_mint") == quote_mint):
                result.append(state)
        return result


def get_pool_stats() -> Dict[str, Any]:
    """Get statistics about pool cache"""
    with _lock:
        valid_pools = sum(1 for p in pool_state.values() if p.is_valid())
        return {
            "total_pools": len(pool_state),
            "valid_pools": valid_pools,
            "pools": {name: {
                "dex": state.dex,
                "price": state.price,
                "age_ms": state.age_ms(),
                "valid": state.is_valid()
            } for name, state in pool_state.items()}
        }


def clear_cache():
    """Clear all pool state (for testing)"""
    with _lock:
        pool_state.clear()
        vault_to_pool.clear()
