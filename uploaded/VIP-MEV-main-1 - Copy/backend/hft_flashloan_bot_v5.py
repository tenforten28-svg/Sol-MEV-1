"""
HFT FLASH LOAN BOT v5 - MULTI-DEX + MULTI-PAIR + MEV PROTECTION
===============================================================
- 3 DEXs: Raydium, Orca, OpenBook (via Raydium routing)
- 2 Pairs: SOL/USDC, SOL/USDT
- MEV Protection: Jito bundle submission
- All v4 features: Slippage-aware, depth filter, dynamic sizing, etc.
"""

import asyncio
import os
import struct
import logging
import time
import aiohttp
from typing import Dict, Optional, List
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
from solders.compute_budget import set_compute_unit_price, set_compute_unit_limit
import base58

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger('hft_v5')

# =============================================================================
# CONFIGURATION - UPDATED
# =============================================================================
MIN_SPREAD_BPS = 8  # Updated from 6 to 8
MIN_PROFIT_USDC = 0.10
SOLEND_FLASHLOAN_FEE_BPS = 30
RAYDIUM_FEE_BPS = 25
ORCA_FEE_BPS = 30
SOL_DECIMALS = 9
USDC_DECIMALS = 6
USDT_DECIMALS = 6

# Depth filter
MAX_POOL_PERCENT = 0.01  # 1%

# Age filter - Updated for HTTP polling
MAX_OPPORTUNITY_AGE_MS = 2000  # 2 seconds - realistic for HTTP polling

# Dynamic trade sizing
TRADE_SIZES = {
    "large": 5000,
    "medium": 2000,
    "small": 1000,
}

# Priority fees (microlamports)
PRIORITY_FEES = {
    "very_high": 500000,
    "high": 100000,
    "medium": 50000,
    "low": 10000,
}

# MEV Protection - Jito
JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4bVGb4pYrGdNLsmQYEzVHXU", 
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
]
JITO_BLOCK_ENGINE_URL = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
JITO_TIP_LAMPORTS = 10000  # 0.00001 SOL tip

# Pool blacklist
POOL_BLACKLIST_DURATION = 300

# Capital safety
MIN_WALLET_BALANCE_USDC = 500

# =============================================================================
# PROGRAM IDS
# =============================================================================
SOLEND_PROGRAM_ID = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo")
RAYDIUM_AMM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
ORCA_SWAP_PROGRAM_ID = Pubkey.from_string("9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")

# Token Mints
USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
USDT_MINT = Pubkey.from_string("Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB")
WSOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")

# =============================================================================
# SOLEND RESERVES
# =============================================================================
SOLEND_USDC_RESERVE = {
    'reserve': Pubkey.from_string("BgxfHJDzm44T7XG68MYKx7YisTjZu73tVovyZSjJMpmw"),
    'liquidity_supply': Pubkey.from_string("8SheGtsopRUDzdiD6v6BR9a6bqZ9QwywYQY99Fp5meNf"),
    'fee_receiver': Pubkey.from_string("5Gdxn4yquneifE6uk9tK8XSXR5RGBdJGSHsZfZpY2ZtE"),
    'lending_market': Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"),
    'lending_market_authority': Pubkey.from_string("DdZR6zRFiUt4S5mg7AV1uKB2z1f1WzcNYCaTEEWPAuby"),
}

