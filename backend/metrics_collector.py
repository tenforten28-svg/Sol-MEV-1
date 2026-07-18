"""
Monitoring & Metrics System
Tracks bundle lifecycle, latencies, P&L, and alerts
"""
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from collections import deque
import logging
import json

logger = logging.getLogger(__name__)

@dataclass
class BundleMetrics:
    """Metrics for a single bundle"""
    bundle_id: str
    created_at: datetime
    submitted_at: Optional[datetime] = None
    landed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    
    # Timings (milliseconds)
    detection_latency_ms: float = 0.0
    build_latency_ms: float = 0.0
    submission_latency_ms: float = 0.0
    confirmation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    
    # Financial
    estimated_profit: float = 0.0
    actual_profit: Optional[float] = None
    tip_paid: int = 0
    gas_cost: float = 0.0
    net_profit: Optional[float] = None
    
    # Status
    status: str = "created"  # created, submitted, landed, failed, expired
    error: Optional[str] = None
    slot: Optional[int] = None
    
@dataclass
class SystemMetrics:
    """System-wide performance metrics"""
    
    # Counters
    opportunities_detected: int = 0
    bundles_created: int = 0
    bundles_submitted: int = 0
    bundles_landed: int = 0
    bundles_failed: int = 0
    
    # Latencies (rolling averages)
    avg_detection_latency_ms: float = 0.0
    avg_build_latency_ms: float = 0.0
    avg_submission_latency_ms: float = 0.0
    avg_confirmation_latency_ms: float = 0.0
    avg_total_latency_ms: float = 0.0
    
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # Financial
    total_profit: float = 0.0
    total_gas_cost: float = 0.0
    total_tips_paid: int = 0
    net_profit: float = 0.0
    
    # Success rates
    submission_success_rate: float = 0.0
    landing_success_rate: float = 0.0
    
    # Timestamp
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class MetricsCollector:
    """Collects and aggregates metrics for monitoring"""
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        
        # Bundle metrics storage
        self.bundle_metrics: Dict[str, BundleMetrics] = {}
        self.recent_bundles: deque = deque(maxlen=max_history)
        
        # System metrics
        self.system_metrics = SystemMetrics()
        
        # Latency buckets for percentile calculation
        self.latency_samples: deque = deque(maxlen=max_history)
        
        # Alerts
        self.alert_thresholds = {
            "max_latency_ms": 100,
            "min_success_rate": 70,
            "max_consecutive_failures": 5
        }
        
        self.consecutive_failures = 0
        self.alerts_triggered: List[Dict] = []
    
    def record_opportunity(self, opportunity_id: str, detection_time_ms: float):
        """Record opportunity detection"""
        self.system_metrics.opportunities_detected += 1
    
    def record_bundle_created(
        self,
        bundle_id: str,
        estimated_profit: float,
        build_time_ms: float
    ):
        """Record bundle creation"""
        metrics = BundleMetrics(
            bundle_id=bundle_id,
            created_at=datetime.now(timezone.utc),
            build_latency_ms=build_time_ms,
            estimated_profit=estimated_profit,
            status="created"
        )
        
        self.bundle_metrics[bundle_id] = metrics
        self.recent_bundles.append(bundle_id)
        
        self.system_metrics.bundles_created += 1
        self._update_latency_metrics()
    
    def record_bundle_submitted(
        self,
        bundle_id: str,
        submission_time_ms: float,
        tip_lamports: int
    ):
        """Record bundle submission"""
        if bundle_id not in self.bundle_metrics:
            logger.warning(f"Bundle {bundle_id} not found in metrics")
            return
        
        metrics = self.bundle_metrics[bundle_id]
        metrics.submitted_at = datetime.now(timezone.utc)
        metrics.submission_latency_ms = submission_time_ms
        metrics.tip_paid = tip_lamports
        metrics.status = "submitted"
        
        self.system_metrics.bundles_submitted += 1
        self._update_latency_metrics()
    
    def record_bundle_landed(
        self,
        bundle_id: str,
        actual_profit: float,
        gas_cost: float,
        slot: int
    ):
        """Record successful bundle landing"""
        if bundle_id not in self.bundle_metrics:
            logger.warning(f"Bundle {bundle_id} not found in metrics")
            return
        
        metrics = self.bundle_metrics[bundle_id]
        metrics.landed_at = datetime.now(timezone.utc)
        metrics.actual_profit = actual_profit
        metrics.gas_cost = gas_cost
        metrics.slot = slot
        metrics.status = "landed"
        
        # Calculate net profit
        tip_cost_sol = metrics.tip_paid / 1_000_000_000  # lamports to SOL
        metrics.net_profit = actual_profit - gas_cost - tip_cost_sol
        
        # Calculate total latency
        if metrics.created_at and metrics.landed_at:
            total_ms = (metrics.landed_at - metrics.created_at).total_seconds() * 1000
            metrics.total_latency_ms = total_ms
            self.latency_samples.append(total_ms)
        
        # Update system metrics
        self.system_metrics.bundles_landed += 1
        self.system_metrics.total_profit += actual_profit
        self.system_metrics.total_gas_cost += gas_cost
        self.system_metrics.total_tips_paid += metrics.tip_paid
        self.system_metrics.net_profit += metrics.net_profit
        
        self.consecutive_failures = 0  # Reset failure counter
        self._update_latency_metrics()
        self._check_alerts()
    
    def record_bundle_failed(
        self,
        bundle_id: str,
        error: str
    ):
        """Record bundle failure"""
        if bundle_id not in self.bundle_metrics:
            logger.warning(f"Bundle {bundle_id} not found in metrics")
            return
        
        metrics = self.bundle_metrics[bundle_id]
        metrics.failed_at = datetime.now(timezone.utc)
        metrics.error = error
        metrics.status = "failed"
        
        self.system_metrics.bundles_failed += 1
        self.consecutive_failures += 1
        
        self._update_latency_metrics()
        self._check_alerts()
    
    def _update_latency_metrics(self):
        """Update latency averages"""
        recent_metrics = [
            self.bundle_metrics[bid] 
            for bid in list(self.recent_bundles)
            if bid in self.bundle_metrics
        ]
        
        if not recent_metrics:
            return
        
        # Calculate averages
        total_build = sum(m.build_latency_ms for m in recent_metrics if m.build_latency_ms > 0)
        total_submission = sum(m.submission_latency_ms for m in recent_metrics if m.submission_latency_ms > 0)
        
        count = len(recent_metrics)
        
        if count > 0:
            self.system_metrics.avg_build_latency_ms = total_build / count
            self.system_metrics.avg_submission_latency_ms = total_submission / count
        
        # Calculate percentiles from latency samples
        if self.latency_samples:
            sorted_samples = sorted(self.latency_samples)
            n = len(sorted_samples)
            
            self.system_metrics.p50_latency_ms = sorted_samples[int(n * 0.50)]
            self.system_metrics.p95_latency_ms = sorted_samples[int(n * 0.95)]
            self.system_metrics.p99_latency_ms = sorted_samples[int(n * 0.99)]
            self.system_metrics.avg_total_latency_ms = sum(sorted_samples) / n
        
        # Calculate success rates
        if self.system_metrics.bundles_submitted > 0:
            self.system_metrics.submission_success_rate = (
                (self.system_metrics.bundles_submitted - self.system_metrics.bundles_failed) /
                self.system_metrics.bundles_submitted * 100
            )
        
        if self.system_metrics.bundles_submitted > 0:
            self.system_metrics.landing_success_rate = (
                self.system_metrics.bundles_landed /
                self.system_metrics.bundles_submitted * 100
            )
        
        self.system_metrics.last_updated = datetime.now(timezone.utc)
    
    def _check_alerts(self):
        """Check for alert conditions"""
        
        # High latency alert
        if self.system_metrics.avg_total_latency_ms > self.alert_thresholds["max_latency_ms"]:
            self._trigger_alert(
                "HIGH_LATENCY",
                f"Average latency {self.system_metrics.avg_total_latency_ms:.1f}ms exceeds threshold"
            )
        
        # Low success rate alert
        if self.system_metrics.landing_success_rate < self.alert_thresholds["min_success_rate"]:
            self._trigger_alert(
                "LOW_SUCCESS_RATE",
                f"Landing success rate {self.system_metrics.landing_success_rate:.1f}% below threshold"
            )
        
        # Consecutive failures alert
        if self.consecutive_failures >= self.alert_thresholds["max_consecutive_failures"]:
            self._trigger_alert(
                "CONSECUTIVE_FAILURES",
                f"{self.consecutive_failures} consecutive bundle failures"
            )
    
    def _trigger_alert(self, alert_type: str, message: str):
        """Trigger an alert"""
        alert = {
            "type": alert_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {
                "success_rate": self.system_metrics.landing_success_rate,
                "avg_latency_ms": self.system_metrics.avg_total_latency_ms,
                "consecutive_failures": self.consecutive_failures
            }
        }
        
        self.alerts_triggered.append(alert)
        logger.warning(f"🚨 ALERT: {alert_type} - {message}")
    
    def get_system_metrics(self) -> Dict:
        """Get current system metrics"""
        return {
            "opportunities_detected": self.system_metrics.opportunities_detected,
            "bundles_created": self.system_metrics.bundles_created,
            "bundles_submitted": self.system_metrics.bundles_submitted,
            "bundles_landed": self.system_metrics.bundles_landed,
            "bundles_failed": self.system_metrics.bundles_failed,
            "submission_success_rate": round(self.system_metrics.submission_success_rate, 2),
            "landing_success_rate": round(self.system_metrics.landing_success_rate, 2),
            "avg_latency_ms": round(self.system_metrics.avg_total_latency_ms, 2),
            "p50_latency_ms": round(self.system_metrics.p50_latency_ms, 2),
            "p95_latency_ms": round(self.system_metrics.p95_latency_ms, 2),
            "p99_latency_ms": round(self.system_metrics.p99_latency_ms, 2),
            "total_profit": round(self.system_metrics.total_profit, 4),
            "total_gas_cost": round(self.system_metrics.total_gas_cost, 4),
            "net_profit": round(self.system_metrics.net_profit, 4),
            "consecutive_failures": self.consecutive_failures,
            "last_updated": self.system_metrics.last_updated.isoformat()
        }
    
    def get_recent_bundles(self, limit: int = 10) -> List[Dict]:
        """Get recent bundle metrics"""
        recent_ids = list(self.recent_bundles)[-limit:]
        
        bundles = []
        for bundle_id in reversed(recent_ids):
            if bundle_id in self.bundle_metrics:
                m = self.bundle_metrics[bundle_id]
                bundles.append({
                    "bundle_id": m.bundle_id[:16],
                    "status": m.status,
                    "estimated_profit": round(m.estimated_profit, 4),
                    "actual_profit": round(m.actual_profit, 4) if m.actual_profit else None,
                    "net_profit": round(m.net_profit, 4) if m.net_profit else None,
                    "total_latency_ms": round(m.total_latency_ms, 2),
                    "created_at": m.created_at.isoformat(),
                    "error": m.error
                })
        
        return bundles
    
    def get_alerts(self, limit: int = 5) -> List[Dict]:
        """Get recent alerts"""
        return self.alerts_triggered[-limit:]


# Example usage
if __name__ == "__main__":
    collector = MetricsCollector()
    
    # Simulate some bundle lifecycle events
    collector.record_opportunity("opp-1", 5.2)
    
    collector.record_bundle_created("bundle-1", 0.05, 10.3)
    collector.record_bundle_submitted("bundle-1", 45.7, 10_000)
    collector.record_bundle_landed("bundle-1", 0.048, 0.001, 123456)
    
    collector.record_bundle_created("bundle-2", 0.03, 12.1)
    collector.record_bundle_submitted("bundle-2", 52.3, 10_000)
    collector.record_bundle_failed("bundle-2", "Timeout")
    
    # Get metrics
    print(json.dumps(collector.get_system_metrics(), indent=2))
    print("\nRecent Bundles:")
    print(json.dumps(collector.get_recent_bundles(), indent=2))
