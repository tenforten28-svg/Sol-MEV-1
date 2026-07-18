import asyncio
import random
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
import logging
from real_price_connector import RealPriceConnector

logger = logging.getLogger(__name__)

# Now using real Jupiter API prices with simulated DEX spreads for paper trading

class DEXConnector:
    """Base class for DEX connections"""
    
    def __init__(self, name: str, fee_percentage: float):
        self.name = name
        self.fee_percentage = fee_percentage
        self.last_update = None
        
    async def get_price(self, token_pair: str) -> Optional[Dict]:
        """Get current price and liquidity info"""
        raise NotImplementedError
        
    def calculate_execution_cost(self, amount: float, price: float) -> Dict:
        """Calculate total execution cost including fees and slippage"""
        trade_value = amount * price
        fee = trade_value * self.fee_percentage
        
        # Simulate slippage based on trade size
        # Smaller trades = less slippage
        base_slippage = 0.0001  # 0.01%
        if trade_value < 10:
            slippage_percentage = base_slippage
        elif trade_value < 50:
            slippage_percentage = base_slippage * 1.5
        else:
            slippage_percentage = base_slippage * 2
            
        slippage = trade_value * slippage_percentage
        
        return {
            "fee": fee,
            "fee_percentage": self.fee_percentage * 100,
            "slippage": slippage,
            "slippage_percentage": slippage_percentage * 100,
            "total_cost": fee + slippage,
            "total_cost_percentage": ((fee + slippage) / trade_value) * 100
        }

class SerumConnector(DEXConnector):
    """Serum DEX (Order Book)"""
    
    def __init__(self, fee: float = 0.0022):
        super().__init__("serum", fee)
        
    async def get_price(self, token_pair: str) -> Optional[Dict]:
        # Simulate order book data
        base_price = self._get_base_price(token_pair)
        
        # Order book has tighter spreads but less liquidity at extremes
        spread = random.uniform(0.0001, 0.0008)  # 0.01% to 0.08%
        
        return {
            "dex": self.name,
            "token_pair": token_pair,
            "bid": base_price * (1 - spread/2),
            "ask": base_price * (1 + spread/2),
            "mid_price": base_price,
            "liquidity_usd": random.uniform(5000, 50000),
            "timestamp": datetime.now(timezone.utc),
            "book_depth": {
                "bid_volume": random.uniform(100, 1000),
                "ask_volume": random.uniform(100, 1000)
            }
        }
    
    def _get_base_price(self, pair: str) -> float:
        # Simulate realistic crypto prices with more variance for arbitrage
        # Extended list for 80+ pairs
        base_prices = {
            # Core pairs
            "SOL/USDC": random.uniform(145, 165),
            "SOL/USDT": random.uniform(145, 165),
            "USDC/USDT": random.uniform(0.998, 1.002),
            "USDT/USDC": random.uniform(0.998, 1.002),
            # DeFi tokens
            "RAY/USDC": random.uniform(1.8, 2.5),
            "RAY/USDT": random.uniform(1.8, 2.5),
            "RAY/SOL": random.uniform(0.012, 0.017),
            "ORCA/USDC": random.uniform(0.8, 1.3),
            "ORCA/USDT": random.uniform(0.8, 1.3),
            "ORCA/SOL": random.uniform(0.005, 0.009),
            "JUP/USDC": random.uniform(0.7, 1.0),
            "JUP/USDT": random.uniform(0.7, 1.0),
            "JUP/SOL": random.uniform(0.004, 0.007),
            "JTO/USDC": random.uniform(2.0, 3.2),
            "JTO/USDT": random.uniform(2.0, 3.2),
            "JTO/SOL": random.uniform(0.013, 0.022),
            "PYTH/USDC": random.uniform(0.28, 0.45),
            "PYTH/USDT": random.uniform(0.28, 0.45),
            "PYTH/SOL": random.uniform(0.0018, 0.003),
            "MNGO/USDC": random.uniform(0.015, 0.03),
            "FIDA/USDC": random.uniform(0.2, 0.35),
            "SRM/USDC": random.uniform(0.02, 0.05),
            # Liquid staking
            "MSOL/USDC": random.uniform(160, 180),
            "MSOL/USDT": random.uniform(160, 180),
            "MSOL/SOL": random.uniform(1.05, 1.12),
            "JITOSOL/USDC": random.uniform(165, 185),
            "JITOSOL/USDT": random.uniform(165, 185),
            "JITOSOL/SOL": random.uniform(1.06, 1.13),
            "BSOL/USDC": random.uniform(150, 170),
            "BSOL/SOL": random.uniform(1.01, 1.08),
            "STSOL/SOL": random.uniform(1.04, 1.10),
            # Meme coins (high volatility)
            "BONK/USDC": random.uniform(0.000015, 0.00003),
            "BONK/USDT": random.uniform(0.000015, 0.00003),
            "BONK/SOL": random.uniform(0.0000001, 0.0000002),
            "WIF/USDC": random.uniform(2.0, 3.5),
            "WIF/USDT": random.uniform(2.0, 3.5),
            "WIF/SOL": random.uniform(0.013, 0.024),
            "BOME/USDC": random.uniform(0.008, 0.015),
            "BOME/USDT": random.uniform(0.008, 0.015),
            "BOME/SOL": random.uniform(0.00005, 0.0001),
            "MEW/USDC": random.uniform(0.003, 0.008),
            "MEW/USDT": random.uniform(0.003, 0.008),
            "MEW/SOL": random.uniform(0.00002, 0.00005),
            "POPCAT/USDC": random.uniform(0.6, 1.1),
            "SLERF/USDC": random.uniform(0.2, 0.45),
            "SAMO/USDC": random.uniform(0.008, 0.015),
            # Meme vs meme (high arb potential)
            "BONK/WIF": random.uniform(0.000008, 0.000015),
            "BOME/BONK": random.uniform(400, 700),
            "MEW/BONK": random.uniform(150, 350),
            "POPCAT/BONK": random.uniform(30000, 50000),
            "SLERF/BONK": random.uniform(10000, 20000),
            "WIF/BOME": random.uniform(180, 350),
            "POPCAT/WIF": random.uniform(0.2, 0.5),
            "MEW/WIF": random.uniform(0.001, 0.003),
            # Infrastructure
            "HNT/USDC": random.uniform(4.0, 7.0),
            "HNT/USDT": random.uniform(4.0, 7.0),
            "HNT/SOL": random.uniform(0.025, 0.048),
            "MOBILE/USDC": random.uniform(0.0008, 0.0015),
            "RENDER/USDC": random.uniform(6.5, 10.0),
            "RENDER/USDT": random.uniform(6.5, 10.0),
            "RENDER/SOL": random.uniform(0.04, 0.07),
            "SHDW/USDC": random.uniform(0.35, 0.7),
            # Gaming
            "ATLAS/USDC": random.uniform(0.002, 0.005),
            "POLIS/USDC": random.uniform(0.15, 0.3),
            "DUST/USDC": random.uniform(0.6, 1.1),
            "GENE/USDC": random.uniform(0.03, 0.08),
            "DFL/USDC": random.uniform(0.0008, 0.002),
            # Other
            "W/USDC": random.uniform(0.22, 0.4),
            "W/USDT": random.uniform(0.22, 0.4),
            "W/SOL": random.uniform(0.0014, 0.0028),
            "TENSOR/USDC": random.uniform(0.35, 0.7),
            "TENSOR/USDT": random.uniform(0.35, 0.7),
            "TENSOR/SOL": random.uniform(0.0022, 0.0048),
            "STEP/USDC": random.uniform(0.03, 0.08),
            "COPE/USDC": random.uniform(0.008, 0.02),
        }
        return base_prices.get(pair, random.uniform(0.1, 10))