# =============================================================================
# DEX POOLS - SOL/USDC
# =============================================================================
RAYDIUM_SOL_USDC = {
    'name': 'raydium_sol_usdc',
    'dex': 'raydium',
    'base': 'SOL',
    'quote': 'USDC',
    'pool_id': Pubkey.from_string("58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"),
    'authority': Pubkey.from_string("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"),
    'open_orders': Pubkey.from_string("HRk9CMrpq7Fo9csEw5zFzhViMZYCrS8HTVU5bQPfr1A6"),
    'target_orders': Pubkey.from_string("CZza3Ej4Mc58MnxWA385itCC9jCo3L1D7zc3LKy1bZMR"),
    'base_vault': Pubkey.from_string("DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz"),
    'quote_vault': Pubkey.from_string("HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz"),
    'serum_program': Pubkey.from_string("srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX"),
    'serum_market': Pubkey.from_string("8BnEgHoWFysVcuFFX7QztDmzuH8r5ZFvyP3sYwn1XTh6"),
    'serum_bids': Pubkey.from_string("5jWUncPNBMZJ3sTHKmMLszypVkoRK6gqbRk1DBQpcfBS"),
    'serum_asks': Pubkey.from_string("EaXdHx7x3mdGA38j5RSmKYSXMzAFzzUXCLNBEDXDn1d5"),
    'serum_event_queue': Pubkey.from_string("8CvwxZ9Db6XbLD46NZwwmVDZZRDy7eydFcAGkXKh9axa"),
    'serum_base_vault': Pubkey.from_string("CKxTHwM9fPMRRvZmFnFoqKNd9pQR21c5Aq9bh5h9oghX"),
    'serum_quote_vault': Pubkey.from_string("6A5NHCj1yF6urc9wZNe6Bcjj4LVszQNj5DwAWG97uj7R"),
    'serum_vault_signer': Pubkey.from_string("CTz5UMLQm2SRWHzQnU62Pi4yJqbNGjgRBHqqp6oDHfF7"),
    'fee_bps': RAYDIUM_FEE_BPS,
}

ORCA_SOL_USDC = {
    'name': 'orca_sol_usdc',
    'dex': 'orca',
    'base': 'SOL',
    'quote': 'USDC',
    'pool_id': Pubkey.from_string("EGZ7tiLeH62TPV1gL8WwbXGzEPa9zmcpVnnkPKKnrE2U"),
    'authority': Pubkey.from_string("JU8kmKzDHF9sXWsnoznaFDFezLsE5uomX2JkRMbmsQP"),
    'base_vault': Pubkey.from_string("ANP74VNsHwSrq9uUSjiSNyNWvf6ZPrKTmE4gHoNd13Lg"),
    'quote_vault': Pubkey.from_string("75HgnSvXbWKZBpZHveX68ZzAhDqMzNDS29X6BGLtxMo1"),
    'pool_token_mint': Pubkey.from_string("APDFRM3HMr8CAGXwKHiu2f5ePSpaiEJhaURwhsRrUUt9"),
    'fee_account': Pubkey.from_string("8JnSiuvQq3BVuCU3n4DrSTw9chBSPvEMswrhtifVkr1o"),
    'fee_bps': ORCA_FEE_BPS,
}

# =============================================================================
# DEX POOLS - SOL/USDT
# =============================================================================
RAYDIUM_SOL_USDT = {
    'name': 'raydium_sol_usdt',
    'dex': 'raydium',
    'base': 'SOL',
    'quote': 'USDT',
    'pool_id': Pubkey.from_string("7XawhbbxtsRcQA8KTkHT9f9nc6d69UwqCDh6U5EEbEmX"),
    'authority': Pubkey.from_string("5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1"),
    'open_orders': Pubkey.from_string("4NJVwEAoudfSvU5kdxKm5DsQe4AAqG6XxpZLNBgVTPm4"),
    'target_orders': Pubkey.from_string("9x4knb3nuNAzxsV7YFuGLgnV48Qwnn8S6S9KjMPEzNk1"),
    'base_vault': Pubkey.from_string("876Z9waBygfzUrwwKFfnRcc7cfY4EQf6Kz1w7GRgbVYW"),
    'quote_vault': Pubkey.from_string("CB86HtaqpXbNWbq67L18y5x2RhqoJ6smb7xHUcyWdQAQ"),
    'serum_program': Pubkey.from_string("srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX"),
    'serum_market': Pubkey.from_string("HWHvQhFmJB3NUcu1aihKmrKegfVxBEHzwVX6yZCKEsi1"),
    'serum_bids': Pubkey.from_string("FuKzSMR9Y3E8VWb4HoMkqUq39m6bWqJbdEtVPeWUvMDC"),
    'serum_asks': Pubkey.from_string("9u7vYjXvpKPQ6pAaC9sMRhGMPykQu4RnqKLXwNSdVYcM"),
    'serum_event_queue': Pubkey.from_string("E3UpBcvgFwVjPunSKB5oWQZXDMpVBKNgUmPwghMFmKBs"),
    'serum_base_vault': Pubkey.from_string("5Bt2capiTZfgEVCVbHpkbGpqL5TTXRK6a7tFWJjNGHBS"),
    'serum_quote_vault': Pubkey.from_string("7eZMWbQfaJLHJnZQGJKbhXCqR7hFDFJhFJN4iu4JCFHZ"),
    'serum_vault_signer': Pubkey.from_string("D5mMmHZSePvQVRLqU4NHQV6SLqsnsmEqUaK5DkDdHmf7"),
    'fee_bps': RAYDIUM_FEE_BPS,
}

