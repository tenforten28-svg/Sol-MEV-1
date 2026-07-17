#!/usr/bin/env python3
"""
Detailed Backend Test - Wait for opportunities and analyze system behavior
"""

import asyncio
import aiohttp
import json
from datetime import datetime, timezone
import time

# Get backend URL from frontend .env file
def get_backend_url():
    try:
        with open('/app/frontend/.env', 'r') as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    return line.split('=', 1)[1].strip()
    except Exception as e:
        print(f"Error reading frontend .env: {e}")
    return "http://localhost:8001"

BACKEND_URL = get_backend_url()
API_BASE = f"{BACKEND_URL}/api"

async def monitor_system_for_opportunities():
    """Monitor the system for 60 seconds to see if opportunities are generated"""
    print("🔍 Monitoring system for 60 seconds to observe opportunity generation...")
    
    async with aiohttp.ClientSession() as session:
        start_time = time.time()
        opportunity_count = 0
        trade_count = 0
        meme_opportunity_count = 0
        meme_trade_count = 0
        
        while time.time() - start_time < 60:  # Monitor for 60 seconds
            try:
                # Check stablecoin opportunities
                async with session.get(f"{API_BASE}/opportunities") as response:
                    if response.status == 200:
                        opportunities = await response.json()
                        current_opp_count = len(opportunities)
                        if current_opp_count > opportunity_count:
                            print(f"📈 New stablecoin opportunities detected: {current_opp_count}")
                            opportunity_count = current_opp_count
                
                # Check stablecoin trades
                async with session.get(f"{API_BASE}/trades?limit=5") as response:
                    if response.status == 200:
                        trades = await response.json()
                        current_trade_count = len(trades)
                        if current_trade_count > trade_count:
                            print(f"💰 New stablecoin trades detected: {current_trade_count}")
                            trade_count = current_trade_count
                
                # Check meme opportunities
                async with session.get(f"{API_BASE}/meme/opportunities") as response:
                    if response.status == 200:
                        meme_opportunities = await response.json()
                        current_meme_opp_count = len(meme_opportunities)
                        if current_meme_opp_count != meme_opportunity_count:
                            print(f"🎯 Meme opportunities: {current_meme_opp_count}")
                            meme_opportunity_count = current_meme_opp_count
                
                # Check meme trades
                async with session.get(f"{API_BASE}/meme/trades") as response:
                    if response.status == 200:
                        meme_trades = await response.json()
                        current_meme_trade_count = len(meme_trades)
                        if current_meme_trade_count > meme_trade_count:
                            print(f"🚀 New meme trades detected: {current_meme_trade_count}")
                            meme_trade_count = current_meme_trade_count
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                print(f"Error during monitoring: {e}")
                await asyncio.sleep(5)
        
        print(f"\n📊 Monitoring Results:")
        print(f"  - Stablecoin opportunities observed: {opportunity_count}")
        print(f"  - Stablecoin trades observed: {trade_count}")
        print(f"  - Meme opportunities observed: {meme_opportunity_count}")
        print(f"  - Meme trades observed: {meme_trade_count}")
        
        return {
            'stablecoin_opportunities': opportunity_count,
            'stablecoin_trades': trade_count,
            'meme_opportunities': meme_opportunity_count,
            'meme_trades': meme_trade_count
        }

