"""
SOLEND FLASH LOAN ARBITRAGE BOT
===============================
- Borrows USDC from Solend via flash loan
- Swaps USDC -> SOL on Raydium
- Swaps SOL -> USDC on Raydium  
- Repays flash loan + fee
- Keeps profit

Based on the working raydium_simple_bot.py
"""

import asyncio
import os
import struct
import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
from dotenv import load_dotenv

# Solana imports
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.transaction import Transaction
from solders.message import Message
from solders.hash import Hash
from solders.system_program import ID as SYSTEM_PROGRAM_ID
import base58

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('flashloan_bot')

# =============================================================================
# STEP 2: SOLEND PROGRAM IDS
# =============================================================================

SOLEND_PROGRAM_ID = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo")

# =============================================================================
# STEP 3: SOLEND USDC RESERVE (Mainnet - Main Pool)
# =============================================================================

SOLEND_USDC_RESERVE = {
    'reserve': Pubkey.from_string("BgxfHJDzm44T7XG68MYKx7YisTjZu73tVovyZSjJMpmw"),
    'liquidity_supply': Pubkey.from_string("8SheGtsopRUDzdiD6v6BR9a6bqZ9QwywYQY99Fp5meNf"),
    'fee_receiver': Pubkey.from_string("5Gdxn4yquneifE6uk9tK8XSXR5RGBdJGSHsZfZpY2ZtE"),
    'lending_market': Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"),
    'lending_market_authority': Pubkey.from_string("DdZR6zRFiUt4S5mg7AV1uKB2z1f1WzcNYCaTEEWPAuby"),
}

# Token Program
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

# USDC Mint
USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

# =============================================================================
# RAYDIUM POOL (Same as raydium_simple_bot.py)
# =============================================================================

RAYDIUM_AMM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")

RAYDIUM_SOL_USDC_POOL = {
    'pool_id': Pubkey.from_string("58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"),
    'authority': Pubkey.from_string("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"),
    'open_orders': Pubkey.from_string("HRk9CMrpq7Fo9csEw5zFzhViMZYCrS8HTVU5bQPfr1A6"),
    'target_orders': Pubkey.from_string("CZza3Ej4Mc58MnxWA385itCC9jCo3L1D7zc3LKy1bZMR"),
    'coin_vault': Pubkey.from_string("DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz"),
    'pc_vault': Pubkey.from_string("HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz"),
    'vault_signer': Pubkey.from_string("GpxTAYyJqAJrVwDyPd4BL6eqwSGqMkQbMgJZrAkkxsbT"),
    'coin_mint': Pubkey.from_string("So11111111111111111111111111111111111111112"),
    'pc_mint': Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
    'serum_program': Pubkey.from_string("srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX"),
    'serum_market': Pubkey.from_string("8BnEgHoWFysVcuFFX7QztDmzuH8r5ZFvyP3sYwn1XTh6"),
    'serum_bids': Pubkey.from_string("5jWUncPNBMZJ3sTHKmMLszypVkoRK6gqbRk1DBQpcfBS"),
    'serum_asks': Pubkey.from_string("EaXdHx7x3mdGA38j5RSmKYSXMzAFzzUXCLNBEDXDn1d5"),
    'serum_event_queue': Pubkey.from_string("8CvwxZ9Db6XbLD46NZwwmVDZZRDy7eydFcAGkXKh9axa"),
    'serum_coin_vault': Pubkey.from_string("CKxTHwM9fPMRRvZmFnFoqKNd9pQR21c5Aq9bh5h9oghX"),
    'serum_pc_vault': Pubkey.from_string("6A5NHCj1yF6urc9wZNe6Bcjj4LVszQNj5DwAWG97uj7R"),
    'serum_vault_signer': Pubkey.from_string("CTz5UMLQm2SRWHzQnU62Pi4yJqbNGjgRBHqqp6oDHfF7"),
}

# Token decimals
SOL_DECIMALS = 9
USDC_DECIMALS = 6

# =============================================================================
# STEP 10: FLASH LOAN AMOUNT (START SMALL!)
# =============================================================================

FLASHLOAN_AMOUNT_USDC = 1000  # Start with $1,000 USDC
SOLEND_FLASHLOAN_FEE_BPS = 30  # 0.30% fee


