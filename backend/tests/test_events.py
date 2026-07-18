"""
Tests for Event Schema and Bus
==============================
Validates event types, schema validation, and redaction.
"""

import pytest
import time
from bot.events import (
    Event, EventType, EventHeader, create_event, validate_event, 
    redact_secrets, now_ms,
    PoolUpdatePayload, OpportunityPayload, SimulationPayload,
    DecisionPayload, HeartbeatPayload, ErrorPayload,
    LiquiditySnapshot, ThresholdsSnapshot, FailureTag
)
from bot.events.bus import EventBus, get_event_bus, emit, get_stats


class TestEventSchema:
    """Test event schema and validation"""
    
    def test_create_pool_update_event(self):
        """Test creating a pool_update event"""
        payload = PoolUpdatePayload(
            pool_name="raydium_sol_usdc",
            dex="raydium",
            base_reserve=1000000000,
            quote_reserve=200000000,
            base_decimals=9,
            quote_decimals=6,
            price=200.0
        )
        
        event = create_event(EventType.POOL_UPDATE, payload, slot=12345)
        
        assert event.event_type == EventType.POOL_UPDATE
        assert event.header.slot == 12345
        assert event.header.event_id is not None
        assert event.header.ts_ms > 0
        
        # Validate
        is_valid, errors = validate_event(event)
        assert is_valid, f"Validation failed: {errors}"
    
    def test_create_opportunity_event(self):
        """Test creating an opportunity_detected event"""
        payload = OpportunityPayload(
            route_id="test-route-123",
            buy_pool="raydium_sol_usdc",
            sell_pool="orca_sol_usdc",
            buy_dex="raydium",
            sell_dex="orca",
            token_path=["USDC", "SOL", "USDC"],
            dex_programs=["RAYDIUM", "ORCA"],
            pool_accounts=["58oQChx4", "HJPjoWUr"],
            spread_bps=15.5,
            buy_price=200.0,
            sell_price=200.31,
            liquidity_snapshots=[],
            estimated_profit_usd=0.50,
            ev_raw_est=0.50,
            optimal_size_usd=1000
        )
        
        event = create_event(
            EventType.OPPORTUNITY_DETECTED, 
            payload, 
            fingerprint="RAYDIUM|ORCA::USDC->SOL->USDC::pools:58oQChx4,HJPjoWUr"
        )
        
        assert event.event_type == EventType.OPPORTUNITY_DETECTED
        assert event.header.fingerprint is not None
        
        is_valid, errors = validate_event(event)
        assert is_valid, f"Validation failed: {errors}"
    
    def test_create_decision_event(self):
        """Test creating a decision event"""
        thresholds = ThresholdsSnapshot(
            min_spread_bps=8,
            min_profit_usd=0.05,
            max_trade_usd=1000,
            slippage_bps=50
        )
        
        payload = DecisionPayload(
            action="EXECUTE",
            reasons=["EV_net > 0", "spread >= min"],
            thresholds_snapshot=thresholds.to_dict(),
            ev_raw_est=0.50,
            ev_net_est=0.35
        )
        
        event = create_event(EventType.DECISION, payload)
        
        assert event.event_type == EventType.DECISION
        is_valid, errors = validate_event(event)
        assert is_valid, f"Validation failed: {errors}"
    
    def test_create_heartbeat_event(self):
        """Test creating a heartbeat event"""
        payload = HeartbeatPayload(
            uptime_seconds=3600,
            pools_active=4,
            events_emitted=1000,
            opportunities_detected=50,
            trades_attempted=10,
            trades_success=8,
            total_profit_usd=5.50
        )
        
        event = create_event(EventType.HEARTBEAT, payload)
        
        is_valid, errors = validate_event(event)
        assert is_valid, f"Validation failed: {errors}"
    
    def test_create_all_event_types(self):
        """Test that all event types can be created and validated"""
        event_tests = [
            (EventType.POOL_UPDATE, PoolUpdatePayload(
                pool_name="test", dex="raydium", base_reserve=1, quote_reserve=1,
                base_decimals=9, quote_decimals=6, price=1.0
            )),
            (EventType.SIMULATION_RESULT, SimulationPayload(
                sim_ok=True, expected_out=1000, cu_est=200000
            )),
            (EventType.ERROR, ErrorPayload(
                error_type="TEST", error_message="Test error"
            )),
        ]
        
        for event_type, payload in event_tests:
            event = create_event(event_type, payload)
            is_valid, errors = validate_event(event)
            assert is_valid, f"{event_type} validation failed: {errors}"


