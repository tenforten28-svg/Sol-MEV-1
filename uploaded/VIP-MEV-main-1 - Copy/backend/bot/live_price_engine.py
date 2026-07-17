"""
LIVE PRICE ENGINE - Real-Time Vault Monitoring
===============================================
Phase 2: Subscribe to vaults, decode balances, calculate spreads
NO polling - instant WebSocket updates
"""

import asyncio
import base64
import struct
import time
import os
import logging
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime

from solders.pubkey import Pubkey
from solana.rpc.websocket_api import connect
from dotenv import load_dotenv

load_dotenv()

# ==============================
# LOGGING
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s'
)
logger = logging.getLogger('live_price')

# ==============================
# CONFIG
# ==============================

WSS_ENDPOINT = os.environ.get('QUICKNODE_WSS_URL', 'wss://api.mainnet-beta.solana.com')

# Override devnet
if 'devnet' in WSS_ENDPOINT.lower():
    WSS_ENDPOINT = 'wss://api.mainnet-beta.solana.com'
    logger.warning("Devnet detected, using mainnet public endpoint")

# Vault addresses - REPLACE WITH YOUR EXTRACTED VAULTS
# Run vault_extractor.py first to get these
VAULTS = {
    "raydium_sol_usdc": {
        "base": "DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz",   # SOL vault
        "quote": "HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz",  # USDC vault
        "base_decimals": 9,   # SOL
        "quote_decimals": 6,  # USDC
        "dex": "raydium"
    },
    "orca_sol_usdc": {
        "base": "3YQm7ujtXWJU2e9jhp2QGHpnn1ShXn12QjvzMvDgabpX",   # Token A vault
        "quote": "2JTw1fE2wz1SymWUQ7UqpVtrTuKjcd6mWwYwUJUCh2rq",  # Token B vault
        "base_decimals": 9,
        "quote_decimals": 6,
        "dex": "orca"
    },
    # Add more pools as needed
    # "meteora_sol_usdc": {
    #     "base": "RESERVE_X_ADDRESS",
    #     "quote": "RESERVE_Y_ADDRESS",
    #     "base_decimals": 9,
    #     "quote_decimals": 6,
    #     "dex": "meteora"
    # },
}

# Trading parameters
MIN_SPREAD_BPS = 8  # Minimum spread to alert

# ==============================
# STATE
# ==============================

@dataclass
class VaultState:
    address: str
    balance: int = 0
    decimals: int = 9
    last_update: float = 0
    slot: int = 0

# Global state
balances: Dict[str, int] = {}
vault_states: Dict[str, VaultState] = {}
subscription_map: Dict[int, str] = {}  # subscription_id -> vault_address
address_to_pool: Dict[str, tuple] = {}  # address -> (pool_name, "base"|"quote")

# Stats
stats = {
    "updates": 0,
    "opportunities": 0,
    "start_time": time.time()
}

# ==============================
# HELPERS
# ==============================

def decode_token_balance(data_base64: str) -> int:
    """
    Decode SPL Token account balance
    Layout: mint(32) + owner(32) + amount(8) + ...
    Amount is at offset 64, 8 bytes, little-endian u64
    """
    data = base64.b64decode(data_base64)
    if len(data) < 72:
        return 0
    amount = struct.unpack_from("<Q", data, offset=64)[0]
    return amount


def calculate_price(base: int, quote: int, base_decimals: int = 9, quote_decimals: int = 6) -> float:
    """
    Calculate price from reserves
    Price = (quote / 10^quote_decimals) / (base / 10^base_decimals)
    """
    if base == 0:
        return 0.0
    
    base_amount = base / (10 ** base_decimals)
    quote_amount = quote / (10 ** quote_decimals)
    
    return quote_amount / base_amount


def calculate_spread_bps(price1: float, price2: float) -> float:
    """Calculate spread in basis points"""
    if price1 == 0 or price2 == 0:
        return 0.0
    
    spread = abs(price1 - price2) / min(price1, price2) * 10000
    return spread


def format_balance(amount: int, decimals: int) -> str:
    """Format balance with decimals"""
    return f"{amount / (10 ** decimals):,.4f}"


# ==============================
# WEBSOCKET LISTENER
# ==============================

