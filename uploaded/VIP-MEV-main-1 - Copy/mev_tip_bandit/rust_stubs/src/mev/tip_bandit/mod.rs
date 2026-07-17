//! Tip Bandit module for adaptive tip optimization

pub mod bandit;
pub mod state;
pub mod simulator;
pub mod metrics;

pub use bandit::{TipBandit, TipStrategy};
pub use state::{BanditState, TipArm, BundleResult};
pub use simulator::MarketSimulator;
pub use metrics::PerformanceMetrics;
