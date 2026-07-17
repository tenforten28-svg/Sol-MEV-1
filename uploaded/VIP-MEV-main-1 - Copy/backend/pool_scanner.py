"""
MULTI-DEX POOL SCANNER
======================
Finds all pools for a token across:
- Raydium (AMM V4, CLMM, CPMM)
- Meteora (DLMM)
- Orca (Whirlpool)

Used to find arbitrage opportunities
"""

import asyncio
import os
import struct
import base64
from typing import Dict, List, Optional
from dataclasses import dataclass
import logging
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
import base58

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger('pool_scanner')

RPC_URL = os.environ.get('SOLANA_RPC_URL')

# Program IDs
PROGRAMS = {
    'raydium_amm': '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8',
    'raydium_clmm': 'CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK',
    'raydium_cpmm': 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C',
    'meteora_dlmm': 'LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo',
    'orca_whirlpool': 'whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc',
}

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@dataclass
class PoolInfo:
    address: str
    dex: str
    program: str
    base_mint: str
    quote_mint: str
    base_vault: Optional[str] = None
    quote_vault: Optional[str] = None
    price: float = 0.0
    liquidity_usd: float = 0.0


async def find_raydium_amm_pools(client: AsyncClient, token_mint: str) -> List[PoolInfo]:
    """Find Raydium AMM V4 pools containing the token"""
    pools = []
    program_id = Pubkey.from_string(PROGRAMS['raydium_amm'])
    token_bytes = base58.b58decode(token_mint)
    
    try:
        # Search for pools with this token as base mint (offset 400)
        filters = [
            {"memcmp": {"offset": 400, "bytes": token_mint}},
            {"dataSize": 752}
        ]
        
        resp = await client.get_program_accounts(
            program_id,
            encoding="base64",
            filters=filters
        )
        
        for account in resp.value:
            pool_address = str(account.pubkey)
            data = base64.b64decode(account.account.data[0])
            
            # Parse pool data
            if len(data) >= 464:
                base_vault = str(Pubkey.from_bytes(data[336:368]))
                quote_vault = str(Pubkey.from_bytes(data[368:400]))
                base_mint = str(Pubkey.from_bytes(data[400:432]))
                quote_mint = str(Pubkey.from_bytes(data[432:464]))
                
                pools.append(PoolInfo(
                    address=pool_address,
                    dex='raydium_amm',
                    program=PROGRAMS['raydium_amm'],
                    base_mint=base_mint,
                    quote_mint=quote_mint,
                    base_vault=base_vault,
                    quote_vault=quote_vault,
                ))
        
        # Also search as quote mint (offset 432)
        filters = [
            {"memcmp": {"offset": 432, "bytes": token_mint}},
            {"dataSize": 752}
        ]
        
        resp = await client.get_program_accounts(
            program_id,
            encoding="base64",
            filters=filters
        )
        
        for account in resp.value:
            pool_address = str(account.pubkey)
            data = base64.b64decode(account.account.data[0])
            
            if len(data) >= 464:
                base_vault = str(Pubkey.from_bytes(data[336:368]))
                quote_vault = str(Pubkey.from_bytes(data[368:400]))
                base_mint = str(Pubkey.from_bytes(data[400:432]))
                quote_mint = str(Pubkey.from_bytes(data[432:464]))
                
                # Avoid duplicates
                if not any(p.address == pool_address for p in pools):
                    pools.append(PoolInfo(
                        address=pool_address,
                        dex='raydium_amm',
                        program=PROGRAMS['raydium_amm'],
                        base_mint=base_mint,
                        quote_mint=quote_mint,
                        base_vault=base_vault,
                        quote_vault=quote_vault,
                    ))
        
        logger.info(f"  Raydium AMM: Found {len(pools)} pools")
        
    except Exception as e:
        logger.error(f"  Raydium AMM error: {e}")
    
    return pools


