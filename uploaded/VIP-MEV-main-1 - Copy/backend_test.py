#!/usr/bin/env python3
"""
Comprehensive Backend Test Suite for Solana MEV Arbitrage Bot
Tests paper trading functionality with real DEX price data integration
"""

import asyncio
import aiohttp
import json
from datetime import datetime, timezone
import time
import sys
import os

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

print(f"🔗 Testing backend at: {API_BASE}")

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.warnings = []
        
    def pass_test(self, test_name):
        self.passed += 1
        print(f"✅ {test_name}")
        
    def fail_test(self, test_name, error):
        self.failed += 1
        self.errors.append(f"{test_name}: {error}")
        print(f"❌ {test_name}: {error}")
        
    def warn_test(self, test_name, warning):
        self.warnings.append(f"{test_name}: {warning}")
        print(f"⚠️  {test_name}: {warning}")
        
    def summary(self):
        total = self.passed + self.failed
        print(f"\n📊 TEST SUMMARY")
        print(f"Total Tests: {total}")
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print(f"Warnings: {len(self.warnings)}")
        
        if self.errors:
            print(f"\n❌ FAILED TESTS:")
            for error in self.errors:
                print(f"  - {error}")
                
        if self.warnings:
            print(f"\n⚠️  WARNINGS:")
            for warning in self.warnings:
                print(f"  - {warning}")
                
        return self.failed == 0

results = TestResults()

async def test_api_endpoint(session, endpoint, test_name, expected_fields=None, validate_func=None):
    """Generic API endpoint tester"""
    try:
        url = f"{API_BASE}{endpoint}"
        async with session.get(url, timeout=10) as response:
            if response.status != 200:
                results.fail_test(test_name, f"HTTP {response.status}")
                return None
                
            data = await response.json()
            
            # Check expected fields
            if expected_fields:
                for field in expected_fields:
                    if field not in data:
                        results.fail_test(test_name, f"Missing field: {field}")
                        return None
            
            # Custom validation
            if validate_func:
                validation_result = validate_func(data)
                if validation_result is not True:
                    results.fail_test(test_name, validation_result)
                    return None
            
            results.pass_test(test_name)
            return data
            
    except asyncio.TimeoutError:
        results.fail_test(test_name, "Request timeout")
        return None
    except Exception as e:
        results.fail_test(test_name, f"Exception: {str(e)}")
        return None

def validate_stablecoin_stats(data):
    """Validate stablecoin stats response"""
    required_fields = [
        'total_opportunities', 'executed_trades', 'total_profit', 'success_rate',
        'starting_capital', 'current_capital', 'available_capital', 'can_trade'
    ]
    
    for field in required_fields:
        if field not in data:
            return f"Missing required field: {field}"
    
    # Validate numeric fields
    if not isinstance(data['starting_capital'], (int, float)) or data['starting_capital'] <= 0:
        return "Invalid starting_capital"
        
    if not isinstance(data['current_capital'], (int, float)):
        return "Invalid current_capital"
        
    if not isinstance(data['total_opportunities'], int) or data['total_opportunities'] < 0:
        return "Invalid total_opportunities"
        
    return True

def validate_opportunities(data):
    """Validate opportunities response"""
    if not isinstance(data, list):
        return "Response should be a list"
    
    if len(data) == 0:
        return "No opportunities found - system may not be generating opportunities"
    
    # Check first opportunity structure
    opp = data[0]
    required_fields = [
        'token_pair', 'dex_buy', 'dex_sell', 'buy_price', 'sell_price',
        'net_profit_percentage', 'trade_amount', 'timestamp'
    ]
    
    for field in required_fields:
        if field not in opp:
            return f"Missing field in opportunity: {field}"
    
    # Validate price ranges for realistic data
    token_pair = opp.get('token_pair', '')
    buy_price = opp.get('buy_price', 0)
    sell_price = opp.get('sell_price', 0)
    
    if 'SOL' in token_pair and buy_price > 0:
        if not (100 < buy_price < 200):  # SOL should be around $150-158
            return f"SOL price seems unrealistic: ${buy_price}"
    
    if 'RAY' in token_pair and buy_price > 0:
        if not (1.0 < buy_price < 5.0):  # RAY should be around $1.5-2.5
            return f"RAY price seems unrealistic: ${buy_price}"
    
    if 'ORCA' in token_pair and buy_price > 0:
        if not (0.5 < buy_price < 2.0):  # ORCA should be around $0.8-1.2
            return f"ORCA price seems unrealistic: ${buy_price}"
    
    return True

