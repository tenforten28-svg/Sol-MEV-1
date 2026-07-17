"""
Fetch Pool Data from Raydium API
================================
Uses Raydium's official API to get correct pool information
"""

import asyncio
import aiohttp
import json

RAYDIUM_API = "https://api-v3.raydium.io"

async def fetch_raydium_pools():
    """Fetch SOL/USDC pools from Raydium API"""
    print("Fetching pools from Raydium API...")
    
    async with aiohttp.ClientSession() as session:
        # Get all AMM pools
        url = f"{RAYDIUM_API}/pools/info/list"
        params = {
            "poolType": "all",
            "poolSortField": "volume24h",
            "sortType": "desc",
            "pageSize": 100,
            "page": 1
        }
        
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pools = data.get('data', {}).get('data', [])
                    
                    print(f"\nFound {len(pools)} pools")
                    print("\nSearching for SOL/USDC pools...\n")
                    
                    sol_usdc_pools = []
                    for pool in pools:
                        mint_a = pool.get('mintA', {}).get('symbol', '')
                        mint_b = pool.get('mintB', {}).get('symbol', '')
                        
                        if ('SOL' in mint_a and 'USDC' in mint_b) or ('USDC' in mint_a and 'SOL' in mint_b):
                            sol_usdc_pools.append(pool)
                    
                    print(f"Found {len(sol_usdc_pools)} SOL/USDC pools:\n")
                    
                    for i, pool in enumerate(sol_usdc_pools[:5]):  # Show top 5
                        print(f"{'='*60}")
                        print(f"Pool #{i+1}")
                        print(f"  ID: {pool.get('id')}")
                        print(f"  Type: {pool.get('type')}")
                        print(f"  Program: {pool.get('programId')}")
                        print(f"  Pair: {pool.get('mintA', {}).get('symbol')}/{pool.get('mintB', {}).get('symbol')}")
                        print(f"  TVL: ${pool.get('tvl', 0):,.2f}")
                        print(f"  24h Volume: ${pool.get('day', {}).get('volume', 0):,.2f}")
                        
                        # Vault addresses
                        vault_a = pool.get('mintA', {}).get('vault')
                        vault_b = pool.get('mintB', {}).get('vault')
                        mint_a_addr = pool.get('mintA', {}).get('address')
                        mint_b_addr = pool.get('mintB', {}).get('address')
                        
                        print(f"  Mint A: {mint_a_addr}")
                        print(f"  Vault A: {vault_a}")
                        print(f"  Mint B: {mint_b_addr}")
                        print(f"  Vault B: {vault_b}")
                        print()
                    
                    return sol_usdc_pools
                else:
                    print(f"API Error: {resp.status}")
                    text = await resp.text()
                    print(text[:500])
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
    
    return []


async def fetch_specific_pool(pool_id):
    """Fetch specific pool details"""
    print(f"\nFetching pool {pool_id}...")
    
    async with aiohttp.ClientSession() as session:
        url = f"{RAYDIUM_API}/pools/info/ids"
        params = {"ids": pool_id}
        
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pools = data.get('data', [])
                    
                    if pools:
                        pool = pools[0]
                        print(f"\n{'='*60}")
                        print("POOL DETAILS")
                        print(f"{'='*60}")
                        print(json.dumps(pool, indent=2))
                        return pool
                else:
                    print(f"Error: {resp.status}")
        except Exception as e:
            print(f"Error: {e}")
    
    return None


async def main():
    print("="*60)
    print("RAYDIUM POOL FETCHER")
    print("="*60)
    
    # Fetch all SOL/USDC pools
    pools = await fetch_raydium_pools()
    
    if pools:
        print("\n" + "="*60)
        print("RECOMMENDED CONFIG FOR BOT")
        print("="*60)
        
        # Find the highest TVL AMM pool
        amm_pools = [p for p in pools if p.get('type') == 'Standard']
        if amm_pools:
            best = amm_pools[0]
            print(f"""
# Best Raydium AMM SOL/USDC Pool (by TVL)
RAYDIUM_SOL_USDC = {{
    "address": "{best.get('id')}",
    "base_vault": "{best.get('mintA', {}).get('vault')}",
    "quote_vault": "{best.get('mintB', {}).get('vault')}",
    "base_mint": "{best.get('mintA', {}).get('address')}",
    "quote_mint": "{best.get('mintB', {}).get('address')}",
    "base_decimals": {best.get('mintA', {}).get('decimals', 9)},
    "quote_decimals": {best.get('mintB', {}).get('decimals', 6)},
    "dex": "raydium",
    "fee_bps": 25,
    "pair": "SOL/USDC"
}}
""")


if __name__ == "__main__":
    asyncio.run(main())
