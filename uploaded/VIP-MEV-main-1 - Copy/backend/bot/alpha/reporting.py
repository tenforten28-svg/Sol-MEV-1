"""
DAILY REPORTING - Performance Analytics
=======================================
Step 13: Generate daily performance reports.

Reports include:
- PnL by fingerprint
- Top failures
- Crowding distribution
- Half-life stats
- Success rate by state
- Skipped opportunities analysis

Gate: You can answer "why did we lose money yesterday?" quickly.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger('reporting')

# ============================================================================
# CONFIG
# ============================================================================

REPORTS_DIR = Path(__file__).parent.parent / 'data' / 'reports'

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class FingerprintStats:
    """Statistics for a single fingerprint"""
    fingerprint: str
    total_opportunities: int = 0
    executed_trades: int = 0
    successful_trades: int = 0
    failed_trades: int = 0
    skipped_opportunities: int = 0
    total_pnl_usd: float = 0.0
    total_fees_usd: float = 0.0
    avg_spread_bps: float = 0.0
    avg_latency_ms: float = 0.0
    success_rate: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'fingerprint': self.fingerprint[:50] + '...' if len(self.fingerprint) > 50 else self.fingerprint,
            'total_opportunities': self.total_opportunities,
            'executed_trades': self.executed_trades,
            'successful_trades': self.successful_trades,
            'failed_trades': self.failed_trades,
            'skipped_opportunities': self.skipped_opportunities,
            'total_pnl_usd': round(self.total_pnl_usd, 4),
            'total_fees_usd': round(self.total_fees_usd, 4),
            'net_pnl_usd': round(self.total_pnl_usd - self.total_fees_usd, 4),
            'avg_spread_bps': round(self.avg_spread_bps, 2),
            'avg_latency_ms': round(self.avg_latency_ms, 1),
            'success_rate': round(self.success_rate * 100, 1)
        }


@dataclass
class FailureStats:
    """Statistics for failure types"""
    failure_tag: str
    count: int = 0
    examples: List[str] = field(default_factory=list)
    fingerprints_affected: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'failure_tag': self.failure_tag,
            'count': self.count,
            'examples': self.examples[:3],  # First 3 examples
            'unique_routes_affected': len(set(self.fingerprints_affected))
        }


@dataclass
class SkippedAnalysis:
    """Analysis of skipped opportunities"""
    skip_reason: str
    count: int = 0
    would_have_succeeded: int = 0  # Based on post-analysis
    avg_potential_profit: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'skip_reason': self.skip_reason,
            'count': self.count,
            'would_have_succeeded': self.would_have_succeeded,
            'missed_profit_est': round(self.would_have_succeeded * self.avg_potential_profit, 4)
        }


@dataclass
class DailyReport:
    """Complete daily report"""
    date: str
    generated_at: str
    
    # Summary
    total_opportunities: int = 0
    total_executed: int = 0
    total_successful: int = 0
    total_failed: int = 0
    total_skipped: int = 0
    
    # PnL
    gross_pnl_usd: float = 0.0
    total_fees_usd: float = 0.0
    net_pnl_usd: float = 0.0
    
    # Rates
    execution_rate: float = 0.0
    success_rate: float = 0.0
    
    # Breakdown
    pnl_by_fingerprint: List[Dict] = field(default_factory=list)
    top_failures: List[Dict] = field(default_factory=list)
    crowding_distribution: Dict = field(default_factory=dict)
    half_life_stats: Dict = field(default_factory=dict)
    success_by_state: Dict = field(default_factory=dict)
    skipped_analysis: List[Dict] = field(default_factory=list)
    
    # Timing
    latency_stats: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'date': self.date,
            'generated_at': self.generated_at,
            'summary': {
                'total_opportunities': self.total_opportunities,
                'total_executed': self.total_executed,
                'total_successful': self.total_successful,
                'total_failed': self.total_failed,
                'total_skipped': self.total_skipped,
                'execution_rate': f"{self.execution_rate:.1%}",
                'success_rate': f"{self.success_rate:.1%}"
            },
            'pnl': {
                'gross_pnl_usd': round(self.gross_pnl_usd, 4),
                'total_fees_usd': round(self.total_fees_usd, 4),
                'net_pnl_usd': round(self.net_pnl_usd, 4)
            },
            'pnl_by_fingerprint': self.pnl_by_fingerprint[:10],  # Top 10
            'top_failures': self.top_failures[:10],
            'crowding_distribution': self.crowding_distribution,
            'half_life_stats': self.half_life_stats,
            'success_by_state': self.success_by_state,
            'skipped_analysis': self.skipped_analysis,
            'latency_stats': self.latency_stats
        }


# ============================================================================
# REPORT GENERATOR
# ============================================================================

class ReportGenerator:
    """
    Generates daily performance reports from event data.
    
    Uses SQLite storage to query events and compute statistics.
    """
    
    def __init__(self, storage=None):
        """
        Initialize report generator.
        
        Args:
            storage: SQLiteStorage instance (optional, will use global if not provided)
        """
        self._storage = storage
    
    def _get_storage(self):
        """Get storage instance"""
        if self._storage is None:
            from ..storage import get_storage
            self._storage = get_storage()
        return self._storage
    
    def generate_daily_report(
        self,
        date: Optional[str] = None,
        save_to_file: bool = True
    ) -> DailyReport:
        """
        Generate report for a specific date.
        
        Args:
            date: Date string (YYYY-MM-DD) or None for yesterday
            save_to_file: Whether to save report to file
        
        Returns:
            DailyReport with all statistics
        """
        # Determine date range
        if date is None:
            target_date = datetime.now() - timedelta(days=1)
        else:
            target_date = datetime.strptime(date, '%Y-%m-%d')
        
        date_str = target_date.strftime('%Y-%m-%d')
        start_ts = int(target_date.replace(hour=0, minute=0, second=0).timestamp() * 1000)
        end_ts = int(target_date.replace(hour=23, minute=59, second=59).timestamp() * 1000)
        
        logger.info(f"Generating report for {date_str}")
        
        # Load events
        storage = self._get_storage()
        
        opportunities = storage.get_events('opportunity_detected', start_ts, end_ts, limit=50000)
        decisions = storage.get_events('decision', start_ts, end_ts, limit=50000)
        tx_results = storage.get_events('tx_result', start_ts, end_ts, limit=50000)
        pnl_events = storage.get_events('pnl_realized', start_ts, end_ts, limit=50000)
        
        logger.info(f"Loaded: {len(opportunities)} opportunities, {len(decisions)} decisions, "
                   f"{len(tx_results)} tx_results, {len(pnl_events)} pnl_events")
        
        # Initialize report
        report = DailyReport(
            date=date_str,
            generated_at=datetime.now().isoformat()
        )
        
        # Process data
        report = self._compute_summary(report, opportunities, decisions, tx_results, pnl_events)
        report = self._compute_pnl_by_fingerprint(report, opportunities, decisions, tx_results, pnl_events)
        report = self._compute_failure_stats(report, tx_results)
        report = self._compute_crowding_distribution(report, decisions)
        report = self._compute_success_by_state(report, decisions, tx_results)
        report = self._compute_skipped_analysis(report, opportunities, decisions, tx_results)
        report = self._compute_latency_stats(report, opportunities, decisions, tx_results)
        
        # Save to file
        if save_to_file:
            self._save_report(report)
        
        return report
    
    def _compute_summary(
        self,
        report: DailyReport,
        opportunities: List[Dict],
        decisions: List[Dict],
        tx_results: List[Dict],
        pnl_events: List[Dict]
    ) -> DailyReport:
        """Compute summary statistics"""
        report.total_opportunities = len(opportunities)
        
        # Count decisions
        execute_count = 0
        skip_count = 0
        for d in decisions:
            payload = d.get('payload', {})
            action = payload.get('action', 'SKIP')
            if action == 'EXECUTE':
                execute_count += 1
            else:
                skip_count += 1
        
        report.total_executed = execute_count
        report.total_skipped = skip_count
        
        # Count results
        success_count = 0
        fail_count = 0
        for tx in tx_results:
            payload = tx.get('payload', {})
            status = payload.get('status', '')
            if status == 'SUCCESS':
                success_count += 1
            else:
                fail_count += 1
        
        report.total_successful = success_count
        report.total_failed = fail_count
        
        # Compute rates
        if report.total_opportunities > 0:
            report.execution_rate = report.total_executed / report.total_opportunities
        if report.total_executed > 0:
            report.success_rate = report.total_successful / report.total_executed
        
        # Compute PnL
        for pnl in pnl_events:
            payload = pnl.get('payload', {})
            report.gross_pnl_usd += payload.get('profit_usd', 0)
            report.total_fees_usd += payload.get('fees_usd', 0)
        
        report.net_pnl_usd = report.gross_pnl_usd - report.total_fees_usd
        
        return report
    
    def _compute_pnl_by_fingerprint(
        self,
        report: DailyReport,
        opportunities: List[Dict],
        decisions: List[Dict],
        tx_results: List[Dict],
        pnl_events: List[Dict]
    ) -> DailyReport:
        """Compute PnL breakdown by fingerprint"""
        stats: Dict[str, FingerprintStats] = {}
        
        # Index events by fingerprint
        for opp in opportunities:
            fp = opp.get('header', {}).get('fingerprint', 'unknown')
            if fp not in stats:
                stats[fp] = FingerprintStats(fingerprint=fp)
            stats[fp].total_opportunities += 1
            
            payload = opp.get('payload', {})
            stats[fp].avg_spread_bps += payload.get('spread_bps', 0)
        
        for d in decisions:
            fp = d.get('header', {}).get('fingerprint', 'unknown')
            if fp not in stats:
                stats[fp] = FingerprintStats(fingerprint=fp)
            
            payload = d.get('payload', {})
            if payload.get('action') == 'EXECUTE':
                stats[fp].executed_trades += 1
            else:
                stats[fp].skipped_opportunities += 1
        
        for tx in tx_results:
            fp = tx.get('header', {}).get('fingerprint', 'unknown')
            if fp not in stats:
                continue
            
            payload = tx.get('payload', {})
            if payload.get('status') == 'SUCCESS':
                stats[fp].successful_trades += 1
            else:
                stats[fp].failed_trades += 1
        
        for pnl in pnl_events:
            fp = pnl.get('header', {}).get('fingerprint', 'unknown')
            if fp not in stats:
                continue
            
            payload = pnl.get('payload', {})
            stats[fp].total_pnl_usd += payload.get('profit_usd', 0)
            stats[fp].total_fees_usd += payload.get('fees_usd', 0)
        
        # Finalize stats
        for fp, s in stats.items():
            if s.total_opportunities > 0:
                s.avg_spread_bps /= s.total_opportunities
            if s.executed_trades > 0:
                s.success_rate = s.successful_trades / s.executed_trades
        
        # Sort by net PnL
        sorted_stats = sorted(
            stats.values(),
            key=lambda x: x.total_pnl_usd - x.total_fees_usd,
            reverse=True
        )
        
        report.pnl_by_fingerprint = [s.to_dict() for s in sorted_stats[:20]]
        
        return report
    
    def _compute_failure_stats(
        self,
        report: DailyReport,
        tx_results: List[Dict]
    ) -> DailyReport:
        """Compute failure statistics"""
        failures: Dict[str, FailureStats] = {}
        
        for tx in tx_results:
            payload = tx.get('payload', {})
            if payload.get('status') == 'SUCCESS':
                continue
            
            tag = payload.get('failure_tag', 'OTHER')
            fp = tx.get('header', {}).get('fingerprint', 'unknown')
            err = payload.get('err', '')[:100]  # Truncate error
            
            if tag not in failures:
                failures[tag] = FailureStats(failure_tag=tag)
            
            failures[tag].count += 1
            failures[tag].fingerprints_affected.append(fp)
            if err and len(failures[tag].examples) < 5:
                failures[tag].examples.append(err)
        
        # Sort by count
        sorted_failures = sorted(failures.values(), key=lambda x: x.count, reverse=True)
        report.top_failures = [f.to_dict() for f in sorted_failures]
        
        return report
    
    def _compute_crowding_distribution(
        self,
        report: DailyReport,
        decisions: List[Dict]
    ) -> DailyReport:
        """Compute crowding score distribution"""
        buckets = {'low': 0, 'medium': 0, 'high': 0}
        
        for d in decisions:
            payload = d.get('payload', {})
            crowding = payload.get('crowding_score', 0)
            
            if crowding < 0.4:
                buckets['low'] += 1
            elif crowding < 0.7:
                buckets['medium'] += 1
            else:
                buckets['high'] += 1
        
        total = sum(buckets.values())
        if total > 0:
            report.crowding_distribution = {
                'low_pct': round(buckets['low'] / total * 100, 1),
                'medium_pct': round(buckets['medium'] / total * 100, 1),
                'high_pct': round(buckets['high'] / total * 100, 1),
                'counts': buckets
            }
        
        return report
    
    def _compute_success_by_state(
        self,
        report: DailyReport,
        decisions: List[Dict],
        tx_results: List[Dict]
    ) -> DailyReport:
        """Compute success rate by Markov state"""
        # Index tx_results by event_id (approximate via fingerprint + time)
        tx_by_fp: Dict[str, List[Dict]] = defaultdict(list)
        for tx in tx_results:
            fp = tx.get('header', {}).get('fingerprint', '')
            tx_by_fp[fp].append(tx)
        
        state_stats = defaultdict(lambda: {'total': 0, 'success': 0})
        
        for d in decisions:
            payload = d.get('payload', {})
            state = payload.get('markov_state', 'NEUTRAL')
            action = payload.get('action', 'SKIP')
            
            if action != 'EXECUTE':
                continue
            
            fp = d.get('header', {}).get('fingerprint', '')
            state_stats[state]['total'] += 1
            
            # Check if this trade succeeded
            txs = tx_by_fp.get(fp, [])
            for tx in txs:
                if tx.get('payload', {}).get('status') == 'SUCCESS':
                    state_stats[state]['success'] += 1
                    break
        
        report.success_by_state = {}
        for state, counts in state_stats.items():
            success_rate = counts['success'] / counts['total'] if counts['total'] > 0 else 0
            report.success_by_state[state] = {
                'total': counts['total'],
                'success': counts['success'],
                'success_rate': f"{success_rate:.1%}"
            }
        
        return report
    
    def _compute_skipped_analysis(
        self,
        report: DailyReport,
        opportunities: List[Dict],
        decisions: List[Dict],
        tx_results: List[Dict]
    ) -> DailyReport:
        """Analyze skipped opportunities"""
        skip_reasons: Dict[str, SkippedAnalysis] = {}
        
        for d in decisions:
            payload = d.get('payload', {})
            if payload.get('action') == 'EXECUTE':
                continue
            
            reasons = payload.get('reasons', ['unknown'])
            main_reason = reasons[0] if reasons else 'unknown'
            
            if main_reason not in skip_reasons:
                skip_reasons[main_reason] = SkippedAnalysis(skip_reason=main_reason)
            
            skip_reasons[main_reason].count += 1
            
            # Estimate potential profit
            ev = payload.get('ev_raw_est', 0)
            skip_reasons[main_reason].avg_potential_profit += ev
        
        # Finalize
        for reason, analysis in skip_reasons.items():
            if analysis.count > 0:
                analysis.avg_potential_profit /= analysis.count
        
        sorted_analysis = sorted(skip_reasons.values(), key=lambda x: x.count, reverse=True)
        report.skipped_analysis = [a.to_dict() for a in sorted_analysis[:10]]
        
        return report
    
    def _compute_latency_stats(
        self,
        report: DailyReport,
        opportunities: List[Dict],
        decisions: List[Dict],
        tx_results: List[Dict]
    ) -> DailyReport:
        """Compute latency statistics"""
        latencies = {
            'detect': [],
            'decision': [],
            'submission': [],
            'confirmation': []
        }
        
        for opp in opportunities:
            payload = opp.get('payload', {})
            if 'detect_latency_ms' in payload:
                latencies['detect'].append(payload['detect_latency_ms'])
        
        for d in decisions:
            payload = d.get('payload', {})
            if 'decision_latency_ms' in payload:
                latencies['decision'].append(payload['decision_latency_ms'])
        
        for tx in tx_results:
            payload = tx.get('payload', {})
            if 'confirmation_ms' in payload:
                latencies['confirmation'].append(payload['confirmation_ms'])
        
        # Compute percentiles
        def compute_percentiles(data: List[float]) -> Dict:
            if not data:
                return {'p50': 0, 'p90': 0, 'p99': 0}
            sorted_data = sorted(data)
            n = len(sorted_data)
            return {
                'p50': sorted_data[int(n * 0.5)],
                'p90': sorted_data[int(n * 0.9)],
                'p99': sorted_data[int(n * 0.99)] if n > 100 else sorted_data[-1],
                'count': n
            }
        
        report.latency_stats = {
            stage: compute_percentiles(data)
            for stage, data in latencies.items()
        }
        
        return report
    
    def _save_report(self, report: DailyReport):
        """Save report to file"""
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        
        filename = f"daily_report_{report.date}.json"
        filepath = REPORTS_DIR / filename
        
        with open(filepath, 'w') as f:
            json.dump(report.to_dict(), f, indent=2)
        
        logger.info(f"Report saved to {filepath}")


# ============================================================================
# CLI & CONVENIENCE
# ============================================================================

def generate_report(date: Optional[str] = None) -> DailyReport:
    """Generate daily report"""
    generator = ReportGenerator()
    return generator.generate_daily_report(date)


def print_report(report: DailyReport):
    """Print formatted report to console"""
    print("\n" + "=" * 70)
    print(f"DAILY REPORT: {report.date}")
    print("=" * 70)
    
    print("\n📊 SUMMARY")
    print("-" * 40)
    print(f"  Opportunities:    {report.total_opportunities}")
    print(f"  Executed:         {report.total_executed} ({report.execution_rate:.1%})")
    print(f"  Successful:       {report.total_successful}")
    print(f"  Failed:           {report.total_failed}")
    print(f"  Skipped:          {report.total_skipped}")
    print(f"  Success Rate:     {report.success_rate:.1%}")
    
    print("\n💰 PnL")
    print("-" * 40)
    print(f"  Gross PnL:        ${report.gross_pnl_usd:,.4f}")
    print(f"  Fees:             ${report.total_fees_usd:,.4f}")
    print(f"  Net PnL:          ${report.net_pnl_usd:,.4f}")
    
    if report.pnl_by_fingerprint:
        print("\n📈 TOP ROUTES BY PnL")
        print("-" * 40)
        for i, fp in enumerate(report.pnl_by_fingerprint[:5]):
            print(f"  {i+1}. {fp['fingerprint']}")
            print(f"     Net: ${fp['net_pnl_usd']:,.4f} | Success: {fp['success_rate']}%")
    
    if report.top_failures:
        print("\n❌ TOP FAILURES")
        print("-" * 40)
        for f in report.top_failures[:5]:
            print(f"  {f['failure_tag']}: {f['count']} ({f['unique_routes_affected']} routes)")
    
    if report.crowding_distribution:
        print("\n👥 CROWDING DISTRIBUTION")
        print("-" * 40)
        cd = report.crowding_distribution
        print(f"  Low:     {cd.get('low_pct', 0)}%")
        print(f"  Medium:  {cd.get('medium_pct', 0)}%")
        print(f"  High:    {cd.get('high_pct', 0)}%")
    
    if report.success_by_state:
        print("\n🎯 SUCCESS BY STATE")
        print("-" * 40)
        for state, stats in report.success_by_state.items():
            print(f"  {state}: {stats['success']}/{stats['total']} = {stats['success_rate']}")
    
    print("\n" + "=" * 70)


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point for report generation"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate daily trading report')
    parser.add_argument('--date', type=str, help='Date (YYYY-MM-DD), default: yesterday')
    parser.add_argument('--output', type=str, help='Output directory')
    parser.add_argument('--no-save', action='store_true', help='Do not save to file')
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    generator = ReportGenerator()
    report = generator.generate_daily_report(
        date=args.date,
        save_to_file=not args.no_save
    )
    
    print_report(report)


if __name__ == "__main__":
    main()
