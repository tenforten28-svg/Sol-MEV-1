"""
COMPLETE NEW TOKEN ARBITRAGE BOT
=================================
Full integration of:
- Real-time pool monitoring
- Multi-DEX price tracking
- Arbitrage detection
- Trade execution

Run this file to start the bot.
"""

import asyncio
import os
import sys
import struct
import time
import base64
from typing import Dict, Set, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import logging
from dotenv import load_dotenv

from solana.rpc.websocket_api import connect, RpcTransactionLogsFilterMentions
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from solders.keypair import Keypair
import base58

# AutoHedge AI validation
from autohedge_bridge import validate_cross_dex_opportunity

load_dotenv()

# ==============================
# LOGGING
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    stream=sys.stdout  # Force output to stdout
)
logger = logging.getLogger('arb_bot')
logger.setLevel(logging.INFO)

# Force unbuffered output for Windows
import functools
print = functools.partial(print, flush=True)

# ==============================
# CONFIG
# ==============================
WSS_URL = os.environ.get('QUICKNODE_WSS_URL')
RPC_URL = os.environ.get('SOLANA_RPC_URL')
PRIVATE_KEY = os.environ.get('SOLANA_PRIVATE_KEY')

# Trading config
MIN_SPREAD_BPS = 100  # Minimum 1% spread to trade
MAX_TRADE_SOL = 1.0   # Maximum trade size in SOL (flash loan amount)
MIN_LIQUIDITY = 1000  # Minimum $1000 liquidity
USE_JITO = True       # Use Jito for MEV protection
JITO_TIP = 10000      # 0.00001 SOL tip
USE_FLASH_LOAN = True # Use flash loans (recommended)
FLASH_LOAN_FEE = 0.003  # 0.3% Solend fee

# ==============================
# QUICKNODE CREDIT MANAGEMENT
# ==============================
# Free tier: 10M credits/month = 333,333/day
DAILY_CREDIT_BUDGET = 333_333
HOURLY_CREDIT_BUDGET = DAILY_CREDIT_BUDGET // 24  # ~13,889/hour

# Estimated credit costs per operation
CREDIT_COSTS = {
    'ws_message': 5,        # WebSocket log message
    'get_transaction': 100,  # getTransaction call
    'get_account': 50,       # getAccountInfo call
    'get_program_accounts': 200,  # getProgramAccounts call
}

# Rate limiting settings
MIN_DELAY_BETWEEN_TX_FETCH = 10  # Seconds between transaction fetches (saves credits)
MAX_TX_FETCHES_PER_HOUR = 100    # Max transaction fetches per hour

# Credit tracking
credit_tracker = {
    'daily_used': 0,
    'hourly_used': 0,
    'last_hour_reset': time.time(),
    'last_day_reset': time.time(),
    'tx_fetches_this_hour': 0,
    'paused': False,
}

def use_credits(operation: str, count: int = 1):
    """Track credit usage and enforce limits"""
    global credit_tracker
    
    cost = CREDIT_COSTS.get(operation, 10) * count
    credit_tracker['daily_used'] += cost
    credit_tracker['hourly_used'] += cost
    
    # Reset hourly counter
    if time.time() - credit_tracker['last_hour_reset'] > 3600:
        credit_tracker['hourly_used'] = 0
        credit_tracker['tx_fetches_this_hour'] = 0
        credit_tracker['last_hour_reset'] = time.time()
    
    # Reset daily counter
    if time.time() - credit_tracker['last_day_reset'] > 86400:
        credit_tracker['daily_used'] = 0
        credit_tracker['last_day_reset'] = time.time()
        credit_tracker['paused'] = False
    
    # Check limits
    if credit_tracker['daily_used'] >= DAILY_CREDIT_BUDGET * 0.95:
        if not credit_tracker['paused']:
            logger.warning(f"⚠️ Daily credit limit reached ({credit_tracker['daily_used']:,}/{DAILY_CREDIT_BUDGET:,}). Pausing until tomorrow.")
            credit_tracker['paused'] = True
        return False
    
    if credit_tracker['hourly_used'] >= HOURLY_CREDIT_BUDGET * 0.95:
        logger.debug(f"Hourly limit approaching. Slowing down...")
        return False
    
    return True