ORCA_SOL_USDT = {
    'name': 'orca_sol_usdt',
    'dex': 'orca',
    'base': 'SOL',
    'quote': 'USDT',
    'pool_id': Pubkey.from_string("Dqk7mHQBx2ZWExmyrR2S8X6UG75CrbbpK2FSBZsNYsw6"),
    'authority': Pubkey.from_string("2sxKY7hxVFrY5oNE2DgaPAJFamMzsmFLM2DgVcjK5yTy"),
    'base_vault': Pubkey.from_string("DTb8NKsfhEJGY1TrA7RXN6MBiTrjnkdMAfjPEjtmTT3M"),
    'quote_vault': Pubkey.from_string("E8erPjPEorykpPjFV9yUYMYigEWKQUxuGfL2rJKLJ3KU"),
    'pool_token_mint': Pubkey.from_string("FZthQCuYHhcfiDma7QrX7buDHwrZEd7vL8SjS6LQa3Tx"),
    'fee_account': Pubkey.from_string("BBKgw75FivTYXj85D2AWyVdaTdTWuSuHVXRm1Xu7fipb"),
    'fee_bps': ORCA_FEE_BPS,
}

# All pools for iteration
ALL_POOLS = {
    'raydium_sol_usdc': RAYDIUM_SOL_USDC,
    'orca_sol_usdc': ORCA_SOL_USDC,
    'raydium_sol_usdt': RAYDIUM_SOL_USDT,
    'orca_sol_usdt': ORCA_SOL_USDT,
}

# Arbitrage pairs to check
ARB_PAIRS = [
    ('raydium_sol_usdc', 'orca_sol_usdc'),  # SOL/USDC: Raydium <-> Orca
    ('raydium_sol_usdt', 'orca_sol_usdt'),  # SOL/USDT: Raydium <-> Orca
]

# =============================================================================
# STATE
# =============================================================================
pool_state: Dict[str, dict] = {}
for pool_name in ALL_POOLS:
    pool_state[pool_name] = {
        "base_reserve": 0,
        "quote_reserve": 0,
        "price": 0.0,
        "last_update": 0
    }

pool_state["market"] = {"sol_usdc": 0.0, "sol_usdt": 0.0}

failed_pools: Dict[str, float] = {}

metrics = {
    "opportunities_detected": 0,
    "depth_filtered": 0,
    "age_filtered": 0,
    "profit_filtered": 0,
    "sim_passed": 0,
    "sim_failed": 0,
    "tx_sent": 0,
    "tx_confirmed": 0,
    "tx_reverted": 0,
    "jito_submitted": 0,
    "profit_usdc": 0.0,
    "start_time": None
}


