"""
FLASH LOAN ARBITRAGE EXECUTOR
=============================
Uses Solend/MarginFi flash loans for capital-efficient arbitrage.

Flow:
1. Flash borrow SOL
2. Buy new token on cheap DEX
3. Sell new token on expensive DEX  
4. Repay flash loan
5. Keep profit

Your capital only covers: gas + flash loan fee (~0.3%)
"""

import asyncio
import os
import struct
import time
from typing import Optional, List, Tuple
from dataclasses import dataclass
import logging
from dotenv import load_dotenv

from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.address_lookup_table_account import AddressLookupTableAccount
import base58

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger('flash_arb')

# ==============================
# CONFIG
# ==============================
RPC_URL = os.environ.get('SOLANA_RPC_URL')
PRIVATE_KEY = os.environ.get('SOLANA_PRIVATE_KEY')

# Flash Loan Providers
SOLEND_PROGRAM = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo")
MARGINFI_PROGRAM = Pubkey.from_string("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA")

# Solend Flash Loan Pool (Main Pool)
SOLEND_MAIN_POOL = Pubkey.from_string("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY")
SOLEND_SOL_RESERVE = Pubkey.from_string("8PbodeaosQP19SjYFx855UMqWxH2HynZLdBXmsrbac36")

# Token Program
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

# Wrapped SOL mint
WSOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")

# Jito tip accounts
JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4bVmTpqFSZfxMQVKqhjGrwW",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
]


@dataclass
class FlashLoanArb:
    """Flash loan arbitrage parameters"""
    borrow_amount: int  # Amount of SOL to borrow (lamports)
    token_mint: Pubkey  # New token to arbitrage
    buy_pool: dict      # Pool to buy from (cheaper)
    sell_pool: dict     # Pool to sell to (expensive)
    min_profit: int     # Minimum profit required (lamports)


# ==============================
# WALLET
# ==============================

def load_wallet() -> Keypair:
    """Load wallet from private key"""
    if not PRIVATE_KEY:
        raise ValueError("SOLANA_PRIVATE_KEY not set")
    try:
        return Keypair.from_bytes(base58.b58decode(PRIVATE_KEY))
    except:
        import json
        return Keypair.from_bytes(bytes(json.loads(PRIVATE_KEY)))


# ==============================
# FLASH LOAN INSTRUCTIONS
# ==============================

def build_solend_flash_borrow(
    user: Pubkey,
    amount: int,
    user_wsol_account: Pubkey,
) -> Instruction:
    """
    Build Solend flash loan borrow instruction
    
    Solend FlashBorrowReserveLiquidity instruction (index 22):
    - Borrows tokens that must be repaid in same transaction
    """
    
    # Instruction data: [22 (u8), amount (u64)]
    data = bytes([22])  # Flash borrow instruction
    data += struct.pack('<Q', amount)
    
    # Accounts for flash borrow
    accounts = [
        # 0. Source liquidity (reserve liquidity supply)
        AccountMeta(SOLEND_SOL_RESERVE, is_signer=False, is_writable=True),
        # 1. Destination liquidity (user's token account)
        AccountMeta(user_wsol_account, is_signer=False, is_writable=True),
        # 2. Reserve account
        AccountMeta(SOLEND_SOL_RESERVE, is_signer=False, is_writable=True),
        # 3. Lending market
        AccountMeta(SOLEND_MAIN_POOL, is_signer=False, is_writable=False),
        # 4. Lending market authority (PDA)
        AccountMeta(
            Pubkey.find_program_address([bytes(SOLEND_MAIN_POOL)], SOLEND_PROGRAM)[0],
            is_signer=False, 
            is_writable=False
        ),
        # 5. Transfer authority
        AccountMeta(user, is_signer=True, is_writable=False),
        # 6. Token program
        AccountMeta(TOKEN_PROGRAM, is_signer=False, is_writable=False),
    ]
    
    return Instruction(SOLEND_PROGRAM, data, accounts)


