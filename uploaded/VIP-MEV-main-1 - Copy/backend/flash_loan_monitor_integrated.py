"""
ULTRA-OPTIMIZED Flash Loan Monitor with Jito MEV
Maximum pairs, fastest scanning, multi-DEX routes
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
    'daily_target': 1000,
    'last_reset_date': datetime.now(timezone.utc).date(),
    'total_opportunities_scanned': 0,
    'high_quality_found': 0,
}

# Trading mode from environment
LIVE_TRADING = os.environ.get('AUTO_EXECUTE', 'false').lower() == 'true'
USE_JITO = os.environ.get('USE_JITO', 'true').lower() == 'true'


class IntegratedFlashLoanMonitor:
    """
    ULTRA-OPTIMIZED Flash loan monitor with Jito MEV integration
    - 80+ trading pairs across multiple quote tokens
    - 1 second scan interval
    - Multi-DEX route optimization
    """
    
    def __init__(self, db, risk_manager: RiskManager):
        self.db = db
        self.dex_aggregator = DEXAggregator()
        self.risk_manager = risk_manager
        
        # ULTRA-OPTIMIZED: 80+ pairs across USDC, USDT, and SOL routes
        self.pairs = [
            # === HIGH VOLUME USDC PAIRS (Primary) ===
            'SOL/USDC', 'RAY/USDC', 'ORCA/USDC', 'JUP/USDC', 'JTO/USDC', 'PYTH/USDC',
            'BONK/USDC', 'WIF/USDC', 'MNGO/USDC', 'MSOL/USDC', 'JITOSOL/USDC',
            'HNT/USDC', 'MOBILE/USDC', 'RENDER/USDC', 'W/USDC', 'TENSOR/USDC',
            'BOME/USDC', 'MEW/USDC', 'POPCAT/USDC', 'SLERF/USDC', 'SAMO/USDC',
            'FIDA/USDC', 'SRM/USDC', 'STEP/USDC', 'COPE/USDC', 'ATLAS/USDC',
            'POLIS/USDC', 'GENE/USDC', 'DFL/USDC', 'SHDW/USDC', 'DUST/USDC',
            
            # === USDT PAIRS (Alternative routes) ===
            'SOL/USDT', 'RAY/USDT', 'ORCA/USDT', 'JUP/USDT', 'JTO/USDT', 'PYTH/USDT',
            'BONK/USDT', 'WIF/USDT', 'MSOL/USDT', 'JITOSOL/USDT', 'HNT/USDT',
            'RENDER/USDT', 'W/USDT', 'TENSOR/USDT', 'BOME/USDT', 'MEW/USDT',
            
            # === SOL PAIRS (Cross-token arbitrage) ===
            'RAY/SOL', 'ORCA/SOL', 'JUP/SOL', 'JTO/SOL', 'PYTH/SOL',
            'BONK/SOL', 'WIF/SOL', 'MSOL/SOL', 'JITOSOL/SOL', 'HNT/SOL',
            'RENDER/SOL', 'W/SOL', 'TENSOR/SOL', 'BOME/SOL', 'MEW/SOL',
            
            # === STABLECOIN ARBITRAGE ===
            'USDC/USDT', 'USDT/USDC',
            
            # === LIQUID STAKING PAIRS ===
            'MSOL/SOL', 'JITOSOL/SOL', 'BSOL/SOL', 'STSOL/SOL',
            'MSOL/USDC', 'JITOSOL/USDC', 'BSOL/USDC',
            
            # === MEME COIN PAIRS (High volatility) ===
            'BONK/WIF', 'BOME/BONK', 'MEW/BONK', 'POPCAT/BONK', 'SLERF/BONK',
            'WIF/BOME', 'POPCAT/WIF', 'MEW/WIF',
        ]
        
        # More loan size options
        self.loan_sizes = [5000, 10000, 15000, 20000, 25000, 50000]
        self.min_profit_bps = int(os.environ.get('MIN_PROFIT_BPS', 10))
        self.daily_target = 1000
        
        # FAST scanning - 1 second interval
        self.scan_interval = float(os.environ.get('SCAN_INTERVAL', 1))
        
        # Executor
        self.jito_executor = None
        self.is_live = LIVE_TRADING
        
        if self.is_live:
            self._init_jito_executor()
        
        mode = "LIVE (JITO)" if self.is_live and self.jito_executor else "SIMULATION"
        logger.info(f"ULTRA-OPTIMIZED Flash Loan Monitor - MODE: {mode}")
        logger.info(f"   Pairs: {len(self.pairs)}")
        logger.info(f"   Min profit: {self.min_profit_bps} bps")
        logger.info(f"   Loan sizes: {len(self.loan_sizes)}")
        logger.info(f"   Scan speed: {self.scan_interval}s")
    
    def _init_jito_executor(self):
        """Initialize Jito executor for live trading"""
        try:
            from jito_flash_executor import JitoFlashLoanExecutor
            
            rpc_url = os.environ.get('SOLANA_RPC_URL')
            private_key = os.environ.get('SOLANA_PRIVATE_KEY')
            
            if not rpc_url or not private_key:
                logger.error("Missing SOLANA_RPC_URL or SOLANA_PRIVATE_KEY")
                logger.error("Live trading disabled - running in simulation mode")
                self.is_live = False
                return
            
            self.jito_executor = JitoFlashLoanExecutor(
                rpc_url=rpc_url,
                private_key=private_key,
                network="mainnet",
                min_tip_lamports=100_000,   # 0.0001 SOL
                max_tip_lamports=5_000_000  # 0.005 SOL
            )
            logger.info("Jito executor initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Jito executor: {e}")
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
    
    async def get_all_dex_prices(self, token_pair: str) -> Dict[str, Dict]:
        """Wrapper for DEX aggregator get_all_prices"""
        return await self.dex_aggregator.get_all_prices(token_pair)
    
    async def scan_for_opportunity(self) -> Optional[Dict]:
        """OPTIMIZED: Scan all pairs and loan sizes for best flash loan opportunity"""
        if not self.can_trade_today():
            return None
        
        best_opportunity = None
        best_net_profit = 0
        
        # Batch pairs for faster scanning
        for pair in self.pairs:
            try:
                prices = await self.get_all_dex_prices(pair)
                
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
        """Execute flash loan - Jito for live, simulation otherwise"""
        if self.is_live and self.jito_executor:
            return await self._execute_with_jito(opportunity)
        else:
            return await self._execute_simulation(opportunity)
    
    async def _execute_with_jito(self, opportunity: Dict) -> Dict:
        """Execute real flash loan via Jito"""
        try:
            logger.info(f"JITO EXECUTION: {opportunity['token_pair']}")
            
            result = await self.jito_executor.execute_arbitrage(
                opportunity=opportunity,
                loan_amount_usd=opportunity['loan_size_usd']
            )
            
            if result.get('success'):
                flash_loan_state['daily_trades_executed'] += 1
                
                logger.info(
                    f"JITO SUCCESS: {result['token_pair']} | "
                    f"Net: ${result.get('net_profit', 0):.2f} | "
                    f"Tip: {result.get('tip_paid', 0):.4f} SOL"
                )
            else:
                logger.warning(f"Jito trade failed: {result.get('error', 'Unknown')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Jito execution error: {e}")
            return {
                'success': False,
                'token_pair': opportunity['token_pair'],
                'error': str(e)
            }
    
    async def _execute_simulation(self, opportunity: Dict) -> Dict:
        """Simulate flash loan execution"""
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
                    f"SIMULATED: {result['token_pair']} | "
                    f"Loan: ${result['loan_amount']:,.0f} | "
                    f"Net: ${result['net_profit']:.2f}"
                )
                
                return result
            else:
                logger.warning(f"Simulation failed for {opportunity['token_pair']}")
                return {
                    'success': False,
                    'token_pair': opportunity['token_pair'],
                    'error': 'Simulation failed',
                    'mode': 'simulation'
                }
                
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            return {'success': False, 'error': str(e), 'mode': 'simulation'}
    
    async def save_trade_to_db(self, trade: Dict):
        """Save executed trade to database"""
        try:
            trade_doc = {
                'type': 'flash_loan',
                'token_pair': trade['token_pair'],
                'loan_amount': trade.get('loan_amount', 0),
                'gross_profit': trade.get('gross_profit', 0),
                'flash_loan_fee': trade.get('flash_loan_fee', 0),
                'gas_cost': trade.get('gas_cost', 0),
                'net_profit': trade.get('net_profit', 0),
                'profit_bps': trade.get('profit_bps', 0),
                'buy_dex': trade.get('buy_dex', 'unknown'),
                'sell_dex': trade.get('sell_dex', 'unknown'),
                'success': trade.get('success', True),
                'signature': trade.get('signature'),
                'bundle_id': trade.get('bundle_id'),
                'tip_paid': trade.get('tip_paid', 0),
                'mode': trade.get('mode', 'simulation'),
                'timestamp': trade.get('timestamp', datetime.now(timezone.utc)),
                'created_at': datetime.now(timezone.utc)
            }
            
            result = await self.db.flash_trades.insert_one(trade_doc)
            logger.info(f"Trade saved to database: {trade_doc['token_pair']} (ID: {result.inserted_id})")
            
        except Exception as e:
            logger.error(f"Error saving trade to DB: {e}")
    
    async def monitor_loop(self):
        """ULTRA-OPTIMIZED Main monitoring loop"""
        mode = "LIVE (JITO)" if self.is_live and self.jito_executor else "SIMULATION"
        logger.info(f"ULTRA-OPTIMIZED Monitor started - {mode}")
        logger.info(f"   Scanning {len(self.pairs)} pairs")
        logger.info(f"   Loan sizes: ${', '.join([f'{s:,}' for s in self.loan_sizes])}")
        logger.info(f"   Min profit: {self.min_profit_bps} bps")
        logger.info(f"   Scan interval: {self.scan_interval}s")
        
        scan_count = 0
        opportunities_today = 0
        trades_today = 0
        
        while True:
            try:
                if not self.can_trade_today():
                    await asyncio.sleep(60)
                    continue
                
                opportunity = await self.scan_for_opportunity()
                scan_count += 1
                
                if opportunity:
                    opportunities_today += 1
                    logger.info(
                        f"🎯 OPPORTUNITY #{opportunities_today}: {opportunity['token_pair']} | "
                        f"Loan: ${opportunity['loan_size_usd']:,} | "
                        f"Net: ${opportunity['net_profit']:.2f} | "
                        f"{opportunity['net_spread_bps']:.1f} bps"
                    )
                    
                    result = await self.execute_flash_loan(opportunity)
                    
                    if result.get('success'):
                        trades_today += 1
                        await self.save_trade_to_db(result)
                        logger.info(f"✅ Trade #{trades_today} SUCCESS | Daily: {flash_loan_state['daily_trades_executed']}")
                    else:
                        logger.warning(f"❌ Trade FAILED: {result.get('error', 'Unknown')}")
                    
                    # Brief pause after trade attempt
                    await asyncio.sleep(2)
                else:
                    # Log progress every 100 scans
                    if scan_count % 100 == 0:
                        logger.info(f"Scan #{scan_count} | Opportunities today: {opportunities_today} | Trades: {trades_today}")
                    
                    # Fast scan interval
                    await asyncio.sleep(self.scan_interval)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(2)
    
    async def close(self):
        """Cleanup"""
        await self.dex_aggregator.close()
        if self.jito_executor:
            await self.jito_executor.close()


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
        'mode': 'live_jito' if LIVE_TRADING else 'simulation'
    }
