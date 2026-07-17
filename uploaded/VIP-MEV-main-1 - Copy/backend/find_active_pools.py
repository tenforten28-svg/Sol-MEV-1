"""
Find Active SOL/USDC Pools
==========================
Queries multiple known pool addresses to find ones with correct market prices.
"""

import asyncio
import os
import struct
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

load_dotenv()

RPC_URL = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Known SOL/USDC pools to check
POOLS_TO_CHECK = {
    # Legacy Raydium AMM V4
    "raydium_v4_legacy": {
        "pool": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
        "type": "AMM_V4"
    },
    # Raydium CPMM (from docs)
    "raydium_cpmm": {
        "pool": "7JuwJuNU88gurFnyWeiyGKbFmExMWcmRZntn9imEzdny",
        "type": "CPMM"
    },
    # Orca Whirlpool
    "orca_whirlpool": {
        "pool": "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE",
        "type": "WHIRLPOOL"
    },
}

# Additional pools to try (common SOL/USDC pools)
ADDITIONAL_POOLS = [
    "HhJpBhRRn4g56VsyLuT8DL5Bv31HkXqsrahTTUCZeZg4",  # Possible CLMM
    "Ds33rQ1d4AXwxqyeXX6Pc3G4pFNr6iWb3dd8YfBBQMPr",  # Possible newer pool
    "2AXXcN6oN9bBT5owwmTH53C7QHUXvhLeu718Kqt8rvY2",  # Another SOL/USDC
]


async def fetch_amm_v4_pool(client, pool_address):
    """Fetch AMM V4 pool data and extract vaults"""
    try:
        pool_pubkey = Pubkey.from_string(pool_address)
        resp = await client.get_account_info(pool_pubkey)
        
        if not resp.value:
            return None
        
        data = resp.value.data
        if isinstance(data, (list, tuple)):
            data = bytes(data)
        
        if len(data) < 464:
            return None
        
        # AMM V4 layout
        base_vault = Pubkey.from_bytes(data[336:368])
        quote_vault = Pubkey.from_bytes(data[368:400])
        coin_mint = Pubkey.from_bytes(data[400:432])
        pc_mint = Pubkey.from_bytes(data[432:464])
        
        return {
            'base_vault': str(base_vault),
            'quote_vault': str(quote_vault),
            'coin_mint': str(coin_mint),
            'pc_mint': str(pc_mint),
        }
    except:
        return None


async def fetch_vault_balance(client, vault_address):
    """Fetch token balance from vault"""
    try:
        pubkey = Pubkey.from_string(vault_address)
        resp = await client.get_account_info(pubkey)
        
        if not resp.value:
            return 0
        
        data = resp.value.data
        if isinstance(data, (list, tuple)):
            data = bytes(data)
        
        if len(data) >= 72:
            return struct.unpack_from("<Q", data, 64)[0]
    except:
        pass
    return 0


async def check_pool_price(client, pool_name, base_vault, quote_vault, base_dec=9, quote_dec=6):
    """Check price from vault balances"""
    base_bal = await fetch_vault_balance(client, base_vault)
    quote_bal = await fetch_vault_balance(client, quote_vault)
    
    if base_bal == 0:
        return None
    
    base_amount = base_bal / (10 ** base_dec)
    quote_amount = quote_bal / (10 ** quote_dec)
    price = quote_amount / base_amount
    
    return {
        'base_balance': base_amount,
        'quote_balance': quote_amount,
        'price': price,
        'base_vault': base_vault,
        'quote_vault': quote_vault,
    }


