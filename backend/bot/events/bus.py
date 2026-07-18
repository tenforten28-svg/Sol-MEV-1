"""
EVENT BUS - Central Event Emission & Subscription
=================================================
Single source of truth for all bot events.
Supports multiple subscribers (console, file, SQLite, etc.)
"""

import asyncio
import logging
import json
import os
from typing import Callable, List, Dict, Any, Optional
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import threading

from .schema import (
    Event, EventType, EventHeader, 
    validate_event, redact_secrets, now_ms
)

logger = logging.getLogger('event_bus')

# ============================================================================
# FEATURE FLAGS
# ============================================================================

FEATURE_FLAGS = {
    'EVENTS_ENABLED': os.environ.get('EVENTS_ENABLED', 'true').lower() == 'true',
    'EVENTS_PERSIST': os.environ.get('EVENTS_PERSIST', 'true').lower() == 'true',
    'EVENTS_LOG_CONSOLE': os.environ.get('EVENTS_LOG_CONSOLE', 'true').lower() == 'true',
    'EVENTS_LOG_FILE': os.environ.get('EVENTS_LOG_FILE', 'true').lower() == 'true',
    'EVENTS_REDACT': os.environ.get('EVENTS_REDACT', 'true').lower() == 'true',
}

# ============================================================================
# EVENT STATS
# ============================================================================

@dataclass
class EventStats:
    """Track event statistics"""
    emitted: int = 0
    valid: int = 0
    invalid: int = 0
    by_type: Dict[str, int] = None
    errors: List[str] = None
    
    def __post_init__(self):
        if self.by_type is None:
            self.by_type = defaultdict(int)
        if self.errors is None:
            self.errors = []
    
    def record(self, event_type: str, is_valid: bool, errors: List[str] = None):
        self.emitted += 1
        self.by_type[event_type] += 1
        
        if is_valid:
            self.valid += 1
        else:
            self.invalid += 1
            if errors:
                self.errors.extend(errors[-5:])  # Keep last 5 errors
    
    def validation_rate(self) -> float:
        if self.emitted == 0:
            return 1.0
        return self.valid / self.emitted
    
    def to_dict(self) -> Dict:
        return {
            'emitted': self.emitted,
            'valid': self.valid,
            'invalid': self.invalid,
            'validation_rate': f"{self.validation_rate() * 100:.2f}%",
            'by_type': dict(self.by_type),
            'recent_errors': self.errors[-10:] if self.errors else []
        }


# ============================================================================
# EVENT SUBSCRIBER
# ============================================================================

EventHandler = Callable[[Event], None]
AsyncEventHandler = Callable[[Event], Any]


