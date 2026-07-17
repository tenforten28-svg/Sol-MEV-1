//! Core Bandit algorithm implementation

use super::state::*;
use rand::Rng;
use std::f64::consts::E;

/// Configuration for the bandit
#[derive(Debug, Clone)]
pub struct BanditConfig {
    pub tip_levels: Vec<u64>,
    pub algorithm: AlgorithmType,
    pub exploration_param: f64,
    pub enable_urgency_boost: bool,
}

impl Default for BanditConfig {
    fn default() -> Self {
        Self {
            tip_levels: vec![5_000, 10_000, 20_000, 35_000, 50_000, 75_000, 100_000],
            algorithm: AlgorithmType::UCB1,
            exploration_param: 2.0,
            enable_urgency_boost: true,
        }
    }
}

/// Trait for tip selection strategies
pub trait TipStrategy {
    /// Select a tip amount based on current state and opportunity
    fn select_tip(&self, state: &BanditState, opportunity: &Opportunity) -> u64;
    
    /// Update state after observing result
    fn update(&self, state: &mut BanditState, result: &BundleResult, opportunity: &Opportunity);
}

/// Main Tip Bandit controller
pub struct TipBandit {
    state: BanditState,
    config: BanditConfig,
}

impl TipBandit {
    /// Create a new TipBandit instance
    pub fn new(config: BanditConfig) -> Self {
        let state = BanditState::new(
            config.tip_levels.clone(),
            config.algorithm,
        );
        
        Self { state, config }
    }

    /// Get recommended tip for an opportunity
    pub fn recommend_tip(&self, opportunity: &Opportunity) -> TipRecommendation {
        let tip = match self.config.algorithm {
            AlgorithmType::UCB1 => self.select_tip_ucb1(opportunity),
            AlgorithmType::ThompsonSampling => self.select_tip_thompson(),
        };

        let arm = self.state.find_arm(tip).unwrap();
        
        TipRecommendation {
            recommended_tip: tip,
            confidence: self.calculate_confidence(arm),
            expected_inclusion_prob: arm.win_rate(),
            expected_roi: arm.avg_reward,
        }
    }

    /// Update bandit state after bundle submission
    pub fn update(&mut self, result: BundleResult, opportunity: Opportunity) {
        let reward = result.calculate_reward(opportunity.expected_profit);
        
        if let Some(arm) = self.state.find_arm_mut(result.tip_used) {
            arm.update(reward, result.included);
        }

        self.state.total_pulls += 1;
        
        // Recompute confidence bounds for all arms
        self.update_confidence_bounds();
        
        // Update phase
        self.state.update_phase();
    }

    /// Select tip using UCB1 algorithm
    fn select_tip_ucb1(&self, opportunity: &Opportunity) -> u64 {
        // TODO: Implement UCB1 selection
        // 1. Check if any arm has 0 pulls (exploration)
        // 2. Calculate UCB for each arm: avg_reward + c * sqrt(2*ln(total)/pulls)
        // 3. Apply urgency boost if enabled
        // 4. Return arm with highest UCB
        
        // Placeholder: return first arm
        self.config.tip_levels[0]
    }

    /// Select tip using Thompson Sampling
    fn select_tip_thompson(&self) -> u64 {
        // TODO: Implement Thompson Sampling
        // 1. For each arm, sample from Beta(alpha + successes, beta + failures)
        // 2. Return arm with highest sample
        
        // Placeholder: return first arm
        self.config.tip_levels[0]
    }

    /// Update confidence bounds for all arms (UCB1)
    fn update_confidence_bounds(&mut self) {
        if self.state.algorithm != AlgorithmType::UCB1 {
            return;
        }

        let total = self.state.total_pulls as f64;
        let c = self.config.exploration_param;

        for arm in &mut self.state.arms {
            if arm.pulls > 0 {
                let exploration = c * ((2.0 * total.ln()) / arm.pulls as f64).sqrt();
                arm.confidence_bound = arm.avg_reward + exploration;
            }
        }
    }

    /// Calculate confidence for a recommendation
    fn calculate_confidence(&self, arm: &TipArm) -> f64 {
        if self.state.total_pulls == 0 {
            0.0
        } else {
            arm.pulls as f64 / self.state.total_pulls as f64
        }
    }

    /// Get current state (for persistence)
    pub fn get_state(&self) -> &BanditState {
        &self.state
    }

    /// Load from saved state
    pub fn from_state(state: BanditState, config: BanditConfig) -> Self {
        Self { state, config }
    }
}

/// Response from tip recommendation
#[derive(Debug, Clone)]
pub struct TipRecommendation {
    pub recommended_tip: u64,
    pub confidence: f64,
    pub expected_inclusion_prob: f64,
    pub expected_roi: f64,
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/// Sample from Beta distribution (placeholder)
fn sample_beta(alpha: f64, beta: f64) -> f64 {
    // TODO: Implement proper Beta sampling using statrs crate
    // For now, return a simple placeholder
    let mut rng = rand::thread_rng();
    rng.gen::<f64>()
}
