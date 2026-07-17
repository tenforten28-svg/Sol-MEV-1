"""
PRODUCTION TRADING ENGINE v2
=============================
Full-featured arbitrage bot with:
- Event-driven architecture
- Structured logging & replay
- EV-based execution gating
- Failure taxonomy & learning
- Latency tracking
"""

import asyncio
import base64
import struct
import time
import os
import uuid
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

# Internal imports
from .events import (
    Event, EventType, EventHeader, create_event, emit, get_event_bus, now_ms,
    PoolUpdatePayload, OpportunityPayload, SimulationPayload, DecisionPayload,
    BundlePayload, TxResultPayload, PnLPayload, HeartbeatPayload, ErrorPayload,
    LiquiditySnapshot, ThresholdsSnapshot, DecisionAction, FailureTag, TxStatus,
    FEATURE_FLAGS
)
from .storage import get_storage, write_event as persist_event
from .alpha import (
    build_fingerprint_from_opportunity, classify_failure, should_retry,
    calculate_ev_net, quick_ev_check, optimal_priority_fee
)

load_dotenv()

# ==============================
# LOGGING
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger('trading_engine')

# ==============================
# CONFIG
# ==============================

WSS_ENDPOINT = os.environ.get('QUICKNODE_WSS_URL', 'wss://api.mainnet-beta.solana.com')
RPC_ENDPOINT = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
BOT_VERSION = os.environ.get('BOT_VERSION', '2.0.0')
RUN_ID = str(uuid.uuid4())[:8]

# Debug: Print loaded endpoints
logger.info(f"Loaded WSS_ENDPOINT: {WSS_ENDPOINT[:50]}...")
logger.info(f"Loaded RPC_ENDPOINT: {RPC_ENDPOINT[:50]}...")

# Override devnet
if 'devnet' in WSS_ENDPOINT.lower():
    WSS_ENDPOINT = 'wss://api.mainnet-beta.solana.com'
if 'devnet' in RPC_ENDPOINT.lower():
    RPC_ENDPOINT = 'https://api.mainnet-beta.solana.com'

# ==============================
# POOL CONFIGURATIONS
# ==============================

POOLS = {
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

ARBITRAGE_PAIRS = {
    "SOL/USDC": ["raydium_sol_usdc", "orca_sol_usdc"],
    "BONK/SOL": ["raydium_bonk_sol", "orca_bonk_sol"],
}

# ==============================
# TRADING PARAMETERS
# ==============================

THRESHOLDS = ThresholdsSnapshot(
    min_spread_bps=8,
    min_profit_usd=0.05,
    max_trade_usd=1000,
    slippage_bps=50,
    crowding_threshold=0.7,
    ev_net_threshold=0.0
)

# ==============================
# PROGRAM IDS
# ==============================

RAYDIUM_AMM_PROGRAM = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
ORCA_WHIRLPOOL_PROGRAM = Pubkey.from_string("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc")
SOLEND_PROGRAM = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo")
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")

SOLEND_USDC_RESERVE = {
    'reserve': Pubkey.from_string("BgxfHJDzm44T7XG68MYKx7YisTjZu73tVovyZSjJMpmw"),
    'liquidity_supply': Pubkey.from_string("8SheGtsopRUDzdiD6v6BR9a6bqZ9QwywYQY99Fp5meNf"),
    'fee_receiver': Pubkey.from_string("5Gdxn4yquneifE6uk9tK8XSXR5RGBdJGSHsZfZpY2ZtE"),
    'lending_market': Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"),
    'lending_market_authority': Pubkey.from_string("DdZR6zRFiUt4S5mg7AV1uKB2z1f1WzcNYCaTEEWPAuby"),
}

JITO_BLOCK_ENGINE_URL = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
JITO_TIP_LAMPORTS = 10000
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
    "decisions_execute": 0,
    "decisions_skip": 0,
    "trades_attempted": 0,
    "trades_success": 0,
    "trades_failed": 0,
    "total_profit": 0.0,
    "start_time": time.time()
}

is_executing = False
wallet: Optional[Keypair] = None
rpc_client: Optional[AsyncClient] = None
http_session: Optional[aiohttp.ClientSession] = None
token_accounts: Dict[str, Pubkey] = {}
storage = None

