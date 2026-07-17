//! Core data types for probe transactions

use serde::{Deserialize, Serialize};
use solana_sdk::{
    pubkey::Pubkey,
    signature::Signature,
    transaction::Transaction,
};
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;

/// Type of probe transaction
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum ProbeType {
    /// Find minimum tip for inclusion
    TipThreshold,
    /// Measure propagation delay
    LatencyTest,
    /// Simulate bundle complexity
    CongestionPressure,
    /// Test against competing bots
    CompetitionTest,
}

/// A probe transaction ready to send
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProbeTransaction {
    /// Unique identifier
    pub probe_id: Uuid,
    /// Type of probe
    pub probe_type: ProbeType,
    /// Target validator
    pub validator_identity: Pubkey,
    
    // Transaction parameters
    pub tip_amount: u64,
    pub compute_units: u32,
    pub account_count: u8,
    pub priority_fee: u64,
    
    // Timing
    pub timestamp_sent: u64,  // Microseconds since epoch
    pub expected_slot: u64,
    
    // Transaction data
    #[serde(skip)]  // Don't serialize the actual transaction
    pub transaction: Option<Transaction>,
    pub signature: Option<Signature>,
    
    // Metadata
    pub bundle_size_bytes: usize,
    pub retry_count: u8,
    pub parent_probe_id: Option<Uuid>,
}

impl ProbeTransaction {
    /// Create a new probe transaction
    pub fn new(probe_type: ProbeType, validator: Pubkey) -> Self {
        Self {
            probe_id: Uuid::new_v4(),
            probe_type,
            validator_identity: validator,
            tip_amount: 0,
            compute_units: 1400,
            account_count: 1,
            priority_fee: 0,
            timestamp_sent: current_time_micros(),
            expected_slot: 0,
            transaction: None,
            signature: None,
            bundle_size_bytes: 0,
            retry_count: 0,
            parent_probe_id: None,
        }
    }
}

/// Result of a probe transaction
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProbeResult {
    pub probe_id: Uuid,
    pub probe_type: ProbeType,
    pub validator_identity: Pubkey,
    
    // Input parameters
    pub tip_sent: u64,
    pub compute_units: u32,
    pub account_count: u8,
    
    // Outcome
    pub included: bool,
    pub slot_included: Option<u64>,
    pub timestamp_confirmed: Option<u64>,
    pub latency_ms: Option<u64>,
    
    // Network state
    pub slot_sent: u64,
    pub cluster_congestion: f64,
    pub competing_transactions: u32,
    
    // Error info
    pub error_code: Option<String>,
    pub retry_count: u8,
}

impl ProbeResult {
    /// Calculate reward for this result (used by tip bandit)
    pub fn calculate_reward(&self, expected_profit: f64) -> f64 {
        if self.included {
            // Success: positive reward proportional to efficiency
            let efficiency = 1.0 - (self.tip_sent as f64 / expected_profit);
            efficiency.max(0.0)
        } else {
            // Failure: negative reward (lost the tip)
            -(self.tip_sent as f64 / expected_profit)
        }
    }
}

/// Profile of a validator's behavior
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidatorProfile {
    pub validator_identity: Pubkey,
    pub total_probes_sent: u64,
    pub total_probes_included: u64,
    pub inclusion_rate: f64,
    
    // Tip statistics
    pub min_tip_observed: u64,
    pub avg_tip_for_inclusion: u64,
    pub tip_acceptance_curve: Vec<(u64, f64)>,  // (tip, probability)
    
    // Performance
    pub avg_latency_ms: f64,
    pub latency_variance: f64,
    pub best_slots: Vec<u64>,
    
    // Behavior patterns
    pub accepts_low_priority: bool,
    pub prefers_high_compute: bool,
    pub last_updated: u64,
}

impl ValidatorProfile {
    pub fn new(validator_identity: Pubkey) -> Self {
        Self {
            validator_identity,
            total_probes_sent: 0,
            total_probes_included: 0,
            inclusion_rate: 0.0,
            min_tip_observed: u64::MAX,
            avg_tip_for_inclusion: 0,
            tip_acceptance_curve: Vec::new(),
            avg_latency_ms: 0.0,
            latency_variance: 0.0,
            best_slots: Vec::new(),
            accepts_low_priority: false,
            prefers_high_compute: false,
            last_updated: current_time_micros(),
        }
    }
}

/// Network snapshot at a point in time
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkSnapshot {
    pub slot: u64,
    pub timestamp: u64,
    
    // Congestion metrics
    pub transactions_per_second: u32,
    pub pending_queue_depth: u32,
    pub average_priority_fee: u64,
    
    // Validator state
    pub active_validators: Vec<Pubkey>,
    pub leader_schedule: Vec<(u64, Pubkey)>,
    
    // Cost metrics
    pub median_tip: u64,
    pub p95_tip: u64,
    pub min_competitive_tip: u64,
}

/// Detected anomaly in validator behavior
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Anomaly {
    pub anomaly_type: AnomalyType,
    pub validator: Pubkey,
    pub severity: Severity,
    pub description: String,
    pub detected_at: u64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub enum AnomalyType {
    InclusionDrop,
    LatencySpike,
    TipIncrease,
    UnexpectedRejection,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub enum Severity {
    Low,
    Medium,
    High,
    Critical,
}

// Helper function
pub fn current_time_micros() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_micros() as u64
}
