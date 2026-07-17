"""
Tests for Half-Life and TTL Gating
==================================
Step 8: Validates half-life calculation and TTL gate.
"""

import pytest
import time
from bot.alpha import (
    HalfLifeCalculator,
    HalfLifeStats,
    TTLDecision,
    check_ttl_gate,
    record_spread_observation,
    record_latency,
    get_half_life_stats
)


class TestHalfLifeCalculator:
    """Test half-life calculation"""
    
    def test_add_observations(self):
        """Test adding spread observations"""
        calc = HalfLifeCalculator()
        fingerprint = "TEST::SOL->USDC"
        
        base_time = int(time.time() * 1000)
        
        for i in range(10):
            calc.add_observation(fingerprint, 50 - i * 3, base_time + i * 100)
        
        # Check observations stored
        assert len(calc._observations[fingerprint]) == 10
    
    def test_compute_half_life_insufficient_data(self):
        """Test half-life with insufficient data returns None"""
        calc = HalfLifeCalculator()
        fingerprint = "TEST::INSUFFICIENT"
        
        # Only add 3 observations (less than MIN_SAMPLES_FOR_HALFLIFE)
        base_time = int(time.time() * 1000)
        for i in range(3):
            calc.add_observation(fingerprint, 50 - i * 5, base_time + i * 100)
        
        result = calc.compute_half_life(fingerprint)
        assert result is None
    
    def test_compute_half_life_with_decay(self):
        """Test half-life calculation with decaying spread"""
        calc = HalfLifeCalculator()
        fingerprint = "TEST::DECAY"
        
        base_time = int(time.time() * 1000)
        
        # Simulate exponential decay
        # spread = 100 * e^(-0.005t) approximately
        spreads = [100, 60, 40, 25, 15, 10, 7, 5, 4, 3, 2.5, 2]
        
        for i, spread in enumerate(spreads):
            calc.add_observation(fingerprint, spread, base_time + i * 100)
        
        result = calc.compute_half_life(fingerprint)
        
        assert result is not None
        assert isinstance(result, HalfLifeStats)
        assert result.half_life_ms > 0
        assert result.samples == len(spreads)
    
    def test_latency_p90(self):
        """Test p90 latency calculation"""
        calc = HalfLifeCalculator()
        fingerprint = "TEST::LATENCY"
        
        # Add latencies: [100, 150, 200, 250, 300, 350, 400, 450, 500, 550]
        for i in range(10):
            calc.add_latency(fingerprint, 100 + i * 50)
        
        p90 = calc.get_latency_p90(fingerprint)
        
        # p90 should be around 500ms (90th percentile)
        assert 450 <= p90 <= 550
    
    def test_latency_p90_insufficient_data(self):
        """Test p90 with insufficient data returns default"""
        calc = HalfLifeCalculator()
        fingerprint = "TEST::NO_LATENCY"
        
        # Only 2 latencies
        calc.add_latency(fingerprint, 100)
        calc.add_latency(fingerprint, 200)
        
        p90 = calc.get_latency_p90(fingerprint)
        
        # Should return default (200ms)
        assert p90 == 200.0


class TestTTLGate:
    """Test TTL gate decisions"""
    
    def test_ttl_gate_no_data(self):
        """Test TTL gate with no historical data"""
        decision = check_ttl_gate("UNKNOWN::FINGERPRINT")
        
        assert isinstance(decision, TTLDecision)
        assert isinstance(decision.should_skip, bool)
        assert decision.half_life_ms > 0  # Should use default
    
    def test_ttl_gate_skip_when_latency_exceeds_halflife(self):
        """Test that high latency relative to half-life causes skip"""
        # This would require setting up the calculator with specific data
        # For now, just verify the decision structure
        decision = check_ttl_gate("TEST::SLOW", current_latency_ms=1000)
        
        assert isinstance(decision, TTLDecision)
        assert 'latency' in decision.reason.lower() or 'ttl' in decision.reason.lower()
    
    def test_ttl_decision_to_dict(self):
        """Test TTLDecision serialization"""
        decision = TTLDecision(
            should_skip=True,
            reason="Test reason",
            half_life_ms=300,
            latency_p90_ms=400,
            ttl_ratio=1.33
        )
        
        d = decision.to_dict()
        
        assert d['should_skip'] == True
        assert d['half_life_ms'] == 300
        assert d['latency_p90_ms'] == 400
        assert d['ttl_ratio'] == 1.33


class TestHalfLifeStats:
    """Test HalfLifeStats data class"""
    
    def test_stats_to_dict(self):
        """Test HalfLifeStats serialization"""
        stats = HalfLifeStats(
            fingerprint="TEST::FP",
            half_life_ms=250.5,
            decay_slope=0.05,
            samples=100,
            confidence=0.8,
            last_updated_ts=1234567890
        )
        
        d = stats.to_dict()
        
        assert d['fingerprint'] == "TEST::FP"
        assert d['half_life_ms'] == 250.5
        assert d['decay_slope'] == 0.05
        assert d['samples'] == 100
        assert d['confidence'] == 0.8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
