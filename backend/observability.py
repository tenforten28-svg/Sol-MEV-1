"""
Comprehensive Observability & KPI System
Grafana-ready metrics, dashboards, and alerting
"""
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
import json
import logging
from collections import deque, defaultdict

logger = logging.getLogger(__name__)

@dataclass
class BundleMetrics:
    """Comprehensive per-bundle metrics"""
    # Identifiers
    bundle_id: str
    strategy: str
    pair: str
    
    # Timestamps (ISO format for Grafana)
    detection_timestamp: str
    submit_timestamp: Optional[str] = None
    inclusion_timestamp: Optional[str] = None
    
    # Latencies (milliseconds)
    latency_detect_to_submit_ms: float = 0.0
    latency_submit_to_include_ms: float = 0.0
    latency_total_ms: float = 0.0
    
    # Financial
    estimated_profit: float = 0.0
    realized_profit: Optional[float] = None
    fees_paid: float = 0.0
    tip_paid: int = 0  # lamports
    tip_paid_sol: float = 0.0
    net_profit: Optional[float] = None
    tip_roi: Optional[float] = None  # tip / profit ratio
    
    # Execution
    success: bool = False
    failure_reason: Optional[str] = None
    inclusion_slot: Optional[int] = None
    confirmation_time_s: Optional[float] = None
    
    # Bundle details
    tx_count_in_bundle: int = 0
    compute_units_requested: int = 0
    compute_units_used: Optional[int] = None
    
    # Retry info
    retry_count: int = 0
    tip_escalations: int = 0
    
    def to_prometheus_format(self) -> List[str]:
        """Convert to Prometheus metrics format"""
        metrics = []
        
        labels = f'bundle_id="{self.bundle_id}",strategy="{self.strategy}",pair="{self.pair}"'
        
        # Success/failure
        metrics.append(f'bundle_success{{{labels}}} {int(self.success)}')
        
        # Latencies
        metrics.append(f'bundle_latency_detect_to_submit_ms{{{labels}}} {self.latency_detect_to_submit_ms}')
        metrics.append(f'bundle_latency_submit_to_include_ms{{{labels}}} {self.latency_submit_to_include_ms}')
        metrics.append(f'bundle_latency_total_ms{{{labels}}} {self.latency_total_ms}')
        
        # Financial
        metrics.append(f'bundle_estimated_profit{{{labels}}} {self.estimated_profit}')
        if self.realized_profit:
            metrics.append(f'bundle_realized_profit{{{labels}}} {self.realized_profit}')
            metrics.append(f'bundle_net_profit{{{labels}}} {self.net_profit or 0}')
        
        metrics.append(f'bundle_tip_paid_sol{{{labels}}} {self.tip_paid_sol}')
        metrics.append(f'bundle_fees_paid{{{labels}}} {self.fees_paid}')
        
        if self.tip_roi:
            metrics.append(f'bundle_tip_roi{{{labels}}} {self.tip_roi}')
        
        # Execution
        metrics.append(f'bundle_tx_count{{{labels}}} {self.tx_count_in_bundle}')
        metrics.append(f'bundle_compute_units{{{labels}}} {self.compute_units_requested}')
        metrics.append(f'bundle_retry_count{{{labels}}} {self.retry_count}')
        
        return metrics