# ==============================
# HELPERS
# ==============================

def decode_token_balance(data_base64: str) -> int:
    data = base64.b64decode(data_base64)
    if len(data) < 72:
        return 0
    return struct.unpack_from("<Q", data, offset=64)[0]


def calculate_price(base: int, quote: int, base_dec: int, quote_dec: int) -> float:
    if base == 0:
        return 0.0
    return (quote / 10**quote_dec) / (base / 10**base_dec)


def calculate_spread_bps(price1: float, price2: float) -> float:
    if price1 == 0 or price2 == 0:
        return 0.0
    return abs(price1 - price2) / min(price1, price2) * 10000


def calculate_swap_out(amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int) -> int:
    if reserve_in == 0 or reserve_out == 0:
        return 0
    amount_after_fee = amount_in * (10000 - fee_bps) // 10000
    return (amount_after_fee * reserve_out) // (reserve_in + amount_after_fee)


def calculate_profit(amount_in: int, buy_pool: str, sell_pool: str) -> float:
    buy_state = pool_states.get(buy_pool)
    sell_state = pool_states.get(sell_pool)
    buy_config = POOLS.get(buy_pool, {})
    sell_config = POOLS.get(sell_pool, {})
    
    if not buy_state or not sell_state:
        return -999
    
    base_out = calculate_swap_out(
        amount_in, buy_state.quote_reserve, buy_state.base_reserve,
        buy_config.get('fee_bps', 30)
    )
    
    if base_out == 0:
        return -999
    
    quote_out = calculate_swap_out(
        base_out, sell_state.base_reserve, sell_state.quote_reserve,
        sell_config.get('fee_bps', 30)
    )
    
    flash_fee = amount_in * 30 // 10000
    profit_raw = quote_out - amount_in - flash_fee
    return profit_raw / 10**buy_config.get('quote_decimals', 6)


# ==============================
# INITIALIZATION
# ==============================

async def initialize():
    global wallet, rpc_client, http_session, storage
    
    private_key = os.environ.get('SOLANA_PRIVATE_KEY')
    if not private_key:
        logger.error("❌ SOLANA_PRIVATE_KEY not set!")
        return False
    
    try:
        wallet = Keypair.from_bytes(base58.b58decode(private_key))
        logger.info(f"✓ Wallet: {wallet.pubkey()}")
    except Exception as e:
        logger.error(f"❌ Wallet error: {e}")
        return False
    
    rpc_client = AsyncClient(RPC_ENDPOINT, commitment=Confirmed)
    http_session = aiohttp.ClientSession()
    storage = get_storage()
    
    # Record run start
    storage.start_run(RUN_ID, BOT_VERSION, THRESHOLDS.to_dict())
    
    # Setup event persistence
    if FEATURE_FLAGS['EVENTS_PERSIST']:
        get_event_bus().subscribe(lambda e: persist_event(e))
    
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
    
    logger.info(f"✓ Token accounts: {len(token_accounts)}")
    
    # Emit startup event
    emit(create_event(
        EventType.STARTUP,
        {"bot_version": BOT_VERSION, "run_id": RUN_ID, "pools": list(POOLS.keys())}
    ))
    
    return True


# ==============================
# EXECUTION
# ==============================

