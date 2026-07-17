"""
Find Second Active Pool for Arbitrage
=====================================
We have Orca working. Now find Raydium CLMM or Meteora.
"""

import asyncio
import os
import struct
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
import base58

load_dotenv()

RPC_URL = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_BYTES = base58.b58decode(SOL_MINT)
USDC_BYTES = base58.b58decode(USDC_MINT)

# More pools to check
POOLS_TO_CHECK = [
    # Orca Whirlpools
    ("Orca Whirlpool 64tick", "7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm"),
    ("Orca Whirlpool 1tick", "83v8iPyZihDEjDdY8RdZddyZNyUtXngz69Lgo9Kt5d6d"),
    ("Orca Whirlpool 128tick", "5dMKUYJDsjZkAD3wiV3ViQkuq9pSmWQ5eAzcQLtDnUT3"),
    
    # Raydium CLMM pools (different program)
    ("Raydium CLMM 1", "2QdhepnKRTLjjSqPL1PtKNwqrUkoLee5Gqs8bvZhRdMv"),
    ("Raydium CLMM 2", "8sLbNZoA1cfnvMJLPfp98ZLAnFSYCFApfJKMbiXNLwxj"),
    
    # Meteora pools
    ("Meteora DLMM", "BVRbyLjjfSBcoyiYFuxbgKYnWuiFaF9CSXEa5vdSZ9Hh"),
    ("Meteora DLMM 2", "ARwi1S4DaiTG5DX7S4M4ZsrXqpMD1MrTmbu9ue2tpmEq"),
    
    # Phoenix (orderbook)
    ("Phoenix SOL/USDC", "4DoNfFBfF7UokCC2FQzriy7yHK6DY6NVdYpuekQ5pRgg"),
]


async def check_pool_for_sol_usdc(client, name, address):
    """Check if pool has SOL/USDC with correct price"""
    try:
        pubkey = Pubkey.from_string(address)
        resp = await client.get_account_info(pubkey)
        
        if not resp.value:
            return None
        
        data = resp.value.data
        if isinstance(data, (list, tuple)):
            data = bytes(data)
        
        owner = str(resp.value.owner)
        
        # Search for SOL and USDC mints
        sol_pos = None
        usdc_pos = None
        
        for i in range(len(data) - 32):
            if data[i:i+32] == SOL_BYTES:
                sol_pos = i
            if data[i:i+32] == USDC_BYTES:
                usdc_pos = i
        
        if sol_pos is None or usdc_pos is None:
            return None
        
        print(f"\n✅ {name}")
        print(f"   Pool: {address}")
        print(f"   Owner: {owner}")
        print(f"   SOL mint at offset {sol_pos}, USDC mint at offset {usdc_pos}")
        
        # Get vault addresses (next pubkey after mint)
        sol_vault = None
        usdc_vault = None
        sol_balance = 0
        usdc_balance = 0
        
        # Try the pubkey right after the mint
        if sol_pos + 64 <= len(data):
            try:
                vault_pubkey = Pubkey.from_bytes(data[sol_pos+32:sol_pos+64])
                vault_resp = await client.get_account_info(vault_pubkey)
                if vault_resp.value:
                    vault_data = vault_resp.value.data
                    if isinstance(vault_data, (list, tuple)):
                        vault_data = bytes(vault_data)
                    if len(vault_data) >= 72:
                        balance = struct.unpack_from("<Q", vault_data, 64)[0]
                        # Verify it's a SOL token account
                        mint_in_vault = Pubkey.from_bytes(vault_data[0:32])
                        if str(mint_in_vault) == SOL_MINT:
                            sol_vault = str(vault_pubkey)
                            sol_balance = balance / 1e9
            except:
                pass
        
        if usdc_pos + 64 <= len(data):
            try:
                vault_pubkey = Pubkey.from_bytes(data[usdc_pos+32:usdc_pos+64])
                vault_resp = await client.get_account_info(vault_pubkey)
                if vault_resp.value:
                    vault_data = vault_resp.value.data
                    if isinstance(vault_data, (list, tuple)):
                        vault_data = bytes(vault_data)
                    if len(vault_data) >= 72:
                        balance = struct.unpack_from("<Q", vault_data, 64)[0]
                        mint_in_vault = Pubkey.from_bytes(vault_data[0:32])
                        if str(mint_in_vault) == USDC_MINT:
                            usdc_vault = str(vault_pubkey)
                            usdc_balance = balance / 1e6
            except:
                pass
        
        if sol_vault and usdc_vault and sol_balance > 0:
            price = usdc_balance / sol_balance
            print(f"   SOL Vault: {sol_vault}")
            print(f"   USDC Vault: {usdc_vault}")
            print(f"   SOL Balance: {sol_balance:,.2f}")
            print(f"   USDC Balance: {usdc_balance:,.2f}")
            print(f"   Price: ${price:.2f}/SOL")
            
            # Check if price is reasonable
            if 100 < price < 300:
                print(f"   🎯 ACTIVE POOL - Price is reasonable!")
                return {
                    'name': name,
                    'pool': address,
                    'owner': owner,
                    'sol_vault': sol_vault,
                    'usdc_vault': usdc_vault,
                    'sol_balance': sol_balance,
                    'usdc_balance': usdc_balance,
                    'price': price
                }
            else:
                print(f"   ⚠️ Price seems off")
        
        return None
        
    except Exception as e:
        return None