async def find_raydium_clmm_pools(client: AsyncClient, token_mint: str) -> List[PoolInfo]:
    """Find Raydium CLMM pools containing the token"""
    pools = []
    program_id = Pubkey.from_string(PROGRAMS['raydium_clmm'])
    
    try:
        # CLMM pools have mints at offset 73 and 105
        for offset in [73, 105]:
            filters = [
                {"memcmp": {"offset": offset, "bytes": token_mint}},
            ]
            
            resp = await client.get_program_accounts(
                program_id,
                encoding="base64",
                filters=filters
            )
            
            for account in resp.value:
                pool_address = str(account.pubkey)
                data = base64.b64decode(account.account.data[0])
                
                if len(data) >= 140:
                    mint_0 = str(Pubkey.from_bytes(data[73:105]))
                    mint_1 = str(Pubkey.from_bytes(data[105:137]))
                    
                    # Avoid duplicates
                    if not any(p.address == pool_address for p in pools):
                        pools.append(PoolInfo(
                            address=pool_address,
                            dex='raydium_clmm',
                            program=PROGRAMS['raydium_clmm'],
                            base_mint=mint_0,
                            quote_mint=mint_1,
                        ))
        
        logger.info(f"  Raydium CLMM: Found {len(pools)} pools")
        
    except Exception as e:
        logger.error(f"  Raydium CLMM error: {e}")
    
    return pools


async def find_meteora_pools(client: AsyncClient, token_mint: str) -> List[PoolInfo]:
    """Find Meteora DLMM pools containing the token"""
    pools = []
    program_id = Pubkey.from_string(PROGRAMS['meteora_dlmm'])
    
    try:
        # Meteora DLMM has mints at offset 88 and 120
        for offset in [88, 120]:
            filters = [
                {"memcmp": {"offset": offset, "bytes": token_mint}},
            ]
            
            resp = await client.get_program_accounts(
                program_id,
                encoding="base64",
                filters=filters
            )
            
            for account in resp.value:
                pool_address = str(account.pubkey)
                data = base64.b64decode(account.account.data[0])
                
                if len(data) >= 160:
                    mint_x = str(Pubkey.from_bytes(data[88:120]))
                    mint_y = str(Pubkey.from_bytes(data[120:152]))
                    
                    if not any(p.address == pool_address for p in pools):
                        pools.append(PoolInfo(
                            address=pool_address,
                            dex='meteora_dlmm',
                            program=PROGRAMS['meteora_dlmm'],
                            base_mint=mint_x,
                            quote_mint=mint_y,
                        ))
        
        logger.info(f"  Meteora DLMM: Found {len(pools)} pools")
        
    except Exception as e:
        logger.error(f"  Meteora DLMM error: {e}")
    
    return pools


async def find_orca_pools(client: AsyncClient, token_mint: str) -> List[PoolInfo]:
    """Find Orca Whirlpool pools containing the token"""
    pools = []
    program_id = Pubkey.from_string(PROGRAMS['orca_whirlpool'])
    
    try:
        # Orca has mints at offset 101 and 181
        for offset in [101, 181]:
            filters = [
                {"memcmp": {"offset": offset, "bytes": token_mint}},
            ]
            
            resp = await client.get_program_accounts(
                program_id,
                encoding="base64",
                filters=filters
            )
            
            for account in resp.value:
                pool_address = str(account.pubkey)
                data = base64.b64decode(account.account.data[0])
                
                if len(data) >= 220:
                    mint_a = str(Pubkey.from_bytes(data[101:133]))
                    mint_b = str(Pubkey.from_bytes(data[181:213]))
                    vault_a = str(Pubkey.from_bytes(data[133:165]))
                    vault_b = str(Pubkey.from_bytes(data[213:245]))
                    
                    if not any(p.address == pool_address for p in pools):
                        pools.append(PoolInfo(
                            address=pool_address,
                            dex='orca_whirlpool',
                            program=PROGRAMS['orca_whirlpool'],
                            base_mint=mint_a,
                            quote_mint=mint_b,
                            base_vault=vault_a,
                            quote_vault=vault_b,
                        ))
        
        logger.info(f"  Orca Whirlpool: Found {len(pools)} pools")
        
    except Exception as e:
        logger.error(f"  Orca Whirlpool error: {e}")
    
    return pools


async def find_all_pools(token_mint: str) -> List[PoolInfo]:
    """Find all pools across all DEXes for a token"""
    logger.info(f"\n{'='*60}")
    logger.info(f"Scanning all DEXes for: {token_mint[:20]}...")
    logger.info(f"{'='*60}")
    
    client = AsyncClient(RPC_URL)
    all_pools = []
    
    try:
        # Run all scans in parallel
        results = await asyncio.gather(
            find_raydium_amm_pools(client, token_mint),
            find_raydium_clmm_pools(client, token_mint),
            find_meteora_pools(client, token_mint),
            find_orca_pools(client, token_mint),
            return_exceptions=True
        )
        
        for result in results:
            if isinstance(result, list):
                all_pools.extend(result)
    
    finally:
        await client.close()
    
    logger.info(f"\n✅ Total pools found: {len(all_pools)}")
    
    return all_pools


