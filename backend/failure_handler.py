"""
Advanced Failure Handler & Retry Policy
Handles all failure modes with intelligent retry strategies
"""
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
import logging
import random

logger = logging.getLogger(__name__)

class FailureMode(Enum):
    """All possible failure modes"""
    NOT_INCLUDED = "not_included"                # Bundle timeout
    PARTIAL_EXECUTION = "partial_execution"      # Some txs reverted
    REVERT = "revert"                           # Full revert
    INSUFFICIENT_FUNDS = "insufficient_funds"    # Balance too low
    ACCOUNT_MISSING = "account_missing"         # Account not created
    COMPUTE_EXCEEDED = "compute_exceeded"       # OOM/compute limit
    SLIPPAGE_EXCEEDED = "slippage_exceeded"     # Price moved
    NETWORK_ERROR = "network_error"             # Connection issues
    INVALID_BUNDLE = "invalid_bundle"           # Malformed bundle
    RATE_LIMITED = "rate_limited"               # Too many requests
    UNKNOWN = "unknown"                         # Unclassified

@dataclass
class FailureContext:
    """Context for a failure event"""
    bundle_id: str
    failure_mode: FailureMode
    error_message: str
    timestamp: datetime
    attempt_number: int
    
    # Diagnostics
    balance_at_failure: Optional[float] = None
    compute_units_used: Optional[int] = None
    slot: Optional[int] = None
    
    # Retry decision
    should_retry: bool = False
    retry_delay_ms: int = 0
    tip_multiplier: float = 1.0
    reason: Optional[str] = None

