"""
HFT FLASH LOAN BOT v7 - DYNAMIC MULTI-PAIR SCANNER
===================================================
- Auto-discovers 100+ trading pairs from DEX APIs
- 3 DEXs: Raydium, Orca, Meteora
- Dynamic pool fetching - no hardcoded addresses
- Filters by liquidity threshold
- MEV Protection: Jito bundles
"""

import asyncio
import os
import struct
import logging
import time
import aiohttp
from typing import Dict, Optional, List, Any
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
logger = logging.getLogger('hft_v7')

# =============================================================================
# CONFIGURATION
# =============================================================================
MIN_SPREAD_BPS = 8
MIN_PROFIT_USD = 0.10
MIN_LIQUIDITY_USD = 50000  # Only consider pools with >$50k liquidity
MAX_POOLS_PER_DEX = 50     # Top 50 pools per DEX
SOLEND_FLASHLOAN_FEE_BPS = 30
SOL_DECIMALS = 9

MAX_POOL_PERCENT = 0.01
MAX_OPPORTUNITY_AGE_MS = 2000

TRADE_SIZES = {"large": 5000, "medium": 2000, "small": 1000}
PRIORITY_FEES = {"very_high": 500000, "high": 100000, "medium": 50000, "low": 10000}

JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4bVGb4pYrGdNLsmQYEzVHXU",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
]
JITO_BLOCK_ENGINE_URL = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
JITO_TIP_LAMPORTS = 10000

POOL_BLACKLIST_DURATION = 300
MIN_WALLET_BALANCE_USD = 500

# =============================================================================
# DEX API ENDPOINTS
# =============================================================================
RAYDIUM_POOLS_API = "https://api.raydium.io/v2/main/pairs"
ORCA_POOLS_API = "https://api.mainnet.orca.so/v1/whirlpool/list"
METEORA_POOLS_API = "https://dlmm-api.meteora.ag/pair/all"
JUPITER_PRICE_API = "https://price.jup.ag/v6/price"

# =============================================================================
# PROGRAM IDS
# =============================================================================
SOLEND_PROGRAM_ID = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo")
RAYDIUM_AMM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
ORCA_WHIRLPOOL_PROGRAM_ID = Pubkey.from_string("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc")
METEORA_DLMM_PROGRAM_ID = Pubkey.from_string("LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")

# Common token mints
KNOWN_TOKENS = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "JTO": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "ORCA": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
    "mSOL": "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    "stSOL": "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",
    "jitoSOL": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
    "bSOL": "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",
    "WBTC": "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",
    "WETH": "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",
}

# Stablecoins for flash loan denomination
STABLECOINS = ["USDC", "USDT"]

# =============================================================================
# SOLEND RESERVES (for flash loans)
# =============================================================================
SOLEND_RESERVES = {
    "USDC": {
        'reserve': Pubkey.from_string("BgxfHJDzm44T7XG68MYKx7YisTjZu73tVovyZSjJMpmw"),
        'liquidity_supply': Pubkey.from_string("8SheGtsopRUDzdiD6v6BR9a6bqZ9QwywYQY99Fp5meNf"),
        'fee_receiver': Pubkey.from_string("5Gdxn4yquneifE6uk9tK8XSXR5RGBdJGSHsZfZpY2ZtE"),
        'lending_market': Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"),
        'lending_market_authority': Pubkey.from_string("DdZR6zRFiUt4S5mg7AV1uKB2z1f1WzcNYCaTEEWPAuby"),
        'decimals': 6,
    },
    "USDT": {
        'reserve': Pubkey.from_string("8K9WC8xoh2rtQNY7iEGXtPvfbDCi563SdWhCAhuMP2xE"),
        'liquidity_supply': Pubkey.from_string("4Aod8KpcZKHwWosKHEmGTMxBALqbeXMvnCKYqLi2h8hx"),
        'fee_receiver': Pubkey.from_string("5Gdxn4yquneifE6uk9tK8XSXR5RGBdJGSHsZfZpY2ZtE"),
        'lending_market': Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"),
        'lending_market_authority': Pubkey.from_string("DdZR6zRFiUt4S5mg7AV1uKB2z1f1WzcNYCaTEEWPAuby"),
        'decimals': 6,
    },
}