class RaydiumConnector(DEXConnector):
    """Raydium AMM"""
    
    def __init__(self, fee: float = 0.0025):
        super().__init__("raydium", fee)
        
    async def get_price(self, token_pair: str) -> Optional[Dict]:
        base_price = self._get_base_price(token_pair)
        
        # AMM pools have slightly wider spreads but deeper liquidity
        spread = random.uniform(0.0002, 0.001)  # 0.02% to 0.1%
        
        return {
            "dex": self.name,
            "token_pair": token_pair,
            "price": base_price,
            "liquidity_usd": random.uniform(10000, 100000),
            "timestamp": datetime.now(timezone.utc),
            "pool_info": {
                "reserve_token_a": random.uniform(1000, 10000),
                "reserve_token_b": random.uniform(10000, 100000),
                "fee_rate": self.fee_percentage
            }
        }
    
    def _get_base_price(self, pair: str) -> float:
        # Raydium uses the same expanded price list with slight variance
        from dex_connectors import SerumConnector
        base = SerumConnector()._get_base_price(pair)
        # Raydium might have slightly different prices (wider variance)
        return base * random.uniform(0.996, 1.004)

class OrcaConnector(DEXConnector):
    """Orca AMM"""
    
    def __init__(self, fee: float = 0.003):
        super().__init__("orca", fee)
        
    async def get_price(self, token_pair: str) -> Optional[Dict]:
        base_price = self._get_base_price(token_pair)
        
        spread = random.uniform(0.0002, 0.0012)  # 0.02% to 0.12%
        
        return {
            "dex": self.name,
            "token_pair": token_pair,
            "price": base_price,
            "liquidity_usd": random.uniform(8000, 80000),
            "timestamp": datetime.now(timezone.utc),
            "pool_info": {
                "whirlpool": True,
                "concentrated_liquidity": random.uniform(5000, 50000),
                "fee_rate": self.fee_percentage
            }
        }
    
    def _get_base_price(self, pair: str) -> float:
        # Orca uses the same expanded price list with slight variance
        from dex_connectors import SerumConnector
        base = SerumConnector()._get_base_price(pair)
        # Orca might have slightly different prices
        return base * random.uniform(0.995, 1.005)

