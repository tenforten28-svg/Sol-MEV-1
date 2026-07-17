"""
REPLAY v1 - Decision Determinism Validation
============================================
Replays stored opportunities through current decision engine
to verify determinism and analyze decision quality.

CLI Usage:
    python -m bot.replay.replay --from 2024-01-01 --to 2024-01-02 --mode decisions

Gate: >=95% decisions must match on the same window.
"""

import argparse
import json
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..storage import get_storage, SQLiteStorage
from ..alpha import calculate_ev_net, EVCalculation
from ..events import DecisionAction

logger = logging.getLogger('replay')

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ReplayResult:
    """Result of replaying a single opportunity"""
    event_id: str
    fingerprint: str
    original_action: str
    replayed_action: str
    matched: bool
    original_reasons: List[str]
    replayed_reasons: List[str]
    mismatch_reason: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'event_id': self.event_id,
            'fingerprint': self.fingerprint,
            'original_action': self.original_action,
            'replayed_action': self.replayed_action,
            'matched': self.matched,
            'original_reasons': self.original_reasons,
            'replayed_reasons': self.replayed_reasons,
            'mismatch_reason': self.mismatch_reason
        }


@dataclass
class ReplaySummary:
    """Summary of replay run"""
    total_decisions: int = 0
    matches: int = 0
    mismatches: int = 0
    match_rate: float = 0.0
    mismatch_details: List[Dict] = field(default_factory=list)
    
    # Breakdown by original action
    original_execute_count: int = 0
    original_skip_count: int = 0
    
    # Breakdown by replayed action
    replayed_execute_count: int = 0
    replayed_skip_count: int = 0
    
    # Mismatch types
    execute_to_skip: int = 0  # Would have executed, now skip
    skip_to_execute: int = 0  # Would have skipped, now execute
    
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'total_decisions': self.total_decisions,
            'matches': self.matches,
            'mismatches': self.mismatches,
            'match_rate': f"{self.match_rate:.2f}%",
            'original_execute_count': self.original_execute_count,
            'original_skip_count': self.original_skip_count,
            'replayed_execute_count': self.replayed_execute_count,
            'replayed_skip_count': self.replayed_skip_count,
            'execute_to_skip': self.execute_to_skip,
            'skip_to_execute': self.skip_to_execute,
            'duration_seconds': self.duration_seconds,
            'mismatch_sample': self.mismatch_details[:10]  # First 10 mismatches
        }


# ============================================================================
# REPLAY RUNNER
# ============================================================================