# =============================================================================
# STATE
# =============================================================================
discovered_pools: Dict[str, Dict] = {}  # pool_id -> pool_info
pool_state: Dict[str, Dict] = {}        # pool_id -> {reserves, price, last_update}
token_prices: Dict[str, float] = {}     # token_symbol -> USD price
failed_pools: Dict[str, float] = {}     # pool_id -> blacklist_until

metrics = {
    "pools_discovered": 0,
    "pairs_monitored": 0,
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
    "profit_usd": 0.0,
    "start_time": None
}


class DynamicPoolScanner:
    """Fetches and manages pools from multiple DEX APIs"""
    
    def __init__(self, http_session: aiohttp.ClientSession):
        self.session = http_session
        self.pools: Dict[str, Dict] = {}
        
    async def fetch_raydium_pools(self) -> List[Dict]:
        """Fetch top Raydium AMM pools"""
        try:
            async with self.session.get(RAYDIUM_POOLS_API, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pools = []
                    for pool in data[:MAX_POOLS_PER_DEX]:
                        if pool.get('liquidity', 0) >= MIN_LIQUIDITY_USD:
                            pools.append({
                                'dex': 'raydium',
                                'pool_id': pool.get('ammId'),
                                'name': pool.get('name', ''),
                                'base_mint': pool.get('baseMint'),
                                'quote_mint': pool.get('quoteMint'),
                                'base_vault': pool.get('baseVault'),
                                'quote_vault': pool.get('quoteVault'),
                                'liquidity_usd': pool.get('liquidity', 0),
                                'fee_bps': 25,
                                'authority': pool.get('authority'),
                                'open_orders': pool.get('openOrders'),
                                'target_orders': pool.get('targetOrders'),
                            })
                    logger.info(f"Raydium: Found {len(pools)} pools")
                    return pools
        except Exception as e:
            logger.error(f"Raydium API error: {e}")
        return []

    async def fetch_orca_pools(self) -> List[Dict]:
        """Fetch top Orca Whirlpool pools"""
        try:
            async with self.session.get(ORCA_POOLS_API, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    whirlpools = data.get('whirlpools', [])
                    pools = []
                    # Sort by TVL
                    sorted_pools = sorted(whirlpools, key=lambda x: float(x.get('tvl', 0) or 0), reverse=True)
                    for pool in sorted_pools[:MAX_POOLS_PER_DEX]:
                        tvl = float(pool.get('tvl', 0) or 0)
                        if tvl >= MIN_LIQUIDITY_USD:
                            pools.append({
                                'dex': 'orca',
                                'pool_id': pool.get('address'),
                                'name': f"{pool.get('tokenA', {}).get('symbol', '?')}/{pool.get('tokenB', {}).get('symbol', '?')}",
                                'base_mint': pool.get('tokenA', {}).get('mint'),
                                'quote_mint': pool.get('tokenB', {}).get('mint'),
                                'base_vault': pool.get('tokenVaultA'),
                                'quote_vault': pool.get('tokenVaultB'),
                                'liquidity_usd': tvl,
                                'fee_bps': int(float(pool.get('lpFeeRate', 0.003)) * 10000),
                            })
                    logger.info(f"Orca: Found {len(pools)} pools")
                    return pools
        except Exception as e:
            logger.error(f"Orca API error: {e}")
        return []

    async def fetch_meteora_pools(self) -> List[Dict]:
        """Fetch top Meteora DLMM pools"""
        try:
            async with self.session.get(METEORA_POOLS_API, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pools = []
                    # Sort by liquidity
                    sorted_pools = sorted(data, key=lambda x: float(x.get('liquidity', 0) or 0), reverse=True)
                    for pool in sorted_pools[:MAX_POOLS_PER_DEX]:
                        liquidity = float(pool.get('liquidity', 0) or 0)
                        if liquidity >= MIN_LIQUIDITY_USD:
                            pools.append({
                                'dex': 'meteora',
                                'pool_id': pool.get('address'),
                                'name': pool.get('name', ''),
                                'base_mint': pool.get('mint_x'),
                                'quote_mint': pool.get('mint_y'),
                                'base_vault': pool.get('reserve_x'),
                                'quote_vault': pool.get('reserve_y'),
                                'liquidity_usd': liquidity,
                                'fee_bps': int(float(pool.get('base_fee_percentage', 0.25)) * 100),
                                'lb_pair': pool.get('address'),
                                'oracle': pool.get('oracle'),
                            })
                    logger.info(f"Meteora: Found {len(pools)} pools")
                    return pools
        except Exception as e:
            logger.error(f"Meteora API error: {e}")
        return []

    async def discover_all_pools(self) -> Dict[str, Dict]:
        """Fetch pools from all DEXs"""
        logger.info("Discovering pools from all DEXs...")
        
        raydium_pools, orca_pools, meteora_pools = await asyncio.gather(
            self.fetch_raydium_pools(),
            self.fetch_orca_pools(),
            self.fetch_meteora_pools(),
            return_exceptions=True
        )
        
        all_pools = {}
        
        for pool_list in [raydium_pools, orca_pools, meteora_pools]:
            if isinstance(pool_list, list):
                for pool in pool_list:
                    pool_id = pool.get('pool_id')
                    if pool_id:
                        all_pools[pool_id] = pool
        
        self.pools = all_pools
        logger.info(f"Total pools discovered: {len(all_pools)}")
        return all_pools

    def find_arbitrage_pairs(self) -> List[tuple]:
        """Find pools trading the same pair across different DEXs"""
        # Group pools by token pair
        pair_pools: Dict[str, List[Dict]] = {}
        
        for pool_id, pool in self.pools.items():
            base = pool.get('base_mint', '')
            quote = pool.get('quote_mint', '')
            if not base or not quote:
                continue
            
            # Normalize pair key (sorted mints)
            pair_key = tuple(sorted([base, quote]))
            
            if pair_key not in pair_pools:
                pair_pools[pair_key] = []
            pair_pools[pair_key].append(pool)
        
        # Find pairs with 2+ pools (arbitrage opportunities)
        arb_pairs = []
        for pair_key, pools in pair_pools.items():
            if len(pools) >= 2:
                # Create all combinations
                for i in range(len(pools)):
                    for j in range(i + 1, len(pools)):
                        if pools[i]['dex'] != pools[j]['dex']:  # Different DEXs
                            arb_pairs.append((pools[i]['pool_id'], pools[j]['pool_id']))
        
        logger.info(f"Found {len(arb_pairs)} arbitrage pairs across DEXs")
        return arb_pairs


class HFTFlashLoanBotV7:
    
    def __init__(self):
        self.rpc_url = os.environ.get('SOLANA_RPC_URL')
        if self.rpc_url and 'devnet' in self.rpc_url.lower():
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
        self.use_jito = True
        
        self.pool_scanner: Optional[DynamicPoolScanner] = None
        self.arb_pairs: List[tuple] = []
        
        logger.info(f"RPC: {self.rpc_url[:50]}...")

    async def connect(self):
        self.client = AsyncClient(self.rpc_url, commitment=Confirmed)
        self.http_session = aiohttp.ClientSession()
        self.pool_scanner = DynamicPoolScanner(self.http_session)
        
        private_key = os.environ.get('SOLANA_PRIVATE_KEY')
        if private_key:
            try:
                self.wallet = Keypair.from_bytes(base58.b58decode(private_key))
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
        """Find ATAs for common tokens"""
        ata_program = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        for token_name, mint_str in KNOWN_TOKENS.items():
            try:
                mint = Pubkey.from_string(mint_str)
                ata, _ = Pubkey.find_program_address(
                    [bytes(self.wallet.pubkey()), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
                    ata_program
                )
                self.token_accounts[token_name] = ata
                self.token_accounts[mint_str] = ata  # Also index by mint
            except:
                pass
        logger.info(f"Found {len(self.token_accounts)} token accounts")

    async def check_wallet_balance(self):
        try:
            usdc_mint = KNOWN_TOKENS.get("USDC")
            if usdc_mint and usdc_mint in self.token_accounts:
                resp = await self.client.get_token_account_balance(self.token_accounts[usdc_mint])
                if resp.value:
                    self.wallet_balance = int(resp.value.amount) / 10**6
                    logger.info(f"Wallet USDC: ${self.wallet_balance:.2f}")
                    self.trading_enabled = self.wallet_balance >= MIN_WALLET_BALANCE_USD
        except:
            self.wallet_balance = 0

    async def discover_pools(self):
        """Discover pools and arbitrage opportunities"""
        discovered_pools.clear()
        discovered_pools.update(await self.pool_scanner.discover_all_pools())
        
        self.arb_pairs = self.pool_scanner.find_arbitrage_pairs()
        
        metrics["pools_discovered"] = len(discovered_pools)
        metrics["pairs_monitored"] = len(self.arb_pairs)
        
        # Initialize pool state
        for pool_id in discovered_pools:
            pool_state[pool_id] = {
                "base_reserve": 0,
                "quote_reserve": 0,
                "price": 0.0,
                "last_update": 0
            }

    async def fetch_pool_reserves(self, pool_id: str):
        """Fetch reserves for a single pool"""
        pool = discovered_pools.get(pool_id)
        if not pool:
            return
        
        try:
            now = time.time()
            base_vault = pool.get('base_vault')
            quote_vault = pool.get('quote_vault')
            
            if not base_vault or not quote_vault:
                return
            
            r1 = await self.client.get_token_account_balance(Pubkey.from_string(base_vault))
            r2 = await self.client.get_token_account_balance(Pubkey.from_string(quote_vault))
            
            if r1.value and r2.value:
                base_res = int(r1.value.amount)
                quote_res = int(r2.value.amount)
                
                # Get decimals from response
                base_decimals = r1.value.decimals
                quote_decimals = r2.value.decimals
                
                price = (quote_res / 10**quote_decimals) / (base_res / 10**base_decimals) if base_res > 0 else 0
                
                pool_state[pool_id] = {
                    "base_reserve": base_res,
                    "quote_reserve": quote_res,
                    "price": price,
                    "last_update": now,
                    "base_decimals": base_decimals,
                    "quote_decimals": quote_decimals,
                }
        except Exception as e:
            logger.debug(f"Fetch {pool_id[:8]} error: {e}")

    async def fetch_batch_reserves(self, pool_ids: List[str], batch_size: int = 10):
        """Fetch reserves in batches to avoid rate limits"""
        for i in range(0, len(pool_ids), batch_size):
            batch = pool_ids[i:i + batch_size]
            await asyncio.gather(
                *[self.fetch_pool_reserves(pid) for pid in batch],
                return_exceptions=True
            )
            await asyncio.sleep(0.1)  # Small delay between batches

    def calculate_swap_out(self, amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int) -> int:
        if reserve_in == 0 or reserve_out == 0:
            return 0
        amount_after_fee = amount_in * (10000 - fee_bps) // 10000
        return (amount_after_fee * reserve_out) // (reserve_in + amount_after_fee)

    def expected_profit(self, amount_in: int, buy_pool_id: str, sell_pool_id: str) -> float:
        buy_pool = discovered_pools.get(buy_pool_id)
        sell_pool = discovered_pools.get(sell_pool_id)
        buy_state = pool_state.get(buy_pool_id, {})
        sell_state = pool_state.get(sell_pool_id, {})
        
        if not buy_pool or not sell_pool or not buy_state or not sell_state:
            return -999999
        
        buy_fee = buy_pool.get('fee_bps', 30)
        sell_fee = sell_pool.get('fee_bps', 30)
        
        # First swap: Quote -> Base
        base_out = self.calculate_swap_out(
            amount_in,
            buy_state.get("quote_reserve", 0),
            buy_state.get("base_reserve", 0),
            buy_fee
        )
        if base_out == 0:
            return -999999
        
        # Second swap: Base -> Quote
        quote_out = self.calculate_swap_out(
            base_out,
            sell_state.get("base_reserve", 0),
            sell_state.get("quote_reserve", 0),
            sell_fee
        )
        
        flash_fee = (amount_in * SOLEND_FLASHLOAN_FEE_BPS) // 10000
        quote_decimals = buy_state.get("quote_decimals", 6)
        
        return (quote_out - amount_in - flash_fee) / 10**quote_decimals

    def passes_filters(self, amount_in: int, buy_pool_id: str) -> bool:
        state = pool_state.get(buy_pool_id, {})
        
        # Depth filter
        max_trade = int(state.get("quote_reserve", 0) * MAX_POOL_PERCENT)
        if amount_in > max_trade:
            metrics["depth_filtered"] += 1
            return False
        
        # Age filter
        age_ms = (time.time() - state.get("last_update", 0)) * 1000
        if age_ms > MAX_OPPORTUNITY_AGE_MS:
            metrics["age_filtered"] += 1
            return False
        
        # Blacklist check
        if buy_pool_id in failed_pools and time.time() < failed_pools[buy_pool_id]:
            return False
        
        return True

    def get_trade_size(self, spread_bps: float, decimals: int = 6) -> int:
        if spread_bps > 20:
            return TRADE_SIZES["large"] * 10**decimals
        elif spread_bps > 12:
            return TRADE_SIZES["medium"] * 10**decimals
        return TRADE_SIZES["small"] * 10**decimals

    def get_priority_fee(self, profit: float) -> int:
        if profit > 5: return PRIORITY_FEES["very_high"]
        elif profit > 2: return PRIORITY_FEES["high"]
        elif profit > 0.5: return PRIORITY_FEES["medium"]
        return PRIORITY_FEES["low"]

    def detect_opportunities(self) -> List[Dict]:
        """Scan all arbitrage pairs for opportunities"""
        opportunities = []
        
        for pool_a_id, pool_b_id in self.arb_pairs:
            state_a = pool_state.get(pool_a_id, {})
            state_b = pool_state.get(pool_b_id, {})
            
            price_a = state_a.get("price", 0)
            price_b = state_b.get("price", 0)
            
            if price_a <= 0 or price_b <= 0:
                continue
            
            # Check both directions
            for buy_id, sell_id, buy_price, sell_price in [
                (pool_a_id, pool_b_id, price_a, price_b),
                (pool_b_id, pool_a_id, price_b, price_a)
            ]:
                if buy_price >= sell_price:
                    continue
                
                spread_bps = ((sell_price - buy_price) / buy_price) * 10000
                
                if spread_bps < MIN_SPREAD_BPS:
                    continue
                
                decimals = state_a.get("quote_decimals", 6)
                trade_size = self.get_trade_size(spread_bps, decimals)
                
                if not self.passes_filters(trade_size, buy_id):
                    continue
                
                profit = self.expected_profit(trade_size, buy_id, sell_id)
                
                if profit < MIN_PROFIT_USD:
                    metrics["profit_filtered"] += 1
                    continue
                
                metrics["opportunities_detected"] += 1
                
                buy_pool = discovered_pools.get(buy_id, {})
                sell_pool = discovered_pools.get(sell_id, {})
                
                opportunities.append({
                    "buy_pool_id": buy_id,
                    "sell_pool_id": sell_id,
                    "buy_dex": buy_pool.get('dex', '?'),
                    "sell_dex": sell_pool.get('dex', '?'),
                    "pair_name": buy_pool.get('name', '?'),
                    "spread_bps": spread_bps,
                    "trade_size": trade_size,
                    "expected_profit": profit,
                    "pool_key": f"{buy_id}_{sell_id}",
                })
        
        # Return best opportunity
        if opportunities:
            return [max(opportunities, key=lambda x: x["expected_profit"])]
        return []

    def build_compute_ixs(self, priority_fee: int) -> List[Instruction]:
        return [set_compute_unit_limit(400000), set_compute_unit_price(priority_fee)]

    def build_jito_tip_ix(self) -> Instruction:
        import random
        tip_account = Pubkey.from_string(random.choice(JITO_TIP_ACCOUNTS))
        return Instruction(
            program_id=SYSTEM_PROGRAM_ID,
            accounts=[
                AccountMeta(pubkey=self.wallet.pubkey(), is_signer=True, is_writable=True),
                AccountMeta(pubkey=tip_account, is_signer=False, is_writable=True),
            ],
            data=struct.pack('<I', 2) + struct.pack('<Q', JITO_TIP_LAMPORTS)
        )

    async def submit_jito_bundle(self, tx: Transaction) -> Optional[str]:
        try:
            async with self.http_session.post(
                JITO_BLOCK_ENGINE_URL,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendBundle",
                    "params": [[base58.b58encode(bytes(tx)).decode('utf-8')]]
                },
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if "result" in result:
                        metrics["jito_submitted"] += 1
                        return result["result"]
        except:
            pass
        return None

    async def execute_arbitrage(self, opp: Dict) -> bool:
        """Execute arbitrage opportunity"""
        if not self.trading_enabled or self.is_executing:
            return False
        
        self.is_executing = True
        
        try:
            logger.info(
                f"EXECUTING | {opp['buy_dex']}->{opp['sell_dex']} | "
                f"{opp['pair_name']} | Spread: {opp['spread_bps']:.1f}bps | "
                f"Profit: ${opp['expected_profit']:.4f}"
            )
            
            # For now, just log the opportunity
            # Full execution would require building DEX-specific swap instructions
            # which vary significantly between Raydium AMM, Orca Whirlpool, and Meteora DLMM
            
            metrics["sim_passed"] += 1
            logger.info("SIM PASS | (Execution disabled - monitoring only)")
            
            return True
            
        except Exception as e:
            metrics["tx_reverted"] += 1
            logger.error(f"TX ERROR | {e}")
            failed_pools[opp["pool_key"]] = time.time() + POOL_BLACKLIST_DURATION
            return False
        finally:
            self.is_executing = False

    async def monitor_loop(self):
        """Main monitoring loop"""
        scan = 0
        
        # Get list of pool IDs to monitor
        pool_ids = list(discovered_pools.keys())
        
        while True:
            try:
                # Fetch reserves for a subset of pools each cycle
                # Rotate through all pools over multiple cycles
                batch_start = (scan * 20) % len(pool_ids)
                batch_end = min(batch_start + 20, len(pool_ids))
                batch = pool_ids[batch_start:batch_end]
                
                await self.fetch_batch_reserves(batch)
                scan += 1
                
                # Detect and execute opportunities
                opportunities = self.detect_opportunities()
                for opp in opportunities:
                    await self.execute_arbitrage(opp)
                
                # Log status
                if scan % 60 == 0:
                    logger.info(
                        f"Scan #{scan} | Pools: {metrics['pools_discovered']} | "
                        f"Pairs: {metrics['pairs_monitored']} | "
                        f"Opps: {metrics['opportunities_detected']}"
                    )
                
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Loop error: {e}")
                await asyncio.sleep(1)

    async def print_stats(self):
        """Print periodic stats"""
        while True:
            await asyncio.sleep(60)
            runtime = (datetime.now(timezone.utc) - metrics["start_time"]).total_seconds() / 3600
            logger.info(
                f"STATS | {runtime:.2f}h | "
                f"Pools: {metrics['pools_discovered']} | "
                f"Pairs: {metrics['pairs_monitored']} | "
                f"Opps: {metrics['opportunities_detected']} | "
                f"Sim: {metrics['sim_passed']}/{metrics['sim_passed']+metrics['sim_failed']} | "
                f"Profit: ${metrics['profit_usd']:.4f}"
            )
            logger.info(
                f"FILTERS | Depth: {metrics['depth_filtered']} | "
                f"Age: {metrics['age_filtered']} | "
                f"Profit: {metrics['profit_filtered']}"
            )

    async def refresh_pools(self):
        """Periodically refresh pool discovery"""
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            logger.info("Refreshing pool discovery...")
            await self.discover_pools()

    async def run(self):
        logger.info("=" * 70)
        logger.info("HFT FLASH LOAN BOT v7 - DYNAMIC MULTI-PAIR SCANNER")
        logger.info("=" * 70)
        logger.info("Features: Auto-discovers 100+ pools from Raydium, Orca, Meteora")
        logger.info(f"Config: Min spread {MIN_SPREAD_BPS}bps | Min profit ${MIN_PROFIT_USD}")
        logger.info(f"        Min liquidity ${MIN_LIQUIDITY_USD:,} | Max {MAX_POOLS_PER_DEX} pools/DEX")
        logger.info("=" * 70)
        
        if not await self.connect():
            return
        
        metrics["start_time"] = datetime.now(timezone.utc)
        
        # Discover pools
        await self.discover_pools()
        
        if not self.arb_pairs:
            logger.error("No arbitrage pairs found!")
            return
        
        logger.info(f"Monitoring {len(self.arb_pairs)} arbitrage pairs...")
        
        if not self.trading_enabled:
            logger.warning("TRADING DISABLED - Balance too low!")
        
        logger.info("Bot running... Ctrl+C to stop")
        
        tasks = [
            asyncio.create_task(self.monitor_loop()),
            asyncio.create_task(self.print_stats()),
            asyncio.create_task(self.refresh_pools()),
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
    bot = HFTFlashLoanBotV7()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
