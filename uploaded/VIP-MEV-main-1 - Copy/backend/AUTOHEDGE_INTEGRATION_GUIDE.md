# AutoHedge Integration Guide for VIP-MEV Bot
==============================================

## Overview

This guide shows how to integrate the `autohedge_bridge.py` module into your existing 
arbitrage detection files (`pumpfun_arbitrage.py` and `lp_unlock_arbitrage.py`).

AutoHedge provides AI-powered trade validation with:
- **Director Agent**: Evaluates market conditions
- **Quant Agent**: Validates technical indicators  
- **Risk Manager**: Determines optimal position sizing

---

## Step 1: Install Dependencies

Run these commands in your local terminal:

```bash
pip install -U autohedge
pip install swarms  # AutoHedge dependency
```

---

## Step 2: Configure API Keys

Add ONE of these to your local `.env` file:

```env
# Option A: OpenAI (Recommended)
OPENAI_API_KEY=sk-your-openai-key-here

# Option B: Anthropic
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
```

Get your key from:
- OpenAI: https://platform.openai.com/api-keys
- Anthropic: https://console.anthropic.com/

---

## Step 3: Copy autohedge_bridge.py

Copy the `autohedge_bridge.py` file to your local `backend/` folder alongside your 
existing files.

---

## Step 4: Integrate into pumpfun_arbitrage.py

Add these changes to your `pumpfun_arbitrage.py`:

### 4.1 Add Import at Top

```python
# Add this import at the top of pumpfun_arbitrage.py
from autohedge_bridge import validate_cross_dex_opportunity, validate_migration_opportunity
```

### 4.2 Modify Your Opportunity Detection Function

Find your function that detects cross-DEX opportunities (likely called something like 
`evaluate_opportunity` or `check_arbitrage`). Wrap the execution logic with AutoHedge 
validation:

**BEFORE (example):**
```python
async def evaluate_opportunity(opportunity: dict):
    spread_bps = opportunity.get('spread_bps', 0)
    
    # Old logic - just checks spread
    if spread_bps >= MIN_SPREAD_BPS:
        await execute_trade(opportunity)
```

**AFTER (with AutoHedge):**
```python
async def evaluate_opportunity(opportunity: dict):
    spread_bps = opportunity.get('spread_bps', 0)
    
    # Quick filter - skip obvious bad opportunities
    if spread_bps < 30:  # < 0.3% not worth AI analysis
        return
    
    # Build opportunity dict for AutoHedge
    autohedge_opp = {
        'token_symbol': opportunity.get('token_symbol', 'UNKNOWN'),
        'token_mint': opportunity.get('token_mint', ''),
        'buy_dex': opportunity.get('buy_dex', ''),
        'sell_dex': opportunity.get('sell_dex', ''),
        'buy_price': opportunity.get('buy_price', 0),
        'sell_price': opportunity.get('sell_price', 0),
        'spread_bps': spread_bps,
        'spread_pct': spread_bps / 100,
        'buy_liquidity_usd': opportunity.get('buy_liquidity_usd', 0),
        'sell_liquidity_usd': opportunity.get('sell_liquidity_usd', 0),
        'token_age_minutes': opportunity.get('token_age_minutes', 0),
    }
    
    # Get AI validation
    decision = await validate_cross_dex_opportunity(autohedge_opp)
    
    if decision.approved:
        logger.info(f"✅ AutoHedge APPROVED: {decision.reasoning}")
        logger.info(f"   Position: {decision.position_size_sol:.3f} SOL, Confidence: {decision.confidence:.2f}")
        
        # Use AI-recommended position size instead of fixed amount
        opportunity['trade_size_sol'] = decision.position_size_sol
        await execute_trade(opportunity)
    else:
        logger.info(f"❌ AutoHedge REJECTED: {decision.reasoning}")
```

### 4.3 Add Migration Validation (if applicable)

If you have PumpFun migration detection:

```python
async def handle_migration(migration_event: dict):
    decision = await validate_migration_opportunity({
        'token_symbol': migration_event.get('symbol', ''),
        'token_mint': migration_event.get('mint', ''),
        'destination_dex': migration_event.get('destination', 'pumpswap'),
        'pumpfun_price': migration_event.get('bonding_price', 0),
        'dex_price': migration_event.get('dex_price', 0),
        'spread_bps': migration_event.get('spread_bps', 0),
        'bonding_progress': migration_event.get('progress_pct', 0),
        'migration_status': migration_event.get('status', 'pending'),
    })
    
    if decision.approved:
        await execute_migration_trade(migration_event, decision.position_size_sol)
```

---

## Step 5: Integrate into lp_unlock_arbitrage.py

Add these changes to your `lp_unlock_arbitrage.py`:

### 5.1 Add Import at Top

```python
# Add this import at the top of lp_unlock_arbitrage.py
from autohedge_bridge import validate_lp_unlock_opportunity
```

### 5.2 Modify Your Unlock Handler

**BEFORE (example):**
```python
async def handle_unlock_event(unlock: dict):
    pct_of_pool = unlock.get('pct_of_pool', 0)
    
    # Simple threshold check
    if pct_of_pool >= 10:  # Big unlock
        await prepare_short_position(unlock)
```

