"""
Flash Loan Configuration for Solana MEV Bot
Supports multiple flash loan providers
"""

# Flash Loan Providers on Solana
FLASH_LOAN_PROVIDERS = {
    'solend': {
        'program_id': 'So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo',
        'fee_percentage': 0.0009,  # 0.09% fee
        'min_amount': 0.01,  # Minimum 0.01 SOL
        'max_amount': 10000,  # Maximum 10,000 SOL
        'supported_tokens': ['SOL', 'USDC', 'USDT'],
        'reserves': {
            'SOL': 'DqhH94PjkZsjAqEze2BEkWhFQJ6EyU6MdtMphMgnXqeK',
            'USDC': 'BgxfHJDzm44T7XG68MYKx7YisTjZu73tVovyZSjJMpmw',
            'USDT': 'BTsbZDV7aCMRJ3VNy9ygV7ApdvCaZnSZU8x4UQqQKZf'
        }
    },
    'mango': {
        'program_id': 'mv3ekLzLbnVPNxjSKvqBpU3ZeZXPQdEC3bp5MDEBG68',
        'fee_percentage': 0.0005,  # 0.05% fee (cheaper!)
        'min_amount': 1.0,
        'max_amount': 50000,
        'supported_tokens': ['SOL', 'USDC', 'USDT', 'BTC', 'ETH'],
    }
}

# Default provider
DEFAULT_PROVIDER = 'solend'

# Flash loan parameters
FLASH_LOAN_CONFIG = {
    'min_profit_bps': 15,  # Minimum 0.15% profit (after flash loan fee)
    'max_loan_size_usd': 50000,  # Start with max $50k loans
    'preferred_token': 'USDC',  # Use USDC for most trades
    'slippage_tolerance_bps': 50,  # 0.5% max slippage
    'max_compute_units': 1400000,  # Solana compute limit
}

# Profitability calculator
def calculate_flash_loan_profitability(
    opportunity_profit_bps: float,
    loan_amount_usd: float,
    provider: str = DEFAULT_PROVIDER
) -> dict:
    """
    Calculate if opportunity is profitable after flash loan fee
    
    Returns:
        {
            'is_profitable': bool,
            'gross_profit': float,
            'flash_loan_fee': float,
            'net_profit': float,
            'roi_bps': float
        }
    """
    provider_config = FLASH_LOAN_PROVIDERS[provider]
    fee_percentage = provider_config['fee_percentage']
    
    # Calculate profits
    gross_profit = loan_amount_usd * (opportunity_profit_bps / 10000)
    flash_loan_fee = loan_amount_usd * fee_percentage
    net_profit = gross_profit - flash_loan_fee
    
    # Calculate ROI in basis points (on $50 initial capital for gas)
    roi_bps = (net_profit / 50) * 10000 if net_profit > 0 else 0
    
    return {
        'is_profitable': net_profit > 0,
        'gross_profit': gross_profit,
        'flash_loan_fee': flash_loan_fee,
        'net_profit': net_profit,
        'roi_bps': roi_bps,
        'min_profit_needed_bps': fee_percentage * 10000
    }


# Example usage
if __name__ == "__main__":
    # Test calculation
    opportunity = {
        'profit_bps': 25,  # 0.25% spread
        'loan_amount': 10000  # $10k loan
    }
    
    result = calculate_flash_loan_profitability(
        opportunity['profit_bps'],
        opportunity['loan_amount'],
        'solend'
    )
    
    print("Flash Loan Profitability Analysis")
    print("=" * 50)
    print(f"Loan Amount: ${opportunity['loan_amount']:,.2f}")
    print(f"Opportunity Profit: {opportunity['profit_bps']} bps")
    print(f"Gross Profit: ${result['gross_profit']:.2f}")
    print(f"Flash Loan Fee: ${result['flash_loan_fee']:.2f}")
    print(f"Net Profit: ${result['net_profit']:.2f}")
    print(f"Profitable: {'✅ YES' if result['is_profitable'] else '❌ NO'}")
    print(f"ROI on $50 capital: {result['roi_bps']:.0f} bps ({result['roi_bps']/100:.1f}%)")
