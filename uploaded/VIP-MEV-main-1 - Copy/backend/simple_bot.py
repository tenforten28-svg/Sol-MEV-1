"""
Simple Working Bot - With CLMM Price Calculation
=================================================
Uses tick-based pricing for Orca Whirlpools (CLMM pools)
"""
import asyncio
import os
import struct
import time
from dotenv import load_dotenv
from solana.rpc.websocket_api import connect
from solders.pubkey import Pubkey

load_dotenv()

WSS_URL = os.environ.get('QUICKNODE_WSS_URL')

# CLMM Pools - subscribe to pool accounts, not vaults
POOLS = {
    'orca_whirlpool_1': {
        'pool_address': 'HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ',
        'tick_offset': 81,  # Offset where tick_current_index is stored
        'base_decimals': 9,  # SOL
        'quote_decimals': 6,  # USDC
        'dex': 'orca',
    },
    'orca_whirlpool_2': {
        'pool_address': 'Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE',
        'tick_offset': 81,
        'base_decimals': 9,
        'quote_decimals': 6,
        'dex': 'orca',
    },
}

subscription_map = {}
pool_prices = {}
msg_count = 0
last_print = 0


def tick_to_price(tick: int, base_decimals: int = 9, quote_decimals: int = 6) -> float:
    """
    Convert CLMM tick index to human-readable price
    Formula: price = 1.0001^tick * 10^(base_decimals - quote_decimals)
    """
    raw_price = 1.0001 ** tick
    decimal_adjustment = 10 ** (base_decimals - quote_decimals)
    return raw_price * decimal_adjustment


def parse_tick_from_data(data: bytes, offset: int) -> int:
    """Parse tick_current_index (i32) from pool data"""
    if len(data) < offset + 4:
        return 0
    return struct.unpack_from("<i", data, offset)[0]


def print_prices():
    """Print current prices and spread"""
    global last_print
    now = time.time()
    if now - last_print < 1:  # Rate limit to 1 per second
        return
    last_print = now
    
    prices = list(pool_prices.values())
    if len(prices) >= 2 and all(p > 0 for p in prices):
        p1 = prices[0]
        p2 = prices[1]
        spread_bps = abs(p1 - p2) / min(p1, p2) * 10000
        
        print(f"\n{'='*60}")
        for name, price in pool_prices.items():
            print(f"  {name}: ${price:.4f}")
        print(f"  SPREAD: {spread_bps:.2f} bps")
        print(f"{'='*60}")


async def main():
    global msg_count
    print(f"WSS: {WSS_URL[:50]}...")
    print("Subscribing to CLMM pool accounts for tick-based pricing...")
    
    pending = []
    
    async with connect(WSS_URL) as ws:
        print("Connected!")
        
        # Subscribe to pool accounts (not vaults)
        for pool_name, config in POOLS.items():
            addr = config['pool_address']
            await ws.account_subscribe(
                Pubkey.from_string(addr),
                commitment="processed",
                encoding="base64"
            )
            pending.append((pool_name, addr))
            print(f"  Sent: {pool_name}")
        
        print(f"Waiting for confirmations...")
        
        sub_idx = 0
        
        async for msg in ws:
            msg_count += 1
            
            if not isinstance(msg, list):
                continue
            
            for item in msg:
                name = type(item).__name__
                
                if name == 'SubscriptionResult':
                    if sub_idx < len(pending):
                        pool_name, addr = pending[sub_idx]
                        subscription_map[item.result] = (pool_name, addr)
                        print(f"  OK: {pool_name} (id:{item.result})")
                        sub_idx += 1
                        if sub_idx == len(pending):
                            print(f"\nAll subscribed! Listening for price updates...\n")
                
                elif name == 'AccountNotification':
                    sub_id = item.subscription
                    
                    if sub_id in subscription_map:
                        pool_name, addr = subscription_map[sub_id]
                        config = POOLS[pool_name]
                        
                        # Get pool data
                        data = item.result.value.data
                        
                        # Handle different data formats
                        if isinstance(data, bytes):
                            pool_data = data
                        elif isinstance(data, (list, tuple)):
                            if isinstance(data[0], int):
                                pool_data = bytes(data)
                            else:
                                import base64
                                pool_data = base64.b64decode(data[0])
                        else:
                            continue
                        
                        # Parse tick and calculate price
                        tick = parse_tick_from_data(pool_data, config['tick_offset'])
                        price = tick_to_price(tick, config['base_decimals'], config['quote_decimals'])
                        
                        pool_prices[pool_name] = price
                        
                        # Print prices when we have both
                        print_prices()


if __name__ == "__main__":
    asyncio.run(main())
