//! Simulation types

use crate::mev::probe::types::*;
use serde::{Deserialize, Serialize};
use solana_sdk::pubkey::Pubkey;

/// Simulation state
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SimulationState {
    pub current_slot: u64,
    pub current_timestamp: u64,
    
    // Market conditions
    pub base_inclusion_probability: f64,
    pub congestion_level: f64,  // 0.0-1.0
    pub competing_bots: u32,
    
    // Validators
    pub validators: Vec<ValidatorConfig>,
    pub current_leader: Option<Pubkey>,
    
    // Tracking
    pub probes_sent: u64,
    pub probes_included: u64,
    pub total_cost: u64,
}

/// Validator configuration for simulation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidatorConfig {
    pub identity: Pubkey,
    
    // Tip acceptance
    pub min_tip: u64,
    pub tip_sensitivity: f64,
    
    // Performance
    pub base_latency_ms: u64,
    pub latency_variance: f64,
    pub base_inclusion_prob: f64,
    
    // Behavior
    pub accepts_low_priority: bool,
    pub compute_preference: f64,
}

/// Simulation configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SimulationConfig {
    pub num_rounds: usize,
    pub base_probability: f64,
    pub initial_congestion: f64,
    pub num_competing_bots: u32,
    pub validators: Vec<ValidatorConfig>,
}
