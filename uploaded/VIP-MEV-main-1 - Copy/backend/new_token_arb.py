"""
NEW TOKEN LAUNCH ARBITRAGE BOT
==============================
Monitors new token launches on:
- Raydium (CLMM + CPMM)
- Meteora (DLMM)
- PumpFun (Bonding Curve Graduations)

Finds arbitrage when same token exists on multiple DEXes
"""

import asyncio
import os
import struct
import time
import json
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
import logging
from dotenv import load_dotenv
from solana.rpc.websocket_api import connect
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
import base58

load_dotenv()

# ==============================
# LOGGING
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger('new_token_arb')

# ==============================
# CONFIG
# ==============================
WSS_URL = os.environ.get('QUICKNODE_WSS_URL')
RPC_URL = os.environ.get('SOLANA_RPC_URL')

# Program IDs
RAYDIUM_AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
RAYDIUM_CLMM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
RAYDIUM_CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
METEORA_DLMM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
ORCA_WHIRLPOOL = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"

# Known quote tokens (we pair against these)
QUOTE_TOKENS = {
    "So11111111111111111111111111111111111111112": {"symbol": "SOL", "decimals": 9},
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": {"symbol": "USDC", "decimals": 6},
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": {"symbol": "USDT", "decimals": 6},
}

# Minimum spread to consider (basis points)
MIN_SPREAD_BPS = 50  # 0.5%
MIN_LIQUIDITY_USD = 1000  # Minimum liquidity to trade

# ==============================
# DATA STRUCTURES
# ==============================

@dataclass
class TokenPool:
    """Represents a liquidity pool for a token"""
    pool_address: str
    dex: str  # raydium, meteora, pumpfun, orca
    base_mint: str  # The new token
    quote_mint: str  # SOL, USDC, etc.
    base_vault: str
    quote_vault: str
    base_decimals: int
    quote_decimals: int
    price: float = 0.0
    base_reserve: int = 0
    quote_reserve: int = 0
    last_update: float = 0
    created_at: float = field(default_factory=time.time)


@dataclass 
class ArbitrageOpportunity:
    """Detected arbitrage opportunity"""
    token_mint: str
    buy_pool: TokenPool
    sell_pool: TokenPool
    spread_bps: float
    expected_profit_usd: float
    detected_at: float = field(default_factory=time.time)


# Global state
token_pools: Dict[str, Dict[str, TokenPool]] = {}  # token_mint -> {dex -> pool}
new_pools_queue: asyncio.Queue = asyncio.Queue()
opportunities: List[ArbitrageOpportunity] = []

# ==============================
# POOL DETECTION
# ==============================

async def monitor_new_pools(client: AsyncClient):
    """Monitor program logs for new pool creations"""
    logger.info("Starting new pool monitor...")
    
    programs_to_watch = [
        RAYDIUM_AMM_V4,
        RAYDIUM_CLMM,
        RAYDIUM_CPMM,
        METEORA_DLMM,
        PUMPFUN,
    ]
    
    async with connect(WSS_URL) as ws:
        # Subscribe to logs for each program
        for program in programs_to_watch:
            try:
                await ws.logs_subscribe(
                    filter_={"mentions": [program]},
                    commitment="confirmed"
                )
                logger.info(f"  Subscribed to: {program[:16]}...")
            except Exception as e:
                logger.error(f"  Failed to subscribe to {program[:16]}: {e}")
        
        logger.info("Listening for new pool creations...")
        
        async for msg in ws:
            try:
                await process_log_message(msg, client)
            except Exception as e:
                logger.debug(f"Error processing log: {e}")


async def process_log_message(msg, client: AsyncClient):
    """Process program log message to detect new pools"""
    if not isinstance(msg, list):
        return
    
    for item in msg:
        if not hasattr(item, 'result'):
            continue
        
        result = item.result
        if not hasattr(result, 'value'):
            continue
        
        value = result.value
        if not value:
            continue
        
        logs = getattr(value, 'logs', [])
        signature = getattr(value, 'signature', '')
        
        # Look for pool creation signatures in logs
        for log in logs:
            log_lower = log.lower()
            
            # Raydium pool creation
            if 'initialize' in log_lower and ('pool' in log_lower or 'amm' in log_lower):
                logger.info(f"🆕 Potential Raydium pool creation: {signature[:20]}...")
                await fetch_new_pool_details(signature, 'raydium', client)
            
            # Meteora DLMM creation
            elif 'initializelbpair' in log_lower or 'create' in log_lower and 'lb' in log_lower:
                logger.info(f"🆕 Potential Meteora pool creation: {signature[:20]}...")
                await fetch_new_pool_details(signature, 'meteora', client)
            
            # PumpFun graduation
            elif 'graduate' in log_lower or 'migrate' in log_lower:
                logger.info(f"🎓 PumpFun graduation detected: {signature[:20]}...")
                await fetch_new_pool_details(signature, 'pumpfun', client)