class KPICollector:
    """
    Collects KPIs for Grafana dashboards
    
    Metrics Categories:
    1. Success & Failure Rates
    2. Latency Distribution
    3. Financial Performance
    4. Tip ROI Analysis
    5. Failure Analysis
    """
    
    def __init__(self, retention_hours: int = 24):
        self.retention_hours = retention_hours
        
        # Time-series data (bucketed by minute)
        self.timeseries: Dict[str, deque] = {
            "success_rate_1h": deque(maxlen=60),      # Last 60 minutes
            "success_rate_24h": deque(maxlen=1440),   # Last 24 hours
            "realized_pnl": deque(maxlen=1440),
            "tip_roi": deque(maxlen=1440),
            "latency_p50": deque(maxlen=1440),
            "latency_p99": deque(maxlen=1440)
        }
        
        # Per-strategy metrics
        self.strategy_metrics: Dict[str, Dict] = defaultdict(lambda: {
            "total_bundles": 0,
            "successful": 0,
            "failed": 0,
            "total_profit": 0.0,
            "total_tips": 0.0
        })
        
        # Failure analysis
        self.failure_counts: Dict[str, int] = defaultdict(int)
        self.failure_details: List[Dict] = []
        
        # All bundles (rolling window)
        self.all_bundles: deque = deque(maxlen=10000)
        
        # Alert state
        self.alert_state: Dict[str, bool] = {}
        self.last_alert_time: Dict[str, datetime] = {}
        
    def record_bundle(self, metrics: BundleMetrics):
        """Record bundle metrics"""
        self.all_bundles.append(metrics)
        
        # Update strategy metrics
        strategy = metrics.strategy
        self.strategy_metrics[strategy]["total_bundles"] += 1
        
        if metrics.success:
            self.strategy_metrics[strategy]["successful"] += 1
            if metrics.realized_profit:
                self.strategy_metrics[strategy]["total_profit"] += metrics.realized_profit
        else:
            self.strategy_metrics[strategy]["failed"] += 1
            self.failure_counts[metrics.failure_reason or "unknown"] += 1
            
            # Store failure details
            self.failure_details.append({
                "timestamp": metrics.detection_timestamp,
                "bundle_id": metrics.bundle_id,
                "reason": metrics.failure_reason,
                "strategy": metrics.strategy
            })
        
        if metrics.tip_paid_sol > 0:
            self.strategy_metrics[strategy]["total_tips"] += metrics.tip_paid_sol
        
        # Update time-series (done periodically)
        self._update_timeseries()
    
    def _update_timeseries(self):
        """Update time-series metrics (called periodically)"""
        now = datetime.now(timezone.utc)
        
        # Calculate success rates
        recent_1h = [b for b in self.all_bundles 
                     if self._parse_timestamp(b.detection_timestamp) > now - timedelta(hours=1)]
        recent_24h = [b for b in self.all_bundles
                      if self._parse_timestamp(b.detection_timestamp) > now - timedelta(hours=24)]
        
        # Success rate
        success_1h = (sum(1 for b in recent_1h if b.success) / len(recent_1h) * 100) if recent_1h else 0
        success_24h = (sum(1 for b in recent_24h if b.success) / len(recent_24h) * 100) if recent_24h else 0
        
        self.timeseries["success_rate_1h"].append({
            "timestamp": now.isoformat(),
            "value": success_1h
        })
        self.timeseries["success_rate_24h"].append({
            "timestamp": now.isoformat(),
            "value": success_24h
        })
        
        # P&L
        realized_pnl = sum(b.realized_profit or 0 for b in recent_24h if b.success)
        self.timeseries["realized_pnl"].append({
            "timestamp": now.isoformat(),
            "value": realized_pnl
        })
        
        # Latency percentiles
        latencies = [b.latency_total_ms for b in recent_24h if b.latency_total_ms > 0]
        if latencies:
            sorted_lat = sorted(latencies)
            p50 = sorted_lat[int(len(sorted_lat) * 0.5)]
            p99 = sorted_lat[int(len(sorted_lat) * 0.99)]
            
            self.timeseries["latency_p50"].append({
                "timestamp": now.isoformat(),
                "value": p50
            })
            self.timeseries["latency_p99"].append({
                "timestamp": now.isoformat(),
                "value": p99
            })
    
    def _parse_timestamp(self, ts: str) -> datetime:
        """Parse ISO timestamp"""
        try:
            return datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except:
            return datetime.now(timezone.utc)
    
    def get_grafana_dashboard_data(self) -> Dict:
        """
        Get data formatted for Grafana dashboard
        
        Returns JSON compatible with Grafana's SimpleJSON datasource
        """
        now = datetime.now(timezone.utc)
        recent_24h = [b for b in self.all_bundles
                      if self._parse_timestamp(b.detection_timestamp) > now - timedelta(hours=24)]
        
        # Calculate current KPIs
        total_bundles = len(recent_24h)
        successful = sum(1 for b in recent_24h if b.success)
        success_rate = (successful / total_bundles * 100) if total_bundles > 0 else 0
        
        total_profit = sum(b.realized_profit or 0 for b in recent_24h if b.success)
        total_tips = sum(b.tip_paid_sol for b in recent_24h)
        net_pnl = total_profit - total_tips
        
        latencies = [b.latency_total_ms for b in recent_24h if b.latency_total_ms > 0]
        median_latency = sorted(latencies)[len(latencies)//2] if latencies else 0
        p99_latency = sorted(latencies)[int(len(latencies)*0.99)] if latencies else 0
        
        # Tip ROI
        successful_bundles = [b for b in recent_24h if b.success and b.tip_roi]
        avg_tip_roi = (sum(b.tip_roi for b in successful_bundles) / len(successful_bundles)) if successful_bundles else 0
        
        return {
            "current_metrics": {
                "success_rate_24h": round(success_rate, 2),
                "total_bundles_24h": total_bundles,
                "successful_bundles_24h": successful,
                "failed_bundles_24h": total_bundles - successful,
                "realized_pnl_24h": round(total_profit, 4),
                "tips_paid_24h": round(total_tips, 4),
                "net_pnl_24h": round(net_pnl, 4),
                "median_latency_ms": round(median_latency, 2),
                "p99_latency_ms": round(p99_latency, 2),
                "avg_tip_roi": round(avg_tip_roi, 4)
            },
            "timeseries": {
                "success_rate_1h": list(self.timeseries["success_rate_1h"])[-60:],
                "success_rate_24h": list(self.timeseries["success_rate_24h"])[-1440:],
                "realized_pnl": list(self.timeseries["realized_pnl"])[-1440:],
                "latency_p50": list(self.timeseries["latency_p50"])[-1440:],
                "latency_p99": list(self.timeseries["latency_p99"])[-1440:]
            },
            "strategy_breakdown": dict(self.strategy_metrics),
            "failure_analysis": {
                "failure_counts": dict(self.failure_counts),
                "recent_failures": self.failure_details[-50:]
            }
        }
    
    def check_alerts(self) -> List[Dict]:
        """
        Check alert conditions and return active alerts
        
        Alert Thresholds:
        - success_rate < 70%
        - repeated failures (>5 in 10 min)
        - high revert rate (>30%)
        - oracle divergence (if applicable)
        """
        alerts = []
        now = datetime.now(timezone.utc)
        
        # Get recent bundles
        recent_10min = [b for b in self.all_bundles
                        if self._parse_timestamp(b.detection_timestamp) > now - timedelta(minutes=10)]
        recent_1h = [b for b in self.all_bundles
                     if self._parse_timestamp(b.detection_timestamp) > now - timedelta(hours=1)]
        
        # Alert 1: Low success rate
        if recent_1h:
            success_rate = sum(1 for b in recent_1h if b.success) / len(recent_1h) * 100
            if success_rate < 70:
                alerts.append({
                    "type": "LOW_SUCCESS_RATE",
                    "severity": "warning",
                    "message": f"Success rate {success_rate:.1f}% below 70% threshold",
                    "value": success_rate,
                    "threshold": 70,
                    "timestamp": now.isoformat()
                })
        
        # Alert 2: Repeated failures
        failed_10min = sum(1 for b in recent_10min if not b.success)
        if failed_10min > 5:
            alerts.append({
                "type": "REPEATED_FAILURES",
                "severity": "warning",
                "message": f"{failed_10min} failures in last 10 minutes",
                "value": failed_10min,
                "threshold": 5,
                "timestamp": now.isoformat()
            })
        
        # Alert 3: High revert rate
        reverts = sum(1 for b in recent_1h if not b.success and b.failure_reason and "revert" in b.failure_reason.lower())
        if recent_1h and reverts / len(recent_1h) > 0.3:
            revert_rate = reverts / len(recent_1h) * 100
            alerts.append({
                "type": "HIGH_REVERT_RATE",
                "severity": "critical",
                "message": f"Revert rate {revert_rate:.1f}% above 30% threshold",
                "value": revert_rate,
                "threshold": 30,
                "timestamp": now.isoformat()
            })
        
        # Alert 4: Latency spike
        if recent_1h:
            latencies = [b.latency_total_ms for b in recent_1h if b.latency_total_ms > 0]
            if latencies:
                p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
                if p95_latency > 150:  # >150ms
                    alerts.append({
                        "type": "HIGH_LATENCY",
                        "severity": "warning",
                        "message": f"P95 latency {p95_latency:.0f}ms above 150ms threshold",
                        "value": p95_latency,
                        "threshold": 150,
                        "timestamp": now.isoformat()
                    })
        
        # Deduplicate and rate-limit alerts
        filtered_alerts = []
        for alert in alerts:
            alert_key = alert["type"]
            last_time = self.last_alert_time.get(alert_key)
            
            # Only alert if >5 minutes since last alert of this type
            if not last_time or (now - last_time).total_seconds() > 300:
                filtered_alerts.append(alert)
                self.last_alert_time[alert_key] = now
                logger.warning(f"🚨 ALERT: {alert['message']}")
        
        return filtered_alerts
    
    def export_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format"""
        lines = []
        
        # Current aggregates
        now = datetime.now(timezone.utc)
        recent_24h = [b for b in self.all_bundles
                      if self._parse_timestamp(b.detection_timestamp) > now - timedelta(hours=24)]
        
        total = len(recent_24h)
        successful = sum(1 for b in recent_24h if b.success)
        
        lines.append(f"# HELP bundles_total Total number of bundles in last 24h")
        lines.append(f"# TYPE bundles_total counter")
        lines.append(f"bundles_total {total}")
        
        lines.append(f"# HELP bundles_successful Successful bundles in last 24h")
        lines.append(f"# TYPE bundles_successful counter")
        lines.append(f"bundles_successful {successful}")
        
        lines.append(f"# HELP success_rate Success rate percentage")
        lines.append(f"# TYPE success_rate gauge")
        success_rate = (successful / total * 100) if total > 0 else 0
        lines.append(f"success_rate {success_rate}")
        
        return "\n".join(lines)


# Example usage
if __name__ == "__main__":
    collector = KPICollector()
    
    # Simulate some bundle metrics
    for i in range(100):
        import random
        
        success = random.random() > 0.2  # 80% success rate
        
        metrics = BundleMetrics(
            bundle_id=f"bundle-{i}",
            strategy="pair_arbitrage",
            pair="SOL/USDC",
            detection_timestamp=datetime.now(timezone.utc).isoformat(),
            submit_timestamp=datetime.now(timezone.utc).isoformat(),
            latency_detect_to_submit_ms=random.uniform(40, 80),
            latency_submit_to_include_ms=random.uniform(1000, 3000) if success else 0,
            latency_total_ms=random.uniform(50, 100),
            estimated_profit=random.uniform(0.01, 0.1),
            realized_profit=random.uniform(0.008, 0.095) if success else None,
            fees_paid=0.001,
            tip_paid=10_000,
            tip_paid_sol=0.00001,
            success=success,
            failure_reason=None if success else random.choice(["timeout", "revert", "slippage"]),
            tx_count_in_bundle=2,
            compute_units_requested=200_000
        )
        
        if success and metrics.realized_profit:
            metrics.net_profit = metrics.realized_profit - metrics.fees_paid - metrics.tip_paid_sol
            metrics.tip_roi = metrics.tip_paid_sol / metrics.realized_profit
        
        collector.record_bundle(metrics)
    
    # Get dashboard data
    dashboard = collector.get_grafana_dashboard_data()
    print("📊 Grafana Dashboard Data:")
    print(json.dumps(dashboard["current_metrics"], indent=2))
    
    # Check alerts
    alerts = collector.check_alerts()
    if alerts:
        print(f"\n🚨 Active Alerts: {len(alerts)}")
        for alert in alerts:
            print(f"  - {alert['message']}")
    else:
        print("\n✅ No active alerts")
