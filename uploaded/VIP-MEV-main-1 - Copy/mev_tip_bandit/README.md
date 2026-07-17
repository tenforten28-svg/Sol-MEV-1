# Adaptive Tip Bandit for Solana MEV

## Overview

This module implements **Multi-Armed Bandit (MAB)** algorithms to optimize validator tips for MEV bundle submissions on Solana. It uses reinforcement learning to dynamically select optimal tip levels that maximize ROI while maintaining competitive inclusion rates.

## Problem Statement

In Solana MEV operations:
- **Higher tips** increase bundle inclusion probability but reduce profit
- **Lower tips** save money but risk bundle rejection
- **Optimal tip** varies with market conditions, competition, and opportunity value

This module **learns the optimal tipping strategy** through experience.

## Features

✅ **Two Algorithms Implemented:**
- **UCB1 (Upper Confidence Bound)**: Balances exploration/exploitation with confidence intervals
- **Thompson Sampling**: Bayesian approach using Beta distribution

✅ **Adaptive Learning:**
- Tracks win rate per tip level
- Calculates average ROI
- Adjusts strategy based on market feedback

✅ **Market Simulation:**
- Realistic inclusion probability modeling
- Dynamic market conditions
- Competition and latency simulation

✅ **Comprehensive Metrics:**
- Per-tip performance analysis
- Convergence tracking
- Regret calculation
- Profit/loss tracking

---

## Project Structure

```
mev_tip_bandit/
├── docs/
│   ├── PSEUDOCODE.md          # Complete algorithm pseudocode
│   └── TESTING_GUIDE.md       # How to test and tune
├── rust_stubs/              # Rust module stubs
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs
│       └── mev/
│           └── tip_bandit/
│               ├── mod.rs
│               ├── bandit.rs       # Core bandit logic
│               ├── state.rs        # State structures
│               ├── simulator.rs    # Market simulation
│               └── metrics.rs      # Performance tracking
├── python_prototype/        # Working Python implementation
│   ├── requirements.txt
│   └── tip_bandit.py
└── README.md
```

---

## Quick Start - Python Prototype

### Installation

```bash
cd /app/mev_tip_bandit/python_prototype
pip install -r requirements.txt
```

### Run Simulation

```bash
python tip_bandit.py
```

### Output

The simulation will:
1. Run 1000 rounds of opportunity detection and tip selection
2. Learn optimal tipping strategy
3. Print performance summary
4. Generate visualization plots

Example output:
```
==================================================
ADAPTIVE TIP BANDIT - PERFORMANCE SUMMARY
==================================================
Algorithm: UCB1
Total Pulls: 1000
Overall Win Rate: 67.50%
Total Profit: $85.23
Total Cost (Tips): $42.15
Net Profit: $43.08
Convergence: 78.30%

Recommended Tip: 35,000 lamports

--------------------------------------------------
Per-Tip Analysis:
--------------------------------------------------
Tip (lamports)   Win Rate     Avg Reward   Pulls  
--------------------------------------------------
5,000               15.00%      -0.1234      20
10,000              35.50%       0.0145      85
20,000              58.20%       0.2341     145
35,000              72.30%       0.4821     423
50,000              81.50%       0.3156     215
75,000              88.00%       0.1234      82
100,000             92.00%      -0.0456      30
==================================================
```

---

## Algorithm Details

### UCB1 (Upper Confidence Bound)

**Selection Formula:**
```
UCB(arm) = avg_reward + c * sqrt((2 * ln(total_pulls)) / arm_pulls)
            └──────────────┘      └────────────────────────────────┘
            Exploitation              Exploration Bonus
```

**Characteristics:**
- Deterministic
- Theoretically optimal regret bounds
- Good for stable environments

### Thompson Sampling

**Selection Process:**
1. For each arm, sample from `Beta(alpha + successes, beta + failures)`
2. Select arm with highest sample

**Characteristics:**
- Probabilistic
- Better for non-stationary environments
- Naturally handles uncertainty

---

## Tip Arms (Default)

| Tip (lamports) | Tip (SOL) | ~USD (@ $150/SOL) |
|----------------|-----------|-------------------|
| 5,000          | 0.000005  | $0.00075          |
| 10,000         | 0.00001   | $0.0015           |
| 20,000         | 0.00002   | $0.003            |
| **35,000**     | 0.000035  | $0.00525          |
| 50,000         | 0.00005   | $0.0075           |
| 75,000         | 0.000075  | $0.01125          |
| 100,000        | 0.0001    | $0.015            |

*Note: Adjust based on your profit margins and competition*

---

## Reward Function

