"""
Real DEX Price Feed Connector
Connects to the Rust price feed service for real-time Solana DEX prices
"""
import aiohttp
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

class RealDEXConnector:
    """Connects to Rust price feed service for real DEX data"""
    
    def __init__(self, rust_service_url: str = "http://localhost:8002"):
        self.rust_service_url = rust_service_url
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def ensure_session(self):
        """Ensure aiohttp session exists"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
    
    async def check_health(self) -> bool:
        """Check if Rust service is running"""
        try:
            await self.ensure_session()
            async with self.session.get(f"{self.rust_service_url}/health", timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    async def get_real_prices(self) -> Dict[str, Dict]:
        """
        Fetch real-time prices from all DEXs via Rust service
        
        Returns:
            Dict mapping DEX name to price data
        """
        try:
            await self.ensure_session()
            async with self.session.get(
                f"{self.rust_service_url}/prices",
                timeout=10
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to fetch prices: {resp.status}")
                    return {}
                
                data = await resp.json()
                
                # Convert to format expected by bot
                prices = {}
                for item in data:
                    dex_name = item['dex']
                    prices[dex_name] = {
                        'dex': dex_name,
                        'token_pair': item['token_pair'],
                        'price': item['price'],
                        'liquidity_usd': item['liquidity'],
                        'timestamp': datetime.fromtimestamp(item['timestamp'], tz=timezone.utc)
                    }
                
                return prices
                
        except asyncio.TimeoutError:
            logger.error("Timeout fetching prices from Rust service")
            return {}
        except Exception as e:
            logger.error(f"Error fetching real prices: {e}")
            return {}
    
    async def get_real_opportunities(self) -> List[Dict]:
        """
        Get arbitrage opportunities calculated by Rust service
        
        Returns:
            List of arbitrage opportunities with real spreads
        """
        try:
            await self.ensure_session()
            async with self.session.get(
                f"{self.rust_service_url}/opportunities",
                timeout=10
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to fetch opportunities: {resp.status}")
                    return []
                
                data = await resp.json()
                
                # Convert to format expected by bot
                opportunities = []
                for item in data:
                    opportunities.append({
                        'token_pair': item['token_pair'],
                        'dex_buy': item['buy_dex'],
                        'dex_sell': item['sell_dex'],
                        'buy_price': item['buy_price'],
                        'sell_price': item['sell_price'],
                        'gross_spread_percentage': item['spread_percentage'],
                        'timestamp': datetime.fromtimestamp(item['timestamp'], tz=timezone.utc)
                    })
                
                return opportunities
                
        except asyncio.TimeoutError:
            logger.error("Timeout fetching opportunities from Rust service")
            return []
        except Exception as e:
            logger.error(f"Error fetching real opportunities: {e}")
            return []
    
    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()


# Example usage
async def test_connection():
    connector = RealDEXConnector()
    
    # Check health
    is_healthy = await connector.check_health()
    print(f"Rust service healthy: {is_healthy}")
    
    if is_healthy:
        # Get prices
        prices = await connector.get_real_prices()
        print(f"\nReal DEX Prices:")
        for dex, data in prices.items():
            print(f"  {dex.upper()}: ${data['price']:.4f}")
        
        # Get opportunities
        opportunities = await connector.get_real_opportunities()
        print(f"\nFound {len(opportunities)} arbitrage opportunities")
        for opp in opportunities:
            print(f"  {opp['dex_buy']} → {opp['dex_sell']}: {opp['gross_spread_percentage']:.2f}%")
    
    await connector.close()


if __name__ == "__main__":
    asyncio.run(test_connection())
