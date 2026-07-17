"""
REAL-TIME NEW POOL MONITOR
==========================
Monitors for new token launches across:
- Raydium (new pools)
- Meteora (new DLMM pairs)
- PumpFun (graduations to Raydium)

Alerts when arbitrage opportunity detected
"""

import asyncio
import os
import json
import time
from typing import Dict, Set
from collections import defaultdict
import logging
from dotenv import load_dotenv
from solana.rpc.websocket_api import connect
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s'
)
logger = logging.getLogger('new_pool_monitor')

WSS_URL = os.environ.get('QUICKNODE_WSS_URL')
RPC_URL = os.environ.get('SOLANA_RPC_URL')

# Program IDs to monitor
RAYDIUM_AMM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
RAYDIUM_CLMM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
RAYDIUM_CPMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
METEORA_DLMM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# Track seen tokens and their pools
token_pools: Dict[str, Dict[str, dict]] = defaultdict(dict)  # token -> {dex: pool_info}
recently_seen: Set[str] = set()  # Avoid duplicate processing

# Stats
stats = {
    'new_pools': 0,
    'opportunities': 0,
    'start_time': time.time()
}


async def subscribe_to_program_logs():
    """Subscribe to transaction logs for all DEX programs"""
    
    logger.info("=" * 60)
    logger.info("🔍 NEW POOL MONITOR - REAL TIME")
    logger.info("=" * 60)
    logger.info("Monitoring: Raydium, Meteora, PumpFun")
    logger.info("Looking for: New token launches & arbitrage")
    logger.info("=" * 60)
    
    async with connect(WSS_URL) as ws:
        # Subscribe to each program's logs
        programs = [
            ("Raydium AMM", RAYDIUM_AMM),
            ("Raydium CLMM", RAYDIUM_CLMM),
            ("Raydium CPMM", RAYDIUM_CPMM),
            ("Meteora DLMM", METEORA_DLMM),
            ("PumpFun", PUMPFUN),
        ]
        
        for name, program in programs:
            try:
                await ws.logs_subscribe(
                    filter_={"mentions": [program]},
                    commitment="confirmed"
                )
                logger.info(f"  ✓ Subscribed to {name}")
            except Exception as e:
                logger.error(f"  ✗ Failed {name}: {e}")
        
        logger.info("\n🎯 Listening for new pools...\n")
        
        async for msg in ws:
            await process_message(msg)


async def process_message(msg):
    """Process incoming log messages"""
    try:
        if not isinstance(msg, list):
            return
        
        for item in msg:
            if not hasattr(item, 'result'):
                continue
            
            result = item.result
            if not hasattr(result, 'value') or not result.value:
                continue
            
            value = result.value
            logs = getattr(value, 'logs', []) or []
            signature = getattr(value, 'signature', '')
            
            if not logs or not signature:
                continue
            
            # Skip if we've seen this transaction
            if signature in recently_seen:
                continue
            recently_seen.add(signature)
            
            # Keep set from growing too large
            if len(recently_seen) > 10000:
                recently_seen.clear()
            
            # Analyze logs for pool creation events
            await analyze_logs(logs, signature)
            
    except Exception as e:
        logger.debug(f"Message processing error: {e}")


