"""
Flash Loan Executor for Solana MEV Bot
Handles atomic flash loan arbitrage transactions
"""

import asyncio
import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.instruction import Instruction, AccountMeta
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
import base58
import os

from flash_loan_config import (
    FLASH_LOAN_PROVIDERS,
    DEFAULT_PROVIDER,
    FLASH_LOAN_CONFIG,
    calculate_flash_loan_profitability
)

logger = logging.getLogger(__name__)


class FlashLoanExecutor:
    """
    Executes flash loan arbitrage on Solana
    
    Flash loan flow:
    1. Borrow assets from Solend/Mango
    2. Execute arbitrage (buy low, sell high)
    3. Repay loan + fee
    All in ONE atomic transaction
    """
    
    def __init__(
        self,
        rpc_url: str,
        private_key: Optional[str] = None,
        provider: str = DEFAULT_PROVIDER
    ):
        self.rpc_url = rpc_url
        self.client = AsyncClient(rpc_url)
        self.provider = provider
        self.provider_config = FLASH_LOAN_PROVIDERS[provider]
        
        # Load or create keypair
        if private_key:
            self.keypair = Keypair.from_base58_string(private_key)
        else:
            # For testing - in production, use secure key management
            self.keypair = Keypair()
            logger.warning("⚠️  Using generated keypair - fund this address for gas!")
            logger.info(f"Wallet address: {self.keypair.pubkey()}")
        
        self.stats = {
            'attempts': 0,
            'successes': 0,
            'failures': 0,
            'total_profit': 0.0,
            'total_fees_paid': 0.0
        }
    
    async def check_opportunity_profitability(
        self,
        opportunity: Dict,
        loan_amount_usd: float
    ) -> Dict:
        """
        Check if opportunity is profitable with flash loan
        
        Args:
            opportunity: Arbitrage opportunity from detector
            loan_amount_usd: Amount to borrow
            
        Returns:
            Profitability analysis dict
        """
        # Get profit in basis points
        profit_bps = opportunity.get('net_profit_percentage', 0) * 100
        
        # Calculate profitability
        analysis = calculate_flash_loan_profitability(
            profit_bps,
            loan_amount_usd,
            self.provider
        )
        
        # Add opportunity details
        analysis['opportunity'] = opportunity
        analysis['loan_amount_usd'] = loan_amount_usd
        
        return analysis
    
    async def simulate_flash_loan_arbitrage(
        self,
        opportunity: Dict,
        loan_amount_usd: float
    ) -> Dict:
        """
        Simulate flash loan transaction before executing
        Critical for avoiding failed transactions
        
        Returns:
            {
                'success': bool,
                'expected_profit': float,
                'gas_cost': float,
                'error': Optional[str]
            }
        """
        try:
            # Check profitability first
            profitability = await self.check_opportunity_profitability(
                opportunity, loan_amount_usd
            )
            
            if not profitability['is_profitable']:
                return {
                    'success': False,
                    'expected_profit': profitability['net_profit'],
                    'gas_cost': 0.000005,  # Estimated SOL
                    'error': 'Not profitable after flash loan fee'
                }
            
            # Simulate the transaction
            # In production, this would actually simulate on-chain
            simulation_result = {
                'success': True,
                'expected_profit': profitability['net_profit'],
                'gas_cost': 0.000005,  # ~$0.0007 in gas
                'slippage': opportunity.get('total_cost_percentage', 0.5),
                'execution_time_ms': 50  # Estimated
            }
            
            logger.info(
                f"📊 Simulation: ${simulation_result['expected_profit']:.2f} profit, "
                f"${simulation_result['gas_cost'] * 150:.4f} gas"
            )
            
            return simulation_result
            
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            return {
                'success': False,
                'expected_profit': 0,
                'gas_cost': 0,
                'error': str(e)
            }
    
    async def build_flash_loan_transaction(
        self,
        opportunity: Dict,
        loan_amount_usd: float
    ) -> Optional[Transaction]:
        """
        Build atomic flash loan transaction
        
        Transaction structure:
        1. Instruction: Borrow from Solend
        2. Instruction: Swap on DEX 1 (buy)
        3. Instruction: Swap on DEX 2 (sell)
        4. Instruction: Repay Solend + fee
        
        All must succeed or entire transaction reverts
        """
        try:
            # Convert USD to token amount
            token = FLASH_LOAN_CONFIG['preferred_token']
            loan_amount = loan_amount_usd  # Assuming USDC 1:1
            
            # Get token addresses
            if token not in self.provider_config.get('reserves', {}):
                logger.error(f"Token {token} not supported by {self.provider}")
                return None
            
            reserve_address = self.provider_config['reserves'][token]
            
            # Build instruction placeholders
            # NOTE: These are simplified - production needs actual DEX instructions
            instructions = []
            
            # 1. Borrow instruction (Solend flash loan)
            borrow_ix = self._build_borrow_instruction(
                reserve_address,
                loan_amount
            )
            instructions.append(borrow_ix)
            
            # 2. Buy on DEX 1
            buy_ix = self._build_swap_instruction(
                opportunity['dex_buy'],
                opportunity['token_pair'],
                loan_amount,
                'buy'
            )
            instructions.append(buy_ix)
            
            # 3. Sell on DEX 2
            sell_ix = self._build_swap_instruction(
                opportunity['dex_sell'],
                opportunity['token_pair'],
                loan_amount,
                'sell'
            )
            instructions.append(sell_ix)
            
            # 4. Repay loan + fee
            fee_amount = loan_amount * self.provider_config['fee_percentage']
            repay_ix = self._build_repay_instruction(
                reserve_address,
                loan_amount + fee_amount
            )
            instructions.append(repay_ix)
            
            # Create transaction
            transaction = Transaction()
            for ix in instructions:
                transaction.add(ix)
            
            logger.info(f"✅ Built transaction with {len(instructions)} instructions")
            return transaction
            
        except Exception as e:
            logger.error(f"Error building transaction: {e}")
            return None
    
    def _build_borrow_instruction(
        self,
        reserve: str,
        amount: float
    ) -> Instruction:
        """Build Solend borrow instruction"""
        # Placeholder - production needs actual Solend program interaction
        program_id = Pubkey.from_string(self.provider_config['program_id'])
        
        return Instruction(
            program_id=program_id,
            accounts=[
                AccountMeta(pubkey=self.keypair.pubkey(), is_signer=True, is_writable=True),
            ],
            data=b"borrow_instruction_data"  # Simplified
        )
    
    def _build_swap_instruction(
        self,
        dex: str,
        pair: str,
        amount: float,
        side: str
    ) -> Instruction:
        """Build DEX swap instruction"""
        # Placeholder - production needs actual Raydium/Orca/Serum instructions
        # Each DEX has different program IDs and instruction formats
        
        dex_programs = {
            'raydium': '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8',
            'orca': 'DjVE6JNiYqPL2QXyCUUh8rNjHrbz9hXHNYt99MQ59qw1',
            'serum': '9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin'
        }
        
        program_id = Pubkey.from_string(dex_programs.get(dex, dex_programs['raydium']))
        
        return Instruction(
            program_id=program_id,
            accounts=[
                AccountMeta(pubkey=self.keypair.pubkey(), is_signer=True, is_writable=True),
            ],
            data=b"swap_instruction_data"  # Simplified
        )
    
    def _build_repay_instruction(
        self,
        reserve: str,
        amount: float
    ) -> Instruction:
        """Build Solend repay instruction"""
        program_id = Pubkey.from_string(self.provider_config['program_id'])
        
        return Instruction(
            program_id=program_id,
            accounts=[
                AccountMeta(pubkey=self.keypair.pubkey(), is_signer=True, is_writable=True),
            ],
            data=b"repay_instruction_data"  # Simplified
        )
    
    async def execute_flash_loan_arbitrage(
        self,
        opportunity: Dict,
        loan_amount_usd: float,
        simulate_first: bool = True
    ) -> Dict:
        """
        Execute flash loan arbitrage
        
        Args:
            opportunity: Arbitrage opportunity
            loan_amount_usd: Amount to borrow
            simulate_first: Run simulation before execution
            
        Returns:
            Execution result dict
        """
        self.stats['attempts'] += 1
        
        try:
            # Step 1: Simulate first
            if simulate_first:
                simulation = await self.simulate_flash_loan_arbitrage(
                    opportunity, loan_amount_usd
                )
                
                if not simulation['success']:
                    logger.warning(f"❌ Simulation failed: {simulation.get('error')}")
                    return {
                        'success': False,
                        'error': 'Simulation failed',
                        'details': simulation
                    }
            
            # Step 2: Build transaction
            transaction = await self.build_flash_loan_transaction(
                opportunity, loan_amount_usd
            )
            
            if not transaction:
                return {
                    'success': False,
                    'error': 'Failed to build transaction'
                }
            
            # Step 3: Send transaction
            logger.info(f"📤 Sending flash loan transaction...")
            
            # In production, this would actually send the transaction
            # For now, return mock success for testing
            
            result = {
                'success': True,
                'transaction_signature': 'mock_signature_' + str(datetime.now().timestamp()),
                'profit': simulation['expected_profit'] if simulate_first else 0,
                'gas_cost': 0.000005,
                'timestamp': datetime.now(timezone.utc),
                'opportunity': opportunity,
                'loan_amount': loan_amount_usd
            }
            
            # Update stats
            self.stats['successes'] += 1
            self.stats['total_profit'] += result['profit']
            self.stats['total_fees_paid'] += result['gas_cost'] * 150  # Convert SOL to USD
            
            logger.info(
                f"✅ Flash loan success! Profit: ${result['profit']:.2f} | "
                f"TX: {result['transaction_signature'][:16]}..."
            )
            
            return result
            
        except Exception as e:
            self.stats['failures'] += 1
            logger.error(f"❌ Flash loan execution failed: {e}")
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
            'net_profit': self.stats['total_profit'] - self.stats['total_fees_paid']
        }
    
    async def close(self):
        """Close RPC connection"""
        await self.client.close()


