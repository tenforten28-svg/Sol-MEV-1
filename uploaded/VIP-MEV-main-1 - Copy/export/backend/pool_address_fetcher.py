"""
Dynamic Pool Address Fetcher
Fetches real-time pool addresses from DEXs
"""

import asyncio
import logging
from typing import Dict, Optional, List
import aiohttp
from solders.pubkey import Pubkey
import json

logger = logging.getLogger(__name__)


class PoolAddressFetcher:
    """
    Fetches pool addresses dynamically from DEX APIs
    Caches addresses to reduce API calls
    """
    
    def __init__(self):
        self.cache = {}
        self.cache_duration = 3600  # 1 hour cache
    
    async def fetch_raydium_pools(self) -> Dict:
        """
        Fetch Raydium pool addresses from API
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.raydium.io/v2/main/pools"
                
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Parse pools
                        pools = {}
                        for pool in data.get('data', []):
                            # Create key from token symbols
                            base_symbol = pool.get('baseMint', {}).get('symbol', '')
                            quote_symbol = pool.get('quoteMint', {}).get('symbol', '')
                            
                            if base_symbol and quote_symbol:
                                pair_key = f"{base_symbol}/{quote_symbol}"
                                pools[pair_key] = {
                                    'amm_id': pool.get('id'),
                                    'amm_authority': pool.get('authority'),
                                    'amm_open_orders': pool.get('openOrders'),
                                    'pool_coin_token_account': pool.get('baseVault'),
                                    'pool_pc_token_account': pool.get('quoteVault'),
                                    'serum_program_id': pool.get('marketProgramId'),
                                    'serum_market': pool.get('marketId'),
                                    'base_mint': pool.get('baseMint', {}).get('address'),
                                    'quote_mint': pool.get('quoteMint', {}).get('address'),
                                }
                        
                        logger.info(f"✅ Fetched {len(pools)} Raydium pools")
                        return pools
                    else:
                        logger.error(f"Raydium API error: {response.status}")
                        return {}
                        
        except Exception as e:
            logger.error(f"Error fetching Raydium pools: {e}")
            return {}
    
    async def fetch_orca_whirlpools(self) -> Dict:
        """
        Fetch Orca Whirlpool addresses
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.mainnet.orca.so/v1/whirlpool/list"
                
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        pools = {}
                        for pool in data.get('whirlpools', []):
                            token_a = pool.get('tokenA', {}).get('symbol', '')
                            token_b = pool.get('tokenB', {}).get('symbol', '')
                            
                            if token_a and token_b:
                                pair_key = f"{token_a}/{token_b}"
                                pools[pair_key] = {
                                    'whirlpool_address': pool.get('address'),
                                    'token_vault_a': pool.get('tokenVaultA'),
                                    'token_vault_b': pool.get('tokenVaultB'),
                                    'tick_array': pool.get('tickArrays', []),
                                    'token_a_mint': pool.get('tokenA', {}).get('mint'),
                                    'token_b_mint': pool.get('tokenB', {}).get('mint'),
                                }
                        
                        logger.info(f"✅ Fetched {len(pools)} Orca pools")
                        return pools
                    else:
                        logger.error(f"Orca API error: {response.status}")
                        return {}
                        
        except Exception as e:
            logger.error(f"Error fetching Orca pools: {e}")
            return {}
    
    async def get_pool_address(
        self,
        dex: str,
        token_a: str,
        token_b: str
    ) -> Optional[Dict]:
        """
        Get pool address for a token pair on specific DEX
        
        Args:
            dex: 'raydium' or 'orca'
            token_a: First token symbol
            token_b: Second token symbol
            
        Returns:
            Pool data dict or None
        """
        pair_key = f"{token_a}/{token_b}"
        cache_key = f"{dex}:{pair_key}"
        
        # Check cache
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        # Fetch fresh data
        if dex.lower() == 'raydium':
            pools = await self.fetch_raydium_pools()
        elif dex.lower() == 'orca':
            pools = await self.fetch_orca_whirlpools()
        else:
            logger.error(f"Unknown DEX: {dex}")
            return None
        
        # Get specific pool
        pool = pools.get(pair_key)
        
        # Try reverse pair
        if not pool:
            reverse_key = f"{token_b}/{token_a}"
            pool = pools.get(reverse_key)
        
        # Cache result
        if pool:
            self.cache[cache_key] = pool
        
        return pool
    
    async def get_all_pools(self, dex: str) -> Dict:
        """Get all pools for a DEX"""
        if dex.lower() == 'raydium':
            return await self.fetch_raydium_pools()
        elif dex.lower() == 'orca':
            return await self.fetch_orca_whirlpools()
        else:
            return {}
    
    def clear_cache(self):
        """Clear pool cache"""
        self.cache = {}
        logger.info("Pool cache cleared")


# Fallback static pool addresses (for when APIs are unavailable)
FALLBACK_POOLS = {
    'raydium': {
        'SOL/USDC': {
            'amm_id': '58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2',
            'amm_authority': '5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1',
            'amm_open_orders': 'HRk9CMrpq7Jn9sh7mzxE8CChHG8dneX9p475QKz4Fsfc',
            'pool_coin_token_account': 'DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz',
            'pool_pc_token_account': 'HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz',
            'serum_program_id': '9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin',
            'serum_market': '9wFFyRfZBsuAha4YcuxcXLKwMxJR43S7fPfQLusDBzvT',
        }
    },
    'orca': {
        'SOL/USDC': {
            'whirlpool_address': '7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm',
            'token_vault_a': 'ANP74VNsHwSJ8Bs9eFaVq3NHPJeJzBLEpCrAuHmP5pPj',
            'token_vault_b': '75HgnSvXbWKZBpZHveX68ZzAhDqMzNDS29X6BGLtxMo1',
        }
    }
}


# Testing
async def test_pool_fetcher():
    """Test pool address fetcher"""
    print("🧪 Testing Pool Address Fetcher")
    print("=" * 70)
    
    fetcher = PoolAddressFetcher()
    
    print("\n1. Fetching Raydium pools...")
    raydium_pools = await fetcher.fetch_raydium_pools()
    print(f"   Found {len(raydium_pools)} pools")
    
    if raydium_pools:
        # Show first 3 pools
        for i, (pair, data) in enumerate(list(raydium_pools.items())[:3], 1):
            print(f"   {i}. {pair}: {data.get('amm_id', 'N/A')[:16]}...")
    
    print("\n2. Fetching Orca pools...")
    orca_pools = await fetcher.fetch_orca_whirlpools()
    print(f"   Found {len(orca_pools)} pools")
    
    if orca_pools:
        for i, (pair, data) in enumerate(list(orca_pools.items())[:3], 1):
            print(f"   {i}. {pair}: {data.get('whirlpool_address', 'N/A')[:16]}...")
    
    print("\n3. Getting specific pool...")
    pool = await fetcher.get_pool_address('raydium', 'SOL', 'USDC')
    if pool:
        print(f"   ✅ Found SOL/USDC pool on Raydium")
        print(f"   AMM ID: {pool.get('amm_id', 'N/A')}")
    else:
        print(f"   ❌ Pool not found")
    
    print("\n4. Testing fallback...")
    print(f"   Fallback pools available: {len(FALLBACK_POOLS['raydium'])}")
    
    print("\n" + "=" * 70)
    print("✅ Pool fetcher test complete!")


if __name__ == "__main__":
    asyncio.run(test_pool_fetcher())
