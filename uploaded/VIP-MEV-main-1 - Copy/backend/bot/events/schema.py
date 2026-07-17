"""
EVENT SCHEMA - Structured Event Definitions
============================================
Every bot action becomes a typed, validated event.
Single source of truth for all bot telemetry.
"""

import uuid
import time
import os
import re
import hashlib
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime

# ============================================================================
# CONSTANTS
# ============================================================================

BOT_VERSION = os.environ.get('BOT_VERSION', '1.0.0')
BOT_ENV = os.environ.get('BOT_ENV', 'mainnet')

# ============================================================================
# ENUMS
# ============================================================================

class EventType(str, Enum):
    POOL_UPDATE = "pool_update"
    OPPORTUNITY_DETECTED = "opportunity_detected"
    SIMULATION_RESULT = "simulation_result"
    DECISION = "decision"
    BUNDLE_SUBMITTED = "bundle_submitted"
    TX_RESULT = "tx_result"
    PNL_REALIZED = "pnl_realized"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    STARTUP = "startup"
    SHUTDOWN = "shutdown"


class DecisionAction(str, Enum):
    EXECUTE = "EXECUTE"
    SKIP = "SKIP"


class FailureTag(str, Enum):
    SLIPPAGE = "SLIPPAGE"
    ACCOUNT_IN_USE = "ACCOUNT_IN_USE"
    PRIORITY_LOST = "PRIORITY_LOST"
    BLOCKHASH_EXPIRED = "BLOCKHASH_EXPIRED"
    SIM_MISMATCH = "SIM_MISMATCH"
    ROUTE_STALE = "ROUTE_STALE"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    PROGRAM_ERROR = "PROGRAM_ERROR"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    OTHER = "OTHER"


class TxStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


# ============================================================================
# EVENT HEADER (common to all events)
# ============================================================================

@dataclass
class EventHeader:
    """Common header for all events"""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    slot: Optional[int] = None
    bot_version: str = BOT_VERSION
    env: str = BOT_ENV
    fingerprint: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


# ============================================================================
# PAYLOAD SCHEMAS
# ============================================================================

@dataclass
class PoolUpdatePayload:
    """Pool state update from WebSocket"""
    pool_name: str
    dex: str
    base_reserve: int
    quote_reserve: int
    base_decimals: int
    quote_decimals: int
    price: float
    update_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class LiquiditySnapshot:
    """Snapshot of pool liquidity at detection time"""
    pool_name: str
    base_reserve: int
    quote_reserve: int
    price: float
    depth_usd: float  # Estimated tradeable depth
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class OpportunityPayload:
    """Detected arbitrage opportunity"""
    route_id: str
    buy_pool: str
    sell_pool: str
    buy_dex: str
    sell_dex: str
    token_path: List[str]  # e.g., ["USDC", "SOL", "USDC"]
    dex_programs: List[str]
    pool_accounts: List[str]
    spread_bps: float
    buy_price: float
    sell_price: float
    liquidity_snapshots: List[Dict]
    estimated_profit_usd: float
    ev_raw_est: float
    optimal_size_usd: float
    detection_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SimulationPayload:
    """Transaction simulation result"""
    sim_ok: bool
    sim_err: Optional[str] = None
    expected_out: int = 0
    cu_est: int = 0
    logs_hash: Optional[str] = None
    failure_tag: Optional[str] = None
    sim_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ThresholdsSnapshot:
    """Snapshot of decision thresholds at decision time"""
    min_spread_bps: float
    min_profit_usd: float
    max_trade_usd: float
    slippage_bps: float
    crowding_threshold: float = 0.7
    ev_net_threshold: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DecisionPayload:
    """Execution decision"""
    action: str  # EXECUTE or SKIP
    reasons: List[str]
    thresholds_snapshot: Dict
    ev_raw_est: float
    ev_net_est: Optional[float] = None
    crowding_score: Optional[float] = None
    half_life_ms: Optional[float] = None
    p_success: Optional[float] = None
    decision_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BundlePayload:
    """Jito bundle submission"""
    jito_bundle_id: Optional[str]
    cu_price: int
    priority_fee_lamports: int
    tx_count: int
    tip_lamports: int
    submit_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TxResultPayload:
    """Transaction result"""
    signature: Optional[str]
    status: str  # CONFIRMED, FAILED, TIMEOUT
    err: Optional[str] = None
    failure_tag: Optional[str] = None
    fee_lamports: int = 0
    cu_used: int = 0
    confirmation_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PnLPayload:
    """Realized profit/loss"""
    profit_lamports: int
    profit_usd_est: float
    slippage_realized_bps: float
    fees_total_lamports: int
    fees_usd_est: float
    net_profit_usd: float
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class HeartbeatPayload:
    """Periodic health check"""
    uptime_seconds: float
    pools_active: int
    events_emitted: int
    opportunities_detected: int
    trades_attempted: int
    trades_success: int
    total_profit_usd: float
    memory_mb: float = 0.0
    ws_connected: bool = True
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ErrorPayload:
    """Error event"""
    error_type: str
    error_message: str
    stack_trace: Optional[str] = None
    context: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


