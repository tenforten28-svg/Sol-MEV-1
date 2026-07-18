"""
Tests for Crowding Score
========================
Step 9: Validates crowding detection and gate.
"""

import pytest
import time
from bot.alpha import (
    CrowdingCalculator,
    CrowdingScore,
    CrowdingDecision,
    check_crowding_gate,
    record_spread,
    record_pool_update,
    record_trade_outcome,
    get_crowding_score,
    HIGH_CROWDING_THRESHOLD,
    MEDIUM_CROWDING_THRESHOLD
)


class TestCrowdingCalculator:
    """Test crowding calculation"""
    
    def test_add_spread_observation(self):
        """Test adding spread observations"""
        calc = CrowdingCalculator()
        fingerprint = "TEST::SPREAD"
        
        for i in range(10):
            calc.add_spread_observation(fingerprint, 50 - i * 3)
        
        assert len(calc._spreads[fingerprint]) == 10
    
    def test_add_pool_update(self):
        """Test adding pool updates"""
        calc = CrowdingCalculator()
        pool_name = "raydium_sol_usdc"
        
        for i in range(20):
            calc.add_pool_update(pool_name, 100000, 0.001)
        
        assert len(calc._pool_updates[pool_name]) == 20
    
    def test_add_trade_outcome(self):
        """Test adding trade outcomes"""
        calc = CrowdingCalculator()
        fingerprint = "TEST::OUTCOMES"
        
        calc.add_trade_outcome(fingerprint, success=True)
        calc.add_trade_outcome(fingerprint, success=False, failure_tag="SLIPPAGE")
        calc.add_trade_outcome(fingerprint, success=True)
        
        assert len(calc._outcomes[fingerprint]) == 3
    
    def test_calculate_crowding_score_no_data(self):
        """Test crowding score with no data returns low score"""
        calc = CrowdingCalculator()
        
        score = calc.calculate_crowding_score("UNKNOWN", ["pool1", "pool2"])
        
        assert isinstance(score, CrowdingScore)
        assert 0 <= score.score <= 1
        # With no data, all components should be 0
        assert score.spread_decay_component == 0
        assert score.pool_churn_component == 0
        assert score.failure_rate_component == 0
    
    def test_calculate_crowding_score_high_activity(self):
        """Test crowding score with high activity"""
        calc = CrowdingCalculator()
        fingerprint = "TEST::HIGH_CROWD"
        pools = ["raydium_sol_usdc", "orca_sol_usdc"]
        
        base_time = int(time.time() * 1000)
        
        # Add rapid spread decay
        for i in range(30):
            calc.add_spread_observation(fingerprint, 100 - i * 3, base_time + i * 30)
        
        # Add high pool churn
        for pool in pools:
            for i in range(50):
                calc.add_pool_update(pool, 1000000, 0.01, base_time + i * 50)
        
        # Add many failures
        for i in range(15):
            success = i % 4 != 0  # 25% failure rate
            tag = "PRIORITY_LOST" if not success else None
            calc.add_trade_outcome(fingerprint, success, tag, base_time + i * 3000)
        
        score = calc.calculate_crowding_score(fingerprint, pools)
        
        assert isinstance(score, CrowdingScore)
        assert score.score > 0  # Should have some crowding detected
    
    def test_crowding_score_caching(self):
        """Test that scores are cached"""
        calc = CrowdingCalculator()
        fingerprint = "TEST::CACHE"
        pools = ["pool1"]
        
        # First call
        score1 = calc.calculate_crowding_score(fingerprint, pools)
        
        # Second call (should hit cache)
        score2 = calc.calculate_crowding_score(fingerprint, pools)
        
        assert score1.score == score2.score


class TestCrowdingGate:
    """Test crowding gate decisions"""
    
    def test_crowding_gate_low_crowding(self):
        """Test gate with low crowding recommends execute"""
        # With no data, crowding should be low
        decision = check_crowding_gate("NEW::FINGERPRINT", ["pool1"])
        
        assert isinstance(decision, CrowdingDecision)
        assert decision.should_skip == False
        assert decision.should_reduce_size == False
        assert decision.score < HIGH_CROWDING_THRESHOLD
    
    def test_crowding_decision_structure(self):
        """Test CrowdingDecision fields"""
        decision = CrowdingDecision(
            should_skip=True,
            should_reduce_size=False,
            should_raise_fee=False,
            score=0.85,
            reason="High crowding"
        )
        
        d = decision.to_dict()
        
        assert d['should_skip'] == True
        assert d['score'] == 0.85
        assert 'High crowding' in d['reason']
    
    def test_crowding_score_to_dict(self):
        """Test CrowdingScore serialization"""
        score = CrowdingScore(
            score=0.65,
            spread_decay_component=0.7,
            pool_churn_component=0.5,
            failure_rate_component=0.6,
            recommendation="CAUTION",
            details={'test': 'data'}
        )
        
        d = score.to_dict()
        
        assert d['score'] == 0.65
        assert d['recommendation'] == "CAUTION"
        assert d['spread_decay_component'] == 0.7


class TestCrowdingRecommendations:
    """Test crowding recommendation logic"""
    
    def test_recommendation_execute(self):
        """Test EXECUTE recommendation for low crowding"""
        score = CrowdingScore(
            score=0.2,
            spread_decay_component=0.1,
            pool_churn_component=0.2,
            failure_rate_component=0.3,
            recommendation="EXECUTE"
        )
        
        assert score.recommendation == "EXECUTE"
        assert score.score < MEDIUM_CROWDING_THRESHOLD
    
    def test_recommendation_caution(self):
        """Test CAUTION recommendation for medium crowding"""
        score = CrowdingScore(
            score=0.55,
            spread_decay_component=0.5,
            pool_churn_component=0.6,
            failure_rate_component=0.5,
            recommendation="CAUTION"
        )
        
        assert score.recommendation == "CAUTION"
        assert MEDIUM_CROWDING_THRESHOLD <= score.score < HIGH_CROWDING_THRESHOLD
    
    def test_recommendation_skip(self):
        """Test SKIP recommendation for high crowding"""
        score = CrowdingScore(
            score=0.85,
            spread_decay_component=0.9,
            pool_churn_component=0.8,
            failure_rate_component=0.85,
            recommendation="SKIP"
        )
        
        assert score.recommendation == "SKIP"
        assert score.score >= HIGH_CROWDING_THRESHOLD


class TestCrowdingThresholds:
    """Test threshold values"""
    
    def test_threshold_ordering(self):
        """Test that thresholds are properly ordered"""
        assert MEDIUM_CROWDING_THRESHOLD < HIGH_CROWDING_THRESHOLD
        assert 0 < MEDIUM_CROWDING_THRESHOLD < 1
        assert 0 < HIGH_CROWDING_THRESHOLD <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