async def main():
    print("="*70)
    print("SEARCHING FOR ACTIVE SOL/USDC POOLS WITH CORRECT PRICES")
    print("="*70)
    print(f"Expected SOL price: ~$180-200")
    print(f"RPC: {RPC_URL[:50]}...")
    print()
    
    client = AsyncClient(RPC_URL)
    
    results = []
    
    try:
        # Check known Raydium V4 pool
        print("Checking Raydium AMM V4 Legacy Pool...")
        pool_data = await fetch_amm_v4_pool(client, POOLS_TO_CHECK["raydium_v4_legacy"]["pool"])
        if pool_data:
            price_data = await check_pool_price(
                client, "raydium_v4_legacy",
                pool_data['base_vault'], pool_data['quote_vault']
            )
            if price_data:
                results.append({
                    'name': 'Raydium V4 Legacy',
                    'pool': POOLS_TO_CHECK["raydium_v4_legacy"]["pool"],
                    **price_data
                })
        
        # Check Orca Whirlpool - different structure
        print("Checking Orca Whirlpool...")
        orca_pool = POOLS_TO_CHECK["orca_whirlpool"]["pool"]
        try:
            orca_pubkey = Pubkey.from_string(orca_pool)
            orca_resp = await client.get_account_info(orca_pubkey)
            
            if orca_resp.value:
                data = orca_resp.value.data
                if isinstance(data, (list, tuple)):
                    data = bytes(data)
                
                if len(data) >= 240:
                    # Whirlpool layout
                    token_vault_a = Pubkey.from_bytes(data[125:157])
                    token_vault_b = Pubkey.from_bytes(data[205:237])
                    
                    price_data = await check_pool_price(
                        client, "orca_whirlpool",
                        str(token_vault_a), str(token_vault_b)
                    )
                    if price_data:
                        results.append({
                            'name': 'Orca Whirlpool',
                            'pool': orca_pool,
                            **price_data
                        })
        except Exception as e:
            print(f"  Error with Orca: {e}")
        
        # Check additional pools
        print("Checking additional pools...")
        for pool_addr in ADDITIONAL_POOLS:
            try:
                pool_data = await fetch_amm_v4_pool(client, pool_addr)
                if pool_data:
                    # Verify it's SOL/USDC
                    sol_mint = "So11111111111111111111111111111111111111112"
                    usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                    
                    if pool_data['coin_mint'] == sol_mint or pool_data['pc_mint'] == sol_mint:
                        price_data = await check_pool_price(
                            client, pool_addr[:8],
                            pool_data['base_vault'], pool_data['quote_vault']
                        )
                        if price_data:
                            results.append({
                                'name': f'Pool {pool_addr[:8]}',
                                'pool': pool_addr,
                                **price_data
                            })
            except:
                pass
        
        # Print results
        print("\n" + "="*70)
        print("RESULTS - POOLS FOUND")
        print("="*70)
        
        for r in results:
            is_active = 150 < r['price'] < 250  # Reasonable SOL price range
            status = "✅ ACTIVE" if is_active else "❌ STALE"
            
            print(f"\n{r['name']} {status}")
            print(f"  Pool: {r['pool']}")
            print(f"  Price: ${r['price']:.2f} per SOL")
            print(f"  SOL Balance: {r['base_balance']:,.2f}")
            print(f"  USDC Balance: {r['quote_balance']:,.2f}")
            print(f"  Base Vault: {r['base_vault']}")
            print(f"  Quote Vault: {r['quote_vault']}")
        
        # Find active pools
        active_pools = [r for r in results if 150 < r['price'] < 250]
        
        if len(active_pools) >= 2:
            print("\n" + "="*70)
            print("🎯 RECOMMENDED ARBITRAGE PAIR CONFIG")
            print("="*70)
            
            for i, p in enumerate(active_pools[:2]):
                print(f"""
'{p['name'].lower().replace(' ', '_')}': {{
    'address': '{p['pool']}',
    'base_vault': '{p['base_vault']}',
    'quote_vault': '{p['quote_vault']}',
    'base_decimals': 9,
    'quote_decimals': 6,
    'dex': '{'raydium' if 'raydium' in p['name'].lower() else 'orca'}',
    'fee_bps': 25,
    'pair': 'SOL/USDC'
}},""")
        elif len(active_pools) == 1:
            print("\n⚠️  Only 1 active pool found. Need 2 pools for arbitrage.")
            print("The Orca pool appears active. Need to find another active Raydium pool.")
        else:
            print("\n❌ No active pools found with correct market prices!")
            print("This might mean:")
            print("  1. We need different pool addresses")
            print("  2. The pools are using different token pairs")
        
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
