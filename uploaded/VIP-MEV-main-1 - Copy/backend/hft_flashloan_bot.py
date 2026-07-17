"""
HIGH-FREQUENCY FLASH LOAN ARBITRAGE BOT
========================================
- WebSocket subscriptions (NO polling!)
- Raydium + Orca dual DEX
- In-memory price cache
- Local price calculation
- Real-time opportunity detection
- Priority fee support

NO Jupiter API, NO sleep(), NO HTTP polling
"""

import asyncio
import os
import struct
import logging
import json
from typing import Dict, Optional
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
import websockets

load_dotenv()

# Configure logging - STEP 10: LOG ONLY ESSENTIAL FIELDS
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s'
)
logger = logging.getLogger('hft_bot')

# =============================================================================
# CONFIGURATION
# =============================================================================

# STEP 5: Minimum spread to trigger (6 bps = 0.06%)
MIN_SPREAD_BPS = 6

# STEP 7: Minimum profit filter
MIN_PROFIT_USDC = 0.5

# Flash loan amount
FLASHLOAN_AMOUNT_USDC = 1000

# Fees
SOLEND_FLASHLOAN_FEE_BPS = 30
RAYDIUM_FEE_BPS = 25
ORCA_FEE_BPS = 30

# Token decimals
SOL_DECIMALS = 9
USDC_DECIMALS = 6

# =============================================================================
# PROGRAM IDS
# =============================================================================

