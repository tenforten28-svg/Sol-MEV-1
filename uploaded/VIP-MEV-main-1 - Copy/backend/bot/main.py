"""
MAIN ENTRY POINT - WebSocket HFT Bot
=====================================
Phase 1: Real-time detection engine
NO polling - pure WebSocket event-driven
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone

from config import LOG_LEVEL, LOG_FORMAT, MIN_SPREAD_BPS, MIN_PROFIT_USD
from websocket_listener import start_listener, stop_listener, get_listener_stats
from pool_cache import get_pool_stats
from arb_detector import get_arbitrage_stats, set_opportunity_callback, ArbitrageOpportunity

# =============================================================================
# LOGGING SETUP
# =============================================================================
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('main')

# =============================================================================
# OPPORTUNITY HANDLER
# =============================================================================
async def handle_opportunity(opp: ArbitrageOpportunity):
    """
    Handle detected arbitrage opportunity
    Phase 1: Log only (execution comes in Phase 2)
    """
    logger.info("=" * 70)
    logger.info("⚡ ARBITRAGE OPPORTUNITY DETECTED")
    logger.info("=" * 70)
    logger.info(f"  Pair:      {opp.pair_name}")
    logger.info(f"  Buy DEX:   {opp.buy_dex} @ {opp.buy_price:.6f}")
    logger.info(f"  Sell DEX:  {opp.sell_dex} @ {opp.sell_price:.6f}")
    logger.info(f"  Spread:    {opp.spread_bps:.2f} bps")
    logger.info(f"  Size:      {opp.optimal_size:,} (raw units)")
    logger.info(f"  Profit:    ${opp.expected_profit_usd:.4f}")
    logger.info(f"  Slot:      {opp.slot}")
    logger.info("=" * 70)
    
    # Phase 2 will add execution here
    # await execute_arbitrage(opp)


def opportunity_callback(opp: ArbitrageOpportunity):
    """Sync callback wrapper for async handler"""
    # Create task for async handling
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(handle_opportunity(opp))
    except RuntimeError:
        # No running loop, log synchronously
        logger.info(f"⚡ ARB: {opp.pair_name} | {opp.spread_bps:.1f}bps | ${opp.expected_profit_usd:.4f}")


# =============================================================================
# STATS PRINTER
# =============================================================================
async def print_stats_loop():
    """Periodically print statistics"""
    while True:
        await asyncio.sleep(60)
        
        listener_stats = get_listener_stats()
        pool_stats = get_pool_stats()
        arb_stats = get_arbitrage_stats()
        
        logger.info("=" * 70)
        logger.info("STATS REPORT")
        logger.info("-" * 70)
        logger.info(f"  Runtime:        {arb_stats['runtime_hours']:.2f} hours")
        logger.info(f"  WS Messages:    {listener_stats['messages_received']:,}")
        logger.info(f"  Pool Updates:   {listener_stats['updates_processed']:,}")
        logger.info(f"  Pools Active:   {pool_stats['valid_pools']}/{pool_stats['total_pools']}")
        logger.info(f"  Opportunities:  {arb_stats['opportunities_detected']}")
        logger.info(f"  Opp/Hour:       {arb_stats['opportunities_per_hour']:.1f}")
        logger.info(f"  Total Profit:   ${arb_stats['total_profit_usd']:.4f}")
        logger.info("=" * 70)
        
        # Log individual pool prices
        for pool_name, pool_info in pool_stats.get('pools', {}).items():
            if pool_info['valid']:
                logger.info(f"  {pool_name}: {pool_info['dex']} @ {pool_info['price']:.6f} (age: {pool_info['age_ms']:.0f}ms)")


# =============================================================================
# GRACEFUL SHUTDOWN
# =============================================================================
shutdown_event = asyncio.Event()

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    logger.info("Shutdown signal received...")
    shutdown_event.set()


# =============================================================================
# MAIN
# =============================================================================
async def main():
    """Main entry point"""
    logger.info("=" * 70)
    logger.info("HFT WEBSOCKET BOT - PHASE 1: DETECTION ENGINE")
    logger.info("=" * 70)
    logger.info("Mode: Real-time WebSocket detection (NO polling)")
    logger.info(f"Config: Min spread {MIN_SPREAD_BPS}bps | Min profit ${MIN_PROFIT_USD}")
    logger.info("=" * 70)
    
    # Set up opportunity callback
    set_opportunity_callback(opportunity_callback)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start tasks
    listener_task = asyncio.create_task(start_listener())
    stats_task = asyncio.create_task(print_stats_loop())
    
    logger.info("Bot started. Listening for opportunities...")
    logger.info("Press Ctrl+C to stop.")
    
    try:
        # Wait for shutdown signal
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        # Cleanup
        logger.info("Shutting down...")
        await stop_listener()
        listener_task.cancel()
        stats_task.cancel()
        
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
        
        try:
            await stats_task
        except asyncio.CancelledError:
            pass
        
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
