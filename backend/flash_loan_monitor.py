"""
Flash Loan Monitor - Paper Trading Demo
Integrates with existing bot to show flash loan opportunities
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from pathlib import Path

from dex_connectors import DEXAggregator
from flash_loan_config import calculate_flash_loan_profitability

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')


class FlashLoanMonitor:
    """
    Monitors for flash loan opportunities in paper trading mode
    Shows what profits would be possible with flash loans
    """
    
    def __init__(self):
        self.dex_aggregator = DEXAggregator()
        
        # MongoDB connection
        mongo_url = os.environ['MONGO_URL']
        self.client = AsyncIOMotorClient(mongo_url)
        self.db = self.client[os.environ['DB_NAME']]
        
        # Stats
        self.opportunities_found = 0
        self.total_potential_profit = 0.0
        
        # Configuration
        self.pairs = ['SOL/USDC', 'RAY/USDC', 'ORCA/USDC', 'JUP/USDC', 'JTO/USDC']
        self.loan_sizes = [10000, 25000]  # Test $10k and $25k loans
        
        logger.info("🚀 Flash Loan Monitor initialized (Paper Trading)")
    
    async def scan_opportunities(self) -> List[Dict]:
        """Scan for flash loan opportunities"""
        opportunities = []
        
        for pair in self.pairs:
            try:
                # Get prices
                prices = await self.dex_aggregator.get_all_prices(pair)
                
                if len(prices) < 2:
                    continue
                
                # Find best prices
                min_ask = min(
                    [(dex, data.get('ask') or data.get('price')) 
                     for dex, data in prices.items()],
                    key=lambda x: x[1]
                )
                max_bid = max(
                    [(dex, data.get('bid') or data.get('price')) 
                     for dex, data in prices.items()],
                    key=lambda x: x[1]
                )
                
                buy_dex, buy_price = min_ask
                sell_dex, sell_price = max_bid
                
                # Calculate spread (accounting for DEX fees ~0.5%)
                raw_spread_bps = ((sell_price - buy_price) / buy_price) * 10000
                net_spread_bps = raw_spread_bps - 50  # Subtract DEX fees
                
                # Test each loan size
                for loan_size in self.loan_sizes:
                    if net_spread_bps > 0:
                        result = calculate_flash_loan_profitability(
                            net_spread_bps,
                            loan_size,
                            'solend'
                        )
                        
                        if result['is_profitable']:
                            opp = {
                                'id': f"flash_{datetime.now().timestamp()}",
                                'pair': pair,
                                'buy_dex': buy_dex,
                                'sell_dex': sell_dex,
                                'buy_price': buy_price,
                                'sell_price': sell_price,
                                'loan_size_usd': loan_size,
                                'spread_bps': net_spread_bps,
                                'flash_loan_fee': result['flash_loan_fee'],
                                'gross_profit': result['gross_profit'],
                                'net_profit': result['net_profit'],
                                'roi_bps': result['roi_bps'],
                                'timestamp': datetime.now(timezone.utc),
                                'type': 'flash_loan'
                            }
                            opportunities.append(opp)
                            self.opportunities_found += 1
                            self.total_potential_profit += opp['net_profit']
            
            except Exception as e:
                logger.error(f"Error scanning {pair}: {e}")
                continue
        
        return opportunities
    
    async def save_opportunity(self, opp: Dict):
        """Save opportunity to database"""
        opp_dict = {**opp}
        opp_dict['timestamp'] = opp_dict['timestamp'].isoformat()
        await self.db.flash_opportunities.insert_one(opp_dict)
    
    async def monitor_loop(self, interval: int = 5):
        """Main monitoring loop"""
        logger.info(f"👀 Starting flash loan monitoring...")
        logger.info(f"   Pairs: {self.pairs}")
        logger.info(f"   Loan sizes: ${', '.join([f'{s:,}' for s in self.loan_sizes])}")
        logger.info(f"   Scan interval: {interval}s")
        
        while True:
            try:
                opportunities = await self.scan_opportunities()
                
                if opportunities:
                    best = max(opportunities, key=lambda x: x['net_profit'])
                    
                    logger.info(
                        f"💎 FLASH LOAN OPPORTUNITY: {best['pair']} | "
                        f"Loan: ${best['loan_size_usd']:,} | "
                        f"Net Profit: ${best['net_profit']:.2f} | "
                        f"{best['buy_dex']} → {best['sell_dex']}"
                    )
                    
                    # Save to database
                    for opp in opportunities:
                        await self.save_opportunity(opp)
                
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(interval)
    
    def get_stats(self) -> Dict:
        """Get monitoring stats"""
        return {
            'opportunities_found': self.opportunities_found,
            'total_potential_profit': self.total_potential_profit,
            'average_profit': (
                self.total_potential_profit / self.opportunities_found
                if self.opportunities_found > 0 else 0
            )
        }
    
    async def close(self):
        """Cleanup"""
        await self.dex_aggregator.close()
        self.client.close()


async def main():
    """Run flash loan monitor"""
    monitor = FlashLoanMonitor()
    
    try:
        await monitor.monitor_loop(interval=3)
    except KeyboardInterrupt:
        logger.info("\n🛑 Stopping monitor...")
        stats = monitor.get_stats()
        logger.info(f"📊 Final Stats:")
        logger.info(f"   Opportunities found: {stats['opportunities_found']}")
        logger.info(f"   Potential profit: ${stats['total_potential_profit']:.2f}")
        logger.info(f"   Average per trade: ${stats['average_profit']:.2f}")
    finally:
        await monitor.close()


if __name__ == "__main__":
    asyncio.run(main())
