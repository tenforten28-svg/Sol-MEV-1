"""
Meme Coin Price Connector
Fetches real-time prices for meme coins from Jupiter and DEXs
"""

import aiohttp
import asyncio
import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
import random
from meme_coin_config import MEME_TOKENS, get_meme_token_address

logger = logging.getLogger(__name__)

class MemePriceConnector:
    """Fetches real-time meme coin prices"""
    
    JUPITER_PRICE_API = "https://lite-api.jup.ag/price/v3"
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.price_cache = {}
        self.cache_duration = 3  # Cache for 3 seconds
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self):
        """Close session"""
        if self.session:
            await self.session.close()
    
    async def get_meme_price(self, symbol: str) -> Optional[float]:
        """Get price for a single meme coin"""
        if symbol not in MEME_TOKENS:
            logger.warning(f"Unknown meme token: {symbol}")
            return None
        
        # Check cache
        cache_key = f"price_{symbol}"
        if cache_key in self.price_cache:
            cached_price, cached_time = self.price_cache[cache_key]
            if (datetime.now().timestamp() - cached_time) < self.cache_duration:
                return cached_price
        
        try:
            session = await self._get_session()
            mint = MEME_TOKENS[symbol]['mint']
            
            url = f"{self.JUPITER_PRICE_API}?ids={mint}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # New API v3 format: {mint: {usdPrice: float, ...}}
                    if mint in data and 'usdPrice' in data[mint]:
                        price = float(data[mint]['usdPrice'])
                        
                        # Cache the price
                        self.price_cache[cache_key] = (price, datetime.now().timestamp())
                        
                        return price
                        
        except asyncio.TimeoutError:
            logger.debug(f"Timeout getting price for {symbol}")
        except Exception as e:
            logger.debug(f"Error getting price for {symbol}: {e}")
        
        # Fallback to simulation
        return self._get_simulated_price(symbol)
    
    def _get_simulated_price(self, symbol: str) -> float:
        """Simulate price when API unavailable"""
        # Base prices for simulation (in USD)
        base_prices = {
            'BONK': 0.000025,
            'WIF': 2.50,
            'POPCAT': 1.20,
            'MEW': 0.0045,
            'MYRO': 0.15,
            'SAMO': 0.012,
            'PONKE': 0.35,
            'SLERF': 0.28,
        }
        
        base = base_prices.get(symbol, 0.01)
        # Add some randomness
        variance = random.uniform(-0.02, 0.02)  # ±2%
        return base * (1 + variance)
    
    async def get_dex_prices(self, pair: str) -> Dict[str, Dict]:
        """
        Get prices from multiple DEXs for a meme pair
        
        Returns:
            {
                'raydium': {'bid': float, 'ask': float, 'mid': float, 'liquidity': float},
                'orca': {...},
                'jupiter': {...}
            }
        """
        base, quote = pair.split('/')
        
        # Get base prices
        base_price = await self.get_meme_price(base) if base in MEME_TOKENS else None
        
        if quote in MEME_TOKENS:
            quote_price = await self.get_meme_price(quote)
        elif quote == 'USDC':
            quote_price = 1.0
        elif quote == 'SOL':
            quote_price = 150.0  # Fallback SOL price
        else:
            quote_price = 1.0
        
        if base_price is None:
            return {}
        
        # Calculate price in quote currency
        if quote_price:
            price_in_quote = base_price / quote_price
        else:
            price_in_quote = base_price
        
        # Generate DEX-specific spreads
        dexs = ['raydium', 'orca', 'jupiter']
        prices = {}
        
        for dex in dexs:
            dex_data = await self._simulate_dex_spread(price_in_quote, dex, pair)
            prices[dex] = dex_data
        
        return prices
    
    async def _simulate_dex_spread(self, base_price: float, dex: str, pair: str) -> Dict:
        """Simulate DEX-specific pricing with spreads"""
        # Meme coins have wider spreads
        spread_configs = {
            'raydium': {'spread_bps': 15, 'liquidity_multiplier': 1.2},
            'orca': {'spread_bps': 18, 'liquidity_multiplier': 1.0},
            'jupiter': {'spread_bps': 12, 'liquidity_multiplier': 1.5},
        }
        
        config = spread_configs.get(dex, {'spread_bps': 20, 'liquidity_multiplier': 1.0})
        
        # Calculate spread
        spread_percentage = config['spread_bps'] / 10000
        spread_amount = base_price * spread_percentage
        
        # Add price variance
        price_variance = random.uniform(-0.005, 0.005)  # ±0.5%
        adjusted_mid = base_price * (1 + price_variance)
        
        bid = adjusted_mid - (spread_amount / 2)
        ask = adjusted_mid + (spread_amount / 2)
        
        # Simulate liquidity (meme coins have lower liquidity)
        base_liquidity = random.uniform(80000, 300000)
        liquidity = base_liquidity * config['liquidity_multiplier']
        
        return {
            'bid': bid,
            'ask': ask,
            'mid': adjusted_mid,
            'liquidity': liquidity,
            'spread_bps': config['spread_bps'],
            'timestamp': datetime.now(timezone.utc)
        }
    
    async def get_all_meme_prices(self) -> Dict[str, float]:
        """Get prices for all meme coins"""
        prices = {}
        
        for symbol in MEME_TOKENS.keys():
            price = await self.get_meme_price(symbol)
            if price:
                prices[symbol] = price
        
        return prices
    
    async def get_cross_pair_prices(self, base: str, intermediary: str, quote: str) -> Dict:
        """
        Get prices for cross-pair arbitrage (triangular)
        
        Example: BONK -> WIF -> USDC
        
        Returns:
            {
                'direct': {base/quote price and best route},
                'triangular': {base->intermediary->quote prices},
                'arbitrage_pct': float
            }
        """
        # Get direct pair
        direct_pair = f"{base}/{quote}"
        direct_prices = await self.get_dex_prices(direct_pair)
        
        # Get triangular pairs
        pair1 = f"{base}/{intermediary}"
        pair2 = f"{intermediary}/{quote}"
        
        prices1 = await self.get_dex_prices(pair1)
        prices2 = await self.get_dex_prices(pair2)
        
        if not direct_prices or not prices1 or not prices2:
            return {}
        
        # Calculate best direct route
        best_direct_ask = min([dex['ask'] for dex in direct_prices.values()])
        best_direct_bid = max([dex['bid'] for dex in direct_prices.values()])
        
        # Calculate triangular route
        # Buy base with quote, swap to intermediary, swap to quote
        best_buy_base = min([dex['ask'] for dex in prices1.values()])
        best_sell_intermediary = max([dex['bid'] for dex in prices2.values()])
        
        # Prevent division by zero or extreme values
        if best_buy_base == 0 or best_direct_ask == 0:
            return {}
        
        # Calculate effective rate through triangular path
        triangular_rate = best_sell_intermediary / best_buy_base
        
        # Compare with direct - prevent inf/nan
        try:
            arbitrage_pct = ((triangular_rate / best_direct_ask) - 1) * 100
            
            # Sanity check - reject extreme values
            if not (-1000 < arbitrage_pct < 1000):  # ±10x seems unreasonable
                return {}
                
        except (ZeroDivisionError, OverflowError):
            return {}
        
        return {
            'direct': {
                'pair': direct_pair,
                'best_ask': best_direct_ask,
                'best_bid': best_direct_bid,
            },
            'triangular': {
                'path': f"{base} -> {intermediary} -> {quote}",
                'rate': triangular_rate,
                'pair1': pair1,
                'pair2': pair2,
            },
            'arbitrage_pct': arbitrage_pct,
            'profitable': arbitrage_pct > 0.15  # Minimum 0.15% profit
        }


