"""
AutoHedge Bridge for VIP-MEV Arbitrage Bot
============================================
Bridges detected arbitrage opportunities (Cross-DEX and LP Unlock) 
to AutoHedge's multi-agent AI system for intelligent trade validation,
confidence scoring, and dynamic position sizing.

Agents:
  - Director Agent: Evaluates market conditions and opportunity quality
  - Quant Agent: Validates spreads and technical indicators
  - Risk Manager: Determines position size based on risk profile

Usage:
    from autohedge_bridge import AutoHedgeBridge
    
    bridge = AutoHedgeBridge()
    decision = await bridge.validate_opportunity(opportunity_dict)
    
    if decision['approved']:
        execute_trade(decision['position_size_sol'])
"""

import os
import logging
import asyncio
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import AutoHedge - graceful fallback if not installed
try:
    from autohedge import AutoHedge
    AUTOHEDGE_AVAILABLE = True
except ImportError:
    AUTOHEDGE_AVAILABLE = False
    logger.warning("AutoHedge not installed. Run: pip install -U autohedge")


class OpportunityType(Enum):
    CROSS_DEX = "cross_dex"      # Token on multiple DEXes with price discrepancy
    LP_UNLOCK = "lp_unlock"      # Liquidity removal event
    MIGRATION = "migration"      # PumpFun -> PumpSwap migration


@dataclass
class TradeDecision:
    """Result from AutoHedge validation"""
    approved: bool
    confidence: float              # 0.0 - 1.0
    position_size_sol: float       # Recommended trade size
    max_position_sol: float        # Hard cap from risk manager
    reasoning: str
    risk_score: float              # 1-10, higher = riskier
    expected_profit_sol: float
    expected_profit_pct: float
    stop_loss_pct: float
    timestamp: datetime