# ============================================================================
# FULL EVENT
# ============================================================================

@dataclass
class Event:
    """Complete event with header and typed payload"""
    event_type: EventType
    header: EventHeader
    payload: Union[
        PoolUpdatePayload,
        OpportunityPayload,
        SimulationPayload,
        DecisionPayload,
        BundlePayload,
        TxResultPayload,
        PnLPayload,
        HeartbeatPayload,
        ErrorPayload,
        Dict
    ]
    
    # Timing fields for latency tracking
    pool_update_received_ts: Optional[int] = None
    opportunity_detected_ts: Optional[int] = None
    simulation_start_ts: Optional[int] = None
    simulation_end_ts: Optional[int] = None
    decision_ts: Optional[int] = None
    bundle_submit_ts: Optional[int] = None
    tx_confirm_ts: Optional[int] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        result = {
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else self.event_type,
            "header": self.header.to_dict() if hasattr(self.header, 'to_dict') else self.header,
            "payload": self.payload.to_dict() if hasattr(self.payload, 'to_dict') else self.payload,
        }
        
        # Add timing fields if present
        timing_fields = [
            'pool_update_received_ts', 'opportunity_detected_ts',
            'simulation_start_ts', 'simulation_end_ts', 'decision_ts',
            'bundle_submit_ts', 'tx_confirm_ts'
        ]
        
        for field_name in timing_fields:
            value = getattr(self, field_name, None)
            if value is not None:
                result[field_name] = value
        
        return result
    
    def compute_latencies(self) -> Dict[str, float]:
        """Compute derived latencies between stages"""
        latencies = {}
        
        if self.pool_update_received_ts and self.opportunity_detected_ts:
            latencies['detect_latency_ms'] = self.opportunity_detected_ts - self.pool_update_received_ts
        
        if self.simulation_start_ts and self.simulation_end_ts:
            latencies['sim_latency_ms'] = self.simulation_end_ts - self.simulation_start_ts
        
        if self.opportunity_detected_ts and self.decision_ts:
            latencies['decision_latency_ms'] = self.decision_ts - self.opportunity_detected_ts
        
        if self.decision_ts and self.bundle_submit_ts:
            latencies['submit_latency_ms'] = self.bundle_submit_ts - self.decision_ts
        
        if self.bundle_submit_ts and self.tx_confirm_ts:
            latencies['confirm_latency_ms'] = self.tx_confirm_ts - self.bundle_submit_ts
        
        if self.pool_update_received_ts and self.tx_confirm_ts:
            latencies['total_latency_ms'] = self.tx_confirm_ts - self.pool_update_received_ts
        
        return latencies


