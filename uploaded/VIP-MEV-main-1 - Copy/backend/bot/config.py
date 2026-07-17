"""
CONFIG - WebSocket HFT Bot Configuration
=========================================
Real-time pool monitoring via QuickNode WebSocket
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger('config')

# =============================================================================
# WEBSOCKET ENDPOINT
# =============================================================================
# Use your QuickNode WSS endpoint for mainnet
# IMPORTANT: Replace with your MAINNET QuickNode WSS URL for live trading
WSS_ENDPOINT = os.environ.get('QUICKNODE_WSS_URL', 'wss://api.mainnet-beta.solana.com')

# If the URL contains "devnet", default to mainnet public endpoint
if 'devnet' in WSS_ENDPOINT.lower():
    WSS_ENDPOINT = 'wss://api.mainnet-beta.solana.com'
    logger.warning("Devnet WSS detected, switching to mainnet public endpoint")

# HTTP RPC for initial pool discovery (one-time use only)
RPC_ENDPOINT = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

if 'devnet' in RPC_ENDPOINT.lower():
    RPC_ENDPOINT = 'https://api.mainnet-beta.solana.com'

# =============================================================================
# POOL ADDRESSES - High Volume SOL/USDC Pools
# =============================================================================
# These are the actual on-chain pool account addresses to subscribe to
POOLS = {
    # Raydium AMM SOL/USDC Pool
    "raydium_sol_usdc": {
        "address": "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2",
        "dex": "raydium",
        "base_mint": "So11111111111111111111111111111111111111112",  # SOL
        "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
        "base_vault": "DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz",
        "quote_vault": "HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz",
    },
    
    # Orca Whirlpool SOL/USDC
    "orca_sol_usdc": {
        "address": "HJPjoWUrhoZzkNfRpHuieeFk9WcZWjwy6PBjZ81ngndJ",
        "dex": "orca",
        "base_mint": "So11111111111111111111111111111111111111112",
        "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "token_vault_a": "3YQm7ujtXWJU2e9jhp2QGHpnn1ShXn12QjvzMvDgabpX",
        "token_vault_b": "2JTw1fE2wz1SymWUQ7UqpVtrTuKjcd6mWwYwUJUCh2rq",
    },
    
    # Meteora DLMM SOL/USDC
    "meteora_sol_usdc": {
        "address": "BVRbyLjjfSBcoyiYFuxbgKYnWuiFaF9CSXEa5vdpZ2Hq",
        "dex": "meteora",
        "base_mint": "So11111111111111111111111111111111111111112",
        "quote_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "reserve_x": "EKjPKDNWc7xMsoEVNgheSQuJpDQB7WEzVjJT1yLjmYzz",
        "reserve_y": "8PkfLx2i8LDuUzxrUHiLp4BcvUSpGqCHf4SoDBvhEhJE",
    },
    
    # Additional high-volume pairs for more arbitrage opportunities
    
    # Raydium BONK/SOL
    "raydium_bonk_sol": {
        "address": "Hni4cvLdJmrCT1MkbZZBJZC7RRDdVeTpQ2m3pm9GXnfH",
        "dex": "raydium",
        "base_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # BONK
        "quote_mint": "So11111111111111111111111111111111111111112",  # SOL
    },
    
    # Orca BONK/SOL
    "orca_bonk_sol": {
        "address": "Dqk7mHQBx2ZWExmyrR2S8X6UG75CrbbpK2FSBZsNYsw6",
        "dex": "orca",
        "base_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "quote_mint": "So11111111111111111111111111111111111111112",
    },
    
    # Raydium WIF/SOL
    "raydium_wif_sol": {
        "address": "EP2ib6dYdEeqD8MfE2ezHCxX3kP3K2eLKkirfPm5eyMx",
        "dex": "raydium",
        "base_mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",  # WIF
        "quote_mint": "So11111111111111111111111111111111111111112",
    },
    
    # Orca WIF/SOL  
    "orca_wif_sol": {
        "address": "EP2ib6dYdEeqD8MfE2ezHCxX3kP3K2eLKkirfPm5eyMx",
        "dex": "orca",
        "base_mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "quote_mint": "So11111111111111111111111111111111111111112",
    },
}

# =============================================================================
# VAULT ADDRESSES FOR RESERVE MONITORING
# =============================================================================
# Subscribe to vault token accounts for real-time reserve updates
VAULT_SUBSCRIPTIONS = {
    # Raydium SOL/USDC vaults
    "raydium_sol_usdc_base": "DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz",
    "raydium_sol_usdc_quote": "HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz",
    
    # Orca SOL/USDC vaults
    "orca_sol_usdc_base": "3YQm7ujtXWJU2e9jhp2QGHpnn1ShXn12QjvzMvDgabpX",
    "orca_sol_usdc_quote": "2JTw1fE2wz1SymWUQ7UqpVtrTuKjcd6mWwYwUJUCh2rq",
}

# =============================================================================
# TRADING PARAMETERS
# =============================================================================
MIN_SPREAD_BPS = 8  # Minimum spread in basis points to trigger
MIN_PROFIT_USD = 0.10  # Minimum expected profit in USD
MAX_TRADE_SIZE_USD = 5000  # Maximum trade size
SLIPPAGE_BPS = 50  # Expected slippage in basis points

# =============================================================================
# TOKEN DECIMALS
# =============================================================================
TOKEN_DECIMALS = {
    "So11111111111111111111111111111111111111112": 9,   # SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 6,  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 6,  # USDT
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": 5,  # BONK
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": 6,  # WIF
}

# =============================================================================
# PROGRAM IDS
# =============================================================================
RAYDIUM_AMM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
ORCA_WHIRLPOOL_PROGRAM = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
METEORA_DLMM_PROGRAM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

# =============================================================================
# JITO MEV PROTECTION
# =============================================================================
JITO_BLOCK_ENGINE_URL = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
JITO_TIP_LAMPORTS = 10000
JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4bVGb4pYrGdNLsmQYEzVHXU",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
]

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