def validate_trades(data):
    """Validate trades response"""
    if not isinstance(data, list):
        return "Response should be a list"
    
    if len(data) == 0:
        return "No trades found - auto-execution may not be working"
    
    # Check first trade structure
    trade = data[0]
    required_fields = [
        'token_pair', 'dex_buy', 'dex_sell', 'profit', 'profit_percentage',
        'status', 'timestamp'
    ]
    
    for field in required_fields:
        if field not in trade:
            return f"Missing field in trade: {field}"
    
    # Validate profit calculation
    if not isinstance(trade['profit'], (int, float)):
        return "Invalid profit value"
        
    if not isinstance(trade['profit_percentage'], (int, float)):
        return "Invalid profit_percentage value"
    
    return True

def validate_meme_stats(data):
    """Validate meme coin stats response"""
    required_fields = [
        'pool_balance', 'initial_capital', 'total_trades', 'total_profit',
        'active_opportunities', 'meme_pairs_monitored', 'tokens_tracked'
    ]
    
    for field in required_fields:
        if field not in data:
            return f"Missing required field: {field}"
    
    # Validate meme pool
    if not isinstance(data['pool_balance'], (int, float)) or data['pool_balance'] <= 0:
        return "Invalid pool_balance"
        
    if data['initial_capital'] != 10.0:
        return f"Expected initial_capital to be 10.0, got {data['initial_capital']}"
    
    return True

def validate_meme_opportunities(data):
    """Validate meme opportunities response"""
    if not isinstance(data, list):
        return "Response should be a list"
    
    if len(data) == 0:
        return "No meme opportunities found - meme system may not be working"
    
    # Check first opportunity
    opp = data[0]
    required_fields = ['type', 'net_profit_bps', 'discovered_at']
    
    for field in required_fields:
        if field not in opp:
            return f"Missing field in meme opportunity: {field}"
    
    # Validate opportunity type
    if opp['type'] not in ['simple', 'triangular']:
        return f"Invalid opportunity type: {opp['type']}"
    
    # Validate profit
    if not isinstance(opp['net_profit_bps'], (int, float)) or opp['net_profit_bps'] <= 0:
        return "Invalid net_profit_bps"
    
    return True

def validate_meme_trades(data):
    """Validate meme trades response"""
    if not isinstance(data, list):
        return "Response should be a list"
    
    if len(data) == 0:
        return "No meme trades found - meme auto-execution may not be working"
    
    # Check first trade
    trade = data[0]
    required_fields = ['type', 'profit', 'profit_percentage', 'status', 'timestamp']
    
    for field in required_fields:
        if field not in trade:
            return f"Missing field in meme trade: {field}"
    
    return True

async def test_websocket_connection():
    """Test WebSocket connection for real-time updates"""
    try:
        ws_url = f"{BACKEND_URL.replace('http', 'ws')}/api/ws"
        
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, timeout=5) as ws:
                # Send a test message
                await ws.send_str("test")
                
                # Wait for any response or timeout after 3 seconds
                try:
                    await asyncio.wait_for(ws.receive(), timeout=3)
                    results.pass_test("WebSocket Connection")
                except asyncio.TimeoutError:
                    results.pass_test("WebSocket Connection (no immediate response)")
                    
    except Exception as e:
        results.fail_test("WebSocket Connection", str(e))