async def main():
    logger.info("=" * 60)
    logger.info("LIVE PRICE ENGINE - Real-Time Vault Monitor")
    logger.info("=" * 60)
    logger.info(f"WSS Endpoint: {WSS_ENDPOINT[:50]}...")
    logger.info(f"Pools to monitor: {len(VAULTS)}")
    logger.info(f"Min spread alert: {MIN_SPREAD_BPS} bps")
    logger.info("=" * 60)
    
    # Build address mapping
    for pool_name, vault_config in VAULTS.items():
        base_addr = vault_config["base"]
        quote_addr = vault_config["quote"]
        
        address_to_pool[base_addr] = (pool_name, "base")
        address_to_pool[quote_addr] = (pool_name, "quote")
        
        # Initialize vault states
        vault_states[base_addr] = VaultState(
            address=base_addr,
            decimals=vault_config.get("base_decimals", 9)
        )
        vault_states[quote_addr] = VaultState(
            address=quote_addr,
            decimals=vault_config.get("quote_decimals", 6)
        )
    
    reconnect_delay = 1
    max_reconnect_delay = 30
    
    while True:
        try:
            logger.info(f"Connecting to WebSocket...")
            
            async with connect(WSS_ENDPOINT) as websocket:
                logger.info("Connected!")
                reconnect_delay = 1  # Reset on success
                
                # Subscribe to all vaults
                sub_count = 0
                for pool_name, vault_config in VAULTS.items():
                    for side in ["base", "quote"]:
                        address = vault_config[side]
                        pubkey = Pubkey.from_string(address)
                        
                        result = await websocket.account_subscribe(
                            pubkey,
                            commitment="processed",
                            encoding="base64"
                        )
                        
                        # Store subscription mapping
                        if hasattr(result, 'result'):
                            subscription_map[result.result] = address
                            sub_count += 1
                            logger.info(f"  ✓ Subscribed: {pool_name} {side} ({address[:8]}...)")
                
                logger.info(f"\nAll {sub_count} vaults subscribed ✅")
                logger.info("Listening for updates...\n")
                logger.info("-" * 60)
                
                # Process messages
                async for msg in websocket:
                    await process_message(msg)
                    
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            logger.info(f"Reconnecting in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)


async def process_message(msg):
    """Process incoming WebSocket message"""
    try:
        # Handle subscription confirmations
        if hasattr(msg, 'result') and isinstance(msg.result, int):
            return
        
        # Handle notifications
        if not hasattr(msg, 'params'):
            return
        
        params = msg.params
        subscription_id = params.get('subscription')
        result = params.get('result')
        
        if not result:
            return
        
        value = result.get('value')
        context = result.get('context', {})
        slot = context.get('slot', 0)
        
        if not value:
            return
        
        # Get account data
        data = value.get('data')
        if not data or not isinstance(data, list):
            return
        
        data_base64 = data[0]
        
        # Find which vault this is
        address = subscription_map.get(subscription_id)
        if not address:
            return
        
        # Decode balance
        balance = decode_token_balance(data_base64)
        
        # Update state
        balances[address] = balance
        if address in vault_states:
            vault_states[address].balance = balance
            vault_states[address].last_update = time.time()
            vault_states[address].slot = slot
        
        stats["updates"] += 1
        
        # Get pool info
        pool_info = address_to_pool.get(address)
        if not pool_info:
            return
        
        pool_name, side = pool_info
        vault_config = VAULTS.get(pool_name, {})
        decimals = vault_config.get(f"{side}_decimals", 9)
        
        # Log update
        formatted = format_balance(balance, decimals)
        logger.debug(f"Update: {pool_name} {side} = {formatted}")
        
        # Calculate and display prices
        await calculate_and_display_prices()
        
    except Exception as e:
        logger.debug(f"Message processing error: {e}")


async def calculate_and_display_prices():
    """Calculate prices for all pools and display spreads"""
    prices = {}
    
    for pool_name, vault_config in VAULTS.items():
        base_addr = vault_config["base"]
        quote_addr = vault_config["quote"]
        
        if base_addr not in balances or quote_addr not in balances:
            continue
        
        base_balance = balances[base_addr]
        quote_balance = balances[quote_addr]
        
        if base_balance == 0:
            continue
        
        price = calculate_price(
            base_balance,
            quote_balance,
            vault_config.get("base_decimals", 9),
            vault_config.get("quote_decimals", 6)
        )
        
        prices[pool_name] = price
        
        # Display pool price
        base_formatted = format_balance(base_balance, vault_config.get("base_decimals", 9))
        quote_formatted = format_balance(quote_balance, vault_config.get("quote_decimals", 6))
        
        logger.info(f"{pool_name}: {price:.6f} (base: {base_formatted}, quote: {quote_formatted})")
    
    # Calculate spreads between all pool pairs
    pool_names = list(prices.keys())
    
    for i in range(len(pool_names)):
        for j in range(i + 1, len(pool_names)):
            pool1 = pool_names[i]
            pool2 = pool_names[j]
            
            price1 = prices[pool1]
            price2 = prices[pool2]
            
            spread_bps = calculate_spread_bps(price1, price2)
            
            # Determine direction
            if price1 < price2:
                buy_pool = pool1
                sell_pool = pool2
            else:
                buy_pool = pool2
                sell_pool = pool1
            
            # Alert on significant spread
            if spread_bps >= MIN_SPREAD_BPS:
                stats["opportunities"] += 1
                logger.info("=" * 60)
                logger.info(f"⚡ SPREAD ALERT: {spread_bps:.2f} bps")
                logger.info(f"   Buy on:  {buy_pool} @ {prices[buy_pool]:.6f}")
                logger.info(f"   Sell on: {sell_pool} @ {prices[sell_pool]:.6f}")
                logger.info(f"   Opportunities detected: {stats['opportunities']}")
                logger.info("=" * 60)
            else:
                logger.info(f"Spread {pool1} vs {pool2}: {spread_bps:.2f} bps")
    
    logger.info("-" * 60)


# ==============================
# STATS PRINTER
# ==============================

async def print_stats():
    """Print periodic statistics"""
    while True:
        await asyncio.sleep(60)
        
        runtime = time.time() - stats["start_time"]
        updates_per_min = stats["updates"] / (runtime / 60) if runtime > 0 else 0
        
        logger.info("=" * 60)
        logger.info("STATS REPORT")
        logger.info(f"  Runtime: {runtime/60:.1f} minutes")
        logger.info(f"  Total updates: {stats['updates']}")
        logger.info(f"  Updates/min: {updates_per_min:.1f}")
        logger.info(f"  Opportunities: {stats['opportunities']}")
        logger.info("=" * 60)


# ==============================
# MAIN
# ==============================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nStopped by user")
        logger.info(f"Total updates: {stats['updates']}")
        logger.info(f"Total opportunities: {stats['opportunities']}")