class DEXAggregator:
    """Aggregates data from multiple DEXs and finds arbitrage opportunities"""
    
    def __init__(self):
        self.connectors = {
            "serum": SerumConnector(),
            "raydium": RaydiumConnector(),
            "orca": OrcaConnector()
        }
        # Initialize real price connector for paper trading
        self.real_price_connector = RealPriceConnector(use_mainnet_prices=True)
        
    async def get_all_prices(self, token_pair: str) -> Dict[str, Dict]:
        """
        Fetch prices from all DEXs using real Jupiter API data
        Maintains DEX-specific spreads and liquidity simulation for paper trading
        """
        try:
            # Get real prices from Jupiter API with DEX-specific spreads
            real_dex_prices = await self.real_price_connector.get_all_prices(token_pair)
            
            if real_dex_prices:
                # Convert real price format to our expected format
                prices = {}
                for dex_name, dex_data in real_dex_prices.items():
                    connector = self.connectors.get(dex_name)
                    if not connector:
                        continue
                    
                    prices[dex_name] = {
                        "dex": dex_name,
                        "token_pair": token_pair,
                        "bid": dex_data['bid'],
                        "ask": dex_data['ask'],
                        "mid_price": dex_data['mid'],
                        "price": dex_data['mid'],  # For AMM compatibility
                        "liquidity_usd": dex_data['liquidity'],
                        "timestamp": dex_data['timestamp'],
                        "source": "jupiter_api"
                    }
                
                logger.info(f"📊 Real prices from Jupiter API for {token_pair}")
                return prices
            
        except Exception as e:
            logger.warning(f"Error fetching real prices for {token_pair}: {e}, using simulated fallback")
        
        # Fallback to simulated prices if real API fails
        logger.info(f"Using simulated prices for {token_pair}")
        prices = {}
        
        tasks = [
            connector.get_price(token_pair) 
            for connector in self.connectors.values()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for connector_name, result in zip(self.connectors.keys(), results):
            if not isinstance(result, Exception) and result:
                prices[connector_name] = result
                
        return prices
    
    def find_arbitrage_opportunity(
        self, 
        prices: Dict[str, Dict],
        max_trade_amount: float,
        min_spread: float,
        max_slippage: float
    ) -> Optional[Dict]:
        """Find profitable arbitrage opportunities with realistic cost modeling"""
        
        if len(prices) < 2:
            return None
            
        opportunities = []
        
        # Compare all DEX pairs
        dex_names = list(prices.keys())
        for i, buy_dex_name in enumerate(dex_names):
            for sell_dex_name in dex_names[i+1:]:
                buy_data = prices[buy_dex_name]
                sell_data = prices[sell_dex_name]
                
                # Get prices (handle both order book and AMM formats)
                buy_price = buy_data.get('ask') or buy_data.get('price')
                sell_price = sell_data.get('bid') or sell_data.get('price')
                
                if not buy_price or not sell_price:
                    continue
                
                # Calculate costs
                buy_connector = self.connectors[buy_dex_name]
                sell_connector = self.connectors[sell_dex_name]
                
                buy_costs = buy_connector.calculate_execution_cost(
                    max_trade_amount / buy_price, buy_price
                )
                sell_costs = sell_connector.calculate_execution_cost(
                    max_trade_amount / sell_price, sell_price
                )
                
                # Check if slippage is within tolerance
                if (buy_costs['slippage_percentage'] > max_slippage * 100 or 
                    sell_costs['slippage_percentage'] > max_slippage * 100):
                    continue
                
                # Calculate net profit
                gross_profit = (sell_price - buy_price) / buy_price
                total_costs = (buy_costs['total_cost'] + sell_costs['total_cost']) / max_trade_amount
                net_profit_percentage = gross_profit - total_costs
                
                if net_profit_percentage >= min_spread:
                    net_profit_amount = max_trade_amount * net_profit_percentage
                    
                    opportunities.append({
                        "dex_buy": buy_dex_name,
                        "dex_sell": sell_dex_name,
                        "token_pair": buy_data['token_pair'],
                        "buy_price": buy_price,
                        "sell_price": sell_price,
                        "gross_spread_percentage": gross_profit * 100,
                        "buy_costs": buy_costs,
                        "sell_costs": sell_costs,
                        "total_cost_percentage": total_costs * 100,
                        "net_profit_percentage": net_profit_percentage * 100,
                        "net_profit_amount": net_profit_amount,
                        "trade_amount": max_trade_amount,
                        "liquidity_buy": buy_data.get('liquidity_usd', 0),
                        "liquidity_sell": sell_data.get('liquidity_usd', 0),
                        "timestamp": datetime.now(timezone.utc)
                    })
        
        # Return best opportunity
        if opportunities:
            return max(opportunities, key=lambda x: x['net_profit_percentage'])
        
        return None
    
    async def close(self):
        """Close real price connector session"""
        if self.real_price_connector:
            await self.real_price_connector.close()