async def analyze_price_data():
    """Analyze the price data being used"""
    print("\n🔍 Analyzing Price Data...")
    
    async with aiohttp.ClientSession() as session:
        # Get current opportunities to see price ranges
        async with session.get(f"{API_BASE}/opportunities?limit=1") as response:
            if response.status == 200:
                opportunities = await response.json()
                if opportunities:
                    opp = opportunities[0]
                    print(f"📈 Recent Stablecoin Opportunity:")
                    print(f"  - Pair: {opp.get('token_pair')}")
                    print(f"  - Buy Price: ${opp.get('buy_price', 0):.4f}")
                    print(f"  - Sell Price: ${opp.get('sell_price', 0):.4f}")
                    print(f"  - Net Profit: {opp.get('net_profit_percentage', 0):.3f}%")
                else:
                    print("📈 No recent stablecoin opportunities found")
        
        # Get meme opportunities to see price ranges
        async with session.get(f"{API_BASE}/meme/opportunities?limit=1") as response:
            if response.status == 200:
                meme_opportunities = await response.json()
                if meme_opportunities:
                    opp = meme_opportunities[0]
                    print(f"🎯 Current Meme Opportunity:")
                    print(f"  - Type: {opp.get('type')}")
                    print(f"  - Path: {opp.get('path', opp.get('pair', 'N/A'))}")
                    print(f"  - Net Profit: {opp.get('net_profit_bps', 0):.1f} bps")
                    
                    # Check if profit calculation seems reasonable
                    profit_bps = opp.get('net_profit_bps', 0)
                    if profit_bps > 1000000:  # More than 10,000%
                        print(f"  ⚠️  WARNING: Profit calculation seems unrealistic: {profit_bps:.1f} bps")
                else:
                    print("🎯 No meme opportunities found")

async def test_system_health():
    """Test overall system health"""
    print("\n🏥 System Health Check...")
    
    async with aiohttp.ClientSession() as session:
        # Check stats endpoints
        async with session.get(f"{API_BASE}/stats") as response:
            if response.status == 200:
                stats = await response.json()
                print(f"📊 Stablecoin System:")
                print(f"  - Capital: ${stats.get('current_capital', 0):.2f}")
                print(f"  - Can Trade: {stats.get('can_trade', False)}")
                print(f"  - Total Opportunities: {stats.get('total_opportunities', 0)}")
                print(f"  - Executed Trades: {stats.get('executed_trades', 0)}")
        
        async with session.get(f"{API_BASE}/meme/stats") as response:
            if response.status == 200:
                meme_stats = await response.json()
                print(f"🎯 Meme System:")
                print(f"  - Pool Balance: ${meme_stats.get('pool_balance', 0):.2f}")
                print(f"  - Active Opportunities: {meme_stats.get('active_opportunities', 0)}")
                print(f"  - Total Trades: {meme_stats.get('total_trades', 0)}")
                print(f"  - Tokens Tracked: {meme_stats.get('tokens_tracked', 0)}")

async def main():
    """Main test function"""
    print("🚀 Detailed Backend Analysis for Solana MEV Arbitrage Bot")
    print("=" * 70)
    
    # Test system health first
    await test_system_health()
    
    # Analyze current price data
    await analyze_price_data()
    
    # Monitor for new opportunities
    results = await monitor_system_for_opportunities()
    
    print("\n" + "=" * 70)
    print("📋 ANALYSIS SUMMARY:")
    
    # Determine if systems are working
    stablecoin_working = results['stablecoin_opportunities'] > 0 or results['stablecoin_trades'] > 0
    meme_working = results['meme_opportunities'] > 0
    meme_execution_working = results['meme_trades'] > 0
    
    print(f"✅ Stablecoin System: {'WORKING' if stablecoin_working else 'NOT GENERATING NEW OPPORTUNITIES'}")
    print(f"✅ Meme Opportunity Detection: {'WORKING' if meme_working else 'NOT WORKING'}")
    print(f"{'✅' if meme_execution_working else '❌'} Meme Auto-Execution: {'WORKING' if meme_execution_working else 'NOT WORKING'}")
    
    if not stablecoin_working:
        print("\n⚠️  STABLECOIN ISSUE: No new opportunities generated during monitoring period")
        print("   - This could be due to:")
        print("   - Market conditions not meeting profit thresholds")
        print("   - Risk manager preventing trades")
        print("   - Price spreads too small after costs")
    
    if not meme_execution_working:
        print("\n❌ MEME EXECUTION ISSUE: Opportunities detected but no trades executed")
        print("   - This indicates a problem with meme auto-execution logic")
        print("   - Risk manager may be rejecting all meme trades")
        print("   - Profit calculations may be incorrect")

if __name__ == "__main__":
    asyncio.run(main())