"""
Integrated Flash Loan Monitor
Runs alongside stablecoin and meme coin arbitrage
Executes 10-15 high-quality flash loan trades per day
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
import os

from dex_connectors import DEXAggregator
from flash_loan_config import calculate_flash_loan_profitability, FLASH_LOAN_CONFIG
from risk_manager import RiskManager

logger = logging.getLogger(__name__)

# Global state
flash_loan_state = {
    'enabled': True,
    'daily_trades_executed': 0,
    'daily_target': 280,  # Increased from 15 to 280 trades per day
    'last_reset_date': datetime.now(timezone.utc).date(),
    'total_opportunities_scanned': 0,
    'high_quality_found': 0,
}


class IntegratedFlashLoanMonitor:
    """
    Flash loan monitor integrated with main MEV bot
    Focuses on 10-15 high-quality trades per day
    """
    
    def __init__(self, db, risk_manager: RiskManager):
        self.db = db
        self.dex_aggregator = DEXAggregator()
        self.risk_manager = risk_manager
        
        # Configuration
        self.pairs = ['SOL/USDC', 'RAY/USDC', 'ORCA/USDC', 'JUP/USDC']
        self.loan_sizes = [10000, 15000, 25000]  # Start with smaller loans
        self.min_profit_bps = 20  # Minimum 0.20% profit after flash loan fee
        self.daily_target = 280  # Increased from 15 to 280 trades per day
        
        logger.info("⚡ Flash Loan Monitor initialized")
        logger.info(f"   Target: {self.daily_target} trades/day")
        logger.info(f"   Min profit: {self.min_profit_bps} bps")
    
    def reset_daily_counter_if_needed(self):
        """Reset daily trade counter at midnight"""
        today = datetime.now(timezone.utc).date()
        if today != flash_loan_state['last_reset_date']:
            logger.info(f"🔄 Daily reset: {flash_loan_state['daily_trades_executed']} trades yesterday")
            flash_loan_state['daily_trades_executed'] = 0
            flash_loan_state['last_reset_date'] = today
    
    def can_trade_today(self) -> bool:
        """Check if bot is enabled (no daily limit, unlimited trading)"""
        self.reset_daily_counter_if_needed()
        
        if not flash_loan_state['enabled']:
            return False
        
        # No daily limit - unlimited trading
        return True
    
    async def scan_for_opportunity(self) -> Optional[Dict]:
        """
        Scan all pairs and loan sizes for best flash loan opportunity
        Returns the most profitable high-quality opportunity
        """
        if not self.can_trade_today():
            return None
        
        best_opportunity = None
        best_net_profit = 0
        
        for pair in self.pairs:
            try:
                # Get prices from all DEXs
                prices = await self.dex_aggregator.get_all_prices(pair)
                
                if len(prices) < 2:
                    continue
                
                # Find best buy and sell prices
                min_ask_dex = min(prices.items(), key=lambda x: x[1].get('ask', float('inf')))
                max_bid_dex = max(prices.items(), key=lambda x: x[1].get('bid', 0))
                
                buy_dex, buy_data = min_ask_dex
                sell_dex, sell_data = max_bid_dex
                
                buy_price = buy_data.get('ask', buy_data.get('price', 0))
                sell_price = sell_data.get('bid', sell_data.get('price', 0))
                
                if buy_price <= 0 or sell_price <= 0:
                    continue
                
                # Calculate raw spread
                raw_spread_pct = (sell_price - buy_price) / buy_price
                raw_spread_bps = raw_spread_pct * 10000
                
                # Subtract DEX fees and slippage (~50 bps total)
                net_spread_bps = raw_spread_bps - 50
                
                # Test each loan size
                for loan_size in self.loan_sizes:
                    if net_spread_bps <= 0:
                        continue
                    
                    # Calculate profitability with flash loan fee
                    profitability = calculate_flash_loan_profitability(
                        net_spread_bps,
                        loan_size,
                        'solend'
                    )
                    
                    # Check if meets quality threshold
                    if profitability['is_profitable'] and net_spread_bps >= self.min_profit_bps:
                        # This is a high-quality opportunity
                        flash_loan_state['high_quality_found'] += 1
                        
                        if profitability['net_profit'] > best_net_profit:
                            best_net_profit = profitability['net_profit']
                            best_opportunity = {
                                'token_pair': pair,
                                'buy_dex': buy_dex,
                                'sell_dex': sell_dex,
                                'buy_price': buy_price,
                                'sell_price': sell_price,
                                'loan_size_usd': loan_size,
                                'raw_spread_bps': raw_spread_bps,
                                'net_spread_bps': net_spread_bps,
                                'gross_profit': profitability['gross_profit'],
                                'flash_loan_fee': profitability['flash_loan_fee'],
                                'net_profit': profitability['net_profit'],
                                'profit_after_flash_loan_bps': net_spread_bps,
                                'timestamp': datetime.now(timezone.utc),
                            }
                
                flash_loan_state['total_opportunities_scanned'] += 1
                
            except Exception as e:
                logger.error(f"Error scanning {pair}: {e}")
                continue
        
        return best_opportunity
    
    async def execute_flash_loan_simulation(self, opportunity: Dict) -> Dict:
        """
        Simulate flash loan execution (paper trading)
        In production, this would call flash_loan_executor
        """
        try:
            # Simulate execution success (90% success rate for realism)
            import random
            success = random.random() < 0.90
            
            # Simulate gas cost
            gas_cost = 0.000005 * 150  # ~$0.0007 in SOL
            
            if success:
                # Calculate actual profit after gas
                actual_profit = opportunity['net_profit'] - gas_cost
                
                result = {
                    'success': True,
                    'token_pair': opportunity['token_pair'],
                    'loan_amount': opportunity['loan_size_usd'],
                    'gross_profit': opportunity['gross_profit'],
                    'flash_loan_fee': opportunity['flash_loan_fee'],
                    'gas_cost': gas_cost,
                    'net_profit': actual_profit,
                    'profit_bps': opportunity['profit_after_flash_loan_bps'],
                    'buy_dex': opportunity['buy_dex'],
                    'sell_dex': opportunity['sell_dex'],
                    'timestamp': datetime.now(timezone.utc),
                    'signature': f"SIM_{datetime.now().timestamp()}",
                }
                
                # Increment daily counter
                flash_loan_state['daily_trades_executed'] += 1
                
                logger.info(
                    f"✅ FLASH LOAN EXECUTED: {result['token_pair']} | "
                    f"Loan: ${result['loan_amount']:,.0f} | "
                    f"Net: ${result['net_profit']:.2f} | "
                    f"({flash_loan_state['daily_trades_executed']}/{self.daily_target} today)"
                )
                
                return result
            else:
                logger.warning(f"❌ Flash loan simulation failed for {opportunity['token_pair']}")
                return {
                    'success': False,
                    'token_pair': opportunity['token_pair'],
                    'error': 'Simulation failed (market conditions changed)'
                }
                
        except Exception as e:
            logger.error(f"Error executing flash loan: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def save_trade_to_db(self, trade: Dict):
        """Save executed trade to database"""
        try:
            trade_doc = {
                'type': 'flash_loan',
                'token_pair': trade['token_pair'],
                'loan_amount': trade['loan_amount'],
                'gross_profit': trade.get('gross_profit', 0),
                'flash_loan_fee': trade.get('flash_loan_fee', 0),
                'gas_cost': trade.get('gas_cost', 0),
                'net_profit': trade['net_profit'],
                'profit_bps': trade.get('profit_bps', 0),
                'buy_dex': trade.get('buy_dex', ''),
                'sell_dex': trade.get('sell_dex', ''),
                'success': trade['success'],
                'signature': trade.get('signature', ''),
                'timestamp': trade['timestamp'],  # Store as datetime object, not string
            }
            
            result = await self.db.flash_trades.insert_one(trade_doc)
            logger.info(f"💾 Trade saved to database: {trade_doc['token_pair']} (ID: {result.inserted_id})")
            
        except Exception as e:
            logger.error(f"Error saving trade to DB: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def report_to_dashboard_api(self, opportunity: Dict = None, trade: Dict = None):
        """Report opportunity or trade to dashboard API"""
        try:
            import aiohttp
            backend_url = "http://localhost:8001"  # Internal URL
            
            async with aiohttp.ClientSession() as session:
                if opportunity:
                    # Report opportunity detected
                    await session.post(
                        f"{backend_url}/api/flash/opportunity/detected",
                        json={
                            'token_pair': opportunity['token_pair'],
                            'loan_size': opportunity['loan_size_usd'],
                            'net_profit': opportunity['net_profit'],
                            'profit_bps': opportunity['profit_after_flash_loan_bps'],
                            'buy_dex': opportunity['buy_dex'],
                            'sell_dex': opportunity['sell_dex'],
                        }
                    )
                
                if trade:
                    # Report trade executed
                    await session.post(
                        f"{backend_url}/api/flash/trade/executed",
                        json={
                            'token_pair': trade['token_pair'],
                            'loan_amount': trade['loan_amount'],
                            'net_profit': trade['net_profit'],
                            'profit_bps': trade.get('profit_bps', 0),
                            'success': trade['success'],
                            'gas_cost': trade.get('gas_cost', 0),
                            'signature': trade.get('signature'),
                        }
                    )
        except Exception as e:
            logger.debug(f"Dashboard API report error: {e}")
    
    async def monitor_loop(self):
        """
        Main monitoring loop
        Scans every 5 seconds, executes high-quality opportunities
        """
        logger.info("🚀 Flash Loan Monitor started")
        logger.info(f"   Scanning {len(self.pairs)} pairs")
        logger.info(f"   Loan sizes: ${', '.join([f'{s:,}' for s in self.loan_sizes])}")
        logger.info(f"   Target: {self.daily_target} trades/day")
        
        while True:
            try:
                # Check if we can trade today
                if not self.can_trade_today():
                    await asyncio.sleep(60)  # Check again in 1 minute
                    continue
                
                # Scan for best opportunity
                opportunity = await self.scan_for_opportunity()
                
                if opportunity:
                    logger.info(
                        f"💎 HIGH-QUALITY OPPORTUNITY: {opportunity['token_pair']} | "
                        f"Loan: ${opportunity['loan_size_usd']:,} | "
                        f"Net: ${opportunity['net_profit']:.2f} | "
                        f"{opportunity['net_spread_bps']:.1f} bps"
                    )
                    
                    # Report to dashboard
                    await self.report_to_dashboard_api(opportunity=opportunity)
                    
                    # Execute (simulated for now)
                    result = await self.execute_flash_loan_simulation(opportunity)
                    
                    if result['success']:
                        # Save to database
                        await self.save_trade_to_db(result)
                        
                        # Report to dashboard
                        await self.report_to_dashboard_api(trade=result)
                        
                        # Show progress (unlimited trading, no target)
                        logger.info(f"📊 Trades today: {flash_loan_state['daily_trades_executed']} (Unlimited)")
                    
                    # Wait a bit after execution before scanning again
                    await asyncio.sleep(10)
                else:
                    # No opportunities, wait and scan again
                    await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Error in flash loan monitor loop: {e}")
                await asyncio.sleep(5)
    
    async def close(self):
        """Cleanup"""
        await self.dex_aggregator.close()


# Stats endpoint helper
def get_flash_loan_stats() -> Dict:
    """Get current flash loan statistics"""
    return {
        'enabled': flash_loan_state['enabled'],
        'daily_trades_executed': flash_loan_state['daily_trades_executed'],
        'daily_target': flash_loan_state['daily_target'],
        'remaining_today': max(0, flash_loan_state['daily_target'] - flash_loan_state['daily_trades_executed']),
        'total_scanned': flash_loan_state['total_opportunities_scanned'],
        'high_quality_found': flash_loan_state['high_quality_found'],
        'last_reset': flash_loan_state['last_reset_date'].isoformat(),
    }
