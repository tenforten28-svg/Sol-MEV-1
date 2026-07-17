"""
AutoHedge Bridge Test Script
============================
Run this to test the bridge in FALLBACK mode (no API key needed).

Usage (Windows CMD):
    cd backend
    python test_autohedge.py
"""

import asyncio
import sys

# Add color support for Windows
try:
    import colorama
    colorama.init()
except ImportError:
    pass

from autohedge_bridge import (
    get_autohedge_bridge,
    validate_cross_dex_opportunity,
    validate_lp_unlock_opportunity,
    AUTOHEDGE_AVAILABLE
)


async def run_tests():
    print("\n" + "=" * 65)
    print("   VIP-MEV BOT - AutoHedge Bridge Test")
    print("=" * 65)
    
    # Initialize bridge
    bridge = get_autohedge_bridge(
        min_confidence=0.60,      # 60% minimum confidence to approve
        max_risk_score=7.5,       # Max risk score of 7.5/10
        base_position_sol=0.5,    # Default 0.5 SOL per trade
        max_position_sol=3.0,     # Max 3 SOL per trade
        simulation_mode=True
    )
    
    mode = "AI-POWERED" if AUTOHEDGE_AVAILABLE else "FALLBACK (Heuristic)"
    print(f"\n   Mode: {mode}")
    print(f"   Min Confidence: {bridge.min_confidence:.0%}")
    print(f"   Max Risk Score: {bridge.max_risk_score}/10")
    print(f"   Max Position: {bridge.max_position_sol} SOL")
    
    print("\n" + "-" * 65)
    print("   CROSS-DEX ARBITRAGE TESTS")
    print("-" * 65)
    
    # Test scenarios
    test_cases = [
        {
            "name": "HIGH-QUALITY (Should APPROVE)",
            "opp": {
                'token_symbol': 'GOODTOKEN',
                'token_mint': 'Good123ABCxyz789',
                'buy_dex': 'raydium',
                'sell_dex': 'orca',
                'spread_bps': 180,          # 1.8% spread
                'buy_liquidity_usd': 45000,
                'sell_liquidity_usd': 40000,
                'token_age_minutes': 60
            }
        },
        {
            "name": "MEDIUM (Borderline)",
            "opp": {
                'token_symbol': 'MIDTOKEN',
                'token_mint': 'Mid456DEF',
                'buy_dex': 'meteora',
                'sell_dex': 'raydium',
                'spread_bps': 100,          # 1% spread
                'buy_liquidity_usd': 18000,
                'sell_liquidity_usd': 15000,
                'token_age_minutes': 25
            }
        },
        {
            "name": "RISKY (Should REJECT)",
            "opp": {
                'token_symbol': 'NEWTOKEN',
                'token_mint': 'New789GHI',
                'buy_dex': 'raydium',
                'sell_dex': 'meteora',
                'spread_bps': 50,           # 0.5% spread
                'buy_liquidity_usd': 4000,  # Low liquidity
                'sell_liquidity_usd': 3500,
                'token_age_minutes': 2      # Very new = risky
            }
        },
        {
            "name": "EXCELLENT (High spread, good liquidity)",
            "opp": {
                'token_symbol': 'GREATTOKEN',
                'token_mint': 'Great111',
                'buy_dex': 'orca',
                'sell_dex': 'raydium',
                'spread_bps': 250,          # 2.5% spread!
                'buy_liquidity_usd': 80000,
                'sell_liquidity_usd': 70000,
                'token_age_minutes': 120
            }
        }
    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n   Test {i}: {test['name']}")
        print(f"   Token: {test['opp']['token_symbol']}")
        print(f"   Route: {test['opp']['buy_dex']} -> {test['opp']['sell_dex']}")
        print(f"   Spread: {test['opp']['spread_bps']} bps ({test['opp']['spread_bps']/100:.1f}%)")
        print(f"   Liquidity: ${test['opp']['sell_liquidity_usd']:,}")
        print(f"   Token Age: {test['opp']['token_age_minutes']} min")
        
        decision = await validate_cross_dex_opportunity(test['opp'])
        
        status = "✅ APPROVED" if decision.approved else "❌ REJECTED"
        print(f"\n   Result: {status}")
        print(f"   Confidence: {decision.confidence:.0%}")
        print(f"   Risk Score: {decision.risk_score}/10")
        if decision.approved:
            print(f"   Position Size: {decision.position_size_sol:.2f} SOL")
            print(f"   Expected Profit: {decision.expected_profit_pct:.2f}%")
        print(f"   Reasoning: {decision.reasoning}")
    
    print("\n" + "-" * 65)
    print("   LP UNLOCK TEST")
    print("-" * 65)
    
    lp_unlock = {
        'token_symbol': 'LPTOKEN',
        'token_mint': 'LP123ABC',
        'lock_platform': 'streamflow',
        'unlock_time': '2026-03-20T12:00:00Z',
        'lp_amount': 5000.0,
        'lp_value_usd': 75000,
        'pct_of_pool': 25.0,        # 25% of pool unlocking
        'current_price': 0.0005,
        'liquidity_usd': 300000,
        'volume_24h': 150000
    }
    
    print(f"\n   Token: {lp_unlock['token_symbol']}")
    print(f"   Platform: {lp_unlock['lock_platform']}")
    print(f"   Unlock: {lp_unlock['pct_of_pool']:.0f}% of pool")
    print(f"   LP Value: ${lp_unlock['lp_value_usd']:,}")
    
    decision = await validate_lp_unlock_opportunity(lp_unlock)
    
    status = "✅ APPROVED" if decision.approved else "❌ REJECTED"
    print(f"\n   Result: {status}")
    print(f"   Confidence: {decision.confidence:.0%}")
    print(f"   Risk Score: {decision.risk_score}/10")
    if decision.approved:
        print(f"   Position Size: {decision.position_size_sol:.2f} SOL")
    print(f"   Reasoning: {decision.reasoning}")
    
    # Final stats
    print("\n" + "=" * 65)
    print("   SUMMARY")
    print("=" * 65)
    stats = bridge.get_stats()
    print(f"\n   Total Opportunities Analyzed: {stats['total_analyzed']}")
    print(f"   Approved: {stats['approved']}")
    print(f"   Rejected: {stats['rejected']}")
    approval_rate = (stats['approved'] / stats['total_analyzed'] * 100) if stats['total_analyzed'] > 0 else 0
    print(f"   Approval Rate: {approval_rate:.1f}%")
    print(f"   Average Confidence: {stats['avg_confidence']:.0%}")
    
    ai_status = "✅ Active" if stats['autohedge_available'] else "⚠️ Not installed (using fallback)"
    print(f"\n   AutoHedge AI: {ai_status}")
    
    print("\n" + "=" * 65)
    print("   TEST COMPLETE")
    print("=" * 65)
    
    if not AUTOHEDGE_AVAILABLE:
        print("\n   💡 To enable AI-powered decisions:")
        print("      1. pip install -U autohedge")
        print("      2. Add OPENAI_API_KEY=sk-xxx to your .env")
        print("      3. Run this test again to see the difference!")
    
    print()


if __name__ == "__main__":
    asyncio.run(run_tests())