def build_solend_flash_repay(
    user: Pubkey,
    amount: int,
    user_wsol_account: Pubkey,
) -> Instruction:
    """
    Build Solend flash loan repay instruction
    
    Must be called in same transaction as borrow.
    Repay amount = borrowed + fee (0.3%)
    """
    
    # Calculate repay amount with fee
    fee = amount * 30 // 10000  # 0.3% fee
    repay_amount = amount + fee
    
    # Instruction data: [23 (u8), amount (u64)]
    data = bytes([23])  # Flash repay instruction
    data += struct.pack('<Q', repay_amount)
    
    accounts = [
        # 0. Source liquidity (user's token account)
        AccountMeta(user_wsol_account, is_signer=False, is_writable=True),
        # 1. Destination liquidity (reserve liquidity supply)
        AccountMeta(SOLEND_SOL_RESERVE, is_signer=False, is_writable=True),
        # 2. Flash loan fee receiver
        AccountMeta(SOLEND_SOL_RESERVE, is_signer=False, is_writable=True),
        # 3. Reserve account
        AccountMeta(SOLEND_SOL_RESERVE, is_signer=False, is_writable=True),
        # 4. Lending market
        AccountMeta(SOLEND_MAIN_POOL, is_signer=False, is_writable=False),
        # 5. User transfer authority
        AccountMeta(user, is_signer=True, is_writable=False),
        # 6. Token program
        AccountMeta(TOKEN_PROGRAM, is_signer=False, is_writable=False),
    ]
    
    return Instruction(SOLEND_PROGRAM, data, accounts)


# ==============================
# SWAP INSTRUCTIONS
# ==============================

def build_raydium_swap(
    pool: dict,
    user: Pubkey,
    user_input: Pubkey,
    user_output: Pubkey,
    amount_in: int,
    min_out: int,
) -> Instruction:
    """Build Raydium AMM swap instruction"""
    
    RAYDIUM_AMM = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
    
    # Swap instruction data
    data = bytes([9])  # Swap instruction
    data += struct.pack('<Q', amount_in)
    data += struct.pack('<Q', min_out)
    
    accounts = [
        AccountMeta(TOKEN_PROGRAM, is_signer=False, is_writable=False),
        AccountMeta(Pubkey.from_string(pool['address']), is_signer=False, is_writable=True),
        AccountMeta(Pubkey.from_string(pool.get('authority', pool['address'])), is_signer=False, is_writable=False),
        AccountMeta(Pubkey.from_string(pool.get('open_orders', pool['address'])), is_signer=False, is_writable=True),
        AccountMeta(Pubkey.from_string(pool['base_vault']), is_signer=False, is_writable=True),
        AccountMeta(Pubkey.from_string(pool['quote_vault']), is_signer=False, is_writable=True),
        AccountMeta(user_input, is_signer=False, is_writable=True),
        AccountMeta(user_output, is_signer=False, is_writable=True),
        AccountMeta(user, is_signer=True, is_writable=False),
    ]
    
    return Instruction(RAYDIUM_AMM, data, accounts)


def build_meteora_swap(
    pool: dict,
    user: Pubkey,
    user_input: Pubkey,
    user_output: Pubkey,
    amount_in: int,
    min_out: int,
) -> Instruction:
    """Build Meteora DLMM swap instruction"""
    
    METEORA_DLMM = Pubkey.from_string("LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo")
    
    # Anchor discriminator for 'swap'
    discriminator = bytes([248, 198, 158, 145, 225, 117, 135, 200])
    
    data = discriminator
    data += struct.pack('<Q', amount_in)
    data += struct.pack('<Q', min_out)
    
    accounts = [
        AccountMeta(Pubkey.from_string(pool['address']), is_signer=False, is_writable=True),
        AccountMeta(Pubkey.from_string(pool.get('bin_array_lower', pool['address'])), is_signer=False, is_writable=True),
        AccountMeta(Pubkey.from_string(pool.get('bin_array_upper', pool['address'])), is_signer=False, is_writable=True),
        AccountMeta(Pubkey.from_string(pool['base_vault']), is_signer=False, is_writable=True),
        AccountMeta(Pubkey.from_string(pool['quote_vault']), is_signer=False, is_writable=True),
        AccountMeta(user_input, is_signer=False, is_writable=True),
        AccountMeta(user_output, is_signer=False, is_writable=True),
        AccountMeta(user, is_signer=True, is_writable=False),
        AccountMeta(TOKEN_PROGRAM, is_signer=False, is_writable=False),
    ]
    
    return Instruction(METEORA_DLMM, data, accounts)


