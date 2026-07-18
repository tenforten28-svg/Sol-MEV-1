"""
FAILURE TAXONOMY - Classify Transaction Failures
=================================================
Auto-tag failures for learning and analysis.
"""

import re
from typing import Optional, List, Tuple
from enum import Enum

from ..events.schema import FailureTag

# ============================================================================
# ERROR PATTERNS
# ============================================================================

# Simulation errors
SIM_ERROR_PATTERNS = {
    FailureTag.SLIPPAGE: [
        r'slippage',
        r'exceeds.*amount',
        r'min.*out',
        r'output.*less.*than',
        r'ExceededSlippage',
    ],
    FailureTag.INSUFFICIENT_LIQUIDITY: [
        r'insufficient.*liquidity',
        r'not.*enough.*liquidity',
        r'liquidity.*empty',
        r'zero.*reserves',
    ],
    FailureTag.INSUFFICIENT_BALANCE: [
        r'insufficient.*balance',
        r'insufficient.*funds',
        r'not.*enough.*balance',
        r'balance.*too.*low',
        r'0x1$',  # Token program insufficient balance
    ],
    FailureTag.ACCOUNT_IN_USE: [
        r'account.*in.*use',
        r'already.*borrowed',
        r'concurrent',
        r'locked',
    ],
    FailureTag.PROGRAM_ERROR: [
        r'program.*error',
        r'custom.*program.*error',
        r'0x[0-9a-f]+',  # Generic hex error
    ],
}

# Transaction errors
TX_ERROR_PATTERNS = {
    FailureTag.BLOCKHASH_EXPIRED: [
        r'blockhash.*expired',
        r'blockhash.*not.*found',
        r'block.*height.*exceeded',
        r'TransactionExpiredBlockheightExceededError',
    ],
    FailureTag.PRIORITY_LOST: [
        r'priority',
        r'outbid',
        r'MEV',
        r'front.*run',
    ],
    FailureTag.TIMEOUT: [
        r'timeout',
        r'timed.*out',
        r'deadline.*exceeded',
    ],
    FailureTag.NETWORK_ERROR: [
        r'network',
        r'connection',
        r'refused',
        r'unreachable',
        r'socket',
    ],
    FailureTag.SIM_MISMATCH: [
        r'simulation.*mismatch',
        r'unexpected.*result',
        r'state.*changed',
    ],
    FailureTag.ROUTE_STALE: [
        r'stale',
        r'outdated',
        r'expired.*route',
    ],
}

# ============================================================================
# CLASSIFIER
# ============================================================================

def classify_failure(
    sim_err: Optional[str] = None,
    tx_err: Optional[str] = None,
    logs: Optional[List[str]] = None
) -> FailureTag:
    """
    Classify a failure into a category.
    
    Args:
        sim_err: Simulation error message
        tx_err: Transaction error message
        logs: Transaction logs
    
    Returns:
        FailureTag enum value
    """
    # Combine all error sources
    all_text = ""
    
    if sim_err:
        all_text += sim_err.lower() + " "
    
    if tx_err:
        all_text += tx_err.lower() + " "
    
    if logs:
        all_text += " ".join(logs).lower()
    
    if not all_text.strip():
        return FailureTag.OTHER
    
    # Check simulation errors first
    for tag, patterns in SIM_ERROR_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, all_text, re.IGNORECASE):
                return tag
    
    # Check transaction errors
    for tag, patterns in TX_ERROR_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, all_text, re.IGNORECASE):
                return tag
    
    return FailureTag.OTHER