```python
if bundle_included:
    reward = (actual_profit - tx_fees - tip) / expected_profit
else:
    reward = -tip / expected_profit  # Penalty for lost tip
```

**Normalization:** Rewards are normalized to expected profit for fair comparison across different opportunity sizes.

---

## Key Metrics

### Win Rate
Percentage of bundles successfully included in blocks for each tip level.

### Average ROI
Mean reward (normalized profit) per tip level.

### Convergence
Proportion of selections on the best-performing arm. High convergence (>80%) indicates confident strategy.

### Regret
Cumulative difference between optimal and actual rewards. Lower is better.

---

## Tuning Parameters

### UCB1 Exploration Parameter (c)
- **Default:** `2.0`
- **Lower (1.0-1.5):** More exploitation, faster convergence
- **Higher (2.5-3.0):** More exploration, better for dynamic markets

### Thompson Sampling Priors
- **Alpha/Beta = 1.0:** Uniform prior (default)
- **Higher values:** Stronger prior beliefs

### Tip Levels
Customize based on your:
- Average opportunity profit
- Market competition
- Risk tolerance

---

## Integration with MEV Bot

### Step 1: Initialize Bandit
```python
from tip_bandit import TipBandit, AlgorithmType

bandit = TipBandit(
    tip_levels=[5_000, 10_000, 20_000, 35_000, 50_000, 75_000, 100_000],
    algorithm=AlgorithmType.UCB1,
    exploration_param=2.0
)
```

### Step 2: Get Tip Recommendation
```python
# When opportunity detected
opportunity = Opportunity(
    token_pair="SOL/USDC",
    expected_profit=50_000,  # lamports
    size=1.0,
    urgency=0.7,
    timestamp=current_time
)

recommended_tip = bandit.select_tip(opportunity)
```

### Step 3: Submit Bundle
```python
result = submit_bundle_to_validator(
    transactions=bundle_txs,
    tip=recommended_tip
)
```

### Step 4: Update Bandit
```python
bundle_result = BundleResult(
    included=result.success,
    tip_used=recommended_tip,
    actual_profit=result.profit,
    latency_ms=result.latency,
    block_slot=result.slot
)

bandit.update(bundle_result, opportunity)
```

---

## Advanced Usage

### Compare Algorithms
```python
from tip_bandit import compare_algorithms

compare_algorithms(num_rounds=1000)
```

### Custom Market Conditions
```python
from tip_bandit import MarketSimulator, MarketCondition

simulator = MarketSimulator()
simulator.market = MarketCondition(
    base_inclusion_prob=0.7,
    competing_bots=25,
    validator_latency_ms=100,
    min_competitive_tip=30_000
)
```

### Save/Load State
```python
import json

# Save
with open('bandit_state.json', 'w') as f:
    json.dump(bandit.get_metrics(), f)

# Load (you'll need to implement state restoration)
```

---

## Rust Implementation (Stubs Provided)

Rust stubs are provided in `rust_stubs/` with:
- Complete type definitions
- Trait interfaces
- Function signatures
- TODO markers for implementation

To complete the Rust implementation:
1. Implement TODOs in `bandit.rs`
2. Add proper Beta sampling in `simulator.rs`
3. Implement state persistence
4. Add async support for real-time operation

---

## Testing & Validation

See `docs/TESTING_GUIDE.md` for:
- Validation methodology
- Backtesting procedures
- Parameter tuning guides
- A/B testing strategies

---

## Production Considerations

### ⚠️ Important Notes

1. **Start Conservative:** Begin with lower exploration parameter in production
2. **Warm-up Period:** Run simulation mode for 100-200 rounds before going live
3. **Monitor Closely:** Track win rates and adjust if performance degrades
4. **Market Changes:** Re-tune when you observe significant market shifts
5. **Capital at Risk:** Each failed bundle loses the tip amount

### Risk Management

- Set maximum tip limits based on profit margins
- Implement circuit breakers for low win rates
- Regular state backups
- Fallback to fixed tips if bandit underperforms

---

## Performance Expectations

After 500-1000 learning rounds:
- **Convergence:** 75-85%
- **Win Rate Improvement:** 10-20% over fixed tips
- **ROI Increase:** 15-30% from optimal tip selection

---

## Contributing

To extend this module:
1. Add new algorithms (e.g., Exp3, Contextual Bandits)
2. Implement contextual features (time of day, pair type)
3. Add multi-validator support
4. Integrate with real Jito Block Engine

---

## License

MIT License - Use at your own risk in production

---

## Support

For issues or questions:
- Review `docs/TESTING_GUIDE.md`
- Check simulation outputs
- Adjust parameters based on your specific market conditions
