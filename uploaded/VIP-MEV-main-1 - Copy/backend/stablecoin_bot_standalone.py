#!/usr/bin/env python3
"""
Standalone Stablecoin Arbitrage Bot
Runs independently of web server
"""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path

from dex_connectors import DEXAggregator
from risk_manager import RiskManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Global state
initial_balance = 50.0
current_balance = initial_balance
risk_manager = None
dex_aggregator = None
db = None


async def initialize():
    """Initialize bot components"""
    global risk_manager, dex_aggregator, db
    
    # Connect to MongoDB
    mongo_url = os.environ['MONGO_URL']
    client = AsyncIOMotorClient(mongo_url)
    db = client[os.environ['DB_NAME']]
    
    # Initialize risk manager
    risk_manager = RiskManager(
        starting_capital=initial_balance,
        reserve_percentage=float(os.getenv('RESERVE_PERCENTAGE', 20)),
        max_trade_percentage=float(os.getenv('MAX_TRADE_PERCENTAGE', 3)),
        max_daily_loss_percentage=10.0,
        max_consecutive_failures=5,
        cooldown_period_seconds=300
    )
    
    # Initialize DEX aggregator
    dex_aggregator = DEXAggregator()
    
    logger.info("🚀 Stablecoin Bot initialized")
    logger.info(f"   Initial balance: ${initial_balance}")
    logger.info(f"   Reserve: {risk_manager.reserve_percentage}%")


async def cleanup_stale_opportunities():
    """Remove old opportunities from database"""
    while True:
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=5)
            result = await db.opportunities.delete_many({
                "timestamp": {"$lt": cutoff_time}
            })
            
            if result.deleted_count > 0:
                logger.info(f"🧹 Cleaned up {result.deleted_count} stale opportunities")
            
        except Exception as e:
            logger.error(f"Error in cleanup_stale_opportunities: {e}")
        
        await asyncio.sleep(60)


async def monitor_arbitrage():
    """Main arbitrage monitoring loop"""
    global current_balance
    
    logger.info("👀 Starting arbitrage monitoring...")
    
    while True:
        try:
            # Get configuration
            config = await db.config.find_one({}, {"_id": 0})
            if not config:
                await asyncio.sleep(5)
                continue
            
            pairs = config.get('monitored_pairs', ['SOL/USDC', 'RAY/USDC', 'ORCA/USDC'])
            auto_execute = config.get('auto_execute', True)
            
            # Check if trading is allowed
            can_trade, reason = risk_manager.can_trade()
            if not can_trade:
                logger.debug(f"Trading paused: {reason}")
                await asyncio.sleep(10)
                continue
            
            # Scan each pair
            for pair in pairs:
                try:
                    # Get prices from all DEXs
                    prices = await dex_aggregator.get_all_prices(pair)
                    
                    if len(prices) < 2:
                        continue
                    
                    # Find arbitrage opportunity
                    opportunity = dex_aggregator.find_arbitrage_opportunity(
                        prices=prices,
                        max_trade_amount=risk_manager.get_max_trade_size(),
                        min_spread=float(os.getenv('MIN_SPREAD_AFTER_COSTS', 0.0005)),
                        max_slippage=0.0015
                    )
                    
                    if opportunity:
                        # Check if we can trade
                        can_trade_check, reason = risk_manager.can_trade()
                        if not can_trade_check:
                            logger.debug(f"Trade rejected: {reason}")
                            continue
                        
                        # Save opportunity
                        opp_doc = {
                            **opportunity,
                            'timestamp': datetime.now(timezone.utc),
                            'executed': False,
                            'type': 'stable'
                        }
                        opp_doc['timestamp'] = opp_doc['timestamp'].isoformat()
                        await db.opportunities.insert_one(opp_doc)
                        
                        # Auto-execute if enabled
                        if auto_execute:
                            # Simulate execution
                            profit = opportunity['net_profit_amount']
                            
                            # Record trade
                            trade_doc = {
                                'id': f"trade_{datetime.now().timestamp()}",
                                'token_pair': opportunity['token_pair'],
                                'dex_buy': opportunity['dex_buy'],
                                'dex_sell': opportunity['dex_sell'],
                                'buy_price': opportunity['buy_price'],
                                'sell_price': opportunity['sell_price'],
                                'amount': opportunity['amount'],
                                'profit': profit,
                                'timestamp': datetime.now(timezone.utc).isoformat(),
                                'type': 'stable'
                            }
                            
                            await db.trades.insert_one(trade_doc)
                            
                            # Update risk manager
                            risk_manager.record_trade(profit, True)
                            current_balance += profit
                            
                            # Mark opportunity as executed
                            await db.opportunities.update_one(
                                {'timestamp': opp_doc['timestamp']},
                                {'$set': {'executed': True}}
                            )
                            
                            logger.info(
                                f"✅ AUTO-EXECUTED: {opportunity['token_pair']} | "
                                f"Profit: ${profit:.4f} | "
                                f"Balance: ${current_balance:.2f}"
                            )
                
                except Exception as e:
                    logger.error(f"Error processing {pair}: {e}")
                    continue
            
            await asyncio.sleep(2.5)
            
        except Exception as e:
            logger.error(f"Error in monitor_arbitrage: {e}")
            await asyncio.sleep(5)


async def main():
    """Main entry point"""
    try:
        await initialize()
        
        # Start background tasks
        cleanup_task = asyncio.create_task(cleanup_stale_opportunities())
        monitor_task = asyncio.create_task(monitor_arbitrage())
        
        logger.info("✅ Stablecoin bot running independently")
        logger.info("   Press Ctrl+C to stop")
        
        # Wait forever
        await asyncio.gather(cleanup_task, monitor_task)
        
    except KeyboardInterrupt:
        logger.info("🛑 Stopping stablecoin bot...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        if dex_aggregator:
            await dex_aggregator.close()
        logger.info("Stablecoin bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
