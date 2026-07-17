"""
Jito Relay Submitter - Handles bundle submission to Jito Block Engine
Provides low-latency bundle submission with adaptive tip bidding
"""
import aiohttp
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
import logging
import base58
import json
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class BundleSubmissionResult:
    """Result of bundle submission"""
    success: bool
    bundle_id: str
    signature: Optional[str] = None
    slot: Optional[int] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    submitted_at: datetime = None
    
    def __post_init__(self):
        if self.submitted_at is None:
            self.submitted_at = datetime.now(timezone.utc)

@dataclass
class BundleStatus:
    """Status of submitted bundle"""
    bundle_id: str
    status: str  # pending, landed, failed, expired
    slot: Optional[int] = None
    confirmation_time: Optional[float] = None
    transactions: List[str] = None

class JitoRelaySubmitter:
    """Submits transaction bundles to Jito Block Engine"""
    
    # Jito Block Engine endpoints
    JITO_ENDPOINTS = {
        "mainnet": [
            "https://mainnet.block-engine.jito.wtf",
            "https://amsterdam.mainnet.block-engine.jito.wtf",
            "https://frankfurt.mainnet.block-engine.jito.wtf",
            "https://ny.mainnet.block-engine.jito.wtf",
            "https://tokyo.mainnet.block-engine.jito.wtf"
        ],
        "devnet": [
            "https://dallas.devnet.block-engine.jito.wtf",
            "https://amsterdam.devnet.block-engine.jito.wtf"
        ]
    }
    
    def __init__(
        self,
        network: str = "devnet",
        timeout_seconds: int = 5,
        max_retries: int = 2,
        paper_mode: bool = True
    ):
        self.network = network
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.max_retries = max_retries
        self.paper_mode = paper_mode
        
        self.endpoints = self.JITO_ENDPOINTS.get(network, self.JITO_ENDPOINTS["devnet"])
        self.current_endpoint_idx = 0
        
        # Metrics
        self.submitted_count = 0
        self.successful_count = 0
        self.failed_count = 0
        self.total_latency_ms = 0.0
        
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def ensure_session(self):
        """Ensure aiohttp session exists"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
    
    def get_next_endpoint(self) -> str:
        """Round-robin endpoint selection for load balancing"""
        endpoint = self.endpoints[self.current_endpoint_idx]
        self.current_endpoint_idx = (self.current_endpoint_idx + 1) % len(self.endpoints)
        return endpoint
    
    async def submit_bundle(
        self,
        bundle_transactions: List[bytes],
        bundle_id: str,
        tip_lamports: int
    ) -> BundleSubmissionResult:
        """
        Submit a bundle to Jito Block Engine
        
        Args:
            bundle_transactions: List of serialized signed transactions
            bundle_id: Unique bundle identifier
            tip_lamports: Tip amount in lamports
            
        Returns:
            BundleSubmissionResult with submission outcome
        """
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Paper mode - simulate submission
            if self.paper_mode:
                await asyncio.sleep(0.05)  # Simulate 50ms latency
                
                latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                
                self.submitted_count += 1
                self.successful_count += 1
                self.total_latency_ms += latency_ms
                
                logger.info(
                    f"📝 PAPER MODE: Bundle {bundle_id[:8]} submitted "
                    f"(tip={tip_lamports} lamports, latency={latency_ms:.1f}ms)"
                )
                
                return BundleSubmissionResult(
                    success=True,
                    bundle_id=bundle_id,
                    signature="SIMULATED_" + bundle_id[:16],
                    slot=123456789,
                    latency_ms=latency_ms
                )
            
            # Real submission
            await self.ensure_session()
            endpoint = self.get_next_endpoint()
            
            # Encode transactions to base58
            encoded_txs = [base58.b58encode(tx).decode('utf-8') for tx in bundle_transactions]
            
            # Prepare Jito bundle payload
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [encoded_txs]
            }
            
            # Submit to Jito
            url = f"{endpoint}/api/v1/bundles"
            
            async with self.session.post(url, json=payload) as response:
                latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
                
                if response.status == 200:
                    result = await response.json()
                    
                    self.submitted_count += 1
                    self.successful_count += 1
                    self.total_latency_ms += latency_ms
                    
                    bundle_uuid = result.get('result', bundle_id)
                    
                    logger.info(
                        f"✅ Bundle submitted: {bundle_id[:8]} "
                        f"(tip={tip_lamports}, latency={latency_ms:.1f}ms)"
                    )
                    
                    return BundleSubmissionResult(
                        success=True,
                        bundle_id=bundle_id,
                        signature=bundle_uuid,
                        latency_ms=latency_ms
                    )
                else:
                    error_text = await response.text()
                    
                    self.submitted_count += 1
                    self.failed_count += 1
                    
                    logger.error(
                        f"❌ Bundle submission failed: {response.status} - {error_text}"
                    )
                    
                    return BundleSubmissionResult(
                        success=False,
                        bundle_id=bundle_id,
                        error=f"HTTP {response.status}: {error_text}",
                        latency_ms=latency_ms
                    )
                    
        except asyncio.TimeoutError:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self.submitted_count += 1
            self.failed_count += 1
            
            logger.error(f"⏱️ Bundle submission timeout after {latency_ms:.1f}ms")
            
            return BundleSubmissionResult(
                success=False,
                bundle_id=bundle_id,
                error="Timeout",
                latency_ms=latency_ms
            )
            
        except Exception as e:
            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self.submitted_count += 1
            self.failed_count += 1
            
            logger.error(f"❌ Bundle submission error: {e}")
            
            return BundleSubmissionResult(
                success=False,
                bundle_id=bundle_id,
                error=str(e),
                latency_ms=latency_ms
            )
    
    async def get_bundle_status(self, bundle_id: str) -> Optional[BundleStatus]:
        """
        Check status of submitted bundle
        
        Args:
            bundle_id: Bundle identifier
            
        Returns:
            BundleStatus or None if not found
        """
        if self.paper_mode:
            # Simulate bundle status
            return BundleStatus(
                bundle_id=bundle_id,
                status="landed",
                slot=123456789,
                confirmation_time=2.5,
                transactions=["SIMULATED_TX"]
            )
        
        try:
            await self.ensure_session()
            endpoint = self.get_next_endpoint()
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBundleStatuses",
                "params": [[bundle_id]]
            }
            
            url = f"{endpoint}/api/v1/bundles"
            
            async with self.session.post(url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    bundles = result.get('result', {}).get('value', [])
                    
                    if bundles:
                        bundle_data = bundles[0]
                        return BundleStatus(
                            bundle_id=bundle_id,
                            status=bundle_data.get('status', 'unknown'),
                            slot=bundle_data.get('slot'),
                            confirmation_time=bundle_data.get('confirmation_time'),
                            transactions=bundle_data.get('transactions', [])
                        )
                        
        except Exception as e:
            logger.error(f"Error getting bundle status: {e}")
        
        return None
    
    def calculate_adaptive_tip(
        self,
        base_tip: int,
        competition_level: float,
        urgency: float
    ) -> int:
        """
        Calculate adaptive tip based on market conditions
        
        Args:
            base_tip: Base tip in lamports
            competition_level: 0.0 to 1.0 (low to high competition)
            urgency: 0.0 to 1.0 (low to high urgency)
            
        Returns:
            Adjusted tip in lamports
        """
        # Increase tip based on competition and urgency
        multiplier = 1.0 + (competition_level * 2.0) + (urgency * 3.0)
        adjusted_tip = int(base_tip * multiplier)
        
        # Cap at reasonable maximum (e.g., 0.01 SOL = 10M lamports)
        max_tip = 10_000_000
        return min(adjusted_tip, max_tip)
    
    def get_metrics(self) -> Dict:
        """Get submission metrics"""
        avg_latency = (
            self.total_latency_ms / self.submitted_count 
            if self.submitted_count > 0 else 0.0
        )
        
        success_rate = (
            (self.successful_count / self.submitted_count * 100)
            if self.submitted_count > 0 else 0.0
        )
        
        return {
            "submitted_count": self.submitted_count,
            "successful_count": self.successful_count,
            "failed_count": self.failed_count,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency,
            "paper_mode": self.paper_mode
        }
    
    async def close(self):
        """Close HTTP session"""
        if self.session and not self.session.closed:
            await self.session.close()


# Test/Example usage
async def test_jito_submitter():
    """Test the Jito submitter"""
    
    submitter = JitoRelaySubmitter(
        network="devnet",
        paper_mode=True  # Safe testing
    )
    
    # Simulate bundle submission
    dummy_tx = bytes([0] * 100)  # Placeholder transaction
    
    result = await submitter.submit_bundle(
        bundle_transactions=[dummy_tx],
        bundle_id="test-bundle-123",
        tip_lamports=10_000
    )
    
    print(f"\nSubmission Result:")
    print(f"  Success: {result.success}")
    print(f"  Bundle ID: {result.bundle_id}")
    print(f"  Signature: {result.signature}")
    print(f"  Latency: {result.latency_ms:.1f}ms")
    
    # Check status
    status = await submitter.get_bundle_status(result.bundle_id)
    if status:
        print(f"\nBundle Status:")
        print(f"  Status: {status.status}")
        print(f"  Slot: {status.slot}")
        print(f"  Confirmation Time: {status.confirmation_time}s")
    
    # Get metrics
    metrics = submitter.get_metrics()
    print(f"\nMetrics:")
    print(f"  Submitted: {metrics['submitted_count']}")
    print(f"  Success Rate: {metrics['success_rate']:.1f}%")
    print(f"  Avg Latency: {metrics['avg_latency_ms']:.1f}ms")
    
    await submitter.close()


if __name__ == "__main__":
    asyncio.run(test_jito_submitter())
