//! Adaptive Tip Bandit Module for Solana MEV
//!
//! This module implements Multi-Armed Bandit algorithms to optimize
//! validator tips for maximum ROI in MEV bundle submissions.

pub mod mev;

pub use mev::tip_bandit::{
    bandit::{TipBandit, BanditConfig},
    state::{BanditState, TipArm},
    simulator::MarketSimulator,
    metrics::PerformanceMetrics,
};
