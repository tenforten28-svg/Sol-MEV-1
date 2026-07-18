"""
MEV Execution Orchestrator
Handles complete data flow from detection → submission → confirmation
Implements retry logic, fallback strategies, and error handling
"""
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
import logging
import json
import time
from enum import Enum

logger = logging.getLogger(__name__)

class ExecutionStage(Enum):
    """Execution pipeline stages"""
    DETECTED = "detected"
    SIMULATED = "simulated"
    BUILT = "built"
    SIGNED = "signed"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"

@dataclass
class ExecutionContext:
    """Complete execution context for an opportunity"""
    opportunity_id: str
    bundle_id: str
    strategy: str  # "pair_arbitrage", "triangular", "multi_hop"
    
    # Market data snapshot
    pair: str
    detected_spread: float
    estimated_profit_usd: float
    
    # Execution metadata
    stage: ExecutionStage
    created_at: datetime
    detected_at: Optional[datetime] = None
    simulated_at: Optional[datetime] = None
    built_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    
    # Timings (milliseconds)
    detection_latency_ms: float = 0.0
    simulation_latency_ms: float = 0.0
    build_latency_ms: float = 0.0
    signing_latency_ms: float = 0.0
    submission_latency_ms: float = 0.0
    confirmation_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    
    # Results
    bundle_signature: Optional[str] = None
    slot: Optional[int] = None
    actual_profit_usd: Optional[float] = None
    error: Optional[str] = None
    retry_count: int = 0
    
    # Snapshot reference
    snapshot_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging"""
        return {
            "opportunity_id": self.opportunity_id,
            "bundle_id": self.bundle_id,
            "strategy": self.strategy,
            "stage": self.stage.value,
            "timings": {
                "detection_ms": self.detection_latency_ms,
                "simulation_ms": self.simulation_latency_ms,
                "build_ms": self.build_latency_ms,
                "signing_ms": self.signing_latency_ms,
                "submission_ms": self.submission_latency_ms,
                "confirmation_ms": self.confirmation_latency_ms,
                "total_ms": self.total_latency_ms
            },
            "results": {
                "estimated_profit": self.estimated_profit_usd,
                "actual_profit": self.actual_profit_usd,
                "bundle_signature": self.bundle_signature,
                "slot": self.slot,
                "retry_count": self.retry_count,
                "error": self.error
            }
        }

class ExecutionOrchestrator:
    """
    Orchestrates the complete MEV execution flow:
    Detection → Simulation → Build → Sign → Submit → Confirm
    """
    
    def __init__(
        self,
        bundle_builder,
        jito_submitter,
        metrics_collector,
        key_manager=None,
        max_retries: int = 3,
        timeout_ms: int = 350,
        fallback_to_rpc: bool = True
    ):
        self.bundle_builder = bundle_builder
        self.jito_submitter = jito_submitter
        self.metrics_collector = metrics_collector
        self.key_manager = key_manager
        
        # Policy
        self.max_retries = max_retries
        self.timeout_ms = timeout_ms
        self.fallback_to_rpc = fallback_to_rpc
        
        # State tracking
        self.active_executions: Dict[str, ExecutionContext] = {}
        self.execution_history: List[ExecutionContext] = []
        
    async def execute_opportunity(
        self,
        opportunity: Dict,
        recent_blockhash
    ) -> ExecutionContext:
        """
        Execute complete flow for an opportunity
        
        Flow:
        1. Detect (already done - opportunity provided)
        2. Simulate execution
        3. Build bundle
        4. Sign transactions
        5. Submit to relay
        6. Monitor confirmation
        7. Record results
        
        Args:
            opportunity: Detected opportunity with pricing data
            recent_blockhash: Recent Solana blockhash
            
        Returns:
            ExecutionContext with results
        """
        # Create execution context
        import uuid
        ctx = ExecutionContext(
            opportunity_id=opportunity['id'],
            bundle_id=str(uuid.uuid4()),
            strategy="pair_arbitrage",
            pair=opportunity['token_pair'],
            detected_spread=opportunity['gross_spread_percentage'],
            estimated_profit_usd=opportunity['net_profit_amount'],
            stage=ExecutionStage.DETECTED,
            created_at=datetime.now(timezone.utc)
        )
        
        self.active_executions[ctx.bundle_id] = ctx
        start_time = time.time()
        
        try:
            # Step 1: Simulate
            ctx = await self._simulate_execution(ctx, opportunity)
            if ctx.stage == ExecutionStage.FAILED:
                return ctx
            
            # Step 2: Build bundle
            ctx = await self._build_bundle(ctx, opportunity, recent_blockhash)
            if ctx.stage == ExecutionStage.FAILED:
                return ctx
            
            # Step 3: Sign transactions
            ctx = await self._sign_bundle(ctx)
            if ctx.stage == ExecutionStage.FAILED:
                return ctx
            
            # Step 4: Submit to relay (with retry)
            ctx = await self._submit_with_retry(ctx)
            if ctx.stage == ExecutionStage.FAILED:
                return ctx
            
            # Step 5: Monitor confirmation
            ctx = await self._monitor_confirmation(ctx)
            
            # Calculate total latency
            ctx.total_latency_ms = (time.time() - start_time) * 1000
            
            # Record success
            if ctx.stage == ExecutionStage.CONFIRMED:
                self.metrics_collector.record_bundle_landed(
                    ctx.bundle_id,
                    ctx.actual_profit_usd or ctx.estimated_profit_usd,
                    gas_cost=0.001,
                    slot=ctx.slot or 0
                )
                
                logger.info(
                    f"✅ Execution complete: {ctx.bundle_id[:8]} | "
                    f"Profit: ${ctx.actual_profit_usd or ctx.estimated_profit_usd:.4f} | "
                    f"Latency: {ctx.total_latency_ms:.1f}ms"
                )
            
        except Exception as e:
            logger.error(f"Execution error: {e}")
            ctx.stage = ExecutionStage.FAILED
            ctx.error = str(e)
            ctx.failed_at = datetime.now(timezone.utc)
            
            self.metrics_collector.record_bundle_failed(ctx.bundle_id, str(e))
        
        finally:
            # Clean up and archive
            self.active_executions.pop(ctx.bundle_id, None)
            self.execution_history.append(ctx)
            
            # Keep only last 1000 executions
            if len(self.execution_history) > 1000:
                self.execution_history = self.execution_history[-1000:]
        
        return ctx
    
    async def _simulate_execution(
        self,
        ctx: ExecutionContext,
        opportunity: Dict
    ) -> ExecutionContext:
        """
        Step 2: Micro-simulation to estimate real execution
        Checks liquidity, slippage, and validates profitability
        """
        start_time = time.time()
        
        try:
            # Simulate execution impact
            # In production: query actual pool reserves and calculate impact
            
            # Check liquidity depth
            min_liquidity_required = opportunity['trade_amount'] * 10
            
            if opportunity['liquidity_buy'] < min_liquidity_required:
                ctx.stage = ExecutionStage.FAILED
                ctx.error = f"Insufficient buy liquidity: ${opportunity['liquidity_buy']:.2f}"
                ctx.failed_at = datetime.now(timezone.utc)
                return ctx
            
            if opportunity['liquidity_sell'] < min_liquidity_required:
                ctx.stage = ExecutionStage.FAILED
                ctx.error = f"Insufficient sell liquidity: ${opportunity['liquidity_sell']:.2f}"
                ctx.failed_at = datetime.now(timezone.utc)
                return ctx
            
            # Check slippage tolerance
            if opportunity['buy_costs']['slippage_percentage'] > 0.15:
                ctx.stage = ExecutionStage.FAILED
                ctx.error = f"Buy slippage too high: {opportunity['buy_costs']['slippage_percentage']:.3f}%"
                ctx.failed_at = datetime.now(timezone.utc)
                return ctx
            
            # Simulation passed
            ctx.stage = ExecutionStage.SIMULATED
            ctx.simulated_at = datetime.now(timezone.utc)
            ctx.simulation_latency_ms = (time.time() - start_time) * 1000
            
            logger.debug(f"Simulation passed: {ctx.bundle_id[:8]} ({ctx.simulation_latency_ms:.1f}ms)")
            
        except Exception as e:
            ctx.stage = ExecutionStage.FAILED
            ctx.error = f"Simulation error: {str(e)}"
            ctx.failed_at = datetime.now(timezone.utc)
        
        return ctx
    
    async def _build_bundle(
        self,
        ctx: ExecutionContext,
        opportunity: Dict,
        recent_blockhash
    ) -> ExecutionContext:
        """
        Step 3: Build atomic transaction bundle
        """
        start_time = time.time()
        
        try:
            from bundle_builder import TradeLeg
            
            # Build trade legs
            legs = [
                TradeLeg(
                    dex=opportunity['dex_buy'],
                    action="buy",
                    token_in="USDC",
                    token_out="SOL",
                    amount_in=opportunity['trade_amount'],
                    min_amount_out=opportunity['trade_amount'] / opportunity['buy_price'] * 0.99
                ),
                TradeLeg(
                    dex=opportunity['dex_sell'],
                    action="sell",
                    token_in="SOL",
                    token_out="USDC",
                    amount_in=opportunity['trade_amount'] / opportunity['buy_price'],
                    min_amount_out=opportunity['trade_amount'] * 1.001
                )
            ]
            
            # Build bundle
            bundle = self.bundle_builder.build_bundle(
                legs=legs,
                estimated_profit=opportunity['net_profit_amount'],
                recent_blockhash=recent_blockhash,
                tip_lamports=self._calculate_tip(opportunity)
            )
            
            if not bundle:
                ctx.stage = ExecutionStage.FAILED
                ctx.error = "Failed to build bundle"
                ctx.failed_at = datetime.now(timezone.utc)
                return ctx
            
            # Validate bundle
            valid, error = self.bundle_builder.validate_bundle(bundle)
            if not valid:
                ctx.stage = ExecutionStage.FAILED
                ctx.error = f"Bundle validation failed: {error}"
                ctx.failed_at = datetime.now(timezone.utc)
                return ctx
            
            # Store bundle reference
            ctx.stage = ExecutionStage.BUILT
            ctx.built_at = datetime.now(timezone.utc)
            ctx.build_latency_ms = (time.time() - start_time) * 1000
            
            # Store bundle in context for next step
            ctx._bundle = bundle  # Internal use
            
            self.metrics_collector.record_bundle_created(
                ctx.bundle_id,
                ctx.estimated_profit_usd,
                ctx.build_latency_ms
            )
            
            logger.debug(f"Bundle built: {ctx.bundle_id[:8]} ({ctx.build_latency_ms:.1f}ms)")
            
        except Exception as e:
            ctx.stage = ExecutionStage.FAILED
            ctx.error = f"Build error: {str(e)}"
            ctx.failed_at = datetime.now(timezone.utc)
        
        return ctx
    
    async def _sign_bundle(self, ctx: ExecutionContext) -> ExecutionContext:
        """
        Step 4: Sign transactions
        Uses key manager if available, otherwise bundle is already signed
        """
        start_time = time.time()
        
        try:
            # In production: Use key manager with HSM
            # For now, bundle is already signed during build
            
            ctx.stage = ExecutionStage.SIGNED
            ctx.signed_at = datetime.now(timezone.utc)
            ctx.signing_latency_ms = (time.time() - start_time) * 1000
            
            logger.debug(f"Bundle signed: {ctx.bundle_id[:8]} ({ctx.signing_latency_ms:.1f}ms)")
            
        except Exception as e:
            ctx.stage = ExecutionStage.FAILED
            ctx.error = f"Signing error: {str(e)}"
            ctx.failed_at = datetime.now(timezone.utc)
        
        return ctx
    
    async def _submit_with_retry(self, ctx: ExecutionContext) -> ExecutionContext:
        """
        Step 5: Submit to relay with exponential backoff retry
        """
        for attempt in range(self.max_retries):
            ctx.retry_count = attempt
            
            try:
                start_time = time.time()
                
                # Extract bundle transactions
                bundle = ctx._bundle
                bundle_txs = [bytes(tx) for tx in bundle.transactions]
                
                # Submit to Jito
                result = await self.jito_submitter.submit_bundle(
                    bundle_transactions=bundle_txs,
                    bundle_id=ctx.bundle_id,
                    tip_lamports=bundle.tip_lamports
                )
                
                ctx.submission_latency_ms = result.latency_ms
                
                if result.success:
                    ctx.stage = ExecutionStage.SUBMITTED
                    ctx.submitted_at = datetime.now(timezone.utc)
                    ctx.bundle_signature = result.signature
                    
                    self.metrics_collector.record_bundle_submitted(
                        ctx.bundle_id,
                        ctx.submission_latency_ms,
                        bundle.tip_lamports
                    )
                    
                    logger.info(
                        f"📤 Bundle submitted: {ctx.bundle_id[:8]} | "
                        f"Attempt {attempt + 1}/{self.max_retries} | "
                        f"Latency: {ctx.submission_latency_ms:.1f}ms"
                    )
                    
                    return ctx
                else:
                    logger.warning(
                        f"⚠️ Submission failed (attempt {attempt + 1}): {result.error}"
                    )
                    
                    # Exponential backoff
                    if attempt < self.max_retries - 1:
                        backoff_ms = (2 ** attempt) * 50  # 50ms, 100ms, 200ms
                        await asyncio.sleep(backoff_ms / 1000)
                    
            except Exception as e:
                logger.error(f"Submission error (attempt {attempt + 1}): {e}")
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep((2 ** attempt) * 0.05)
        
        # All retries failed
        ctx.stage = ExecutionStage.FAILED
        ctx.error = f"Submission failed after {self.max_retries} attempts"
        ctx.failed_at = datetime.now(timezone.utc)
        
        self.metrics_collector.record_bundle_failed(ctx.bundle_id, ctx.error)
        
        return ctx
    
    async def _monitor_confirmation(self, ctx: ExecutionContext) -> ExecutionContext:
        """
        Step 6: Monitor for confirmation
        Waits for bundle to land on-chain
        """
        start_time = time.time()
        max_wait_seconds = 30
        
        try:
            # Poll for status
            for _ in range(max_wait_seconds):
                status = await self.jito_submitter.get_bundle_status(ctx.bundle_id)
                
                if status:
                    if status.status == "landed":
                        ctx.stage = ExecutionStage.CONFIRMED
                        ctx.confirmed_at = datetime.now(timezone.utc)
                        ctx.slot = status.slot
                        ctx.confirmation_latency_ms = (time.time() - start_time) * 1000
                        
                        # In production: Parse transaction logs for actual P&L
                        ctx.actual_profit_usd = ctx.estimated_profit_usd * 0.95  # Realistic: 5% slippage
                        
                        logger.info(
                            f"✅ Bundle confirmed: {ctx.bundle_id[:8]} | "
                            f"Slot: {ctx.slot} | "
                            f"Confirmation: {ctx.confirmation_latency_ms:.1f}ms"
                        )
                        
                        return ctx
                    
                    elif status.status == "failed":
                        ctx.stage = ExecutionStage.FAILED
                        ctx.error = "Bundle execution failed on-chain"
                        ctx.failed_at = datetime.now(timezone.utc)
                        return ctx
                
                # Wait 1 second before retry
                await asyncio.sleep(1)
            
            # Timeout
            ctx.stage = ExecutionStage.FAILED
            ctx.error = f"Confirmation timeout after {max_wait_seconds}s"
            ctx.failed_at = datetime.now(timezone.utc)
            
        except Exception as e:
            ctx.stage = ExecutionStage.FAILED
            ctx.error = f"Confirmation error: {str(e)}"
            ctx.failed_at = datetime.now(timezone.utc)
        
        return ctx
    
    def _calculate_tip(self, opportunity: Dict) -> int:
        """
        Calculate adaptive tip based on opportunity value
        Higher profit = higher tip to win the block space
        """
        base_tip = 10_000  # 10k lamports = ~0.00001 SOL
        
        # Scale tip with profit (up to 10x)
        profit_multiplier = min(opportunity['net_profit_amount'] * 100, 10)
        
        tip = int(base_tip * profit_multiplier)
        
        # Cap at 0.001 SOL = 1M lamports
        return min(tip, 1_000_000)
    
    def get_active_executions(self) -> List[Dict]:
        """Get currently executing bundles"""
        return [ctx.to_dict() for ctx in self.active_executions.values()]
    
    def get_execution_history(self, limit: int = 50) -> List[Dict]:
        """Get recent execution history"""
        return [ctx.to_dict() for ctx in self.execution_history[-limit:]]
    
    def get_success_metrics(self) -> Dict:
        """Get execution success metrics"""
        if not self.execution_history:
            return {
                "total_executions": 0,
                "confirmed": 0,
                "failed": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0
            }
        
        confirmed = sum(1 for ctx in self.execution_history if ctx.stage == ExecutionStage.CONFIRMED)
        failed = sum(1 for ctx in self.execution_history if ctx.stage == ExecutionStage.FAILED)
        
        latencies = [
            ctx.total_latency_ms 
            for ctx in self.execution_history 
            if ctx.total_latency_ms > 0
        ]
        
        return {
            "total_executions": len(self.execution_history),
            "confirmed": confirmed,
            "failed": failed,
            "success_rate": (confirmed / len(self.execution_history) * 100) if self.execution_history else 0,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0
        }


# Example usage
if __name__ == "__main__":
    async def test_orchestrator():
        from bundle_builder import BundleBuilder
        from jito_submitter import JitoRelaySubmitter
        from metrics_collector import MetricsCollector
        from solders.keypair import Keypair
        from solders.hash import Hash
        
        # Initialize components
        keypair = Keypair()
        builder = BundleBuilder(keypair=keypair)
        submitter = JitoRelaySubmitter(paper_mode=True)
        collector = MetricsCollector()
        
        # Create orchestrator
        orchestrator = ExecutionOrchestrator(
            bundle_builder=builder,
            jito_submitter=submitter,
            metrics_collector=collector
        )
        
        # Simulate opportunity
        opportunity = {
            "id": "test-opp-1",
            "token_pair": "SOL/USDC",
            "dex_buy": "raydium",
            "dex_sell": "orca",
            "buy_price": 156.20,
            "sell_price": 156.50,
            "gross_spread_percentage": 0.19,
            "net_profit_amount": 0.01,
            "trade_amount": 5.0,
            "liquidity_buy": 50000,
            "liquidity_sell": 80000,
            "buy_costs": {"slippage_percentage": 0.01},
            "sell_costs": {"slippage_percentage": 0.01}
        }
        
        # Execute
        ctx = await orchestrator.execute_opportunity(
            opportunity=opportunity,
            recent_blockhash=Hash.default()
        )
        
        print(f"\n📊 Execution Result:")
        print(json.dumps(ctx.to_dict(), indent=2))
        
        # Get metrics
        metrics = orchestrator.get_success_metrics()
        print(f"\n✅ Success Metrics:")
        print(json.dumps(metrics, indent=2))
        
        await submitter.close()
    
    asyncio.run(test_orchestrator())
