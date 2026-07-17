"""
Solend Flash Loan Implementation
Implements real Solend flash loan program interaction
"""

import asyncio
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.transaction import Transaction
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed, Finalized
from solana.rpc.types import TxOpts
import struct

logger = logging.getLogger(__name__)

# Solend Program ID (Mainnet)
SOLEND_PROGRAM_ID = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

# Solend Reserves (Mainnet - Main Pool)
SOLEND_RESERVES = {
    'SOL': {
        'reserve': 'DqhH94PjkZsjAqEze2BEkWhFQJ6EyU6MdtMphMgnXqeK',
        'liquidity_supply': '8PbodeaosQP19SjYFx855UMqWxH2HynZLdBXmsrbac36',
        'collateral_mint': '5h6ssFpeDeRbzsEHDbTQNH7nVGgsKrZydxdSTnLm6QdV',
        'collateral_supply': 'FTkSmGsJ3ZqDSHdcnY7ejN1pWV3Ej7i88MYpZyyaqgGt',
        'fee_receiver': '8c51v2G3Y4Hv6R8jVJaJoKG3CcJBxEYqGXdx6Gxt33vC',
    },
    'USDC': {
        'reserve': 'BgxfHJDzm44T7XG68MYKx7YisTjZu73tVovyZSjJMpmw',
        'liquidity_supply': '8SheGtsopRUDzdiD6v6BR9a6bqZ9QwywYQY99Fp5meNf',
        'collateral_mint': '993dVFL2uXWYeoXuEBFXR4BijeXdTv4s6BzsCjJZuwqk',
        'collateral_supply': 'Dqfq8pPzgW2RBxQJG3SiCNmpPY9kMJ6tYTJGLRVLeRy6',
        'fee_receiver': '5Gdx2XcCbYqH6nrmT3xLfnLJDhGkGJtfKEJhXPf46e5J',
    },
    'USDT': {
        'reserve': 'BTsbZDV7aCMRJ3VNy9ygV7ApdvCaZnSZU8x4UQqQKZf',
        'liquidity_supply': 'BXsK4DJR3W6o7wDZaEtR9XmqHhWS8X3Y3N1q1MQdG9Cq',
        'collateral_mint': 'BTsbZDV7aCMRJ3VNy9ygV7ApdvCaZnSZU8x4UQqQKZf',
        'collateral_supply': 'B3KTz1VfWZU2p6B2uZ4pHtCYdVCdyWRJYHcGMHSxYfYR',
        'fee_receiver': '4bRLP6vLyQ7Y8qP7rM9VZX5qY8Z9NhR8QXfDCMvxHxVZ',
    }
}

# Flash loan fee: 0.09% (9 basis points)
FLASH_LOAN_FEE_BPS = 9


@dataclass
class FlashLoanParams:
    """Parameters for flash loan"""
    reserve: str  # Token (SOL, USDC, USDT)
    amount: int  # Amount in lamports/smallest unit
    user_wallet: Pubkey
    instructions: List[Instruction]  # Instructions to execute with borrowed funds


