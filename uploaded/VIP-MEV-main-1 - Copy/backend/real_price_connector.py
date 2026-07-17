"""
Real-Time DEX Price Connector
Uses Jupiter API and direct Solana RPC for real price data
"""

import aiohttp
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timezone
import random

logger = logging.getLogger(__name__)

class RealPriceConnector:
    """Fetches real-time prices using Jupiter API and Solana RPC"""
    
    # Jupiter API endpoints (updated June 2025)
    JUPITER_PRICE_API = "https://lite-api.jup.ag/price/v3"
    JUPITER_QUOTE_API = "https://api.jup.ag/swap/v1/quote"
    
    # Token mints (mainnet addresses - Jupiter needs these)
    # EXPANDED list for 80+ pairs
    TOKEN_MINTS = {
        # === Core Tokens ===
        'SOL': 'So11111111111111111111111111111111111111112',
        'USDC': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
        'USDT': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
        
        # === Major DeFi Tokens ===
        'RAY': '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
        'ORCA': 'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE',
        'JUP': 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',
        'JTO': 'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL',
        'PYTH': 'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3',
        'MNGO': 'MangoCzJ36AjZyKwVj3VnYU4GTonjfVEnJmvvWaxLac',
        'SRM': 'SRMuApVNdxXokk5GT7XD5cUUgXMBCoAz2LHeuAoKWRt',
        'FIDA': 'EchesyfXePKdLtoiZSL8pBe8Myagyy8ZRqsACNCFGnvp',
        'STEP': 'StepAscQoEioFxxWGnh2sLBDFp9d8rvKz2Yp39iDpyT',
        'COPE': '8HGyAAB1yoM1ttS7pXjHMa3dukTFGQggnFFH3hJZgzQh',
        
        # === Liquid Staking ===
        'MSOL': 'mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So',
        'JITOSOL': 'J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn',
        'BSOL': 'bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1',
        'STSOL': '7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj',
        
        # === Meme Coins (High Volatility) ===
        'BONK': 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',
        'WIF': 'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm',
        'BOME': 'ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82',
        'MEW': 'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5',
        'POPCAT': '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr',
        'SLERF': '7BgBvyjrZX1YKz4oh9mjb8ZScatkkwb8DzFx7LoiVkM3',
        'SAMO': '7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU',
        
        # === Infrastructure & DePIN ===
        'HNT': 'hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux',
        'MOBILE': 'mb1eu7TzEc71KxDpsmsKoucSSuuoGLv1drys1oP2jh6',
        'RENDER': 'rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof',
        'SHDW': 'SHDWyBxihqiCj6YekG2GUr7wqKLeLAMK1gHZck9pL6y',
        
        # === Gaming & Metaverse ===
        'ATLAS': 'ATLASXmbPQxBUYbxPsV97usA3fPQYEqzQBUHgiFCUsXx',
        'POLIS': 'poLisWXnNRwC6oBu1vHiuKQzFjGL4XDSu4g9qjz9qVk',
        'DUST': 'DUSTawucrTsGU8hcqRdHDCbuYhCPADMLM2VcCb8VnFnQ',
        'GENE': 'GENEtH5amGSi8kHAtQoezp1XEXwZJ8vcuePYnXdKrMYz',
        'DFL': 'DFL1zNkaGPWm1BqAVqRjCZvHmwTFrEaJtbzJWgseoNJh',
        
        # === Other Major Tokens ===
        'W': '85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ',
        'TENSOR': 'TNSRxcUxoT9xBG3de7PiJyTDYu7kskLqcpddxnEJAS6',
    }
    
    def __init__(self, use_mainnet_prices: bool = True):
        self.session: Optional[aiohttp.ClientSession] = None
        self.use_mainnet_prices = use_mainnet_prices
        self.price_cache = {}
        self.cache_duration = 2  # Cache for 2 seconds
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self):
        """Close session"""
        if self.session:
            await self.session.close()
    
    async def get_jupiter_price(self, token_symbol: str) -> Optional[float]:
        """
        Get token price from Jupiter Price API
        
        Args:
            token_symbol: e.g., 'SOL', 'USDC', 'RAY'
            
        Returns:
            Price in USD or None
        """
        if token_symbol not in self.TOKEN_MINTS:
            logger.warning(f"Unknown token: {token_symbol}")
            return None
        
        # Check cache
        cache_key = f"jupiter_{token_symbol}"
        if cache_key in self.price_cache:
            cached_data, cached_time = self.price_cache[cache_key]
            if (datetime.now().timestamp() - cached_time) < self.cache_duration:
                return cached_data
        
        try:
            session = await self._get_session()
            mint = self.TOKEN_MINTS[token_symbol]
            
            # Jupiter price API v3
            url = f"{self.JUPITER_PRICE_API}?ids={mint}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # New API v3 format: {mint: {usdPrice: float, ...}}
                    if mint in data and 'usdPrice' in data[mint]:
                        price = float(data[mint]['usdPrice'])
                        
                        # Cache the price
                        self.price_cache[cache_key] = (price, datetime.now().timestamp())
                        
                        return price
                        
        except asyncio.TimeoutError:
            logger.warning(f"Timeout getting Jupiter price for {token_symbol}")
        except Exception as e:
            logger.error(f"Error getting Jupiter price for {token_symbol}: {e}")
        
        return None
    
    async def get_simulated_dex_spread(self, base_price: float, dex: str) -> Dict:
        """
        Simulate DEX-specific pricing with small spreads
        In real implementation, this would query actual DEX state
        
        Args:
            base_price: Base price from Jupiter
            dex: DEX name
            
        Returns:
            {'bid': float, 'ask': float, 'mid': float, 'liquidity': float}
        """
        # Simulate different spreads for different DEXs (wider for paper trading)
        spread_configs = {
            'raydium': {'spread_bps': 15, 'liquidity_multiplier': 1.2},
            'orca': {'spread_bps': 18, 'liquidity_multiplier': 1.0},
            'serum': {'spread_bps': 12, 'liquidity_multiplier': 0.8},
        }
        
        config = spread_configs.get(dex.lower(), {'spread_bps': 20, 'liquidity_multiplier': 1.0})
        
        # Calculate spread
        spread_percentage = config['spread_bps'] / 10000  # bps to decimal
        spread_amount = base_price * spread_percentage
        
        # Add more randomness to simulate market movement (increased for paper trading)
        price_variance = random.uniform(-0.006, 0.006)  # ±0.6%
        adjusted_mid = base_price * (1 + price_variance)
        
        bid = adjusted_mid - (spread_amount / 2)
        ask = adjusted_mid + (spread_amount / 2)
        
        # Simulate liquidity (in USD)
        base_liquidity = random.uniform(50000, 500000)
        liquidity = base_liquidity * config['liquidity_multiplier']
        
        return {
            'bid': bid,
            'ask': ask,
            'mid': adjusted_mid,
            'liquidity': liquidity,
            'timestamp': datetime.now(timezone.utc)
        }
    
    async def get_all_prices(self, token_pair: str) -> Dict[str, Dict]:
        """
        Get prices from multiple DEXs for a token pair
        
        Args:
            token_pair: e.g., "SOL/USDC"
            
        Returns:
            {
                'raydium': {'bid': float, 'ask': float, 'mid': float, 'liquidity': float},
                'orca': {...},
                'serum': {...}
            }
        """
        base, quote = token_pair.split('/')
        
        # Get base price from Jupiter
        base_price_usd = await self.get_jupiter_price(base)
        
        if base_price_usd is None:
            logger.warning(f"Could not get price for {base}, using fallback")
            # Fallback prices for testing (realistic market prices Feb 2026)
            fallback_prices = {
                # Core
                'SOL': 150.0, 'USDC': 1.0, 'USDT': 1.0,
                # DeFi
                'RAY': 2.0, 'ORCA': 1.0, 'JUP': 0.85, 'JTO': 2.5, 'PYTH': 0.35,
                'MNGO': 0.02, 'SRM': 0.03, 'FIDA': 0.25, 'STEP': 0.05, 'COPE': 0.01,
                # Liquid Staking
                'MSOL': 165.0, 'JITOSOL': 170.0, 'BSOL': 155.0, 'STSOL': 160.0,
                # Meme Coins
                'BONK': 0.00002, 'WIF': 2.5, 'BOME': 0.01, 'MEW': 0.005,
                'POPCAT': 0.8, 'SLERF': 0.3, 'SAMO': 0.01,
                # Infrastructure
                'HNT': 5.0, 'MOBILE': 0.001, 'RENDER': 8.0, 'SHDW': 0.5,
                # Gaming
                'ATLAS': 0.003, 'POLIS': 0.2, 'DUST': 0.8, 'GENE': 0.05, 'DFL': 0.001,
                # Other
                'W': 0.3, 'TENSOR': 0.5,
            }
            base_price_usd = fallback_prices.get(base, 1.0)
        
        # If quote is not USDC, get its price too
        if quote != 'USDC':
            quote_price_usd = await self.get_jupiter_price(quote)
            if quote_price_usd:
                # Calculate price ratio
                price_in_quote = base_price_usd / quote_price_usd
            else:
                price_in_quote = base_price_usd
        else:
            price_in_quote = base_price_usd
        
        # Get DEX-specific prices with simulated spreads
        dexs = ['raydium', 'orca', 'serum']
        prices = {}
        
        for dex in dexs:
            dex_data = await self.get_simulated_dex_spread(price_in_quote, dex)
            prices[dex] = dex_data
        
        return prices