async def analyze_logs(logs: list, signature: str):
    """Analyze transaction logs for pool creation events"""
    
    log_text = ' '.join(logs).lower()
    
    # Detect different types of pool creation
    is_pool_creation = False
    dex = None
    event_type = None
    
    # Raydium AMM initialization
    if 'program 675kpx9mhtjs2zt1qfr1nyhuzeljxfqm9h24wfsut1mp8' in log_text:
        if 'initialize' in log_text:
            is_pool_creation = True
            dex = 'raydium_amm'
            event_type = 'AMM Pool Created'
    
    # Raydium CLMM
    elif 'program cammc' in log_text.replace(' ', ''):
        if 'createpool' in log_text or 'initialize' in log_text:
            is_pool_creation = True
            dex = 'raydium_clmm'
            event_type = 'CLMM Pool Created'
    
    # Raydium CPMM
    elif 'program cpmmoo8l3f4nbtegbckvnunggl7h1zpdthkxqb5qkp1c' in log_text:
        if 'initialize' in log_text or 'create' in log_text:
            is_pool_creation = True
            dex = 'raydium_cpmm'
            event_type = 'CPMM Pool Created'
    
    # Meteora DLMM
    elif 'program lbuzkhrxpf3xupbcjp4yztkg' in log_text:
        if 'initializelbpair' in log_text or 'initialize' in log_text:
            is_pool_creation = True
            dex = 'meteora_dlmm'
            event_type = 'Meteora DLMM Created'
    
    # PumpFun graduation
    elif 'program 6ef8rrecth' in log_text:
        if 'graduate' in log_text or 'migrate' in log_text:
            is_pool_creation = True
            dex = 'pumpfun'
            event_type = 'PumpFun Graduation'
    
    if is_pool_creation:
        stats['new_pools'] += 1
        
        logger.info(f"\n🆕 {event_type}!")
        logger.info(f"   DEX: {dex}")
        logger.info(f"   TX: {signature[:40]}...")
        logger.info(f"   Time: {time.strftime('%H:%M:%S')}")
        
        # Fetch pool details in background
        asyncio.create_task(fetch_and_analyze_pool(signature, dex))


async def fetch_and_analyze_pool(signature: str, dex: str):
    """Fetch pool details and check for arbitrage"""
    
    client = AsyncClient(RPC_URL)
    
    try:
        # Get transaction details
        tx = await client.get_transaction(
            signature,
            encoding="jsonParsed",
            max_supported_transaction_version=0
        )
        
        if not tx.value:
            return
        
        # Extract token mints from transaction
        meta = tx.value.transaction.meta
        if not meta:
            return
        
        # Look for new token mints in post balances
        post_balances = getattr(meta, 'post_token_balances', [])
        
        # Common quote tokens
        quote_tokens = {
            "So11111111111111111111111111111111111111112",  # SOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
        }
        
        new_tokens = set()
        for balance in post_balances:
            mint = getattr(balance, 'mint', '')
            if mint and mint not in quote_tokens:
                new_tokens.add(mint)
        
        if new_tokens:
            for token in new_tokens:
                logger.info(f"   Token: {token[:20]}...")
                
                # Add to our tracking
                token_pools[token][dex] = {
                    'signature': signature,
                    'detected_at': time.time()
                }
                
                # Check if token exists on multiple DEXes
                if len(token_pools[token]) >= 2:
                    await check_arbitrage_opportunity(token)
        
    except Exception as e:
        logger.debug(f"Error fetching pool: {e}")
    
    finally:
        await client.close()


async def check_arbitrage_opportunity(token: str):
    """Check if there's an arbitrage opportunity for this token"""
    
    pools = token_pools[token]
    
    if len(pools) < 2:
        return
    
    logger.info(f"\n⚡ POTENTIAL ARBITRAGE - Token on {len(pools)} DEXes!")
    logger.info(f"   Token: {token[:20]}...")
    
    for dex, info in pools.items():
        age = time.time() - info['detected_at']
        logger.info(f"   - {dex} (detected {age:.0f}s ago)")
    
    stats['opportunities'] += 1
    
    # Here you would:
    # 1. Fetch current prices from each pool
    # 2. Calculate spread
    # 3. Execute if profitable
    
    logger.info("   → Fetching prices for comparison...")


async def print_stats():
    """Periodically print statistics"""
    while True:
        await asyncio.sleep(60)
        
        runtime = (time.time() - stats['start_time']) / 60
        logger.info(f"\n📊 Stats: {runtime:.1f}min | Pools: {stats['new_pools']} | Opportunities: {stats['opportunities']}")


async def main():
    """Run the monitor"""
    try:
        await asyncio.gather(
            subscribe_to_program_logs(),
            print_stats(),
        )
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
