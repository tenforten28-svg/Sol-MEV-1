//! Market simulation for testing the bandit

use super::state::*;
use rand::Rng;
use std::f64::consts::E;

/// Simulated market conditions
#[derive(Debug, Clone)]
pub struct MarketCondition {
    /// Base probability of bundle inclusion
    pub base_inclusion_prob: f64,
    /// Number of competing bots
    pub competing_bots: u32,
    /// Validator latency in milliseconds
    pub validator_latency_ms: u64,
    /// Minimum competitive tip to have reasonable chance
    pub min_competitive_tip: u64,
}

impl MarketCondition {
    /// Generate random market conditions
    pub fn random() -> Self {
        let mut rng = rand::thread_rng();
        Self {
            base_inclusion_prob: rng.gen_range(0.3..0.9),
            competing_bots: rng.gen_range(5..50),
            validator_latency_ms: rng.gen_range(10..200),
            min_competitive_tip: rng.gen_range(10_000..80_000),
        }
    }
}

/// Market simulator for testing bandit
pub struct MarketSimulator {
    /// Current market conditions
    market: MarketCondition,
    /// Current block slot
    current_slot: u64,
}

impl MarketSimulator {
    pub fn new() -> Self {
        Self {
            market: MarketCondition::random(),
            current_slot: 1_000_000,
        }
    }

    /// Simulate bundle submission with a given tip
    pub fn simulate_submission(
        &mut self,
        tip: u64,
        opportunity: &Opportunity,
    ) -> BundleResult {
        // Calculate inclusion probability based on tip
        let inclusion_prob = self.calculate_inclusion_probability(tip);

        let mut rng = rand::thread_rng();
        let included = rng.gen::<f64>() < inclusion_prob;

        let actual_profit = if included {
            // Simulate actual profit (with some variance)
            let variance = rng.gen_range(0.8..1.2);
            opportunity.expected_profit * variance
        } else {
            0.0
        };

        self.current_slot += 1;

        BundleResult {
            included,
            tip_used: tip,
            actual_profit,
            latency_ms: self.market.validator_latency_ms,
            block_slot: self.current_slot,
            validator_id: "sim_validator".to_string(),
        }
    }

    /// Calculate inclusion probability based on tip and market
    fn calculate_inclusion_probability(&self, tip: u64) -> f64 {
        if tip < self.market.min_competitive_tip {
            // Very low chance if tip is too low
            0.1
        } else {
            // Logarithmic relationship: higher tip = higher probability
            let tip_factor = (1.0 + tip as f64).ln() / (1.0 + 100_000.0).ln();
            let prob = self.market.base_inclusion_prob * tip_factor;
            prob.min(0.99) // Cap at 99%
        }
    }

    /// Update market conditions (simulates changing market)
    pub fn update_market(&mut self) {
        self.market = MarketCondition::random();
    }

    /// Generate random opportunity for testing
    pub fn generate_opportunity(&self) -> Opportunity {
        let mut rng = rand::thread_rng();
        
        let token_pairs = vec!["SOL/USDC", "RAY/USDC", "ORCA/USDC"];
        let pair = token_pairs[rng.gen_range(0..token_pairs.len())];

        Opportunity {
            token_pair: pair.to_string(),
            expected_profit: rng.gen_range(20_000.0..150_000.0),
            size: rng.gen_range(0.1..10.0),
            urgency: rng.gen_range(0.0..1.0),
            timestamp: self.current_slot,
        }
    }
}

impl Default for MarketSimulator {
    fn default() -> Self {
        Self::new()
    }
}