class ReplayRunner:
    """
    Replays stored opportunities through the decision engine.
    
    Loads opportunity_detected events from SQLite, runs them through
    the current decision engine, and compares to stored decision events.
    """
    
    def __init__(self, storage: Optional[SQLiteStorage] = None):
        self.storage = storage or get_storage()
        self.results: List[ReplayResult] = []
        self.summary = ReplaySummary()
    
    def load_opportunities(
        self,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        limit: int = 10000
    ) -> List[Dict]:
        """Load opportunity_detected events from storage"""
        events = self.storage.get_events(
            event_type='opportunity_detected',
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit
        )
        logger.info(f"Loaded {len(events)} opportunities")
        return events
    
    def load_decisions(
        self,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        limit: int = 10000
    ) -> Dict[str, Dict]:
        """Load decision events indexed by fingerprint + timestamp"""
        events = self.storage.get_events(
            event_type='decision',
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit
        )
        
        # Index by fingerprint for fast lookup
        decisions = {}
        for event in events:
            header = event.get('header', {})
            fingerprint = header.get('fingerprint')
            ts = header.get('ts_ms', 0)
            
            if fingerprint:
                key = f"{fingerprint}_{ts}"
                decisions[key] = event
        
        logger.info(f"Loaded {len(decisions)} decisions")
        return decisions
    
    def replay_decision(self, opportunity: Dict) -> EVCalculation:
        """
        Replay a single opportunity through the decision engine.
        
        Uses the stored opportunity payload to make a decision
        with the current decision engine.
        """
        payload = opportunity.get('payload', {})
        
        # Extract decision inputs from opportunity
        expected_profit = payload.get('estimated_profit_usd', 0)
        spread_bps = payload.get('spread_bps', 0)
        optimal_size = payload.get('optimal_size_usd', 1000)
        
        # Get liquidity from snapshots
        liquidity_depth = 100000  # Default
        snapshots = payload.get('liquidity_snapshots', [])
        if snapshots:
            depths = [s.get('depth_usd', 100000) for s in snapshots]
            liquidity_depth = min(depths) if depths else 100000
        
        # Run through current decision engine
        ev_result = calculate_ev_net(
            expected_profit_usd=expected_profit,
            trade_size_usd=optimal_size,
            spread_bps=spread_bps,
            liquidity_depth_usd=liquidity_depth,
            p_success=0.7  # Default assumption
        )
        
        return ev_result
    
    def compare_decision(
        self,
        opportunity: Dict,
        original_decision: Optional[Dict],
        replayed_result: EVCalculation
    ) -> ReplayResult:
        """Compare original decision to replayed decision"""
        header = opportunity.get('header', {})
        event_id = header.get('event_id', 'unknown')
        fingerprint = header.get('fingerprint', 'unknown')
        
        # Determine replayed action
        replayed_action = DecisionAction.EXECUTE.value if replayed_result.should_execute else DecisionAction.SKIP.value
        replayed_reasons = replayed_result.reasons
        
        # Get original decision
        if original_decision:
            orig_payload = original_decision.get('payload', {})
            original_action = orig_payload.get('action', 'SKIP')
            original_reasons = orig_payload.get('reasons', [])
        else:
            # No stored decision found - assume SKIP
            original_action = 'SKIP'
            original_reasons = ['no_decision_recorded']
        
        # Compare
        matched = original_action == replayed_action
        
        mismatch_reason = None
        if not matched:
            mismatch_reason = f"Original: {original_action}, Replayed: {replayed_action}"
        
        return ReplayResult(
            event_id=event_id,
            fingerprint=fingerprint,
            original_action=original_action,
            replayed_action=replayed_action,
            matched=matched,
            original_reasons=original_reasons,
            replayed_reasons=replayed_reasons,
            mismatch_reason=mismatch_reason
        )
    
    def run(
        self,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        speed_multiplier: float = 1.0,
        limit: int = 10000
    ) -> ReplaySummary:
        """
        Run full replay.
        
        Args:
            from_ts: Start timestamp (ms)
            to_ts: End timestamp (ms)
            speed_multiplier: Playback speed (not used in decisions mode)
            limit: Max events to process
        
        Returns:
            ReplaySummary with results
        """
        start_time = time.time()
        
        # Load data
        opportunities = self.load_opportunities(from_ts, to_ts, limit)
        decisions = self.load_decisions(from_ts, to_ts, limit)
        
        self.results = []
        self.summary = ReplaySummary()
        
        for opp in opportunities:
            header = opp.get('header', {})
            fingerprint = header.get('fingerprint')
            ts = header.get('ts_ms', 0)
            
            # Find matching decision
            key = f"{fingerprint}_{ts}"
            original_decision = decisions.get(key)
            
            # If no exact match, try to find closest decision
            if not original_decision and fingerprint:
                for k, v in decisions.items():
                    if k.startswith(fingerprint):
                        original_decision = v
                        break
            
            # Replay through decision engine
            replayed_result = self.replay_decision(opp)
            
            # Compare
            result = self.compare_decision(opp, original_decision, replayed_result)
            self.results.append(result)
            
            # Update summary
            self.summary.total_decisions += 1
            
            if result.matched:
                self.summary.matches += 1
            else:
                self.summary.mismatches += 1
                self.summary.mismatch_details.append(result.to_dict())
                
                # Track mismatch types
                if result.original_action == 'EXECUTE' and result.replayed_action == 'SKIP':
                    self.summary.execute_to_skip += 1
                elif result.original_action == 'SKIP' and result.replayed_action == 'EXECUTE':
                    self.summary.skip_to_execute += 1
            
            # Track action distribution
            if result.original_action == 'EXECUTE':
                self.summary.original_execute_count += 1
            else:
                self.summary.original_skip_count += 1
            
            if result.replayed_action == 'EXECUTE':
                self.summary.replayed_execute_count += 1
            else:
                self.summary.replayed_skip_count += 1
        
        # Calculate match rate
        if self.summary.total_decisions > 0:
            self.summary.match_rate = (self.summary.matches / self.summary.total_decisions) * 100
        
        self.summary.duration_seconds = time.time() - start_time
        
        return self.summary
    
    def print_report(self):
        """Print formatted replay report"""
        print("\n" + "=" * 60)
        print("REPLAY REPORT")
        print("=" * 60)
        print(f"Total decisions: {self.summary.total_decisions}")
        print(f"Matches: {self.summary.matches}")
        print(f"Mismatches: {self.summary.mismatches}")
        print(f"Match rate: {self.summary.match_rate:.2f}%")
        print("-" * 40)
        print(f"Original EXECUTE: {self.summary.original_execute_count}")
        print(f"Original SKIP: {self.summary.original_skip_count}")
        print(f"Replayed EXECUTE: {self.summary.replayed_execute_count}")
        print(f"Replayed SKIP: {self.summary.replayed_skip_count}")
        print("-" * 40)
        print(f"Execute->Skip: {self.summary.execute_to_skip}")
        print(f"Skip->Execute: {self.summary.skip_to_execute}")
        print("-" * 40)
        print(f"Duration: {self.summary.duration_seconds:.2f}s")
        
        # Gate check
        gate_passed = self.summary.match_rate >= 95.0
        status = "PASSED" if gate_passed else "FAILED"
        print("=" * 60)
        print(f"GATE (>=95% match): {status}")
        print("=" * 60)
        
        # Sample mismatches
        if self.summary.mismatch_details:
            print("\nSAMPLE MISMATCHES:")
            for i, mm in enumerate(self.summary.mismatch_details[:5]):
                print(f"  {i+1}. {mm['fingerprint'][:30]}... | {mm['mismatch_reason']}")


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def run_replay(
    from_ts: Optional[int] = None,
    to_ts: Optional[int] = None,
    limit: int = 10000
) -> ReplaySummary:
    """Convenience function to run replay"""
    runner = ReplayRunner()
    return runner.run(from_ts, to_ts, limit=limit)


