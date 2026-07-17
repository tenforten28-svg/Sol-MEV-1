"""
VAULT EXTRACTOR - Extract Vault Addresses from Pool Accounts
=============================================================
Connects to Solana RPC, fetches pool data, decodes vault addresses
Supports: Raydium V4, Orca Whirlpool, Pump.fun, Meteora DLMM
"""

import base64
import json
import os
from typing import Dict, Optional, List
from dotenv import load_dotenv

from solana.rpc.api import Client
from solders.pubkey import Pubkey

load_dotenv()

# =========================
# CONFIG
# =========================

RPC_ENDPOINT = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Override devnet with mainnet
if 'devnet' in RPC_ENDPOINT.lower():
    RPC_ENDPOINT = 'https://api.mainnet-beta.solana.com'

# Example pool addresses - REPLACE WITH YOUR ACTUAL POOLS
POOLS = {
    # Raydium SOL/USDC AMM V4
    "raydium_sol_usdc": {
        "address": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
        "type": "raydium"
    },
    # Orca SOL/USDC Whirlpool
    "orca_sol_usdc": {
        "address": "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
        "type": "orca"
    },
    # Meteora SOL/USDC DLMM
    "meteora_sol_usdc": {
        "address": "BVRbyLjjfSBcoyiYFuxbgKYnWuiFaF9CSXEa5vdpZ2Hq",
        "type": "meteora"
    },
    # Raydium BONK/SOL
    "raydium_bonk_sol": {
        "address": "Hni4cvLdJmrCT1MkbZZBJZC7RRDdVeTpQ2m3pm9GXnfH",
        "type": "raydium"
    },
    # Add more pools as needed...
}

client = Client(RPC_ENDPOINT)


# =========================
# HELPERS
# =========================

def fetch_account_data(address: str) -> Optional[bytes]:
    """Fetch raw account data from Solana"""
    try:
        response = client.get_account_info(Pubkey.from_string(address))
        if response.value is None:
            print(f"  ❌ Account not found: {address}")
            return None
        
        data = response.value.data
        if isinstance(data, tuple) and len(data) >= 1:
            # Base64 encoded
            return base64.b64decode(data[0])
        elif isinstance(data, bytes):
            return data
        else:
            print(f"  ❌ Unknown data format: {type(data)}")
            return None
    except Exception as e:
        print(f"  ❌ Error fetching account: {e}")
        return None


def extract_pubkey(data: bytes, offset: int) -> str:
    """Extract a 32-byte public key from data at given offset"""
    if len(data) < offset + 32:
        raise ValueError(f"Data too short: {len(data)} bytes, need {offset + 32}")
    return str(Pubkey.from_bytes(data[offset:offset + 32]))


def extract_u64(data: bytes, offset: int) -> int:
    """Extract a u64 from data at given offset"""
    if len(data) < offset + 8:
        raise ValueError(f"Data too short for u64")
    return int.from_bytes(data[offset:offset + 8], 'little')


def extract_u128(data: bytes, offset: int) -> int:
    """Extract a u128 from data at given offset"""
    if len(data) < offset + 16:
        raise ValueError(f"Data too short for u128")
    return int.from_bytes(data[offset:offset + 16], 'little')


# =========================
# RAYDIUM V4 (AMM)
# Account size: 752 bytes
# =========================