def get_failure_details(tag: FailureTag) -> dict:
    """Get details about a failure type"""
    details = {
        FailureTag.SLIPPAGE: {
            "description": "Price moved unfavorably during execution",
            "is_retryable": True,
            "retry_delay_ms": 500,
            "action": "Reduce size or increase slippage tolerance"
        },
        FailureTag.ACCOUNT_IN_USE: {
            "description": "Pool account is being used by another transaction",
            "is_retryable": True,
            "retry_delay_ms": 100,
            "action": "Wait and retry quickly"
        },
        FailureTag.PRIORITY_LOST: {
            "description": "Another bot outbid us on priority",
            "is_retryable": True,
            "retry_delay_ms": 50,
            "action": "Increase priority fee"
        },
        FailureTag.BLOCKHASH_EXPIRED: {
            "description": "Transaction took too long to land",
            "is_retryable": True,
            "retry_delay_ms": 0,
            "action": "Rebuild transaction with fresh blockhash"
        },
        FailureTag.SIM_MISMATCH: {
            "description": "On-chain state changed between simulation and execution",
            "is_retryable": False,
            "retry_delay_ms": 0,
            "action": "Re-evaluate opportunity"
        },
        FailureTag.ROUTE_STALE: {
            "description": "Opportunity is no longer valid",
            "is_retryable": False,
            "retry_delay_ms": 0,
            "action": "Skip this opportunity"
        },
        FailureTag.INSUFFICIENT_LIQUIDITY: {
            "description": "Not enough liquidity in the pool",
            "is_retryable": False,
            "retry_delay_ms": 0,
            "action": "Reduce trade size or skip"
        },
        FailureTag.INSUFFICIENT_BALANCE: {
            "description": "Wallet doesn't have enough tokens",
            "is_retryable": False,
            "retry_delay_ms": 0,
            "action": "Check wallet balance"
        },
        FailureTag.PROGRAM_ERROR: {
            "description": "DEX program returned an error",
            "is_retryable": False,
            "retry_delay_ms": 0,
            "action": "Check instruction parameters"
        },
        FailureTag.TIMEOUT: {
            "description": "Request timed out",
            "is_retryable": True,
            "retry_delay_ms": 1000,
            "action": "Retry with backoff"
        },
        FailureTag.NETWORK_ERROR: {
            "description": "Network connectivity issue",
            "is_retryable": True,
            "retry_delay_ms": 1000,
            "action": "Check connection and retry"
        },
        FailureTag.OTHER: {
            "description": "Unknown error type",
            "is_retryable": False,
            "retry_delay_ms": 0,
            "action": "Manual investigation needed"
        },
    }
    
    return details.get(tag, details[FailureTag.OTHER])


def should_retry(tag: FailureTag) -> Tuple[bool, int]:
    """
    Determine if a failure should be retried.
    
    Returns:
        (should_retry, delay_ms)
    """
    details = get_failure_details(tag)
    return details['is_retryable'], details['retry_delay_ms']


def get_failure_stats_query() -> str:
    """SQL query to get failure stats from events"""
    return '''
        SELECT 
            json_extract(payload_json, '$.payload.failure_tag') as failure_tag,
            COUNT(*) as count
        FROM events
        WHERE event_type IN ('simulation_result', 'tx_result')
        AND json_extract(payload_json, '$.payload.failure_tag') IS NOT NULL
        GROUP BY failure_tag
        ORDER BY count DESC
    '''


# ============================================================================
# TESTS
# ============================================================================

def test_classifier():
    """Test failure classification"""
    test_cases = [
        ("slippage tolerance exceeded", None, FailureTag.SLIPPAGE),
        ("insufficient balance", None, FailureTag.INSUFFICIENT_BALANCE),
        (None, "blockhash expired", FailureTag.BLOCKHASH_EXPIRED),
        (None, "connection refused", FailureTag.NETWORK_ERROR),
        ("custom program error: 0x1", None, FailureTag.INSUFFICIENT_BALANCE),
        ("account in use", None, FailureTag.ACCOUNT_IN_USE),
        ("unknown weird error", None, FailureTag.OTHER),
    ]
    
    for sim_err, tx_err, expected in test_cases:
        result = classify_failure(sim_err, tx_err)
        status = "✓" if result == expected else "✗"
        print(f"{status} classify({sim_err or tx_err}) = {result.value} (expected {expected.value})")
    
    print("Tests complete")


if __name__ == "__main__":
    test_classifier()
