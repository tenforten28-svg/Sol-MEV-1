//! State management for the Tip Bandit

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Represents a single tip level (arm) in the bandit
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TipArm {
    /// Tip amount in lamports
    pub lamports: u64,
    /// Number of times this arm has been selected
    pub pulls: u64,
    /// Cumulative reward from this arm
    pub total_reward: f64,
    /// Number of successful bundle inclusions
    pub successes: u64,
    /// Number of failed bundle inclusions
    pub failures: u64,
    /// Average reward per pull
    pub avg_reward: f64,
    /// UCB1 upper confidence bound
    pub confidence_bound: f64,
}

impl TipArm {
    pub fn new(lamports: u64) -> Self {
        Self {
            lamports,
            pulls: 0,
            total_reward: 0.0,
            successes: 0,
            failures: 0,
            avg_reward: 0.0,
            confidence_bound: f64::INFINITY,
        }
    }

    /// Update arm statistics after a pull
    pub fn update(&mut self, reward: f64, success: bool) {
        self.pulls += 1;
        self.total_reward += reward;
        self.avg_reward = self.total_reward / self.pulls as f64;
        
        if success {
            self.successes += 1;
        } else {
            self.failures += 1;
        }
    }

    /// Get win rate (inclusion rate)
    pub fn win_rate(&self) -> f64 {
        if self.pulls == 0 {
            0.0
        } else {
            self.successes as f64 / self.pulls as f64
        }
    }
}

/// Algorithm type for bandit
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub enum AlgorithmType {
    UCB1,
    ThompsonSampling,
}

/// Current phase of the bandit
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub enum BanditPhase {
    /// Initial exploration phase
    Exploration,
    /// Confident exploitation phase
    Exploitation,
    /// Continuous adaptive learning
    Adaptive,
}

/// Main state for the Tip Bandit
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BanditState {
    /// Available tip arms
    pub arms: Vec<TipArm>,
    /// Total selections across all arms
    pub total_pulls: u64,
    /// Algorithm being used
    pub algorithm: AlgorithmType,
    /// Exploration parameter for UCB1 (c)
    pub exploration_param: f64,
    /// Success prior for Thompson Sampling (alpha)
    pub alpha: f64,
    /// Failure prior for Thompson Sampling (beta)
    pub beta: f64,
    /// Current phase
    pub phase: BanditPhase,
}

impl BanditState {
    pub fn new(tip_levels: Vec<u64>, algorithm: AlgorithmType) -> Self {
        let arms = tip_levels.into_iter().map(TipArm::new).collect();
        
        Self {
            arms,
            total_pulls: 0,
            algorithm,
            exploration_param: 2.0, // Standard UCB1 parameter
            alpha: 1.0,
            beta: 1.0,
            phase: BanditPhase::Exploration,
        }
    }

    /// Update phase based on convergence
    pub fn update_phase(&mut self) {
        // TODO: Implement phase transition logic
        // - EXPLORATION if total_pulls < 100
        // - EXPLOITATION if convergence > 0.95
        // - ADAPTIVE otherwise
    }

    /// Find arm by tip amount
    pub fn find_arm(&self, lamports: u64) -> Option<&TipArm> {
        self.arms.iter().find(|arm| arm.lamports == lamports)
    }

    /// Find mutable arm by tip amount
    pub fn find_arm_mut(&mut self, lamports: u64) -> Option<&mut TipArm> {
        self.arms.iter_mut().find(|arm| arm.lamports == lamports)
    }
}

/// Represents an arbitrage opportunity
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Opportunity {
    pub token_pair: String,
    pub expected_profit: f64,  // In lamports
    pub size: f64,
    pub urgency: f64,  // 0.0 - 1.0
    pub timestamp: u64,
}

/// Result of a bundle submission
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BundleResult {
    /// Was the bundle included in a block?
    pub included: bool,
    /// Tip amount used (lamports)
    pub tip_used: u64,
    /// Actual profit realized (0 if not included)
    pub actual_profit: f64,
    /// Latency to inclusion (milliseconds)
    pub latency_ms: u64,
    /// Block slot number
    pub block_slot: u64,
    /// Validator ID
    pub validator_id: String,
}

impl BundleResult {
    /// Calculate reward for bandit update
    pub fn calculate_reward(&self, expected_profit: f64) -> f64 {
        if self.included {
            let tx_fees = 5000.0; // Base transaction fee
            let net_profit = self.actual_profit - tx_fees - self.tip_used as f64;
            // Normalize to expected profit
            (net_profit / expected_profit).max(0.0)
        } else {
            // Penalty: lost the tip
            -(self.tip_used as f64 / expected_profit)
        }
    }
}
