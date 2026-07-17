//! Data ingestion and storage

pub mod ingestion;
pub mod schema;
pub mod storage;
pub mod sources;

pub use ingestion::DataIngestion;
pub use schema::DexSnapshot;
pub use storage::StorageBackend;
