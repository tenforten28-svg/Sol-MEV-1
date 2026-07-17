"""
Calculate CLMM Price from Tick Index
====================================
For CLMM pools: price = 1.0001^tick
This is more reliable than parsing sqrt_price
"""

import asyncio
import os
import struct
import math
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

load_dotenv()

RPC_URL = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Pools to check
POOLS = [
    ("Orca Whirlpool 2", "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ"),
    ("Orca Whirlpool Main", "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"),
]


def tick_to_price(tick: int, decimals_a: int = 9, decimals_b: int = 6) -> float:
    """
    Convert tick index to price
    price = 1.0001^tick * 10^(decimals_a - decimals_b)
    """
    raw_price = 1.0001 ** tick
    decimal_adjustment = 10 ** (decimals_a - decimals_b)
    return raw_price * decimal_adjustment


def find_tick_in_data(data: bytes) -> list:
    """Find possible tick values (i32) that give reasonable prices"""
    candidates = []
    
    # For SOL at ~$190, tick should be around:
    # 190 = 1.0001^tick * 10^3 (for SOL/USDC with 9/6 decimals)
    # 0.19 = 1.0001^tick
    # tick = log(0.19) / log(1.0001) ≈ -16600
    
    # Or if inverted:
    # 190 = 1.0001^tick / 10^3
    # 190000 = 1.0001^tick
    # tick = log(190000) / log(1.0001) ≈ 121600
    
    expected_ticks = range(-20000, 150000, 1)  # Wide range
    
    for offset in range(0, len(data) - 4, 4):
        try:
            # Read as signed i32
            tick = struct.unpack_from("<i", data, offset)[0]
            
            # Skip unreasonable ticks
            if tick < -500000 or tick > 500000:
                continue
            
            # Calculate price
            try:
                price = tick_to_price(tick)
                price_inv = tick_to_price(-tick)
                
                # Check if either interpretation gives reasonable SOL price
                if 150 < price < 250:
                    candidates.append({
                        'offset': offset,
                        'tick': tick,
                        'price': price,
                        'interpretation': 'direct'
                    })
                elif 150 < price_inv < 250:
                    candidates.append({
                        'offset': offset,
                        'tick': tick,
                        'price': price_inv,
                        'interpretation': 'inverted (-tick)'
                    })
                elif 150 < 1/price < 250 and price > 0:
                    candidates.append({
                        'offset': offset,
                        'tick': tick,
                        'price': 1/price,
                        'interpretation': '1/price'
                    })
            except:
                pass
        except:
            pass
    
    return candidates


async def analyze_pool(client, name, address):
    """Analyze pool to find tick and price"""
    print(f"\n{'='*60}")
    print(f"Analyzing: {name}")
    print(f"Address: {address}")
    print(f"{'='*60}")
    
    pubkey = Pubkey.from_string(address)
    resp = await client.get_account_info(pubkey)
    
    if not resp.value:
        print("Account not found")
        return None
    
    data = resp.value.data
    if isinstance(data, (list, tuple)):
        data = bytes(data)
    
    print(f"Data size: {len(data)} bytes")
    
    # Find tick candidates
    candidates = find_tick_in_data(data)
    
    if candidates:
        print(f"\n✅ Found {len(candidates)} candidate tick positions:\n")
        
        # Sort by how close to expected price
        candidates.sort(key=lambda x: abs(x['price'] - 190))
        
        for c in candidates[:10]:
            print(f"  Offset {c['offset']}: tick={c['tick']}, price=${c['price']:.2f} ({c['interpretation']})")
        
        best = candidates[0]
        print(f"\n🎯 Best match: offset {best['offset']}, tick={best['tick']}, price=${best['price']:.2f}")
        return best
    else:
        print("\n❌ No valid tick found")
        
        # Debug: show values at common Whirlpool offsets
        # Whirlpool tick_current_index is typically around offset 69-73
        print("\nDebug - checking common offsets for tick:")
        for offset in [65, 69, 73, 77, 81, 85, 89, 93]:
            try:
                tick = struct.unpack_from("<i", data, offset)[0]
                if -500000 < tick < 500000:
                    price = tick_to_price(tick)
                    price2 = tick_to_price(-tick)
                    print(f"  Offset {offset}: tick={tick}, price=${price:.6f}, inv_price=${price2:.6f}")
            except:
                pass
    
    return None


async def main():
    print("="*60)
    print("CLMM TICK-BASED PRICE FINDER")
    print("="*60)
    print("For CLMM pools, price = 1.0001^tick")
    print(f"Expected SOL price: ~$190")
    
    client = AsyncClient(RPC_URL)
    
    try:
        results = {}
        for name, address in POOLS:
            result = await analyze_pool(client, name, address)
            if result:
                results[name] = result
        
        if results:
            print("\n" + "="*60)
            print("FINAL RESULTS")
            print("="*60)
            for name, r in results.items():
                print(f"\n{name}:")
                print(f"  Tick offset: {r['offset']}")
                print(f"  Tick value: {r['tick']}")
                print(f"  Price: ${r['price']:.2f}/SOL")
    
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