class AutoHedgeBridge:
    """
    Bridge between VIP-MEV bot's detection layer and AutoHedge's AI agents.
    
    The bridge converts arbitrage opportunities into a format that AutoHedge
    can analyze, then interprets the AI response back into actionable trade parameters.
    """
    
    def __init__(
        self,
        min_confidence: float = 0.65,
        max_risk_score: float = 7.0,
        base_position_sol: float = 0.5,
        max_position_sol: float = 5.0,
        simulation_mode: bool = True
    ):
        """
        Initialize the AutoHedge bridge.
        
        Args:
            min_confidence: Minimum AI confidence to approve trade (0-1)
            max_risk_score: Maximum risk score to approve trade (1-10)
            base_position_sol: Default position size in SOL
            max_position_sol: Maximum position size cap
            simulation_mode: If True, only log decisions without executing
        """
        self.min_confidence = min_confidence
        self.max_risk_score = max_risk_score
        self.base_position_sol = base_position_sol
        self.max_position_sol = max_position_sol
        self.simulation_mode = simulation_mode
        
        self._autohedge = None
        self._initialized = False
        
        # Track decisions for analytics
        self.decision_history: list = []
        self.stats = {
            'total_analyzed': 0,
            'approved': 0,
            'rejected': 0,
            'avg_confidence': 0.0,
            'total_profit_est': 0.0
        }
    
    def _ensure_initialized(self):
        """Lazy initialization of AutoHedge"""
        if self._initialized:
            return True
            
        if not AUTOHEDGE_AVAILABLE:
            logger.error("AutoHedge not available. Install with: pip install -U autohedge")
            return False
        
        # Check for API key
        api_key = os.environ.get('OPENAI_API_KEY') or os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            logger.error("No LLM API key found. Set OPENAI_API_KEY or ANTHROPIC_API_KEY")
            return False
        
        try:
            # Initialize AutoHedge with proper configuration
            # AutoHedge uses simple initialization: AutoHedge(name, description)
            self._autohedge = AutoHedge(
                name="vip-mev-validator",
                description="AI validator for Solana arbitrage opportunities. Analyzes Cross-DEX spreads, LP unlocks, and token migrations.",
                output_type="str"  # Return as string for easier parsing
            )
            self._initialized = True
            logger.info("AutoHedge initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize AutoHedge: {e}")
            return False
    
    async def validate_opportunity(
        self,
        opportunity: Dict[str, Any],
        opp_type: OpportunityType = OpportunityType.CROSS_DEX
    ) -> TradeDecision:
        """
        Validate an arbitrage opportunity using AutoHedge AI agents.
        
        Args:
            opportunity: Dict containing opportunity details
            opp_type: Type of opportunity (CROSS_DEX, LP_UNLOCK, MIGRATION)
            
        Returns:
            TradeDecision with approval status and trade parameters
        """
        self.stats['total_analyzed'] += 1
        
        # Build task description based on opportunity type
        task = self._build_task_description(opportunity, opp_type)
        
        # Check if AutoHedge is available
        if not self._ensure_initialized():
            # Fallback: Use heuristic-based validation
            return self._fallback_validation(opportunity, opp_type)
        
        try:
            # Run AutoHedge analysis
            # AutoHedge.run(task) returns a conversation with agent responses
            loop = asyncio.get_event_loop()
            ai_response = await loop.run_in_executor(
                None,
                lambda: self._autohedge.run(task=task)
            )
            
            # Parse AI response
            decision = self._parse_ai_decision(ai_response, opportunity)
            
        except Exception as e:
            logger.error(f"AutoHedge analysis failed: {e}")
            decision = self._fallback_validation(opportunity, opp_type)
        
        # Apply risk limits
        decision = self._apply_risk_limits(decision)
        
        # Update stats
        if decision.approved:
            self.stats['approved'] += 1
            self.stats['total_profit_est'] += decision.expected_profit_sol
        else:
            self.stats['rejected'] += 1
        
        # Rolling average confidence
        n = self.stats['total_analyzed']
        self.stats['avg_confidence'] = (
            (self.stats['avg_confidence'] * (n - 1) + decision.confidence) / n
        )
        
        # Store in history
        self.decision_history.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'opportunity': opportunity,
            'decision': decision.__dict__
        })
        
        # Keep history bounded
        if len(self.decision_history) > 1000:
            self.decision_history = self.decision_history[-500:]
        
        self._log_decision(opportunity, decision, opp_type)
        
        return decision
    
    def _build_task_description(
        self,
        opportunity: Dict[str, Any],
        opp_type: OpportunityType
    ) -> str:
        """Build AutoHedge task description from opportunity"""
        
        if opp_type == OpportunityType.CROSS_DEX:
            return f"""
SOLANA DEX ARBITRAGE OPPORTUNITY ANALYSIS

Token: {opportunity.get('token_symbol', 'Unknown')} ({opportunity.get('token_mint', 'N/A')[:20]}...)
Type: Cross-DEX Price Discrepancy

Market Data:
- Buy DEX: {opportunity.get('buy_dex', 'Unknown')} @ ${opportunity.get('buy_price', 0):.8f}
- Sell DEX: {opportunity.get('sell_dex', 'Unknown')} @ ${opportunity.get('sell_price', 0):.8f}
- Spread: {opportunity.get('spread_bps', 0):.2f} bps ({opportunity.get('spread_pct', 0):.4f}%)
- Buy Liquidity: ${opportunity.get('buy_liquidity_usd', 0):,.2f}
- Sell Liquidity: ${opportunity.get('sell_liquidity_usd', 0):,.2f}
- Token Age: {opportunity.get('token_age_minutes', 0):.1f} minutes

Execution Context:
- Network: Solana Mainnet
- Execution Method: Jito Bundle (MEV-protected)
- Flash Loan Available: Yes (Solend)
- Estimated Gas: ~0.002 SOL

Task: Evaluate this arbitrage opportunity. Consider:
1. Is the spread sufficient after fees (~0.5% total)?
2. Is liquidity adequate for the trade size?
3. Is the token too new (high rug risk) or established?
4. What position size (in SOL) balances profit vs. risk?

Return JSON with:
- action: "EXECUTE" or "SKIP"
- confidence: 0.0-1.0
- position_size_sol: recommended trade size
- risk_score: 1-10
- reasoning: brief explanation
"""
        
        elif opp_type == OpportunityType.LP_UNLOCK:
            return f"""
SOLANA LP UNLOCK ARBITRAGE OPPORTUNITY ANALYSIS

Token: {opportunity.get('token_symbol', 'Unknown')} ({opportunity.get('token_mint', 'N/A')[:20]}...)
Type: Liquidity Provider Unlock Event

Event Data:
- Lock Platform: {opportunity.get('lock_platform', 'Unknown')}
- Unlock Time: {opportunity.get('unlock_time', 'Unknown')}
- LP Amount: {opportunity.get('lp_amount', 0):,.4f} LP tokens
- LP Value (USD): ${opportunity.get('lp_value_usd', 0):,.2f}
- Percentage of Pool: {opportunity.get('pct_of_pool', 0):.2f}%

Market Context:
- Current Price: ${opportunity.get('current_price', 0):.8f}
- 24h Volume: ${opportunity.get('volume_24h', 0):,.2f}
- Liquidity: ${opportunity.get('liquidity_usd', 0):,.2f}

Risk Assessment:
- If >50% of pool unlocks = HIGH RISK (likely dump)
- If <10% of pool = LOW RISK (normal unlock)
- Team wallet unlock = MEDIUM-HIGH RISK

Task: Evaluate this LP unlock event. Consider:
1. Will this unlock cause significant price impact?
2. Should we short before unlock or buy the dip after?
3. What position size is appropriate given the risk?
4. What's the expected profit/loss scenario?

Return JSON with:
- action: "SHORT_BEFORE", "BUY_DIP", or "SKIP"
- confidence: 0.0-1.0
- position_size_sol: recommended trade size
- risk_score: 1-10
- entry_price: target entry
- exit_price: target exit
- stop_loss_pct: max loss percentage
- reasoning: brief explanation
"""
        
        else:  # MIGRATION
            return f"""
PUMPFUN MIGRATION ARBITRAGE OPPORTUNITY

Token: {opportunity.get('token_symbol', 'Unknown')}
Type: PumpFun -> PumpSwap/Raydium Migration

Migration Data:
- Source: PumpFun Bonding Curve
- Destination: {opportunity.get('destination_dex', 'PumpSwap/Raydium')}
- Migration Status: {opportunity.get('migration_status', 'Pending')}
- Bonding Curve Progress: {opportunity.get('bonding_progress', 0):.1f}%

Market Data:
- PumpFun Price: ${opportunity.get('pumpfun_price', 0):.8f}
- DEX Price: ${opportunity.get('dex_price', 0):.8f}
- Spread: {opportunity.get('spread_bps', 0):.2f} bps

Task: Evaluate this migration opportunity. Consider:
1. Is migration confirmed or still pending?
2. Expected price movement post-migration?
3. Competition from other MEV bots?
4. Optimal entry timing?

Return JSON with:
- action: "EXECUTE" or "SKIP"
- confidence: 0.0-1.0
- position_size_sol: recommended trade size
- risk_score: 1-10
- reasoning: brief explanation
"""
    
    def _parse_ai_decision(
        self,
        ai_response: Any,
        opportunity: Dict[str, Any]
    ) -> TradeDecision:
        """Parse AutoHedge AI response into TradeDecision"""
        
        import json
        
        # Handle various response formats
        if isinstance(ai_response, str):
            try:
                # Try to extract JSON from response
                if '{' in ai_response:
                    json_start = ai_response.find('{')
                    json_end = ai_response.rfind('}') + 1
                    ai_response = json.loads(ai_response[json_start:json_end])
                else:
                    ai_response = {}
            except json.JSONDecodeError:
                ai_response = {}
        
        if isinstance(ai_response, dict):
            action = ai_response.get('action', 'SKIP').upper()
            approved = action in ['EXECUTE', 'BUY', 'BUY_DIP', 'SHORT_BEFORE']
            confidence = float(ai_response.get('confidence', 0.5))
            position_size = float(ai_response.get('position_size_sol', self.base_position_sol))
            risk_score = float(ai_response.get('risk_score', 5.0))
            reasoning = ai_response.get('reasoning', 'No reasoning provided')
            stop_loss = float(ai_response.get('stop_loss_pct', 5.0))
        else:
            # Fallback defaults
            approved = False
            confidence = 0.5
            position_size = self.base_position_sol
            risk_score = 5.0
            reasoning = "Unable to parse AI response"
            stop_loss = 5.0
        
        # Calculate expected profit
        spread_pct = opportunity.get('spread_pct', 0) or opportunity.get('spread_bps', 0) / 100
        expected_profit_pct = max(0, spread_pct - 0.5)  # Subtract ~0.5% fees
        expected_profit_sol = position_size * (expected_profit_pct / 100)
        
        return TradeDecision(
            approved=approved,
            confidence=confidence,
            position_size_sol=position_size,
            max_position_sol=self.max_position_sol,
            reasoning=reasoning,
            risk_score=risk_score,
            expected_profit_sol=expected_profit_sol,
            expected_profit_pct=expected_profit_pct,
            stop_loss_pct=stop_loss,
            timestamp=datetime.now(timezone.utc)
        )
    
    def _fallback_validation(
        self,
        opportunity: Dict[str, Any],
        opp_type: OpportunityType
    ) -> TradeDecision:
        """
        Heuristic-based validation when AutoHedge is unavailable.
        Uses rule-based logic as a fallback.
        """
        logger.info("Using fallback heuristic validation")
        
        # Extract key metrics
        spread_bps = opportunity.get('spread_bps', 0)
        spread_pct = spread_bps / 100
        liquidity_usd = min(
            opportunity.get('buy_liquidity_usd', 0),
            opportunity.get('sell_liquidity_usd', opportunity.get('liquidity_usd', 0))
        )
        token_age_min = opportunity.get('token_age_minutes', 0)
        
        # Base confidence from spread
        if spread_bps >= 200:  # 2%+ spread
            confidence = 0.85
        elif spread_bps >= 100:  # 1%+ spread
            confidence = 0.70
        elif spread_bps >= 50:  # 0.5%+ spread
            confidence = 0.55
        else:
            confidence = 0.30
        
        # Adjust for liquidity
        if liquidity_usd < 5000:
            confidence *= 0.5
            risk_score = 8.0
        elif liquidity_usd < 20000:
            confidence *= 0.8
            risk_score = 6.0
        elif liquidity_usd < 50000:
            risk_score = 4.0
        else:
            risk_score = 3.0
        
        # Adjust for token age (newer = riskier)
        if token_age_min < 5:
            confidence *= 0.6
            risk_score = min(10, risk_score + 3)
        elif token_age_min < 30:
            confidence *= 0.85
            risk_score = min(10, risk_score + 1)
        
        # LP Unlock specific adjustments
        if opp_type == OpportunityType.LP_UNLOCK:
            pct_of_pool = opportunity.get('pct_of_pool', 0)
            if pct_of_pool > 50:
                confidence *= 0.5
                risk_score = min(10, risk_score + 2)
            elif pct_of_pool > 20:
                confidence *= 0.8
        
        # Determine position size based on confidence and risk
        if confidence >= 0.8 and risk_score <= 4:
            position_size = self.max_position_sol * 0.8
        elif confidence >= 0.65 and risk_score <= 6:
            position_size = self.base_position_sol * 1.5
        elif confidence >= 0.5:
            position_size = self.base_position_sol
        else:
            position_size = self.base_position_sol * 0.5
        
        # Final approval check
        approved = (
            confidence >= self.min_confidence and
            risk_score <= self.max_risk_score and
            spread_bps >= 30  # Minimum 0.3% spread
        )
        
        reasoning = (
            f"Heuristic: spread={spread_bps:.0f}bps, "
            f"liquidity=${liquidity_usd:,.0f}, "
            f"age={token_age_min:.0f}min"
        )
        
        expected_profit_pct = max(0, spread_pct - 0.5)
        expected_profit_sol = position_size * (expected_profit_pct / 100)
        
        return TradeDecision(
            approved=approved,
            confidence=round(confidence, 2),
            position_size_sol=round(position_size, 3),
            max_position_sol=self.max_position_sol,
            reasoning=reasoning,
            risk_score=round(risk_score, 1),
            expected_profit_sol=round(expected_profit_sol, 6),
            expected_profit_pct=round(expected_profit_pct, 4),
            stop_loss_pct=5.0,
            timestamp=datetime.now(timezone.utc)
        )
    
    def _apply_risk_limits(self, decision: TradeDecision) -> TradeDecision:
        """Apply hard risk limits to decision"""
        
        # Cap position size
        decision.position_size_sol = min(
            decision.position_size_sol,
            self.max_position_sol
        )
        
        # Reject if below min confidence
        if decision.confidence < self.min_confidence:
            decision.approved = False
            decision.reasoning += f" | REJECTED: confidence {decision.confidence:.2f} < {self.min_confidence}"
        
        # Reject if above max risk
        if decision.risk_score > self.max_risk_score:
            decision.approved = False
            decision.reasoning += f" | REJECTED: risk {decision.risk_score:.1f} > {self.max_risk_score}"
        
        return decision
    
    def _log_decision(
        self,
        opportunity: Dict[str, Any],
        decision: TradeDecision,
        opp_type: OpportunityType
    ):
        """Log decision for debugging and analytics"""
        
        token = opportunity.get('token_symbol', opportunity.get('token_mint', 'Unknown')[:20])
        status = "APPROVED" if decision.approved else "REJECTED"
        emoji = "✅" if decision.approved else "❌"
        
        logger.info(
            f"{emoji} AutoHedge [{opp_type.value}] {token}: {status} | "
            f"conf={decision.confidence:.2f} risk={decision.risk_score:.1f} "
            f"size={decision.position_size_sol:.3f} SOL | "
            f"{decision.reasoning}"
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get bridge statistics"""
        approval_rate = (
            self.stats['approved'] / self.stats['total_analyzed'] * 100
            if self.stats['total_analyzed'] > 0 else 0
        )
        
        return {
            **self.stats,
            'approval_rate_pct': round(approval_rate, 2),
            'autohedge_available': AUTOHEDGE_AVAILABLE,
            'initialized': self._initialized,
            'min_confidence': self.min_confidence,
            'max_risk_score': self.max_risk_score,
            'simulation_mode': self.simulation_mode
        }


# ============================================================
# INTEGRATION HELPERS
# ============================================================

# Global singleton instance
_bridge_instance: Optional[AutoHedgeBridge] = None


def get_autohedge_bridge(
    min_confidence: float = 0.65,
    max_risk_score: float = 7.0,
    **kwargs
) -> AutoHedgeBridge:
    """Get or create singleton AutoHedge bridge instance"""
    global _bridge_instance
    
    if _bridge_instance is None:
        _bridge_instance = AutoHedgeBridge(
            min_confidence=min_confidence,
            max_risk_score=max_risk_score,
            **kwargs
        )
    
    return _bridge_instance


async def validate_cross_dex_opportunity(opportunity: Dict[str, Any]) -> TradeDecision:
    """
    Convenience function for Cross-DEX arbitrage validation.
    
    Usage in pumpfun_arbitrage.py:
        from autohedge_bridge import validate_cross_dex_opportunity
        
        decision = await validate_cross_dex_opportunity({
            'token_symbol': 'MYTOKEN',
            'token_mint': 'ABC123...',
            'buy_dex': 'raydium',
            'sell_dex': 'orca',
            'buy_price': 0.00001,
            'sell_price': 0.000012,
            'spread_bps': 200,
            'spread_pct': 2.0,
            'buy_liquidity_usd': 15000,
            'sell_liquidity_usd': 12000,
            'token_age_minutes': 15
        })
        
        if decision.approved:
            execute_trade(decision.position_size_sol)
    """
    bridge = get_autohedge_bridge()
    return await bridge.validate_opportunity(opportunity, OpportunityType.CROSS_DEX)


async def validate_lp_unlock_opportunity(opportunity: Dict[str, Any]) -> TradeDecision:
    """
    Convenience function for LP Unlock arbitrage validation.
    
    Usage in lp_unlock_arbitrage.py:
        from autohedge_bridge import validate_lp_unlock_opportunity
        
        decision = await validate_lp_unlock_opportunity({
            'token_symbol': 'MYTOKEN',
            'token_mint': 'ABC123...',
            'lock_platform': 'streamflow',
            'unlock_time': '2026-03-15T12:00:00Z',
            'lp_amount': 1000.0,
            'lp_value_usd': 50000,
            'pct_of_pool': 15.0,
            'current_price': 0.00001,
            'liquidity_usd': 100000,
            'volume_24h': 50000
        })
        
        if decision.approved:
            if decision.reasoning includes 'SHORT':
                short_before_unlock(decision.position_size_sol)
            else:
                prepare_buy_dip(decision.position_size_sol)
    """
    bridge = get_autohedge_bridge()
    return await bridge.validate_opportunity(opportunity, OpportunityType.LP_UNLOCK)


async def validate_migration_opportunity(opportunity: Dict[str, Any]) -> TradeDecision:
    """
    Convenience function for PumpFun migration validation.
    """
    bridge = get_autohedge_bridge()
    return await bridge.validate_opportunity(opportunity, OpportunityType.MIGRATION)


# ============================================================
# TEST / DEBUG
# ============================================================

async def test_bridge():
    """Test the AutoHedge bridge with sample data"""
    
    print("\n" + "=" * 60)
    print("  AutoHedge Bridge Test")
    print("=" * 60)
    
    bridge = get_autohedge_bridge(
        min_confidence=0.6,
        max_risk_score=7.5,
        simulation_mode=True
    )
    
    # Test 1: High-quality Cross-DEX opportunity
    print("\n1. Testing HIGH-QUALITY Cross-DEX opportunity...")
    opp1 = {
        'token_symbol': 'TESTCOIN',
        'token_mint': 'ABC123xyz789',
        'buy_dex': 'raydium',
        'sell_dex': 'orca',
        'buy_price': 0.00001,
        'sell_price': 0.000012,
        'spread_bps': 200,  # 2% spread
        'spread_pct': 2.0,
        'buy_liquidity_usd': 25000,
        'sell_liquidity_usd': 20000,
        'token_age_minutes': 30
    }
    
    decision1 = await validate_cross_dex_opportunity(opp1)
    print(f"   Approved: {decision1.approved}")
    print(f"   Confidence: {decision1.confidence:.2f}")
    print(f"   Position: {decision1.position_size_sol:.3f} SOL")
    print(f"   Risk Score: {decision1.risk_score:.1f}")
    print(f"   Reasoning: {decision1.reasoning}")
    
    # Test 2: Low-quality opportunity (should reject)
    print("\n2. Testing LOW-QUALITY opportunity (should reject)...")
    opp2 = {
        'token_symbol': 'SCAMCOIN',
        'token_mint': 'XYZ999',
        'buy_dex': 'raydium',
        'sell_dex': 'meteora',
        'buy_price': 0.001,
        'sell_price': 0.00102,
        'spread_bps': 20,  # Only 0.2% spread
        'spread_pct': 0.2,
        'buy_liquidity_usd': 2000,  # Low liquidity
        'sell_liquidity_usd': 1500,
        'token_age_minutes': 2  # Very new
    }
    
    decision2 = await validate_cross_dex_opportunity(opp2)
    print(f"   Approved: {decision2.approved}")
    print(f"   Confidence: {decision2.confidence:.2f}")
    print(f"   Risk Score: {decision2.risk_score:.1f}")
    print(f"   Reasoning: {decision2.reasoning}")
    
    # Test 3: LP Unlock opportunity
    print("\n3. Testing LP UNLOCK opportunity...")
    opp3 = {
        'token_symbol': 'LPTOKEN',
        'token_mint': 'LP123ABC',
        'lock_platform': 'streamflow',
        'unlock_time': '2026-03-20T12:00:00Z',
        'lp_amount': 5000.0,
        'lp_value_usd': 75000,
        'pct_of_pool': 25.0,
        'current_price': 0.0005,
        'liquidity_usd': 300000,
        'volume_24h': 150000
    }
    
    decision3 = await validate_lp_unlock_opportunity(opp3)
    print(f"   Approved: {decision3.approved}")
    print(f"   Confidence: {decision3.confidence:.2f}")
    print(f"   Position: {decision3.position_size_sol:.3f} SOL")
    print(f"   Reasoning: {decision3.reasoning}")
    
    # Print stats
    print("\n" + "=" * 60)
    print("  Bridge Statistics")
    print("=" * 60)
    stats = bridge.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_bridge())