def can_fetch_transaction() -> bool:
    """Check if we can fetch another transaction (rate limited)"""
    if credit_tracker['paused']:
        return False
    if credit_tracker['tx_fetches_this_hour'] >= MAX_TX_FETCHES_PER_HOUR:
        return False
    return True

def record_tx_fetch():
    """Record a transaction fetch"""
    credit_tracker['tx_fetches_this_hour'] += 1
    use_credits('get_transaction')

def get_credit_status() -> str:
    """Get current credit usage status"""
    daily_pct = (credit_tracker['daily_used'] / DAILY_CREDIT_BUDGET) * 100
    hourly_pct = (credit_tracker['hourly_used'] / HOURLY_CREDIT_BUDGET) * 100
    return f"Credits: {credit_tracker['daily_used']:,}/{DAILY_CREDIT_BUDGET:,} ({daily_pct:.1f}%) | Hour: {hourly_pct:.1f}%"

# Program IDs
RAYDIUM_AMM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
RAYDIUM_CLMM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
METEORA_DLMM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# ==============================
# DATA STRUCTURES
# ==============================

@dataclass
class Pool:
    address: str
    dex: str
    base_mint: str
    quote_mint: str
    base_vault: Optional[str] = None
    quote_vault: Optional[str] = None
    price: float = 0.0
    liquidity: float = 0.0
    last_update: float = 0.0


@dataclass
class TokenState:
    mint: str
    symbol: str = ""
    pools: Dict[str, Pool] = field(default_factory=dict)
    first_seen: float = field(default_factory=time.time)
    arb_count: int = 0


# Global state
tokens: Dict[str, TokenState] = {}
watched_pools: Dict[str, str] = {}  # pool_address -> token_mint
pending_tokens: asyncio.Queue = asyncio.Queue()  # Initialize immediately
fetch_semaphore: asyncio.Semaphore = None  # Limit concurrent RPC calls
stats = {
    'start_time': time.time(),
    'pools_detected': 0,
    'tokens_found': 0,
    'opportunities': 0,
    'trades_executed': 0,
    'total_profit': 0.0,
    'by_dex': defaultdict(int),
}


# ==============================
# WALLET
# ==============================

