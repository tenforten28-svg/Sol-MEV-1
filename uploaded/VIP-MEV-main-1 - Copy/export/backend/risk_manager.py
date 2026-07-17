from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class RiskManager:
    """Manages trading risk and capital allocation"""
    
    def __init__(
        self,
        starting_capital: float,
        reserve_percentage: float,
        max_trade_percentage: float,
        max_daily_loss_percentage: float,
        max_consecutive_failures: int,
        cooldown_period_seconds: int
    ):
        self.starting_capital = starting_capital
        self.current_capital = starting_capital
        self.reserve_percentage = reserve_percentage
        self.max_trade_percentage = max_trade_percentage
        self.max_daily_loss_percentage = max_daily_loss_percentage
        self.max_consecutive_failures = max_consecutive_failures
        self.cooldown_period_seconds = cooldown_period_seconds
        
        # Tracking
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_failures = 0
        self.last_trade_time = None
        self.cooldown_until = None
        self.daily_reset_time = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
    def get_available_capital(self) -> float:
        """Calculate available capital for trading (excluding reserve)"""
        return self.current_capital * (1 - self.reserve_percentage / 100)
    
    def get_max_trade_size(self) -> float:
        """Calculate maximum trade size based on risk parameters"""
        available = self.get_available_capital()
        max_per_trade = self.current_capital * (self.max_trade_percentage / 100)
        return min(available, max_per_trade)
    
    def can_trade(self) -> tuple[bool, Optional[str]]:
        """Check if trading is allowed based on risk controls"""
        
        # Check if in cooldown period
        if self.cooldown_until and datetime.now(timezone.utc) < self.cooldown_until:
            remaining = (self.cooldown_until - datetime.now(timezone.utc)).seconds
            return False, f"In cooldown period. {remaining}s remaining"
        
        # Check daily loss limit
        daily_loss_percentage = (self.daily_pnl / self.starting_capital) * 100
        if daily_loss_percentage < -self.max_daily_loss_percentage:
            return False, f"Daily loss limit exceeded: {daily_loss_percentage:.2f}%"
        
        # Check consecutive failures
        if self.consecutive_failures >= self.max_consecutive_failures:
            return False, f"Max consecutive failures reached: {self.consecutive_failures}"
        
        # Check capital erosion
        capital_loss_percentage = ((self.starting_capital - self.current_capital) / self.starting_capital) * 100
        if capital_loss_percentage > 20:  # Lost more than 20% of capital
            return False, f"Capital erosion too high: {capital_loss_percentage:.2f}%"
        
        return True, None
    
    def evaluate_opportunity(
        self, 
        opportunity: Dict,
        max_slippage_tolerance: float
    ) -> tuple[bool, Optional[str]]:
        """Evaluate if an opportunity meets risk criteria"""
        
        # Check if trading is allowed
        can_trade, reason = self.can_trade()
        if not can_trade:
            return False, reason
        
        # Check slippage
        buy_slippage = opportunity['buy_costs']['slippage_percentage']
        sell_slippage = opportunity['sell_costs']['slippage_percentage']
        
        if buy_slippage > max_slippage_tolerance * 100:
            return False, f"Buy slippage too high: {buy_slippage:.3f}%"
        
        if sell_slippage > max_slippage_tolerance * 100:
            return False, f"Sell slippage too high: {sell_slippage:.3f}%"
        
        # Check liquidity
        min_liquidity = opportunity['trade_amount'] * 10  # Need 10x trade size in liquidity
        if opportunity['liquidity_buy'] < min_liquidity:
            return False, f"Insufficient buy liquidity: ${opportunity['liquidity_buy']:.2f}"
        
        if opportunity['liquidity_sell'] < min_liquidity:
            return False, f"Insufficient sell liquidity: ${opportunity['liquidity_sell']:.2f}"
        
        # Check if net profit justifies the risk
        if opportunity['net_profit_amount'] < 0.001:  # Less than $0.001 profit
            return False, f"Profit too small: ${opportunity['net_profit_amount']:.4f}"
        
        return True, None
    
    def record_trade(self, profit_loss: float, success: bool):
        """Record trade result and update metrics"""
        
        # Reset daily stats if new day
        now = datetime.now(timezone.utc)
        if now >= self.daily_reset_time + timedelta(days=1):
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.daily_reset_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Update capital and daily P&L
        self.current_capital += profit_loss
        self.daily_pnl += profit_loss
        self.daily_trades += 1
        self.last_trade_time = now
        
        # Update consecutive failures
        if success:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            
            # Trigger cooldown if too many failures
            if self.consecutive_failures >= self.max_consecutive_failures:
                self.cooldown_until = now + timedelta(seconds=self.cooldown_period_seconds)
                logger.warning(
                    f"Cooldown triggered. {self.consecutive_failures} consecutive failures. "
                    f"Resuming at {self.cooldown_until}"
                )
    
    def get_stats(self) -> Dict:
        """Get current risk and performance statistics"""
        
        capital_change = self.current_capital - self.starting_capital
        capital_change_pct = (capital_change / self.starting_capital) * 100
        
        return {
            "starting_capital": self.starting_capital,
            "current_capital": self.current_capital,
            "capital_change": capital_change,
            "capital_change_percentage": capital_change_pct,
            "available_capital": self.get_available_capital(),
            "reserved_capital": self.current_capital * (self.reserve_percentage / 100),
            "max_trade_size": self.get_max_trade_size(),
            "daily_pnl": self.daily_pnl,
            "daily_pnl_percentage": (self.daily_pnl / self.starting_capital) * 100,
            "daily_trades": self.daily_trades,
            "consecutive_failures": self.consecutive_failures,
            "in_cooldown": bool(self.cooldown_until and datetime.now(timezone.utc) < self.cooldown_until),
            "can_trade": self.can_trade()[0]
        }