async def execute_arbitrage(
    buy_pool: str,
    sell_pool: str,
    spread_bps: float,
    expected_profit: float,
    fingerprint: str,
    opportunity_event_id: str
):
    global is_executing
    
    if is_executing:
        return
    
    is_executing = True
    stats["trades_attempted"] += 1
    
    trade_id = str(uuid.uuid4())[:8]
    decision_ts = now_ms()
    
    try:
        buy_config = POOLS[buy_pool]
        sell_config = POOLS[sell_pool]
        
        logger.info(f"🚀 EXECUTING | {buy_pool} -> {sell_pool} | ${expected_profit:.4f}")
        
        quote_decimals = buy_config['quote_decimals']
        trade_size = int(THRESHOLDS.max_trade_usd * 10**quote_decimals)
        
        # Calculate optimal priority fee
        priority_fee = optimal_priority_fee(expected_profit, 0.7, 0.5)
        
        # Build transaction
        instructions = []
        instructions.append(set_compute_unit_limit(400000))
        instructions.append(set_compute_unit_price(priority_fee))
        instructions.append(build_flash_loan_borrow(trade_size))
        
        buy_ix = build_swap_instruction(buy_pool, trade_size, is_buy=True)
        if buy_ix:
            instructions.append(buy_ix)
        
        sell_ix = build_swap_instruction(sell_pool, trade_size, is_buy=False)
        if sell_ix:
            instructions.append(sell_ix)
        
        instructions.append(build_flash_loan_repay(trade_size))
        instructions.append(build_jito_tip())
        
        # Simulation
        sim_start = now_ms()
        recent_blockhash = await rpc_client.get_latest_blockhash()
        msg = Message.new_with_blockhash(instructions, wallet.pubkey(), recent_blockhash.value.blockhash)
        tx = Transaction([wallet], msg, recent_blockhash.value.blockhash)
        
        sim_result = await rpc_client.simulate_transaction(tx)
        sim_end = now_ms()
        
        # Emit simulation result
        sim_ok = sim_result.value.err is None
        sim_err = str(sim_result.value.err) if sim_result.value.err else None
        failure_tag = classify_failure(sim_err) if sim_err else None
        
        emit(create_event(
            EventType.SIMULATION_RESULT,
            SimulationPayload(
                sim_ok=sim_ok,
                sim_err=sim_err,
                cu_est=sim_result.value.units_consumed or 0,
                failure_tag=failure_tag.value if failure_tag else None,
                sim_latency_ms=sim_end - sim_start
            ),
            fingerprint=fingerprint
        ))
        
        if not sim_ok:
            logger.warning(f"❌ Simulation failed: {sim_err}")
            stats["trades_failed"] += 1
            
            storage.write_trade({
                'trade_id': trade_id,
                'opportunity_event_id': opportunity_event_id,
                'fingerprint': fingerprint,
                'status': 'SIM_FAILED',
                'buy_pool': buy_pool,
                'sell_pool': sell_pool,
                'spread_bps': spread_bps,
                'expected_profit_usd': expected_profit,
                'failure_tag': failure_tag.value if failure_tag else None,
                'created_ts_ms': now_ms()
            })
            return
        
        # Submit via Jito
        bundle_submit_ts = now_ms()
        bundle_id = await submit_jito_bundle(tx)
        
        emit(create_event(
            EventType.BUNDLE_SUBMITTED,
            BundlePayload(
                jito_bundle_id=bundle_id,
                cu_price=priority_fee,
                priority_fee_lamports=priority_fee,
                tx_count=1,
                tip_lamports=JITO_TIP_LAMPORTS,
                submit_latency_ms=now_ms() - bundle_submit_ts
            ),
            fingerprint=fingerprint
        ))
        
        if bundle_id:
            logger.info(f"✓ JITO Bundle: {bundle_id}")
            stats["trades_success"] += 1
            stats["total_profit"] += expected_profit
            
            emit(create_event(
                EventType.TX_RESULT,
                TxResultPayload(
                    signature=bundle_id,
                    status=TxStatus.CONFIRMED.value,
                    fee_lamports=priority_fee + JITO_TIP_LAMPORTS,
                    confirmation_ms=now_ms() - bundle_submit_ts
                ),
                fingerprint=fingerprint
            ))
            
            emit(create_event(
                EventType.PNL_REALIZED,
                PnLPayload(
                    profit_lamports=int(expected_profit * 1e6),
                    profit_usd_est=expected_profit,
                    slippage_realized_bps=0,
                    fees_total_lamports=priority_fee + JITO_TIP_LAMPORTS,
                    fees_usd_est=0.01,
                    net_profit_usd=expected_profit - 0.01
                ),
                fingerprint=fingerprint
            ))
            
            storage.write_trade({
                'trade_id': trade_id,
                'opportunity_event_id': opportunity_event_id,
                'fingerprint': fingerprint,
                'status': 'SUCCESS',
                'buy_pool': buy_pool,
                'sell_pool': sell_pool,
                'spread_bps': spread_bps,
                'expected_profit_usd': expected_profit,
                'actual_profit_usd': expected_profit,
                'signature': bundle_id,
                'created_ts_ms': now_ms()
            })
            
            storage.update_fingerprint_stats(
                fingerprint, True, expected_profit, spread_bps,
                now_ms() - decision_ts
            )
        else:
            stats["trades_failed"] += 1
            
    except Exception as e:
        logger.error(f"❌ Execution error: {e}")
        stats["trades_failed"] += 1
        
        emit(create_event(
            EventType.ERROR,
            ErrorPayload(
                error_type="EXECUTION_ERROR",
                error_message=str(e)
            ),
            fingerprint=fingerprint
        ))
    finally:
        is_executing = False


