"""
Find Raydium CLMM Pools
=======================
CLMM pools are where the active trading happens.
Different data structure than AMM V4.
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

# Raydium CLMM Program ID
RAYDIUM_CLMM_PROGRAM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"

# Known CLMM SOL/USDC pools (various fee tiers)
CLMM_POOLS = [
    "2QdhepnKRTLjjSqPL1PtKNwqrUkoLee5Gqs8bvZhRdMv",  # SOL/USDC 0.01%
    "BKgwCn9DNHB4fFQKms8hUWbS4wZFqDsZKbJMpj6VmTgL",  # SOL/USDC 0.05%
    "pool_address_3",  # placeholder
]

# Orca Whirlpool Program
ORCA_WHIRLPOOL_PROGRAM = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"

# Known Orca SOL/USDC Whirlpools
ORCA_POOLS = [
    "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",  # Legacy
    "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE",  # Main Whirlpool
    "7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm",  # Another one
]

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def fetch_token_balance(client, vault_address):
    """Fetch balance from token vault"""
    try:
        pubkey = Pubkey.from_string(vault_address)
        resp = await client.get_account_info(pubkey)
        if resp.value:
            data = resp.value.data
            if isinstance(data, (list, tuple)):
                data = bytes(data)
            if len(data) >= 72:
                return struct.unpack_from("<Q", data, 64)[0]
    except:
        pass
    return 0


async def check_clmm_pool(client, pool_address):
    """
    Parse Raydium CLMM pool state
    CLMM layout is different from AMM V4
    """
    try:
        pubkey = Pubkey.from_string(pool_address)
        resp = await client.get_account_info(pubkey)
        
        if not resp.value:
            return None
        
        data = resp.value.data
        if isinstance(data, (list, tuple)):
            data = bytes(data)
        
        # Raydium CLMM PoolState layout (approximate):
        # This varies by version, need to check actual layout
        # Key fields we need: token_vault_0, token_vault_1, sqrt_price_x64
        
        if len(data) < 200:
            return None
        
        # Try to find pubkeys in the data (32 bytes each)
        # CLMM pools have vaults and mints at various offsets
        
        # Check owner to verify it's CLMM
        owner = str(resp.value.owner)
        
        print(f"  Pool {pool_address[:16]}...")
        print(f"    Owner: {owner}")
        print(f"    Data size: {len(data)} bytes")
        
        if owner != RAYDIUM_CLMM_PROGRAM:
            print(f"    Not a CLMM pool (owner mismatch)")
            return None
        
        # Parse CLMM state - offsets may vary
        # Common structure:
        # bump, amm_config, creator, mint_0, mint_1, vault_0, vault_1, ...
        
        # Try offset-based parsing
        possible_vaults = []
        for offset in range(0, min(len(data)-32, 400), 32):
            try:
                maybe_pubkey = Pubkey.from_bytes(data[offset:offset+32])
                pubkey_str = str(maybe_pubkey)
                # Check if it looks like a valid Solana address (not all zeros or all ones)
                if pubkey_str != "11111111111111111111111111111111" and not pubkey_str.startswith("1111"):
                    # Try to fetch as token account
                    bal = await fetch_token_balance(client, pubkey_str)
                    if bal > 0:
                        possible_vaults.append({
                            'offset': offset,
                            'address': pubkey_str,
                            'balance': bal
                        })
            except:
                pass
        
        if possible_vaults:
            print(f"    Found {len(possible_vaults)} potential vaults:")
            for v in possible_vaults[:6]:  # Show first 6
                print(f"      Offset {v['offset']}: {v['address'][:20]}... bal={v['balance']}")
        
        return possible_vaults
        
    except Exception as e:
        print(f"  Error: {e}")
        return None


async def check_orca_whirlpool(client, pool_address):
    """Parse Orca Whirlpool state"""
    try:
        pubkey = Pubkey.from_string(pool_address)
        resp = await client.get_account_info(pubkey)
        
        if not resp.value:
            return None
        
        data = resp.value.data
        if isinstance(data, (list, tuple)):
            data = bytes(data)
        
        owner = str(resp.value.owner)
        print(f"  Pool {pool_address[:16]}...")
        print(f"    Owner: {owner}")
        print(f"    Data size: {len(data)} bytes")
        
        if len(data) < 850:
            print(f"    ❌ Data too small for Whirlpool")
            return None
        
        # Whirlpool layout with Anchor (8-byte discriminator):
        # Offset 744: token_mint_a (32 bytes)
        # Offset 776: token_vault_a (32 bytes)
        # Offset 808: token_mint_b (32 bytes)
        # Offset 840: token_vault_b (32 bytes)
        
        token_mint_a = Pubkey.from_bytes(data[744:776])
        token_vault_a = Pubkey.from_bytes(data[776:808])
        token_mint_b = Pubkey.from_bytes(data[808:840])
        token_vault_b = Pubkey.from_bytes(data[840:872])
        
        print(f"    Mint A: {token_mint_a}")
        print(f"    Vault A: {token_vault_a}")
        print(f"    Mint B: {token_mint_b}")
        print(f"    Vault B: {token_vault_b}")
        
        # Check if SOL/USDC pair
        mint_a_str = str(token_mint_a)
        mint_b_str = str(token_mint_b)
        
        is_sol_usdc = (
            (mint_a_str == SOL_MINT and mint_b_str == USDC_MINT) or
            (mint_a_str == USDC_MINT and mint_b_str == SOL_MINT)
        )
        
        if not is_sol_usdc:
            print(f"    ❌ Not SOL/USDC pair")
            return None
        
        print(f"    ✅ SOL/USDC pair confirmed!")
        
        # Fetch vault balances
        vault_a_bal = await fetch_token_balance(client, str(token_vault_a))
        vault_b_bal = await fetch_token_balance(client, str(token_vault_b))
        
        # Determine which is SOL and which is USDC
        if mint_a_str == SOL_MINT:
            sol_balance = vault_a_bal / 1e9
            usdc_balance = vault_b_bal / 1e6
            sol_vault = str(token_vault_a)
            usdc_vault = str(token_vault_b)
        else:
            sol_balance = vault_b_bal / 1e9
            usdc_balance = vault_a_bal / 1e6
            sol_vault = str(token_vault_b)
            usdc_vault = str(token_vault_a)
        
        # For CLMM/Whirlpool, price is calculated from sqrt_price_x64
        # Located earlier in the struct - let's try offset around 200-300
        # sqrtPrice is u128 (16 bytes)
        
        # Try reading sqrt_price at common offsets
        for sqrt_offset in [200, 216, 232, 248, 264]:
            try:
                sqrt_price_low = struct.unpack_from("<Q", data, sqrt_offset)[0]
                sqrt_price_high = struct.unpack_from("<Q", data, sqrt_offset + 8)[0]
                sqrt_price_x64 = (sqrt_price_high << 64) | sqrt_price_low
                
                if sqrt_price_x64 > 0:
                    sqrt_price = sqrt_price_x64 / (2**64)
                    raw_price = sqrt_price ** 2
                    
                    # Adjust for decimals
                    if mint_a_str == SOL_MINT:
                        adjusted_price = raw_price * (10**3)  # USDC/SOL decimal diff
                    else:
                        adjusted_price = (1/raw_price) * (10**3) if raw_price > 0 else 0
                    
                    if 50 < adjusted_price < 500:  # Reasonable SOL price range
                        print(f"    Price from sqrt (offset {sqrt_offset}): ${adjusted_price:.2f}")
                        break
            except:
                pass
        
        # Also calculate from reserves
        price_from_reserves = usdc_balance / sol_balance if sol_balance > 0 else 0
        
        print(f"    SOL Balance: {sol_balance:,.2f}")
        print(f"    USDC Balance: {usdc_balance:,.2f}")
        print(f"    Price (reserves): ${price_from_reserves:.2f}")
        
        return {
            'pool': pool_address,
            'sol_vault': sol_vault,
            'usdc_vault': usdc_vault,
            'sol_balance': sol_balance,
            'usdc_balance': usdc_balance,
            'price': price_from_reserves if price_from_reserves > 50 else 0,
        }
        
    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    print("="*70)
    print("FINDING ACTIVE CLMM/WHIRLPOOL SOL/USDC POOLS")
    print("="*70)
    print(f"RPC: {RPC_URL[:50]}...")
    print()
    
    client = AsyncClient(RPC_URL)
    
    try:
        results = []
        
        # Check Orca Whirlpools
        print("\n--- ORCA WHIRLPOOLS ---")
        for pool in ORCA_POOLS:
            result = await check_orca_whirlpool(client, pool)
            if result and result.get('price', 0) > 100:
                results.append({
                    'name': 'Orca Whirlpool',
                    'dex': 'orca',
                    **result
                })
            print()
        
        # Summary
        print("\n" + "="*70)
        print("SUMMARY - ACTIVE POOLS FOUND")
        print("="*70)
        
        active = [r for r in results if 100 < r.get('price', 0) < 300]
        
        if active:
            for r in active:
                print(f"\n✅ {r['name']} - ${r['price']:.2f}/SOL")
                print(f"   Pool: {r['pool']}")
                print(f"   SOL Vault: {r['sol_vault']}")
                print(f"   USDC Vault: {r['usdc_vault']}")
                print(f"   Liquidity: {r['sol_balance']:,.0f} SOL / ${r['usdc_balance']:,.0f} USDC")
        else:
            print("\n❌ No active pools found")
            print("\nThe Orca Whirlpool pools use concentrated liquidity.")
            print("Vault balances may not reflect total liquidity.")
        
        # Print config
        if active:
            print("\n" + "="*70)
            print("RECOMMENDED CONFIG")
            print("="*70)
            for r in active:
                print(f"""
'{r['name'].lower().replace(' ', '_')}': {{
    'address': '{r['pool']}',
    'base_vault': '{r['sol_vault']}',
    'quote_vault': '{r['usdc_vault']}',
    'base_decimals': 9,
    'quote_decimals': 6,
    'dex': '{r['dex']}',
    'fee_bps': 30,
    'pair': 'SOL/USDC'
}},""")
        
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
