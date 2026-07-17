"""
Fetch Real Pool Data from Solana Mainnet
=========================================
This script fetches the actual vault addresses and current prices
from Raydium and Orca pools on mainnet.
"""

import asyncio
import os
import struct
import base64
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

load_dotenv()

RPC_URL = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Raydium AMM Pool ID for SOL/USDC (the most liquid one)
RAYDIUM_SOL_USDC_POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"

# Orca Whirlpool for SOL/USDC
ORCA_SOL_USDC_WHIRLPOOL = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"

async def fetch_raydium_pool_info():
    """Fetch Raydium AMM pool state to get vault addresses"""
    print("\n" + "="*60)
    print("FETCHING RAYDIUM SOL/USDC POOL DATA")
    print("="*60)
    
    client = AsyncClient(RPC_URL)
    
    try:
        pool_pubkey = Pubkey.from_string(RAYDIUM_SOL_USDC_POOL)
        resp = await client.get_account_info(pool_pubkey)
        
        if resp.value is None:
            print("❌ Could not fetch Raydium pool data")
            return None
        
        data = resp.value.data
        if isinstance(data, str):
            data = base64.b64decode(data)
        elif hasattr(data, '__iter__') and not isinstance(data, bytes):
            data = bytes(data)
        
        print(f"Pool data length: {len(data)} bytes")
        
        # Raydium AMM V4 layout (approximate offsets)
        # The pool state contains vault addresses at specific offsets
        # Layout reference: https://github.com/raydium-io/raydium-amm
        
        # Try to parse key fields
        # Note: These offsets are for Raydium AMM V4
        if len(data) >= 752:
            # Common fields at known offsets
            status = struct.unpack_from("<Q", data, 0)[0]
            nonce = struct.unpack_from("<Q", data, 8)[0]
            
            # Token vaults are typically at offsets around 80-144 in AMM state
            # Let's find pubkeys (32 bytes each)
            
            # Based on Raydium AMM layout:
            # offset 80: base_vault
            # offset 112: quote_vault
            
            base_vault = Pubkey.from_bytes(data[80:112])
            quote_vault = Pubkey.from_bytes(data[112:144])
            
            # Also try alternate offsets used in some pools
            lp_mint = Pubkey.from_bytes(data[144:176])
            base_mint = Pubkey.from_bytes(data[176:208])
            quote_mint = Pubkey.from_bytes(data[208:240])
            
            print(f"\nParsed Raydium Pool State:")
            print(f"  Status: {status}")
            print(f"  Base Vault:  {base_vault}")
            print(f"  Quote Vault: {quote_vault}")
            print(f"  LP Mint:     {lp_mint}")
            print(f"  Base Mint:   {base_mint}")
            print(f"  Quote Mint:  {quote_mint}")
            
            # Verify base/quote mints
            expected_sol = "So11111111111111111111111111111111111111112"
            expected_usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            
            if str(base_mint) == expected_sol:
                print("  ✓ Base = SOL (correct)")
            if str(quote_mint) == expected_usdc:
                print("  ✓ Quote = USDC (correct)")
            
            return {
                'base_vault': str(base_vault),
                'quote_vault': str(quote_vault),
                'base_mint': str(base_mint),
                'quote_mint': str(quote_mint),
            }
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()
    
    return None


async def fetch_orca_whirlpool_info():
    """Fetch Orca Whirlpool state to get vault addresses"""
    print("\n" + "="*60)
    print("FETCHING ORCA SOL/USDC WHIRLPOOL DATA")
    print("="*60)
    
    client = AsyncClient(RPC_URL)
    
    try:
        pool_pubkey = Pubkey.from_string(ORCA_SOL_USDC_WHIRLPOOL)
        resp = await client.get_account_info(pool_pubkey)
        
        if resp.value is None:
            print("❌ Could not fetch Orca Whirlpool data")
            return None
        
        data = resp.value.data
        if isinstance(data, str):
            data = base64.b64decode(data)
        elif hasattr(data, '__iter__') and not isinstance(data, bytes):
            data = bytes(data)
        
        print(f"Pool data length: {len(data)} bytes")
        
        # Whirlpool account layout (from orca_whirlpools SDK):
        # https://github.com/orca-so/whirlpools/blob/main/programs/whirlpool/src/state/whirlpool.rs
        #
        # pub struct Whirlpool {
        #     pub whirlpools_config: Pubkey,        // 0
        #     pub whirlpool_bump: [u8; 1],          // 32
        #     pub tick_spacing: u16,                 // 33
        #     pub tick_spacing_seed: [u8; 2],       // 35
        #     pub fee_rate: u16,                     // 37
        #     pub protocol_fee_rate: u16,           // 39
        #     pub liquidity: u128,                   // 41
        #     pub sqrt_price: u128,                  // 57
        #     pub tick_current_index: i32,          // 73
        #     pub protocol_fee_owed_a: u64,         // 77
        #     pub protocol_fee_owed_b: u64,         // 85
        #     pub token_mint_a: Pubkey,             // 93
        #     pub token_vault_a: Pubkey,            // 125
        #     pub fee_growth_global_a: u128,        // 157
        #     pub token_mint_b: Pubkey,             // 173
        #     pub token_vault_b: Pubkey,            // 205
        #     pub fee_growth_global_b: u128,        // 237
        #     pub reward_last_updated_timestamp: u64, // 253
        #     ...
        # }
        
        if len(data) >= 240:
            # Parse Whirlpool state
            whirlpools_config = Pubkey.from_bytes(data[0:32])
            tick_spacing = struct.unpack_from("<H", data, 33)[0]
            fee_rate = struct.unpack_from("<H", data, 37)[0]
            liquidity = struct.unpack_from("<QQ", data, 41)  # u128 as 2x u64
            sqrt_price = struct.unpack_from("<QQ", data, 57)  # u128 as 2x u64
            tick_current = struct.unpack_from("<i", data, 73)[0]
            
            token_mint_a = Pubkey.from_bytes(data[93:125])
            token_vault_a = Pubkey.from_bytes(data[125:157])
            token_mint_b = Pubkey.from_bytes(data[173:205])
            token_vault_b = Pubkey.from_bytes(data[205:237])
            
            # Calculate price from sqrt_price
            # sqrt_price is Q64.64 fixed point
            sqrt_price_x64 = (sqrt_price[1] << 64) | sqrt_price[0]
            price = (sqrt_price_x64 / (2**64)) ** 2
            
            print(f"\nParsed Orca Whirlpool State:")
            print(f"  Config:      {whirlpools_config}")
            print(f"  Tick Spacing: {tick_spacing}")
            print(f"  Fee Rate:    {fee_rate} (bps: {fee_rate/100:.2f})")
            print(f"  Current Tick: {tick_current}")
            print(f"  Token Mint A: {token_mint_a}")
            print(f"  Token Vault A: {token_vault_a}")
            print(f"  Token Mint B: {token_mint_b}")
            print(f"  Token Vault B: {token_vault_b}")
            print(f"  Price (raw): {price:.6f}")
            
            # For SOL/USDC, price should be in range 100-300
            # USDC has 6 decimals, SOL has 9
            adjusted_price = price * (10**6) / (10**9)  # Adjust for decimals
            print(f"  Price (adjusted): ${1/adjusted_price:.2f} per SOL")
            
            expected_sol = "So11111111111111111111111111111111111111112"
            expected_usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            
            if str(token_mint_a) == expected_sol:
                print("  ✓ Mint A = SOL")
            if str(token_mint_b) == expected_usdc:
                print("  ✓ Mint B = USDC")
            
            return {
                'token_vault_a': str(token_vault_a),
                'token_vault_b': str(token_vault_b),
                'token_mint_a': str(token_mint_a),
                'token_mint_b': str(token_mint_b),
            }
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()
    
    return None