class FlashLoanBot:
    """
    Flash Loan Arbitrage Bot
    Borrows from Solend -> Swaps on Raydium -> Repays with profit
    """
    
    def __init__(self):
        self.rpc_url = os.environ.get('SOLANA_RPC_URL')
        if not self.rpc_url:
            raise ValueError("SOLANA_RPC_URL not set in .env")
        
        self.client: Optional[AsyncClient] = None
        self.wallet: Optional[Keypair] = None
        
        # Pool state
        self.sol_reserve = 0
        self.usdc_reserve = 0
        
        # User token accounts (will be fetched)
        self.user_usdc_account: Optional[Pubkey] = None
        self.user_wsol_account: Optional[Pubkey] = None
        
        # Raydium fee
        self.raydium_fee_bps = 25
        
        logger.info(f"RPC URL: {self.rpc_url[:50]}...")
    
    async def connect(self):
        """Connect to Solana RPC and load wallet"""
        self.client = AsyncClient(self.rpc_url, commitment=Confirmed)
        
        # Load wallet
        private_key = os.environ.get('SOLANA_PRIVATE_KEY')
        if private_key:
            try:
                key_bytes = base58.b58decode(private_key)
                self.wallet = Keypair.from_bytes(key_bytes)
                logger.info(f"Wallet loaded: {self.wallet.pubkey()}")
            except Exception as e:
                logger.error(f"Failed to load wallet: {e}")
                return False
        else:
            logger.error("No SOLANA_PRIVATE_KEY set!")
            return False
        
        # Test connection
        try:
            slot = await self.client.get_slot()
            logger.info(f"Connected to Solana! Current slot: {slot.value}")
            
            # Find user token accounts
            await self.find_user_token_accounts()
            
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False
    
    async def close(self):
        """Close RPC connection"""
        if self.client:
            await self.client.close()
    
    async def find_user_token_accounts(self):
        """Find user's USDC and WSOL token accounts"""
        try:
            # Get all token accounts for the wallet
            response = await self.client.get_token_accounts_by_owner(
                self.wallet.pubkey(),
                {"programId": TOKEN_PROGRAM_ID}
            )
            
            for account in response.value:
                # Parse account data to get mint
                data = account.account.data
                # Token account data: first 32 bytes = mint
                # This is simplified - in production use proper parsing
                pubkey = account.pubkey
                
                # For now, we'll use Associated Token Account addresses
                pass
            
            # Calculate Associated Token Account addresses
            from solders.pubkey import Pubkey
            
            # USDC ATA
            self.user_usdc_account, _ = Pubkey.find_program_address(
                [
                    bytes(self.wallet.pubkey()),
                    bytes(TOKEN_PROGRAM_ID),
                    bytes(USDC_MINT),
                ],
                Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
            )
            logger.info(f"User USDC Account: {self.user_usdc_account}")
            
            # WSOL ATA
            wsol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
            self.user_wsol_account, _ = Pubkey.find_program_address(
                [
                    bytes(self.wallet.pubkey()),
                    bytes(TOKEN_PROGRAM_ID),
                    bytes(wsol_mint),
                ],
                Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
            )
            logger.info(f"User WSOL Account: {self.user_wsol_account}")
            
        except Exception as e:
            logger.error(f"Error finding token accounts: {e}")

    async def fetch_pool_reserves(self) -> bool:
        """Fetch Raydium pool reserves"""
        try:
            # Fetch SOL vault
            sol_vault = RAYDIUM_SOL_USDC_POOL['coin_vault']
            sol_response = await self.client.get_token_account_balance(sol_vault)
            if sol_response.value:
                self.sol_reserve = int(sol_response.value.amount)
            
            # Fetch USDC vault
            usdc_vault = RAYDIUM_SOL_USDC_POOL['pc_vault']
            usdc_response = await self.client.get_token_account_balance(usdc_vault)
            if usdc_response.value:
                self.usdc_reserve = int(usdc_response.value.amount)
            
            return True
        except Exception as e:
            logger.error(f"Error fetching reserves: {e}")
            return False

    def calculate_price(self) -> float:
        """Calculate SOL price from reserves"""
        if self.sol_reserve == 0:
            return 0
        sol_amount = self.sol_reserve / 10**SOL_DECIMALS
        usdc_amount = self.usdc_reserve / 10**USDC_DECIMALS
        return usdc_amount / sol_amount

    def calculate_swap_out(self, amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int = 25) -> int:
        """Calculate output amount for a swap"""
        amount_in_after_fee = amount_in * (10000 - fee_bps) // 10000
        numerator = amount_in_after_fee * reserve_out
        denominator = reserve_in + amount_in_after_fee
        return numerator // denominator

    # =============================================================================
    # STEP 4: FLASH LOAN BORROW INSTRUCTION
    # =============================================================================
    
    def build_flashloan_borrow_instruction(
        self,
        amount: int,  # Amount in smallest units (e.g., 1000 * 10^6 for 1000 USDC)
    ) -> Instruction:
        """
        Build Solend flash loan borrow instruction
        
        Solend FlashBorrowReserveLiquidity instruction (index 20)
        """
        reserve = SOLEND_USDC_RESERVE
        
        # Instruction data: [20 (instruction index), amount (u64)]
        instruction_data = bytes([20])  # FlashBorrowReserveLiquidity
        instruction_data += struct.pack('<Q', amount)
        
        accounts = [
            AccountMeta(pubkey=reserve['liquidity_supply'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=self.user_usdc_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['reserve'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['lending_market'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=reserve['lending_market_authority'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SOLEND_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        
        return Instruction(
            program_id=SOLEND_PROGRAM_ID,
            accounts=accounts,
            data=instruction_data
        )

    # =============================================================================
    # STEP 5: FLASH LOAN REPAY INSTRUCTION
    # =============================================================================
    
    def build_flashloan_repay_instruction(
        self,
        amount: int,  # Original borrow amount + fee
    ) -> Instruction:
        """
        Build Solend flash loan repay instruction
        
        Solend FlashRepayReserveLiquidity instruction (index 21)
        """
        reserve = SOLEND_USDC_RESERVE
        
        # Calculate repay amount with fee
        fee = (amount * SOLEND_FLASHLOAN_FEE_BPS) // 10000
        repay_amount = amount + fee
        
        # Instruction data: [21 (instruction index), amount (u64), borrow_instruction_index (u8)]
        instruction_data = bytes([21])  # FlashRepayReserveLiquidity
        instruction_data += struct.pack('<Q', repay_amount)
        instruction_data += bytes([0])  # Index of borrow instruction in transaction (0 = first)
        
        accounts = [
            AccountMeta(pubkey=self.user_usdc_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['liquidity_supply'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['fee_receiver'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['reserve'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['lending_market'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        
        return Instruction(
            program_id=SOLEND_PROGRAM_ID,
            accounts=accounts,
            data=instruction_data
        )

    # =============================================================================
    # RAYDIUM SWAP INSTRUCTIONS (From raydium_simple_bot.py)
    # =============================================================================
    
    def build_raydium_swap_instruction(
        self,
        amount_in: int,
        minimum_amount_out: int,
        swap_direction: str  # "usdc_to_sol" or "sol_to_usdc"
    ) -> Instruction:
        """Build Raydium swap instruction"""
        pool = RAYDIUM_SOL_USDC_POOL
        
        instruction_data = bytes([9])  # Swap instruction
        instruction_data += struct.pack('<Q', amount_in)
        instruction_data += struct.pack('<Q', minimum_amount_out)
        
        if swap_direction == "usdc_to_sol":
            user_source = self.user_usdc_account
            user_dest = self.user_wsol_account
            accounts = [
                AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['pool_id'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['authority'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['open_orders'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['target_orders'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['coin_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['pc_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_program'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['serum_market'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_bids'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_asks'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_event_queue'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_coin_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_pc_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_vault_signer'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=user_source, is_signer=False, is_writable=True),
                AccountMeta(pubkey=user_dest, is_signer=False, is_writable=True),
                AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
            ]
        else:  # sol_to_usdc
            user_source = self.user_wsol_account
            user_dest = self.user_usdc_account
            accounts = [
                AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['pool_id'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['authority'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['open_orders'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['target_orders'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['pc_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['coin_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_program'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['serum_market'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_bids'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_asks'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_event_queue'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_coin_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_pc_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_vault_signer'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=user_source, is_signer=False, is_writable=True),
                AccountMeta(pubkey=user_dest, is_signer=False, is_writable=True),
                AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
            ]
        
        return Instruction(
            program_id=RAYDIUM_AMM_PROGRAM_ID,
            accounts=accounts,
            data=instruction_data
        )

    # =============================================================================
    # STEP 9: PROFIT CHECK
    # =============================================================================
    
    def calculate_expected_profit(self, loan_amount_usdc: int) -> Dict:
        """
        Calculate expected profit from flash loan arbitrage
        
        Flow: Borrow USDC -> Buy SOL -> Sell SOL -> Repay + Keep Profit
        """
        # Convert to smallest units
        loan_amount = loan_amount_usdc * 10**USDC_DECIMALS
        
        # Step 1: Buy SOL with borrowed USDC
        sol_received = self.calculate_swap_out(
            amount_in=loan_amount,
            reserve_in=self.usdc_reserve,
            reserve_out=self.sol_reserve,
            fee_bps=self.raydium_fee_bps
        )
        
        # Step 2: Sell SOL back to USDC
        # Note: Reserves change after first swap, but for estimation we use original
        usdc_received = self.calculate_swap_out(
            amount_in=sol_received,
            reserve_in=self.sol_reserve,
            reserve_out=self.usdc_reserve,
            fee_bps=self.raydium_fee_bps
        )
        
        # Step 3: Calculate flash loan fee
        flashloan_fee = (loan_amount * SOLEND_FLASHLOAN_FEE_BPS) // 10000
        
        # Step 4: Calculate profit
        total_cost = loan_amount + flashloan_fee
        profit = usdc_received - total_cost
        profit_usdc = profit / 10**USDC_DECIMALS
        
        return {
            'loan_amount_usdc': loan_amount_usdc,
            'sol_received': sol_received / 10**SOL_DECIMALS,
            'usdc_received': usdc_received / 10**USDC_DECIMALS,
            'flashloan_fee_usdc': flashloan_fee / 10**USDC_DECIMALS,
            'profit_usdc': profit_usdc,
            'profitable': profit > 0
        }

    # =============================================================================
    # STEP 6 & 7: BUILD AND SIMULATE FLASH LOAN TRANSACTION
    # =============================================================================
    
    async def build_flashloan_arbitrage_tx(self, loan_amount_usdc: int) -> Optional[Transaction]:
        """
        Build complete flash loan arbitrage transaction
        
        Order (CRITICAL):
        1. Solend Flash Loan Borrow
        2. Raydium Buy (USDC -> SOL)
        3. Raydium Sell (SOL -> USDC)
        4. Solend Flash Loan Repay
        """
        loan_amount = loan_amount_usdc * 10**USDC_DECIMALS
        
        # Calculate expected outputs
        sol_to_receive = self.calculate_swap_out(
            loan_amount, self.usdc_reserve, self.sol_reserve, self.raydium_fee_bps
        )
        usdc_to_receive = self.calculate_swap_out(
            sol_to_receive, self.sol_reserve, self.usdc_reserve, self.raydium_fee_bps
        )
        
        # Minimum outputs with 1% slippage tolerance
        min_sol = int(sol_to_receive * 0.99)
        min_usdc = int(usdc_to_receive * 0.99)
        
        # Build instructions in CORRECT ORDER
        instructions = []
        
        # 1. Flash Loan Borrow
        borrow_ix = self.build_flashloan_borrow_instruction(loan_amount)
        instructions.append(borrow_ix)
        
        # 2. Raydium Buy (USDC -> SOL)
        buy_ix = self.build_raydium_swap_instruction(
            amount_in=loan_amount,
            minimum_amount_out=min_sol,
            swap_direction="usdc_to_sol"
        )
        instructions.append(buy_ix)
        
        # 3. Raydium Sell (SOL -> USDC)
        sell_ix = self.build_raydium_swap_instruction(
            amount_in=sol_to_receive,
            minimum_amount_out=min_usdc,
            swap_direction="sol_to_usdc"
        )
        instructions.append(sell_ix)
        
        # 4. Flash Loan Repay
        repay_ix = self.build_flashloan_repay_instruction(loan_amount)
        instructions.append(repay_ix)
        
        try:
            # Get recent blockhash
            blockhash_response = await self.client.get_latest_blockhash()
            recent_blockhash = blockhash_response.value.blockhash
            
            # Build transaction
            message = Message.new_with_blockhash(
                instructions,
                self.wallet.pubkey(),
                Hash.from_string(str(recent_blockhash))
            )
            tx = Transaction.new_unsigned(message)
            tx = tx.sign([self.wallet], Hash.from_string(str(recent_blockhash)))
            
            return tx
            
        except Exception as e:
            logger.error(f"Error building transaction: {e}")
            return None

    async def simulate_flashloan_tx(self, loan_amount_usdc: int) -> Dict:
        """
        Simulate flash loan transaction before sending
        """
        tx = await self.build_flashloan_arbitrage_tx(loan_amount_usdc)
        
        if not tx:
            return {'success': False, 'error': 'Failed to build transaction'}
        
        try:
            simulation = await self.client.simulate_transaction(tx)
            
            if simulation.value.err:
                logger.error(f"FLASHLOAN SIM FAILED: {simulation.value.err}")
                if simulation.value.logs:
                    for log in simulation.value.logs[-10:]:
                        logger.error(f"  {log}")
                return {
                    'success': False,
                    'error': str(simulation.value.err),
                    'logs': simulation.value.logs
                }
            
            logger.info("FLASHLOAN SIMULATION PASSED!")
            return {
                'success': True,
                'transaction': tx,
                'logs': simulation.value.logs
            }
            
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            return {'success': False, 'error': str(e)}

    # =============================================================================
    # STEP 8: EXECUTE TRANSACTION
    # =============================================================================
    
    async def execute_flashloan_arbitrage(self, loan_amount_usdc: int) -> Dict:
        """
        Execute flash loan arbitrage
        """
        # Step 9: Profit check
        profit_calc = self.calculate_expected_profit(loan_amount_usdc)
        
        if not profit_calc['profitable']:
            logger.info(f"Skipping - not profitable. Expected: ${profit_calc['profit_usdc']:.4f}")
            return {'success': False, 'error': 'Not profitable', 'profit': profit_calc}
        
        logger.info(f"Expected profit: ${profit_calc['profit_usdc']:.4f}")
        
        # Simulate first
        sim_result = await self.simulate_flashloan_tx(loan_amount_usdc)
        
        if not sim_result['success']:
            return sim_result
        
        # Execute
        try:
            tx = sim_result['transaction']
            
            logger.info("Sending flash loan transaction...")
            response = await self.client.send_transaction(tx)
            
            signature = response.value
            logger.info(f"TX Signature: {signature}")
            logger.info(f"Explorer: https://solscan.io/tx/{signature}")
            
            # Wait for confirmation
            await self.client.confirm_transaction(signature, commitment=Confirmed)
            
            logger.info("FLASH LOAN EXECUTED SUCCESSFULLY!")
            
            return {
                'success': True,
                'signature': str(signature),
                'profit': profit_calc
            }
            
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {'success': False, 'error': str(e)}

    # =============================================================================
    # MAIN LOOP
    # =============================================================================
    
    async def run(self):
        """Main bot loop"""
        logger.info("=" * 60)
        logger.info("SOLEND FLASH LOAN ARBITRAGE BOT")
        logger.info("=" * 60)
        logger.info(f"Loan Amount: ${FLASHLOAN_AMOUNT_USDC} USDC")
        logger.info(f"Flash Loan Fee: {SOLEND_FLASHLOAN_FEE_BPS} bps")
        logger.info("=" * 60)
        
        if not await self.connect():
            return
        
        scan_count = 0
        opportunities_found = 0
        trades_executed = 0
        
        while True:
            try:
                # Fetch latest reserves
                await self.fetch_pool_reserves()
                scan_count += 1
                
                # Calculate potential profit
                profit_calc = self.calculate_expected_profit(FLASHLOAN_AMOUNT_USDC)
                
                if scan_count % 10 == 1:
                    price = self.calculate_price()
                    logger.info(f"Scan #{scan_count} | SOL: ${price:.2f} | Expected Profit: ${profit_calc['profit_usdc']:.4f}")
                
                # Check if profitable
                if profit_calc['profitable']:
                    opportunities_found += 1
                    logger.info(f"OPPORTUNITY FOUND! Expected profit: ${profit_calc['profit_usdc']:.4f}")
                    
                    # Try to execute
                    result = await self.execute_flashloan_arbitrage(FLASHLOAN_AMOUNT_USDC)
                    
                    if result['success']:
                        trades_executed += 1
                        logger.info(f"Trade #{trades_executed} successful!")
                    else:
                        logger.warning(f"Trade failed: {result.get('error', 'Unknown')}")
                    
                    # Brief pause after trade attempt
                    await asyncio.sleep(5)
                else:
                    await asyncio.sleep(1)
                
                # Progress log
                if scan_count % 100 == 0:
                    logger.info(f"Progress: {scan_count} scans | {opportunities_found} opportunities | {trades_executed} trades")
                
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(5)
        
        await self.close()


async def main():
    bot = FlashLoanBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