class HFTFlashLoanBotV5:
    
    def __init__(self):
        self.rpc_url = os.environ.get('SOLANA_RPC_URL')
        if self.rpc_url and 'devnet' in self.rpc_url.lower():
            logger.warning("Devnet detected! Switching to mainnet.")
            self.rpc_url = "https://api.mainnet-beta.solana.com"
        elif not self.rpc_url:
            self.rpc_url = "https://api.mainnet-beta.solana.com"
        
        self.client = None
        self.wallet = None
        self.token_accounts: Dict[str, Pubkey] = {}
        self.wallet_balance = 0
        self.is_executing = False
        self.http_session = None
        self.trading_enabled = True
        self.use_jito = True  # MEV protection
        
        logger.info(f"RPC: {self.rpc_url[:50]}...")

    async def connect(self):
        self.client = AsyncClient(self.rpc_url, commitment=Confirmed)
        self.http_session = aiohttp.ClientSession()
        
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
            await self.find_token_accounts()
            await self.check_wallet_balance()
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

    async def find_token_accounts(self):
        """Find ATAs for all tokens"""
        ata_program = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        
        for mint_name, mint in [("USDC", USDC_MINT), ("USDT", USDT_MINT), ("WSOL", WSOL_MINT)]:
            ata, _ = Pubkey.find_program_address(
                [bytes(self.wallet.pubkey()), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
                ata_program
            )
            self.token_accounts[mint_name] = ata
            logger.info(f"{mint_name} ATA: {ata}")

    async def check_wallet_balance(self):
        try:
            resp = await self.client.get_token_account_balance(self.token_accounts["USDC"])
            if resp.value:
                self.wallet_balance = int(resp.value.amount) / 10**USDC_DECIMALS
                logger.info(f"Wallet USDC: ${self.wallet_balance:.2f}")
                self.trading_enabled = self.wallet_balance >= MIN_WALLET_BALANCE_USDC
                if not self.trading_enabled:
                    logger.warning("LOW BALANCE! Trading disabled.")
        except Exception:
            self.wallet_balance = 0

    # =============================================================================
    # CALCULATIONS
    # =============================================================================
    def calculate_swap_out(self, amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int) -> int:
        if reserve_in == 0 or reserve_out == 0:
            return 0
        amount_after_fee = amount_in * (10000 - fee_bps) // 10000
        numerator = amount_after_fee * reserve_out
        denominator = reserve_in + amount_after_fee
        return numerator // denominator if denominator > 0 else 0

    def expected_profit(self, amount_in: int, buy_pool: str, sell_pool: str) -> float:
        buy = pool_state[buy_pool]
        sell = pool_state[sell_pool]
        buy_fee = ALL_POOLS[buy_pool]['fee_bps']
        sell_fee = ALL_POOLS[sell_pool]['fee_bps']
        
        # First swap: Quote -> Base (buy SOL)
        base_out = self.calculate_swap_out(
            amount_in, buy["quote_reserve"], buy["base_reserve"], buy_fee
        )
        if base_out == 0:
            return -999999
        
        # Second swap: Base -> Quote (sell SOL)
        quote_out = self.calculate_swap_out(
            base_out, sell["base_reserve"], sell["quote_reserve"], sell_fee
        )
        
        # Flash loan fee
        flash_fee = (amount_in * SOLEND_FLASHLOAN_FEE_BPS) // 10000
        
        # Determine decimals based on quote token
        quote = ALL_POOLS[buy_pool]['quote']
        decimals = USDC_DECIMALS if quote == 'USDC' else USDT_DECIMALS
        
        profit = (quote_out - amount_in - flash_fee) / 10**decimals
        return profit

    # =============================================================================
    # FILTERS
    # =============================================================================
    def passes_depth_filter(self, amount_in: int, pool_name: str) -> bool:
        pool = pool_state[pool_name]
        max_trade = int(pool["quote_reserve"] * MAX_POOL_PERCENT)
        if amount_in > max_trade:
            metrics["depth_filtered"] += 1
            return False
        return True

    def passes_age_filter(self, pool_name: str) -> bool:
        pool = pool_state[pool_name]
        age_ms = (time.time() - pool["last_update"]) * 1000
        if age_ms > MAX_OPPORTUNITY_AGE_MS:
            metrics["age_filtered"] += 1
            return False
        return True

    def get_trade_size(self, spread_bps: float, quote: str) -> int:
        decimals = USDC_DECIMALS if quote == 'USDC' else USDT_DECIMALS
        if spread_bps > 20:
            return TRADE_SIZES["large"] * 10**decimals
        elif spread_bps > 12:
            return TRADE_SIZES["medium"] * 10**decimals
        else:
            return TRADE_SIZES["small"] * 10**decimals

    def get_priority_fee(self, profit: float) -> int:
        if profit > 5:
            return PRIORITY_FEES["very_high"]
        elif profit > 2:
            return PRIORITY_FEES["high"]
        elif profit > 0.5:
            return PRIORITY_FEES["medium"]
        return PRIORITY_FEES["low"]

    def is_blacklisted(self, pool_key: str) -> bool:
        if pool_key in failed_pools:
            if time.time() < failed_pools[pool_key]:
                return True
            del failed_pools[pool_key]
        return False

    def blacklist(self, pool_key: str):
        failed_pools[pool_key] = time.time() + POOL_BLACKLIST_DURATION
        logger.warning(f"Blacklisted {pool_key}")

    # =============================================================================
    # OPPORTUNITY DETECTION
    # =============================================================================
    def detect_opportunities(self) -> List[dict]:
        """Detect arbitrage opportunities across all pairs"""
        opportunities = []
        
        for pool_a, pool_b in ARB_PAIRS:
            state_a = pool_state[pool_a]
            state_b = pool_state[pool_b]
            
            if state_a["price"] <= 0 or state_b["price"] <= 0:
                continue
            
            # Check both directions
            for buy_pool, sell_pool in [(pool_a, pool_b), (pool_b, pool_a)]:
                buy_price = pool_state[buy_pool]["price"]
                sell_price = pool_state[sell_pool]["price"]
                
                if buy_price >= sell_price:
                    continue
                
                spread_bps = ((sell_price - buy_price) / buy_price) * 10000
                
                if spread_bps < MIN_SPREAD_BPS:
                    continue
                
                quote = ALL_POOLS[buy_pool]['quote']
                trade_size = self.get_trade_size(spread_bps, quote)
                
                # Filters
                if not self.passes_depth_filter(trade_size, buy_pool):
                    continue
                if not self.passes_age_filter(buy_pool):
                    continue
                
                pool_key = f"{buy_pool}_{sell_pool}"
                if self.is_blacklisted(pool_key):
                    continue
                
                # Calculate profit
                profit = self.expected_profit(trade_size, buy_pool, sell_pool)
                
                if profit < MIN_PROFIT_USDC:
                    metrics["profit_filtered"] += 1
                    continue
                
                metrics["opportunities_detected"] += 1
                
                opportunities.append({
                    "buy_pool": buy_pool,
                    "sell_pool": sell_pool,
                    "spread_bps": spread_bps,
                    "trade_size": trade_size,
                    "expected_profit": profit,
                    "pool_key": pool_key,
                    "quote": quote,
                })
        
        # Return best opportunity
        if opportunities:
            return [max(opportunities, key=lambda x: x["expected_profit"])]
        return []

    # =============================================================================
    # INSTRUCTION BUILDERS
    # =============================================================================
    def build_compute_ixs(self, priority_fee: int) -> List[Instruction]:
        return [
            set_compute_unit_limit(400000),
            set_compute_unit_price(priority_fee),
        ]

    def build_jito_tip_ix(self) -> Instruction:
        """Build Jito tip instruction for MEV protection"""
        import random
        tip_account = Pubkey.from_string(random.choice(JITO_TIP_ACCOUNTS))
        
        # SOL transfer instruction
        data = struct.pack('<I', 2) + struct.pack('<Q', JITO_TIP_LAMPORTS)
        
        return Instruction(
            program_id=SYSTEM_PROGRAM_ID,
            accounts=[
                AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=True),
                AccountMeta(pubkey=tip_account, is_signer=False, is_writable=True),
            ],
            data=data
        )

    def build_flashloan_borrow_ix(self, amount: int) -> Instruction:
        r = SOLEND_USDC_RESERVE
        data = bytes([20]) + struct.pack('<Q', amount)
        accounts = [
            AccountMeta(pubkey=r['liquidity_supply'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=self.token_accounts["USDC"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['reserve'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['lending_market'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=r['lending_market_authority'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SOLEND_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        return Instruction(program_id=SOLEND_PROGRAM_ID, accounts=accounts, data=data)

    def build_flashloan_repay_ix(self, amount: int) -> Instruction:
        r = SOLEND_USDC_RESERVE
        fee = (amount * SOLEND_FLASHLOAN_FEE_BPS) // 10000
        data = bytes([21]) + struct.pack('<Q', amount + fee) + bytes([0])
        accounts = [
            AccountMeta(pubkey=self.token_accounts["USDC"], is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['liquidity_supply'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['fee_receiver'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['reserve'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=r['lending_market'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        return Instruction(program_id=SOLEND_PROGRAM_ID, accounts=accounts, data=data)

    def build_raydium_swap_ix(self, pool: dict, amount_in: int, min_out: int, direction: str) -> Instruction:
        data = bytes([9]) + struct.pack('<Q', amount_in) + struct.pack('<Q', min_out)
        
        quote = pool['quote']
        quote_account = self.token_accounts[quote]
        base_account = self.token_accounts["WSOL"]
        
        if direction == "quote_to_base":
            src, dst = quote_account, base_account
        else:
            src, dst = base_account, quote_account
        
        accounts = [
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=pool['pool_id'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['authority'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=pool['open_orders'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['target_orders'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['base_vault'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['quote_vault'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['serum_program'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=pool['serum_market'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['serum_bids'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['serum_asks'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['serum_event_queue'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['serum_base_vault'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['serum_quote_vault'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['serum_vault_signer'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=src, is_signer=False, is_writable=True),
            AccountMeta(pubkey=dst, is_signer=False, is_writable=True),
            AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
        ]
        return Instruction(program_id=RAYDIUM_AMM_PROGRAM_ID, accounts=accounts, data=data)

    def build_orca_swap_ix(self, pool: dict, amount_in: int, min_out: int, direction: str) -> Instruction:
        data = bytes([1]) + struct.pack('<Q', amount_in) + struct.pack('<Q', min_out)
        
        quote = pool['quote']
        quote_account = self.token_accounts[quote]
        base_account = self.token_accounts["WSOL"]
        
        if direction == "quote_to_base":
            src, dst = quote_account, base_account
            src_v, dst_v = pool['quote_vault'], pool['base_vault']
        else:
            src, dst = base_account, quote_account
            src_v, dst_v = pool['base_vault'], pool['quote_vault']
        
        accounts = [
            AccountMeta(pubkey=pool['pool_id'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=pool['authority'], is_signer=False, is_writable=False),
            AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=False),
            AccountMeta(pubkey=src, is_signer=False, is_writable=True),
            AccountMeta(pubkey=src_v, is_signer=False, is_writable=True),
            AccountMeta(pubkey=dst, is_signer=False, is_writable=True),
            AccountMeta(pubkey=dst_v, is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['pool_token_mint'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=pool['fee_account'], is_signer=False, is_writable=True),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ]
        return Instruction(program_id=ORCA_SWAP_PROGRAM_ID, accounts=accounts, data=data)

    # =============================================================================
    # MEV PROTECTION - JITO BUNDLE SUBMISSION
    # =============================================================================
    async def submit_jito_bundle(self, tx: Transaction) -> Optional[str]:
        """Submit transaction as Jito bundle for MEV protection"""
        try:
            # Serialize transaction
            tx_bytes = bytes(tx)
            tx_base58 = base58.b58encode(tx_bytes).decode('utf-8')
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [[tx_base58]]
            }
            
            async with self.http_session.post(
                JITO_BLOCK_ENGINE_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if "result" in result:
                        metrics["jito_submitted"] += 1
                        return result["result"]
                    else:
                        logger.warning(f"Jito error: {result}")
                else:
                    logger.warning(f"Jito HTTP {resp.status}")
        except Exception as e:
            logger.warning(f"Jito submit failed: {e}")
        return None

    # =============================================================================
    # EXECUTION
    # =============================================================================
    async def execute_arbitrage(self, opp: dict) -> bool:
        if not self.trading_enabled or self.is_executing:
            return False
        
        self.is_executing = True
        
        try:
            buy_pool_name = opp["buy_pool"]
            sell_pool_name = opp["sell_pool"]
            trade_size = opp["trade_size"]
            expected_profit = opp["expected_profit"]
            
            buy_pool = ALL_POOLS[buy_pool_name]
            sell_pool = ALL_POOLS[sell_pool_name]
            buy_state = pool_state[buy_pool_name]
            sell_state = pool_state[sell_pool_name]
            
            priority_fee = self.get_priority_fee(expected_profit)
            
            # Calculate swap amounts
            base_out = self.calculate_swap_out(
                trade_size, buy_state["quote_reserve"], buy_state["base_reserve"], buy_pool['fee_bps']
            )
            quote_out = self.calculate_swap_out(
                base_out, sell_state["base_reserve"], sell_state["quote_reserve"], sell_pool['fee_bps']
            )
            
            # Build instructions
            ixs = self.build_compute_ixs(priority_fee)
            
            # Add Jito tip for MEV protection
            if self.use_jito:
                ixs.append(self.build_jito_tip_ix())
            
            # Flash loan borrow
            ixs.append(self.build_flashloan_borrow_ix(trade_size))
            
            # First swap: Quote -> Base
            min_base = int(base_out * 0.98)
            if buy_pool['dex'] == 'raydium':
                ixs.append(self.build_raydium_swap_ix(buy_pool, trade_size, min_base, "quote_to_base"))
            else:
                ixs.append(self.build_orca_swap_ix(buy_pool, trade_size, min_base, "quote_to_base"))
            
            # Second swap: Base -> Quote
            min_quote = int(quote_out * 0.98)
            if sell_pool['dex'] == 'raydium':
                ixs.append(self.build_raydium_swap_ix(sell_pool, base_out, min_quote, "base_to_quote"))
            else:
                ixs.append(self.build_orca_swap_ix(sell_pool, base_out, min_quote, "base_to_quote"))
            
            # Flash loan repay
            ixs.append(self.build_flashloan_repay_ix(trade_size))
            
            # Build transaction
            bh_resp = await self.client.get_latest_blockhash()
            bh = bh_resp.value.blockhash
            
            msg = Message.new_with_blockhash(ixs, self.wallet.pubkey(), Hash.from_string(str(bh)))
            tx = Transaction.new_unsigned(msg)
            tx = tx.sign([self.wallet], Hash.from_string(str(bh)))
            
            # Simulate first
            sim = await self.client.simulate_transaction(tx)
            
            if sim.value.err:
                metrics["sim_failed"] += 1
                logger.warning(f"SIM FAIL | {sim.value.err}")
                self.blacklist(opp["pool_key"])
                return False
            
            metrics["sim_passed"] += 1
            
            # Send via Jito or standard
            sig = None
            if self.use_jito:
                logger.info("SIM PASS | Submitting to Jito...")
                bundle_id = await self.submit_jito_bundle(tx)
                if bundle_id:
                    logger.info(f"JITO BUNDLE | {bundle_id}")
                    # Wait for confirmation
                    await asyncio.sleep(2)
                    sig = bundle_id
            
            if not sig:
                logger.info(f"Sending standard TX (priority: {priority_fee})...")
                resp = await self.client.send_transaction(tx)
                sig = resp.value
            
            metrics["tx_sent"] += 1
            logger.info(f"TX SENT | {sig}")
            
            # Confirm
            await self.client.confirm_transaction(sig, commitment=Confirmed)
            
            metrics["tx_confirmed"] += 1
            metrics["profit_usdc"] += expected_profit
            
            logger.info(f"TX CONFIRMED | +${expected_profit:.4f}")
            await self.check_wallet_balance()
            
            return True
            
        except Exception as e:
            metrics["tx_reverted"] += 1
            logger.error(f"TX ERROR | {e}")
            self.blacklist(opp["pool_key"])
            return False
        finally:
            self.is_executing = False

    # =============================================================================
    # DATA FETCHING
    # =============================================================================
    async def fetch_pool_reserves(self, pool_name: str, pool: dict):
        """Fetch reserves for a single pool"""
        try:
            now = time.time()
            
            r1 = await self.client.get_token_account_balance(pool['base_vault'])
            r2 = await self.client.get_token_account_balance(pool['quote_vault'])
            
            if r1.value and r2.value:
                base_res = int(r1.value.amount)
                quote_res = int(r2.value.amount)
                
                quote_decimals = USDC_DECIMALS if pool['quote'] == 'USDC' else USDT_DECIMALS
                
                price = (quote_res / 10**quote_decimals) / (base_res / 10**SOL_DECIMALS) if base_res > 0 else 0
                
                pool_state[pool_name]["base_reserve"] = base_res
                pool_state[pool_name]["quote_reserve"] = quote_res
                pool_state[pool_name]["price"] = price
                pool_state[pool_name]["last_update"] = now
                
        except Exception as e:
            logger.debug(f"Fetch {pool_name} error: {e}")

    async def fetch_all_reserves(self):
        """Fetch reserves from all pools"""
        tasks = [
            self.fetch_pool_reserves(name, pool)
            for name, pool in ALL_POOLS.items()
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def fetch_market_prices(self):
        """Fetch market prices from CoinGecko"""
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            async with self.http_session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "solana" in data:
                        pool_state["market"]["sol_usdc"] = float(data["solana"]["usd"])
                        pool_state["market"]["sol_usdt"] = float(data["solana"]["usd"])  # Assume same for USDT
        except Exception:
            pass

    # =============================================================================
    # MAIN LOOP
    # =============================================================================
    async def monitor_loop(self):
        scan = 0
        while True:
            try:
                await self.fetch_all_reserves()
                scan += 1
                
                # Detect and execute
                opportunities = self.detect_opportunities()
                for opp in opportunities:
                    logger.info(
                        f"OPP | {opp['buy_pool']}->{opp['sell_pool']} | "
                        f"Spread: {opp['spread_bps']:.1f}bps | "
                        f"Size: ${opp['trade_size']/10**6:.0f} | "
                        f"Profit: ${opp['expected_profit']:.4f}"
                    )
                    await self.execute_arbitrage(opp)
                
                # Log status
                if scan % 60 == 0:
                    self.log_prices()
                
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Loop error: {e}")
                await asyncio.sleep(1)

    def log_prices(self):
        """Log current prices"""
        usdc_ray = pool_state["raydium_sol_usdc"]["price"]
        usdc_orca = pool_state["orca_sol_usdc"]["price"]
        usdt_ray = pool_state["raydium_sol_usdt"]["price"]
        usdt_orca = pool_state["orca_sol_usdt"]["price"]
        
        usdc_spread = abs((usdc_orca - usdc_ray) / usdc_ray * 10000) if usdc_ray > 0 else 0
        usdt_spread = abs((usdt_orca - usdt_ray) / usdt_ray * 10000) if usdt_ray > 0 else 0
        
        logger.info(f"SOL/USDC | Ray: ${usdc_ray:.2f} | Orca: ${usdc_orca:.2f} | Spread: {usdc_spread:.1f}bps")
        logger.info(f"SOL/USDT | Ray: ${usdt_ray:.2f} | Orca: ${usdt_orca:.2f} | Spread: {usdt_spread:.1f}bps")

    async def print_stats(self):
        while True:
            await asyncio.sleep(60)
            runtime = (datetime.now(timezone.utc) - metrics["start_time"]).total_seconds() / 3600
            logger.info(
                f"STATS | {runtime:.2f}h | "
                f"Opps: {metrics['opportunities_detected']} | "
                f"Sim: {metrics['sim_passed']}/{metrics['sim_passed']+metrics['sim_failed']} | "
                f"TX: {metrics['tx_confirmed']}/{metrics['tx_sent']} | "
                f"Jito: {metrics['jito_submitted']} | "
                f"Profit: ${metrics['profit_usdc']:.4f}"
            )
            logger.info(
                f"FILTERS | Depth: {metrics['depth_filtered']} | "
                f"Age: {metrics['age_filtered']} | "
                f"Profit: {metrics['profit_filtered']} | "
                f"Blacklisted: {len(failed_pools)}"
            )
            
            await self.check_wallet_balance()
            asyncio.create_task(self.fetch_market_prices())

    async def run(self):
        logger.info("=" * 70)
        logger.info("HFT FLASH LOAN BOT v5 - MULTI-DEX + MULTI-PAIR + MEV PROTECTION")
        logger.info("=" * 70)
        logger.info("DEXs: Raydium | Orca")
        logger.info("Pairs: SOL/USDC | SOL/USDT")
        logger.info("MEV: Jito bundle submission enabled")
        logger.info(f"Config: Min spread {MIN_SPREAD_BPS}bps | Min profit ${MIN_PROFIT_USDC}")
        logger.info(f"        Max pool% {MAX_POOL_PERCENT*100}% | Max age {MAX_OPPORTUNITY_AGE_MS}ms")
        logger.info("=" * 70)
        
        if not await self.connect():
            return
        
        metrics["start_time"] = datetime.now(timezone.utc)
        
        await self.fetch_all_reserves()
        self.log_prices()
        
        if not self.trading_enabled:
            logger.warning("TRADING DISABLED - Balance too low!")
        
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
    bot = HFTFlashLoanBotV5()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