class RetryPolicy:
    """
    Intelligent retry policy with failure mode awareness
    
    Retry Matrix:
    - NOT_INCLUDED → Retry with higher tip (2-3x)
    - PARTIAL_EXECUTION → Do NOT retry (atomicity issue)
    - REVERT (slippage) → Do NOT retry (market moved)
    - INSUFFICIENT_FUNDS → Do NOT retry (fix balance first)
    - ACCOUNT_MISSING → Retry once after creating account
    - COMPUTE_EXCEEDED → Retry with higher compute budget
    - NETWORK_ERROR → Retry with exponential backoff
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_backoff_ms: int = 50,
        tip_escalation_factor: float = 1.5,
        max_tip_multiplier: float = 5.0
    ):
        self.max_retries = max_retries
        self.base_backoff_ms = base_backoff_ms
        self.tip_escalation_factor = tip_escalation_factor
        self.max_tip_multiplier = max_tip_multiplier
    
    def evaluate_failure(
        self,
        bundle_id: str,
        failure_mode: FailureMode,
        error_message: str,
        attempt_number: int,
        current_tip: int,
        diagnostics: Dict = None
    ) -> FailureContext:
        """
        Evaluate failure and determine retry strategy
        
        Args:
            bundle_id: Bundle identifier
            failure_mode: Type of failure
            error_message: Error details
            attempt_number: Current attempt (1-indexed)
            current_tip: Current tip in lamports
            diagnostics: Additional diagnostic info
            
        Returns:
            FailureContext with retry decision
        """
        ctx = FailureContext(
            bundle_id=bundle_id,
            failure_mode=failure_mode,
            error_message=error_message,
            timestamp=datetime.now(timezone.utc),
            attempt_number=attempt_number
        )
        
        # Add diagnostics
        if diagnostics:
            ctx.balance_at_failure = diagnostics.get('balance')
            ctx.compute_units_used = diagnostics.get('compute_units')
            ctx.slot = diagnostics.get('slot')
        
        # Check max retries
        if attempt_number >= self.max_retries:
            ctx.should_retry = False
            ctx.reason = f"Max retries ({self.max_retries}) reached"
            return ctx
        
        # Evaluate based on failure mode
        if failure_mode == FailureMode.NOT_INCLUDED:
            # Bundle timeout - retry with higher tip
            ctx.should_retry = True
            ctx.tip_multiplier = min(
                self.tip_escalation_factor ** attempt_number,
                self.max_tip_multiplier
            )
            ctx.retry_delay_ms = self._exponential_backoff_with_jitter(attempt_number)
            ctx.reason = f"Timeout - retry with {ctx.tip_multiplier:.1f}x tip"
            
        elif failure_mode == FailureMode.PARTIAL_EXECUTION:
            # Atomicity failure - DO NOT RETRY
            ctx.should_retry = False
            ctx.reason = "Partial execution detected - atomicity violated"
            
        elif failure_mode == FailureMode.REVERT:
            # Transaction reverted (likely slippage) - DO NOT RETRY
            ctx.should_retry = False
            ctx.reason = "Revert detected - market conditions changed"
            
        elif failure_mode == FailureMode.SLIPPAGE_EXCEEDED:
            # Price moved - DO NOT RETRY
            ctx.should_retry = False
            ctx.reason = "Slippage exceeded - opportunity expired"
            
        elif failure_mode == FailureMode.INSUFFICIENT_FUNDS:
            # Balance too low - DO NOT RETRY
            ctx.should_retry = False
            ctx.reason = f"Insufficient funds: ${ctx.balance_at_failure or 0:.2f}"
            
        elif failure_mode == FailureMode.ACCOUNT_MISSING:
            # Account not created - RETRY ONCE after creating
            ctx.should_retry = attempt_number == 1
            ctx.retry_delay_ms = 100  # Short delay for account creation
            ctx.reason = "Account missing - create and retry" if ctx.should_retry else "Account creation failed"
            
        elif failure_mode == FailureMode.COMPUTE_EXCEEDED:
            # OOM - DO NOT RETRY (bundle design issue)
            ctx.should_retry = False
            ctx.reason = f"Compute exceeded ({ctx.compute_units_used or 0} units) - bundle too complex"
            
        elif failure_mode == FailureMode.NETWORK_ERROR:
            # Network issue - RETRY with backoff
            ctx.should_retry = True
            ctx.retry_delay_ms = self._exponential_backoff_with_jitter(attempt_number)
            ctx.reason = "Network error - retry with backoff"
            
        elif failure_mode == FailureMode.RATE_LIMITED:
            # Rate limit - RETRY with longer backoff
            ctx.should_retry = True
            ctx.retry_delay_ms = self._exponential_backoff_with_jitter(attempt_number) * 2
            ctx.reason = "Rate limited - retry with extended backoff"
            
        elif failure_mode == FailureMode.INVALID_BUNDLE:
            # Malformed bundle - DO NOT RETRY
            ctx.should_retry = False
            ctx.reason = "Invalid bundle - fix construction logic"
            
        else:
            # Unknown failure - conservative retry
            ctx.should_retry = attempt_number <= 2
            ctx.retry_delay_ms = self._exponential_backoff_with_jitter(attempt_number)
            ctx.reason = "Unknown failure - conservative retry"
        
        logger.info(
            f"{'🔄 RETRY' if ctx.should_retry else '❌ ABORT'}: {bundle_id[:8]} | "
            f"{failure_mode.value} | Attempt {attempt_number}/{self.max_retries} | "
            f"{ctx.reason}"
        )
        
        return ctx
    
    def _exponential_backoff_with_jitter(self, attempt: int) -> int:
        """
        Calculate exponential backoff with jitter
        
        Formula: base * (2^attempt) + random_jitter
        
        Args:
            attempt: Attempt number (1-indexed)
            
        Returns:
            Delay in milliseconds
        """
        exponential = self.base_backoff_ms * (2 ** (attempt - 1))
        jitter = random.randint(0, int(exponential * 0.1))  # 10% jitter
        return exponential + jitter

class FailureAnalyzer:
    """
    Analyzes errors to classify failure modes
    """
    
    @staticmethod
    def classify_error(error_message: str, result: Dict = None) -> FailureMode:
        """
        Classify error into failure mode
        
        Args:
            error_message: Error message string
            result: Additional result data
            
        Returns:
            FailureMode enum
        """
        error_lower = error_message.lower()
        
        # Pattern matching for common errors
        if any(x in error_lower for x in ["timeout", "not included", "expired"]):
            return FailureMode.NOT_INCLUDED
        
        if any(x in error_lower for x in ["partial", "incomplete"]):
            return FailureMode.PARTIAL_EXECUTION
        
        if any(x in error_lower for x in ["revert", "reverted", "failed to execute"]):
            return FailureMode.REVERT
        
        if any(x in error_lower for x in ["slippage", "price impact"]):
            return FailureMode.SLIPPAGE_EXCEEDED
        
        if any(x in error_lower for x in ["insufficient funds", "insufficient balance", "balance"]):
            return FailureMode.INSUFFICIENT_FUNDS
        
        if any(x in error_lower for x in ["account does not exist", "account not found"]):
            return FailureMode.ACCOUNT_MISSING
        
        if any(x in error_lower for x in ["compute", "exceeded", "oom", "out of memory"]):
            return FailureMode.COMPUTE_EXCEEDED
        
        if any(x in error_lower for x in ["network", "connection", "unreachable"]):
            return FailureMode.NETWORK_ERROR
        
        if any(x in error_lower for x in ["rate limit", "too many requests", "429"]):
            return FailureMode.RATE_LIMITED
        
        if any(x in error_lower for x in ["invalid", "malformed", "parse error"]):
            return FailureMode.INVALID_BUNDLE
        
        return FailureMode.UNKNOWN
    
    @staticmethod
    def extract_diagnostics(error_message: str, context: Dict = None) -> Dict:
        """
        Extract diagnostic information from error
        
        Args:
            error_message: Error message
            context: Additional context
            
        Returns:
            Dictionary of diagnostic info
        """
        diagnostics = {}
        
        # Try to extract compute units
        import re
        compute_match = re.search(r'(\d+)\s*compute units', error_message, re.IGNORECASE)
        if compute_match:
            diagnostics['compute_units'] = int(compute_match.group(1))
        
        # Extract balance if present
        balance_match = re.search(r'\$?([\d.]+)\s*SOL', error_message)
        if balance_match:
            diagnostics['balance'] = float(balance_match.group(1))
        
        # Add context if provided
        if context:
            diagnostics.update(context)
        
        return diagnostics

class PreflightChecker:
    """
    Pre-flight checks to prevent common failures
    """
    
    def __init__(self, min_balance_sol: float = 0.1):
        self.min_balance_sol = min_balance_sol
    
    async def check_before_submit(
        self,
        bundle_metadata: Dict,
        wallet_balance: Optional[float] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Run pre-flight checks before submission
        
        Args:
            bundle_metadata: Bundle metadata
            wallet_balance: Current wallet balance in SOL
            
        Returns:
            (passed, error_message) tuple
        """
        checks = []
        
        # Check 1: Sufficient balance
        if wallet_balance is not None:
            if wallet_balance < self.min_balance_sol:
                return False, f"Insufficient balance: {wallet_balance:.4f} SOL < {self.min_balance_sol:.4f} SOL"
        
        # Check 2: Compute budget reasonable
        compute_units = bundle_metadata.get('max_compute_units', 0)
        if compute_units > 1_400_000:
            return False, f"Compute units too high: {compute_units}"
        
        # Check 3: Transaction size
        tx_count = len(bundle_metadata.get('legs', []))
        if tx_count > 5:
            return False, f"Too many transactions: {tx_count} (max 5)"
        
        # Check 4: Estimated profit positive
        profit = bundle_metadata.get('estimated_profit_usd', 0)
        if profit <= 0:
            return False, f"Non-positive profit: ${profit:.4f}"
        
        # Check 5: Tip reasonable
        tip = bundle_metadata.get('tip_lamports', 0)
        if tip > 10_000_000:  # 0.01 SOL
            return False, f"Tip too high: {tip} lamports"
        
        return True, None