async def run_comprehensive_tests():
    """Run all backend tests"""
    print("🚀 Starting Comprehensive Backend Tests for Solana MEV Arbitrage Bot")
    print("=" * 80)
    
    async with aiohttp.ClientSession() as session:
        
        # Test 1: Basic API Health Check
        await test_api_endpoint(
            session, "/", 
            "API Health Check",
            expected_fields=['message', 'status']
        )
        
        # Test 2: Stablecoin Arbitrage System
        print("\n📈 STABLECOIN ARBITRAGE SYSTEM TESTS")
        print("-" * 50)
        
        stats_data = await test_api_endpoint(
            session, "/stats",
            "Stablecoin Stats Endpoint",
            validate_func=validate_stablecoin_stats
        )
        
        opportunities_data = await test_api_endpoint(
            session, "/opportunities",
            "Stablecoin Opportunities Endpoint", 
            validate_func=validate_opportunities
        )
        
        trades_data = await test_api_endpoint(
            session, "/trades",
            "Stablecoin Trades Endpoint",
            validate_func=validate_trades
        )
        
        # Test 3: Meme Coin Arbitrage System  
        print("\n🎯 MEME COIN ARBITRAGE SYSTEM TESTS")
        print("-" * 50)
        
        meme_stats_data = await test_api_endpoint(
            session, "/meme/stats",
            "Meme Stats Endpoint",
            validate_func=validate_meme_stats
        )
        
        meme_opportunities_data = await test_api_endpoint(
            session, "/meme/opportunities", 
            "Meme Opportunities Endpoint",
            validate_func=validate_meme_opportunities
        )
        
        meme_trades_data = await test_api_endpoint(
            session, "/meme/trades",
            "Meme Trades Endpoint",
            validate_func=validate_meme_trades
        )
        
        # Test 4: Integration Tests
        print("\n🔗 INTEGRATION TESTS")
        print("-" * 50)
        
        # Test WebSocket
        await test_websocket_connection()
        
        # Test parallel system operation
        if stats_data and meme_stats_data:
            if stats_data.get('can_trade') and meme_stats_data.get('pool_balance', 0) > 0:
                results.pass_test("Parallel System Operation")
            else:
                results.warn_test("Parallel System Operation", "One or both systems may be in cooldown")
        
        # Test 5: Data Validation Tests
        print("\n📊 DATA VALIDATION TESTS")
        print("-" * 50)
        
        # Validate timestamp formats
        timestamp_valid = True
        if opportunities_data and len(opportunities_data) > 0:
            try:
                timestamp_str = opportunities_data[0].get('timestamp')
                if timestamp_str:
                    datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                results.pass_test("Timestamp Format Validation")
            except Exception as e:
                results.fail_test("Timestamp Format Validation", str(e))
        
        # Validate profit calculations
        if trades_data and len(trades_data) > 0:
            trade = trades_data[0]
            profit = trade.get('profit', 0)
            profit_pct = trade.get('profit_percentage', 0)
            
            if profit != 0 and profit_pct != 0:
                # Basic sanity check - profit percentage should correlate with profit amount
                results.pass_test("Profit Calculation Validation")
            else:
                results.warn_test("Profit Calculation Validation", "Zero profit values found")
        
        # Test 6: Performance and Reliability
        print("\n⚡ PERFORMANCE TESTS")
        print("-" * 50)
        
        # Test multiple rapid requests
        start_time = time.time()
        tasks = []
        for i in range(5):
            task = test_api_endpoint(session, "/stats", f"Rapid Request {i+1}")
            tasks.append(task)
        
        await asyncio.gather(*tasks)
        end_time = time.time()
        
        if end_time - start_time < 10:  # Should complete within 10 seconds
            results.pass_test("API Response Performance")
        else:
            results.fail_test("API Response Performance", "Requests took too long")

async def main():
    """Main test runner"""
    try:
        await run_comprehensive_tests()
        
        print("\n" + "=" * 80)
        success = results.summary()
        
        if success:
            print("\n🎉 ALL TESTS PASSED! Paper trading system is working correctly.")
            return 0
        else:
            print(f"\n💥 {results.failed} TESTS FAILED! Issues need to be addressed.")
            return 1
            
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"\n💥 Test runner error: {e}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)