RAYDIUM_V4_OFFSETS = {
    "status": 0,           # u64
    "nonce": 8,            # u64
    "max_order": 16,       # u64
    "depth": 24,           # u64
    "base_decimal": 32,    # u64
    "quote_decimal": 40,   # u64
    "state": 48,           # u64
    "reset_flag": 56,      # u64
    "min_size": 64,        # u64
    "vol_max_cut": 72,     # u64
    "amount_wave": 80,     # u64
    "base_lot_size": 88,   # u64
    "quote_lot_size": 96,  # u64
    "min_price_mul": 104,  # u64
    "max_price_mul": 112,  # u64
    "system_decimal": 120, # u64
    "min_separate_num": 128,   # u64
    "min_separate_denom": 136, # u64
    "trade_fee_num": 144,      # u64
    "trade_fee_denom": 152,    # u64
    "pnl_num": 160,            # u64
    "pnl_denom": 168,          # u64
    "swap_fee_num": 176,       # u64
    "swap_fee_denom": 184,     # u64
    "base_need_take_pnl": 192, # u64
    "quote_need_take_pnl": 200,# u64
    "quote_total_pnl": 208,    # u64
    "base_total_pnl": 216,     # u64
    "pool_open_time": 224,     # u64
    "punish_pc_amount": 232,   # u64
    "punish_coin_amount": 240, # u64
    "orderbook_to_init_time": 248, # u64
    "swap_base_in_amount": 256,    # u128
    "swap_quote_out_amount": 272,  # u128
    "swap_base2_quote_fee": 288,   # u64
    "swap_quote_in_amount": 296,   # u128
    "swap_base_out_amount": 312,   # u128
    "swap_quote2_base_fee": 328,   # u64
    # Public keys start here
    "base_vault": 336,         # Pubkey (32 bytes)
    "quote_vault": 368,        # Pubkey
    "base_mint": 400,          # Pubkey
    "quote_mint": 432,         # Pubkey
    "lp_mint": 464,            # Pubkey
    "open_orders": 496,        # Pubkey
    "market_id": 528,          # Pubkey
    "market_program_id": 560,  # Pubkey
    "target_orders": 592,      # Pubkey
    "withdraw_queue": 624,     # Pubkey
    "lp_vault": 656,           # Pubkey
    "amm_owner": 688,          # Pubkey
    "lp_reserve": 720,         # u64
}


def decode_raydium(pool_address: str) -> Optional[Dict]:
    """Decode Raydium V4 AMM pool account"""
    data = fetch_account_data(pool_address)
    if data is None:
        return None
    
    print(f"  📊 Account size: {len(data)} bytes")
    
    if len(data) < 752:
        print(f"  ⚠️ Warning: Data smaller than expected Raydium V4 layout")
    
    try:
        return {
            "base_vault": extract_pubkey(data, 336),
            "quote_vault": extract_pubkey(data, 368),
            "base_mint": extract_pubkey(data, 400),
            "quote_mint": extract_pubkey(data, 432),
            "lp_mint": extract_pubkey(data, 464),
            "open_orders": extract_pubkey(data, 496),
            "market_id": extract_pubkey(data, 528),
            "target_orders": extract_pubkey(data, 592),
            "base_decimal": extract_u64(data, 32),
            "quote_decimal": extract_u64(data, 40),
        }
    except Exception as e:
        print(f"  ❌ Decode error: {e}")
        return None


# =========================
# ORCA WHIRLPOOL (CLMM)
# Account size: 653 bytes
# =========================

ORCA_WHIRLPOOL_OFFSETS = {
    "discriminator": 0,        # 8 bytes
    "whirlpools_config": 8,    # Pubkey
    "whirlpool_bump": 40,      # u8 array [1]
    "tick_spacing": 42,        # u16
    "tick_spacing_seed": 44,   # u8 array [2]
    "fee_rate": 46,            # u16
    "protocol_fee_rate": 48,   # u16
    "liquidity": 50,           # u128
    "sqrt_price": 66,          # u128
    "tick_current_index": 82,  # i32
    "protocol_fee_owed_a": 86, # u64
    "protocol_fee_owed_b": 94, # u64
    "token_mint_a": 102,       # Pubkey
    "token_vault_a": 134,      # Pubkey
    "fee_growth_global_a": 166,# u128
    "token_mint_b": 182,       # Pubkey
    "token_vault_b": 214,      # Pubkey
    "fee_growth_global_b": 246,# u128
    "reward_last_updated": 262,# u64
    # ... rewards follow
}