async def calculate_pool_price(client: AsyncClient, pool: PoolInfo) -> float:
    """Calculate current price from pool reserves"""
    
    if pool.dex == 'raydium_amm' and pool.base_vault and pool.quote_vault:
        # For AMM, price = quote_reserve / base_reserve
        try:
            base_resp = await client.get_account_info(Pubkey.from_string(pool.base_vault))
            quote_resp = await client.get_account_info(Pubkey.from_string(pool.quote_vault))
            
            if base_resp.value and quote_resp.value:
                base_data = base_resp.value.data
                quote_data = quote_resp.value.data
                
                if isinstance(base_data, (list, tuple)):
                    base_data = bytes(base_data)
                if isinstance(quote_data, (list, tuple)):
                    quote_data = bytes(quote_data)
                
                if len(base_data) >= 72 and len(quote_data) >= 72:
                    base_balance = struct.unpack_from("<Q", base_data, 64)[0]
                    quote_balance = struct.unpack_from("<Q", quote_data, 64)[0]
                    
                    if base_balance > 0:
                        # Assume 9 decimals for new tokens, 6 for USDC, 9 for SOL
                        base_dec = 9 if pool.base_mint not in [USDC_MINT] else 6
                        quote_dec = 9 if pool.quote_mint == SOL_MINT else 6
                        
                        price = (quote_balance / 10**quote_dec) / (base_balance / 10**base_dec)
                        return price
        except:
            pass
    
    elif pool.dex == 'orca_whirlpool':
        # For Whirlpool, use tick-based pricing
        try:
            resp = await client.get_account_info(Pubkey.from_string(pool.address))
            if resp.value:
                data = resp.value.data
                if isinstance(data, (list, tuple)):
                    data = bytes(data)
                
                if len(data) >= 85:
                    tick = struct.unpack_from("<i", data, 81)[0]
                    price = 1.0001 ** tick * 1000  # Adjust for decimals
                    return price
        except:
            pass
    
    return 0.0


async def find_arbitrage_for_token(token_mint: str):
    """Find arbitrage opportunities for a specific token"""
    
    pools = await find_all_pools(token_mint)
    
    if len(pools) < 2:
        logger.info("Need at least 2 pools for arbitrage")
        return []
    
    client = AsyncClient(RPC_URL)
    
    try:
        # Get prices for all pools
        logger.info("\nFetching current prices...")
        for pool in pools:
            pool.price = await calculate_pool_price(client, pool)
            if pool.price > 0:
                logger.info(f"  {pool.dex}: ${pool.price:.8f}")
    
    finally:
        await client.close()
    
    # Find opportunities
    opportunities = []
    priced_pools = [p for p in pools if p.price > 0]
    
    for i in range(len(priced_pools)):
        for j in range(i + 1, len(priced_pools)):
            p1 = priced_pools[i]
            p2 = priced_pools[j]
            
            spread_bps = abs(p1.price - p2.price) / min(p1.price, p2.price) * 10000
            
            if spread_bps >= 50:  # 0.5% minimum
                buy = p1 if p1.price < p2.price else p2
                sell = p2 if p1.price < p2.price else p1
                
                logger.info(f"\n⚡ ARBITRAGE OPPORTUNITY!")
                logger.info(f"   Buy on {buy.dex}: ${buy.price:.8f}")
                logger.info(f"   Sell on {sell.dex}: ${sell.price:.8f}")
                logger.info(f"   Spread: {spread_bps:.2f} bps ({spread_bps/100:.2f}%)")
                
                opportunities.append({
                    'buy_pool': buy,
                    'sell_pool': sell,
                    'spread_bps': spread_bps
                })
    
    return opportunities


# ==============================
# TEST WITH KNOWN TOKENS
# ==============================

async def main():
    """Test scanning with some known tokens"""
    
    # Test with SOL/USDC
    logger.info("Testing with SOL...")
    await find_arbitrage_for_token(SOL_MINT)
    
    # Test with a popular meme coin (BONK)
    BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
    logger.info("\nTesting with BONK...")
    await find_arbitrage_for_token(BONK)


if __name__ == "__main__":
    asyncio.run(main())