class EventBus:
    """
    Central event bus for all bot events
    Thread-safe, supports sync and async handlers
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._handlers: List[EventHandler] = []
        self._async_handlers: List[AsyncEventHandler] = []
        self._type_handlers: Dict[EventType, List[EventHandler]] = defaultdict(list)
        self._stats = EventStats()
        self._event_queue: asyncio.Queue = None
        self._file_handle = None
        self._initialized = True
        
        # Set up default handlers
        if FEATURE_FLAGS['EVENTS_LOG_CONSOLE']:
            self.subscribe(self._console_handler)
        
        if FEATURE_FLAGS['EVENTS_LOG_FILE']:
            self._setup_file_logging()
    
    def _setup_file_logging(self):
        """Set up file logging for events"""
        log_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, f"events_{datetime.now().strftime('%Y%m%d')}.jsonl")
        self._file_handle = open(log_file, 'a')
        self.subscribe(self._file_handler)
        logger.info(f"Event file logging: {log_file}")
    
    def _console_handler(self, event: Event):
        """Log important events to console"""
        event_type = event.event_type
        
        # Only log certain event types to console
        verbose_types = {
            EventType.POOL_UPDATE,  # Too noisy
        }
        
        if event_type in verbose_types:
            return
        
        payload = event.payload
        if hasattr(payload, 'to_dict'):
            payload = payload.to_dict()
        
        # Format based on event type
        if event_type == EventType.OPPORTUNITY_DETECTED:
            logger.info(
                f"⚡ OPPORTUNITY | {payload.get('buy_pool')} -> {payload.get('sell_pool')} | "
                f"Spread: {payload.get('spread_bps', 0):.1f}bps | "
                f"Profit: ${payload.get('estimated_profit_usd', 0):.4f}"
            )
        
        elif event_type == EventType.DECISION:
            action = payload.get('action', 'UNKNOWN')
            emoji = "✅" if action == "EXECUTE" else "⏭️"
            logger.info(f"{emoji} DECISION: {action} | Reasons: {payload.get('reasons', [])}")
        
        elif event_type == EventType.BUNDLE_SUBMITTED:
            logger.info(f"📦 BUNDLE | ID: {payload.get('jito_bundle_id', 'N/A')}")
        
        elif event_type == EventType.TX_RESULT:
            status = payload.get('status', 'UNKNOWN')
            emoji = "✅" if status == "CONFIRMED" else "❌"
            logger.info(f"{emoji} TX {status} | Sig: {payload.get('signature', 'N/A')[:16]}...")
        
        elif event_type == EventType.PNL_REALIZED:
            profit = payload.get('net_profit_usd', 0)
            emoji = "💰" if profit > 0 else "📉"
            logger.info(f"{emoji} PNL: ${profit:.4f}")
        
        elif event_type == EventType.HEARTBEAT:
            logger.info(
                f"💓 HEARTBEAT | Pools: {payload.get('pools_active', 0)} | "
                f"Opps: {payload.get('opportunities_detected', 0)} | "
                f"Trades: {payload.get('trades_success', 0)}/{payload.get('trades_attempted', 0)} | "
                f"Profit: ${payload.get('total_profit_usd', 0):.4f}"
            )
        
        elif event_type == EventType.ERROR:
            logger.error(f"❌ ERROR | {payload.get('error_type')}: {payload.get('error_message')}")
    
    def _file_handler(self, event: Event):
        """Write events to JSONL file"""
        if not self._file_handle:
            return
        
        try:
            event_dict = event.to_dict()
            
            # Redact secrets before writing
            if FEATURE_FLAGS['EVENTS_REDACT']:
                event_dict = redact_secrets(event_dict)
            
            line = json.dumps(event_dict, default=str) + "\n"
            self._file_handle.write(line)
            self._file_handle.flush()
        except Exception as e:
            logger.debug(f"File write error: {e}")
    
    def subscribe(self, handler: EventHandler):
        """Subscribe a handler to all events"""
        self._handlers.append(handler)
    
    def subscribe_async(self, handler: AsyncEventHandler):
        """Subscribe an async handler"""
        self._async_handlers.append(handler)
    
    def subscribe_to_type(self, event_type: EventType, handler: EventHandler):
        """Subscribe to specific event type"""
        self._type_handlers[event_type].append(handler)
    
    def unsubscribe(self, handler: EventHandler):
        """Remove a handler"""
        if handler in self._handlers:
            self._handlers.remove(handler)
    
    def emit(self, event: Event) -> bool:
        """
        Emit an event to all subscribers
        Returns True if event was valid
        """
        if not FEATURE_FLAGS['EVENTS_ENABLED']:
            return True
        
        # Validate event
        is_valid, errors = validate_event(event)
        
        # Record stats
        event_type = event.event_type.value if isinstance(event.event_type, EventType) else str(event.event_type)
        self._stats.record(event_type, is_valid, errors)
        
        if not is_valid:
            logger.warning(f"Invalid event: {errors}")
        
        # Notify all handlers
        for handler in self._handlers:
            try:
                handler(event)
            except Exception as e:
                logger.debug(f"Handler error: {e}")
        
        # Notify type-specific handlers
        if event.event_type in self._type_handlers:
            for handler in self._type_handlers[event.event_type]:
                try:
                    handler(event)
                except Exception as e:
                    logger.debug(f"Type handler error: {e}")
        
        return is_valid
    
    async def emit_async(self, event: Event) -> bool:
        """Emit event and await async handlers"""
        is_valid = self.emit(event)
        
        # Call async handlers
        for handler in self._async_handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.debug(f"Async handler error: {e}")
        
        return is_valid
    
    def emit_and_return(self, event: Event) -> Event:
        """Emit event and return it (for chaining)"""
        self.emit(event)
        return event
    
    def get_stats(self) -> Dict:
        """Get event statistics"""
        return self._stats.to_dict()
    
    def print_stats(self):
        """Print event statistics to console"""
        stats = self.get_stats()
        logger.info("=" * 50)
        logger.info("EVENT STATS")
        logger.info(f"  Total emitted: {stats['emitted']}")
        logger.info(f"  Valid: {stats['valid']} ({stats['validation_rate']})")
        logger.info(f"  Invalid: {stats['invalid']}")
        logger.info("  By type:")
        for event_type, count in stats['by_type'].items():
            logger.info(f"    {event_type}: {count}")
        logger.info("=" * 50)
    
    def close(self):
        """Close file handles"""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None


# ============================================================================
# GLOBAL BUS INSTANCE
# ============================================================================

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance"""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def emit(event: Event) -> bool:
    """Convenience function to emit an event"""
    return get_event_bus().emit(event)


async def emit_async(event: Event) -> bool:
    """Convenience function for async emit"""
    return await get_event_bus().emit_async(event)


def subscribe(handler: EventHandler):
    """Convenience function to subscribe"""
    get_event_bus().subscribe(handler)


def get_stats() -> Dict:
    """Get event stats"""
    return get_event_bus().get_stats()
