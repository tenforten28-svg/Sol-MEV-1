"""
LIVE TRADING ENGINE - Real-Time Arbitrage Execution
====================================================
- Monitors 4 pools across Raydium, Orca, Meteora
- Detects spreads via WebSocket
- Executes trades via Jito bundles
- Uses flash loans for zero-capital trading
- LIVE TRADING MODE
"""

import asyncio
import base64
import struct
import time
import os
import logging
import random
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime, timezone

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.transaction import Transaction
from solders.message import Message
from solders.compute_budget import set_compute_unit_price, set_compute_unit_limit
from solana.rpc.websocket_api import connect
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
import aiohttp
import base58
from dotenv import load_dotenv

load_dotenv()

# ==============================
# LOGGING
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s'
)
logger = logging.getLogger('live_trader')

# ==============================
# CONFIG
# ==============================

WSS_ENDPOINT = os.environ.get('QUICKNODE_WSS_URL', 'wss://api.mainnet-beta.solana.com')
RPC_ENDPOINT = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Override devnet
if 'devnet' in WSS_ENDPOINT.lower():
    WSS_ENDPOINT = 'wss://api.mainnet-beta.solana.com'
if 'devnet' in RPC_ENDPOINT.lower():
    RPC_ENDPOINT = 'https://api.mainnet-beta.solana.com'

# ==============================
# POOL CONFIGURATIONS - 4 POOLS
# ==============================

POOLS = {
    # === SOL/USDC POOLS ===
    "raydium_sol_usdc": {
        "address": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
        "base_vault": "DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz",
        "quote_vault": "HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz",
        "base_mint": "So11111111111111111111111111111111111111112",
        "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "base_decimals": 9,
        "quote_decimals": 6,
        "dex": "raydium",
        "fee_bps": 25,
        "pair": "SOL/USDC"
    },
    "orca_sol_usdc": {
        "address": "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
        "base_vault": "3YQm7ujtXWJU2e9jhp2QGHpnn1ShXn12QjvzMvDgabpX",
        "quote_vault": "2JTw1fE2wz1SymWUQ7UqpVtrTuKjcd6mWwYwUJUCh2rq",
        "base_mint": "So11111111111111111111111111111111111111112",
        "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "base_decimals": 9,
        "quote_decimals": 6,
        "dex": "orca",
        "fee_bps": 30,
        "pair": "SOL/USDC"
    },
    
    # === BONK/SOL POOLS ===
    "raydium_bonk_sol": {
        "address": "Hni4cvLdJmrCT1MkbZZBJZC7RRDdVeTpQ2m3pm9GXnfH",
        "base_vault": "ErcxwkPgLdyoVL6j2SsekZ5iysPZEDRGfAggh282kQb8",
        "quote_vault": "EDukSdAegSfUCT3PL7Jg7pPxzYDgG4cf8S3B9Hx8BqDe",
        "base_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "quote_mint": "So11111111111111111111111111111111111111112",
        "base_decimals": 5,
        "quote_decimals": 9,
        "dex": "raydium",
        "fee_bps": 25,
        "pair": "BONK/SOL"
    },
    "orca_bonk_sol": {
        "address": "Dqk7mHQBx2ZWExmyrR2S8X6UG75CrbbpK2FSBZsNYsw6",
        "base_vault": "CekFbTf3MvYRVCNnTtPKcvogqPVABfzETFfXnPjGMK1q",
        "quote_vault": "G3q2zUe2V4eSTWrkhVPjz95gHaEXkrTivr8LQUsUjWYz",
        "base_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "quote_mint": "So11111111111111111111111111111111111111112",
        "base_decimals": 5,
        "quote_decimals": 9,
        "dex": "orca",
        "fee_bps": 30,
        "pair": "BONK/SOL"
    },
}

# Group pools by trading pair for arbitrage
ARBITRAGE_PAIRS = {
    "SOL/USDC": ["raydium_sol_usdc", "orca_sol_usdc"],
    "BONK/SOL": ["raydium_bonk_sol", "orca_bonk_sol"],
}

