//! ML signal framework

pub mod features;
pub mod labels;
pub mod dataset;
pub mod interface;
pub mod utils;

pub use features::FeatureVector;
pub use labels::generate_labels;
pub use interface::SignalModel;