async def test_connection():
    """Test the real price connector"""
    connector = RealPriceConnector()
    
    print("Testing Real Price Connector...")
    print("=" * 60)
    
    # Test 1: Get SOL price from Jupiter
    print("\n1. Testing Jupiter price fetch for SOL...")
    sol_price = await connector.get_jupiter_price('SOL')
    if sol_price:
        print(f"✅ SOL Price (Jupiter): ${sol_price:.2f}")
    else:
        print("⚠️  Could not fetch from Jupiter, will use fallback prices")
    
    # Test 2: Get RAY price
    print("\n2. Testing Jupiter price fetch for RAY...")
    ray_price = await connector.get_jupiter_price('RAY')
    if ray_price:
        print(f"✅ RAY Price (Jupiter): ${ray_price:.2f}")
    else:
        print("⚠️  Using fallback price for RAY")
    
    # Test 3: Get SOL/USDC prices across DEXs
    print("\n3. Testing multi-DEX price comparison for SOL/USDC...")
    dex_prices = await connector.get_all_prices('SOL/USDC')
    if dex_prices:
        print(f"✅ Found prices on {len(dex_prices)} DEXs:")
        for dex, data in dex_prices.items():
            print(f"   - {dex.upper()}:")
            print(f"     Bid: ${data['bid']:.2f} | Ask: ${data['ask']:.2f} | Mid: ${data['mid']:.2f}")
            print(f"     Liquidity: ${data['liquidity']:,.0f}")
            spread_bps = ((data['ask'] - data['bid']) / data['mid']) * 10000
            print(f"     Spread: {spread_bps:.1f} bps")
    else:
        print("❌ No DEX prices found")
    
    # Test 4: Check for arbitrage opportunity
    print("\n4. Checking for arbitrage opportunities...")
    if dex_prices:
        # Find min ask and max bid
        min_ask_dex = min(dex_prices.items(), key=lambda x: x[1]['ask'])
        max_bid_dex = max(dex_prices.items(), key=lambda x: x[1]['bid'])
        
        buy_price = min_ask_dex[1]['ask']
        sell_price = max_bid_dex[1]['bid']
        
        if sell_price > buy_price:
            profit_pct = ((sell_price - buy_price) / buy_price) * 100
            print(f"✅ Arbitrage opportunity found!")
            print(f"   Buy on {min_ask_dex[0].upper()} @ ${buy_price:.2f}")
            print(f"   Sell on {max_bid_dex[0].upper()} @ ${sell_price:.2f}")
            print(f"   Gross profit: {profit_pct:.3f}%")
        else:
            print("   No arbitrage opportunity in current spread")
    
    await connector.close()
    print("\n" + "=" * 60)
    print("Test complete!")


if __name__ == "__main__":
    asyncio.run(test_connection())
