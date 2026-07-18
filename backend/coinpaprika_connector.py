"""
CoinPaprika DEX Connector for Real-Time Solana Token Prices
Uses QuickNode + CoinPaprika API for liquidity pool and price data
"""

import aiohttp
import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class CoinPaprikaConnector:
    """Fetches real-time Solana token prices and liquidity data via CoinPaprika"""
    
    # Common Solana token addresses (devnet/mainnet)
    TOKEN_ADDRESSES = {
        'SOL': 'So11111111111111111111111111111111111111112',  # Wrapped SOL
        'USDC': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
        'RAY': '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',  # Raydium
        'ORCA': 'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE',  # Orca
    }
    
    def __init__(self, quicknode_http_url: str, session: Optional[aiohttp.ClientSession] = None):
        self.quicknode_url = quicknode_http_url
        self.session = session
        self._own_session = session is None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self):
        """Close session if we own it"""
        if self._own_session and self.session:
            await self.session.close()
    
    async def get_token_price(self, token_address: str) -> Optional[Dict]:
        """
        Get token price from CoinPaprika via QuickNode
        
        Returns:
            {
                'price': float,
                'volume_24h': float,
                'price_change_24h': float,
                'last_updated': datetime
            }
        """
        try:
            session = await self._get_session()
            
            # CoinPaprika API endpoint via QuickNode
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "qn_fetchTokenPrice",
                "params": {
                    "tokenAddress": token_address
                }
            }
            
            async with session.post(
                self.quicknode_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status != 200:
                    logger.error(f"CoinPaprika API error: {response.status}")
                    return None
                
                data = await response.json()
                
                if 'result' in data:
                    result = data['result']
                    return {
                        'price': float(result.get('price', 0)),
                        'volume_24h': float(result.get('volume24h', 0)),
                        'price_change_24h': float(result.get('priceChange24h', 0)),
                        'last_updated': datetime.now(timezone.utc)
                    }
                
                return None
                
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching price for {token_address}")
            return None
        except Exception as e:
            logger.error(f"Error fetching token price: {e}")
            return None
    
    async def get_liquidity_pools(self, token_address: str) -> List[Dict]:
        """
        Get all liquidity pools for a token
        
        Returns:
            [
                {
                    'dex': str,
                    'pair': str,
                    'liquidity_usd': float,
                    'volume_24h': float,
                    'price': float
                }
            ]
        """
        try:
            session = await self._get_session()
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "qn_fetchTokenPools",
                "params": {
                    "tokenAddress": token_address
                }
            }
            
            async with session.post(
                self.quicknode_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status != 200:
                    logger.error(f"Error fetching pools: {response.status}")
                    return []
                
                data = await response.json()
                
                if 'result' in data and 'pools' in data['result']:
                    pools = []
                    for pool in data['result']['pools']:
                        pools.append({
                            'dex': pool.get('dex', 'unknown'),
                            'pair': pool.get('pair', ''),
                            'liquidity_usd': float(pool.get('liquidityUsd', 0)),
                            'volume_24h': float(pool.get('volume24h', 0)),
                            'price': float(pool.get('price', 0))
                        })
                    return pools
                
                return []
                
        except Exception as e:
            logger.error(f"Error fetching liquidity pools: {e}")
            return []
    
    async def get_dex_prices(self, token_pair: str) -> Dict[str, float]:
        """
        Get prices from multiple DEXs for a token pair
        
        Args:
            token_pair: e.g., "SOL/USDC"
            
        Returns:
            {
                'raydium': price,
                'orca': price,
                'serum': price
            }
        """
        base, quote = token_pair.split('/')
        
        if base not in self.TOKEN_ADDRESSES or quote not in self.TOKEN_ADDRESSES:
            logger.warning(f"Unknown token in pair: {token_pair}")
            return {}
        
        base_address = self.TOKEN_ADDRESSES[base]
        
        # Get all pools for the base token
        pools = await self.get_liquidity_pools(base_address)
        
        # Filter pools that match our quote currency and group by DEX
        dex_prices = {}
        
        for pool in pools:
            if quote in pool['pair'].upper():
                dex = pool['dex'].lower()
                price = pool['price']
                
                # Take the pool with highest liquidity for each DEX
                if dex not in dex_prices or pool['liquidity_usd'] > dex_prices[dex].get('liquidity', 0):
                    dex_prices[dex] = {
                        'price': price,
                        'liquidity': pool['liquidity_usd'],
                        'volume_24h': pool['volume_24h']
                    }
        
        # Extract just the prices
        result = {}
        for dex, data in dex_prices.items():
            result[dex] = data['price']
        
        return result
    
    async def get_all_prices(self, token_pair: str) -> Dict[str, Dict]:
        """
        Get comprehensive price data from all available DEXs
        
        Returns:
            {
                'raydium': {'price': float, 'liquidity': float, 'timestamp': datetime},
                'orca': {'price': float, 'liquidity': float, 'timestamp': datetime},
                ...
            }
        """
        base, quote = token_pair.split('/')
        
        if base not in self.TOKEN_ADDRESSES or quote not in self.TOKEN_ADDRESSES:
            logger.warning(f"Unknown token in pair: {token_pair}")
            return {}
        
        base_address = self.TOKEN_ADDRESSES[base]
        
        # Get all pools
        pools = await self.get_liquidity_pools(base_address)
        
        # Group by DEX and get best pool for each
        dex_data = {}
        timestamp = datetime.now(timezone.utc)
        
        for pool in pools:
            if quote in pool['pair'].upper():
                dex = pool['dex'].lower()
                
                # Use pool with highest liquidity for each DEX
                if dex not in dex_data or pool['liquidity_usd'] > dex_data[dex]['liquidity']:
                    dex_data[dex] = {
                        'price': pool['price'],
                        'liquidity': pool['liquidity_usd'],
                        'volume_24h': pool['volume_24h'],
                        'timestamp': timestamp
                    }
        
        return dex_data


async def test_connection():
    """Test the CoinPaprika connector"""
    import os
    
    quicknode_url = os.getenv('QUICKNODE_HTTP_URL')
    if not quicknode_url:
        print("❌ QUICKNODE_HTTP_URL not set in environment")
        return
    
    connector = CoinPaprikaConnector(quicknode_url)
    
    print("Testing CoinPaprika Connector...")
    print("=" * 60)
    
    # Test 1: Get SOL price
    print("\n1. Testing SOL price fetch...")
    sol_price = await connector.get_token_price(connector.TOKEN_ADDRESSES['SOL'])
    if sol_price:
        print(f"✅ SOL Price: ${sol_price['price']:.2f}")
        print(f"   24h Volume: ${sol_price['volume_24h']:,.2f}")
        print(f"   24h Change: {sol_price['price_change_24h']:.2f}%")
    else:
        print("❌ Failed to fetch SOL price")
    
    # Test 2: Get SOL/USDC pools
    print("\n2. Testing SOL/USDC liquidity pools...")
    pools = await connector.get_liquidity_pools(connector.TOKEN_ADDRESSES['SOL'])
    if pools:
        print(f"✅ Found {len(pools)} liquidity pools:")
        for pool in pools[:5]:  # Show first 5
            print(f"   - {pool['dex']}: ${pool['price']:.2f} | Liquidity: ${pool['liquidity_usd']:,.0f}")
    else:
        print("❌ No pools found")
    
    # Test 3: Get DEX prices
    print("\n3. Testing multi-DEX price comparison...")
    dex_prices = await connector.get_all_prices('SOL/USDC')
    if dex_prices:
        print(f"✅ Found prices on {len(dex_prices)} DEXs:")
        for dex, data in dex_prices.items():
            print(f"   - {dex.upper()}: ${data['price']:.2f} | Liquidity: ${data['liquidity']:,.0f}")
    else:
        print("❌ No DEX prices found")
    
    await connector.close()
    print("\n" + "=" * 60)
    print("Test complete!")


if __name__ == "__main__":
    asyncio.run(test_connection())
