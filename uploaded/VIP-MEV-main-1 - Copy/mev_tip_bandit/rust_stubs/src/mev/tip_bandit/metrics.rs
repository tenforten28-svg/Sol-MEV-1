//! Performance metrics and reporting

use super::state::*;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Performance metrics for the bandit
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PerformanceMetrics {
    /// Win rate per tip level
    pub win_rate_by_tip: HashMap<u64, f64>,
    /// Average ROI per tip level
    pub avg_roi_by_tip: HashMap<u64, f64>,
    /// Total profit earned
    pub total_profit: f64,
    /// Total cost (tips spent)
    pub total_cost: f64,
    /// Net profit
    pub net_profit: f64,
    /// Cumulative regret
    pub regret: f64,
    /// Convergence score (0-1)
    pub convergence_score: f64,
    /// Total opportunities processed
    pub total_opportunities: u64,
    /// Total successful inclusions
    pub total_successes: u64,
    /// Overall win rate
    pub overall_win_rate: f64,
}

impl PerformanceMetrics {
    pub fn new() -> Self {
        Self {
            win_rate_by_tip: HashMap::new(),
            avg_roi_by_tip: HashMap::new(),
            total_profit: 0.0,
            total_cost: 0.0,
            net_profit: 0.0,
            regret: 0.0,
            convergence_score: 0.0,
            total_opportunities: 0,
            total_successes: 0,
            overall_win_rate: 0.0,
        }
    }

    /// Calculate metrics from bandit state
    pub fn from_state(state: &BanditState) -> Self {
        let mut metrics = Self::new();

        for arm in &state.arms {
            metrics.win_rate_by_tip.insert(arm.lamports, arm.win_rate());
            metrics.avg_roi_by_tip.insert(arm.lamports, arm.avg_reward);
            
            // Accumulate totals
            metrics.total_opportunities += arm.pulls;
            metrics.total_successes += arm.successes;
        }

        if metrics.total_opportunities > 0 {
            metrics.overall_win_rate = 
                metrics.total_successes as f64 / metrics.total_opportunities as f64;
        }

        // Calculate convergence
        metrics.convergence_score = calculate_convergence(state);

        metrics
    }

    /// Update metrics with a new result
    pub fn update(&mut self, result: &BundleResult) {
        self.total_opportunities += 1;
        
        if result.included {
            self.total_successes += 1;
            self.total_profit += result.actual_profit;
        }
        
        self.total_cost += result.tip_used as f64;
        self.net_profit = self.total_profit - self.total_cost;
        
        if self.total_opportunities > 0 {
            self.overall_win_rate = 
                self.total_successes as f64 / self.total_opportunities as f64;
        }
    }

    /// Generate JSON report
    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).unwrap_or_else(|_| "{}".to_string())
    }

    /// Print summary report
    pub fn print_summary(&self) {
        println!("\n=== Performance Metrics Summary ===");
        println!("Total Opportunities: {}", self.total_opportunities);
        println!("Total Successes: {}", self.total_successes);
        println!("Overall Win Rate: {:.2}%", self.overall_win_rate * 100.0);
        println!("Total Profit: ${:.2}", self.total_profit / 1_000_000.0);
        println!("Total Cost (Tips): ${:.2}", self.total_cost / 1_000_000.0);
        println!("Net Profit: ${:.2}", self.net_profit / 1_000_000.0);
        println!("Convergence Score: {:.2}%", self.convergence_score * 100.0);
        println!("Cumulative Regret: {:.4}", self.regret);
        
        println!("\n--- Per-Tip Analysis ---");
        let mut tips: Vec<_> = self.win_rate_by_tip.keys().collect();
        tips.sort();
        
        for tip in tips {
            let win_rate = self.win_rate_by_tip.get(tip).unwrap_or(&0.0);
            let roi = self.avg_roi_by_tip.get(tip).unwrap_or(&0.0);
            println!(
                "Tip: {} lamports | Win Rate: {:.2}% | Avg ROI: {:.4}",
                tip,
                win_rate * 100.0,
                roi
            );
        }
        println!("==================================\n");
    }
}

