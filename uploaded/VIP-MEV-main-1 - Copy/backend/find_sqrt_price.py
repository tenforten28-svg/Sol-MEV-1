"""
Find sqrt_price offset in CLMM pools
====================================
Scan pool data to find where sqrt_price is located
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

# Known pools
ORCA_WHIRLPOOL = "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ"
ORCA_WHIRLPOOL_MAIN = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"

# Expected SOL price range
EXPECTED_PRICE_MIN = 150
EXPECTED_PRICE_MAX = 250


def try_sqrt_price_at_offset(data, offset, swap_direction=False):
    """Try to parse sqrt_price at given offset and calculate price"""
    try:
        if offset + 16 > len(data):
            return None
        
        # Read as u128 (little endian)
        low = struct.unpack_from("<Q", data, offset)[0]
        high = struct.unpack_from("<Q", data, offset + 8)[0]
        sqrt_price_x64 = (high << 64) | low
        
        if sqrt_price_x64 == 0:
            return None
        
        # sqrt_price is in Q64.64 format
        sqrt_price = sqrt_price_x64 / (2**64)
        
        # price = sqrt_price^2
        raw_price = sqrt_price ** 2
        
        # Adjust for decimals (SOL=9, USDC=6)
        # If token_a is SOL, price is in USDC/SOL
        price_a = raw_price * (10**6) / (10**9)  # = raw_price / 1000
        price_b = (1 / raw_price) * (10**6) / (10**9) if raw_price > 0 else 0
        
        return {
            'offset': offset,
            'sqrt_price_x64': sqrt_price_x64,
            'sqrt_price': sqrt_price,
            'raw_price': raw_price,
            'price_a_over_b': price_a,
            'price_b_over_a': 1/price_a if price_a > 0 else 0,
        }
    except:
        return None


async def find_sqrt_price(client, pool_address, pool_name):
    """Scan pool data to find sqrt_price offset"""
    print(f"\n{'='*60}")
    print(f"Scanning: {pool_name}")
    print(f"Address: {pool_address}")
    print(f"{'='*60}")
    
    pubkey = Pubkey.from_string(pool_address)
    resp = await client.get_account_info(pubkey)
    
    if not resp.value:
        print("Account not found")
        return
    
    data = resp.value.data
    if isinstance(data, (list, tuple)):
        data = bytes(data)
    
    print(f"Data size: {len(data)} bytes")
    print(f"Looking for sqrt_price that gives SOL price ${EXPECTED_PRICE_MIN}-${EXPECTED_PRICE_MAX}...")
    
    candidates = []
    
    # Try every possible offset
    for offset in range(0, len(data) - 16, 8):  # u128 is 16 bytes, try 8-byte aligned
        result = try_sqrt_price_at_offset(data, offset)
        if result:
            # Check if either price interpretation is reasonable
            if EXPECTED_PRICE_MIN < result['price_b_over_a'] < EXPECTED_PRICE_MAX:
                result['likely_price'] = result['price_b_over_a']
                result['interpretation'] = 'B/A (USDC per SOL)'
                candidates.append(result)
            elif EXPECTED_PRICE_MIN < result['price_a_over_b'] < EXPECTED_PRICE_MAX:
                result['likely_price'] = result['price_a_over_b']
                result['interpretation'] = 'A/B'
                candidates.append(result)
    
    if candidates:
        print(f"\n✅ Found {len(candidates)} candidate offsets:\n")
        for c in candidates[:5]:  # Show top 5
            print(f"  Offset {c['offset']}:")
            print(f"    sqrt_price_x64: {c['sqrt_price_x64']}")
            print(f"    sqrt_price: {c['sqrt_price']:.10f}")
            print(f"    Likely price: ${c['likely_price']:.2f}/SOL ({c['interpretation']})")
        
        # Return the best candidate (closest to expected price)
        best = min(candidates, key=lambda x: abs(x['likely_price'] - 190))
        print(f"\n🎯 Best match: offset {best['offset']} = ${best['likely_price']:.2f}/SOL")
        return best
    else:
        print("\n❌ No valid sqrt_price found")
        
        # Debug: show some raw values
        print("\nDebug - trying common offsets:")
        for offset in [40, 48, 56, 64, 72, 80, 88, 96]:
            result = try_sqrt_price_at_offset(data, offset)
            if result:
                print(f"  Offset {offset}: sqrt={result['sqrt_price']:.6f}, price_a={result['price_a_over_b']:.4f}, price_b={result['price_b_over_a']:.4f}")
    
    return None


async def main():
    print("="*60)
    print("SQRT_PRICE OFFSET FINDER")
    print("="*60)
    
    client = AsyncClient(RPC_URL)
    
    try:
        results = {}
        
        # Check Orca Whirlpool 2 (known working)
        result = await find_sqrt_price(client, ORCA_WHIRLPOOL, "Orca Whirlpool 2")
        if result:
            results['orca_whirlpool_2'] = result
        
        # Check Orca Whirlpool Main
        result = await find_sqrt_price(client, ORCA_WHIRLPOOL_MAIN, "Orca Whirlpool Main")
        if result:
            results['orca_whirlpool_main'] = result
        
        if results:
            print("\n" + "="*60)
            print("SUMMARY")
            print("="*60)
            for name, r in results.items():
                print(f"\n{name}:")
                print(f"  sqrt_price offset: {r['offset']}")
                print(f"  Price: ${r['likely_price']:.2f}/SOL")
        
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
