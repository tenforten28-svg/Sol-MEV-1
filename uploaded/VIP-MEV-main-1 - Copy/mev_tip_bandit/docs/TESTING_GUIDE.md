# Testing & Tuning Guide - Adaptive Tip Bandit

## Table of Contents
1. [Validation Methodology](#validation-methodology)
2. [Running Tests](#running-tests)
3. [Parameter Tuning](#parameter-tuning)
4. [Interpreting Results](#interpreting-results)
5. [Production Deployment](#production-deployment)

---

## Validation Methodology

### Phase 1: Simulation Testing
**Objective:** Verify algorithm works correctly in controlled environment

```bash
cd /app/mev_tip_bandit/python_prototype
python tip_bandit.py
```

**What to check:**
- ✅ All arms get explored initially
- ✅ Best-performing arms get more pulls over time
- ✅ Convergence score increases (should reach >70%)
- ✅ Cumulative reward is positive
- ✅ Win rate stabilizes after ~500 rounds

### Phase 2: Parameter Sensitivity Analysis
**Objective:** Understand how parameters affect performance

```python
# Test different exploration parameters
for c in [1.0, 1.5, 2.0, 2.5, 3.0]:
    bandit = TipBandit(tip_levels, exploration_param=c)
    # Run simulation and compare results
```

### Phase 3: Algorithm Comparison
**Objective:** Choose best algorithm for your use case

```python
from tip_bandit import compare_algorithms
compare_algorithms(num_rounds=1000)
```

**Decision Criteria:**
- **UCB1:** Better for stable markets, deterministic behavior
- **Thompson:** Better for dynamic markets, faster adaptation

### Phase 4: Real Market Backtesting
**Objective:** Validate with historical data

1. Collect historical opportunity data:
   - Expected profits
   - Actual inclusion outcomes
   - Tips used
   - Market conditions

2. Replay through bandit:
```python
for historical_opp in historical_data:
    tip = bandit.select_tip(historical_opp)
    # Use actual outcome from history
    bandit.update(historical_result, historical_opp)
```

3. Compare to your actual historical performance

---

## Running Tests

### Basic Simulation Test

```bash
python tip_bandit.py
```

**Expected Output:**
- Simulation runs for 1000 rounds
- Progress printed every 100 rounds
- Final summary with metrics
- Plot saved to `simulation_results.png`

### Extended Simulation (More Rounds)

```python
from tip_bandit import run_simulation, AlgorithmType

# Run 5000 rounds for better convergence
bandit = run_simulation(
    num_rounds=5000,
    algorithm=AlgorithmType.UCB1,
    plot_results=True
)
```

### Stress Test (Changing Markets)

```python
from tip_bandit import TipBandit, MarketSimulator, AlgorithmType

tip_levels = [5_000, 10_000, 20_000, 35_000, 50_000, 75_000, 100_000]
bandit = TipBandit(tip_levels, algorithm=AlgorithmType.UCB1)
simulator = MarketSimulator()

for i in range(2000):
    opp = simulator.generate_opportunity()
    tip = bandit.select_tip(opp)
    result = simulator.simulate_submission(tip, opp)
    bandit.update(result, opp)
    
    # Change market every 200 rounds
    if i % 200 == 0 and i > 0:
        simulator.update_market()
        print(f"Round {i}: Market changed!")

bandit.print_summary()
```

### Algorithm Comparison Test

```python
from tip_bandit import compare_algorithms

# Compare UCB1 vs Thompson Sampling
compare_algorithms(num_rounds=1000)
```

---

## Parameter Tuning

### 1. Exploration Parameter (UCB1 only)

**Default:** `c = 2.0`

**Tuning Guide:**

| Value | Behavior | Use When |
|-------|----------|----------|
| 1.0-1.5 | More exploitation | Stable market, confident in estimates |
| 2.0 (default) | Balanced | General use |
| 2.5-3.0 | More exploration | Dynamic market, uncertain conditions |

**Test Script:**
```python
for c in [1.0, 1.5, 2.0, 2.5, 3.0]:
    print(f"\nTesting c={c}")
    bandit = TipBandit(
        tip_levels=[5_000, 10_000, 20_000, 35_000, 50_000, 75_000, 100_000],
        algorithm=AlgorithmType.UCB1,
        exploration_param=c
    )
    # Run simulation...
    metrics = bandit.get_metrics()
    print(f"Net Profit: ${metrics['net_profit']/1_000_000:.2f}")
    print(f"Convergence: {metrics['convergence']*100:.2f}%")
```

### 2. Tip Levels

**Considerations:**
- **Spread:** Cover range from conservative to aggressive
- **Granularity:** More arms = better precision but slower learning
- **Min/Max:** Based on your profit margins

**Example Configurations:**

```python
# Conservative (lower tips)
tip_levels_conservative = [2_000, 5_000, 10_000, 20_000, 35_000]

# Aggressive (higher tips)
tip_levels_aggressive = [20_000, 35_000, 50_000, 75_000, 100_000, 150_000]

# Fine-grained (more precision)
tip_levels_fine = [5_000, 10_000, 15_000, 20_000, 25_000, 30_000, 35_000, 
                   40_000, 50_000, 60_000, 75_000, 100_000]
```

### 3. Thompson Sampling Priors

**Default:** `alpha = beta = 1.0` (uniform prior)

**Optimistic Prior:** Start with belief that tips work well
```python
bandit.alpha = 2.0  # Optimistic about success
bandit.beta = 1.0
```

**Pessimistic Prior:** Start conservative
```python
bandit.alpha = 1.0
bandit.beta = 2.0   # Pessimistic about success
```

---

## Interpreting Results

### Key Metrics

#### 1. Win Rate
**Target:** 60-80% overall

- **< 50%:** Tips too low or market too competitive
- **50-60%:** Acceptable but could improve
- **60-80%:** Good range
- **> 90%:** Tips might be too high (wasting money)

#### 2. Net Profit
**Target:** Positive and growing

```
Net Profit = Total Profit - Total Tips Spent
```

- **Negative:** Tips eating into profits, reduce tip levels
- **Close to zero:** Break-even, might be learning phase
- **Positive:** Good! Bandit is profitable

#### 3. Convergence Score
**Target:** 70-85% after 1000 rounds

- **< 50%:** Still exploring, needs more rounds
- **50-70%:** Learning phase
- **70-85%:** Good convergence
- **> 90%:** Might be over-exploiting, reduce exploration param

#### 4. Regret
**Target:** Sublinear growth (flattening curve)

- Should grow quickly at first (exploration)
- Should flatten as bandit learns
- If keeps growing linearly: algorithm not learning properly

### Visualization Analysis

#### Plot 1: Cumulative Reward
- **Should:** Increase steadily with occasional dips
- **Red Flag:** Decreasing or flat for long periods

#### Plot 2: Win Rate
- **Should:** Stabilize after ~500 rounds
- **Red Flag:** High volatility throughout

#### Plot 3: Arm Distribution
- **Should:** Heavily favor 1-2 best arms
- **Red Flag:** Uniform distribution after 1000 rounds

#### Plot 4: Average Reward per Tip
- **Should:** Clear winner(s) with highest bars
- **Red Flag:** All bars similar height

---

## Production Deployment

### Pre-Launch Checklist

- [ ] Run simulation for 1000+ rounds successfully
- [ ] Convergence score > 70%
- [ ] Net profit consistently positive in simulation
- [ ] Tested with various market conditions
- [ ] Chosen appropriate exploration parameter
- [ ] Set tip levels based on profit margins
- [ ] Implemented state persistence (save/load)
- [ ] Added monitoring and alerts
- [ ] Tested fallback to fixed tips

### Deployment Strategy

#### Phase 1: Shadow Mode (Days 1-3)
- Run bandit alongside existing system
- Don't use recommendations yet
- Just collect data and compare

```python
# Pseudo-code
bandit_tip = bandit.select_tip(opportunity)
current_tip = your_current_logic(opportunity)

print(f"Bandit: {bandit_tip}, Current: {current_tip}")

# Use current_tip for now
result = submit_bundle(current_tip)

# But update bandit as if we used its recommendation
bandit.update(result, opportunity)
```

#### Phase 2: Partial Rollout (Days 4-7)
- Use bandit for 25% of opportunities
- Monitor performance closely

```python
import random

if random.random() < 0.25:  # 25% chance
    tip = bandit.select_tip(opportunity)
    use_bandit = True
else:
    tip = your_current_logic(opportunity)
    use_bandit = False

result = submit_bundle(tip)
if use_bandit:
    bandit.update(result, opportunity)
```

#### Phase 3: Full Rollout (Day 8+)
- Use bandit for all opportunities
- Keep monitoring
- Revert if performance degrades

### Monitoring in Production

**Key Metrics to Track:**
```python
# Every 100 opportunities
if count % 100 == 0:
    metrics = bandit.get_metrics()
    
    # Log to monitoring system
    log_metric("bandit.win_rate", metrics['overall_win_rate'])
    log_metric("bandit.net_profit", metrics['net_profit'])
    log_metric("bandit.convergence", metrics['convergence'])
    log_metric("bandit.total_pulls", metrics['total_pulls'])
    
    # Alert if performance drops
    if metrics['overall_win_rate'] < 0.4:
        send_alert("Low win rate detected!")
    
    if metrics['net_profit'] < -100_000:
        send_alert("Negative profit threshold reached!")
```

### Fallback Strategy

```python
class SafeBandit:
    def __init__(self, bandit, fallback_tip=35_000):
        self.bandit = bandit
        self.fallback_tip = fallback_tip
        self.performance_window = []
        self.window_size = 100
    
    def select_tip(self, opportunity):
        # Check recent performance
        if len(self.performance_window) >= self.window_size:
            recent_win_rate = sum(self.performance_window) / len(self.performance_window)
            
            # Fallback if performance poor
            if recent_win_rate < 0.3:
                print("WARNING: Low win rate, using fallback tip")
                return self.fallback_tip
        
        return self.bandit.select_tip(opportunity)
    
    def update(self, result, opportunity):
        self.bandit.update(result, opportunity)
        
        # Track recent performance
        self.performance_window.append(1 if result.included else 0)
        if len(self.performance_window) > self.window_size:
            self.performance_window.pop(0)
```

### State Persistence

```python
import json
import os

STATE_FILE = "/app/bandit_state.json"

def save_state(bandit):
    state = {
        'arms': [
            {
                'lamports': arm.lamports,
                'pulls': arm.pulls,
                'total_reward': arm.total_reward,
                'successes': arm.successes,
                'failures': arm.failures,
                'avg_reward': arm.avg_reward
            }
            for arm in bandit.arms
        ],
        'total_pulls': bandit.total_pulls,
        'algorithm': bandit.algorithm.value
    }
    
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def load_state(tip_levels):
    if not os.path.exists(STATE_FILE):
        return TipBandit(tip_levels)
    
    with open(STATE_FILE, 'r') as f:
        state = json.load(f)
    
    bandit = TipBandit(tip_levels, algorithm=AlgorithmType[state['algorithm'].upper()])
    
    # Restore arm states
    for arm_state in state['arms']:
        arm = next(a for a in bandit.arms if a.lamports == arm_state['lamports'])
        arm.pulls = arm_state['pulls']
        arm.total_reward = arm_state['total_reward']
        arm.successes = arm_state['successes']
        arm.failures = arm_state['failures']
        arm.avg_reward = arm_state['avg_reward']
    
    bandit.total_pulls = state['total_pulls']
    return bandit
```

---

## Troubleshooting

### Issue: Low Win Rate (<40%)
**Possible Causes:**
- Tips too low for market
- High competition
- Poor network latency

**Solutions:**
- Increase tip levels
- Check if other bots using higher tips
- Verify RPC performance

### Issue: Negative Net Profit
**Possible Causes:**
- Tips too high relative to profits
- Opportunities not actually profitable

**Solutions:**
- Lower tip levels
- Improve opportunity detection
- Filter low-profit opportunities

### Issue: Not Converging
**Possible Causes:**
- Market too dynamic
- Exploration parameter too high
- Not enough rounds

**Solutions:**
- Reduce exploration_param to 1.5
- Run more rounds (2000+)
- Use Thompson Sampling instead

### Issue: Over-Converged (>95%)
**Possible Causes:**
- Exploration parameter too low
- Missing better strategies

**Solutions:**
- Increase exploration_param to 2.5
- Add more tip levels
- Review if market changed

---

## Best Practices

1. **Start Conservative:** Lower exploration, observe first
2. **Regular Backups:** Save state every hour
3. **Monitor Continuously:** Check metrics every 100 rounds
4. **Adapt to Changes:** Re-tune when market shifts
5. **A/B Testing:** Run parallel bandits occasionally
6. **Document Changes:** Keep log of parameter adjustments
7. **Emergency Stop:** Have kill switch if performance tanks

---

## Next Steps

1. Run basic simulation
2. Analyze results
3. Tune parameters
4. Run extended simulation
5. Deploy in shadow mode
6. Gradually increase usage
7. Monitor and iterate