async def main():
    print("="*60)
    print("SEARCHING FOR SECOND ACTIVE POOL")
    print("="*60)
    print("We have Orca Whirlpool 2 at ~$194/SOL")
    print("Looking for another pool with correct price...")
    
    client = AsyncClient(RPC_URL)
    
    try:
        active_pools = []
        
        # First add the known working Orca pool
        active_pools.append({
            'name': 'Orca Whirlpool 2',
            'pool': 'HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ',
            'sol_vault': '3YQm7ujtXWJU2e9jhp2QGHpnn1ShXn12QjvzMvDgabpX',
            'usdc_vault': '2JTw1fE2wz1SymWUQ7UqpVtrTuKjcd6mWwYwUJUCh2rq',
            'price': 193.79,
            'dex': 'orca'
        })
        
        # Check other pools
        for name, address in POOLS_TO_CHECK:
            result = await check_pool_for_sol_usdc(client, name, address)
            if result:
                active_pools.append(result)
        
        print("\n" + "="*60)
        print("ACTIVE POOLS FOUND")
        print("="*60)
        
        for p in active_pools:
            print(f"\n{p['name']}: ${p.get('price', 0):.2f}/SOL")
            print(f"  Pool: {p['pool']}")
            print(f"  SOL Vault: {p['sol_vault']}")
            print(f"  USDC Vault: {p['usdc_vault']}")
        
        if len(active_pools) >= 2:
            print("\n" + "="*60)
            print("🎉 CONFIG FOR ARBITRAGE BOT")
            print("="*60)
            
            for i, p in enumerate(active_pools[:2]):
                dex = p.get('dex', 'unknown')
                if 'orca' in p['name'].lower():
                    dex = 'orca'
                elif 'raydium' in p['name'].lower():
                    dex = 'raydium'
                elif 'meteora' in p['name'].lower():
                    dex = 'meteora'
                
                print(f"""
'{p['name'].lower().replace(' ', '_')}': {{
    'address': '{p['pool']}',
    'base_vault': '{p['sol_vault']}',
    'quote_vault': '{p['usdc_vault']}',
    'base_mint': '{SOL_MINT}',
    'quote_mint': '{USDC_MINT}',
    'base_decimals': 9,
    'quote_decimals': 6,
    'dex': '{dex}',
    'fee_bps': 30,
    'pair': 'SOL/USDC'
}},""")
        else:
            print("\n⚠️ Only found 1 active pool. Need 2 for arbitrage.")
            print("Try checking Raydium CLMM or Meteora pools manually.")
        
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
