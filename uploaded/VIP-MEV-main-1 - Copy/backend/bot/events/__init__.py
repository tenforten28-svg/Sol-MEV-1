"""
Events Package
"""

from .schema import (
    Event, EventType, EventHeader,
    PoolUpdatePayload, OpportunityPayload, SimulationPayload,
    DecisionPayload, BundlePayload, TxResultPayload, PnLPayload,
    HeartbeatPayload, ErrorPayload, LiquiditySnapshot, ThresholdsSnapshot,
    DecisionAction, FailureTag, TxStatus,
    create_event, validate_event, redact_secrets, now_ms
)

from .bus import (
    EventBus, get_event_bus, emit, emit_async, subscribe, get_stats,
    FEATURE_FLAGS
)

__all__ = [
    # Schema
    'Event', 'EventType', 'EventHeader',
    'PoolUpdatePayload', 'OpportunityPayload', 'SimulationPayload',
    'DecisionPayload', 'BundlePayload', 'TxResultPayload', 'PnLPayload',
    'HeartbeatPayload', 'ErrorPayload', 'LiquiditySnapshot', 'ThresholdsSnapshot',
    'DecisionAction', 'FailureTag', 'TxStatus',
    'create_event', 'validate_event', 'redact_secrets', 'now_ms',
    
    # Bus
    'EventBus', 'get_event_bus', 'emit', 'emit_async', 'subscribe', 'get_stats',
    'FEATURE_FLAGS'
]