# Example usage
if __name__ == "__main__":
    # Initialize policy
    policy = RetryPolicy(
        max_retries=3,
        base_backoff_ms=50,
        tip_escalation_factor=1.5
    )
    
    # Simulate failure scenarios
    scenarios = [
        (FailureMode.NOT_INCLUDED, "Bundle not included in block after 500ms"),
        (FailureMode.REVERT, "Transaction reverted: slippage exceeded"),
        (FailureMode.NETWORK_ERROR, "Connection timeout to relay"),
        (FailureMode.INSUFFICIENT_FUNDS, "Insufficient balance: 0.001 SOL"),
        (FailureMode.COMPUTE_EXCEEDED, "Compute units exceeded: 1500000 units used")
    ]
    
    print("🧪 Testing Retry Policy:\n")
    
    for mode, error in scenarios:
        print(f"\n{'='*60}")
        print(f"Scenario: {mode.value}")
        print(f"Error: {error}")
        print("-" * 60)
        
        for attempt in range(1, 4):
            ctx = policy.evaluate_failure(
                bundle_id="test-bundle-123",
                failure_mode=mode,
                error_message=error,
                attempt_number=attempt,
                current_tip=10_000
            )
            
            print(f"\nAttempt {attempt}:")
            print(f"  Retry: {ctx.should_retry}")
            print(f"  Reason: {ctx.reason}")
            if ctx.should_retry:
                print(f"  Delay: {ctx.retry_delay_ms}ms")
                print(f"  Tip Multiplier: {ctx.tip_multiplier:.2f}x")
            
            if not ctx.should_retry:
                break
    
    print("\n" + "="*60)
    print("\n✅ Retry policy test complete")
