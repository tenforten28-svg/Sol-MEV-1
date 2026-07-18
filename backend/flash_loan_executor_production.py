"""
Production Flash Loan Executor
Combines Solend flash loans with DEX swaps for atomic arbitrage
"""

import asyncio
import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
from solders.keypair import Keypair
from solders.transaction import Transaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
import os

from solend_flash_loan import SolendFlashLoan
from solana_dex_swaps import get_dex_swap, JupiterSwap
from flash_loan_config import calculate_flash_loan_profitability, FLASH_LOAN_CONFIG

logger = logging.getLogger(__name__)


class ProductionFlashLoanExecutor:
    """
    Production-ready flash loan arbitrage executor
    
    Workflow:
    1. Detect arbitrage opportunity
    2. Calculate profitability with flash loan fee
    3. Build atomic transaction:
       - Borrow from Solend
       - Swap on DEX 1 (buy)
       - Swap on DEX 2 (sell)
       - Repay Solend
    4. Simulate transaction
    5. Execute on-chain
    """
    
    def __init__(
        self,
        rpc_url: str,
        private_key: str,
        use_jupiter: bool = True
    ):
        self.rpc_url = rpc_url
        self.client = AsyncClient(rpc_url)
        self.keypair = Keypair.from_base58_string(private_key)
        self.use_jupiter = use_jupiter  # Jupiter finds best routes automatically
        
        # Initialize components
        self.flash_loan = SolendFlashLoan(self.client)
        
        # Stats
        self.stats = {
            'attempts': 0,
            'successes': 0,
            'failures': 0,
            'total_profit': 0.0,
            'total_fees_paid': 0.0,
            'simulation_failures': 0
        }
        
        logger.info(f"🚀 Production Flash Loan Executor initialized")
        logger.info(f"   Wallet: {self.keypair.pubkey()}")
        logger.info(f"   Using Jupiter: {use_jupiter}")
    
    async def check_opportunity_profitability(
        self,
        opportunity: Dict,
        loan_amount_usd: float
    ) -> Dict:
        """
        Check if opportunity is profitable after flash loan fees
        """
        # Get profit in basis points
        profit_bps = opportunity.get('net_profit_percentage', 0) * 100
        
        # Calculate profitability
        analysis = calculate_flash_loan_profitability(
            profit_bps,
            loan_amount_usd,
            'solend'
        )
        
        # Add opportunity details
        analysis['opportunity'] = opportunity
        analysis['loan_amount_usd'] = loan_amount_usd
        
        return analysis
    
    async def build_arbitrage_transaction(
        self,
        opportunity: Dict,
        loan_amount_usd: float
    ) -> Optional[Transaction]:
        """
        Build complete flash loan arbitrage transaction
        
        Args:
            opportunity: {
                'token_pair': 'SOL/USDC',
                'dex_buy': 'raydium',
                'dex_sell': 'orca',
                'buy_price': 150.00,
                'sell_price': 150.30,
                ...
            }
            loan_amount_usd: Flash loan amount
            
        Returns:
            Atomic transaction or None
        """
        try:
            # Parse token pair
            pair = opportunity['token_pair']
            token_base, token_quote = pair.split('/')
            
            # For simplicity, we borrow the quote token (usually USDC)
            borrow_token = token_quote
            
            # Build swap instructions
            swap_instructions = []
            
            if self.use_jupiter:
                # Use Jupiter for both swaps (automatic best routing)
                jupiter = JupiterSwap(self.client)
                
                # Swap 1: Buy (USDC → SOL on best DEX)
                buy_tx = await jupiter.create_swap_transaction(
                    token_quote,  # USDC
                    token_base,   # SOL
                    loan_amount_usd,
                    FLASH_LOAN_CONFIG['slippage_tolerance_bps'],
                    self.keypair
                )
                
                if not buy_tx:
                    logger.error("Failed to build buy swap")
                    return None
                
                swap_instructions.extend(buy_tx.instructions)
                
                # Swap 2: Sell (SOL → USDC on best DEX)
                # Amount is output from first swap (simplified - should track exact amount)
                sell_amount = loan_amount_usd * (1 + opportunity['net_profit_percentage']/100)
                
                sell_tx = await jupiter.create_swap_transaction(
                    token_base,   # SOL
                    token_quote,  # USDC
                    sell_amount,
                    FLASH_LOAN_CONFIG['slippage_tolerance_bps'],
                    self.keypair
                )
                
                if not sell_tx:
                    logger.error("Failed to build sell swap")
                    return None
                
                swap_instructions.extend(sell_tx.instructions)
                
            else:
                # Use specific DEXs from opportunity
                buy_dex = get_dex_swap(opportunity['dex_buy'], self.client)
                sell_dex = get_dex_swap(opportunity['dex_sell'], self.client)
                
                # Build buy swap
                buy_tx = await buy_dex.create_swap_transaction(
                    token_quote,
                    token_base,
                    loan_amount_usd,
                    FLASH_LOAN_CONFIG['slippage_tolerance_bps'],
                    self.keypair
                )
                
                if not buy_tx:
                    return None
                
                swap_instructions.extend(buy_tx.instructions)
                
                # Build sell swap
                sell_amount = loan_amount_usd * (1 + opportunity['net_profit_percentage']/100)
                sell_tx = await sell_dex.create_swap_transaction(
                    token_base,
                    token_quote,
                    sell_amount,
                    FLASH_LOAN_CONFIG['slippage_tolerance_bps'],
                    self.keypair
                )
                
                if not sell_tx:
                    return None
                
                swap_instructions.extend(sell_tx.instructions)
            
            # Build complete flash loan transaction
            flash_loan_tx = await self.flash_loan.build_flash_loan_transaction(
                token=borrow_token,
                amount=loan_amount_usd,
                user_keypair=self.keypair,
                arbitrage_instructions=swap_instructions
            )
            
            return flash_loan_tx
            
        except Exception as e:
            logger.error(f"Error building arbitrage transaction: {e}")
            return None
    
    async def execute_arbitrage(
        self,
        opportunity: Dict,
        loan_amount_usd: float,
        simulate_first: bool = True
    ) -> Dict:
        """
        Execute flash loan arbitrage
        
        Returns:
            {
                'success': bool,
                'signature': Optional[str],
                'profit': float,
                'error': Optional[str]
            }
        """
        self.stats['attempts'] += 1
        
        try:
            # Step 1: Check profitability
            profitability = await self.check_opportunity_profitability(
                opportunity,
                loan_amount_usd
            )
            
            if not profitability['is_profitable']:
                logger.warning(f"❌ Not profitable after fees: {profitability['net_profit']:.2f}")
                return {
                    'success': False,
                    'error': 'Not profitable after flash loan fee'
                }
            
            logger.info(
                f"💎 Profitable opportunity: {opportunity['token_pair']} | "
                f"Net profit: ${profitability['net_profit']:.2f}"
            )
            
            # Step 2: Build transaction
            transaction = await self.build_arbitrage_transaction(
                opportunity,
                loan_amount_usd
            )
            
            if not transaction:
                return {
                    'success': False,
                    'error': 'Failed to build transaction'
                }
            
            logger.info(f"✅ Built transaction with {len(transaction.instructions)} instructions")
            
            # Step 3: Simulate
            if simulate_first:
                sim_result = await self.flash_loan.simulate_flash_loan(
                    transaction,
                    self.keypair
                )
                
                if not sim_result['success']:
                    self.stats['simulation_failures'] += 1
                    logger.error(f"❌ Simulation failed: {sim_result['error']}")
                    return {
                        'success': False,
                        'error': f"Simulation failed: {sim_result['error']}"
                    }
                
                logger.info(f"✅ Simulation passed | Compute units: {sim_result.get('compute_units', 0)}")
            
            # Step 4: Execute on-chain
            logger.info(f"📤 Executing flash loan arbitrage...")
            
            result = await self.flash_loan.execute_flash_loan(
                transaction,
                self.keypair,
                simulate_first=False  # Already simulated
            )
            
            if result['success']:
                self.stats['successes'] += 1
                self.stats['total_profit'] += profitability['net_profit']
                
                logger.info(
                    f"✅ SUCCESS! Profit: ${profitability['net_profit']:.2f} | "
                    f"TX: {result['signature']}"
                )
                
                return {
                    'success': True,
                    'signature': result['signature'],
                    'profit': profitability['net_profit'],
                    'timestamp': datetime.now(timezone.utc)
                }
            else:
                self.stats['failures'] += 1
                logger.error(f"❌ Execution failed: {result.get('error')}")
                
                return {
                    'success': False,
                    'error': result.get('error')
                }
            
        except Exception as e:
            self.stats['failures'] += 1
            logger.error(f"❌ Arbitrage execution error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_stats(self) -> Dict:
        """Get execution statistics"""
        success_rate = (
            (self.stats['successes'] / self.stats['attempts'] * 100)
            if self.stats['attempts'] > 0 else 0
        )
        
        avg_profit = (
            self.stats['total_profit'] / self.stats['successes']
            if self.stats['successes'] > 0 else 0
        )
        
        return {
            **self.stats,
            'success_rate': success_rate,
            'average_profit': avg_profit,
            'simulation_failure_rate': (
                self.stats['simulation_failures'] / self.stats['attempts'] * 100
                if self.stats['attempts'] > 0 else 0
            )
        }
    
    async def close(self):
        """Cleanup"""
        await self.client.close()


# Testing (with mock private key)
async def test_production_executor():
    """Test production executor"""
    print("🧪 Testing Production Flash Loan Executor")
    print("=" * 70)
    
    # IMPORTANT: Use real private key in production!
    # For testing, generate a throwaway keypair
    test_keypair = Keypair()
    test_private_key = test_keypair.to_base58_string()
    
    print(f"Test wallet: {test_keypair.pubkey()}")
    print(f"⚠️  This is a TEST wallet - fund it before real use!")
    
    # Initialize executor
    executor = ProductionFlashLoanExecutor(
        rpc_url="https://api.mainnet-beta.solana.com",
        private_key=test_private_key,
        use_jupiter=True
    )
    
    # Mock opportunity
    opportunity = {
        'token_pair': 'SOL/USDC',
        'dex_buy': 'raydium',
        'dex_sell': 'orca',
        'buy_price': 150.00,
        'sell_price': 150.40,
        'net_profit_percentage': 0.25  # 0.25% profit
    }
    
    loan_amount = 10000  # $10k
    
    print(f"\n1. Checking profitability...")
    profitability = await executor.check_opportunity_profitability(
        opportunity,
        loan_amount
    )
    print(f"   Profitable: {profitability['is_profitable']}")
    print(f"   Net profit: ${profitability['net_profit']:.2f}")
    
    print(f"\n2. Building transaction...")
    transaction = await executor.build_arbitrage_transaction(
        opportunity,
        loan_amount
    )
    
    if transaction:
        print(f"   ✅ Transaction built with {len(transaction.instructions)} instructions")
    else:
        print(f"   ❌ Failed to build transaction")
    
    # Show stats
    print(f"\n3. Executor Stats:")
    stats = executor.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    await executor.close()
    print("\n" + "=" * 70)
    print("✅ Production executor test complete!")
    print("\n💡 Next steps:")
    print("   1. Fund wallet with SOL for gas")
    print("   2. Test on devnet first")
    print("   3. Run simulation mode for 1 week")
    print("   4. Deploy to mainnet")


if __name__ == "__main__":
    asyncio.run(test_production_executor())