class TestRedaction:
    """Test secret redaction"""
    
    def test_redact_private_key(self):
        """Test redacting private key patterns"""
        data = {
            "wallet": "5bwrZzK1BxVoMf8yLjCqGz4K1bwrZzK1BxVoMf8yLjCqGz4K1bwrZzK1BxVoMf8yLjCqGz4K1bwrZzK1BxVoMf8y",
            "normal_field": "hello"
        }
        
        redacted = redact_secrets(data)
        
        assert redacted["normal_field"] == "hello"
        # Long base58 string should be redacted
        assert redacted["wallet"] == "[REDACTED]"
    
    def test_redact_key_names(self):
        """Test redacting by key name"""
        data = {
            "private_key": "my-secret",
            "api_key": "sk_live_xxx",
            "password": "hunter2",
            "normal": "visible"
        }
        
        redacted = redact_secrets(data)
        
        assert redacted["private_key"] == "[REDACTED]"
        assert redacted["api_key"] == "[REDACTED]"
        assert redacted["password"] == "[REDACTED]"
        assert redacted["normal"] == "visible"
    
    def test_redact_nested(self):
        """Test redacting nested structures"""
        data = {
            "outer": {
                "secret": "hidden",
                "inner": {
                    "api_key": "sk_xxx"
                }
            }
        }
        
        redacted = redact_secrets(data)
        
        assert redacted["outer"]["secret"] == "[REDACTED]"
        assert redacted["outer"]["inner"]["api_key"] == "[REDACTED]"


class TestEventBus:
    """Test event bus functionality"""
    
    def test_emit_event(self):
        """Test emitting an event"""
        bus = EventBus()
        
        received_events = []
        def handler(event):
            received_events.append(event)
        
        bus.subscribe(handler)
        
        event = create_event(EventType.HEARTBEAT, HeartbeatPayload(
            uptime_seconds=1, pools_active=1, events_emitted=1,
            opportunities_detected=0, trades_attempted=0, trades_success=0,
            total_profit_usd=0
        ))
        
        result = bus.emit(event)
        
        assert result == True
        assert len(received_events) == 1
        assert received_events[0].event_type == EventType.HEARTBEAT
    
    def test_event_stats(self):
        """Test event statistics tracking"""
        bus = EventBus()
        
        # Emit several events
        for _ in range(5):
            event = create_event(EventType.POOL_UPDATE, PoolUpdatePayload(
                pool_name="test", dex="test", base_reserve=1, quote_reserve=1,
                base_decimals=9, quote_decimals=6, price=1.0
            ))
            bus.emit(event)
        
        stats = bus.get_stats()
        
        assert stats['emitted'] >= 5
        assert stats['valid'] >= 5
        assert 'pool_update' in stats['by_type']


class TestTimingFields:
    """Test latency tracking in events"""
    
    def test_compute_latencies(self):
        """Test computing derived latencies"""
        event = create_event(EventType.OPPORTUNITY_DETECTED, OpportunityPayload(
            route_id="test", buy_pool="a", sell_pool="b",
            buy_dex="raydium", sell_dex="orca",
            token_path=["A", "B", "A"], dex_programs=["X"], pool_accounts=["Y"],
            spread_bps=10, buy_price=1, sell_price=1.001,
            liquidity_snapshots=[], estimated_profit_usd=0.1,
            ev_raw_est=0.1, optimal_size_usd=100
        ))
        
        # Set timing fields
        event.pool_update_received_ts = 1000
        event.opportunity_detected_ts = 1050
        event.simulation_start_ts = 1060
        event.simulation_end_ts = 1100
        event.decision_ts = 1110
        event.bundle_submit_ts = 1120
        event.tx_confirm_ts = 1500
        
        latencies = event.compute_latencies()
        
        assert latencies['detect_latency_ms'] == 50
        assert latencies['sim_latency_ms'] == 40
        assert latencies['decision_latency_ms'] == 60
        assert latencies['submit_latency_ms'] == 10
        assert latencies['confirm_latency_ms'] == 380
        assert latencies['total_latency_ms'] == 500


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