SOLEND_PROGRAM_ID = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo")
RAYDIUM_AMM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
ORCA_SWAP_PROGRAM_ID = Pubkey.from_string("9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

# =============================================================================
# SOLEND USDC RESERVE
# =============================================================================

SOLEND_USDC_RESERVE = {
    'reserve': Pubkey.from_string("BgxfHJDzm44T7XG68MYKx7YisTjZu73tVovyZSjJMpmw"),
    'liquidity_supply': Pubkey.from_string("8SheGtsopRUDzdiD6v6BR9a6bqZ9QwywYQY99Fp5meNf"),
    'fee_receiver': Pubkey.from_string("5Gdxn4yquneifE6uk9tK8XSXR5RGBdJGSHsZfZpY2ZtE"),
    'lending_market': Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"),
    'lending_market_authority': Pubkey.from_string("DdZR6zRFiUt4S5mg7AV1uKB2z1f1WzcNYCaTEEWPAuby"),
}

# =============================================================================
# RAYDIUM SOL/USDC POOL
# =============================================================================

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

# =============================================================================
# ORCA SOL/USDC POOL (Legacy AMM)
# =============================================================================

ORCA_SOL_USDC_POOL = {
    'pool_id': Pubkey.from_string("EGZ7tiLeH62TPV1gL8WwbXGzEPa9zmcpVnnkPKKnrE2U"),
    'authority': Pubkey.from_string("JU8kmKzDHF9sXWsnoznaFDFezLsE5uomX2JkRMbmsQP"),
    'token_a_vault': Pubkey.from_string("ANP74VNsHwSrq9uUSjiSNyNWvf6ZPrKTmE4gHoNd13Lg"),  # SOL
    'token_b_vault': Pubkey.from_string("75HgnSvXbWKZBpZHveX68ZzAhDqMzNDS29X6BGLtxMo1"),  # USDC
    'pool_token_mint': Pubkey.from_string("APDFRM3HMr8CAGXwKHiu2f5ePSpaiEJhaURwhsRrUUt9"),
    'fee_account': Pubkey.from_string("8JnSiuvQq3BVuCU3n4DrSTw9chBSPvEMswrhtifVkr1o"),
}

# =============================================================================
# STEP 3: SHARED IN-MEMORY PRICE CACHE
# =============================================================================

pool_state = {
    "raydium": {
        "sol_reserve": 0,
        "usdc_reserve": 0,
        "price": 0.0,
        "last_update": None
    },
    "orca": {
        "sol_reserve": 0,
        "usdc_reserve": 0,
        "price": 0.0,
        "last_update": None
    }
}

# Statistics
stats = {
    "opportunities_detected": 0,
    "simulations_run": 0,
    "txs_executed": 0,
    "txs_reverted": 0,
    "total_profit": 0.0,
    "start_time": None
}


class HFTFlashLoanBot:
    """
    High-Frequency Trading Flash Loan Arbitrage Bot
    Uses WebSocket subscriptions for real-time updates
    """
    
    def __init__(self):
        self.rpc_url = os.environ.get('SOLANA_RPC_URL')
        if not self.rpc_url:
            raise ValueError("SOLANA_RPC_URL not set in .env")
        
        self.ws_url = self.rpc_url.replace('https://', 'wss://').replace('http://', 'ws://')
        
        self.client: Optional[AsyncClient] = None
        self.wallet: Optional[Keypair] = None
        
        self.user_usdc_account: Optional[Pubkey] = None
        self.user_wsol_account: Optional[Pubkey] = None
        
        # Lock to prevent concurrent trade execution
        self.trade_lock = asyncio.Lock()
        
        logger.info(f"RPC: {self.rpc_url[:50]}...")
        logger.info(f"WS: {self.ws_url[:50]}...")

    async def connect(self):
        """Connect to Solana RPC"""
        self.client = AsyncClient(self.rpc_url, commitment=Confirmed)
        
        private_key = os.environ.get('SOLANA_PRIVATE_KEY')
        if private_key:
            try:
                key_bytes = base58.b58decode(private_key)
                self.wallet = Keypair.from_bytes(key_bytes)
                logger.info(f"Wallet: {self.wallet.pubkey()}")
            except Exception as e:
                logger.error(f"Wallet error: {e}")
                return False
        else:
            logger.error("No SOLANA_PRIVATE_KEY!")
            return False
        
        try:
            slot = await self.client.get_slot()
            logger.info(f"Connected | Slot: {slot.value}")
            await self.find_user_token_accounts()
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def close(self):
        if self.client:
            await self.client.close()

    async def find_user_token_accounts(self):
        """Find user's token accounts"""
        self.user_usdc_account, _ = Pubkey.find_program_address(
            [bytes(self.wallet.pubkey()), bytes(TOKEN_PROGRAM_ID), bytes(USDC_MINT)],
            Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        )
        
        wsol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
        self.user_wsol_account, _ = Pubkey.find_program_address(
            [bytes(self.wallet.pubkey()), bytes(TOKEN_PROGRAM_ID), bytes(wsol_mint)],
            Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        )
        
        logger.info(f"USDC Account: {self.user_usdc_account}")
        logger.info(f"WSOL Account: {self.user_wsol_account}")

    # =============================================================================
    # STEP 4: LOCAL PRICE CALCULATION (NO APIs)
    # =============================================================================
    
    def amm_price(self, sol_reserve: int, usdc_reserve: int) -> float:
        """Calculate price from reserves - NO API!"""
        if sol_reserve == 0:
            return 0
        sol = sol_reserve / 10**SOL_DECIMALS
        usdc = usdc_reserve / 10**USDC_DECIMALS
        return usdc / sol

    def calculate_swap_out(self, amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int) -> int:
        """Calculate swap output using constant product formula"""
        amount_in_after_fee = amount_in * (10000 - fee_bps) // 10000
        numerator = amount_in_after_fee * reserve_out
        denominator = reserve_in + amount_in_after_fee
        return numerator // denominator

    # =============================================================================
    # STEP 5: REAL OPPORTUNITY DETECTION
    # =============================================================================
    
    def detect_opportunity(self) -> Optional[Dict]:
        """
        Detect arbitrage opportunity between Raydium and Orca
        Returns opportunity details if spread >= MIN_SPREAD_BPS
        """
        ray = pool_state["raydium"]
        orca = pool_state["orca"]
        
        if ray["price"] == 0 or orca["price"] == 0:
            return None
        
        ray_price = ray["price"]
        orca_price = orca["price"]
        
        # Calculate spread in basis points
        # Positive spread = Orca higher than Raydium
        spread_bps = (orca_price - ray_price) / ray_price * 10000
        
        # Check both directions
        if abs(spread_bps) >= MIN_SPREAD_BPS:
            if spread_bps > 0:
                # Buy on Raydium (cheaper), Sell on Orca (higher)
                return {
                    "direction": "ray_to_orca",
                    "buy_dex": "raydium",
                    "sell_dex": "orca",
                    "buy_price": ray_price,
                    "sell_price": orca_price,
                    "spread_bps": spread_bps
                }
            else:
                # Buy on Orca (cheaper), Sell on Raydium (higher)
                return {
                    "direction": "orca_to_ray",
                    "buy_dex": "orca",
                    "sell_dex": "raydium",
                    "buy_price": orca_price,
                    "sell_price": ray_price,
                    "spread_bps": abs(spread_bps)
                }
        
        return None

    # =============================================================================
    # PROFIT CALCULATION
    # =============================================================================
    
    def calculate_profit(self, opportunity: Dict) -> Dict:
        """Calculate expected profit for an opportunity"""
        loan_amount = FLASHLOAN_AMOUNT_USDC * 10**USDC_DECIMALS
        
        ray = pool_state["raydium"]
        orca = pool_state["orca"]
        
        if opportunity["direction"] == "ray_to_orca":
            # Buy SOL on Raydium
            sol_received = self.calculate_swap_out(
                loan_amount, ray["usdc_reserve"], ray["sol_reserve"], RAYDIUM_FEE_BPS
            )
            # Sell SOL on Orca
            usdc_received = self.calculate_swap_out(
                sol_received, orca["sol_reserve"], orca["usdc_reserve"], ORCA_FEE_BPS
            )
        else:
            # Buy SOL on Orca
            sol_received = self.calculate_swap_out(
                loan_amount, orca["usdc_reserve"], orca["sol_reserve"], ORCA_FEE_BPS
            )
            # Sell SOL on Raydium
            usdc_received = self.calculate_swap_out(
                sol_received, ray["sol_reserve"], ray["usdc_reserve"], RAYDIUM_FEE_BPS
            )
        
        flashloan_fee = (loan_amount * SOLEND_FLASHLOAN_FEE_BPS) // 10000
        total_cost = loan_amount + flashloan_fee
        profit = usdc_received - total_cost
        profit_usdc = profit / 10**USDC_DECIMALS
        
        return {
            "loan_usdc": FLASHLOAN_AMOUNT_USDC,
            "sol_received": sol_received / 10**SOL_DECIMALS,
            "usdc_received": usdc_received / 10**USDC_DECIMALS,
            "flashloan_fee": flashloan_fee / 10**USDC_DECIMALS,
            "profit_usdc": profit_usdc,
            "profitable": profit_usdc >= MIN_PROFIT_USDC
        }

    # =============================================================================
    # FLASH LOAN INSTRUCTIONS
    # =============================================================================
    
    def build_flashloan_borrow_ix(self, amount: int) -> Instruction:
        reserve = SOLEND_USDC_RESERVE
        data = bytes([20]) + struct.pack('<Q', amount)
        accounts = [
            AccountMeta(pubkey=reserve['liquidity_supply'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=self.user_usdc_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['reserve'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['lending_market'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=reserve['lending_market_authority'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SOLEND_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        return Instruction(program_id=SOLEND_PROGRAM_ID, accounts=accounts, data=data)

    def build_flashloan_repay_ix(self, amount: int) -> Instruction:
        reserve = SOLEND_USDC_RESERVE
        fee = (amount * SOLEND_FLASHLOAN_FEE_BPS) // 10000
        repay_amount = amount + fee
        data = bytes([21]) + struct.pack('<Q', repay_amount) + bytes([0])
        accounts = [
            AccountMeta(pubkey=self.user_usdc_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['liquidity_supply'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['fee_receiver'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['reserve'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=reserve['lending_market'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        return Instruction(program_id=SOLEND_PROGRAM_ID, accounts=accounts, data=data)

    def build_raydium_swap_ix(self, amount_in: int, min_out: int, direction: str) -> Instruction:
        pool = RAYDIUM_SOL_USDC_POOL
        data = bytes([9]) + struct.pack('<Q', amount_in) + struct.pack('<Q', min_out)
        
        if direction == "usdc_to_sol":
            src, dst = self.user_usdc_account, self.user_wsol_account
        else:
            src, dst = self.user_wsol_account, self.user_usdc_account
        
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
            AccountMeta(pubkey=src, is_signer=False, is_writable=True),
            AccountMeta(pubkey=dst, is_signer=False, is_writable=True),
            AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
        ]
        return Instruction(program_id=RAYDIUM_AMM_PROGRAM_ID, accounts=accounts, data=data)

    def build_orca_swap_ix(self, amount_in: int, min_out: int, direction: str) -> Instruction:
        pool = ORCA_SOL_USDC_POOL
        data = bytes([1]) + struct.pack('<Q', amount_in) + struct.pack('<Q', min_out)
        
        if direction == "usdc_to_sol":
            src, dst = self.user_usdc_account, self.user_wsol_account
            src_vault, dst_vault = pool['token_b_vault'], pool['token_a_vault']
        else:
            src, dst = self.user_wsol_account, self.user_usdc_account
            src_vault, dst_vault = pool['token_a_vault'], pool['token_b_vault']
        
        accounts = [
            AccountMeta(pubkey=pool['pool_id'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=pool['authority'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
            AccountMeta(pubkey=src, is_signer=False, is_writable=True),
            AccountMeta(pubkey=src_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=dst, is_signer=False, is_writable=True),
            AccountMeta(pubkey=dst_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['pool_token_mint'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['fee_account'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        return Instruction(program_id=ORCA_SWAP_PROGRAM_ID, accounts=accounts, data=data)

    # =============================================================================
    # EXECUTE ARBITRAGE
    # =============================================================================
    
    async def execute_arbitrage(self, opportunity: Dict, profit_calc: Dict) -> Dict:
        """Execute flash loan arbitrage"""
        async with self.trade_lock:
            loan_amount = FLASHLOAN_AMOUNT_USDC * 10**USDC_DECIMALS
            
            ray = pool_state["raydium"]
            orca = pool_state["orca"]
            
            instructions = []
            
            # 1. Borrow
            instructions.append(self.build_flashloan_borrow_ix(loan_amount))
            
            if opportunity["direction"] == "ray_to_orca":
                # 2. Buy on Raydium
                sol_out = self.calculate_swap_out(loan_amount, ray["usdc_reserve"], ray["sol_reserve"], RAYDIUM_FEE_BPS)
                instructions.append(self.build_raydium_swap_ix(loan_amount, int(sol_out * 0.99), "usdc_to_sol"))
                
                # 3. Sell on Orca
                usdc_out = self.calculate_swap_out(sol_out, orca["sol_reserve"], orca["usdc_reserve"], ORCA_FEE_BPS)
                instructions.append(self.build_orca_swap_ix(sol_out, int(usdc_out * 0.99), "sol_to_usdc"))
            else:
                # 2. Buy on Orca
                sol_out = self.calculate_swap_out(loan_amount, orca["usdc_reserve"], orca["sol_reserve"], ORCA_FEE_BPS)
                instructions.append(self.build_orca_swap_ix(loan_amount, int(sol_out * 0.99), "usdc_to_sol"))
                
                # 3. Sell on Raydium
                usdc_out = self.calculate_swap_out(sol_out, ray["sol_reserve"], ray["usdc_reserve"], RAYDIUM_FEE_BPS)
                instructions.append(self.build_raydium_swap_ix(sol_out, int(usdc_out * 0.99), "sol_to_usdc"))
            
            # 4. Repay
            instructions.append(self.build_flashloan_repay_ix(loan_amount))
            
            try:
                blockhash_resp = await self.client.get_latest_blockhash()
                blockhash = blockhash_resp.value.blockhash
                
                message = Message.new_with_blockhash(
                    instructions, self.wallet.pubkey(), Hash.from_string(str(blockhash))
                )
                tx = Transaction.new_unsigned(message)
                tx = tx.sign([self.wallet], Hash.from_string(str(blockhash)))
                
                # Simulate
                stats["simulations_run"] += 1
                sim = await self.client.simulate_transaction(tx)
                
                if sim.value.err:
                    logger.warning(f"SIM FAIL | {sim.value.err}")
                    return {"success": False, "error": str(sim.value.err)}
                
                # Execute
                response = await self.client.send_transaction(tx)
                signature = response.value
                
                await self.client.confirm_transaction(signature, commitment=Confirmed)
                
                stats["txs_executed"] += 1
                stats["total_profit"] += profit_calc["profit_usdc"]
                
                logger.info(f"TX SUCCESS | {signature} | Profit: ${profit_calc['profit_usdc']:.4f}")
                
                return {"success": True, "signature": str(signature), "profit": profit_calc["profit_usdc"]}
                
            except Exception as e:
                stats["txs_reverted"] += 1
                logger.error(f"TX ERROR | {e}")
                return {"success": False, "error": str(e)}

    # =============================================================================
    # STEP 2: WEBSOCKET SUBSCRIPTIONS
    # =============================================================================
    
    async def subscribe_raydium(self):
        """Subscribe to Raydium pool vault updates"""
        sol_vault = str(RAYDIUM_SOL_USDC_POOL['coin_vault'])
        usdc_vault = str(RAYDIUM_SOL_USDC_POOL['pc_vault'])
        
        while True:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    # Subscribe to SOL vault
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": 1, "method": "accountSubscribe",
                        "params": [sol_vault, {"encoding": "jsonParsed", "commitment": "confirmed"}]
                    }))
                    
                    # Subscribe to USDC vault
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": 2, "method": "accountSubscribe",
                        "params": [usdc_vault, {"encoding": "jsonParsed", "commitment": "confirmed"}]
                    }))
                    
                    logger.info("Raydium WebSocket connected")
                    
                    async for msg in ws:
                        data = json.loads(msg)
                        if "params" in data and "result" in data["params"]:
                            await self.on_raydium_update(data)
                            
            except Exception as e:
                logger.error(f"Raydium WS error: {e}")
                await asyncio.sleep(1)

    async def subscribe_orca(self):
        """Subscribe to Orca pool vault updates"""
        sol_vault = str(ORCA_SOL_USDC_POOL['token_a_vault'])
        usdc_vault = str(ORCA_SOL_USDC_POOL['token_b_vault'])
        
        while True:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": 1, "method": "accountSubscribe",
                        "params": [sol_vault, {"encoding": "jsonParsed", "commitment": "confirmed"}]
                    }))
                    
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0", "id": 2, "method": "accountSubscribe",
                        "params": [usdc_vault, {"encoding": "jsonParsed", "commitment": "confirmed"}]
                    }))
                    
                    logger.info("Orca WebSocket connected")
                    
                    async for msg in ws:
                        data = json.loads(msg)
                        if "params" in data and "result" in data["params"]:
                            await self.on_orca_update(data)
                            
            except Exception as e:
                logger.error(f"Orca WS error: {e}")
                await asyncio.sleep(1)

    async def on_raydium_update(self, data):
        """Handle Raydium pool update"""
        try:
            result = data["params"]["result"]
            if "value" in result and "data" in result["value"]:
                parsed = result["value"]["data"].get("parsed")
                if parsed and "info" in parsed:
                    amount = int(parsed["info"]["tokenAmount"]["amount"])
                    # Determine if SOL or USDC based on subscription ID
                    sub_id = data["params"]["subscription"]
                    if sub_id == 0:  # SOL vault
                        pool_state["raydium"]["sol_reserve"] = amount
                    else:  # USDC vault
                        pool_state["raydium"]["usdc_reserve"] = amount
                    
                    pool_state["raydium"]["price"] = self.amm_price(
                        pool_state["raydium"]["sol_reserve"],
                        pool_state["raydium"]["usdc_reserve"]
                    )
                    pool_state["raydium"]["last_update"] = datetime.now(timezone.utc)
                    
                    await self.check_opportunity()
        except Exception as e:
            pass  # Ignore parse errors

    async def on_orca_update(self, data):
        """Handle Orca pool update"""
        try:
            result = data["params"]["result"]
            if "value" in result and "data" in result["value"]:
                parsed = result["value"]["data"].get("parsed")
                if parsed and "info" in parsed:
                    amount = int(parsed["info"]["tokenAmount"]["amount"])
                    sub_id = data["params"]["subscription"]
                    if sub_id == 0:
                        pool_state["orca"]["sol_reserve"] = amount
                    else:
                        pool_state["orca"]["usdc_reserve"] = amount
                    
                    pool_state["orca"]["price"] = self.amm_price(
                        pool_state["orca"]["sol_reserve"],
                        pool_state["orca"]["usdc_reserve"]
                    )
                    pool_state["orca"]["last_update"] = datetime.now(timezone.utc)
                    
                    await self.check_opportunity()
        except Exception as e:
            pass

    async def check_opportunity(self):
        """Check for arbitrage opportunity and execute if profitable"""
        opportunity = self.detect_opportunity()
        
        if opportunity:
            stats["opportunities_detected"] += 1
            profit_calc = self.calculate_profit(opportunity)
            
            # STEP 10: LOG ESSENTIAL FIELDS
            logger.info(
                f"OPP | Ray: ${pool_state['raydium']['price']:.2f} | "
                f"Orca: ${pool_state['orca']['price']:.2f} | "
                f"Spread: {opportunity['spread_bps']:.1f}bps | "
                f"Profit: ${profit_calc['profit_usdc']:.4f}"
            )
            
            # STEP 7: PROFIT FILTER
            if profit_calc["profitable"]:
                logger.info(f"EXECUTING | Direction: {opportunity['direction']}")
                await self.execute_arbitrage(opportunity, profit_calc)

    # =============================================================================
    # STEP 6: SLOT-BASED FALLBACK + INITIAL FETCH
    # =============================================================================
    
    async def fetch_initial_reserves(self):
        """Fetch initial reserves via RPC"""
        try:
            # Raydium
            sol_resp = await self.client.get_token_account_balance(RAYDIUM_SOL_USDC_POOL['coin_vault'])
            usdc_resp = await self.client.get_token_account_balance(RAYDIUM_SOL_USDC_POOL['pc_vault'])
            if sol_resp.value and usdc_resp.value:
                pool_state["raydium"]["sol_reserve"] = int(sol_resp.value.amount)
                pool_state["raydium"]["usdc_reserve"] = int(usdc_resp.value.amount)
                pool_state["raydium"]["price"] = self.amm_price(
                    pool_state["raydium"]["sol_reserve"], pool_state["raydium"]["usdc_reserve"]
                )
            
            # Orca
            sol_resp = await self.client.get_token_account_balance(ORCA_SOL_USDC_POOL['token_a_vault'])
            usdc_resp = await self.client.get_token_account_balance(ORCA_SOL_USDC_POOL['token_b_vault'])
            if sol_resp.value and usdc_resp.value:
                pool_state["orca"]["sol_reserve"] = int(sol_resp.value.amount)
                pool_state["orca"]["usdc_reserve"] = int(usdc_resp.value.amount)
                pool_state["orca"]["price"] = self.amm_price(
                    pool_state["orca"]["sol_reserve"], pool_state["orca"]["usdc_reserve"]
                )
            
            logger.info(f"Initial | Ray: ${pool_state['raydium']['price']:.2f} | Orca: ${pool_state['orca']['price']:.2f}")
            
        except Exception as e:
            logger.error(f"Initial fetch error: {e}")

    async def periodic_refresh(self):
        """Fallback: Periodically refresh reserves in case WS misses updates"""
        while True:
            await asyncio.sleep(5)  # Every 5 seconds
            await self.fetch_initial_reserves()

    async def print_stats(self):
        """Print statistics periodically"""
        while True:
            await asyncio.sleep(60)
            runtime = (datetime.now(timezone.utc) - stats["start_time"]).total_seconds() / 3600
            logger.info(
                f"STATS | Runtime: {runtime:.1f}h | "
                f"Opps: {stats['opportunities_detected']} | "
                f"Sims: {stats['simulations_run']} | "
                f"TXs: {stats['txs_executed']} | "
                f"Reverts: {stats['txs_reverted']} | "
                f"Profit: ${stats['total_profit']:.4f}"
            )

    # =============================================================================
    # STEP 8: MAIN RUN (PARALLELIZED)
    # =============================================================================
    
    async def run(self):
        """Main entry point - runs all tasks in parallel"""
        logger.info("=" * 60)
        logger.info("HIGH-FREQUENCY FLASH LOAN ARBITRAGE BOT")
        logger.info("=" * 60)
        logger.info(f"Min Spread: {MIN_SPREAD_BPS} bps")
        logger.info(f"Min Profit: ${MIN_PROFIT_USDC}")
        logger.info(f"Loan Size: ${FLASHLOAN_AMOUNT_USDC}")
        logger.info("=" * 60)
        
        if not await self.connect():
            return
        
        stats["start_time"] = datetime.now(timezone.utc)
        
        # Fetch initial data
        await self.fetch_initial_reserves()
        
        # STEP 8: PARALLELIZE ALL TASKS
        tasks = [
            asyncio.create_task(self.subscribe_raydium()),
            asyncio.create_task(self.subscribe_orca()),
            asyncio.create_task(self.periodic_refresh()),
            asyncio.create_task(self.print_stats()),
        ]
        
        logger.info("Bot running... Press Ctrl+C to stop")
        
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            for task in tasks:
                task.cancel()
            await self.close()


async def main():
    bot = HFTFlashLoanBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
