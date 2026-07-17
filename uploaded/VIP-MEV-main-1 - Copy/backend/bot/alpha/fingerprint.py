"""
FINGERPRINT - Route Identification for Learning
================================================
Creates stable, unique identifiers for arbitrage routes.
Required for tracking performance by route type.
"""

import hashlib
from typing import List, Optional

# ============================================================================
# FINGERPRINT BUILDER
# ============================================================================

def build_fingerprint(
    dex_programs: List[str],
    pool_accounts: List[str],
    token_path: List[str],
    route_length: int = 2,
    cu_bucket: Optional[str] = None
) -> str:
    """
    Build a stable fingerprint for an arbitrage route.
    
    The fingerprint uniquely identifies a route type for learning.
    Same route always produces same fingerprint.
    
    Format:
    DEX1|DEX2::TOKEN_PATH::pools:<sorted_addrs>::cu:<bucket>
    
    Args:
        dex_programs: List of DEX program IDs (sorted)
        pool_accounts: List of pool account addresses (sorted)
        token_path: Token path e.g., ["USDC", "SOL", "USDC"]
        route_length: Number of swaps in route
        cu_bucket: Optional CU bucket e.g., "CU_180_220"
    
    Returns:
        Stable fingerprint string
    """
    # Sort DEX programs for stability
    sorted_dexs = sorted(set(dex_programs))
    dex_part = "|".join(sorted_dexs)
    
    # Create token path string
    path_part = "->".join(token_path)
    
    # Sort pool accounts and take first 8 chars of each
    sorted_pools = sorted(set(pool_accounts))
    pools_short = [p[:8] for p in sorted_pools]
    pools_part = f"pools:{','.join(pools_short)}"
    
    # Build fingerprint
    parts = [dex_part, path_part, pools_part]
    
    if cu_bucket:
        parts.append(f"cu:{cu_bucket}")
    
    fingerprint = "::".join(parts)
    
    return fingerprint


def build_fingerprint_from_opportunity(
    buy_pool: str,
    sell_pool: str,
    buy_dex: str,
    sell_dex: str,
    buy_mint: str,
    sell_mint: str,
    quote_mint: str,
    cu_estimate: Optional[int] = None
) -> str:
    """
    Build fingerprint from opportunity details.
    
    Args:
        buy_pool: Buy pool address
        sell_pool: Sell pool address
        buy_dex: Buy DEX name
        sell_dex: Sell DEX name
        buy_mint: Base token mint (token being bought)
        sell_mint: Base token mint (should match buy_mint)
        quote_mint: Quote token mint
        cu_estimate: Estimated compute units
    """
    # Map DEX names to program IDs
    dex_to_program = {
        'raydium': 'RAYDIUM',
        'raydium_amm': 'RAYDIUM',
        'orca': 'ORCA',
        'orca_whirlpool': 'ORCA',
        'meteora': 'METEORA',
        'meteora_dlmm': 'METEORA',
    }
    
    dex_programs = [
        dex_to_program.get(buy_dex.lower(), buy_dex.upper()),
        dex_to_program.get(sell_dex.lower(), sell_dex.upper()),
    ]
    
    pool_accounts = [buy_pool, sell_pool]
    
    # Token path: quote -> base -> quote
    token_path = [
        mint_to_symbol(quote_mint),
        mint_to_symbol(buy_mint),
        mint_to_symbol(quote_mint)
    ]
    
    # CU bucket
    cu_bucket = None
    if cu_estimate:
        cu_bucket = get_cu_bucket(cu_estimate)
    
    return build_fingerprint(
        dex_programs=dex_programs,
        pool_accounts=pool_accounts,
        token_path=token_path,
        route_length=2,
        cu_bucket=cu_bucket
    )


def mint_to_symbol(mint: str) -> str:
    """Convert mint address to token symbol"""
    known_mints = {
        "So11111111111111111111111111111111111111112": "SOL",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
        "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
        "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "WIF",
        "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
        "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": "JTO",
    }
    return known_mints.get(mint, mint[:8])


def get_cu_bucket(cu_estimate: int) -> str:
    """Get CU bucket for fingerprint"""
    if cu_estimate < 100000:
        return "CU_0_100"
    elif cu_estimate < 150000:
        return "CU_100_150"
    elif cu_estimate < 200000:
        return "CU_150_200"
    elif cu_estimate < 250000:
        return "CU_200_250"
    elif cu_estimate < 300000:
        return "CU_250_300"
    else:
        return "CU_300_PLUS"


def fingerprint_hash(fingerprint: str) -> str:
    """
    Create a short hash of the fingerprint.
    Useful for storage/display when full fingerprint is too long.
    """
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:12]


# ============================================================================
# FINGERPRINT PARSING
# ============================================================================

def parse_fingerprint(fingerprint: str) -> dict:
    """
    Parse a fingerprint back into its components.
    
    Returns:
        Dict with keys: dexs, token_path, pools, cu_bucket
    """
    parts = fingerprint.split("::")
    
    result = {
        'dexs': [],
        'token_path': [],
        'pools': [],
        'cu_bucket': None
    }
    
    if len(parts) >= 1:
        result['dexs'] = parts[0].split("|")
    
    if len(parts) >= 2:
        result['token_path'] = parts[1].split("->")
    
    if len(parts) >= 3 and parts[2].startswith("pools:"):
        pools_str = parts[2].replace("pools:", "")
        result['pools'] = pools_str.split(",")
    
    if len(parts) >= 4 and parts[3].startswith("cu:"):
        result['cu_bucket'] = parts[3].replace("cu:", "")
    
    return result


def fingerprints_match(fp1: str, fp2: str) -> bool:
    """Check if two fingerprints represent the same route"""
    # Parse and compare
    p1 = parse_fingerprint(fp1)
    p2 = parse_fingerprint(fp2)
    
    return (
        sorted(p1['dexs']) == sorted(p2['dexs']) and
        p1['token_path'] == p2['token_path'] and
        sorted(p1['pools']) == sorted(p2['pools'])
    )


# ============================================================================
# TESTS
# ============================================================================

def test_fingerprint():
    """Test fingerprint creation"""
    fp1 = build_fingerprint(
        dex_programs=["RAYDIUM", "ORCA"],
        pool_accounts=["58oQChx4", "HJPjoWUr"],
        token_path=["USDC", "SOL", "USDC"],
        cu_bucket="CU_200_250"
    )
    
    fp2 = build_fingerprint(
        dex_programs=["ORCA", "RAYDIUM"],  # Different order
        pool_accounts=["HJPjoWUr", "58oQChx4"],  # Different order
        token_path=["USDC", "SOL", "USDC"],
        cu_bucket="CU_200_250"
    )
    
    # Should produce same fingerprint regardless of order
    assert fp1 == fp2, "Fingerprints should match regardless of order"
    
    # Different pools should produce different fingerprint
    fp3 = build_fingerprint(
        dex_programs=["RAYDIUM", "ORCA"],
        pool_accounts=["DIFFERENT1", "DIFFERENT2"],
        token_path=["USDC", "SOL", "USDC"],
    )
    
    assert fp1 != fp3, "Different pools should produce different fingerprint"
    
    print(f"Test 1 passed: {fp1}")
    print(f"Test 2 passed: fp1 == fp2")
    print(f"Test 3 passed: fp1 != fp3")
    
    return True


if __name__ == "__main__":
    test_fingerprint()