def decode_orca(pool_address: str) -> Optional[Dict]:
    """Decode Orca Whirlpool account"""
    data = fetch_account_data(pool_address)
    if data is None:
        return None
    
    print(f"  📊 Account size: {len(data)} bytes")
    
    if len(data) < 300:
        print(f"  ⚠️ Warning: Data smaller than expected Orca Whirlpool layout")
    
    try:
        sqrt_price = extract_u128(data, 66)
        
        return {
            "token_vault_a": extract_pubkey(data, 134),
            "token_vault_b": extract_pubkey(data, 214),
            "token_mint_a": extract_pubkey(data, 102),
            "token_mint_b": extract_pubkey(data, 182),
            "sqrt_price": sqrt_price,
            "tick_current": int.from_bytes(data[82:86], 'little', signed=True),
            "liquidity": extract_u128(data, 50),
            "fee_rate": int.from_bytes(data[46:48], 'little'),
        }
    except Exception as e:
        print(f"  ❌ Decode error: {e}")
        return None


# =========================
# PUMP.FUN BONDING CURVE
# =========================

PUMPFUN_OFFSETS = {
    "discriminator": 0,        # 8 bytes
    "virtual_token_reserves": 8,   # u64
    "virtual_sol_reserves": 16,    # u64
    "real_token_reserves": 24,     # u64
    "real_sol_reserves": 32,       # u64
    "token_total_supply": 40,      # u64
    "complete": 48,                # bool
    "padding": 49,                 # 7 bytes
    "token_mint": 56,              # Pubkey
    "bonding_curve": 88,           # Pubkey (this is often the token vault)
}


def decode_pumpfun(pool_address: str) -> Optional[Dict]:
    """Decode Pump.fun bonding curve account"""
    data = fetch_account_data(pool_address)
    if data is None:
        return None
    
    print(f"  📊 Account size: {len(data)} bytes")
    
    try:
        return {
            "token_mint": extract_pubkey(data, 56),
            "virtual_token_reserves": extract_u64(data, 8),
            "virtual_sol_reserves": extract_u64(data, 16),
            "real_token_reserves": extract_u64(data, 24),
            "real_sol_reserves": extract_u64(data, 32),
            "complete": data[48] == 1,
        }
    except Exception as e:
        print(f"  ❌ Decode error: {e}")
        return None


# =========================
# METEORA DLMM (LbPair)
# Account size: ~904 bytes
# =========================

METEORA_DLMM_OFFSETS = {
    "discriminator": 0,        # 8 bytes
    "parameters": 8,           # StaticParameters (various)
    "v_parameters": 40,        # VariableParameters (various)
    "bump_seed": 72,           # u8 array [1]
    "bin_step_seed": 73,       # u8 array [2]
    "pair_type": 75,           # u8
    "active_id": 76,           # i32
    "bin_step": 80,            # u16
    "status": 82,              # u8
    "padding1": 83,            # u8 array [5]
    "token_x_mint": 88,        # Pubkey
    "token_y_mint": 120,       # Pubkey
    "reserve_x": 152,          # Pubkey (token X vault)
    "reserve_y": 184,          # Pubkey (token Y vault)
    "protocol_fee": 216,       # ProtocolFee
    "padding2": 248,           # various
    # ... more fields
}


def decode_meteora(pool_address: str) -> Optional[Dict]:
    """Decode Meteora DLMM LbPair account"""
    data = fetch_account_data(pool_address)
    if data is None:
        return None
    
    print(f"  📊 Account size: {len(data)} bytes")
    
    if len(data) < 250:
        print(f"  ⚠️ Warning: Data smaller than expected Meteora DLMM layout")
    
    try:
        active_id = int.from_bytes(data[76:80], 'little', signed=True)
        bin_step = int.from_bytes(data[80:82], 'little')
        
        return {
            "reserve_x": extract_pubkey(data, 152),
            "reserve_y": extract_pubkey(data, 184),
            "token_x_mint": extract_pubkey(data, 88),
            "token_y_mint": extract_pubkey(data, 120),
            "active_id": active_id,
            "bin_step": bin_step,
        }
    except Exception as e:
        print(f"  ❌ Decode error: {e}")
        return None


# =========================
# GENERIC DECODER
# =========================

