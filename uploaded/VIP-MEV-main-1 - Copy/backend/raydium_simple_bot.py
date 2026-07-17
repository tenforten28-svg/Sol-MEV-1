"""
SIMPLIFIED RAYDIUM BOT - MVP
==========================
- Single DEX (Raydium only)
- Single pool (SOL/USDC)
- Direct pool interaction (no Jupiter API)
- Local price calculation from reserves
- Real transaction execution

NO flash loans, NO multi-DEX, NO external APIs for prices
"""

import asyncio
import os
import struct
import logging
from typing import Dict, Optional, Tuple
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
import base58

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('raydium_simple_bot')

# =============================================================================
# RAYDIUM AMM V4 CONSTANTS (Mainnet)
# =============================================================================

# Raydium AMM Program ID
RAYDIUM_AMM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")

# Token Program
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

# SOL/USDC Pool (Raydium AMM v4)
RAYDIUM_SOL_USDC_POOL = {
    'pool_id': Pubkey.from_string("58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"),
    'authority': Pubkey.from_string("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"),
    'open_orders': Pubkey.from_string("HRk9CMrpq7Fo9csEw5zFzhViMZYCrS8HTVU5bQPfr1A6"),
    'target_orders': Pubkey.from_string("CZza3Ej4Mc58MnxWA385itCC9jCo3L1D7zc3LKy1bZMR"),
    'coin_vault': Pubkey.from_string("DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz"),  # SOL vault
    'pc_vault': Pubkey.from_string("HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz"),    # USDC vault
    'vault_signer': Pubkey.from_string("GpxTAYyJqAJrVwDyPd4BL6eqwSGqMkQbMgJZrAkkxsbT"),
    'coin_mint': Pubkey.from_string("So11111111111111111111111111111111111111112"),     # SOL
    'pc_mint': Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),     # USDC
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
# STEP 3: RPC CONNECTION
# =============================================================================

