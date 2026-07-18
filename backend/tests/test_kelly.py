"""
Tests for Kelly Sizing
======================
Step 12: Validates Kelly criterion calculations and risk management.
"""

import pytest
from bot.alpha import (
    calculate_optimal_size,
    get_kelly_sizing,
    update_risk_state,
    reset_daily_risk_state,
    should_stop_trading,
    get_risk_state,
    KellyResult,
    RiskState
)


class TestKellyCalculation:
    """Test Kelly criterion calculation"""
    
    def test_strong_edge(self):
        """Test Kelly with strong edge"""
        result = calculate_optimal_size(
            p_success=0.8,
            profit_if_win=1.00,
            loss_if_lose=0.10,
            base_size_usd=1000
        )
        
        assert isinstance(result, KellyResult)
        assert result.full_kelly > 0  # Positive edge
        assert result.size_multiplier > 0
        assert result.recommended_size_usd > 0
    
    def test_no_edge(self):
        """Test Kelly with no edge"""
        result = calculate_optimal_size(
            p_success=0.4,
            profit_if_win=0.10,
            loss_if_lose=0.10,
            base_size_usd=1000
        )
        
        assert result.full_kelly <= 0  # No edge
        assert result.size_multiplier == 0  # Should not trade
        assert result.recommended_size_usd == 0
    
    def test_weak_edge(self):
        """Test Kelly with weak edge"""
        result = calculate_optimal_size(
            p_success=0.55,
            profit_if_win=0.12,
            loss_if_lose=0.10,
            base_size_usd=1000
        )
        
        assert isinstance(result, KellyResult)
        assert result.full_kelly > 0  # Positive but small
        assert result.size_multiplier > 0
        assert result.size_multiplier < 1  # Fractional Kelly
    
    def test_fee_multiplier_increases_with_edge(self):
        """Test that stronger edge increases fee willingness"""
        weak_edge = calculate_optimal_size(
            p_success=0.55,
            profit_if_win=0.12,
            loss_if_lose=0.10,
            base_size_usd=1000
        )
        
        strong_edge = calculate_optimal_size(
            p_success=0.8,
            profit_if_win=1.00,
            loss_if_lose=0.10,
            base_size_usd=1000
        )
        
        assert strong_edge.fee_multiplier >= weak_edge.fee_multiplier
    
    def test_kelly_result_to_dict(self):
        """Test KellyResult serialization"""
        result = KellyResult(
            full_kelly=0.5,
            fractional_kelly=0.075,
            size_multiplier=0.1,
            fee_multiplier=1.2,
            recommended_size_usd=100,
            recommended_fee_lamports=60000,
            reason="Test",
            breakdown={'test': 'data'}
        )
        
        d = result.to_dict()
        
        assert d['full_kelly'] == 0.5
        assert d['recommended_size_usd'] == 100


class TestRiskState:
    """Test risk state management"""
    
    def test_risk_state_initialization(self):
        """Test RiskState defaults"""
        state = RiskState()
        
        assert state.daily_pnl_usd == 0.0
        assert state.consecutive_losses == 0
        assert state.trades_today == 0
    
    def test_drawdown_calculation(self):
        """Test drawdown percentage calculation"""
        state = RiskState(
            peak_balance_usd=1000,
            current_balance_usd=900
        )
        
        assert state.drawdown_pct == 0.1  # 10% drawdown
    
    def test_win_rate_calculation(self):
        """Test win rate calculation"""
        state = RiskState(
            trades_today=10,
            wins_today=7,
            losses_today=3
        )
        
        assert state.win_rate_today == 0.7
    
    def test_risk_state_to_dict(self):
        """Test RiskState serialization"""
        state = RiskState(
            daily_pnl_usd=-50,
            consecutive_losses=3,
            peak_balance_usd=1000,
            current_balance_usd=900
        )
        
        d = state.to_dict()
        
        assert d['daily_pnl_usd'] == -50
        assert d['consecutive_losses'] == 3
        assert d['drawdown_pct'] == 0.1


class TestRiskManagement:
    """Test risk management functions"""
    
    def test_drawdown_reduces_size(self):
        """Test that drawdown reduces position size"""
        risk_state = RiskState(
            peak_balance_usd=1000,
            current_balance_usd=850  # 15% drawdown
        )
        
        result = calculate_optimal_size(
            p_success=0.7,
            profit_if_win=0.50,
            loss_if_lose=0.05,
            base_size_usd=1000,
            risk_state=risk_state
        )
        
        # Should have drawdown reduction
        assert 'drawdown' in result.reason.lower() or result.size_multiplier < 0.15
    
    def test_consecutive_losses_reduce_size(self):
        """Test that consecutive losses reduce position size"""
        risk_state = RiskState(
            consecutive_losses=6  # Above threshold
        )
        
        result = calculate_optimal_size(
            p_success=0.7,
            profit_if_win=0.50,
            loss_if_lose=0.05,
            base_size_usd=1000,
            risk_state=risk_state
        )
        
        # Should have loss reduction
        assert 'loss' in result.reason.lower() or result.size_multiplier < 0.1
    
    def test_should_stop_trading_daily_loss(self):
        """Test stop trading on daily loss limit"""
        # Reset state first
        reset_daily_risk_state()
        state = get_risk_state()
        state.daily_pnl_usd = -150  # Beyond limit
        
        should_stop, reason = should_stop_trading()
        
        assert should_stop == True
        assert 'loss' in reason.lower()


class TestConvenienceFunctions:
    """Test convenience functions"""
    
    def test_get_kelly_sizing(self):
        """Test get_kelly_sizing function"""
        result = get_kelly_sizing(
            p_success=0.7,
            expected_profit_usd=0.50,
            expected_loss_usd=0.05,
            base_size_usd=500
        )
        
        assert isinstance(result, KellyResult)
        assert result.recommended_size_usd <= 500  # Can't exceed base


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