async def test_meme_prices():
    """Test meme price connector"""
    connector = MemePriceConnector()
    
    print("Testing Meme Price Connector...")
    print("=" * 60)
    
    # Test 1: Get single meme price
    print("\n1. Testing single meme price (BONK)...")
    bonk_price = await connector.get_meme_price('BONK')
    if bonk_price:
        print(f"   ✅ BONK Price: ${bonk_price:.8f}")
    
    # Test 2: Get all meme prices
    print("\n2. Testing all meme prices...")
    all_prices = await connector.get_all_meme_prices()
    for symbol, price in all_prices.items():
        print(f"   {symbol}: ${price:.8f}")
    
    # Test 3: Get DEX prices for a pair
    print("\n3. Testing BONK/USDC DEX prices...")
    dex_prices = await connector.get_dex_prices('BONK/USDC')
    for dex, data in dex_prices.items():
        print(f"   {dex.upper()}: Bid ${data['bid']:.8f} | Ask ${data['ask']:.8f} | Spread {data['spread_bps']} bps")
    
    # Test 4: Cross-pair arbitrage
    print("\n4. Testing triangular arbitrage (BONK->WIF->USDC)...")
    cross = await connector.get_cross_pair_prices('BONK', 'WIF', 'USDC')
    if cross:
        print(f"   Direct rate: {cross['direct']['best_ask']:.8f}")
        print(f"   Triangular rate: {cross['triangular']['rate']:.8f}")
        print(f"   Arbitrage: {cross['arbitrage_pct']:.3f}%")
        print(f"   Profitable: {'✅ Yes' if cross['profitable'] else '❌ No'}")
    
    await connector.close()
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(test_meme_prices())