def decode_pool(pool_name: str, pool_config: Dict) -> Optional[Dict]:
    """Decode pool based on type"""
    pool_type = pool_config.get("type", "unknown")
    address = pool_config.get("address")
    
    if not address:
        print(f"  ❌ No address for {pool_name}")
        return None
    
    print(f"\n{'='*60}")
    print(f"🔍 Decoding {pool_name} ({pool_type})")
    print(f"   Address: {address}")
    print(f"{'='*60}")
    
    if pool_type == "raydium":
        return decode_raydium(address)
    elif pool_type == "orca":
        return decode_orca(address)
    elif pool_type == "pumpfun":
        return decode_pumpfun(address)
    elif pool_type == "meteora":
        return decode_meteora(address)
    else:
        print(f"  ❌ Unknown pool type: {pool_type}")
        return None


# =========================
# OUTPUT FORMATTERS
# =========================

def generate_config_output(results: Dict[str, Dict]) -> str:
    """Generate config.py compatible output"""
    output = []
    output.append("# Auto-generated vault configuration")
    output.append("EXTRACTED_POOLS = {")
    
    for pool_name, data in results.items():
        if data is None:
            continue
        
        pool_config = POOLS.get(pool_name, {})
        pool_type = pool_config.get("type", "unknown")
        address = pool_config.get("address", "")
        
        output.append(f'    "{pool_name}": {{')
        output.append(f'        "address": "{address}",')
        output.append(f'        "dex": "{pool_type}",')
        
        for key, value in data.items():
            if isinstance(value, str):
                output.append(f'        "{key}": "{value}",')
            else:
                output.append(f'        "{key}": {value},')
        
        output.append('    },')
    
    output.append("}")
    return "\n".join(output)


def generate_vault_subscriptions(results: Dict[str, Dict]) -> str:
    """Generate vault subscription list"""
    output = []
    output.append("# Auto-generated vault subscriptions for WebSocket")
    output.append("VAULT_SUBSCRIPTIONS = {")
    
    for pool_name, data in results.items():
        if data is None:
            continue
        
        pool_config = POOLS.get(pool_name, {})
        pool_type = pool_config.get("type", "unknown")
        
        if pool_type == "raydium":
            output.append(f'    "{pool_name}_base": "{data.get("base_vault", "")}",')
            output.append(f'    "{pool_name}_quote": "{data.get("quote_vault", "")}",')
        elif pool_type == "orca":
            output.append(f'    "{pool_name}_a": "{data.get("token_vault_a", "")}",')
            output.append(f'    "{pool_name}_b": "{data.get("token_vault_b", "")}",')
        elif pool_type == "meteora":
            output.append(f'    "{pool_name}_x": "{data.get("reserve_x", "")}",')
            output.append(f'    "{pool_name}_y": "{data.get("reserve_y", "")}",')
    
    output.append("}")
    return "\n".join(output)


# =========================
# MAIN EXECUTION
# =========================

def main():
    print("="*60)
    print("🚀 VAULT EXTRACTOR - Solana Pool Decoder")
    print("="*60)
    print(f"RPC Endpoint: {RPC_ENDPOINT[:50]}...")
    print(f"Pools to decode: {len(POOLS)}")
    
    results = {}
    
    for pool_name, pool_config in POOLS.items():
        result = decode_pool(pool_name, pool_config)
        results[pool_name] = result
        
        if result:
            print("\n  ✅ Decoded successfully:")
            for key, value in result.items():
                if isinstance(value, str) and len(value) > 20:
                    print(f"     {key}: {value}")
                else:
                    print(f"     {key}: {value}")
    
    # Summary
    print("\n" + "="*60)
    print("📋 SUMMARY")
    print("="*60)
    
    success = sum(1 for r in results.values() if r is not None)
    print(f"Successfully decoded: {success}/{len(POOLS)} pools")
    
    # Generate config output
    print("\n" + "="*60)
    print("📝 CONFIG OUTPUT (copy to config.py)")
    print("="*60)
    print(generate_config_output(results))
    
    # Generate vault subscriptions
    print("\n" + "="*60)
    print("📝 VAULT SUBSCRIPTIONS (copy to config.py)")
    print("="*60)
    print(generate_vault_subscriptions(results))
    
    # Save to file
    with open("extracted_vaults.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n✅ Results saved to extracted_vaults.json")
    
    return results


if __name__ == "__main__":
    main()
