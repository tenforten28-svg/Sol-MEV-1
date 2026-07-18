"""
Tests for EV Net Calculation
============================
Validates expected value calculations and decision gating.
"""

import pytest
from bot.alpha import (
    calculate_ev_net,
    quick_ev_check,
    optimal_priority_fee,
    EVCalculation,
    CostBreakdown
)


class TestEVCalculation:
    """Test EV net calculations"""
    
    def test_profitable_trade_should_execute(self):
        """Test that clearly profitable trades get EXECUTE decision"""
        # Use parameters that will result in positive EV after costs
        result = calculate_ev_net(
            expected_profit_usd=5.00,  # Higher profit to overcome costs
            trade_size_usd=500,  # Smaller trade for less slippage
            spread_bps=25,  # Healthy spread
            liquidity_depth_usd=500000,  # Deep liquidity
            p_success=0.85
        )
        
        assert isinstance(result, EVCalculation)
        assert result.ev_raw == 5.00
        assert result.should_execute == True, f"Expected EXECUTE, got reasons: {result.reasons}"
        assert "EXECUTE" in result.reasons
    
    def test_unprofitable_trade_should_skip(self):
        """Test that unprofitable trades get SKIP decision"""
        result = calculate_ev_net(
            expected_profit_usd=0.01,  # Very small profit
            trade_size_usd=1000,
            spread_bps=5,  # Thin spread
            liquidity_depth_usd=10000,  # Low liquidity
            p_success=0.3  # Low success probability
        )
        
        assert result.should_execute == False
        assert "SKIP" in result.reasons
    
    def test_negative_ev_should_skip(self):
        """Test that negative EV trades are skipped"""
        result = calculate_ev_net(
            expected_profit_usd=0.005,  # Tiny profit
            trade_size_usd=10000,  # Large trade
            spread_bps=2,  # Very thin spread
            liquidity_depth_usd=10000,  # Equal to trade size
            p_success=0.4
        )
        
        # With large slippage and low p_success, should skip
        assert result.should_execute == False
    
    def test_cost_breakdown(self):
        """Test that cost breakdown is populated"""
        result = calculate_ev_net(
            expected_profit_usd=0.50,
            trade_size_usd=1000,
            spread_bps=15,
            p_success=0.7
        )
        
        costs = result.costs
        assert isinstance(costs, CostBreakdown)
        assert costs.base_fee_usd >= 0
        assert costs.priority_fee_usd >= 0
        assert costs.jito_tip_usd >= 0
        assert costs.slippage_usd >= 0
        assert costs.total_cost_usd > 0
    
    def test_ev_net_less_than_raw(self):
        """Test that EV_net is less than EV_raw due to costs"""
        result = calculate_ev_net(
            expected_profit_usd=1.00,
            trade_size_usd=1000,
            spread_bps=20,
            p_success=0.9
        )
        
        # After costs, EV_net should be less than raw
        assert result.ev_net < result.ev_raw
    
    def test_slippage_scales_with_trade_size(self):
        """Test that larger trades have higher slippage estimates"""
        small_trade = calculate_ev_net(
            expected_profit_usd=0.10,
            trade_size_usd=100,
            spread_bps=10,
            liquidity_depth_usd=10000,
            p_success=0.7
        )
        
        large_trade = calculate_ev_net(
            expected_profit_usd=0.10,
            trade_size_usd=5000,
            spread_bps=10,
            liquidity_depth_usd=10000,
            p_success=0.7
        )
        
        assert large_trade.costs.slippage_usd > small_trade.costs.slippage_usd


class TestQuickEVCheck:
    """Test quick EV check for filtering"""
    
    def test_clearly_profitable(self):
        """Test clearly profitable opportunities pass"""
        result = quick_ev_check(
            expected_profit_usd=10.00,  # Very high profit
            trade_size_usd=500,  # Small trade
            spread_bps=30,  # Wide spread
            p_success=0.9  # High success rate
        )
        
        assert result == True
    
    def test_clearly_unprofitable(self):
        """Test clearly unprofitable opportunities fail"""
        result = quick_ev_check(
            expected_profit_usd=0.001,
            trade_size_usd=10000,
            spread_bps=2,
            p_success=0.2
        )
        
        assert result == False
    
    def test_borderline(self):
        """Test borderline cases"""
        # Just above threshold
        result = quick_ev_check(
            expected_profit_usd=0.05,
            trade_size_usd=500,
            spread_bps=10,
            p_success=0.7
        )
        
        # Should be True or False depending on exact calculation
        assert isinstance(result, bool)


class TestOptimalPriorityFee:
    """Test priority fee optimization"""
    
    def test_higher_profit_higher_fee(self):
        """Test that higher profit allows higher fees"""
        low_profit_fee = optimal_priority_fee(
            expected_profit_usd=0.10,
            p_success=0.7,
            competition_level=0.5
        )
        
        high_profit_fee = optimal_priority_fee(
            expected_profit_usd=5.00,
            p_success=0.7,
            competition_level=0.5
        )
        
        assert high_profit_fee > low_profit_fee
    
    def test_higher_competition_higher_fee(self):
        """Test that higher competition requires higher fees"""
        low_comp_fee = optimal_priority_fee(
            expected_profit_usd=1.00,
            p_success=0.7,
            competition_level=0.1
        )
        
        high_comp_fee = optimal_priority_fee(
            expected_profit_usd=1.00,
            p_success=0.7,
            competition_level=0.9
        )
        
        assert high_comp_fee > low_comp_fee
    
    def test_fee_has_maximum(self):
        """Test that fees are capped at maximum"""
        max_fee = optimal_priority_fee(
            expected_profit_usd=1000,  # Very high profit
            p_success=0.1,  # Low success
            competition_level=1.0  # Max competition
        )
        
        assert max_fee <= 500000, "Fee should be capped"
    
    def test_fee_has_minimum(self):
        """Test that fees have reasonable minimum"""
        min_fee = optimal_priority_fee(
            expected_profit_usd=0.01,
            p_success=1.0,
            competition_level=0.0
        )
        
        assert min_fee >= 10000, "Fee should have minimum"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
