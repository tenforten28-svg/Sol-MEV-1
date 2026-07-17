"""
Flash Loan API Endpoints
Provides comprehensive monitoring data for flash loan dashboard
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

# Create router
flash_router = APIRouter(prefix="/api/flash", tags=["flash_loan"])

# Models
class FlashLoanStats(BaseModel):
    total_opportunities: int
    high_quality_opportunities: int  # >30 bps
    executed_trades: int
    target_trades: int = 15
    success_rate: float
    total_profit: float
    avg_profit_per_trade: float
    gas_costs: float
    net_profit: float
    simulation_failures: int
    best_trade: Optional[Dict]
    worst_trade: Optional[Dict]
    uptime_hours: float


class FlashLoanTrade(BaseModel):
    token_pair: str
    loan_amount: float
    net_profit: float
    profit_bps: float
    success: bool
    timestamp: datetime
    signature: Optional[str]


class FlashLoanOpportunity(BaseModel):
    token_pair: str
    loan_size_usd: float
    net_profit: float
    profit_after_flash_loan_bps: float
    buy_dex: str
    sell_dex: str
    timestamp: datetime


# Global stats tracking (in production, use Redis or database)
flash_stats = {
    'start_time': datetime.now(timezone.utc),
    'total_opportunities': 0,
    'high_quality_opportunities': 0,
    'executed_trades': 0,
    'successful_trades': 0,
    'simulation_failures': 0,
    'total_profit': 0.0,
    'total_gas_costs': 0.0,
    'best_trade': None,
    'worst_trade': None,
    'trades': [],
    'opportunities': [],
}


@flash_router.get("/stats", response_model=FlashLoanStats)
async def get_flash_loan_stats():
    """
    Get comprehensive flash loan bot statistics (from database)
    Optimized for 10-15 high-quality trades per day
    """
    from server import db
    
    # Fetch ALL flash loan trades from database (no limit)
    trades_cursor = db.flash_trades.find(
        {"type": "flash_loan"},
        {"_id": 0}
    )
    trades = await trades_cursor.to_list(length=None)  # No limit - fetch all trades
    
    # Calculate uptime
    uptime = (datetime.now(timezone.utc) - flash_stats['start_time']).total_seconds() / 3600
    
    # Calculate stats from database trades
    successful_trades = [t for t in trades if t.get('success', True)]
    executed_trades = len(successful_trades)
    
    # Calculate totals
    total_profit = sum(t.get('gross_profit', 0) for t in successful_trades)
    total_gas_costs = sum(t.get('gas_cost', 0) for t in successful_trades)
    net_profit = sum(t.get('net_profit', 0) for t in successful_trades)
    
    # Calculate success rate (assume high since these are simulations)
    simulation_failures = flash_stats['simulation_failures']
    total_attempts = executed_trades + simulation_failures
    success_rate = (executed_trades / total_attempts * 100) if total_attempts > 0 else 100.0
    
    # Calculate average profit per trade
    avg_profit = net_profit / executed_trades if executed_trades > 0 else 0
    
    # Find best and worst trades
    best_trade = None
    worst_trade = None
    if successful_trades:
        best = max(successful_trades, key=lambda x: x.get('net_profit', 0))
        worst = min(successful_trades, key=lambda x: x.get('net_profit', 0))
        best_trade = {
            'pair': best.get('token_pair', 'N/A'),
            'profit': best.get('net_profit', 0),
            'bps': best.get('profit_bps', 0)
        }
        worst_trade = {
            'pair': worst.get('token_pair', 'N/A'),
            'profit': worst.get('net_profit', 0),
            'bps': worst.get('profit_bps', 0)
        }
    
    # Count high-quality opportunities (>30 bps)
    high_quality_count = len([t for t in successful_trades if t.get('profit_bps', 0) >= 30])
    
    return FlashLoanStats(
        total_opportunities=len(trades),  # All scanned opportunities
        high_quality_opportunities=high_quality_count,
        executed_trades=executed_trades,
        target_trades=0,  # 0 = Unlimited trading (no daily limit)
        success_rate=success_rate,
        total_profit=total_profit,
        avg_profit_per_trade=avg_profit,
        gas_costs=total_gas_costs,
        net_profit=net_profit,
        simulation_failures=simulation_failures,
        best_trade=best_trade,
        worst_trade=worst_trade,
        uptime_hours=uptime,
    )


@flash_router.get("/trades", response_model=List[FlashLoanTrade])
async def get_flash_loan_trades(limit: int = 20):
    """
    Get recent flash loan trades (from database)
    """
    from server import db
    
    # Fetch from MongoDB, sorted by timestamp (most recent first)
    trades_cursor = db.flash_trades.find(
        {"type": "flash_loan"},
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit)
    
    trades = await trades_cursor.to_list(length=limit)
    return trades


@flash_router.get("/opportunities", response_model=List[FlashLoanOpportunity])
async def get_flash_loan_opportunities(limit: int = 10, min_quality_bps: int = 20):
    """
    Get current high-quality flash loan opportunities
    Only returns opportunities above quality threshold
    """
    # Filter for high-quality opportunities
    high_quality = [
        opp for opp in flash_stats['opportunities']
        if opp.get('profit_after_flash_loan_bps', 0) >= min_quality_bps
    ]
    
    # Sort by profit
    high_quality.sort(key=lambda x: x.get('net_profit', 0), reverse=True)
    
    return high_quality[:limit]


@flash_router.post("/opportunity/detected")
async def report_opportunity_detected(
    token_pair: str,
    loan_size: float,
    net_profit: float,
    profit_bps: float,
    buy_dex: str,
    sell_dex: str
):
    """
    Report a detected opportunity (called by bot)
    """
    flash_stats['total_opportunities'] += 1
    
    # Track high-quality opportunities (>30 bps after fees)
    if profit_bps >= 30:
        flash_stats['high_quality_opportunities'] += 1
    
    # Add to opportunities list
    opportunity = {
        'token_pair': token_pair,
        'loan_size_usd': loan_size,
        'net_profit': net_profit,
        'profit_after_flash_loan_bps': profit_bps,
        'buy_dex': buy_dex,
        'sell_dex': sell_dex,
        'timestamp': datetime.now(timezone.utc),
    }
    
    flash_stats['opportunities'].append(opportunity)
    
    # Keep only recent opportunities (last 100)
    if len(flash_stats['opportunities']) > 100:
        flash_stats['opportunities'] = flash_stats['opportunities'][-100:]
    
    logger.info(
        f"💎 Flash opportunity detected: {token_pair} | "
        f"${net_profit:.2f} ({profit_bps:.1f} bps)"
    )
    
    return {"status": "recorded"}


@flash_router.post("/trade/executed")
async def report_trade_executed(
    token_pair: str,
    loan_amount: float,
    net_profit: float,
    profit_bps: float,
    success: bool,
    gas_cost: float = 0.0,
    signature: Optional[str] = None
):
    """
    Report an executed trade (called by bot)
    """
    if success:
        flash_stats['successful_trades'] += 1
        flash_stats['total_profit'] += net_profit
        flash_stats['total_gas_costs'] += gas_cost
        
        # Track best/worst trades
        if not flash_stats['best_trade'] or net_profit > flash_stats['best_trade']['profit']:
            flash_stats['best_trade'] = {
                'pair': token_pair,
                'profit': net_profit,
                'bps': profit_bps
            }
        
        if not flash_stats['worst_trade'] or net_profit < flash_stats['worst_trade']['profit']:
            flash_stats['worst_trade'] = {
                'pair': token_pair,
                'profit': net_profit,
                'bps': profit_bps
            }
    
    flash_stats['executed_trades'] += 1
    
    # Add to trades list
    trade = {
        'token_pair': token_pair,
        'loan_amount': loan_amount,
        'net_profit': net_profit,
        'profit_bps': profit_bps,
        'success': success,
        'timestamp': datetime.now(timezone.utc),
        'signature': signature,
    }
    
    flash_stats['trades'].append(trade)
    
    # Keep only recent trades (last 100)
    if len(flash_stats['trades']) > 100:
        flash_stats['trades'] = flash_stats['trades'][-100:]
    
    status_emoji = "✅" if success else "❌"
    logger.info(
        f"{status_emoji} Flash trade {'' if success else 'FAILED: '}"
        f"{token_pair} | ${net_profit:.2f} | TX: {signature[:16] if signature else 'N/A'}..."
    )
    
    return {"status": "recorded"}


@flash_router.post("/simulation/failed")
async def report_simulation_failed(token_pair: str, error: str):
    """
    Report a failed simulation (called by bot)
    """
    flash_stats['simulation_failures'] += 1
    
    logger.warning(f"⚠️  Simulation failed for {token_pair}: {error}")
    
    return {"status": "recorded"}


@flash_router.get("/daily/summary")
async def get_daily_summary():
    """
    Get daily summary statistics (from database)
    """
    from server import db
    from datetime import datetime, timezone
    
    today = datetime.now(timezone.utc).date()
    
    # Fetch today's trades from database
    start_of_day = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
    
    # Query for both datetime objects and ISO string timestamps (for backward compatibility)
    trades_cursor = db.flash_trades.find({
        "type": "flash_loan",
        "success": True,
        "$or": [
            # For new trades with datetime objects
            {"timestamp": {"$gte": start_of_day, "$lte": end_of_day}},
            # For old trades with ISO strings - match date prefix
            {"timestamp": {"$regex": f"^{today.isoformat()}"}}
        ]
    }, {"_id": 0})
    
    today_trades = await trades_cursor.to_list(length=500)  # Increased limit for higher daily target
    
    trades_count = len(today_trades)
    profit_today = sum(t.get('net_profit', 0) for t in today_trades)
    avg_profit_today = profit_today / trades_count if trades_count > 0 else 0
    
    # No daily limit - unlimited trading
    return {
        'date': today.isoformat(),
        'trades_executed': trades_count,
        'profit_today': profit_today,
        'avg_profit': avg_profit_today,
        'unlimited': True,  # No daily limit
    }


@flash_router.post("/config/target")
async def update_target_trades(target: int):
    """
    Update daily trade target
    """
    if target < 1 or target > 100:
        return {"error": "Target must be between 1 and 100"}
    
    # In production, save to database
    logger.info(f"Updated daily trade target to {target}")
    
    return {"target": target, "status": "updated"}


@flash_router.delete("/reset")
async def reset_stats():
    """
    Reset all statistics (use with caution!)
    """
    flash_stats['total_opportunities'] = 0
    flash_stats['high_quality_opportunities'] = 0
    flash_stats['executed_trades'] = 0
    flash_stats['successful_trades'] = 0
    flash_stats['simulation_failures'] = 0
    flash_stats['total_profit'] = 0.0
    flash_stats['total_gas_costs'] = 0.0
    flash_stats['best_trade'] = None
    flash_stats['worst_trade'] = None
    flash_stats['trades'] = []
    flash_stats['opportunities'] = []
    flash_stats['start_time'] = datetime.now(timezone.utc)
    
    logger.warning("⚠️  Flash loan stats reset!")
    
    return {"status": "reset"}


@flash_router.get("/daily/history")
async def get_daily_history(days: int = 7):
    """
    Get historical daily summaries for the past N days
    Shows trades executed, success rate, avg profit, and total profit per day
    """
    from server import db
    from datetime import timedelta
    
    summaries = []
    today = datetime.now(timezone.utc).date()
    
    for i in range(days):
        date = today - timedelta(days=i)
        start_of_day = datetime.combine(date, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_of_day = datetime.combine(date, datetime.max.time()).replace(tzinfo=timezone.utc)
        
        # Query for both datetime objects and ISO string timestamps
        trades_cursor = db.flash_trades.find({
            "type": "flash_loan",
            "$or": [
                {"timestamp": {"$gte": start_of_day, "$lte": end_of_day}},
                {"timestamp": {"$regex": f"^{date.isoformat()}"}}
            ]
        }, {"_id": 0, "success": 1, "net_profit": 1})
        
        day_trades = await trades_cursor.to_list(length=10000)
        
        if day_trades:
            successful = [t for t in day_trades if t.get('success', True)]
            total_trades = len(day_trades)
            successful_trades = len(successful)
            total_profit = sum(t.get('net_profit', 0) for t in successful)
            avg_profit = total_profit / successful_trades if successful_trades > 0 else 0
            success_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0
            
            summaries.append({
                'date': date.isoformat(),
                'total_trades': total_trades,
                'successful_trades': successful_trades,
                'failed_trades': total_trades - successful_trades,
                'success_rate': round(success_rate, 2),
                'total_profit': round(total_profit, 2),
                'avg_profit': round(avg_profit, 2),
            })
        else:
            summaries.append({
                'date': date.isoformat(),
                'total_trades': 0,
                'successful_trades': 0,
                'failed_trades': 0,
                'success_rate': 0,
                'total_profit': 0,
                'avg_profit': 0,
            })
    
    return summaries