def compare_decisions(
    opportunity: Dict,
    original_decision: Dict
) -> ReplayResult:
    """Compare a single opportunity's decisions"""
    runner = ReplayRunner()
    replayed = runner.replay_decision(opportunity)
    return runner.compare_decision(opportunity, original_decision, replayed)


# ============================================================================
# CLI
# ============================================================================

def parse_timestamp(ts_str: str) -> int:
    """Parse timestamp string to milliseconds"""
    try:
        # Try ISO format
        dt = datetime.fromisoformat(ts_str)
        return int(dt.timestamp() * 1000)
    except:
        # Try as integer
        return int(ts_str)


def main():
    parser = argparse.ArgumentParser(description='Replay decisions from stored events')
    parser.add_argument('--from', dest='from_ts', type=str, help='Start timestamp (ISO or ms)')
    parser.add_argument('--to', dest='to_ts', type=str, help='End timestamp (ISO or ms)')
    parser.add_argument('--speed', type=float, default=1.0, help='Playback speed multiplier')
    parser.add_argument('--mode', choices=['decisions', 'full'], default='decisions', help='Replay mode')
    parser.add_argument('--limit', type=int, default=10000, help='Max events to process')
    parser.add_argument('--output', type=str, help='Output file for JSON report')
    
    args = parser.parse_args()
    
    # Parse timestamps
    from_ts = parse_timestamp(args.from_ts) if args.from_ts else None
    to_ts = parse_timestamp(args.to_ts) if args.to_ts else None
    
    # Run replay
    logger.info(f"Starting replay: from={from_ts}, to={to_ts}, mode={args.mode}")
    
    runner = ReplayRunner()
    summary = runner.run(from_ts, to_ts, args.speed, args.limit)
    
    # Print report
    runner.print_report()
    
    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(summary.to_dict(), f, indent=2)
        print(f"\nReport saved to: {args.output}")
    
    # Exit with appropriate code
    exit_code = 0 if summary.match_rate >= 95.0 else 1
    exit(exit_code)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    main()