# Testing
async def test_flash_loan_executor():
    """Test flash loan executor with mock opportunity"""
    print("🧪 Testing Flash Loan Executor")
    print("=" * 60)
    
    # Initialize executor
    executor = FlashLoanExecutor(
        rpc_url="https://api.devnet.solana.com",
        provider='solend'
    )
    
    # Mock opportunity
    opportunity = {
        'token_pair': 'SOL/USDC',
        'dex_buy': 'raydium',
        'dex_sell': 'orca',
        'buy_price': 150.00,
        'sell_price': 150.50,
        'net_profit_percentage': 0.30,  # 0.30% profit
        'liquidity_buy': 100000,
        'liquidity_sell': 100000
    }
    
    loan_amount = 10000  # $10k flash loan
    
    # Test profitability check
    print("\n1. Checking profitability...")
    profitability = await executor.check_opportunity_profitability(
        opportunity, loan_amount
    )
    print(f"   Is Profitable: {profitability['is_profitable']}")
    print(f"   Net Profit: ${profitability['net_profit']:.2f}")
    
    # Test simulation
    print("\n2. Simulating transaction...")
    simulation = await executor.simulate_flash_loan_arbitrage(
        opportunity, loan_amount
    )
    print(f"   Success: {simulation['success']}")
    print(f"   Expected Profit: ${simulation.get('expected_profit', 0):.2f}")
    
    # Test execution (mock)
    print("\n3. Executing flash loan arbitrage...")
    result = await executor.execute_flash_loan_arbitrage(
        opportunity, loan_amount
    )
    print(f"   Success: {result['success']}")
    if result['success']:
        print(f"   Profit: ${result['profit']:.2f}")
        print(f"   TX: {result['transaction_signature'][:32]}...")
    
    # Show stats
    print("\n4. Executor Statistics:")
    stats = executor.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    await executor.close()
    print("\n" + "=" * 60)
    print("✅ Test complete!")


if __name__ == "__main__":
    asyncio.run(test_flash_loan_executor())
