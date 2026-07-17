//! Backtesting engine module

pub mod engine;
pub mod state;
pub mod event;
pub mod reporter;
pub mod simulator;

pub use engine::BacktestEngine;
pub use state::BacktestState;
pub use event::{MarketEvent, EventType};
