"""
Meme Coin Risk Manager
Separate risk management for volatile meme coin trading
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple
import logging

logger = logging.getLogger(__name__)

class MemeRiskManager:
    """
    Conservative risk management specifically for meme coin trading
    Separate from stable coin trading to prevent cross-contamination
    """
    
    def __init__(
        self,
        initial_capital: float = 10.0,
        reserve_percentage: float = 60.0,
        max_trade_percentage: float = 1.0,
        max_daily_loss_percentage: float = 5.0,
        min_liquidity_usd: float = 100000.0,
        max_slippage_bps: int = 30,
        min_profit_threshold_bps: int = 15,
        cooldown_after_failures: int = 3,
        cooldown_duration_minutes: int = 15
    ):
        # Capital management
        self.initial_capital = initial_capital
        self.reserve_percentage = reserve_percentage
        self.max_trade_percentage = max_trade_percentage
        
        # Risk limits
        self.max_daily_loss_percentage = max_daily_loss_percentage
        self.min_liquidity_usd = min_liquidity_usd
        self.max_slippage_bps = max_slippage_bps
        self.min_profit_threshold_bps = min_profit_threshold_bps
        
        # Failure tracking
        self.cooldown_after_failures = cooldown_after_failures
        self.cooldown_duration_minutes = cooldown_duration_minutes
        self.consecutive_failures = 0
        self.last_failure_time = None
        self.cooldown_until = None
        
        # Performance tracking
        self.daily_pnl = 0.0
        self.last_reset = datetime.now(timezone.utc)
        self.total_trades = 0
        self.successful_trades = 0
        
        logger.info(f"MemeRiskManager initialized: {initial_capital} SOL capital, "
                   f"{reserve_percentage}% reserve, {max_trade_percentage}% max trade")
    
    def get_available_capital(self, current_balance: float) -> float:
        """
        Calculate available capital for meme trading
        More conservative than stable coin trading
        """
        reserved = current_balance * (self.reserve_percentage / 100)
        available = current_balance - reserved
        return max(0, available)
    
    def calculate_trade_size(self, current_balance: float, opportunity_profit_pct: float) -> float:
        """
        Calculate safe trade size for meme coin
        Conservative sizing due to volatility
        """
        available = self.get_available_capital(current_balance)
        
        # Base position size
        max_size = current_balance * (self.max_trade_percentage / 100)
        
        # Scale down for lower profit opportunities
        if opportunity_profit_pct < self.min_profit_threshold_bps / 100:
            return 0.0  # Don't trade below minimum threshold
        
        # Use smaller of available capital or max position
        trade_size = min(available, max_size)
        
        # Additional safety: never exceed 40% of available capital
        safety_cap = available * 0.4
        trade_size = min(trade_size, safety_cap)
        
        return max(0, trade_size)
    
    def check_liquidity_requirement(self, liquidity_usd: float) -> Tuple[bool, str]:
        """
        Verify liquidity meets minimum requirement
        Critical for meme coins to prevent price impact
        """
        if liquidity_usd < self.min_liquidity_usd:
            return False, f"Insufficient liquidity: ${liquidity_usd:,.0f} < ${self.min_liquidity_usd:,.0f}"
        return True, "Liquidity OK"
    
    def check_slippage(self, expected_slippage_bps: float) -> Tuple[bool, str]:
        """Check if slippage is within acceptable range"""
        if expected_slippage_bps > self.max_slippage_bps:
            return False, f"Slippage too high: {expected_slippage_bps:.1f} bps > {self.max_slippage_bps} bps"
        return True, "Slippage acceptable"
    
    def check_profit_threshold(self, profit_bps: float) -> Tuple[bool, str]:
        """Verify profit meets minimum threshold"""
        if profit_bps < self.min_profit_threshold_bps:
            return False, f"Profit below threshold: {profit_bps:.1f} bps < {self.min_profit_threshold_bps} bps"
        return True, "Profit acceptable"
    
    def check_daily_loss_limit(self, current_balance: float) -> Tuple[bool, str]:
        """Check if daily loss limit exceeded"""
        # Reset daily PnL if new day
        now = datetime.now(timezone.utc)
        if (now - self.last_reset).days >= 1:
            self.daily_pnl = 0.0
            self.last_reset = now
        
        # Calculate daily loss percentage
        daily_loss_pct = abs(self.daily_pnl / self.initial_capital) * 100
        
        if self.daily_pnl < 0 and daily_loss_pct >= self.max_daily_loss_percentage:
            return False, f"Daily loss limit reached: {daily_loss_pct:.2f}% >= {self.max_daily_loss_percentage}%"
        
        return True, "Daily loss limit OK"
    
    def can_trade(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed (not in cooldown)
        """
        if self.cooldown_until:
            now = datetime.now(timezone.utc)
            if now < self.cooldown_until:
                remaining = (self.cooldown_until - now).total_seconds() / 60
                return False, f"In cooldown for {remaining:.1f} more minutes"
            else:
                # Cooldown expired, reset
                self.cooldown_until = None
                self.consecutive_failures = 0
        
        return True, "Trading allowed"
    
    def approve_trade(
        self,
        current_balance: float,
        opportunity: Dict
    ) -> Tuple[bool, float, str]:
        """
        Comprehensive trade approval for meme coins
        
        Returns:
            (approved, trade_size, reason)
        """
        # Check cooldown
        can_trade, reason = self.can_trade()
        if not can_trade:
            return False, 0.0, reason
        
        # Check daily loss limit
        loss_ok, reason = self.check_daily_loss_limit(current_balance)
        if not loss_ok:
            return False, 0.0, reason
        
        # Check liquidity
        liquidity_ok, reason = self.check_liquidity_requirement(
            opportunity.get('liquidity_usd', 0)
        )
        if not liquidity_ok:
            return False, 0.0, reason
        
        # Check slippage
        slippage_ok, reason = self.check_slippage(
            opportunity.get('slippage_bps', 999)
        )
        if not slippage_ok:
            return False, 0.0, reason
        
        # Check profit threshold
        profit_ok, reason = self.check_profit_threshold(
            opportunity.get('net_profit_bps', 0)
        )
        if not profit_ok:
            return False, 0.0, reason
        
        # Calculate trade size
        trade_size = self.calculate_trade_size(
            current_balance,
            opportunity.get('net_profit_bps', 0) / 100
        )
        
        if trade_size <= 0:
            return False, 0.0, "Trade size too small or capital insufficient"
        
        return True, trade_size, "Trade approved"
    
    def record_trade_result(self, success: bool, pnl: float):
        """Record trade outcome and update risk metrics"""
        self.total_trades += 1
        
        if success:
            self.successful_trades += 1
            self.consecutive_failures = 0
            self.daily_pnl += pnl
            logger.info(f"Meme trade successful: PnL ${pnl:.4f}, Daily PnL: ${self.daily_pnl:.4f}")
        else:
            self.consecutive_failures += 1
            self.last_failure_time = datetime.now(timezone.utc)
            self.daily_pnl += pnl  # PnL will be negative
            
            # Check if cooldown needed
            if self.consecutive_failures >= self.cooldown_after_failures:
                self.cooldown_until = datetime.now(timezone.utc) + timedelta(
                    minutes=self.cooldown_duration_minutes
                )
                logger.warning(
                    f"Meme trading cooldown activated after {self.consecutive_failures} failures. "
                    f"Cooldown until {self.cooldown_until}"
                )
    
    def get_stats(self) -> Dict:
        """Get current risk management statistics"""
        success_rate = (self.successful_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        
        return {
            "initial_capital": self.initial_capital,
            "reserve_percentage": self.reserve_percentage,
            "max_trade_percentage": self.max_trade_percentage,
            "min_liquidity_usd": self.min_liquidity_usd,
            "total_trades": self.total_trades,
            "successful_trades": self.successful_trades,
            "success_rate": success_rate,
            "daily_pnl": self.daily_pnl,
            "consecutive_failures": self.consecutive_failures,
            "in_cooldown": self.cooldown_until is not None,
            "can_trade": self.can_trade()[0]
        }