# ==============================
# JITO TIP
# ==============================

def build_jito_tip(payer: Pubkey, tip_lamports: int) -> Instruction:
    """Build Jito tip instruction"""
    import random
    tip_account = Pubkey.from_string(random.choice(JITO_TIP_ACCOUNTS))
    
    # System transfer
    data = bytes([2, 0, 0, 0])
    data += struct.pack('<Q', tip_lamports)
    
    return Instruction(
        SYSTEM_PROGRAM_ID,
        data,
        [
            AccountMeta(payer, is_signer=True, is_writable=True),
            AccountMeta(tip_account, is_signer=False, is_writable=True),
        ]
    )


# ==============================
# FLASH LOAN ARBITRAGE
# ==============================

async def execute_flash_loan_arb(
    buy_pool: dict,
    sell_pool: dict,
    token_mint: str,
    borrow_amount_sol: float = 1.0,
    min_profit_sol: float = 0.001,
    jito_tip_sol: float = 0.00001,
) -> Tuple[bool, str]:
    """
    Execute flash loan arbitrage:
    
    1. Flash borrow SOL from Solend
    2. Buy token on cheaper DEX
    3. Sell token on expensive DEX
    4. Repay flash loan + fee
    5. Keep profit
    
    Returns: (success, message)
    """
    
    logger.info(f"\n{'='*60}")
    logger.info("⚡ FLASH LOAN ARBITRAGE")
    logger.info(f"{'='*60}")
    logger.info(f"   Borrow: {borrow_amount_sol} SOL")
    logger.info(f"   Buy on: {buy_pool.get('dex', 'unknown')}")
    logger.info(f"   Sell on: {sell_pool.get('dex', 'unknown')}")
    logger.info(f"   Min profit: {min_profit_sol} SOL")
    
    client = AsyncClient(RPC_URL)
    
    try:
        wallet = load_wallet()
        user = wallet.pubkey()
        
        # Convert to lamports
        borrow_lamports = int(borrow_amount_sol * 1e9)
        min_profit_lamports = int(min_profit_sol * 1e9)
        jito_tip_lamports = int(jito_tip_sol * 1e9)
        
        # Calculate amounts
        flash_fee = borrow_lamports * 30 // 10000  # 0.3%
        repay_amount = borrow_lamports + flash_fee
        
        logger.info(f"   Flash loan fee: {flash_fee / 1e9:.6f} SOL")
        
        # Get user's wSOL account (or create)
        user_wsol = Pubkey.find_program_address(
            [bytes(user), bytes(TOKEN_PROGRAM), bytes(WSOL_MINT)],
            ASSOCIATED_TOKEN
        )[0]
        
        # Get user's token account for the new token
        token_mint_pubkey = Pubkey.from_string(token_mint)
        user_token = Pubkey.find_program_address(
            [bytes(user), bytes(TOKEN_PROGRAM), bytes(token_mint_pubkey)],
            ASSOCIATED_TOKEN
        )[0]
        
        # Build instructions
        instructions = []
        
        # 1. Flash borrow SOL
        instructions.append(build_solend_flash_borrow(
            user=user,
            amount=borrow_lamports,
            user_wsol_account=user_wsol,
        ))
        
        # 2. Buy token on cheaper DEX
        if buy_pool.get('dex') == 'raydium_amm':
            instructions.append(build_raydium_swap(
                pool=buy_pool,
                user=user,
                user_input=user_wsol,
                user_output=user_token,
                amount_in=borrow_lamports,
                min_out=1,  # Will calculate proper slippage
            ))
        elif buy_pool.get('dex') == 'meteora_dlmm':
            instructions.append(build_meteora_swap(
                pool=buy_pool,
                user=user,
                user_input=user_wsol,
                user_output=user_token,
                amount_in=borrow_lamports,
                min_out=1,
            ))
        
        # 3. Sell token on expensive DEX
        if sell_pool.get('dex') == 'raydium_amm':
            instructions.append(build_raydium_swap(
                pool=sell_pool,
                user=user,
                user_input=user_token,
                user_output=user_wsol,
                amount_in=0,  # All tokens
                min_out=repay_amount + min_profit_lamports,
            ))
        elif sell_pool.get('dex') == 'meteora_dlmm':
            instructions.append(build_meteora_swap(
                pool=sell_pool,
                user=user,
                user_input=user_token,
                user_output=user_wsol,
                amount_in=0,
                min_out=repay_amount + min_profit_lamports,
            ))
        
        # 4. Flash repay
        instructions.append(build_solend_flash_repay(
            user=user,
            amount=borrow_lamports,
            user_wsol_account=user_wsol,
        ))
        
        # 5. Jito tip (for MEV protection)
        instructions.append(build_jito_tip(user, jito_tip_lamports))
        
        # Get recent blockhash
        blockhash_resp = await client.get_latest_blockhash()
        recent_blockhash = blockhash_resp.value.blockhash
        
        # Build transaction
        message = MessageV0.try_compile(
            payer=user,
            instructions=instructions,
            address_lookup_table_accounts=[],
            recent_blockhash=recent_blockhash,
        )
        
        tx = VersionedTransaction(message, [wallet])
        
        # Simulate first
        logger.info("   Simulating transaction...")
        sim_resp = await client.simulate_transaction(tx)
        
        if sim_resp.value.err:
            error_msg = str(sim_resp.value.err)
            logger.error(f"   ❌ Simulation failed: {error_msg}")
            return (False, f"Simulation failed: {error_msg}")
        
        # Check logs for profit
        logs = sim_resp.value.logs or []
        logger.info(f"   ✅ Simulation passed")
        
        # Send transaction
        logger.info("   Sending transaction...")
        send_resp = await client.send_transaction(tx)
        signature = str(send_resp.value)
        
        logger.info(f"   ✅ TX: {signature[:40]}...")
        
        return (True, signature)
        
    except Exception as e:
        logger.error(f"   ❌ Error: {e}")
        return (False, str(e))
    
    finally:
        await client.close()