async def fetch_token_balance(client, vault_address):
    """Fetch token balance from a vault"""
    try:
        pubkey = Pubkey.from_string(vault_address)
        resp = await client.get_account_info(pubkey)
        
        if resp.value is None:
            return 0
        
        data = resp.value.data
        if isinstance(data, str):
            data = base64.b64decode(data)
        elif hasattr(data, '__iter__') and not isinstance(data, bytes):
            data = bytes(data)
        
        if len(data) >= 72:
            amount = struct.unpack_from("<Q", data, 64)[0]
            return amount
    except:
        pass
    return 0


async def verify_vaults_and_prices():
    """Fetch and verify vault balances, calculate prices"""
    print("\n" + "="*60)
    print("VERIFYING VAULT BALANCES AND PRICES")
    print("="*60)
    
    raydium = await fetch_raydium_pool_info()
    orca = await fetch_orca_whirlpool_info()
    
    client = AsyncClient(RPC_URL)
    
    try:
        if raydium:
            print("\n--- Raydium Vault Balances ---")
            base_bal = await fetch_token_balance(client, raydium['base_vault'])
            quote_bal = await fetch_token_balance(client, raydium['quote_vault'])
            print(f"  Base (SOL):  {base_bal / 1e9:.4f} SOL")
            print(f"  Quote (USDC): {quote_bal / 1e6:.2f} USDC")
            if base_bal > 0:
                price = (quote_bal / 1e6) / (base_bal / 1e9)
                print(f"  Price: ${price:.4f} per SOL")
        
        if orca:
            print("\n--- Orca Vault Balances ---")
            vault_a_bal = await fetch_token_balance(client, orca['token_vault_a'])
            vault_b_bal = await fetch_token_balance(client, orca['token_vault_b'])
            print(f"  Vault A (SOL):  {vault_a_bal / 1e9:.4f} SOL")
            print(f"  Vault B (USDC): {vault_b_bal / 1e6:.2f} USDC")
            if vault_a_bal > 0:
                price = (vault_b_bal / 1e6) / (vault_a_bal / 1e9)
                print(f"  Price: ${price:.4f} per SOL")
        
        # Output config for bot
        print("\n" + "="*60)
        print("RECOMMENDED CONFIG FOR YOUR BOT")
        print("="*60)
        
        if raydium:
            print(f"""
# Raydium SOL/USDC Pool
RAYDIUM_SOL_USDC = {{
    "address": "{RAYDIUM_SOL_USDC_POOL}",
    "base_vault": "{raydium['base_vault']}",
    "quote_vault": "{raydium['quote_vault']}",
    "base_mint": "{raydium['base_mint']}",
    "quote_mint": "{raydium['quote_mint']}",
    "base_decimals": 9,
    "quote_decimals": 6,
    "dex": "raydium",
    "fee_bps": 25,
}}
""")
        
        if orca:
            print(f"""
# Orca Whirlpool SOL/USDC Pool
ORCA_SOL_USDC = {{
    "address": "{ORCA_SOL_USDC_WHIRLPOOL}",
    "base_vault": "{orca['token_vault_a']}",
    "quote_vault": "{orca['token_vault_b']}",
    "base_mint": "{orca['token_mint_a']}",
    "quote_mint": "{orca['token_mint_b']}",
    "base_decimals": 9,
    "quote_decimals": 6,
    "dex": "orca",
    "fee_bps": 30,
}}
""")
    
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(verify_vaults_and_prices())