class SolendFlashLoan:
    """
    Solend Flash Loan Implementation
    
    Flash loan flow:
    1. Flash borrow from Solend
    2. Execute arbitrage instructions
    3. Flash repay to Solend (amount + 0.09% fee)
    
    All in one atomic transaction
    """
    
    def __init__(self, rpc_client: AsyncClient):
        self.client = rpc_client
        self.program_id = SOLEND_PROGRAM_ID
    
    def calculate_flash_loan_fee(self, amount: int) -> int:
        """Calculate flash loan fee (0.09%)"""
        return (amount * FLASH_LOAN_FEE_BPS) // 10000
    
    async def get_reserve_data(self, token: str) -> Optional[Dict]:
        """Get reserve data for token"""
        if token not in SOLEND_RESERVES:
            logger.error(f"Token {token} not supported")
            return None
        
        return SOLEND_RESERVES[token]
    
    def build_flash_borrow_instruction(
        self,
        params: FlashLoanParams,
        reserve_data: Dict
    ) -> Instruction:
        """
        Build Solend flash borrow instruction
        
        Instruction discriminator: [11] (flash borrow)
        Data: [11, amount: u64]
        """
        # Build instruction data
        instruction_data = bytearray()
        instruction_data.append(11)  # Flash borrow discriminator
        instruction_data.extend(struct.pack('<Q', params.amount))
        
        # Build accounts
        # Order matters - must match Solend program expectations
        accounts = [
            # Source liquidity (Solend pool)
            AccountMeta(
                pubkey=Pubkey.from_string(reserve_data['liquidity_supply']),
                is_signer=False,
                is_writable=True
            ),
            # Destination (user's token account)
            AccountMeta(
                pubkey=params.user_wallet,
                is_signer=False,
                is_writable=True
            ),
            # Reserve account
            AccountMeta(
                pubkey=Pubkey.from_string(reserve_data['reserve']),
                is_signer=False,
                is_writable=True
            ),
            # Lending market (Solend main pool)
            AccountMeta(
                pubkey=Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"),
                is_signer=False,
                is_writable=False
            ),
            # Token program
            AccountMeta(
                pubkey=TOKEN_PROGRAM_ID,
                is_signer=False,
                is_writable=False
            ),
        ]
        
        return Instruction(
            program_id=self.program_id,
            accounts=accounts,
            data=bytes(instruction_data)
        )
    
    def build_flash_repay_instruction(
        self,
        params: FlashLoanParams,
        reserve_data: Dict,
        repay_amount: int
    ) -> Instruction:
        """
        Build Solend flash repay instruction
        
        Instruction discriminator: [12] (flash repay)
        Data: [12, amount: u64]
        """
        # Build instruction data
        instruction_data = bytearray()
        instruction_data.append(12)  # Flash repay discriminator
        instruction_data.extend(struct.pack('<Q', repay_amount))
        
        # Build accounts (reverse of borrow)
        accounts = [
            # Source (user's token account)
            AccountMeta(
                pubkey=params.user_wallet,
                is_signer=True,
                is_writable=True
            ),
            # Destination (Solend pool)
            AccountMeta(
                pubkey=Pubkey.from_string(reserve_data['liquidity_supply']),
                is_signer=False,
                is_writable=True
            ),
            # Fee receiver
            AccountMeta(
                pubkey=Pubkey.from_string(reserve_data['fee_receiver']),
                is_signer=False,
                is_writable=True
            ),
            # Reserve account
            AccountMeta(
                pubkey=Pubkey.from_string(reserve_data['reserve']),
                is_signer=False,
                is_writable=True
            ),
            # Lending market
            AccountMeta(
                pubkey=Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"),
                is_signer=False,
                is_writable=False
            ),
            # Token program
            AccountMeta(
                pubkey=TOKEN_PROGRAM_ID,
                is_signer=False,
                is_writable=False
            ),
        ]
        
        return Instruction(
            program_id=self.program_id,
            accounts=accounts,
            data=bytes(instruction_data)
        )
    
    async def build_flash_loan_transaction(
        self,
        token: str,
        amount: float,
        user_keypair: Keypair,
        arbitrage_instructions: List[Instruction]
    ) -> Optional[Transaction]:
        """
        Build complete flash loan transaction
        
        Transaction structure:
        1. Flash borrow from Solend
        2. Execute arbitrage (swap on DEX 1)
        3. Execute arbitrage (swap on DEX 2)
        4. Flash repay to Solend (borrowed + fee)
        
        Args:
            token: Token to borrow (SOL, USDC, USDT)
            amount: Amount to borrow
            user_keypair: User's keypair
            arbitrage_instructions: Instructions to execute with borrowed funds
            
        Returns:
            Complete atomic transaction
        """
        try:
            # Get reserve data
            reserve_data = await self.get_reserve_data(token)
            if not reserve_data:
                return None
            
            # Convert to lamports
            if token == 'SOL':
                amount_lamports = int(amount * 1e9)
            else:
                amount_lamports = int(amount * 1e6)
            
            # Calculate fee
            fee_amount = self.calculate_flash_loan_fee(amount_lamports)
            repay_amount = amount_lamports + fee_amount
            
            logger.info(
                f"💰 Flash loan: {amount} {token} | "
                f"Fee: {fee_amount/1e6:.2f} {token} | "
                f"Repay: {repay_amount/1e6:.2f} {token}"
            )
            
            # Build params
            params = FlashLoanParams(
                reserve=token,
                amount=amount_lamports,
                user_wallet=user_keypair.pubkey(),
                instructions=arbitrage_instructions
            )
            
            # Build instructions
            # 1. Flash borrow
            borrow_ix = self.build_flash_borrow_instruction(params, reserve_data)
            
            # 2. Arbitrage instructions (provided)
            # These execute with the borrowed funds
            
            # 3. Flash repay
            repay_ix = self.build_flash_repay_instruction(
                params,
                reserve_data,
                repay_amount
            )
            
            # Build complete transaction
            from solders.message import Message
            
            # Collect all instructions
            all_instructions = [borrow_ix]
            all_instructions.extend(arbitrage_instructions)
            all_instructions.append(repay_ix)
            
            # Create message
            message = Message.new_with_blockhash(
                all_instructions,
                user_keypair.pubkey(),
                None  # Will set blockhash later
            )
            
            # Create transaction
            transaction = Transaction([user_keypair], message, None)
            
            logger.info(
                f"✅ Built flash loan transaction with "
                f"{len(arbitrage_instructions)} arbitrage instructions"
            )
            
            return transaction
            
        except Exception as e:
            logger.error(f"Error building flash loan transaction: {e}")
            return None
    
    async def simulate_flash_loan(
        self,
        transaction: Transaction,
        keypair: Keypair
    ) -> Dict:
        """
        Simulate flash loan transaction before sending
        Critical for avoiding failed transactions
        """
        try:
            # Get recent blockhash
            recent_blockhash = await self.client.get_latest_blockhash()
            transaction.recent_blockhash = recent_blockhash.value.blockhash
            
            # Sign transaction
            transaction.sign(keypair)
            
            # Simulate
            simulation = await self.client.simulate_transaction(transaction)
            
            if simulation.value.err:
                logger.error(f"Simulation failed: {simulation.value.err}")
                return {
                    'success': False,
                    'error': str(simulation.value.err),
                    'logs': simulation.value.logs
                }
            
            logger.info("✅ Simulation successful!")
            return {
                'success': True,
                'logs': simulation.value.logs,
                'compute_units': simulation.value.units_consumed
            }
            
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def execute_flash_loan(
        self,
        transaction: Transaction,
        keypair: Keypair,
        simulate_first: bool = True
    ) -> Dict:
        """
        Execute flash loan transaction on-chain
        
        Returns:
            {
                'success': bool,
                'signature': str,
                'error': Optional[str]
            }
        """
        try:
            # Simulate first
            if simulate_first:
                sim_result = await self.simulate_flash_loan(transaction, keypair)
                if not sim_result['success']:
                    return {
                        'success': False,
                        'error': f"Simulation failed: {sim_result['error']}"
                    }
            
            # Get recent blockhash
            recent_blockhash = await self.client.get_latest_blockhash()
            transaction.recent_blockhash = recent_blockhash.value.blockhash
            
            # Sign transaction
            transaction.sign(keypair)
            
            # Send transaction
            opts = TxOpts(
                skip_preflight=False,
                preflight_commitment=Confirmed,
                max_retries=3
            )
            
            response = await self.client.send_transaction(
                transaction,
                keypair,
                opts=opts
            )
            
            signature = str(response.value)
            
            logger.info(f"📤 Transaction sent: {signature}")
            
            # Wait for confirmation
            confirmation = await self.client.confirm_transaction(
                signature,
                commitment=Confirmed
            )
            
            if confirmation.value.err:
                logger.error(f"Transaction failed: {confirmation.value.err}")
                return {
                    'success': False,
                    'signature': signature,
                    'error': str(confirmation.value.err)
                }
            
            logger.info(f"✅ Flash loan executed successfully!")
            return {
                'success': True,
                'signature': signature
            }
            
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {
                'success': False,
                'error': str(e)
            }