**AFTER (with AutoHedge):**
```python
async def handle_unlock_event(unlock: dict):
    # Build opportunity dict for AutoHedge
    autohedge_opp = {
        'token_symbol': unlock.get('token_symbol', 'UNKNOWN'),
        'token_mint': unlock.get('token_mint', ''),
        'lock_platform': unlock.get('platform', 'streamflow'),
        'unlock_time': unlock.get('unlock_time', ''),
        'lp_amount': unlock.get('lp_amount', 0),
        'lp_value_usd': unlock.get('lp_value_usd', 0),
        'pct_of_pool': unlock.get('pct_of_pool', 0),
        'current_price': unlock.get('current_price', 0),
        'liquidity_usd': unlock.get('liquidity_usd', 0),
        'volume_24h': unlock.get('volume_24h', 0),
    }
    
    # Get AI validation
    decision = await validate_lp_unlock_opportunity(autohedge_opp)
    
    if decision.approved:
        logger.info(f"✅ AutoHedge APPROVED LP Unlock: {decision.reasoning}")
        logger.info(f"   Position: {decision.position_size_sol:.3f} SOL, Risk: {decision.risk_score:.1f}")
        
        # AI decides strategy based on analysis
        if 'SHORT' in decision.reasoning.upper():
            await prepare_short_position(unlock, decision.position_size_sol)
        else:
            await prepare_buy_dip(unlock, decision.position_size_sol)
    else:
        logger.info(f"❌ AutoHedge REJECTED LP Unlock: {decision.reasoning}")
```

---

## Step 6: Configure AutoHedge Settings

You can customize the bridge behavior by modifying the singleton in your main file:

```python
from autohedge_bridge import get_autohedge_bridge

# Configure at startup
bridge = get_autohedge_bridge(
    min_confidence=0.65,       # Minimum AI confidence to trade (0-1)
    max_risk_score=7.0,        # Maximum risk score to trade (1-10)
    base_position_sol=0.5,     # Default position size
    max_position_sol=5.0,      # Maximum position cap
    simulation_mode=True       # Set False for live trading
)
```

---

## Step 7: Test the Integration

Run the bridge test to verify installation:

```bash
cd backend
python autohedge_bridge.py
```

Expected output:
```
============================================================
  AutoHedge Bridge Test
============================================================

1. Testing HIGH-QUALITY Cross-DEX opportunity...
   Approved: True
   Confidence: 0.85
   Position: 0.750 SOL
   ...

2. Testing LOW-QUALITY opportunity (should reject)...
   Approved: False
   ...
```

---

## Fallback Mode

If AutoHedge is not installed or API keys are missing, the bridge automatically 
falls back to **heuristic-based validation** using rule-based logic. This ensures 
your bot continues to work even without the AI layer.

Fallback rules:
- Spread >= 2%: High confidence (0.85)
- Spread >= 1%: Medium confidence (0.70)
- Low liquidity (<$5K): Reduced confidence, high risk
- New tokens (<5 min): Reduced confidence, high risk

---

## Monitoring & Stats

Get real-time stats from the bridge:

```python
from autohedge_bridge import get_autohedge_bridge

bridge = get_autohedge_bridge()
stats = bridge.get_stats()

print(f"Total Analyzed: {stats['total_analyzed']}")
print(f"Approved: {stats['approved']} ({stats['approval_rate_pct']:.1f}%)")
print(f"Avg Confidence: {stats['avg_confidence']:.2f}")
print(f"Est. Total Profit: {stats['total_profit_est']:.4f} SOL")
```

---

## Troubleshooting

### "AutoHedge not installed"
```bash
pip install -U autohedge swarms
```

### "No LLM API key found"
Add `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` to your `.env` file.

### Slow Response Times
The AI analysis adds ~1-3 seconds latency. For time-sensitive opportunities:
1. Pre-filter obvious bad opportunities (spread < 0.3%)
2. Only send promising opportunities to AutoHedge
3. Consider using `gpt-4o-mini` for faster responses (configured in bridge)

### High Rejection Rate
Lower the thresholds:
```python
bridge = get_autohedge_bridge(
    min_confidence=0.50,  # Lower from 0.65
    max_risk_score=8.0,   # Higher from 7.0
)
```

---

## Complete Integration Example

Here's a minimal complete example combining everything:

```python
# main_bot.py
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from autohedge_bridge import (
    get_autohedge_bridge,
    validate_cross_dex_opportunity,
    validate_lp_unlock_opportunity
)

# Initialize bridge at startup
bridge = get_autohedge_bridge(
    min_confidence=0.65,
    max_risk_score=7.0,
    simulation_mode=True  # Change to False for live
)

async def main():
    print("VIP-MEV Bot with AutoHedge AI")
    print(f"AutoHedge Status: {bridge.get_stats()}")
    
    # Your existing monitoring loop
    while True:
        # ... detect opportunities ...
        
        # When opportunity found:
        opportunity = {
            'token_symbol': 'DETECTED_TOKEN',
            'spread_bps': 150,
            # ... other fields
        }
        
        decision = await validate_cross_dex_opportunity(opportunity)
        
        if decision.approved:
            print(f"EXECUTING: {decision.position_size_sol} SOL")
            # execute_trade(...)
        
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Need Help?

The bridge includes detailed logging. Enable debug mode:

```python
import logging
logging.getLogger('autohedge_bridge').setLevel(logging.DEBUG)
```

This will show all AI prompts, responses, and decision reasoning.
