"""
HFT WebSocket Bot - Production Trading Engine
=============================================
Event-driven architecture with:
- Event schema and bus
- SQLite persistence
- Route fingerprinting
- EV-based decision gating
- Failure taxonomy
- Latency tracking
- Replay capability
"""

# Only import the core modules - avoid importing modules with broken relative imports
from .events import (
    Event, EventType, EventHeader, create_event, emit, get_event_bus, now_ms,
    FEATURE_FLAGS
)
from .storage import get_storage, SQLiteStorage, write_event
from .alpha import (
    build_fingerprint, build_fingerprint_from_opportunity,
    classify_failure, should_retry,
    calculate_ev_net, quick_ev_check
)

__all__ = [
    # Events
    'Event', 'EventType', 'EventHeader', 'create_event', 'emit', 'get_event_bus', 'now_ms',
    'FEATURE_FLAGS',
    # Storage
    'get_storage', 'SQLiteStorage', 'write_event',
    # Alpha
    'build_fingerprint', 'build_fingerprint_from_opportunity',
    'classify_failure', 'should_retry',
    'calculate_ev_net', 'quick_ev_check',
]