# ==============================
# TRADING PARAMETERS
# ==============================

MIN_SPREAD_BPS = 8          # Minimum spread to execute
MIN_PROFIT_USD = 0.05       # Minimum profit in USD
MAX_TRADE_USD = 1000        # Maximum trade size
SLIPPAGE_BPS = 50           # Slippage tolerance
FLASH_LOAN_FEE_BPS = 30     # Solend flash loan fee

# ==============================
# PROGRAM IDS
# ==============================

RAYDIUM_AMM_PROGRAM = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
ORCA_WHIRLPOOL_PROGRAM = Pubkey.from_string("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc")
SOLEND_PROGRAM = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo")
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111111111111")

# Solend USDC Reserve for flash loans
SOLEND_USDC_RESERVE = {
    'reserve': Pubkey.from_string("BgxfHJDzm44T7XG68MYKx7YisTjZu73tVovyZSjJMpmw"),
    'liquidity_supply': Pubkey.from_string("8SheGtsopRUDzdiD6v6BR9a6bqZ9QwywYQY99Fp5meNf"),
    'fee_receiver': Pubkey.from_string("5Gdxn4yquneifE6uk9tK8XSXR5RGBdJGSHsZfZpY2ZtE"),
    'lending_market': Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"),
    'lending_market_authority': Pubkey.from_string("DdZR6zRFiUt4S5mg7AV1uKB2z1f1WzcNYCaTEEWPAuby"),
}

# ==============================
# JITO MEV PROTECTION
# ==============================

JITO_BLOCK_ENGINE_URL = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
JITO_TIP_LAMPORTS = 10000  # 0.00001 SOL tip
JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4bVGb4pYrGdNLsmQYEzVHXU",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
]

# ==============================
# STATE
# ==============================

@dataclass
class PoolState:
    pool_name: str
    base_reserve: int = 0
    quote_reserve: int = 0
    price: float = 0.0
    last_update: float = 0
    slot: int = 0

balances: Dict[str, int] = {}
pool_states: Dict[str, PoolState] = {}
subscription_map: Dict[int, str] = {}
address_to_pool: Dict[str, tuple] = {}

stats = {
    "updates": 0,
    "opportunities": 0,
    "trades_attempted": 0,
    "trades_success": 0,
    "trades_failed": 0,
    "total_profit": 0.0,
    "start_time": time.time()
}

# Execution lock
is_executing = False

# ==============================
# WALLET & RPC
# ==============================

wallet: Optional[Keypair] = None
rpc_client: Optional[AsyncClient] = None
http_session: Optional[aiohttp.ClientSession] = None
token_accounts: Dict[str, Pubkey] = {}

# ==============================
# HELPERS
# ==============================

def decode_token_balance(data_base64: str) -> int:
    """Decode SPL Token account balance"""
    data = base64.b64decode(data_base64)
    if len(data) < 72:
        return 0
    return struct.unpack_from("<Q", data, offset=64)[0]


def calculate_price(base: int, quote: int, base_dec: int, quote_dec: int) -> float:
    """Calculate price from reserves"""
    if base == 0:
        return 0.0
    return (quote / 10**quote_dec) / (base / 10**base_dec)


def calculate_spread_bps(price1: float, price2: float) -> float:
    """Calculate spread in basis points"""
    if price1 == 0 or price2 == 0:
        return 0.0
    return abs(price1 - price2) / min(price1, price2) * 10000


def calculate_swap_out(amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int) -> int:
    """Constant product swap output"""
    if reserve_in == 0 or reserve_out == 0:
        return 0
    amount_after_fee = amount_in * (10000 - fee_bps) // 10000
    return (amount_after_fee * reserve_out) // (reserve_in + amount_after_fee)


