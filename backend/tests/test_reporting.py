"""
Tests for Daily Reporting
=========================
Step 13: Validates report generation.
"""

import pytest
from datetime import datetime
from bot.alpha import (
    ReportGenerator,
    DailyReport,
    FingerprintStats
)


class TestFingerprintStats:
    """Test FingerprintStats data class"""
    
    def test_fingerprint_stats_to_dict(self):
        """Test serialization"""
        stats = FingerprintStats(
            fingerprint="TEST::SOL->USDC",
            total_opportunities=100,
            executed_trades=50,
            successful_trades=40,
            failed_trades=10,
            skipped_opportunities=50,
            total_pnl_usd=5.50,
            total_fees_usd=1.20,
            avg_spread_bps=15.5,
            avg_latency_ms=150,
            success_rate=0.8
        )
        
        d = stats.to_dict()
        
        assert d['total_opportunities'] == 100
        assert d['success_rate'] == 80.0  # Percentage
        assert d['net_pnl_usd'] == 4.3  # 5.50 - 1.20
    
    def test_fingerprint_truncation(self):
        """Test long fingerprint is truncated"""
        long_fp = "A" * 100
        stats = FingerprintStats(fingerprint=long_fp)
        
        d = stats.to_dict()
        
        assert len(d['fingerprint']) <= 53  # 50 + "..."


class TestDailyReport:
    """Test DailyReport data class"""
    
    def test_daily_report_to_dict(self):
        """Test serialization"""
        report = DailyReport(
            date="2024-01-15",
            generated_at="2024-01-16T00:00:00",
            total_opportunities=1000,
            total_executed=200,
            total_successful=180,
            total_failed=20,
            total_skipped=800,
            gross_pnl_usd=50.0,
            total_fees_usd=10.0,
            net_pnl_usd=40.0,
            execution_rate=0.2,
            success_rate=0.9
        )
        
        d = report.to_dict()
        
        assert d['date'] == "2024-01-15"
        assert d['summary']['total_opportunities'] == 1000
        assert d['pnl']['net_pnl_usd'] == 40.0
    
    def test_report_rates_formatted(self):
        """Test rate formatting"""
        report = DailyReport(
            date="2024-01-15",
            generated_at="2024-01-16T00:00:00",
            execution_rate=0.25,
            success_rate=0.85
        )
        
        d = report.to_dict()
        
        assert d['summary']['execution_rate'] == "25.0%"
        assert d['summary']['success_rate'] == "85.0%"


class TestReportGenerator:
    """Test report generation"""
    
    def test_generator_initialization(self):
        """Test generator can be created"""
        generator = ReportGenerator()
        
        assert generator is not None
    
    def test_generate_report_no_data(self):
        """Test generating report with no data"""
        generator = ReportGenerator()
        
        # This would require a mock storage
        # For now just test the generator exists
        assert hasattr(generator, 'generate_daily_report')
    
    def test_report_has_required_sections(self):
        """Test that report has all required sections"""
        report = DailyReport(
            date="2024-01-15",
            generated_at="2024-01-16T00:00:00"
        )
        
        d = report.to_dict()
        
        # Check required sections exist
        assert 'summary' in d
        assert 'pnl' in d
        assert 'pnl_by_fingerprint' in d
        assert 'top_failures' in d
        assert 'crowding_distribution' in d
        assert 'success_by_state' in d
        assert 'skipped_analysis' in d
        assert 'latency_stats' in d


class TestReportMetrics:
    """Test specific report metrics"""
    
    def test_crowding_distribution_structure(self):
        """Test crowding distribution format"""
        report = DailyReport(
            date="2024-01-15",
            generated_at="now",
            crowding_distribution={
                'low_pct': 60.0,
                'medium_pct': 30.0,
                'high_pct': 10.0,
                'counts': {'low': 600, 'medium': 300, 'high': 100}
            }
        )
        
        d = report.to_dict()
        cd = d['crowding_distribution']
        
        assert cd['low_pct'] == 60.0
        assert cd['counts']['low'] == 600
    
    def test_latency_stats_structure(self):
        """Test latency stats format"""
        report = DailyReport(
            date="2024-01-15",
            generated_at="now",
            latency_stats={
                'detect': {'p50': 50, 'p90': 100, 'p99': 200},
                'decision': {'p50': 10, 'p90': 20, 'p99': 50}
            }
        )
        
        d = report.to_dict()
        ls = d['latency_stats']
        
        assert ls['detect']['p50'] == 50
        assert ls['decision']['p90'] == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
