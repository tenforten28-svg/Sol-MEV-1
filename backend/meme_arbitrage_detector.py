"""
Meme Coin Arbitrage Detector
Detects arbitrage opportunities across DEXs for meme coins
Supports both simple and triangular arbitrage
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from meme_coin_config import ALL_MEME_PAIRS, MEME_CROSS_PAIRS, MEME_STABLE_PAIRS
from meme_price_connector import MemePriceConnector
from liquidity_verifier import LiquidityVerifier

logger = logging.getLogger(__name__)

class MemeArbitrageDetector:
    """Detects arbitrage opportunities for meme coins"""
    
    def __init__(
        self,
        price_connector: MemePriceConnector,
        liquidity_verifier: LiquidityVerifier,
        min_profit_bps: int = 15,
        max_slippage_bps: int = 30
    ):
        self.price_connector = price_connector
        self.liquidity_verifier = liquidity_verifier
        self.min_profit_bps = min_profit_bps
        self.max_slippage_bps = max_slippage_bps
    
    async def detect_simple_arbitrage(self, pair: str) -> Optional[Dict]:
        """
        Detect simple arbitrage: buy on one DEX, sell on another
        
        Returns opportunity dict or None
        """
        dex_prices = await self.price_connector.get_dex_prices(pair)
        
        if not dex_prices or len(dex_prices) < 2:
            return None
        
        # Find cheapest ask and highest bid
        min_ask_dex = min(dex_prices.items(), key=lambda x: x[1]['ask'])
        max_bid_dex = max(dex_prices.items(), key=lambda x: x[1]['bid'])
        
        buy_dex, buy_data = min_ask_dex
        sell_dex, sell_data = max_bid_dex
        
        # Don't trade with same DEX
        if buy_dex == sell_dex:
            return None
        
        buy_price = buy_data['ask']
        sell_price = sell_data['bid']
        
        # Calculate profit
        if sell_price <= buy_price:
            return None
        
        profit_bps = ((sell_price - buy_price) / buy_price) * 10000
        
        # Check minimum profit threshold
        if profit_bps < self.min_profit_bps:
            return None
        
        # Estimate slippage (higher for meme coins)
        estimated_slippage_bps = self._estimate_slippage(
            buy_data['liquidity'],
            sell_data['liquidity'],
            1.0  # Assume 1 SOL trade size for estimation
        )
        
        # Check slippage
        if estimated_slippage_bps > self.max_slippage_bps:
            return None
        
        # Check liquidity safety
        min_liquidity = min(buy_data['liquidity'], sell_data['liquidity'])
        
        # Net profit after slippage
        net_profit_bps = profit_bps - estimated_slippage_bps
        
        if net_profit_bps < self.min_profit_bps:
            return None
        
        return {
            'type': 'simple',
            'pair': pair,
            'buy_dex': buy_dex,
            'sell_dex': sell_dex,
            'buy_price': buy_price,
            'sell_price': sell_price,
            'gross_profit_bps': profit_bps,
            'slippage_bps': estimated_slippage_bps,
            'net_profit_bps': net_profit_bps,
            'liquidity_usd': min_liquidity,
            'spread_bps': ((sell_price - buy_price) / buy_price) * 10000,
            'timestamp': datetime.now(timezone.utc),
            'safe': min_liquidity >= 100000  # $100K minimum
        }
    
    async def detect_triangular_arbitrage(
        self,
        base: str,
        intermediary: str,
        quote: str
    ) -> Optional[Dict]:
        """
        Detect triangular arbitrage opportunity
        
        Example: BONK -> WIF -> USDC
        """
        cross_data = await self.price_connector.get_cross_pair_prices(
            base, intermediary, quote
        )
        
        if not cross_data or not cross_data.get('profitable'):
            return None
        
        arbitrage_pct = cross_data['arbitrage_pct']
        
        if arbitrage_pct < (self.min_profit_bps / 100):
            return None
        
        # Get detailed price data for each leg
        pair1 = f"{base}/{intermediary}"
        pair2 = f"{intermediary}/{quote}"
        
        prices1 = await self.price_connector.get_dex_prices(pair1)
        prices2 = await self.price_connector.get_dex_prices(pair2)
        
        if not prices1 or not prices2:
            return None
        
        # Find best routes for each leg
        best_dex1 = min(prices1.items(), key=lambda x: x[1]['ask'])
        best_dex2 = max(prices2.items(), key=lambda x: x[1]['bid'])
        
        # Estimate combined slippage
        liquidity1 = best_dex1[1]['liquidity']
        liquidity2 = best_dex2[1]['liquidity']
        
        estimated_slippage_bps = self._estimate_slippage(liquidity1, liquidity2, 0.5)
        
        net_profit_bps = (arbitrage_pct * 100) - estimated_slippage_bps
        
        if net_profit_bps < self.min_profit_bps:
            return None
        
        min_liquidity = min(liquidity1, liquidity2)
        
        return {
            'type': 'triangular',
            'path': f"{base} -> {intermediary} -> {quote}",
            'leg1': {
                'pair': pair1,
                'dex': best_dex1[0],
                'price': best_dex1[1]['ask'],
                'liquidity': liquidity1
            },
            'leg2': {
                'pair': pair2,
                'dex': best_dex2[0],
                'price': best_dex2[1]['bid'],
                'liquidity': liquidity2
            },
            'gross_profit_bps': arbitrage_pct * 100,
            'slippage_bps': estimated_slippage_bps,
            'net_profit_bps': net_profit_bps,
            'liquidity_usd': min_liquidity,
            'timestamp': datetime.now(timezone.utc),
            'safe': min_liquidity >= 100000
        }
    
    def _estimate_slippage(
        self,
        liquidity1: float,
        liquidity2: float,
        trade_size_sol: float
    ) -> float:
        """
        Estimate slippage based on liquidity and trade size
        Meme coins have higher price impact
        """
        # Convert trade size to USD (assume SOL = $150)
        trade_size_usd = trade_size_sol * 150
        
        # Calculate price impact for each side
        avg_liquidity = (liquidity1 + liquidity2) / 2
        
        if avg_liquidity == 0:
            return 999  # Very high slippage for zero liquidity
        
        # Price impact formula (simplified)
        impact_ratio = trade_size_usd / avg_liquidity
        
        # Meme coins have 2x the impact due to volatility
        meme_multiplier = 2.0
        
        # Base slippage in bps
        slippage_bps = impact_ratio * 10000 * meme_multiplier
        
        # Minimum 5 bps for meme coins
        return max(slippage_bps, 5.0)
    
    async def scan_all_opportunities(self) -> List[Dict]:
        """
        Scan all meme pairs for arbitrage opportunities
        
        Returns list of opportunities sorted by profitability
        """
        opportunities = []
        
        # Scan simple arbitrage for stable pairs
        for pair in MEME_STABLE_PAIRS:
            try:
                opp = await self.detect_simple_arbitrage(pair)
                if opp:
                    opportunities.append(opp)
            except Exception as e:
                logger.error(f"Error detecting arbitrage for {pair}: {e}")
        
        # Scan triangular arbitrage for cross pairs
        triangular_paths = [
            ('BONK', 'WIF', 'USDC'),
            ('BONK', 'POPCAT', 'USDC'),
            ('WIF', 'POPCAT', 'USDC'),
            ('MEW', 'BONK', 'USDC'),
            ('MYRO', 'WIF', 'USDC'),
        ]
        
        for base, intermediary, quote in triangular_paths:
            try:
                opp = await self.detect_triangular_arbitrage(base, intermediary, quote)
                if opp:
                    opportunities.append(opp)
            except Exception as e:
                logger.error(f"Error detecting triangular arbitrage {base}->{intermediary}->{quote}: {e}")
        
        # Sort by net profit
        opportunities.sort(key=lambda x: x['net_profit_bps'], reverse=True)
        
        return opportunities


async def test_detector():
    """Test meme arbitrage detector"""
    from meme_price_connector import MemePriceConnector
    from liquidity_verifier import LiquidityVerifier
    
    connector = MemePriceConnector()
    verifier = LiquidityVerifier()
    detector = MemeArbitrageDetector(connector, verifier)
    
    print("Testing Meme Arbitrage Detector...")
    print("=" * 60)
    
    # Test simple arbitrage
    print("\n1. Testing simple arbitrage (BONK/USDC)...")
    opp = await detector.detect_simple_arbitrage('BONK/USDC')
    if opp:
        print(f"   ✅ Opportunity found!")
        print(f"   Buy on {opp['buy_dex'].upper()} @ ${opp['buy_price']:.8f}")
        print(f"   Sell on {opp['sell_dex'].upper()} @ ${opp['sell_price']:.8f}")
        print(f"   Gross profit: {opp['gross_profit_bps']:.1f} bps")
        print(f"   Slippage: {opp['slippage_bps']:.1f} bps")
        print(f"   Net profit: {opp['net_profit_bps']:.1f} bps")
    else:
        print("   No opportunity found")
    
    # Test triangular arbitrage
    print("\n2. Testing triangular arbitrage (BONK->WIF->USDC)...")
    tri_opp = await detector.detect_triangular_arbitrage('BONK', 'WIF', 'USDC')
    if tri_opp:
        print(f"   ✅ Triangular opportunity found!")
        print(f"   Path: {tri_opp['path']}")
        print(f"   Leg 1: {tri_opp['leg1']['pair']} on {tri_opp['leg1']['dex']}")
        print(f"   Leg 2: {tri_opp['leg2']['pair']} on {tri_opp['leg2']['dex']}")
        print(f"   Net profit: {tri_opp['net_profit_bps']:.1f} bps")
    else:
        print("   No triangular opportunity found")
    
    # Test full scan
    print("\n3. Scanning all opportunities...")
    all_opps = await detector.scan_all_opportunities()
    print(f"   Found {len(all_opps)} total opportunities")
    
    if all_opps:
        print("\n   Top 3 opportunities:")
        for i, opp in enumerate(all_opps[:3], 1):
            if opp['type'] == 'simple':
                print(f"   {i}. {opp['pair']}: {opp['buy_dex']} -> {opp['sell_dex']} | {opp['net_profit_bps']:.1f} bps")
            else:
                print(f"   {i}. {opp['path']} | {opp['net_profit_bps']:.1f} bps")
    
    await connector.close()
    await verifier.close()
    print("\n" + "=" * 60)


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_detector())
