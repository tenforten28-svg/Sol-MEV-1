"""
Integrated Flash Loan Monitor - Live Trading Version
Supports both simulation and live trading modes
"""

import asyncio
import logging
import os
from typing import Dict, List, Optional
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

from dex_connectors import DEXAggregator
from flash_loan_config import calculate_flash_loan_profitability, FLASH_LOAN_CONFIG
from risk_manager import RiskManager

logger = logging.getLogger(__name__)

# Global state
flash_loan_state = {
    'enabled': True,
    'daily_trades_executed': 0,
    'daily_target': 280,
    'last_reset_date': datetime.now(timezone.utc).date(),
    'total_opportunities_scanned': 0,
    'high_quality_found': 0,
}

# Check if live trading is enabled
LIVE_TRADING = os.environ.get('AUTO_EXECUTE', 'false').lower() == 'true'
SIMULATE_FIRST = os.environ.get('SIMULATE_FIRST', 'true').lower() == 'true'


class IntegratedFlashLoanMonitor:
    """
    Flash loan monitor with live trading support
    """
    
    def __init__(self, db, risk_manager: RiskManager):
        self.db = db
        self.dex_aggregator = DEXAggregator()
        self.risk_manager = risk_manager
        
        # Configuration
        self.pairs = ['SOL/USDC', 'RAY/USDC', 'ORCA/USDC', 'JUP/USDC']
        self.loan_sizes = [10000, 15000, 25000]
        self.min_profit_bps = int(os.environ.get('MIN_PROFIT_BPS', 20))
        self.daily_target = 280
        
        # Live trading components
        self.live_executor = None
        self.is_live = LIVE_TRADING and not SIMULATE_FIRST
        
        if self.is_live:
            self._init_live_executor()
        
        mode = "LIVE TRADING" if self.is_live else "SIMULATION"
        logger.info(f"Flash Loan Monitor initialized - MODE: {mode}")
        logger.info(f"   Target: {self.daily_target} trades/day")
        logger.info(f"   Min profit: {self.min_profit_bps} bps")
    
    def _init_live_executor(self):
        """Initialize live trading executor"""
        try:
            from flash_loan_executor_production import ProductionFlashLoanExecutor
            
            rpc_url = os.environ.get('SOLANA_RPC_URL')
            private_key = os.environ.get('SOLANA_PRIVATE_KEY')
            
            if not rpc_url or not private_key:
                logger.error("Missing SOLANA_RPC_URL or SOLANA_PRIVATE_KEY for live trading")
                self.is_live = False
                return
            
            self.live_executor = ProductionFlashLoanExecutor(
                rpc_url=rpc_url,
                private_key=private_key,
                use_jupiter=True
            )
            logger.info("Live trading executor initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize live executor: {e}")
            self.is_live = False
    
    def reset_daily_counter_if_needed(self):
        """Reset daily trade counter at midnight"""
        today = datetime.now(timezone.utc).date()
        if today != flash_loan_state['last_reset_date']:
            logger.info(f"Daily reset: {flash_loan_state['daily_trades_executed']} trades yesterday")
            flash_loan_state['daily_trades_executed'] = 0
            flash_loan_state['last_reset_date'] = today
    
    def can_trade_today(self) -> bool:
        """Check if bot is enabled"""
        self.reset_daily_counter_if_needed()
        return flash_loan_state['enabled']
    
    async def scan_for_opportunity(self) -> Optional[Dict]:
        """Scan all pairs and loan sizes for best flash loan opportunity"""
        if not self.can_trade_today():
            return None
        
        best_opportunity = None
        best_net_profit = 0
        
        for pair in self.pairs:
            try:
                prices = await self.dex_aggregator.get_all_dex_prices(pair)
                
                if not prices or len(prices) < 2:
                    continue
                
                flash_loan_state['total_opportunities_scanned'] += 1
                
                dex_list = [(dex, data) for dex, data in prices.items() if data.get('price')]
                
                for i, (buy_dex, buy_data) in enumerate(dex_list):
                    for sell_dex, sell_data in dex_list[i+1:]:
                        buy_price = buy_data['price']
                        sell_price = sell_data['price']
                        
                        if sell_price > buy_price:
                            high_dex, high_price = sell_dex, sell_price
                            low_dex, low_price = buy_dex, buy_price
                        else:
                            high_dex, high_price = buy_dex, buy_price
                            low_dex, low_price = sell_dex, sell_price
                        
                        spread_bps = ((high_price - low_price) / low_price) * 10000
                        
                        if spread_bps < self.min_profit_bps + 9:
                            continue
                        
                        for loan_size in self.loan_sizes:
                            analysis = calculate_flash_loan_profitability(
                                spread_bps,
                                loan_size,
                                'solend'
                            )
                            
                            if analysis['is_profitable'] and analysis['net_profit'] > best_net_profit:
                                best_net_profit = analysis['net_profit']
                                best_opportunity = {
                                    'token_pair': pair,
                                    'buy_dex': low_dex,
                                    'sell_dex': high_dex,
                                    'buy_price': low_price,
                                    'sell_price': high_price,
                                    'spread_bps': spread_bps,
                                    'loan_size_usd': loan_size,
                                    'gross_profit': analysis['gross_profit'],
                                    'flash_loan_fee': analysis['flash_loan_fee'],
                                    'net_profit': analysis['net_profit'],
                                    'profit_after_flash_loan_bps': analysis['net_profit_bps'],
                                    'net_spread_bps': analysis['net_profit_bps'],
                                    'timestamp': datetime.now(timezone.utc)
                                }
                                flash_loan_state['high_quality_found'] += 1
                
            except Exception as e:
                logger.debug(f"Error scanning {pair}: {e}")
                continue
        
        return best_opportunity
    
    async def execute_flash_loan(self, opportunity: Dict) -> Dict:
        """Execute flash loan - live or simulation based on mode"""
        if self.is_live and self.live_executor:
            return await self._execute_live(opportunity)
        else:
            return await self._execute_simulation(opportunity)
    
    async def _execute_live(self, opportunity: Dict) -> Dict:
        """Execute real flash loan on-chain"""
        try:
            logger.info(f"LIVE EXECUTION: {opportunity['token_pair']}")
            
            # Build and execute the transaction
            result = await self.live_executor.execute_arbitrage(
                opportunity=opportunity,
                loan_amount_usd=opportunity['loan_size_usd']
            )
            
            if result and result.get('success'):
                flash_loan_state['daily_trades_executed'] += 1
                
                logger.info(
                    f"LIVE TRADE SUCCESS: {result['token_pair']} | "
                    f"Loan: ${result['loan_amount']:,.0f} | "
                    f"Net: ${result['net_profit']:.2f} | "
                    f"Sig: {result.get('signature', 'N/A')[:20]}..."
                )
                
                # Transfer profit to safe wallet if configured
                await self._transfer_profit_to_safe_wallet(result['net_profit'])
                
                return result
            else:
                error = result.get('error', 'Unknown error') if result else 'No result'
                logger.warning(f"Live trade failed: {error}")
                return {
                    'success': False,
                    'token_pair': opportunity['token_pair'],
                    'error': error
                }
                
        except Exception as e:
            logger.error(f"Live execution error: {e}")
            return {
                'success': False,
                'token_pair': opportunity['token_pair'],
                'error': str(e)
            }
    
    async def _execute_simulation(self, opportunity: Dict) -> Dict:
        """Simulate flash loan execution (paper trading)"""
        try:
            import random
            success = random.random() < 0.90
            
            gas_cost = 0.000005 * 150
            
            if success:
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
                    'mode': 'simulation'
                }
                
                flash_loan_state['daily_trades_executed'] += 1
                
                logger.info(
                    f"SIMULATED TRADE: {result['token_pair']} | "
                    f"Loan: ${result['loan_amount']:,.0f} | "
                    f"Net: ${result['net_profit']:.2f} | "
                    f"({flash_loan_state['daily_trades_executed']}/{self.daily_target} today)"
                )
                
                return result
            else:
                logger.warning(f"Simulation failed for {opportunity['token_pair']}")
                return {
                    'success': False,
                    'token_pair': opportunity['token_pair'],
                    'error': 'Simulation failed (market conditions changed)',
                    'mode': 'simulation'
                }
                
        except Exception as e:
            logger.error(f"Error in simulation: {e}")
            return {
                'success': False,
                'error': str(e),
                'mode': 'simulation'
            }
    
    async def _transfer_profit_to_safe_wallet(self, profit_usd: float):
        """Transfer profits to safe wallet"""
        try:
            profit_wallet = os.environ.get('PROFIT_WALLET_ADDRESS')
            if not profit_wallet or not self.live_executor:
                return
            
            # Only transfer if profit is above minimum threshold
            min_transfer = 1.0  # $1 minimum
            if profit_usd < min_transfer:
                return
            
            logger.info(f"Transferring ${profit_usd:.2f} profit to safe wallet")
            # Transfer logic would go here
            
        except Exception as e:
            logger.error(f"Profit transfer error: {e}")
    
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
                'buy_dex': trade.get('buy_dex', 'unknown'),
                'sell_dex': trade.get('sell_dex', 'unknown'),
                'success': trade.get('success', True),
                'signature': trade.get('signature'),
                'mode': trade.get('mode', 'simulation'),
                'timestamp': trade.get('timestamp', datetime.now(timezone.utc)),
                'created_at': datetime.now(timezone.utc)
            }
            
            result = await self.db.flash_trades.insert_one(trade_doc)
            logger.info(f"Trade saved to database: {trade_doc['token_pair']} (ID: {result.inserted_id})")
            
        except Exception as e:
            logger.error(f"Error saving trade to DB: {e}")
    
    async def monitor_loop(self):
        """Main monitoring loop"""
        mode = "LIVE" if self.is_live else "SIMULATION"
        logger.info(f"Flash Loan Monitor started - {mode} MODE")
        logger.info(f"   Scanning {len(self.pairs)} pairs")
        logger.info(f"   Loan sizes: ${', '.join([f'{s:,}' for s in self.loan_sizes])}")
        
        while True:
            try:
                if not self.can_trade_today():
                    await asyncio.sleep(60)
                    continue
                
                opportunity = await self.scan_for_opportunity()
                
                if opportunity:
                    logger.info(
                        f"OPPORTUNITY: {opportunity['token_pair']} | "
                        f"Loan: ${opportunity['loan_size_usd']:,} | "
                        f"Net: ${opportunity['net_profit']:.2f} | "
                        f"{opportunity['net_spread_bps']:.1f} bps"
                    )
                    
                    result = await self.execute_flash_loan(opportunity)
                    
                    if result['success']:
                        await self.save_trade_to_db(result)
                        logger.info(f"Trades today: {flash_loan_state['daily_trades_executed']} (Unlimited)")
                    
                    await asyncio.sleep(10)
                else:
                    await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(5)
    
    async def close(self):
        """Cleanup"""
        await self.dex_aggregator.close()


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
        'mode': 'live' if LIVE_TRADING else 'simulation'
    }
