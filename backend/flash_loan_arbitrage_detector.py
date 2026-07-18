"""
Flash Loan Arbitrage Detector
Integrates flash loans with existing arbitrage detection
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

from dex_connectors import DEXAggregator
from flash_loan_executor import FlashLoanExecutor
from flash_loan_config import FLASH_LOAN_CONFIG, calculate_flash_loan_profitability

logger = logging.getLogger(__name__)


class FlashLoanArbitrageDetector:
    """
    Detects and executes arbitrage opportunities using flash loans
    No capital needed - borrow, trade, repay in one transaction
    """
    
    def __init__(
        self,
        rpc_url: str,
        private_key: Optional[str] = None,
        auto_execute: bool = False
    ):
        self.dex_aggregator = DEXAggregator()
        self.flash_loan_executor = FlashLoanExecutor(rpc_url, private_key)
        self.auto_execute = auto_execute
        
        # Performance tracking
        self.opportunities_found = 0
        self.opportunities_executed = 0
        self.total_profit = 0.0
        
        logger.info(f"🚀 Flash Loan Arbitrage Detector initialized")
        logger.info(f"   Auto-execute: {auto_execute}")
        logger.info(f"   Min profit: {FLASH_LOAN_CONFIG['min_profit_bps']} bps")
    
    async def scan_for_opportunities(
        self,
        pairs: List[str],
        loan_sizes: List[float] = [5000, 10000, 25000]
    ) -> List[Dict]:
        """
        Scan trading pairs for flash loan arbitrage opportunities
        
        Args:
            pairs: List of token pairs to scan
            loan_sizes: Different loan sizes to test
            
        Returns:
            List of profitable opportunities
        """
        opportunities = []
        
        for pair in pairs:
            try:
                # Get prices from all DEXs
                prices = await self.dex_aggregator.get_all_prices(pair)
                
                if len(prices) < 2:
                    continue
                
                # Test each loan size
                for loan_size in loan_sizes:
                    # Find arbitrage with flash loan consideration
                    opportunity = self._find_flash_loan_arbitrage(
                        prices,
                        loan_size,
                        pair
                    )
                    
                    if opportunity and opportunity['is_profitable']:
                        opportunities.append(opportunity)
                        self.opportunities_found += 1
                        
                        logger.info(
                            f"💎 Flash loan opportunity: {pair} | "
                            f"Loan: ${loan_size:,.0f} | "
                            f"Net profit: ${opportunity['net_profit']:.2f}"
                        )
                
            except Exception as e:
                logger.error(f"Error scanning {pair}: {e}")
                continue
        
        return opportunities
    
    def _find_flash_loan_arbitrage(
        self,
        prices: Dict[str, Dict],
        loan_amount_usd: float,
        pair: str
    ) -> Optional[Dict]:
        """
        Find arbitrage opportunity and calculate profitability with flash loan
        
        Args:
            prices: DEX prices
            loan_amount_usd: Flash loan amount
            pair: Token pair
            
        Returns:
            Opportunity dict or None
        """
        # Find basic arbitrage (without flash loan fee)
        base_opportunity = self.dex_aggregator.find_arbitrage_opportunity(
            prices=prices,
            max_trade_amount=loan_amount_usd,
            min_spread=0.0001,  # Very low threshold - we'll check flash loan fee separately
            max_slippage=FLASH_LOAN_CONFIG['slippage_tolerance_bps'] / 10000
        )
        
        if not base_opportunity:
            return None
        
        # Calculate profitability with flash loan fee
        profit_bps = base_opportunity['net_profit_percentage'] * 100
        profitability = calculate_flash_loan_profitability(
            profit_bps,
            loan_amount_usd,
            self.flash_loan_executor.provider
        )
        
        # Check minimum profit threshold
        min_profit_bps = FLASH_LOAN_CONFIG['min_profit_bps']
        
        if profitability['net_profit'] <= 0 or profit_bps < min_profit_bps:
            return None
        
        # Build opportunity dict
        opportunity = {
            **base_opportunity,
            'flash_loan': True,
            'loan_amount_usd': loan_amount_usd,
            'flash_loan_fee': profitability['flash_loan_fee'],
            'gross_profit': profitability['gross_profit'],
            'net_profit': profitability['net_profit'],
            'profit_after_flash_loan_bps': (
                profitability['net_profit'] / loan_amount_usd * 10000
            ),
            'is_profitable': profitability['is_profitable'],
            'timestamp': datetime.now(timezone.utc)
        }
        
        return opportunity
    
    async def execute_opportunity(
        self,
        opportunity: Dict,
        simulate_first: bool = True
    ) -> Dict:
        """
        Execute flash loan arbitrage opportunity
        
        Args:
            opportunity: Opportunity from scan
            simulate_first: Simulate before executing
            
        Returns:
            Execution result
        """
        logger.info(f"⚡ Executing flash loan arbitrage...")
        
        result = await self.flash_loan_executor.execute_flash_loan_arbitrage(
            opportunity,
            opportunity['loan_amount_usd'],
            simulate_first=simulate_first
        )
        
        if result['success']:
            self.opportunities_executed += 1
            self.total_profit += result['profit']
            
            logger.info(
                f"✅ Success! Profit: ${result['profit']:.2f} | "
                f"Total profit: ${self.total_profit:.2f}"
            )
        else:
            logger.warning(f"❌ Execution failed: {result.get('error')}")
        
        return result
    
    async def monitor_and_execute(
        self,
        pairs: List[str],
        scan_interval: int = 3,
        loan_sizes: List[float] = [10000, 25000]
    ):
        """
        Continuously monitor for opportunities and auto-execute
        
        Args:
            pairs: Trading pairs to monitor
            scan_interval: Seconds between scans
            loan_sizes: Flash loan sizes to test
        """
        logger.info(f"👀 Starting continuous monitoring...")
        logger.info(f"   Pairs: {pairs}")
        logger.info(f"   Scan interval: {scan_interval}s")
        logger.info(f"   Loan sizes: {loan_sizes}")
        
        while True:
            try:
                # Scan for opportunities
                opportunities = await self.scan_for_opportunities(
                    pairs,
                    loan_sizes
                )
                
                if opportunities and self.auto_execute:
                    # Execute best opportunity
                    best_opp = max(opportunities, key=lambda x: x['net_profit'])
                    
                    logger.info(
                        f"🎯 Best opportunity: {best_opp['token_pair']} | "
                        f"Net: ${best_opp['net_profit']:.2f}"
                    )
                    
                    await self.execute_opportunity(best_opp)
                
                # Wait before next scan
                await asyncio.sleep(scan_interval)
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(scan_interval)
    
    def get_stats(self) -> Dict:
        """Get detector statistics"""
        executor_stats = self.flash_loan_executor.get_stats()
        
        return {
            'opportunities_found': self.opportunities_found,
            'opportunities_executed': self.opportunities_executed,
            'execution_rate': (
                self.opportunities_executed / self.opportunities_found * 100
                if self.opportunities_found > 0 else 0
            ),
            'total_profit': self.total_profit,
            'executor_stats': executor_stats
        }
    
    async def close(self):
        """Cleanup resources"""
        await self.dex_aggregator.close()
        await self.flash_loan_executor.close()


# Testing
async def test_flash_loan_detector():
    """Test flash loan arbitrage detector"""
    print("🧪 Testing Flash Loan Arbitrage Detector")
    print("=" * 70)
    
    # Initialize detector
    detector = FlashLoanArbitrageDetector(
        rpc_url="https://api.devnet.solana.com",
        auto_execute=False  # Manual for testing
    )
    
    # Test pairs
    pairs = ['SOL/USDC', 'RAY/USDC', 'ORCA/USDC']
    loan_sizes = [5000, 10000]
    
    print(f"\n1. Scanning for opportunities...")
    print(f"   Pairs: {pairs}")
    print(f"   Loan sizes: ${', '.join([f'{s:,.0f}' for s in loan_sizes])}")
    
    opportunities = await detector.scan_for_opportunities(pairs, loan_sizes)
    
    print(f"\n✅ Found {len(opportunities)} flash loan opportunities")
    
    if opportunities:
        print(f"\nTop 3 opportunities:")
        for i, opp in enumerate(sorted(opportunities, key=lambda x: x['net_profit'], reverse=True)[:3], 1):
            print(f"\n{i}. {opp['token_pair']}")
            print(f"   Loan: ${opp['loan_amount_usd']:,.0f}")
            print(f"   Buy on {opp['dex_buy'].upper()} @ ${opp['buy_price']:.4f}")
            print(f"   Sell on {opp['dex_sell'].upper()} @ ${opp['sell_price']:.4f}")
            print(f"   Gross profit: ${opp['gross_profit']:.2f}")
            print(f"   Flash loan fee: ${opp['flash_loan_fee']:.2f}")
            print(f"   Net profit: ${opp['net_profit']:.2f}")
            print(f"   ROI: {opp['profit_after_flash_loan_bps']:.1f} bps")
        
        # Test execution on best opportunity
        print(f"\n2. Testing execution simulation...")
        best = opportunities[0]
        result = await detector.execute_opportunity(best, simulate_first=True)
        
        if result['success']:
            print(f"   ✅ Would profit: ${result['profit']:.2f}")
        else:
            print(f"   ❌ Would fail: {result.get('error')}")
    
    # Show stats
    print(f"\n3. Detector Statistics:")
    stats = detector.get_stats()
    print(f"   Opportunities found: {stats['opportunities_found']}")
    print(f"   Opportunities executed: {stats['opportunities_executed']}")
    print(f"   Total profit: ${stats['total_profit']:.2f}")
    
    await detector.close()
    print("\n" + "=" * 70)
    print("✅ Test complete!")


if __name__ == "__main__":
    asyncio.run(test_flash_loan_detector())