impl Default for PerformanceMetrics {
    fn default() -> Self {
        Self::new()
    }
}

/// Calculate convergence score from bandit state
pub fn calculate_convergence(state: &BanditState) -> f64 {
    if state.arms.is_empty() || state.total_pulls == 0 {
        return 0.0;
    }

    // Find best arm by average reward
    let best_arm = state.arms.iter()
        .max_by(|a, b| a.avg_reward.partial_cmp(&b.avg_reward).unwrap())
        .unwrap();

    // Convergence = proportion of pulls on best arm
    best_arm.pulls as f64 / state.total_pulls as f64
}

/// Calculate cumulative regret
pub fn calculate_regret(state: &BanditState, results: &[BundleResult]) -> f64 {
    if state.arms.is_empty() {
        return 0.0;
    }

    // Find optimal arm (highest average reward)
    let optimal_reward = state.arms.iter()
        .map(|arm| arm.avg_reward)
        .max_by(|a, b| a.partial_cmp(b).unwrap())
        .unwrap_or(0.0);

    // Regret = sum of (optimal - actual) rewards
    let mut total_regret = 0.0;
    
    for result in results {
        if let Some(arm) = state.arms.iter().find(|a| a.lamports == result.tip_used) {
            let actual_reward = arm.avg_reward;
            total_regret += optimal_reward - actual_reward;
        }
    }

    total_regret
}

/// Detailed report structure
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DetailedReport {
    pub metrics: PerformanceMetrics,
    pub arm_details: Vec<ArmDetail>,
    pub recommendations: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArmDetail {
    pub tip_lamports: u64,
    pub pulls: u64,
    pub successes: u64,
    pub failures: u64,
    pub win_rate: f64,
    pub avg_reward: f64,
    pub confidence_bound: f64,
}

impl DetailedReport {
    pub fn from_state(state: &BanditState) -> Self {
        let metrics = PerformanceMetrics::from_state(state);
        
        let arm_details = state.arms.iter().map(|arm| ArmDetail {
            tip_lamports: arm.lamports,
            pulls: arm.pulls,
            successes: arm.successes,
            failures: arm.failures,
            win_rate: arm.win_rate(),
            avg_reward: arm.avg_reward,
            confidence_bound: arm.confidence_bound,
        }).collect();

        let recommendations = generate_recommendations(state, &metrics);

        Self {
            metrics,
            arm_details,
            recommendations,
        }
    }
}

/// Generate actionable recommendations
fn generate_recommendations(state: &BanditState, metrics: &PerformanceMetrics) -> Vec<String> {
    let mut recs = Vec::new();

    // Convergence recommendations
    if metrics.convergence_score < 0.5 {
        recs.push("Low convergence - consider running more trials".to_string());
    } else if metrics.convergence_score > 0.9 {
        recs.push("High convergence achieved - bandit has learned optimal strategy".to_string());
    }

    // Find best performing arm
    if let Some(best_arm) = state.arms.iter().max_by(|a, b| 
        a.avg_reward.partial_cmp(&b.avg_reward).unwrap()
    ) {
        recs.push(format!(
            "Best performing tip: {} lamports (win rate: {:.1}%, avg reward: {:.4})",
            best_arm.lamports,
            best_arm.win_rate() * 100.0,
            best_arm.avg_reward
        ));
    }

    // ROI recommendations
    if metrics.net_profit < 0.0 {
        recs.push("WARNING: Negative net profit - tips may be too high for current opportunities".to_string());
    }

    // Exploration recommendations
    let unexplored = state.arms.iter().filter(|arm| arm.pulls < 10).count();
    if unexplored > 0 {
        recs.push(format!(
            "{} arms have insufficient data (<10 pulls) - more exploration recommended",
            unexplored
        ));
    }

    recs
}
