//! MEV Backtesting & Data Pipeline System
//!
//! Complete system for:
//! - Historical data ingestion from Serum, Raydium, Orca, Jupiter
//! - Event-driven backtesting engine
//! - Execution optimization
//! - ML feature/label generation

pub mod backtest;
pub mod data;
pub mod execution;
pub mod ml;

// Re-exports
pub use backtest::{
    engine::BacktestEngine,
    state::BacktestState,
    event::MarketEvent,
};

pub use data::{
    schema::DexSnapshot,
    ingestion::DataIngestion,
};

pub use execution::{
    optimizer::ExecutionOptimizer,
    risk::RiskScore,
};

pub use ml::{
    features::FeatureVector,
    labels::generate_labels,
};