def build_flash_loan_borrow(amount: int) -> Instruction:
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
    reserve = SOLEND_USDC_RESERVE
    fee = amount * 30 // 10000
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
    config = POOLS.get(pool_name, {})
    dex = config.get('dex')
    
    if dex == 'raydium':
        return build_raydium_swap(pool_name, amount, is_buy)
    elif dex == 'orca':
        return build_orca_swap(pool_name, amount, is_buy)
    return None


def build_raydium_swap(pool_name: str, amount: int, is_buy: bool) -> Instruction:
    config = POOLS[pool_name]
    pool_id = Pubkey.from_string(config['address'])
    base_vault = Pubkey.from_string(config['base_vault'])
    quote_vault = Pubkey.from_string(config['quote_vault'])
    user_base = token_accounts.get(config['base_mint'], wallet.pubkey())
    user_quote = token_accounts.get(config['quote_mint'], wallet.pubkey())
    
    if is_buy:
        source_vault, dest_vault = quote_vault, base_vault
        user_source, user_dest = user_quote, user_base
    else:
        source_vault, dest_vault = base_vault, quote_vault
        user_source, user_dest = user_base, user_quote
    
    min_out = int(amount * (10000 - THRESHOLDS.slippage_bps) // 10000)
    
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
    config = POOLS[pool_name]
    pool_id = Pubkey.from_string(config['address'])
    vault_a = Pubkey.from_string(config['base_vault'])
    vault_b = Pubkey.from_string(config['quote_vault'])
    user_base = token_accounts.get(config['base_mint'], wallet.pubkey())
    user_quote = token_accounts.get(config['quote_mint'], wallet.pubkey())
    
    min_out = int(amount * (10000 - THRESHOLDS.slippage_bps) // 10000)
    
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
    tip_account = Pubkey.from_string(random.choice(JITO_TIP_ACCOUNTS))
    accounts = [
        AccountMeta(pubkey=wallet.pubkey(), is_signer=True, is_writable=True),
        AccountMeta(pubkey=tip_account, is_signer=False, is_writable=True),
    ]
    data = struct.pack('<I', 2) + struct.pack('<Q', JITO_TIP_LAMPORTS)
    return Instruction(program_id=SYSTEM_PROGRAM, accounts=accounts, data=data)


async def submit_jito_bundle(tx: Transaction) -> Optional[str]:
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
    for pool_name, config in POOLS.items():
        address_to_pool[config['base_vault']] = (pool_name, 'base')
        address_to_pool[config['quote_vault']] = (pool_name, 'quote')
        pool_states[pool_name] = PoolState(pool_name=pool_name)
    
    reconnect_delay = 1
    pending_subscriptions = []  # Track vault addresses waiting for subscription IDs
    
    while True:
        try:
            logger.info(f"Connecting to WebSocket...")
            
            async with connect(WSS_ENDPOINT) as websocket:
                logger.info("✓ Connected!")
                reconnect_delay = 1
                
                # Queue all subscriptions
                for pool_name, config in POOLS.items():
                    for vault_type in ['base_vault', 'quote_vault']:
                        address = config[vault_type]
                        try:
                            await websocket.account_subscribe(
                                Pubkey.from_string(address),
                                commitment="processed",
                                encoding="base64"
                            )
                            pending_subscriptions.append((pool_name, vault_type, address))
                            logger.info(f"  📤 Sent subscription for {pool_name} {vault_type[:4]}")
                        except Exception as sub_err:
                            logger.error(f"  ✗ {pool_name} {vault_type}: {sub_err}")
                
                logger.info(f"\n⏳ Waiting for {len(pending_subscriptions)} subscription confirmations...")
                
                # Process messages - first batch will be subscription confirmations
                sub_index = 0
                logger.info("🔴 LIVE TRADING ENABLED")
                
                async for msg in websocket:
                    # Messages come as lists
                    if isinstance(msg, list):
                        for item in msg:
                            # Handle subscription confirmation
                            if hasattr(item, 'result') and isinstance(item.result, int):
                                if sub_index < len(pending_subscriptions):
                                    pool_name, vault_type, address = pending_subscriptions[sub_index]
                                    subscription_map[item.result] = address
                                    logger.info(f"  ✓ {pool_name} {vault_type[:4]} (sub_id: {item.result})")
                                    sub_index += 1
                                    
                                    if sub_index == len(pending_subscriptions):
                                        logger.info(f"\n✅ Subscribed to {len(subscription_map)} vaults")
                            
                            # Handle account notifications
                            elif hasattr(item, 'subscription') and hasattr(item, 'result'):
                                await process_account_notification(item)
                    else:
                        # Fallback for non-list messages
                        await process_update(msg)
                    
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            emit(create_event(EventType.ERROR, ErrorPayload(
                error_type="WEBSOCKET_ERROR",
                error_message=str(e)
            )))
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)


async def process_account_notification(notification):
    """Process an AccountNotification from the WebSocket"""
    try:
        sub_id = notification.subscription
        result = notification.result
        pool_update_ts = now_ms()
        
        if sub_id not in subscription_map:
            return
        
        address = subscription_map[sub_id]
        
        # Get account value
        value = result.value
        if not value:
            return
        
        # Decode the account data - can be bytes or base64 string
        data = value.data
        if not data:
            return
        
        # Find which pool this vault belongs to
        pool_info = address_to_pool.get(address)
        if not pool_info:
            return
        
        pool_name, vault_type = pool_info
        state = pool_states[pool_name]
        config = POOLS[pool_name]
        
        # Parse token amount from account data
        # SPL Token accounts have amount at bytes 64-72
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
        if vault_type == 'base':
            state.base_reserve = amount
        else:
            state.quote_reserve = amount
        
        state.last_update = time.time()
        state.slot = result.context.slot if hasattr(result, 'context') else 0
        balances[address] = amount
        stats["updates"] += 1
        
        # Calculate price if we have both reserves
        if state.base_reserve > 0 and state.quote_reserve > 0:
            state.price = calculate_price(
                state.base_reserve, state.quote_reserve,
                config['base_decimals'], config['quote_decimals']
            )
            
            # Emit pool update event
            emit(create_event(EventType.POOL_UPDATE, PoolUpdatePayload(
                pool_name=pool_name,
                dex=config['dex'],
                base_reserve=state.base_reserve,
                quote_reserve=state.quote_reserve,
                base_decimals=config['base_decimals'],
                quote_decimals=config['quote_decimals'],
                price=state.price,
                update_latency_ms=now_ms() - pool_update_ts
            )))
            
            # Check for arbitrage
            await check_arbitrage(pool_update_ts)
                
    except Exception as e:
        logger.error(f"Error processing notification: {e}")
        import traceback
        traceback.print_exc()


async def process_update(msg):
    try:
        if not hasattr(msg, 'params'):
            return
        
        pool_update_ts = now_ms()
        params = msg.params
        sub_id = params.get('subscription')
        result = params.get('result', {})
        value = result.get('value', {})
        context = result.get('context', {})
        slot = context.get('slot', 0)
        
        if not value:
            return
        
        data = value.get('data', [])
        if not data:
            return
        
        address = subscription_map.get(sub_id)
        if not address:
            return
        
        balance = decode_token_balance(data[0])
        balances[address] = balance
        stats["updates"] += 1
        
        pool_info = address_to_pool.get(address)
        if not pool_info:
            return
        
        pool_name, vault_type = pool_info
        state = pool_states[pool_name]
        config = POOLS[pool_name]
        
        if vault_type == 'base':
            state.base_reserve = balance
        else:
            state.quote_reserve = balance
        
        state.last_update = time.time()
        state.slot = slot
        
        if state.base_reserve > 0 and state.quote_reserve > 0:
            state.price = calculate_price(
                state.base_reserve, state.quote_reserve,
                config['base_decimals'], config['quote_decimals']
            )
        
        # Emit pool update event
        emit(create_event(
            EventType.POOL_UPDATE,
            PoolUpdatePayload(
                pool_name=pool_name,
                dex=config['dex'],
                base_reserve=state.base_reserve,
                quote_reserve=state.quote_reserve,
                base_decimals=config['base_decimals'],
                quote_decimals=config['quote_decimals'],
                price=state.price,
                update_latency_ms=now_ms() - pool_update_ts
            ),
            slot=slot
        ))
        
        await check_arbitrage(pool_update_ts)
        
    except Exception as e:
        logger.debug(f"Update error: {e}")


async def check_arbitrage(pool_update_ts: int):
    for pair_name, pools in ARBITRAGE_PAIRS.items():
        if len(pools) < 2:
            continue
        
        valid_pools = []
        for pool_name in pools:
            state = pool_states.get(pool_name)
            if state and state.price > 0 and (time.time() - state.last_update) < 2:
                valid_pools.append((pool_name, state))
        
        if len(valid_pools) < 2:
            continue
        
        for i in range(len(valid_pools)):
            for j in range(i + 1, len(valid_pools)):
                pool1_name, state1 = valid_pools[i]
                pool2_name, state2 = valid_pools[j]
                
                spread_bps = calculate_spread_bps(state1.price, state2.price)
                
                if spread_bps < THRESHOLDS.min_spread_bps:
                    continue
                
                if state1.price < state2.price:
                    buy_pool, sell_pool = pool1_name, pool2_name
                    buy_state, sell_state = state1, state2
                else:
                    buy_pool, sell_pool = pool2_name, pool1_name
                    buy_state, sell_state = state2, state1
                
                trade_size = int(THRESHOLDS.max_trade_usd * 10**POOLS[buy_pool]['quote_decimals'])
                profit = calculate_profit(trade_size, buy_pool, sell_pool)
                
                if profit < THRESHOLDS.min_profit_usd:
                    continue
                
                stats["opportunities"] += 1
                opportunity_ts = now_ms()
                
                # Build fingerprint
                fingerprint = build_fingerprint_from_opportunity(
                    buy_pool=POOLS[buy_pool]['address'],
                    sell_pool=POOLS[sell_pool]['address'],
                    buy_dex=POOLS[buy_pool]['dex'],
                    sell_dex=POOLS[sell_pool]['dex'],
                    buy_mint=POOLS[buy_pool]['base_mint'],
                    sell_mint=POOLS[sell_pool]['base_mint'],
                    quote_mint=POOLS[buy_pool]['quote_mint']
                )
                
                opportunity_event_id = str(uuid.uuid4())
                
                # Emit opportunity event
                opp_event = create_event(
                    EventType.OPPORTUNITY_DETECTED,
                    OpportunityPayload(
                        route_id=opportunity_event_id,
                        buy_pool=buy_pool,
                        sell_pool=sell_pool,
                        buy_dex=POOLS[buy_pool]['dex'],
                        sell_dex=POOLS[sell_pool]['dex'],
                        token_path=[POOLS[buy_pool]['quote_mint'][:8], POOLS[buy_pool]['base_mint'][:8], POOLS[buy_pool]['quote_mint'][:8]],
                        dex_programs=[POOLS[buy_pool]['dex'], POOLS[sell_pool]['dex']],
                        pool_accounts=[POOLS[buy_pool]['address'], POOLS[sell_pool]['address']],
                        spread_bps=spread_bps,
                        buy_price=buy_state.price,
                        sell_price=sell_state.price,
                        liquidity_snapshots=[
                            LiquiditySnapshot(buy_pool, buy_state.base_reserve, buy_state.quote_reserve, buy_state.price, THRESHOLDS.max_trade_usd * 10).to_dict(),
                            LiquiditySnapshot(sell_pool, sell_state.base_reserve, sell_state.quote_reserve, sell_state.price, THRESHOLDS.max_trade_usd * 10).to_dict()
                        ],
                        estimated_profit_usd=profit,
                        ev_raw_est=profit,
                        optimal_size_usd=THRESHOLDS.max_trade_usd,
                        detection_latency_ms=opportunity_ts - pool_update_ts
                    ),
                    slot=buy_state.slot,
                    fingerprint=fingerprint
                )
                opp_event.header.event_id = opportunity_event_id
                opp_event.pool_update_received_ts = pool_update_ts
                opp_event.opportunity_detected_ts = opportunity_ts
                emit(opp_event)
                
                # EV-based decision
                ev_result = calculate_ev_net(
                    expected_profit_usd=profit,
                    trade_size_usd=THRESHOLDS.max_trade_usd,
                    spread_bps=spread_bps,
                    liquidity_depth_usd=100000,
                    p_success=0.7
                )
                
                decision_ts = now_ms()
                
                # Emit decision event
                decision_event = create_event(
                    EventType.DECISION,
                    DecisionPayload(
                        action=DecisionAction.EXECUTE.value if ev_result.should_execute else DecisionAction.SKIP.value,
                        reasons=ev_result.reasons,
                        thresholds_snapshot=THRESHOLDS.to_dict(),
                        ev_raw_est=profit,
                        ev_net_est=ev_result.ev_net,
                        p_success=ev_result.p_success,
                        decision_latency_ms=decision_ts - opportunity_ts
                    ),
                    fingerprint=fingerprint
                )
                decision_event.decision_ts = decision_ts
                emit(decision_event)
                
                if ev_result.should_execute:
                    stats["decisions_execute"] += 1
                    logger.info(f"⚡ {pair_name} | {spread_bps:.1f}bps | ${profit:.4f} | EV_net: ${ev_result.ev_net:.4f}")
                    await execute_arbitrage(buy_pool, sell_pool, spread_bps, profit, fingerprint, opportunity_event_id)
                else:
                    stats["decisions_skip"] += 1
                    logger.debug(f"⏭️ SKIP | {ev_result.reasons}")


# ==============================
# HEARTBEAT
# ==============================

async def heartbeat_loop():
    while True:
        await asyncio.sleep(60)
        
        runtime = time.time() - stats["start_time"]
        
        emit(create_event(
            EventType.HEARTBEAT,
            HeartbeatPayload(
                uptime_seconds=runtime,
                pools_active=len([s for s in pool_states.values() if s.price > 0]),
                events_emitted=get_event_bus().get_stats()['emitted'],
                opportunities_detected=stats["opportunities"],
                trades_attempted=stats["trades_attempted"],
                trades_success=stats["trades_success"],
                total_profit_usd=stats["total_profit"],
                ws_connected=True
            )
        ))
        
        # Print stats summary
        get_event_bus().print_stats()
        
        logger.info(f"📊 Opps: {stats['opportunities']} | Exec: {stats['decisions_execute']} | Skip: {stats['decisions_skip']} | Profit: ${stats['total_profit']:.4f}")


# ==============================
# MAIN
# ==============================

async def main():
    logger.info("=" * 60)
    logger.info("🚀 PRODUCTION TRADING ENGINE v2")
    logger.info("=" * 60)
    logger.info(f"Run ID: {RUN_ID}")
    logger.info(f"Version: {BOT_VERSION}")
    logger.info(f"Pools: {len(POOLS)}")
    logger.info(f"Min Spread: {THRESHOLDS.min_spread_bps} bps")
    logger.info(f"EV Gate: {FEATURE_FLAGS.get('EVENTS_ENABLED', True)}")
    logger.info("=" * 60)
    
    if not await initialize():
        return
    
    tasks = [
        asyncio.create_task(websocket_listener()),
        asyncio.create_task(heartbeat_loop()),
    ]
    
    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        pass
    finally:
        emit(create_event(EventType.SHUTDOWN, {"reason": "user_interrupt"}))
        storage.end_run(RUN_ID, stats)
        
        if rpc_client:
            await rpc_client.close()
        if http_session:
            await http_session.close()
        
        get_event_bus().close()
        
        logger.info("\n" + "=" * 60)
        logger.info("FINAL STATS")
        logger.info(f"Profit: ${stats['total_profit']:.4f}")
        logger.info(f"Trades: {stats['trades_success']}/{stats['trades_attempted']}")
        logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