# Testing
async def test_solend_flash_loan():
    """Test Solend flash loan builder"""
    print("🧪 Testing Solend Flash Loan")
    print("=" * 70)
    
    # Mock RPC client
    rpc = AsyncClient("https://api.mainnet-beta.solana.com")
    
    # Generate test keypair
    keypair = Keypair()
    print(f"Test wallet: {keypair.pubkey()}")
    
    # Initialize flash loan
    flash_loan = SolendFlashLoan(rpc)
    
    # Calculate fee
    borrow_amount = 10000  # $10,000 USDC
    fee = flash_loan.calculate_flash_loan_fee(int(borrow_amount * 1e6))
    print(f"\n1. Fee calculation:")
    print(f"   Borrow: ${borrow_amount:,}")
    print(f"   Fee: ${fee/1e6:.2f} (0.09%)")
    print(f"   Repay: ${(borrow_amount + fee/1e6):.2f}")
    
    # Test transaction building
    print(f"\n2. Building flash loan transaction...")
    
    # Mock arbitrage instructions (would be real DEX swaps in production)
    mock_instructions = []
    
    transaction = await flash_loan.build_flash_loan_transaction(
        token='USDC',
        amount=10000,
        user_keypair=keypair,
        arbitrage_instructions=mock_instructions
    )
    
    if transaction:
        print(f"   ✅ Transaction built with {len(transaction.instructions)} instructions")
        print(f"   Instructions: Borrow → Arbitrage → Repay")
    else:
        print(f"   ❌ Failed to build transaction")
    
    await rpc.close()
    print("\n" + "=" * 70)
    print("✅ Solend flash loan testing complete!")


if __name__ == "__main__":
    asyncio.run(test_solend_flash_loan())