# ============================================================================
# REDACTION HELPERS
# ============================================================================

SECRET_PATTERNS = [
    r'[1-9A-HJ-NP-Za-km-z]{87,88}',  # Base58 private keys
    r'[A-Za-z0-9+/]{40,}={0,2}',      # Base64 secrets (long)
    r'sk_[a-zA-Z0-9]{20,}',           # API keys (sk_ prefix)
    r'key_[a-zA-Z0-9]{20,}',          # API keys (key_ prefix)
    r'Bearer\s+[A-Za-z0-9\-_]+',      # Bearer tokens
]

REDACT_KEYS = [
    'private_key', 'secret', 'password', 'token', 'api_key',
    'auth', 'credential', 'SOLANA_PRIVATE_KEY'
]


def redact_secrets(data: Any, depth: int = 0) -> Any:
    """
    Recursively redact secrets from data
    Removes private keys, auth tokens, and sensitive patterns
    """
    if depth > 10:  # Prevent infinite recursion
        return data
    
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            # Check if key suggests sensitive data
            key_lower = key.lower()
            if any(secret in key_lower for secret in REDACT_KEYS):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_secrets(value, depth + 1)
        return result
    
    elif isinstance(data, list):
        return [redact_secrets(item, depth + 1) for item in data]
    
    elif isinstance(data, str):
        # Check for secret patterns
        for pattern in SECRET_PATTERNS:
            if re.search(pattern, data):
                return "[REDACTED]"
        return data
    
    else:
        return data


def hash_logs(logs: List[str]) -> str:
    """Create a hash of transaction logs for reference without storing full logs"""
    combined = "\n".join(logs) if logs else ""
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


# ============================================================================
# VALIDATION
# ============================================================================

def validate_event(event: Event) -> tuple:
    """
    Validate event against schema
    Returns: (is_valid, errors)
    """
    errors = []
    
    # Check header
    if not event.header.event_id:
        errors.append("Missing event_id")
    
    if not event.header.ts_ms or event.header.ts_ms <= 0:
        errors.append("Invalid ts_ms")
    
    # Check payload type matches event type
    type_payload_map = {
        EventType.POOL_UPDATE: PoolUpdatePayload,
        EventType.OPPORTUNITY_DETECTED: OpportunityPayload,
        EventType.SIMULATION_RESULT: SimulationPayload,
        EventType.DECISION: DecisionPayload,
        EventType.BUNDLE_SUBMITTED: BundlePayload,
        EventType.TX_RESULT: TxResultPayload,
        EventType.PNL_REALIZED: PnLPayload,
        EventType.HEARTBEAT: HeartbeatPayload,
        EventType.ERROR: ErrorPayload,
    }
    
    expected_type = type_payload_map.get(event.event_type)
    if expected_type and not isinstance(event.payload, (expected_type, dict)):
        errors.append(f"Payload type mismatch: expected {expected_type.__name__}")
    
    # Check timing fields are non-negative
    timing_fields = [
        'pool_update_received_ts', 'opportunity_detected_ts',
        'simulation_start_ts', 'simulation_end_ts', 'decision_ts',
        'bundle_submit_ts', 'tx_confirm_ts'
    ]
    
    for field_name in timing_fields:
        value = getattr(event, field_name, None)
        if value is not None and value < 0:
            errors.append(f"Negative timing: {field_name}")
    
    return len(errors) == 0, errors


# ============================================================================
# FACTORY FUNCTIONS
# ============================================================================

def create_event(
    event_type: EventType,
    payload: Any,
    slot: Optional[int] = None,
    fingerprint: Optional[str] = None
) -> Event:
    """Factory function to create events with proper header"""
    header = EventHeader(
        slot=slot,
        fingerprint=fingerprint
    )
    
    return Event(
        event_type=event_type,
        header=header,
        payload=payload
    )


def now_ms() -> int:
    """Get current timestamp in milliseconds"""
    return int(time.time() * 1000)