class RaydiumSimpleBot:
    """Simple Raydium bot with direct pool interaction"""
    
    def __init__(self):
        self.rpc_url = os.environ.get('SOLANA_RPC_URL')
        if not self.rpc_url:
            raise ValueError("SOLANA_RPC_URL not set in .env")
        
        self.client: Optional[AsyncClient] = None
        self.wallet: Optional[Keypair] = None
        
        # Pool state
        self.sol_reserve = 0
        self.usdc_reserve = 0
        self.last_update = None
        
        # Fee (Raydium charges 0.25% = 25 bps)
        self.fee_bps = 25
        
        logger.info(f"RPC URL: {self.rpc_url[:50]}...")
    
    async def connect(self):
        """Connect to Solana RPC"""
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
                self.wallet = None
        else:
            logger.warning("No SOLANA_PRIVATE_KEY set - read-only mode")
        
        # Test connection
        try:
            slot = await self.client.get_slot()
            logger.info(f"Connected to Solana! Current slot: {slot.value}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False
    
    async def close(self):
        """Close RPC connection"""
        if self.client:
            await self.client.close()


    # =============================================================================
    # STEP 4 & 5: LOAD AND PARSE RAYDIUM POOL
    # =============================================================================
    
    async def fetch_pool_state(self) -> bool:
        """
        Fetch Raydium pool account and parse reserves
        This is STEP 4 and STEP 5 combined
        """
        try:
            pool_id = RAYDIUM_SOL_USDC_POOL['pool_id']
            
            # Fetch pool account
            response = await self.client.get_account_info(pool_id)
            
            if response.value is None:
                logger.error("Pool account not found!")
                return False
            
            account_data = response.value.data
            
            # Parse Raydium AMM v4 pool state
            # The layout is complex, but we need:
            # - Offset 72-80: coin_reserve (u64) - SOL
            # - Offset 80-88: pc_reserve (u64) - USDC
            
            # Actually, let's fetch the vault balances directly for accuracy
            return await self.fetch_vault_balances()
            
        except Exception as e:
            logger.error(f"Error fetching pool state: {e}")
            return False
    
    async def fetch_vault_balances(self) -> bool:
        """
        Fetch actual token balances from pool vaults
        More reliable than parsing pool state
        """
        try:
            # Fetch SOL vault balance
            sol_vault = RAYDIUM_SOL_USDC_POOL['coin_vault']
            sol_response = await self.client.get_token_account_balance(sol_vault)
            
            if sol_response.value:
                self.sol_reserve = int(sol_response.value.amount)
                logger.info(f"SOL Vault: {self.sol_reserve / 10**SOL_DECIMALS:.4f} SOL")
            
            # Fetch USDC vault balance
            usdc_vault = RAYDIUM_SOL_USDC_POOL['pc_vault']
            usdc_response = await self.client.get_token_account_balance(usdc_vault)
            
            if usdc_response.value:
                self.usdc_reserve = int(usdc_response.value.amount)
                logger.info(f"USDC Vault: {self.usdc_reserve / 10**USDC_DECIMALS:.2f} USDC")
            
            self.last_update = datetime.now(timezone.utc)
            
            # Calculate current price
            if self.sol_reserve > 0 and self.usdc_reserve > 0:
                price = self.calculate_price()
                logger.info(f"Current SOL Price: ${price:.2f}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error fetching vault balances: {e}")
            return False


    # =============================================================================
    # STEP 6: LOCAL PRICE CALCULATION (NO APIs)
    # =============================================================================
    
    def calculate_price(self) -> float:
        """
        Calculate SOL price in USDC from reserves
        NO external API calls!
        """
        if self.sol_reserve == 0:
            return 0
        
        # Adjust for decimals
        sol_amount = self.sol_reserve / 10**SOL_DECIMALS
        usdc_amount = self.usdc_reserve / 10**USDC_DECIMALS
        
        return usdc_amount / sol_amount
    
    def calculate_swap_out(
        self, 
        amount_in: int, 
        reserve_in: int, 
        reserve_out: int,
        fee_bps: int = 25
    ) -> int:
        """
        Calculate output amount for a swap using constant product formula
        
        Args:
            amount_in: Input amount (in smallest units)
            reserve_in: Input token reserve
            reserve_out: Output token reserve
            fee_bps: Fee in basis points (25 = 0.25%)
        
        Returns:
            Output amount (in smallest units)
        """
        # Apply fee to input
        amount_in_after_fee = amount_in * (10000 - fee_bps) // 10000
        
        # Constant product: x * y = k
        # new_reserve_out = k / new_reserve_in
        # amount_out = reserve_out - new_reserve_out
        
        numerator = amount_in_after_fee * reserve_out
        denominator = reserve_in + amount_in_after_fee
        
        return numerator // denominator
    
    def calculate_swap_in(
        self,
        amount_out: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25
    ) -> int:
        """
        Calculate input amount needed to get desired output
        """
        numerator = reserve_in * amount_out * 10000
        denominator = (reserve_out - amount_out) * (10000 - fee_bps)
        
        return (numerator // denominator) + 1


    # =============================================================================
    # STEP 7: TEST TRADE CALCULATION
    # =============================================================================
    
    async def calculate_test_trade(self, usdc_amount: float = 100.0) -> Dict:
        """
        Calculate expected output for a test trade
        USDC → SOL
        """
        # Convert to smallest units
        usdc_in = int(usdc_amount * 10**USDC_DECIMALS)
        
        # Calculate SOL output
        sol_out = self.calculate_swap_out(
            amount_in=usdc_in,
            reserve_in=self.usdc_reserve,
            reserve_out=self.sol_reserve,
            fee_bps=self.fee_bps
        )
        
        # Calculate effective price
        sol_out_decimal = sol_out / 10**SOL_DECIMALS
        effective_price = usdc_amount / sol_out_decimal if sol_out_decimal > 0 else 0
        
        # Calculate price impact
        spot_price = self.calculate_price()
        price_impact = ((effective_price - spot_price) / spot_price) * 100 if spot_price > 0 else 0
        
        result = {
            'usdc_in': usdc_amount,
            'sol_out': sol_out_decimal,
            'effective_price': effective_price,
            'spot_price': spot_price,
            'price_impact_pct': price_impact,
            'fee_paid_usdc': usdc_amount * self.fee_bps / 10000
        }
        
        logger.info(f"Test Trade: {usdc_amount} USDC → {sol_out_decimal:.6f} SOL")
        logger.info(f"  Spot Price: ${spot_price:.2f}")
        logger.info(f"  Effective Price: ${effective_price:.2f}")
        logger.info(f"  Price Impact: {price_impact:.4f}%")
        logger.info(f"  Fee Paid: ${result['fee_paid_usdc']:.4f}")
        
        return result


    # =============================================================================
    # STEP 8: BUILD REAL RAYDIUM SWAP INSTRUCTION
    # =============================================================================
    
    async def build_swap_instruction(
        self,
        amount_in: int,
        minimum_amount_out: int,
        user_source_token: Pubkey,  # User's USDC account
        user_dest_token: Pubkey,    # User's SOL (WSOL) account
        swap_direction: str = "usdc_to_sol"  # or "sol_to_usdc"
    ) -> Instruction:
        """
        Build a Raydium AMM v4 swap instruction
        
        This is the CRITICAL piece that was missing!
        """
        pool = RAYDIUM_SOL_USDC_POOL
        
        # Raydium swap instruction discriminator (instruction index 9 for swap)
        # Data layout: [instruction_index(1), amount_in(8), min_out(8)]
        instruction_data = bytes([9])  # Swap instruction
        instruction_data += struct.pack('<Q', amount_in)
        instruction_data += struct.pack('<Q', minimum_amount_out)
        
        # Account order matters for Raydium AMM v4 swap
        if swap_direction == "usdc_to_sol":
            # Swapping USDC (pc) for SOL (coin)
            accounts = [
                AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['pool_id'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['authority'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['open_orders'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['target_orders'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['coin_vault'], is_signer=False, is_writable=True),  # SOL vault
                AccountMeta(pubkey=pool['pc_vault'], is_signer=False, is_writable=True),    # USDC vault
                AccountMeta(pubkey=pool['serum_program'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['serum_market'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_bids'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_asks'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_event_queue'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_coin_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_pc_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_vault_signer'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=user_source_token, is_signer=False, is_writable=True),  # User USDC
                AccountMeta(pubkey=user_dest_token, is_signer=False, is_writable=True),    # User SOL
                AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),  # User wallet
            ]
        else:
            # Swapping SOL (coin) for USDC (pc)
            accounts = [
                AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['pool_id'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['authority'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['open_orders'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['target_orders'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['pc_vault'], is_signer=False, is_writable=True),    # USDC vault
                AccountMeta(pubkey=pool['coin_vault'], is_signer=False, is_writable=True),  # SOL vault
                AccountMeta(pubkey=pool['serum_program'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=pool['serum_market'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_bids'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_asks'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_event_queue'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_coin_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_pc_vault'], is_signer=False, is_writable=True),
                AccountMeta(pubkey=pool['serum_vault_signer'], is_signer=False, is_writable=False),
                AccountMeta(pubkey=user_source_token, is_signer=False, is_writable=True),  # User SOL
                AccountMeta(pubkey=user_dest_token, is_signer=False, is_writable=True),    # User USDC
                AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
            ]
        
        return Instruction(
            program_id=RAYDIUM_AMM_PROGRAM_ID,
            accounts=accounts,
            data=instruction_data
        )


    # =============================================================================
    # STEP 9: BUILD & SIMULATE TRANSACTION
    # =============================================================================
    
    async def simulate_swap(
        self,
        amount_in: int,
        minimum_amount_out: int,
        user_source_token: Pubkey,
        user_dest_token: Pubkey,
        swap_direction: str = "usdc_to_sol"
    ) -> Dict:
        """
        Build and simulate a swap transaction
        """
        if not self.wallet:
            return {'success': False, 'error': 'No wallet loaded'}
        
        try:
            # Build swap instruction
            swap_ix = await self.build_swap_instruction(
                amount_in=amount_in,
                minimum_amount_out=minimum_amount_out,
                user_source_token=user_source_token,
                user_dest_token=user_dest_token,
                swap_direction=swap_direction
            )
            
            # Get recent blockhash
            blockhash_response = await self.client.get_latest_blockhash()
            recent_blockhash = blockhash_response.value.blockhash
            
            # Build transaction using solders
            message = Message.new_with_blockhash(
                [swap_ix],
                self.wallet.pubkey(),
                Hash.from_string(str(recent_blockhash))
            )
            tx = Transaction.new_unsigned(message)
            tx = tx.sign([self.wallet], Hash.from_string(str(recent_blockhash)))
            
            # Simulate
            simulation = await self.client.simulate_transaction(tx)
            
            if simulation.value.err:
                logger.error(f"Simulation failed: {simulation.value.err}")
                return {
                    'success': False,
                    'error': str(simulation.value.err),
                    'logs': simulation.value.logs
                }
            
            logger.info("Simulation PASSED!")
            if simulation.value.logs:
                for log in simulation.value.logs[-5:]:  # Last 5 logs
                    logger.info(f"  {log}")
            
            return {
                'success': True,
                'transaction': tx,
                'recent_blockhash': recent_blockhash,
                'logs': simulation.value.logs
            }
            
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}


    # =============================================================================
    # STEP 10: SEND TRANSACTION (REAL EXECUTION)
    # =============================================================================
    
    async def execute_swap(
        self,
        amount_in: int,
        minimum_amount_out: int,
        user_source_token: Pubkey,
        user_dest_token: Pubkey,
        swap_direction: str = "usdc_to_sol"
    ) -> Dict:
        """
        Execute a real swap transaction
        
        WARNING: This uses real money!
        """
        # First simulate
        sim_result = await self.simulate_swap(
            amount_in=amount_in,
            minimum_amount_out=minimum_amount_out,
            user_source_token=user_source_token,
            user_dest_token=user_dest_token,
            swap_direction=swap_direction
        )
        
        if not sim_result['success']:
            return sim_result
        
        try:
            tx = sim_result['transaction']
            
            # Send transaction
            logger.info("Sending transaction...")
            response = await self.client.send_transaction(tx)
            
            signature = response.value
            logger.info(f"TX Signature: {signature}")
            logger.info(f"Explorer: https://solscan.io/tx/{signature}")
            
            # Wait for confirmation
            logger.info("Waiting for confirmation...")
            await self.client.confirm_transaction(signature, commitment=Confirmed)
            
            logger.info("Transaction CONFIRMED!")
            
            return {
                'success': True,
                'signature': str(signature),
                'explorer_url': f"https://solscan.io/tx/{signature}"
            }
            
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {'success': False, 'error': str(e)}


    # =============================================================================
    # STEP 12: EVENT-BASED TRIGGER (WebSocket)
    # =============================================================================
    
    async def subscribe_to_pool_updates(self, callback):
        """
        Subscribe to pool account changes via WebSocket
        This replaces sleep(1) polling
        """
        import websockets
        import json
        
        # Convert HTTP URL to WebSocket URL
        ws_url = self.rpc_url.replace('https://', 'wss://').replace('http://', 'ws://')
        
        pool_id = str(RAYDIUM_SOL_USDC_POOL['pool_id'])
        
        subscribe_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "accountSubscribe",
            "params": [
                pool_id,
                {"encoding": "base64", "commitment": "confirmed"}
            ]
        }
        
        try:
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps(subscribe_msg))
                logger.info(f"Subscribed to pool updates: {pool_id[:20]}...")
                
                while True:
                    response = await ws.recv()
                    data = json.loads(response)
                    
                    if 'params' in data:
                        # Pool state changed!
                        logger.info("Pool state updated!")
                        await self.fetch_vault_balances()
                        await callback()
                        
        except Exception as e:
            logger.error(f"WebSocket error: {e}")


    # =============================================================================
    # MAIN MONITORING LOOP
    # =============================================================================
    
    async def run_simple_monitor(self):
        """
        Simple monitoring loop - fetch prices and look for opportunities
        """
        logger.info("=" * 60)
        logger.info("RAYDIUM SIMPLE BOT - MVP")
        logger.info("=" * 60)
        logger.info("Mode: Direct pool interaction (NO Jupiter API)")
        logger.info("Pool: SOL/USDC on Raydium")
        logger.info("=" * 60)
        
        if not await self.connect():
            return
        
        scan_count = 0
        
        while True:
            try:
                # Fetch current pool state
                await self.fetch_vault_balances()
                
                scan_count += 1
                
                # Calculate test trade
                if scan_count % 10 == 1:  # Log every 10 scans
                    await self.calculate_test_trade(usdc_amount=100)
                
                # For now, just monitor - no execution
                if scan_count % 100 == 0:
                    logger.info(f"Scan #{scan_count} | SOL: ${self.calculate_price():.2f}")
                
                await asyncio.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(5)
        
        await self.close()


# =============================================================================
# ENTRY POINT
# =============================================================================

async def main():
    bot = RaydiumSimpleBot()
    await bot.run_simple_monitor()


if __name__ == "__main__":
    asyncio.run(main())