def get_wallet() -> Optional[Keypair]:
    """Load wallet from environment - supports Base58, JSON array, and hex formats"""
    if not PRIVATE_KEY:
        logger.warning("No SOLANA_PRIVATE_KEY set - running in monitor-only mode")
        return None
    
    # Clean the key (remove whitespace, quotes)
    clean_key = PRIVATE_KEY.strip().strip('"').strip("'")
    key_len = len(clean_key)
    logger.info(f"   Loading wallet - Key length: {key_len} chars")
    
    # Method 1: Base58 string (most common for Solana wallets)
    try:
        key_bytes = base58.b58decode(clean_key)
        logger.info(f"   Base58 decoded to {len(key_bytes)} bytes")
        
        if len(key_bytes) == 64:
            # Full keypair (private + public)
            wallet = Keypair.from_bytes(key_bytes)
            logger.info(f"   ✅ Wallet loaded (base58-64): {str(wallet.pubkey())[:30]}...")
            return wallet
        elif len(key_bytes) == 32:
            # Seed only - derive full keypair using nacl
            try:
                from nacl.signing import SigningKey
                signing_key = SigningKey(key_bytes)
                full_key = bytes(signing_key) + bytes(signing_key.verify_key)
                wallet = Keypair.from_bytes(full_key)
                logger.info(f"   ✅ Wallet loaded (base58-seed): {str(wallet.pubkey())[:30]}...")
                return wallet
            except ImportError:
                logger.warning("   nacl not installed - cannot derive from 32-byte seed")
        else:
            logger.debug(f"   Base58 decoded to {len(key_bytes)} bytes - expected 32 or 64")
    except Exception as e:
        logger.debug(f"   Base58 decode failed: {e}")
    
    # Method 2: JSON array [1, 2, 3, ...]
    try:
        import json
        key_array = json.loads(clean_key)
        if isinstance(key_array, list) and len(key_array) in [32, 64]:
            key_bytes = bytes(key_array)
            if len(key_bytes) == 32:
                from nacl.signing import SigningKey
                signing_key = SigningKey(key_bytes)
                full_key = bytes(signing_key) + bytes(signing_key.verify_key)
                key_bytes = full_key
            wallet = Keypair.from_bytes(key_bytes)
            logger.info(f"   ✅ Wallet loaded (JSON array): {str(wallet.pubkey())[:30]}...")
            return wallet
    except Exception as e:
        logger.debug(f"   JSON parse failed: {e}")
    
    # Method 3: Comma-separated numbers
    if ',' in clean_key:
        try:
            key_array = [int(x.strip()) for x in clean_key.split(',')]
            if len(key_array) in [32, 64]:
                key_bytes = bytes(key_array)
                if len(key_bytes) == 32:
                    from nacl.signing import SigningKey
                    signing_key = SigningKey(key_bytes)
                    full_key = bytes(signing_key) + bytes(signing_key.verify_key)
                    key_bytes = full_key
                wallet = Keypair.from_bytes(key_bytes)
                logger.info(f"   ✅ Wallet loaded (CSV): {str(wallet.pubkey())[:30]}...")
                return wallet
        except Exception as e:
            logger.debug(f"   CSV parse failed: {e}")
    
    # Method 4: Hex string
    try:
        hex_clean = clean_key.replace('0x', '').replace(' ', '')
        key_bytes = bytes.fromhex(hex_clean)
        if len(key_bytes) in [32, 64]:
            if len(key_bytes) == 32:
                from nacl.signing import SigningKey
                signing_key = SigningKey(key_bytes)
                full_key = bytes(signing_key) + bytes(signing_key.verify_key)
                key_bytes = full_key
            wallet = Keypair.from_bytes(key_bytes)
            logger.info(f"   ✅ Wallet loaded (hex): {str(wallet.pubkey())[:30]}...")
            return wallet
    except Exception as e:
        logger.debug(f"   Hex parse failed: {e}")
    
    logger.error("❌ Invalid private key format. Supported formats:")
    logger.error("   - Base58 string (87 chars for full keypair)")
    logger.error("   - JSON array: [1, 2, 3, ..., 64 numbers]")
    logger.error("   - Comma-separated: 1,2,3,...,64")
    logger.error("   - Hex string: 0x... or plain hex")
    return None


# ==============================
# POOL DETECTION
# ==============================

async def safe_process_pool(signature: str, dex: str):
    """Wrapper to catch errors in background tasks with rate limiting and credit management"""
    global fetch_semaphore
    if fetch_semaphore is None:
        fetch_semaphore = asyncio.Semaphore(1)  # Only 1 concurrent fetch
    
    # Check credit limits before processing
    if credit_tracker['paused']:
        logger.debug(f"Skipping tx fetch - daily credit limit reached")
        return
    
    if not can_fetch_transaction():
        logger.debug(f"Skipping tx fetch - hourly limit reached")
        return
    
    try:
        async with fetch_semaphore:
            # Wait between fetches to save credits
            await asyncio.sleep(MIN_DELAY_BETWEEN_TX_FETCH)
            await process_new_pool(signature, dex)
    except Exception as e:
        print(f"   ❌ Process error for {signature[:20]}: {e}")