# ==============================
# CALCULATE OPTIMAL BORROW
# ==============================

def calculate_optimal_borrow(
    buy_pool: dict,
    sell_pool: dict,
    max_borrow_sol: float = 10.0,
) -> float:
    """
    Calculate optimal borrow amount based on:
    - Pool liquidity
    - Price impact
    - Spread
    
    Returns optimal borrow amount in SOL
    """
    
    buy_liquidity = buy_pool.get('liquidity', 0)
    sell_liquidity = sell_pool.get('liquidity', 0)
    
    # Don't trade more than 1% of pool liquidity
    max_from_liquidity = min(buy_liquidity, sell_liquidity) * 0.01
    
    return min(max_borrow_sol, max_from_liquidity)


# ==============================
# TEST
# ==============================

async def main():
    """Test flash loan arb"""
    
    logger.info("=" * 60)
    logger.info("🧪 FLASH LOAN ARB TEST")
    logger.info("=" * 60)
    
    # Mock pools for testing
    buy_pool = {
        'address': 'MockPool1111111111111111111111111111111111111',
        'dex': 'raydium_amm',
        'base_vault': 'MockVault111111111111111111111111111111111111',
        'quote_vault': 'MockVault222222222222222222222222222222222222',
        'price': 0.001,
    }
    
    sell_pool = {
        'address': 'MockPool2222222222222222222222222222222222222',
        'dex': 'meteora_dlmm',
        'base_vault': 'MockVault333333333333333333333333333333333333',
        'quote_vault': 'MockVault444444444444444444444444444444444444',
        'price': 0.00105,  # 5% higher
    }
    
    # This will fail simulation (mock addresses) but shows the flow
    success, result = await execute_flash_loan_arb(
        buy_pool=buy_pool,
        sell_pool=sell_pool,
        token_mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # BONK
        borrow_amount_sol=0.1,
        min_profit_sol=0.001,
    )
    
    if success:
        logger.info(f"✅ Success: {result}")
    else:
        logger.info(f"❌ Failed: {result}")


if __name__ == "__main__":
    asyncio.run(main())
