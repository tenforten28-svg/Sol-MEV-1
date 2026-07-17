"""
HFT FLASH LOAN BOT v3 - MULTI-DEX
=================================
- Raydium (AMM) - Direct on-chain
- Orca (AMM) - Direct on-chain  
- Jupiter (Aggregator) - API price reference
- 3x more arbitrage paths
"""

import asyncio
import os
import struct
import logging
import aiohttp
from typing import Dict, Optional
from datetime import datetime, timezone
from dotenv import load_dotenv

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger('hft_v3')

# Configuration
MIN_SPREAD_BPS = 6  # Minimum spread to consider (6 bps = 0.06%)
MIN_PROFIT_USDC = 0.10  # Minimum profit after fees
FLASHLOAN_AMOUNT_USDC = 1000
SOLEND_FLASHLOAN_FEE_BPS = 30
RAYDIUM_FEE_BPS = 25
ORCA_FEE_BPS = 30
SOL_DECIMALS = 9
USDC_DECIMALS = 6

# Token addresses for Jupiter API
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT_STR = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Program IDs
SOLEND_PROGRAM_ID = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo")
RAYDIUM_AMM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
ORCA_SWAP_PROGRAM_ID = Pubkey.from_string("9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

# Solend Reserve
SOLEND_USDC_RESERVE = {
    'reserve': Pubkey.from_string("BgxfHJDzm44T7XG68MYKx7YisTjZu73tVovyZSjJMpmw"),
    'liquidity_supply': Pubkey.from_string("8SheGtsopRUDzdiD6v6BR9a6bqZ9QwywYQY99Fp5meNf"),
    'fee_receiver': Pubkey.from_string("5Gdxn4yquneifE6uk9tK8XSXR5RGBdJGSHsZfZpY2ZtE"),
    'lending_market': Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"),
    'lending_market_authority': Pubkey.from_string("DdZR6zRFiUt4S5mg7AV1uKB2z1f1WzcNYCaTEEWPAuby"),
}

# Raydium Pool
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

# Orca Pool
ORCA_SOL_USDC_POOL = {
    'pool_id': Pubkey.from_string("EGZ7tiLeH62TPV1gL8WwbXGzEPa9zmcpVnnkPKKnrE2U"),
    'authority': Pubkey.from_string("JU8kmKzDHF9sXWsnoznaFDFezLsE5uomX2JkRMbmsQP"),
    'token_a_vault': Pubkey.from_string("ANP74VNsHwSrq9uUSjiSNyNWvf6ZPrKTmE4gHoNd13Lg"),
    'token_b_vault': Pubkey.from_string("75HgnSvXbWKZBpZHveX68ZzAhDqMzNDS29X6BGLtxMo1"),
    'pool_token_mint': Pubkey.from_string("APDFRM3HMr8CAGXwKHiu2f5ePSpaiEJhaURwhsRrUUt9"),
    'fee_account': Pubkey.from_string("8JnSiuvQq3BVuCU3n4DrSTw9chBSPvEMswrhtifVkr1o"),
}

# Price cache - 3 sources: Raydium, Orca, Market (aggregator)
pool_state = {
    "raydium": {"sol_reserve": 0, "usdc_reserve": 0, "price": 0.0},
    "orca": {"sol_reserve": 0, "usdc_reserve": 0, "price": 0.0},
    "market": {"price": 0.0}  # Aggregator/market price via API (CoinGecko)
}

stats = {
    "opportunities_detected": 0,
    "ray_orca_opps": 0,
    "ray_mkt_opps": 0,
    "orca_mkt_opps": 0,
    "simulations_run": 0,
    "txs_executed": 0,
    "txs_reverted": 0,
    "total_profit": 0.0,
    "start_time": None
}


class HFTFlashLoanBotV3:
    
    def __init__(self):
        # Use SOLANA_RPC_URL from env, fallback to public mainnet
        self.rpc_url = os.environ.get('SOLANA_RPC_URL')
        
        # Check if it's devnet (wrong network for mainnet pools)
        if self.rpc_url and 'devnet' in self.rpc_url.lower():
            logger.warning("Devnet RPC detected! Using public mainnet RPC instead.")
            logger.warning("For better performance, set SOLANA_RPC_URL to a mainnet QuickNode URL.")
            self.rpc_url = "https://api.mainnet-beta.solana.com"
        elif not self.rpc_url:
            logger.warning("No RPC URL set. Using public mainnet RPC (rate limited).")
            self.rpc_url = "https://api.mainnet-beta.solana.com"
        
        self.client = None
        self.wallet = None
        self.user_usdc_account = None
        self.user_wsol_account = None
        self.is_executing = False
        self.http_session = None  # For Jupiter API calls
        
        logger.info(f"RPC: {self.rpc_url[:50]}...")

    async def connect(self):
        self.client = AsyncClient(self.rpc_url, commitment=Confirmed)
        self.http_session = aiohttp.ClientSession()  # For market price API
        
        private_key = os.environ.get('SOLANA_PRIVATE_KEY')
        if private_key:
            try:
                key_bytes = base58.b58decode(private_key)
                self.wallet = Keypair.from_bytes(key_bytes)
                logger.info(f"Wallet: {self.wallet.pubkey()}")
            except Exception as e:
                logger.error(f"Wallet error: {e}")
                await self.close()
                return False
        else:
            logger.error("No SOLANA_PRIVATE_KEY!")
            await self.close()
            return False
        
        try:
            slot = await self.client.get_slot()
            logger.info(f"Connected | Slot: {slot.value}")
            await self.find_user_token_accounts()
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            await self.close()
            return False

    async def close(self):
        if self.client:
            await self.client.close()
        if self.http_session:
            await self.http_session.close()

    async def find_user_token_accounts(self):
        self.user_usdc_account, _ = Pubkey.find_program_address(
            [bytes(self.wallet.pubkey()), bytes(TOKEN_PROGRAM_ID), bytes(USDC_MINT)],
            Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        )
        wsol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
        self.user_wsol_account, _ = Pubkey.find_program_address(
            [bytes(self.wallet.pubkey()), bytes(TOKEN_PROGRAM_ID), bytes(wsol_mint)],
            Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        )
        logger.info(f"USDC: {self.user_usdc_account}")
        logger.info(f"WSOL: {self.user_wsol_account}")

    def amm_price(self, sol_reserve, usdc_reserve):
        if sol_reserve == 0:
            return 0
        return (usdc_reserve / 10**USDC_DECIMALS) / (sol_reserve / 10**SOL_DECIMALS)

    def calculate_swap_out(self, amount_in, reserve_in, reserve_out, fee_bps):
        if reserve_in == 0 or reserve_out == 0:
            return 0
        amount_in_after_fee = amount_in * (10000 - fee_bps) // 10000
        numerator = amount_in_after_fee * reserve_out
        denominator = reserve_in + amount_in_after_fee
        return numerator // denominator if denominator > 0 else 0

    def detect_all_opportunities(self):
        """Detect opportunities across all 3 price sources"""
        opportunities = []
        
        ray_p = pool_state["raydium"]["price"]
        orca_p = pool_state["orca"]["price"]
        jup_p = pool_state["market"]["price"]
        
        if ray_p <= 0 or orca_p <= 0:
            return opportunities
        
        # 1. Raydium <-> Orca (both executable)
        spread = ((orca_p - ray_p) / ray_p) * 10000 if ray_p > 0 else 0
        if abs(spread) >= MIN_SPREAD_BPS:
            if spread > 0:
                opportunities.append({
                    "pair": "ray_orca",
                    "direction": "ray_to_orca",
                    "buy_dex": "raydium",
                    "sell_dex": "orca",
                    "buy_price": ray_p,
                    "sell_price": orca_p,
                    "spread_bps": spread,
                    "executable": True
                })
            else:
                opportunities.append({
                    "pair": "ray_orca",
                    "direction": "orca_to_ray",
                    "buy_dex": "orca",
                    "sell_dex": "raydium",
                    "buy_price": orca_p,
                    "sell_price": ray_p,
                    "spread_bps": abs(spread),
                    "executable": True
                })
        
        # 2. Raydium <-> Jupiter (price reference - shows market opportunity)
        if jup_p > 0:
            spread = ((jup_p - ray_p) / ray_p) * 10000
            if abs(spread) >= MIN_SPREAD_BPS:
                opportunities.append({
                    "pair": "ray_market",
                    "direction": "reference_only",
                    "buy_dex": "raydium" if spread > 0 else "market",
                    "sell_dex": "market" if spread > 0 else "raydium",
                    "buy_price": ray_p if spread > 0 else jup_p,
                    "sell_price": jup_p if spread > 0 else ray_p,
                    "spread_bps": abs(spread),
                    "executable": False  # Jupiter is aggregator, not direct swap
                })
        
        # 3. Orca <-> Jupiter (price reference)
        if jup_p > 0:
            spread = ((jup_p - orca_p) / orca_p) * 10000
            if abs(spread) >= MIN_SPREAD_BPS:
                opportunities.append({
                    "pair": "orca_market",
                    "direction": "reference_only",
                    "buy_dex": "orca" if spread > 0 else "market",
                    "sell_dex": "market" if spread > 0 else "orca",
                    "buy_price": orca_p if spread > 0 else jup_p,
                    "sell_price": jup_p if spread > 0 else orca_p,
                    "spread_bps": abs(spread),
                    "executable": False
                })
        
        return opportunities

    def calculate_profit(self, opportunity):
        """Calculate profit for Raydium <-> Orca opportunities only"""
        if not opportunity.get("executable", True):
            return {"profit_usdc": 0, "profitable": False, "note": "Price reference only"}
        
        loan = FLASHLOAN_AMOUNT_USDC * 10**USDC_DECIMALS
        ray = pool_state["raydium"]
        orca = pool_state["orca"]
        
        if opportunity["direction"] == "ray_to_orca":
            sol_out = self.calculate_swap_out(loan, ray["usdc_reserve"], ray["sol_reserve"], RAYDIUM_FEE_BPS)
            usdc_out = self.calculate_swap_out(sol_out, orca["sol_reserve"], orca["usdc_reserve"], ORCA_FEE_BPS)
        elif opportunity["direction"] == "orca_to_ray":
            sol_out = self.calculate_swap_out(loan, orca["usdc_reserve"], orca["sol_reserve"], ORCA_FEE_BPS)
            usdc_out = self.calculate_swap_out(sol_out, ray["sol_reserve"], ray["usdc_reserve"], RAYDIUM_FEE_BPS)
        else:
            return {"profit_usdc": 0, "profitable": False}
        
        fee = (loan * SOLEND_FLASHLOAN_FEE_BPS) // 10000
        profit = (usdc_out - loan - fee) / 10**USDC_DECIMALS
        return {"profit_usdc": profit, "profitable": profit >= MIN_PROFIT_USDC}

    # Instruction builders (same as v2)
    def build_flashloan_borrow_ix(self, amount):
        r = SOLEND_USDC_RESERVE
        data = bytes([20]) + struct.pack('<Q', amount)
        accounts = [
            AccountMeta(pubkey=r['liquidity_supply'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=self.user_usdc_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['reserve'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['lending_market'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=r['lending_market_authority'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SOLEND_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        return Instruction(program_id=SOLEND_PROGRAM_ID, accounts=accounts, data=data)

    def build_flashloan_repay_ix(self, amount):
        r = SOLEND_USDC_RESERVE
        fee = (amount * SOLEND_FLASHLOAN_FEE_BPS) // 10000
        data = bytes([21]) + struct.pack('<Q', amount + fee) + bytes([0])
        accounts = [
            AccountMeta(pubkey=self.user_usdc_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['liquidity_supply'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['fee_receiver'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['reserve'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['lending_market'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        return Instruction(program_id=SOLEND_PROGRAM_ID, accounts=accounts, data=data)

    def build_raydium_swap_ix(self, amount_in, min_out, direction):
        p = RAYDIUM_SOL_USDC_POOL
        data = bytes([9]) + struct.pack('<Q', amount_in) + struct.pack('<Q', min_out)
        src = self.user_usdc_account if direction == "usdc_to_sol" else self.user_wsol_account
        dst = self.user_wsol_account if direction == "usdc_to_sol" else self.user_usdc_account
        accounts = [
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=p['pool_id'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['authority'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=p['open_orders'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['target_orders'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['coin_vault'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['pc_vault'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['serum_program'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=p['serum_market'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['serum_bids'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['serum_asks'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['serum_event_queue'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['serum_coin_vault'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['serum_pc_vault'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['serum_vault_signer'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=src, is_signer=False, is_writable=True),
            AccountMeta(pubkey=dst, is_signer=False, is_writable=True),
            AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
        ]
        return Instruction(program_id=RAYDIUM_AMM_PROGRAM_ID, accounts=accounts, data=data)

    def build_orca_swap_ix(self, amount_in, min_out, direction):
        p = ORCA_SOL_USDC_POOL
        data = bytes([1]) + struct.pack('<Q', amount_in) + struct.pack('<Q', min_out)
        if direction == "usdc_to_sol":
            src, dst = self.user_usdc_account, self.user_wsol_account
            src_v, dst_v = p['token_b_vault'], p['token_a_vault']
        else:
            src, dst = self.user_wsol_account, self.user_usdc_account
            src_v, dst_v = p['token_a_vault'], p['token_b_vault']
        accounts = [
            AccountMeta(pubkey=p['pool_id'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=p['authority'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
            AccountMeta(pubkey=src, is_signer=False, is_writable=True),
            AccountMeta(pubkey=src_v, is_signer=False, is_writable=True),
            AccountMeta(pubkey=dst, is_signer=False, is_writable=True),
            AccountMeta(pubkey=dst_v, is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['pool_token_mint'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=p['fee_account'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        return Instruction(program_id=ORCA_SWAP_PROGRAM_ID, accounts=accounts, data=data)

    async def execute_arbitrage(self, opportunity, profit_calc):
        if self.is_executing or not opportunity.get("executable", True):
            return {"success": False, "error": "Cannot execute"}
        
        self.is_executing = True
        try:
            loan = FLASHLOAN_AMOUNT_USDC * 10**USDC_DECIMALS
            ray = pool_state["raydium"]
            orca = pool_state["orca"]
            
            ixs = [self.build_flashloan_borrow_ix(loan)]
            
            if opportunity["direction"] == "ray_to_orca":
                sol_out = self.calculate_swap_out(loan, ray["usdc_reserve"], ray["sol_reserve"], RAYDIUM_FEE_BPS)
                ixs.append(self.build_raydium_swap_ix(loan, int(sol_out * 0.98), "usdc_to_sol"))
                usdc_out = self.calculate_swap_out(sol_out, orca["sol_reserve"], orca["usdc_reserve"], ORCA_FEE_BPS)
                ixs.append(self.build_orca_swap_ix(sol_out, int(usdc_out * 0.98), "sol_to_usdc"))
            else:
                sol_out = self.calculate_swap_out(loan, orca["usdc_reserve"], orca["sol_reserve"], ORCA_FEE_BPS)
                ixs.append(self.build_orca_swap_ix(loan, int(sol_out * 0.98), "usdc_to_sol"))
                usdc_out = self.calculate_swap_out(sol_out, ray["sol_reserve"], ray["usdc_reserve"], RAYDIUM_FEE_BPS)
                ixs.append(self.build_raydium_swap_ix(sol_out, int(usdc_out * 0.98), "sol_to_usdc"))
            
            ixs.append(self.build_flashloan_repay_ix(loan))
            
            bh_resp = await self.client.get_latest_blockhash()
            bh = bh_resp.value.blockhash
            
            msg = Message.new_with_blockhash(ixs, self.wallet.pubkey(), Hash.from_string(str(bh)))
            tx = Transaction.new_unsigned(msg)
            tx = tx.sign([self.wallet], Hash.from_string(str(bh)))
            
            stats["simulations_run"] += 1
            sim = await self.client.simulate_transaction(tx)
            
            if sim.value.err:
                logger.warning(f"SIM FAIL | {sim.value.err}")
                return {"success": False}
            
            logger.info("SIM PASS | Sending...")
            resp = await self.client.send_transaction(tx)
            sig = resp.value
            
            await self.client.confirm_transaction(sig, commitment=Confirmed)
            stats["txs_executed"] += 1
            stats["total_profit"] += profit_calc["profit_usdc"]
            
            logger.info(f"TX OK | {sig} | +${profit_calc['profit_usdc']:.4f}")
            return {"success": True}
            
        except Exception as e:
            stats["txs_reverted"] += 1
            logger.error(f"TX ERR | {e}")
            return {"success": False}
        finally:
            self.is_executing = False

    async def fetch_market_price(self):
        """Fetch SOL/USDC price from aggregator APIs"""
        try:
            # Try CoinGecko first (free, no auth required)
            url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            async with self.http_session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "solana" in data and "usd" in data["solana"]:
                        price = float(data["solana"]["usd"])
                        pool_state["market"]["price"] = price
                        return True
        except Exception as e:
            logger.debug(f"CoinGecko API error: {e}")
        return False

    async def fetch_reserves(self):
        """Fetch prices from all 3 sources"""
        try:
            # Raydium AMM vaults (on-chain)
            r1 = await self.client.get_token_account_balance(RAYDIUM_SOL_USDC_POOL['coin_vault'])
            r2 = await self.client.get_token_account_balance(RAYDIUM_SOL_USDC_POOL['pc_vault'])
            if r1.value and r2.value:
                pool_state["raydium"]["sol_reserve"] = int(r1.value.amount)
                pool_state["raydium"]["usdc_reserve"] = int(r2.value.amount)
                pool_state["raydium"]["price"] = self.amm_price(
                    pool_state["raydium"]["sol_reserve"],
                    pool_state["raydium"]["usdc_reserve"]
                )
            
            # Orca AMM vaults (on-chain)
            o1 = await self.client.get_token_account_balance(ORCA_SOL_USDC_POOL['token_a_vault'])
            o2 = await self.client.get_token_account_balance(ORCA_SOL_USDC_POOL['token_b_vault'])
            if o1.value and o2.value:
                pool_state["orca"]["sol_reserve"] = int(o1.value.amount)
                pool_state["orca"]["usdc_reserve"] = int(o2.value.amount)
                pool_state["orca"]["price"] = self.amm_price(
                    pool_state["orca"]["sol_reserve"],
                    pool_state["orca"]["usdc_reserve"]
                )
            
            # Market aggregator price (API)
            await self.fetch_market_price()
            
            return True
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            return False

    async def check_and_execute(self):
        """Check all opportunities and execute if profitable"""
        opportunities = self.detect_all_opportunities()
        
        for opp in opportunities:
            stats["opportunities_detected"] += 1
            
            if opp["pair"] == "ray_orca":
                stats["ray_orca_opps"] += 1
            elif opp["pair"] == "ray_market":
                stats["ray_mkt_opps"] += 1
            elif opp["pair"] == "orca_market":
                stats["orca_mkt_opps"] += 1
            
            profit = self.calculate_profit(opp)
            
            # Log all opportunities
            executable = "EXEC" if opp.get("executable", True) else "REF"
            logger.info(
                f"[{executable}] {opp['pair']} | "
                f"Buy: {opp['buy_dex']}@${opp['buy_price']:.2f} | "
                f"Sell: {opp['sell_dex']}@${opp['sell_price']:.2f} | "
                f"Spread: {opp['spread_bps']:.1f}bps | "
                f"Profit: ${profit['profit_usdc']:.4f}"
            )
            
            # Only execute Ray<->Orca trades
            if opp["pair"] == "ray_orca" and profit["profitable"] and not self.is_executing:
                logger.info(f"EXECUTING | {opp['direction']}")
                await self.execute_arbitrage(opp, profit)

    async def monitor_loop(self):
        scan = 0
        while True:
            try:
                await self.fetch_reserves()
                scan += 1
                
                await self.check_and_execute()
                
                if scan % 60 == 0:
                    ray_p = pool_state["raydium"]["price"]
                    orca_p = pool_state["orca"]["price"]
                    mkt_p = pool_state["market"]["price"]
                    logger.info(f"Scan #{scan} | Ray: ${ray_p:.2f} | Orca: ${orca_p:.2f} | Mkt: ${mkt_p:.2f}")
                
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Loop error: {e}")
                await asyncio.sleep(1)

    async def print_stats(self):
        while True:
            await asyncio.sleep(60)
            runtime = (datetime.now(timezone.utc) - stats["start_time"]).total_seconds() / 3600
            logger.info(
                f"STATS | {runtime:.1f}h | "
                f"Opps: {stats['opportunities_detected']} "
                f"(R-O:{stats['ray_orca_opps']} R-M:{stats['ray_mkt_opps']} O-M:{stats['orca_mkt_opps']}) | "
                f"Sims: {stats['simulations_run']} | "
                f"TXs: {stats['txs_executed']} | "
                f"Profit: ${stats['total_profit']:.4f}"
            )

    async def run(self):
        logger.info("=" * 70)
        logger.info("HFT FLASH LOAN BOT v3 - MULTI-DEX + MARKET AGGREGATOR")
        logger.info("=" * 70)
        logger.info("Price Sources: Raydium (on-chain) | Orca (on-chain) | Market (CoinGecko)")
        logger.info(f"Min Spread: {MIN_SPREAD_BPS} bps | Min Profit: ${MIN_PROFIT_USDC} | Loan: ${FLASHLOAN_AMOUNT_USDC}")
        logger.info("=" * 70)
        
        if not await self.connect():
            return
        
        stats["start_time"] = datetime.now(timezone.utc)
        
        await self.fetch_reserves()
        logger.info(
            f"Initial | Ray: ${pool_state['raydium']['price']:.2f} | "
            f"Orca: ${pool_state['orca']['price']:.2f} | "
            f"Mkt: ${pool_state['market']['price']:.2f}"
        )
        
        logger.info("Bot running... Ctrl+C to stop")
        
        tasks = [
            asyncio.create_task(self.monitor_loop()),
            asyncio.create_task(self.print_stats()),
        ]
        
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("Stopping...")
        finally:
            for t in tasks:
                t.cancel()
            await self.close()


async def main():
    bot = HFTFlashLoanBotV3()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
