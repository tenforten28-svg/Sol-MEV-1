"""
Scan Pool Data for Known Addresses
==================================
Find where SOL and USDC mints are located in pool data
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

# Known addresses to search for
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

SOL_BYTES = base58.b58decode(SOL_MINT)
USDC_BYTES = base58.b58decode(USDC_MINT)

# Pools to scan
POOLS = [
    ("Orca Whirlpool Main", "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"),
    ("Orca Whirlpool 2", "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ"),
    ("Raydium V4 Legacy", "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"),
]


async def scan_pool(client, name, address):
    """Scan pool data for known mints"""
    print(f"\n{'='*60}")
    print(f"Scanning: {name}")
    print(f"Address: {address}")
    print(f"{'='*60}")
    
    try:
        pubkey = Pubkey.from_string(address)
        resp = await client.get_account_info(pubkey)
        
        if not resp.value:
            print("  ❌ Account not found")
            return
        
        data = resp.value.data
        if isinstance(data, (list, tuple)):
            data = bytes(data)
        
        owner = str(resp.value.owner)
        print(f"Owner: {owner}")
        print(f"Data size: {len(data)} bytes")
        
        # Search for SOL mint
        sol_positions = []
        for i in range(len(data) - 32):
            if data[i:i+32] == SOL_BYTES:
                sol_positions.append(i)
        
        # Search for USDC mint
        usdc_positions = []
        for i in range(len(data) - 32):
            if data[i:i+32] == USDC_BYTES:
                usdc_positions.append(i)
        
        print(f"\nSOL mint found at offsets: {sol_positions}")
        print(f"USDC mint found at offsets: {usdc_positions}")
        
        # If we found mints, look for vault addresses nearby
        if sol_positions or usdc_positions:
            print("\n--- Analyzing nearby pubkeys ---")
            
            # For each found mint, check the next 32 bytes (likely vault)
            all_positions = [(p, "SOL") for p in sol_positions] + [(p, "USDC") for p in usdc_positions]
            all_positions.sort()
            
            for pos, mint_type in all_positions:
                print(f"\n  {mint_type} mint at offset {pos}")
                
                # Check pubkey right after (likely vault)
                if pos + 64 <= len(data):
                    next_pubkey = Pubkey.from_bytes(data[pos+32:pos+64])
                    print(f"    Next pubkey (offset {pos+32}): {next_pubkey}")
                    
                    # Try to fetch as token account
                    try:
                        vault_resp = await client.get_account_info(next_pubkey)
                        if vault_resp.value:
                            vault_data = vault_resp.value.data
                            if isinstance(vault_data, (list, tuple)):
                                vault_data = bytes(vault_data)
                            if len(vault_data) >= 72:
                                balance = struct.unpack_from("<Q", vault_data, 64)[0]
                                if mint_type == "SOL":
                                    print(f"    Balance: {balance / 1e9:.4f} SOL")
                                else:
                                    print(f"    Balance: {balance / 1e6:.2f} USDC")
                    except Exception as e:
                        print(f"    (Could not fetch: {e})")
        
        # Also try to find any pubkeys that look like token accounts
        print("\n--- Scanning all 32-byte segments for token accounts ---")
        found_vaults = []
        
        for i in range(0, len(data) - 32, 32):
            try:
                maybe_pubkey = Pubkey.from_bytes(data[i:i+32])
                pubkey_str = str(maybe_pubkey)
                
                # Skip obvious non-addresses
                if pubkey_str.startswith("1111111111"):
                    continue
                
                # Try to fetch as token account
                vault_resp = await client.get_account_info(maybe_pubkey)
                if vault_resp.value:
                    vault_data = vault_resp.value.data
                    if isinstance(vault_data, (list, tuple)):
                        vault_data = bytes(vault_data)
                    
                    # Check if it's a token account (165 bytes for SPL Token)
                    if len(vault_data) == 165:
                        balance = struct.unpack_from("<Q", vault_data, 64)[0]
                        mint = Pubkey.from_bytes(vault_data[0:32])
                        
                        mint_str = str(mint)
                        if mint_str == SOL_MINT or mint_str == USDC_MINT:
                            token_type = "SOL" if mint_str == SOL_MINT else "USDC"
                            human_bal = balance / 1e9 if token_type == "SOL" else balance / 1e6
                            
                            found_vaults.append({
                                'offset': i,
                                'address': pubkey_str,
                                'token': token_type,
                                'balance': human_bal
                            })
                            print(f"  ✅ Found {token_type} vault at offset {i}: {pubkey_str[:20]}... bal={human_bal:,.2f}")
            except:
                pass
        
        if found_vaults:
            print(f"\n--- VAULT SUMMARY ---")
            sol_vaults = [v for v in found_vaults if v['token'] == 'SOL']
            usdc_vaults = [v for v in found_vaults if v['token'] == 'USDC']
            
            if sol_vaults and usdc_vaults:
                sol_v = sol_vaults[0]
                usdc_v = usdc_vaults[0]
                price = usdc_v['balance'] / sol_v['balance'] if sol_v['balance'] > 0 else 0
                
                print(f"  SOL Vault: {sol_v['address']}")
                print(f"  USDC Vault: {usdc_v['address']}")
                print(f"  Price: ${price:.2f} per SOL")
                
                return {
                    'name': name,
                    'pool': address,
                    'sol_vault': sol_v['address'],
                    'usdc_vault': usdc_v['address'],
                    'price': price
                }
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    return None


async def main():
    print("="*60)
    print("POOL DATA SCANNER")
    print("="*60)
    print(f"Looking for SOL mint: {SOL_MINT[:20]}...")
    print(f"Looking for USDC mint: {USDC_MINT[:20]}...")
    
    client = AsyncClient(RPC_URL)
    
    try:
        results = []
        for name, address in POOLS:
            result = await scan_pool(client, name, address)
            if result:
                results.append(result)
        
        if results:
            print("\n" + "="*60)
            print("FINAL RESULTS")
            print("="*60)
            for r in results:
                print(f"\n{r['name']}: ${r['price']:.2f}/SOL")
                print(f"  Pool: {r['pool']}")
                print(f"  SOL Vault: {r['sol_vault']}")
                print(f"  USDC Vault: {r['usdc_vault']}")
    
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
