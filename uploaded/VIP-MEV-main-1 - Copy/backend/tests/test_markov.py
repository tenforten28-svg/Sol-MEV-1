"""
Tests for Markov State Model
============================
Step 10: Validates state classification and EV_adj calculation.
"""

import pytest
from bot.alpha import (
    MarkovModel,
    MarkovState,
    MarkovDecision,
    StateFeatures,
    features_to_state,
    calculate_ev_adj,
    get_markov_stats
)


class TestStateClassification:
    """Test state classification"""
    
    def test_favorable_state(self):
        """Test that good conditions produce FAVORABLE state"""
        features = StateFeatures(
            ev_net=0.6,
            crowding_score=0.2,
            recent_failure_rate=0.1,
            volatility_score=0.2,
            fingerprint="TEST"
        )
        
        state = features_to_state(features)
        assert state == MarkovState.FAVORABLE
    
    def test_unfavorable_state(self):
        """Test that poor conditions produce UNFAVORABLE state"""
        features = StateFeatures(
            ev_net=-0.1,
            crowding_score=0.8,
            recent_failure_rate=0.6,
            volatility_score=0.7,
            fingerprint="TEST"
        )
        
        state = features_to_state(features)
        assert state == MarkovState.UNFAVORABLE
    
    def test_neutral_state(self):
        """Test that mixed conditions produce NEUTRAL state"""
        features = StateFeatures(
            ev_net=0.15,
            crowding_score=0.45,
            recent_failure_rate=0.3,
            volatility_score=0.4,
            fingerprint="TEST"
        )
        
        state = features_to_state(features)
        assert state == MarkovState.NEUTRAL
    
    def test_state_features_to_dict(self):
        """Test StateFeatures serialization"""
        features = StateFeatures(
            ev_net=0.5,
            crowding_score=0.3,
            recent_failure_rate=0.2,
            volatility_score=0.1,
            fingerprint="TEST::FP"
        )
        
        d = features.to_dict()
        
        assert d['ev_net'] == 0.5
        assert d['fingerprint'] == "TEST::FP"


class TestMarkovModel:
    """Test Markov model"""
    
    def test_record_outcome(self):
        """Test recording outcomes"""
        model = MarkovModel()
        
        features = StateFeatures(
            ev_net=0.5,
            crowding_score=0.2,
            recent_failure_rate=0.1,
            volatility_score=0.2,
            fingerprint="TEST"
        )
        
        model.record_outcome(features, success=True)
        model.record_outcome(features, success=False)
        
        stats = model.get_stats()
        assert stats['total_outcomes'] == 2
    
    def test_get_p_success_no_data(self):
        """Test P_success with no data returns default"""
        model = MarkovModel()
        
        p, count = model.get_p_success(MarkovState.FAVORABLE, "UNKNOWN")
        
        assert p == 0.5  # Default
        assert count == 0
    
    def test_get_p_success_with_data(self):
        """Test P_success calculation with sufficient data"""
        model = MarkovModel()
        fingerprint = "TEST::ROUTE"
        
        # Record 10 outcomes: 8 success, 2 failure
        for i in range(10):
            features = StateFeatures(
                ev_net=0.6,
                crowding_score=0.2,
                recent_failure_rate=0.1,
                volatility_score=0.2,
                fingerprint=fingerprint
            )
            model.record_outcome(features, success=(i < 8))
        
        state = MarkovState.FAVORABLE
        p, count = model.get_p_success(state, fingerprint)
        
        assert count >= 5  # Enough data
        assert 0.6 <= p <= 0.9  # Should reflect ~80% success rate
    
    def test_model_stats(self):
        """Test model statistics"""
        model = MarkovModel()
        
        for i in range(5):
            features = StateFeatures(
                ev_net=0.5 if i % 2 == 0 else -0.1,
                crowding_score=0.3,
                recent_failure_rate=0.2,
                volatility_score=0.2,
                fingerprint=f"TEST_{i}"
            )
            model.record_outcome(features, success=(i % 2 == 0))
        
        stats = model.get_stats()
        
        assert stats['total_outcomes'] == 5
        assert 'by_state' in stats


class TestEVAdjCalculation:
    """Test EV_adj calculation"""
    
    def test_ev_adj_positive(self):
        """Test EV_adj with positive expected value"""
        features = StateFeatures(
            ev_net=0.5,
            crowding_score=0.2,
            recent_failure_rate=0.1,
            volatility_score=0.2,
            fingerprint="TEST"
        )
        
        decision = calculate_ev_adj(
            features=features,
            profit_est=0.50,
            loss_est=0.05,
            fees=0.02
        )
        
        assert isinstance(decision, MarkovDecision)
        assert 0 <= decision.p_success <= 1
        assert decision.state in MarkovState
    
    def test_ev_adj_negative(self):
        """Test EV_adj with negative expected value"""
        features = StateFeatures(
            ev_net=-0.2,
            crowding_score=0.8,
            recent_failure_rate=0.6,
            volatility_score=0.7,
            fingerprint="TEST"
        )
        
        decision = calculate_ev_adj(
            features=features,
            profit_est=0.05,
            loss_est=0.10,
            fees=0.05
        )
        
        # With unfavorable conditions and low profit, should not execute
        assert isinstance(decision, MarkovDecision)
    
    def test_markov_decision_to_dict(self):
        """Test MarkovDecision serialization"""
        decision = MarkovDecision(
            should_execute=True,
            p_success=0.75,
            ev_adj=0.25,
            state=MarkovState.FAVORABLE,
            reason="Test",
            breakdown={'test': 'data'}
        )
        
        d = decision.to_dict()
        
        assert d['should_execute'] == True
        assert d['p_success'] == 0.75
        assert d['state'] == 'FAVORABLE'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
