"""
Meme Coin Trading Configuration
Separate capital pool and risk management for meme coin trading
"""

from typing import Dict, List

# Meme coin token addresses (Solana mainnet)
MEME_TOKENS = {
    'BONK': {
        'mint': 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',
        'name': 'Bonk',
        'decimals': 5,
    },
    'WIF': {
        'mint': 'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm',
        'name': 'dogwifhat',
        'decimals': 6,
    },
    'POPCAT': {
        'mint': '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr',
        'name': 'Popcat',
        'decimals': 9,
    },
    'MEW': {
        'mint': 'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5',
        'name': 'cat in a dogs world',
        'decimals': 5,
    },
    'MYRO': {
        'mint': 'HhJpBhRRn4g56VsyLuT8DL5Bv31HkXqsrahTTUCZeZg4',
        'name': 'Myro',
        'decimals': 9,
    },
    'SAMO': {
        'mint': '7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU',
        'name': 'Samoyedcoin',
        'decimals': 9,
    },
    'PONKE': {
        'mint': '5z3EqYQo9HiCEs3R84RCDMu2n7anpDMxRhdK8PSWmrRC',
        'name': 'Ponke',
        'decimals': 9,
    },
    'SLERF': {
        'mint': '7BgBvyjrZX1YKz4oh9mjb8ZScatkkwb8DzFx7LoiVkM3',
        'name': 'Slerf',
        'decimals': 9,
    }
}

# Meme coin trading pairs
# Cross-meme pairs for triangular arbitrage
MEME_CROSS_PAIRS = [
    'BONK/WIF',
    'BONK/POPCAT',
    'WIF/POPCAT',
    'MEW/BONK',
    'MYRO/WIF',
]

# Meme/stable pairs
MEME_STABLE_PAIRS = [
    'BONK/USDC',
    'WIF/USDC',
    'POPCAT/USDC',
    'MEW/USDC',
    'MYRO/USDC',
    'SAMO/USDC',
    'PONKE/USDC',
    'SLERF/USDC',
    'BONK/SOL',
    'WIF/SOL',
    'POPCAT/SOL',
    'MEW/SOL',
]

# All monitored pairs
ALL_MEME_PAIRS = MEME_CROSS_PAIRS + MEME_STABLE_PAIRS

# Meme coin risk parameters (Conservative)
MEME_RISK_CONFIG = {
    'initial_capital': 10.0,  # 10 SOL dedicated to meme trading
    'reserve_percentage': 60.0,  # Keep 60% in reserve (more conservative)
    'max_trade_percentage': 1.0,  # Max 1% of meme pool per trade
    'min_liquidity_usd': 100000.0,  # Minimum $100K liquidity
    'max_slippage_bps': 30,  # Higher slippage tolerance for memes (0.3%)
    'min_profit_threshold_bps': 15,  # Require higher profit for memes (0.15%)
    'max_position_size': 1.0,  # Max position size in SOL
    'liquidity_lock_required': True,  # Must verify liquidity is locked
    'min_lock_duration_days': 30,  # Minimum 30 days liquidity lock
}

# DEXs to monitor for meme coins
MEME_DEXS = [
    'raydium',
    'orca',
    'jupiter',  # Jupiter aggregates best routes
]

def get_meme_token_address(symbol: str) -> str:
    """Get token mint address for a meme coin"""
    if symbol in MEME_TOKENS:
        return MEME_TOKENS[symbol]['mint']
    return None

def get_all_meme_symbols() -> List[str]:
    """Get list of all meme coin symbols"""
    return list(MEME_TOKENS.keys())

def is_meme_pair(pair: str) -> bool:
    """Check if a trading pair involves meme coins"""
    return pair in ALL_MEME_PAIRS

def parse_meme_pair(pair: str) -> tuple:
    """Parse a meme pair string into (base, quote)"""
    parts = pair.split('/')
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, None