async def fetch_new_pool_details(signature: str, dex: str, client: AsyncClient):
    """Fetch details of newly created pool"""
    try:
        # Get transaction details
        tx = await client.get_transaction(
            signature,
            encoding="jsonParsed",
            max_supported_transaction_version=0
        )
        
        if not tx.value:
            return
        
        # Parse transaction to find pool accounts
        meta = tx.value.transaction.meta
        if not meta:
            return
        
        # Look for token accounts in post_token_balances
        post_balances = getattr(meta, 'post_token_balances', [])
        
        tokens_found = set()
        for balance in post_balances:
            mint = getattr(balance, 'mint', '')
            if mint and mint not in QUOTE_TOKENS:
                tokens_found.add(mint)
        
        # For each new token found, try to find its pools
        for token_mint in tokens_found:
            await scan_token_pools(token_mint, client)
            
    except Exception as e:
        logger.debug(f"Error fetching pool details: {e}")


async def scan_token_pools(token_mint: str, client: AsyncClient):
    """Scan for all pools containing this token"""
    logger.info(f"🔍 Scanning pools for token: {token_mint[:16]}...")
    
    # This would typically use getProgramAccounts to find all pools
    # For now, we'll add the token to our watch list
    if token_mint not in token_pools:
        token_pools[token_mint] = {}
    
    # Queue for price monitoring
    await new_pools_queue.put(token_mint)


# ==============================
# PRICE MONITORING
# ==============================

async def monitor_prices():
    """Monitor prices across all tracked pools"""
    logger.info("Starting price monitor...")
    
    while True:
        try:
            # Check for new tokens to monitor
            while not new_pools_queue.empty():
                token_mint = await new_pools_queue.get()
                logger.info(f"📊 Added {token_mint[:16]}... to price monitoring")
            
            # Update prices for all tracked tokens
            for token_mint, pools in token_pools.items():
                for dex, pool in pools.items():
                    await update_pool_price(pool)
                
                # Check for arbitrage opportunities
                check_arbitrage(token_mint)
            
            await asyncio.sleep(0.5)  # 500ms update interval
            
        except Exception as e:
            logger.error(f"Price monitor error: {e}")
            await asyncio.sleep(1)


async def update_pool_price(pool: TokenPool):
    """Update price for a single pool"""
    # This would fetch current reserves and calculate price
    # Implementation depends on pool type (AMM vs CLMM)
    pass


def check_arbitrage(token_mint: str):
    """Check for arbitrage opportunities for a token"""
    pools = token_pools.get(token_mint, {})
    
    if len(pools) < 2:
        return  # Need at least 2 pools for arbitrage
    
    pool_list = list(pools.values())
    
    for i in range(len(pool_list)):
        for j in range(i + 1, len(pool_list)):
            pool1 = pool_list[i]
            pool2 = pool_list[j]
            
            if pool1.price <= 0 or pool2.price <= 0:
                continue
            
            # Calculate spread
            spread_bps = abs(pool1.price - pool2.price) / min(pool1.price, pool2.price) * 10000
            
            if spread_bps >= MIN_SPREAD_BPS:
                # Determine buy/sell direction
                if pool1.price < pool2.price:
                    buy_pool, sell_pool = pool1, pool2
                else:
                    buy_pool, sell_pool = pool2, pool1
                
                # Estimate profit
                # (simplified - real calc would consider slippage, fees, etc.)
                estimated_profit = spread_bps / 10000 * MIN_LIQUIDITY_USD
                
                opp = ArbitrageOpportunity(
                    token_mint=token_mint,
                    buy_pool=buy_pool,
                    sell_pool=sell_pool,
                    spread_bps=spread_bps,
                    expected_profit_usd=estimated_profit
                )
                
                logger.info(f"⚡ ARBITRAGE OPPORTUNITY!")
                logger.info(f"   Token: {token_mint[:16]}...")
                logger.info(f"   Buy on {buy_pool.dex} @ ${buy_pool.price:.6f}")
                logger.info(f"   Sell on {sell_pool.dex} @ ${sell_pool.price:.6f}")
                logger.info(f"   Spread: {spread_bps:.2f} bps")
                logger.info(f"   Est. Profit: ${estimated_profit:.4f}")
                
                opportunities.append(opp)


# ==============================
# MAIN
# ==============================

async def main():
    logger.info("=" * 60)
    logger.info("🚀 NEW TOKEN LAUNCH ARBITRAGE BOT")
    logger.info("=" * 60)
    logger.info(f"Monitoring DEXes: Raydium, Meteora, PumpFun")
    logger.info(f"Min Spread: {MIN_SPREAD_BPS} bps")
    logger.info("=" * 60)
    
    client = AsyncClient(RPC_URL)
    
    try:
        # Run monitors in parallel
        await asyncio.gather(
            monitor_new_pools(client),
            monitor_prices(),
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