def calculate_profit(amount_in: int, buy_pool: str, sell_pool: str) -> float:
    """Calculate expected profit in USD"""
    buy_state = pool_states.get(buy_pool)
    sell_state = pool_states.get(sell_pool)
    buy_config = POOLS.get(buy_pool, {})
    sell_config = POOLS.get(sell_pool, {})
    
    if not buy_state or not sell_state:
        return -999
    
    # Buy: quote -> base
    base_out = calculate_swap_out(
        amount_in,
        buy_state.quote_reserve,
        buy_state.base_reserve,
        buy_config.get('fee_bps', 30)
    )
    
    if base_out == 0:
        return -999
    
    # Sell: base -> quote
    quote_out = calculate_swap_out(
        base_out,
        sell_state.base_reserve,
        sell_state.quote_reserve,
        sell_config.get('fee_bps', 30)
    )
    
    # Subtract flash loan fee
    flash_fee = amount_in * FLASH_LOAN_FEE_BPS // 10000
    
    profit_raw = quote_out - amount_in - flash_fee
    return profit_raw / 10**buy_config.get('quote_decimals', 6)


# ==============================
# INITIALIZATION
# ==============================

async def initialize():
    """Initialize wallet, RPC, and token accounts"""
    global wallet, rpc_client, http_session
    
    # Load wallet
    private_key = os.environ.get('SOLANA_PRIVATE_KEY')
    if not private_key:
        logger.error("❌ SOLANA_PRIVATE_KEY not set in .env!")
        return False
    
    try:
        wallet = Keypair.from_bytes(base58.b58decode(private_key))
        logger.info(f"✓ Wallet loaded: {wallet.pubkey()}")
    except Exception as e:
        logger.error(f"❌ Wallet error: {e}")
        return False
    
    # Initialize RPC client
    rpc_client = AsyncClient(RPC_ENDPOINT, commitment=Confirmed)
    http_session = aiohttp.ClientSession()
    
    # Find token accounts
    ata_program = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
    
    known_mints = {
        "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "SOL": "So11111111111111111111111111111111111111112",
        "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    }
    
    for name, mint_str in known_mints.items():
        try:
            mint = Pubkey.from_string(mint_str)
            ata, _ = Pubkey.find_program_address(
                [bytes(wallet.pubkey()), bytes(TOKEN_PROGRAM), bytes(mint)],
                ata_program
            )
            token_accounts[name] = ata
            token_accounts[mint_str] = ata
        except:
            pass
    
    logger.info(f"✓ Found {len(token_accounts)} token accounts")
    
    # Check USDC balance
    try:
        resp = await rpc_client.get_token_account_balance(token_accounts["USDC"])
        if resp.value:
            balance = int(resp.value.amount) / 10**6
            logger.info(f"✓ USDC Balance: ${balance:.2f}")
    except:
        pass
    
    return True


# ==============================
# EXECUTION ENGINE
# ==============================

async def execute_arbitrage(buy_pool: str, sell_pool: str, spread_bps: float, expected_profit: float):
    """Execute arbitrage trade"""
    global is_executing
    
    if is_executing:
        return
    
    is_executing = True
    stats["trades_attempted"] += 1
    
    try:
        buy_config = POOLS[buy_pool]
        sell_config = POOLS[sell_pool]
        
        logger.info("=" * 60)
        logger.info("🚀 EXECUTING ARBITRAGE")
        logger.info(f"   Buy:    {buy_pool} ({buy_config['dex']})")
        logger.info(f"   Sell:   {sell_pool} ({sell_config['dex']})")
        logger.info(f"   Spread: {spread_bps:.2f} bps")
        logger.info(f"   Expected Profit: ${expected_profit:.4f}")
        logger.info("=" * 60)
        
        # Calculate optimal trade size
        quote_decimals = buy_config['quote_decimals']
        trade_size = int(MAX_TRADE_USD * 10**quote_decimals)
        
        # Build transaction
        instructions = []
        
        # 1. Compute budget (priority fee)
        priority_fee = 100000 if expected_profit > 1 else 50000
        instructions.append(set_compute_unit_limit(400000))
        instructions.append(set_compute_unit_price(priority_fee))
        
        # 2. Flash loan borrow (Solend)
        instructions.append(build_flash_loan_borrow(trade_size))
        
        # 3. Buy swap
        buy_ix = build_swap_instruction(buy_pool, trade_size, is_buy=True)
        if buy_ix:
            instructions.append(buy_ix)
        
        # 4. Sell swap
        sell_ix = build_swap_instruction(sell_pool, trade_size, is_buy=False)
        if sell_ix:
            instructions.append(sell_ix)
        
        # 5. Flash loan repay
        instructions.append(build_flash_loan_repay(trade_size))
        
        # 6. Jito tip
        instructions.append(build_jito_tip())
        
        # Build and send transaction
        recent_blockhash = await rpc_client.get_latest_blockhash()
        msg = Message.new_with_blockhash(
            instructions,
            wallet.pubkey(),
            recent_blockhash.value.blockhash
        )
        tx = Transaction([wallet], msg, recent_blockhash.value.blockhash)
        
        # Simulate first
        sim_result = await rpc_client.simulate_transaction(tx)
        if sim_result.value.err:
            logger.warning(f"❌ Simulation failed: {sim_result.value.err}")
            stats["trades_failed"] += 1
            return
        
        logger.info("✓ Simulation passed")
        
        # Submit via Jito
        bundle_id = await submit_jito_bundle(tx)
        
        if bundle_id:
            logger.info(f"✓ JITO Bundle submitted: {bundle_id}")
            stats["trades_success"] += 1
            stats["total_profit"] += expected_profit
        else:
            # Fallback to regular RPC
            result = await rpc_client.send_transaction(tx)
            if result.value:
                logger.info(f"✓ TX sent: {result.value}")
                stats["trades_success"] += 1
                stats["total_profit"] += expected_profit
            else:
                logger.warning("❌ TX failed")
                stats["trades_failed"] += 1
        
    except Exception as e:
        logger.error(f"❌ Execution error: {e}")
        stats["trades_failed"] += 1
    finally:
        is_executing = False


def build_flash_loan_borrow(amount: int) -> Instruction:
    """Build Solend flash loan borrow instruction"""
    reserve = SOLEND_USDC_RESERVE
    
    accounts = [
        AccountMeta(pubkey=reserve['liquidity_supply'], is_signer=False, is_writable=True),
        AccountMeta(pubkey=token_accounts.get("USDC", wallet.pubkey()), is_signer=False, is_writable=True),
        AccountMeta(pubkey=reserve['reserve'], is_signer=False, is_writable=True),
        AccountMeta(pubkey=reserve['lending_market'], is_signer=False, is_writable=False),
        AccountMeta(pubkey=reserve['lending_market_authority'], is_signer=False, is_writable=False),
        AccountMeta(pubkey=wallet.pubkey(), is_signer=True, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
    ]
    
    data = struct.pack('<B', 18) + struct.pack('<Q', amount)
    
    return Instruction(program_id=SOLEND_PROGRAM, accounts=accounts, data=data)


def build_flash_loan_repay(amount: int) -> Instruction:
    """Build Solend flash loan repay instruction"""
    reserve = SOLEND_USDC_RESERVE
    fee = amount * FLASH_LOAN_FEE_BPS // 10000
    repay_amount = amount + fee
    
    accounts = [
        AccountMeta(pubkey=token_accounts.get("USDC", wallet.pubkey()), is_signer=False, is_writable=True),
        AccountMeta(pubkey=reserve['liquidity_supply'], is_signer=False, is_writable=True),
        AccountMeta(pubkey=reserve['fee_receiver'], is_signer=False, is_writable=True),
        AccountMeta(pubkey=reserve['reserve'], is_signer=False, is_writable=True),
        AccountMeta(pubkey=reserve['lending_market'], is_signer=False, is_writable=False),
        AccountMeta(pubkey=wallet.pubkey(), is_signer=True, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
    ]
    
    data = struct.pack('<B', 19) + struct.pack('<Q', repay_amount)
    
    return Instruction(program_id=SOLEND_PROGRAM, accounts=accounts, data=data)


def build_swap_instruction(pool_name: str, amount: int, is_buy: bool) -> Optional[Instruction]:
    """Build swap instruction for pool"""
    config = POOLS.get(pool_name, {})
    dex = config.get('dex')
    
    if dex == 'raydium':
        return build_raydium_swap(pool_name, amount, is_buy)
    elif dex == 'orca':
        return build_orca_swap(pool_name, amount, is_buy)
    
    return None


def build_raydium_swap(pool_name: str, amount: int, is_buy: bool) -> Instruction:
    """Build Raydium AMM swap"""
    config = POOLS[pool_name]
    
    pool_id = Pubkey.from_string(config['address'])
    base_vault = Pubkey.from_string(config['base_vault'])
    quote_vault = Pubkey.from_string(config['quote_vault'])
    
    user_base = token_accounts.get(config['base_mint'], wallet.pubkey())
    user_quote = token_accounts.get(config['quote_mint'], wallet.pubkey())
    
    if is_buy:
        source_vault = quote_vault
        dest_vault = base_vault
        user_source = user_quote
        user_dest = user_base
    else:
        source_vault = base_vault
        dest_vault = quote_vault
        user_source = user_base
        user_dest = user_quote
    
    min_out = int(amount * (10000 - SLIPPAGE_BPS) // 10000)
    
    accounts = [
        AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=pool_id, is_signer=False, is_writable=True),
        AccountMeta(pubkey=wallet.pubkey(), is_signer=False, is_writable=False),
        AccountMeta(pubkey=wallet.pubkey(), is_signer=False, is_writable=False),
        AccountMeta(pubkey=wallet.pubkey(), is_signer=False, is_writable=False),
        AccountMeta(pubkey=source_vault, is_signer=False, is_writable=True),
        AccountMeta(pubkey=dest_vault, is_signer=False, is_writable=True),
        AccountMeta(pubkey=user_source, is_signer=False, is_writable=True),
        AccountMeta(pubkey=user_dest, is_signer=False, is_writable=True),
        AccountMeta(pubkey=wallet.pubkey(), is_signer=True, is_writable=False),
    ]
    
    data = struct.pack('<B', 9) + struct.pack('<Q', amount) + struct.pack('<Q', min_out)
    
    return Instruction(program_id=RAYDIUM_AMM_PROGRAM, accounts=accounts, data=data)


def build_orca_swap(pool_name: str, amount: int, is_buy: bool) -> Instruction:
    """Build Orca Whirlpool swap"""
    config = POOLS[pool_name]
    
    pool_id = Pubkey.from_string(config['address'])
    vault_a = Pubkey.from_string(config['base_vault'])
    vault_b = Pubkey.from_string(config['quote_vault'])
    
    user_base = token_accounts.get(config['base_mint'], wallet.pubkey())
    user_quote = token_accounts.get(config['quote_mint'], wallet.pubkey())
    
    min_out = int(amount * (10000 - SLIPPAGE_BPS) // 10000)
    
    accounts = [
        AccountMeta(pubkey=TOKEN_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(pubkey=wallet.pubkey(), is_signer=True, is_writable=False),
        AccountMeta(pubkey=pool_id, is_signer=False, is_writable=True),
        AccountMeta(pubkey=user_quote if is_buy else user_base, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_b if is_buy else vault_a, is_signer=False, is_writable=True),
        AccountMeta(pubkey=user_base if is_buy else user_quote, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_a if is_buy else vault_b, is_signer=False, is_writable=True),
    ]
    
    discriminator = bytes([0xf8, 0xc6, 0x9e, 0x91, 0xe1, 0x75, 0x87, 0xc8])
    data = discriminator + struct.pack('<Q', amount) + struct.pack('<Q', min_out) + struct.pack('<Q', 0)
    
    return Instruction(program_id=ORCA_WHIRLPOOL_PROGRAM, accounts=accounts, data=data)


def build_jito_tip() -> Instruction:
    """Build Jito tip instruction"""
    tip_account = Pubkey.from_string(random.choice(JITO_TIP_ACCOUNTS))
    
    accounts = [
        AccountMeta(pubkey=wallet.pubkey(), is_signer=True, is_writable=True),
        AccountMeta(pubkey=tip_account, is_signer=False, is_writable=True),
    ]
    
    data = struct.pack('<I', 2) + struct.pack('<Q', JITO_TIP_LAMPORTS)
    
    return Instruction(program_id=SYSTEM_PROGRAM, accounts=accounts, data=data)


async def submit_jito_bundle(tx: Transaction) -> Optional[str]:
    """Submit transaction via Jito"""
    try:
        async with http_session.post(
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
                    return result["result"]
    except Exception as e:
        logger.debug(f"Jito error: {e}")
    return None


# ==============================
# WEBSOCKET LISTENER
# ==============================

async def websocket_listener():
    """Listen to vault updates via WebSocket"""
    
    # Build address mappings
    for pool_name, config in POOLS.items():
        address_to_pool[config['base_vault']] = (pool_name, 'base')
        address_to_pool[config['quote_vault']] = (pool_name, 'quote')
        pool_states[pool_name] = PoolState(pool_name=pool_name)
    
    reconnect_delay = 1
    pending_subscriptions = []
    
    while True:
        try:
            logger.info(f"Connecting to WebSocket...")
            
            async with connect(WSS_ENDPOINT) as websocket:
                logger.info("✓ Connected!")
                reconnect_delay = 1
                pending_subscriptions.clear()
                
                # Subscribe to all vaults
                for pool_name, config in POOLS.items():
                    for vault_type in ['base_vault', 'quote_vault']:
                        address = config[vault_type]
                        await websocket.account_subscribe(
                            Pubkey.from_string(address),
                            commitment="processed",
                            encoding="base64"
                        )
                        pending_subscriptions.append((pool_name, vault_type, address))
                        logger.info(f"  📤 {pool_name} {vault_type[:4]}")
                
                logger.info(f"\n⏳ Waiting for {len(pending_subscriptions)} confirmations...")
                
                sub_index = 0
                
                # Process messages
                async for msg in websocket:
                    if isinstance(msg, list):
                        for item in msg:
                            item_type = type(item).__name__
                            
                            # Handle subscription confirmation
                            if item_type == 'SubscriptionResult':
                                if sub_index < len(pending_subscriptions):
                                    pool_name, vault_type, address = pending_subscriptions[sub_index]
                                    subscription_map[item.result] = address
                                    logger.info(f"  ✓ {pool_name} {vault_type[:4]} (id:{item.result})")
                                    sub_index += 1
                                    if sub_index == len(pending_subscriptions):
                                        logger.info(f"\n✅ Subscribed to {len(subscription_map)} vaults")
                                        logger.info("🔴 LIVE TRADING ENABLED\n")
                            
                            # Handle account update
                            elif item_type == 'AccountNotification':
                                await process_account_update(item)
                    
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)


async def process_account_update(notification):
    """Process account notification and check for arb"""
    try:
        sub_id = notification.subscription
        result = notification.result
        
        address = subscription_map.get(sub_id)
        if not address:
            return
        
        pool_info = address_to_pool.get(address)
        if not pool_info:
            return
        
        pool_name, vault_type = pool_info
        
        # Get data
        value = result.value
        if not value:
            return
        
        data = value.data
        if not data:
            return
        
        # Parse amount from bytes (SPL Token account: amount at bytes 64-72)
        amount = 0
        if isinstance(data, bytes) and len(data) >= 72:
            amount = int.from_bytes(data[64:72], 'little')
        elif isinstance(data, (list, tuple)) and len(data) >= 72:
            amount = int.from_bytes(bytes(data)[64:72], 'little')
        elif isinstance(data, str):
            # Base64 encoded
            decoded = base64.b64decode(data)
            if len(decoded) >= 72:
                amount = int.from_bytes(decoded[64:72], 'little')
        
        if amount == 0:
            return
        
        # Update state
        state = pool_states[pool_name]
        config = POOLS[pool_name]
        
        if vault_type == 'base':
            state.base_reserve = amount
        else:
            state.quote_reserve = amount
        
        state.last_update = time.time()
        balances[address] = amount
        stats["updates"] += 1
        
        # Calculate price if we have both reserves
        if state.base_reserve > 0 and state.quote_reserve > 0:
            state.price = calculate_price(
                state.base_reserve, state.quote_reserve,
                config['base_decimals'], config['quote_decimals']
            )
            
            # Check for arbitrage
            await check_arbitrage()
        
    except Exception as e:
        logger.error(f"Update error: {e}")


async def check_arbitrage():
    """Check all pairs for arbitrage opportunities"""
    for pair_name, pools in ARBITRAGE_PAIRS.items():
        if len(pools) < 2:
            continue
        
        # Get valid pool states
        valid_pools = []
        for pool_name in pools:
            state = pool_states.get(pool_name)
            if state and state.price > 0 and (time.time() - state.last_update) < 2:
                valid_pools.append((pool_name, state))
        
        if len(valid_pools) < 2:
            continue
        
        # Compare prices
        for i in range(len(valid_pools)):
            for j in range(i + 1, len(valid_pools)):
                pool1_name, state1 = valid_pools[i]
                pool2_name, state2 = valid_pools[j]
                
                spread_bps = calculate_spread_bps(state1.price, state2.price)
                
                if spread_bps < MIN_SPREAD_BPS:
                    continue
                
                # Determine direction
                if state1.price < state2.price:
                    buy_pool, sell_pool = pool1_name, pool2_name
                else:
                    buy_pool, sell_pool = pool2_name, pool1_name
                
                # Calculate profit
                trade_size = int(MAX_TRADE_USD * 10**POOLS[buy_pool]['quote_decimals'])
                profit = calculate_profit(trade_size, buy_pool, sell_pool)
                
                if profit < MIN_PROFIT_USD:
                    continue
                
                stats["opportunities"] += 1
                
                logger.info(f"⚡ {pair_name} | {spread_bps:.1f}bps | ${profit:.4f}")
                
                # EXECUTE!
                await execute_arbitrage(buy_pool, sell_pool, spread_bps, profit)


# ==============================
# STATS PRINTER
# ==============================

async def stats_printer():
    """Print periodic stats"""
    while True:
        await asyncio.sleep(60)
        
        runtime = (time.time() - stats["start_time"]) / 60
        
        logger.info("=" * 60)
        logger.info("📊 TRADING STATS")
        logger.info(f"   Runtime:      {runtime:.1f} min")
        logger.info(f"   Updates:      {stats['updates']}")
        logger.info(f"   Opportunities: {stats['opportunities']}")
        logger.info(f"   Trades:       {stats['trades_success']}/{stats['trades_attempted']}")
        logger.info(f"   Total Profit: ${stats['total_profit']:.4f}")
        logger.info("=" * 60)
        
        # Print current prices
        for pool_name, state in pool_states.items():
            if state.price > 0:
                age = time.time() - state.last_update
                logger.info(f"   {pool_name}: {state.price:.6f} ({age:.1f}s ago)")


# ==============================
# MAIN
# ==============================

async def main():
    logger.info("=" * 60)
    logger.info("🚀 LIVE TRADING ENGINE")
    logger.info("=" * 60)
    logger.info(f"Pools: {len(POOLS)}")
    logger.info(f"Pairs: {list(ARBITRAGE_PAIRS.keys())}")
    logger.info(f"Min Spread: {MIN_SPREAD_BPS} bps")
    logger.info(f"Max Trade: ${MAX_TRADE_USD}")
    logger.info("=" * 60)
    
    # Initialize
    if not await initialize():
        logger.error("Initialization failed!")
        return
    
    # Start tasks
    tasks = [
        asyncio.create_task(websocket_listener()),
        asyncio.create_task(stats_printer()),
    ]
    
    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        pass
    finally:
        if rpc_client:
            await rpc_client.close()
        if http_session:
            await http_session.close()
        
        logger.info("\n" + "=" * 60)
        logger.info("FINAL STATS")
        logger.info(f"Total Profit: ${stats['total_profit']:.4f}")
        logger.info(f"Successful Trades: {stats['trades_success']}")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