async def monitor_new_pools():
    """Monitor for new pool creations"""
    
    print("🔍 Starting pool monitor...")
    print(f"   WSS URL: {WSS_URL[:50] if WSS_URL else 'NOT SET'}...")
    
    reconnect_delay = 1
    connection_count = 0
    
    while True:
        try:
            connection_count += 1
            print(f"🔌 Connecting to WebSocket (attempt #{connection_count})...")
            
            async with connect(WSS_URL) as ws:
                reconnect_delay = 1  # Reset on successful connection
                print("✅ WebSocket connected!")
                
                # Subscribe to DEX programs
                programs = [
                    ("Raydium AMM", RAYDIUM_AMM),
                    ("Raydium CLMM", RAYDIUM_CLMM),
                    ("Meteora DLMM", METEORA_DLMM),
                    ("PumpFun", PUMPFUN),
                ]
                
                for name, program in programs:
                    try:
                        # Use proper filter type
                        mentions_filter = RpcTransactionLogsFilterMentions(Pubkey.from_string(program))
                        await ws.logs_subscribe(
                            filter_=mentions_filter,
                            commitment="confirmed"
                        )
                        print(f"   ✓ {name}")
                    except Exception as e:
                        print(f"   ✗ {name}: {e}")
                
                print("\n🎯 Monitoring for new tokens...\n")
                
                seen_sigs: Set[str] = set()
                ws_message_count = 0
                last_heartbeat = time.time()
                
                async for msg in ws:
                    try:
                        # Heartbeat every 5 minutes
                        if time.time() - last_heartbeat > 300:
                            print(f"💓 Still alive - {ws_message_count} msgs received, {len(tokens)} tokens tracked")
                            last_heartbeat = time.time()
                        
                        # Track WebSocket credits (every 100 messages)
                        ws_message_count += 1
                        if ws_message_count % 100 == 0:
                            use_credits('ws_message', 100)
                        
                        # Check if paused due to credit limit
                        if credit_tracker['paused']:
                            await asyncio.sleep(60)  # Sleep 1 min if paused
                            continue
                        
                        if not isinstance(msg, list):
                            continue
                        
                        for item in msg:
                            if not hasattr(item, 'result'):
                                continue
                            
                            value = getattr(item.result, 'value', None)
                            if not value:
                                continue
                            
                            # Get signature - convert to string if needed
                            signature_raw = getattr(value, 'signature', None)
                            if not signature_raw:
                                continue
                            signature = str(signature_raw)  # Convert Signature object to string
                            
                            logs = getattr(value, 'logs', []) or []
                            
                            if signature in seen_sigs:
                                continue
                            
                            seen_sigs.add(signature)
                            if len(seen_sigs) > 5000:
                                seen_sigs.clear()
                            
                            # Debug: Print first few log entries occasionally
                            stats['pools_detected'] += 1  # Count all transactions
                            
                            if stats['pools_detected'] % 500 == 1:
                                print(f"📨 Sample TX: {signature[:30]}...")
                                for log in logs[:2]:
                                    print(f"   {log[:100]}...")
                            
                            # Check for pool creation in logs
                            dex = None
                            event_type = None
                            
                            for log in logs:
                                log_l = log.lower()
                                
                                # Raydium AMM V4 - initialize
                                if 'initialize2' in log_l or ('initialize' in log_l and '675k' in log_l):
                                    dex = 'raydium_amm'
                                    event_type = 'Raydium AMM'
                                    break
                                
                                # Raydium CLMM - createPool
                                if 'createpool' in log_l or ('create' in log_l and 'pool' in log_l and 'camm' in log_l):
                                    dex = 'raydium_clmm'
                                    event_type = 'Raydium CLMM'
                                    break
                                
                                # Meteora DLMM - initializeLbPair
                                if 'initializelbpair' in log_l or 'initialize_lb_pair' in log_l:
                                    dex = 'meteora_dlmm'
                                    event_type = 'Meteora DLMM'
                                    break
                                
                                # PumpFun - graduation/migration to Raydium
                                if 'graduate' in log_l or 'migration' in log_l or 'bonding' in log_l:
                                    dex = 'pumpfun'
                                    event_type = 'PumpFun'
                                    break
                                
                                # Generic pool creation
                                if ('initializepool' in log_l.replace(' ', '') or 
                                    'createpool' in log_l.replace(' ', '') or
                                    'newpool' in log_l.replace(' ', '')):
                                    dex = 'unknown'
                                    event_type = 'Pool Creation'
                                    break
                            
                            if dex:
                                stats['by_dex'][dex] += 1
                                # Log detection immediately
                                print(f"🆕 {event_type}: {signature[:40]}...")
                                # Process in background to not block WebSocket
                                asyncio.create_task(safe_process_pool(signature, dex))
                                
                    except Exception as e:
                        logger.debug(f"Message error: {e}")
                        
        except asyncio.CancelledError:
            print("Monitor cancelled")
            break
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
            print(f"🔄 Reconnecting in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)


async def process_new_pool(signature: str, dex: str):
    """Process newly detected pool - extract token mints from transaction"""
    from solders.signature import Signature as SolanaSignature
    from solana.exceptions import SolanaRpcException
    
    client = AsyncClient(RPC_URL)
    
    try:
        logger.info(f"   📥 Fetching tx: {signature[:30]}...")
        
        # Convert string signature to Signature object
        sig_obj = SolanaSignature.from_string(signature)
        
        # Retry logic for rate limiting and tx propagation
        max_retries = 3
        tx = None
        
        for attempt in range(max_retries):
            try:
                tx = await client.get_transaction(
                    sig_obj,
                    encoding="jsonParsed",
                    max_supported_transaction_version=0
                )
                if tx and tx.value:
                    break  # Successfully got transaction
                # Transaction not found yet, wait and retry
                logger.debug(f"   Attempt {attempt+1}: tx not found yet")
                await asyncio.sleep(1 + attempt)
            except SolanaRpcException as e:
                if "429" in str(e) or "Too Many Requests" in str(e):
                    # Rate limited - back off
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"   ⚠️ Rate limited, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"   RPC error: {e}")
                    return
            except Exception as e:
                logger.error(f"   Unexpected error fetching tx: {e}")
                return
        
        if not tx or not tx.value:
            logger.warning(f"   ⚠️ Could not fetch tx after {max_retries} attempts")
            return
        
        # Get transaction components
        transaction = tx.value.transaction
        meta = transaction.meta
        
        if not meta:
            logger.warning(f"   ⚠️ No meta in tx: {signature[:20]}")
            return
        
        logger.info(f"   ✓ Got transaction data, parsing...")
        
        quote_tokens = {SOL_MINT, USDC_MINT}
        new_tokens = set()
        
        # ============================================
        # METHOD 1: Post Token Balances (most reliable)
        # ============================================
        post_balances = getattr(meta, 'post_token_balances', None)
        if post_balances is None:
            post_balances = getattr(meta, 'postTokenBalances', []) or []
        else:
            post_balances = post_balances or []
        
        logger.info(f"   📊 Post token balances: {len(post_balances)}")
        
        for balance in post_balances:
            mint = None
            
            # Try different access methods
            if hasattr(balance, 'mint'):
                mint = balance.mint
            elif isinstance(balance, dict):
                mint = balance.get('mint')
            
            if mint:
                mint_str = str(mint)
                if mint_str not in quote_tokens:
                    new_tokens.add(mint_str)
                    logger.info(f"   🪙 TOKEN: {mint_str[:40]}...")
        
        # ============================================  
        # METHOD 2: Inner Instructions
        # ============================================
        if not new_tokens:
            inner_instructions = getattr(meta, 'inner_instructions', None)
            if inner_instructions is None:
                inner_instructions = getattr(meta, 'innerInstructions', []) or []
            else:
                inner_instructions = inner_instructions or []
            
            for inner in inner_instructions:
                instructions = getattr(inner, 'instructions', []) or []
                for ix in instructions:
                    parsed = getattr(ix, 'parsed', None)
                    if parsed and isinstance(parsed, dict):
                        info = parsed.get('info', {})
                        mint = info.get('mint')
                        if mint and str(mint) not in quote_tokens:
                            new_tokens.add(str(mint))
                            logger.info(f"   🪙 TOKEN (inner): {str(mint)[:40]}...")
        
        # ============================================
        # RESULT: Track found tokens
        # ============================================
        if new_tokens:
            logger.info(f"   ✅ Found {len(new_tokens)} token(s) in {dex} pool!")
            
            for token_mint in new_tokens:
                if token_mint not in tokens:
                    tokens[token_mint] = TokenState(mint=token_mint)
                    stats['tokens_found'] = len(tokens)
                    logger.info(f"   🎯 TRACKING: {token_mint}")
                
                # Add pool info
                tokens[token_mint].pools[dex] = Pool(
                    address=signature,
                    dex=dex,
                    base_mint=token_mint,
                    quote_mint=SOL_MINT,
                )
                
                # Queue for multi-DEX scanning
                await pending_tokens.put((token_mint, dex))
                
                # Check if token now exists on multiple DEXes
                if len(tokens[token_mint].pools) >= 2:
                    logger.info(f"   ⚡ Token on {len(tokens[token_mint].pools)} DEXes!")
                    await check_arbitrage(client, tokens[token_mint])
        else:
            logger.info(f"   📭 No new tokens in tx (may be existing token trade)")
            
    except Exception as e:
        logger.error(f"   ❌ Process error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()


# ==============================
# MULTI-DEX SCANNER
# ==============================

async def scan_all_dexes():
    """Continuously scan for pools across all DEXes"""
    
    logger.info("🔄 Starting DEX scanner...")
    
    # Wait a moment for monitor to start
    await asyncio.sleep(2)
    
    client = AsyncClient(RPC_URL)
    
    try:
        while True:
            try:
                # Process pending tokens
                while not pending_tokens.empty():
                    token_mint, source_dex = await pending_tokens.get()
                    await scan_token_pools(client, token_mint)
                
                await asyncio.sleep(0.5)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scanner error: {e}")
                await asyncio.sleep(1)
    finally:
        await client.close()


async def scan_token_pools(client: AsyncClient, token_mint: str):
    """Scan all DEXes for pools containing this token"""
    
    if token_mint not in tokens:
        tokens[token_mint] = TokenState(mint=token_mint)
    
    state = tokens[token_mint]
    
    # Scan each DEX
    dexes = [
        ('raydium_amm', RAYDIUM_AMM, [400, 432], 752),
        ('raydium_clmm', RAYDIUM_CLMM, [73, 105], None),
        ('meteora_dlmm', METEORA_DLMM, [88, 120], None),
    ]
    
    for dex_name, program_id, offsets, data_size in dexes:
        try:
            program = Pubkey.from_string(program_id)
            
            for offset in offsets:
                filters = [{"memcmp": {"offset": offset, "bytes": token_mint}}]
                if data_size:
                    filters.append({"dataSize": data_size})
                
                resp = await client.get_program_accounts(
                    program,
                    encoding="base64",
                    filters=filters
                )
                
                for account in resp.value:
                    pool_addr = str(account.pubkey)
                    
                    if pool_addr not in state.pools:
                        state.pools[pool_addr] = Pool(
                            address=pool_addr,
                            dex=dex_name,
                            base_mint=token_mint,
                            quote_mint="",
                        )
                        logger.info(f"   Found {dex_name} pool: {pool_addr[:20]}...")
                        
        except Exception as e:
            logger.debug(f"Scan {dex_name} error: {e}")
    
    # Check for arbitrage if multiple pools
    if len(state.pools) >= 2:
        await check_arbitrage(client, state)


# ==============================
# ARBITRAGE DETECTION
# ==============================

async def check_arbitrage(client: AsyncClient, state: TokenState):
    """Check for arbitrage opportunity with AutoHedge AI validation"""
    
    if len(state.pools) < 2:
        return
    
    # Get prices from all pools
    prices = {}
    
    for pool_addr, pool in state.pools.items():
        try:
            price = await get_pool_price(client, pool)
            if price > 0:
                prices[pool_addr] = price
                pool.price = price
                pool.last_update = time.time()
        except:
            pass
    
    if len(prices) < 2:
        return
    
    # Find best spread
    sorted_prices = sorted(prices.items(), key=lambda x: x[1])
    
    buy_pool = sorted_prices[0][0]
    sell_pool = sorted_prices[-1][0]
    buy_price = sorted_prices[0][1]
    sell_price = sorted_prices[-1][1]
    
    spread_bps = (sell_price - buy_price) / buy_price * 10000
    
    # Quick filter - skip if spread too low
    if spread_bps < 30:  # Less than 0.3% not worth analyzing
        return
    
    # === AUTOHEDGE VALIDATION ===
    token_age = (time.time() - state.first_seen) / 60  # minutes
    
    decision = await validate_cross_dex_opportunity({
        'token_symbol': state.symbol or 'UNKNOWN',
        'token_mint': state.mint,
        'buy_dex': state.pools[buy_pool].dex,
        'sell_dex': state.pools[sell_pool].dex,
        'buy_price': buy_price,
        'sell_price': sell_price,
        'spread_bps': spread_bps,
        'spread_pct': spread_bps / 100,
        'buy_liquidity_usd': state.pools[buy_pool].liquidity,
        'sell_liquidity_usd': state.pools[sell_pool].liquidity,
        'token_age_minutes': token_age,
    })
    
    if decision.approved:
        stats['opportunities'] += 1
        state.arb_count += 1
        
        logger.info(f"\n✅ AUTOHEDGE APPROVED #{stats['opportunities']}")
        logger.info(f"   Token: {state.mint[:20]}...")
        logger.info(f"   Buy:  {state.pools[buy_pool].dex} @ ${buy_price:.8f}")
        logger.info(f"   Sell: {state.pools[sell_pool].dex} @ ${sell_price:.8f}")
        logger.info(f"   Spread: {spread_bps:.2f} bps ({spread_bps/100:.2f}%)")
        logger.info(f"   Confidence: {decision.confidence:.0%}")
        logger.info(f"   Risk Score: {decision.risk_score}/10")
        logger.info(f"   Position: {decision.position_size_sol:.2f} SOL")
        
        # Execute if we have a wallet
        wallet = get_wallet()
        if wallet:
            await execute_arb(
                client,
                state.pools[buy_pool],
                state.pools[sell_pool],
                wallet,
                decision.position_size_sol  # Use AI-recommended size
            )
    else:
        logger.debug(f"❌ REJECTED: {state.mint[:20]}... | {decision.reasoning}")


async def get_pool_price(client: AsyncClient, pool: Pool) -> float:
    """Get current price from pool"""
    
    try:
        resp = await client.get_account_info(Pubkey.from_string(pool.address))
        if not resp.value:
            return 0.0
        
        data = resp.value.data
        if isinstance(data, (list, tuple)):
            if isinstance(data[0], str):
                data = base64.b64decode(data[0])
            else:
                data = bytes(data)
        
        # Different parsing based on DEX
        if pool.dex == 'raydium_amm':
            # AMM: Get vault balances
            if len(data) >= 400:
                base_vault = Pubkey.from_bytes(data[336:368])
                quote_vault = Pubkey.from_bytes(data[368:400])
                
                base_resp = await client.get_account_info(base_vault)
                quote_resp = await client.get_account_info(quote_vault)
                
                if base_resp.value and quote_resp.value:
                    base_data = base_resp.value.data
                    quote_data = quote_resp.value.data
                    
                    if isinstance(base_data, (list, tuple)):
                        base_data = bytes(base_data) if isinstance(base_data[0], int) else base64.b64decode(base_data[0])
                    if isinstance(quote_data, (list, tuple)):
                        quote_data = bytes(quote_data) if isinstance(quote_data[0], int) else base64.b64decode(quote_data[0])
                    
                    if len(base_data) >= 72 and len(quote_data) >= 72:
                        base_bal = struct.unpack_from("<Q", base_data, 64)[0]
                        quote_bal = struct.unpack_from("<Q", quote_data, 64)[0]
                        
                        if base_bal > 0:
                            # Simplified - assumes 9/6 decimals
                            return (quote_bal / 1e6) / (base_bal / 1e9)
        
        elif pool.dex in ['raydium_clmm', 'meteora_dlmm']:
            # CLMM: Use tick
            if len(data) >= 85:
                tick = struct.unpack_from("<i", data, 81)[0]
                return 1.0001 ** tick * 1000
        
    except Exception as e:
        logger.debug(f"Price error: {e}")
    
    return 0.0


# ==============================
# TRADE EXECUTION
# ==============================

async def execute_arb(
    client: AsyncClient,
    buy_pool: Pool,
    sell_pool: Pool,
    wallet: Keypair,
    position_size_sol: float = None
):
    """Execute arbitrage trade using flash loan"""
    
    trade_size = position_size_sol or MAX_TRADE_SOL
    logger.info(f"\n🚀 EXECUTING FLASH LOAN ARBITRAGE ({trade_size:.2f} SOL)...")
    
    if USE_FLASH_LOAN:
        # Import flash loan executor
        try:
            from flash_arb import execute_flash_loan_arb
            
            success, result = await execute_flash_loan_arb(
                buy_pool={
                    'address': buy_pool.address,
                    'dex': buy_pool.dex,
                    'base_vault': buy_pool.base_vault or '',
                    'quote_vault': buy_pool.quote_vault or '',
                    'price': buy_pool.price,
                },
                sell_pool={
                    'address': sell_pool.address,
                    'dex': sell_pool.dex,
                    'base_vault': sell_pool.base_vault or '',
                    'quote_vault': sell_pool.quote_vault or '',
                    'price': sell_pool.price,
                },
                token_mint=buy_pool.base_mint,
                borrow_amount_sol=trade_size,
                min_profit_sol=0.001,  # Min 0.001 SOL profit
                jito_tip_sol=JITO_TIP / 1e9,
            )
            
            if success:
                stats['trades_executed'] += 1
                logger.info(f"   ✅ TX: {result[:40]}...")
            else:
                logger.info(f"   ❌ Failed: {result}")
                
        except ImportError:
            logger.error("   ❌ flash_arb.py not found - run without flash loans")
    else:
        logger.info(f"   ⚠️ Flash loans disabled - skipping trade")


# ==============================
# STATS & MONITORING
# ==============================

async def print_stats():
    """Print periodic stats"""
    while True:
        await asyncio.sleep(60)
        
        runtime = (time.time() - stats['start_time']) / 60
        tokens_tracked = len(tokens)
        
        print(f"\n📊 STATS ({runtime:.0f} min)")
        print(f"   Tokens tracked: {tokens_tracked}")
        print(f"   Pools detected: {stats['pools_detected']} (all txs)")
        print(f"   Pool creations: {sum(stats['by_dex'].values())}")
        print(f"   Opportunities: {stats['opportunities']}")
        print(f"   Trades: {stats['trades_executed']}")
        print(f"   Profit: ${stats['total_profit']:.4f}")
        
        # Show credit usage
        print(f"   💳 {get_credit_status()}")
        print(f"   TX fetches this hour: {credit_tracker['tx_fetches_this_hour']}/{MAX_TX_FETCHES_PER_HOUR}")
        if credit_tracker['paused']:
            print(f"   ⚠️ BOT PAUSED - Daily credit limit reached!")
        
        # Show breakdown by DEX
        if stats['by_dex']:
            print(f"   By DEX:")
            for dex, count in stats['by_dex'].items():
                print(f"      {dex}: {count}")


# ==============================
# MAIN
# ==============================

async def main():
    """Run the bot"""
    
    print("\n" + "=" * 60)
    print("🤖 NEW TOKEN ARBITRAGE BOT")
    print("=" * 60)
    
    # Network detection
    is_devnet = 'devnet' in (WSS_URL or '') or 'devnet' in (RPC_URL or '')
    is_mainnet = 'mainnet' in (WSS_URL or '') or not is_devnet
    
    network = "DEVNET ⚠️" if is_devnet else "MAINNET"
    print(f"   Network: {network}")
    
    if is_devnet:
        print("")
        print("   ⚠️  WARNING: Running on DEVNET!")
        print("   ⚠️  PumpFun, Raydium, Meteora only work on MAINNET")
        print("   ⚠️  You will NOT see real pool creations on devnet")
        print("")
    
    print(f"   Min Spread: {MIN_SPREAD_BPS} bps")
    print(f"   Max Trade: {MAX_TRADE_SOL} SOL")
    print(f"   Jito: {'Enabled' if USE_JITO else 'Disabled'}")
    print(f"   Flash Loans: {'Enabled' if USE_FLASH_LOAN else 'Disabled'}")
    print("=" * 60)
    print(f"   💳 QuickNode Credit Budget:")
    print(f"      Daily: {DAILY_CREDIT_BUDGET:,} credits")
    print(f"      Hourly: {HOURLY_CREDIT_BUDGET:,} credits")
    print(f"      Max TX fetches/hour: {MAX_TX_FETCHES_PER_HOUR}")
    print("=" * 60)
    
    wallet = get_wallet()
    if wallet:
        print(f"   Wallet: {str(wallet.pubkey())[:20]}...")
    else:
        print(f"   Mode: MONITOR ONLY (no wallet)")
    print("=" * 60 + "\n")
    
    try:
        await asyncio.gather(
            monitor_new_pools(),
            scan_all_dexes(),
            print_stats(),
        )
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
        print(f"   Final stats: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
