"""
Tests for Kernel Model (ML)
===========================
Step 11: Validates kernel model predictions.
"""

import pytest
import numpy as np
from bot.alpha import (
    KernelModel,
    ModelFeatures,
    ModelPrediction,
    kernel_predict,
    add_training_sample,
    get_kernel_stats
)


class TestModelFeatures:
    """Test ModelFeatures data class"""
    
    def test_features_to_vector(self):
        """Test conversion to numpy vector"""
        features = ModelFeatures(
            ev_net=0.3,
            spread_bps=15,
            liquidity_depth_usd=100000,
            crowding_score=0.4,
            half_life_ms=400,
            latency_ms=150,
            recent_success_rate=0.7,
            recent_failure_rate=0.3,
            pool_update_rate=2.0,
            time_of_day_hour=14
        )
        
        vec = features.to_vector()
        
        assert isinstance(vec, np.ndarray)
        assert len(vec) == 10  # 10 features
    
    def test_features_to_dict(self):
        """Test serialization"""
        features = ModelFeatures(
            ev_net=0.3,
            spread_bps=15,
            liquidity_depth_usd=100000,
            crowding_score=0.4,
            half_life_ms=400,
            latency_ms=150,
            recent_success_rate=0.7,
            recent_failure_rate=0.3,
            pool_update_rate=2.0,
            time_of_day_hour=14
        )
        
        d = features.to_dict()
        
        assert d['ev_net'] == 0.3
        assert d['spread_bps'] == 15


class TestKernelModel:
    """Test kernel model"""
    
    def test_add_sample(self):
        """Test adding training samples"""
        model = KernelModel()
        
        features = ModelFeatures(
            ev_net=0.3,
            spread_bps=15,
            liquidity_depth_usd=100000,
            crowding_score=0.4,
            half_life_ms=400,
            latency_ms=150,
            recent_success_rate=0.7,
            recent_failure_rate=0.3,
            pool_update_rate=2.0,
            time_of_day_hour=14
        )
        
        model.add_sample(features, success=True, slippage_bps=5)
        
        assert len(model.samples) == 1
    
    def test_predict_no_data(self):
        """Test prediction with insufficient data"""
        model = KernelModel()
        
        features = ModelFeatures(
            ev_net=0.3,
            spread_bps=15,
            liquidity_depth_usd=100000,
            crowding_score=0.4,
            half_life_ms=400,
            latency_ms=150,
            recent_success_rate=0.7,
            recent_failure_rate=0.3,
            pool_update_rate=2.0,
            time_of_day_hour=14
        )
        
        p_success, confidence = model.predict_p_success(features)
        
        assert p_success == 0.5  # Default
        assert confidence == 0.0  # No confidence
    
    def test_predict_with_data(self):
        """Test prediction with sufficient data"""
        model = KernelModel()
        
        # Add training data
        for i in range(100):
            features = ModelFeatures(
                ev_net=0.1 + (i % 10) * 0.05,
                spread_bps=10 + (i % 20),
                liquidity_depth_usd=50000 + i * 1000,
                crowding_score=0.3 + (i % 5) * 0.1,
                half_life_ms=300 + i * 10,
                latency_ms=100 + (i % 10) * 20,
                recent_success_rate=0.6,
                recent_failure_rate=0.4,
                pool_update_rate=2.0,
                time_of_day_hour=i % 24
            )
            success = (features.ev_net > 0.2 and features.crowding_score < 0.5)
            model.add_sample(features, success, slippage_bps=5 + i % 10)
        
        # Test prediction
        test_features = ModelFeatures(
            ev_net=0.3,
            spread_bps=15,
            liquidity_depth_usd=80000,
            crowding_score=0.4,
            half_life_ms=400,
            latency_ms=150,
            recent_success_rate=0.7,
            recent_failure_rate=0.3,
            pool_update_rate=1.5,
            time_of_day_hour=14
        )
        
        prediction = model.predict(test_features)
        
        assert isinstance(prediction, ModelPrediction)
        assert 0 <= prediction.p_success <= 1
        assert prediction.slippage_bps >= 0
        assert prediction.confidence > 0  # Should have some confidence now
    
    def test_model_stats(self):
        """Test model statistics"""
        model = KernelModel()
        
        for i in range(20):
            features = ModelFeatures(
                ev_net=0.3,
                spread_bps=15,
                liquidity_depth_usd=100000,
                crowding_score=0.4,
                half_life_ms=400,
                latency_ms=150,
                recent_success_rate=0.7,
                recent_failure_rate=0.3,
                pool_update_rate=2.0,
                time_of_day_hour=14
            )
            model.add_sample(features, success=(i % 2 == 0), slippage_bps=10)
        
        stats = model.get_stats()
        
        assert stats['samples'] == 20
        assert stats['success_rate'] == 0.5


class TestModelPrediction:
    """Test ModelPrediction data class"""
    
    def test_prediction_to_dict(self):
        """Test serialization"""
        prediction = ModelPrediction(
            p_success=0.75,
            slippage_bps=8.5,
            ttl_ms=450,
            confidence=0.8,
            features_used={'test': 'data'}
        )
        
        d = prediction.to_dict()
        
        assert d['p_success'] == 0.75
        assert d['slippage_bps'] == 8.5
        assert d['confidence'] == 0.8


class TestKernelTypes:
    """Test different kernel functions"""
    
    def test_rbf_kernel_model(self):
        """Test RBF kernel"""
        model = KernelModel(kernel_type='rbf', gamma=0.1)
        
        assert model.kernel_type == 'rbf'
        assert model.gamma == 0.1
    
    def test_linear_kernel_model(self):
        """Test linear kernel"""
        model = KernelModel(kernel_type='linear')
        
        assert model.kernel_type == 'linear'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
