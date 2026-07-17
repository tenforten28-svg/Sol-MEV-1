#!/usr/bin/env python3
"""
Standalone Flash Loan Arbitrage Bot
Runs independently of web server
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path

from flash_loan_monitor_integrated import IntegratedFlashLoanMonitor
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
flash_monitor = None
risk_manager = None
db = None


async def initialize():
    """Initialize bot components"""
    global flash_monitor, risk_manager, db
    
    # Connect to MongoDB
    mongo_url = os.environ['MONGO_URL']
    client = AsyncIOMotorClient(mongo_url)
    db = client[os.environ['DB_NAME']]
    
    # Initialize risk manager (for validation)
    risk_manager = RiskManager(
        starting_capital=50.0,
        reserve_percentage=20.0,
        max_trade_percentage=3.0,
        max_daily_loss_percentage=10.0,
        max_consecutive_failures=5,
        cooldown_period_seconds=300
    )
    
    # Initialize flash loan monitor
    flash_monitor = IntegratedFlashLoanMonitor(db, risk_manager)
    
    logger.info("⚡ Flash Loan Bot initialized")
    logger.info(f"   Target: {flash_monitor.daily_target} trades/day")
    logger.info(f"   Min profit: {flash_monitor.min_profit_bps} bps")


async def main():
    """Main entry point"""
    try:
        await initialize()
        
        # Start monitoring
        monitor_task = asyncio.create_task(flash_monitor.monitor_loop())
        
        logger.info("✅ Flash loan bot running independently")
        logger.info("   Press Ctrl+C to stop")
        
        # Wait forever
        await monitor_task
        
    except KeyboardInterrupt:
        logger.info("🛑 Stopping flash loan bot...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        if flash_monitor:
            await flash_monitor.close()
        logger.info("Flash loan bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
