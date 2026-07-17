//! Probe transaction sender

use super::types::*;
use anyhow::{Context, Result};
use solana_client::{
    nonblocking::rpc_client::RpcClient,
    rpc_config::RpcSendTransactionConfig,
};
use solana_sdk::{
    commitment_config::CommitmentConfig,
    signature::Signature,
};
use std::time::Duration;
use tokio::time::sleep;

/// Sends probe transactions to validators
pub struct ProbeSender {
    rpc_client: RpcClient,
    confirmation_timeout_slots: u64,
}

impl ProbeSender {
    pub fn new(rpc_url: String, timeout_slots: u64) -> Self {
        Self {
            rpc_client: RpcClient::new(rpc_url),
            confirmation_timeout_slots: timeout_slots,
        }
    }

    /// Send a probe transaction
    pub async fn send_probe(&self, probe: &mut ProbeTransaction) -> Result<Signature> {
        // TODO: Implement probe sending
        //
        // Steps:
        // 1. Get current slot
        // 2. Update probe.timestamp_sent
        // 3. Configure RPC send options
        // 4. Send transaction
        // 5. Return signature
        
        unimplemented!("send_probe")
    }

    /// Confirm a probe transaction
    pub async fn confirm_probe(
        &self,
        probe: &ProbeTransaction,
    ) -> Result<ProbeResult> {
        // TODO: Implement confirmation polling
        //
        // Steps:
        // 1. Get start slot
        // 2. Poll signature status
        // 3. Check for timeout
        // 4. Calculate latency on success
        // 5. Return ProbeResult
        
        unimplemented!("confirm_probe")
    }

    /// Send and confirm in one call
    pub async fn send_and_confirm(
        &self,
        probe: &mut ProbeTransaction,
    ) -> Result<ProbeResult> {
        let signature = self.send_probe(probe).await?;
        probe.signature = Some(signature);
        self.confirm_probe(probe).await
    }

    /// Get current slot
    async fn get_current_slot(&self) -> Result<u64> {
        self.rpc_client
            .get_slot()
            .await
            .context("Failed to get current slot")
    }

    /// Get network snapshot
    pub async fn get_network_snapshot(&self) -> Result<NetworkSnapshot> {
        // TODO: Implement network snapshot collection
        //
        // Steps:
        // 1. Get current slot
        // 2. Get recent performance samples
        // 3. Get leader schedule
        // 4. Calculate congestion metrics
        // 5. Return NetworkSnapshot
        
        unimplemented!("get_network_snapshot")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_sender_creation() {
        let sender = ProbeSender::new(
            "https://api.devnet.solana.com".to_string(),
            150
        );
        // Basic creation test
    }

    // TODO: Add more tests with mocked RPC
}
