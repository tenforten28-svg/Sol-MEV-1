#!/usr/bin/env python3
"""
Standalone Meme Coin Arbitrage Bot
Runs independently of web server
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path

from meme_risk_manager import MemeRiskManager
from meme_price_connector import MemePriceConnector
from meme_arbitrage_detector import MemeArbitrageDetector
from liquidity_verifier import LiquidityVerifier

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
meme_balance = 10.0
meme_active_opportunities = []
risk_manager = None
price_connector = None
arbitrage_detector = None
liquidity_verifier = None
db = None


async def initialize():
    """Initialize bot components"""
    global risk_manager, price_connector, arbitrage_detector, liquidity_verifier, db
    
    # Connect to MongoDB
    mongo_url = os.environ['MONGO_URL']
    client = AsyncIOMotorClient(mongo_url)
    db = client[os.environ['DB_NAME']]
    
    # Initialize components
    risk_manager = MemeRiskManager(
        initial_capital=10.0,
        reserve_percentage=60.0,
        max_trade_percentage=1.0
    )
    
    price_connector = MemePriceConnector()
    liquidity_verifier = LiquidityVerifier()
    arbitrage_detector = MemeArbitrageDetector(
        price_connector=price_connector,
        liquidity_verifier=liquidity_verifier,
        min_profit_bps=15
    )
    
    logger.info("🚀 Meme Coin Bot initialized")
    logger.info(f"   Initial pool: ${meme_balance} SOL")


async def monitor_meme_opportunities():
    """Monitor and execute meme coin arbitrage"""
    global meme_balance, meme_active_opportunities
    
    logger.info("👀 Starting meme coin monitoring...")
    
    while True:
        try:
            # Check if we can trade
            can_trade, reason = risk_manager.can_trade()
            
            if not can_trade:
                logger.debug(f"Meme trading paused: {reason}")
                await asyncio.sleep(10)
                continue
            
            # Scan for opportunities
            opportunities = await arbitrage_detector.scan_all_opportunities()
            
            # Update active opportunities
            meme_active_opportunities = opportunities
            
            # Execute best opportunity
            if opportunities:
                best = max(opportunities, key=lambda x: x.get('net_profit_bps', 0))
                
                # Approve trade with risk manager
                is_approved, trade_size, reason = risk_manager.approve_trade(meme_balance, best)
                
                if is_approved:
                    # Use approved trade size
                    max_amount = trade_size
                    
                    # Simulate execution
                    if best['type'] == 'simple':
                        profit_usd = (best['net_profit_bps'] / 10000) * max_amount
                    else:
                        profit_usd = (best['net_profit_bps'] / 10000) * max_amount
                    
                    # Record trade
                    trade_doc = {
                        'token_pair': best.get('pair', best.get('path', 'UNKNOWN')),
                        'type': best['type'],
                        'buy_dex': best.get('buy_dex', best.get('leg1', {}).get('dex', '')),
                        'sell_dex': best.get('sell_dex', best.get('leg2', {}).get('dex', '')),
                        'buy_amount': max_amount,
                        'sell_amount': max_amount + profit_usd,
                        'profit': profit_usd,
                        'profit_percentage': best['net_profit_bps'] / 100,
                        'status': 'simulated',
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                    }
                    
                    await db.meme_trades.insert_one(trade_doc)
                    
                    # Update balance and risk manager
                    meme_balance += profit_usd
                    risk_manager.record_trade_result(True, profit_usd)
                    
                    logger.info(
                        f"🎯 MEME TRADE: {trade_doc['token_pair']} | "
                        f"Profit: ${profit_usd:.4f} ({best['net_profit_bps']:.1f} bps)"
                    )
                
                # Save opportunity to database
                opp_doc = {
                    **best,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }
                await db.meme_opportunities.insert_one(opp_doc)
            
            await asyncio.sleep(5)
            
        except Exception as e:
            logger.error(f"Error in meme monitoring: {e}")
            await asyncio.sleep(5)


async def main():
    """Main entry point"""
    try:
        await initialize()
        
        # Start monitoring
        monitor_task = asyncio.create_task(monitor_meme_opportunities())
        
        logger.info("✅ Meme coin bot running independently")
        logger.info("   Press Ctrl+C to stop")
        
        # Wait forever
        await monitor_task
        
    except KeyboardInterrupt:
        logger.info("🛑 Stopping meme bot...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Meme bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
