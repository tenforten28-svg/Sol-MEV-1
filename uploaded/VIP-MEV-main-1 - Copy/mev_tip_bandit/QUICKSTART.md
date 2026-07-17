# Quick Start Guide - Adaptive Tip Bandit

## 5-Minute Setup

### Step 1: Install Dependencies

```bash
cd /app/mev_tip_bandit/python_prototype
pip install numpy matplotlib scipy pandas
```

### Step 2: Run Your First Simulation

```bash
python tip_bandit.py
```

That's it! The simulation will run and show you results.

---

## Understanding the Output

### Console Output

You'll see progress every 100 rounds:
```
Round 100: Win Rate = 45.50%, Net Profit = $2.34
Round 200: Win Rate = 58.25%, Net Profit = $5.67
...
```

### Final Summary

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

Recommended Tip: 35,000 lamports  <-- USE THIS!
```

**Key Takeaway:** After learning, the bandit recommends using **35,000 lamports** as your tip.

### Per-Tip Breakdown

```
Tip (lamports)   Win Rate     Avg Reward   Pulls  
--------------------------------------------------
5,000               15.00%      -0.1234      20   <- Too low
10,000              35.50%       0.0145      85   <- Still too low
20,000              58.20%       0.2341     145   <- Getting better
35,000              72.30%       0.4821     423   <- BEST! ⭐
50,000              81.50%       0.3156     215   <- High win but costly
75,000              88.00%       0.1234      82   <- Overkill
100,000             92.00%      -0.0456      30   <- Way too expensive
```

**Interpretation:**
- **5k-20k:** Win rates too low, bundles rejected
- **35k:** Sweet spot - good win rate + good ROI
- **50k+:** Higher win rates but ROI decreases (wasting money)

---

## What the Plots Show

### 1. Cumulative Reward
- Should trend upward
- Shows total learning progress

### 2. Win Rate Over Time
- Should stabilize around 60-80%
- Early volatility is normal (exploration)

### 3. Arm Pull Distribution
- Best arms get more pulls
- Shows which tips were selected most

### 4. Average Reward per Tip
- Highest bar = best tip
- Use this to choose your strategy

---

## Common Questions

### Q: What does "convergence" mean?
A: Percentage of time the bandit picked its best arm. High convergence (>70%) means it's confident.

### Q: Why is net profit positive but some arms have negative rewards?
A: Negative rewards on some arms show they're not profitable. The bandit learned to avoid them!

### Q: Should I use the recommended tip immediately?
A: In production, start conservative. Use the recommended tip, but:
1. Start with 50% of recommendations
2. Monitor for a day
3. Gradually increase usage

### Q: How often should I retrain?
A: The bandit learns continuously. But consider retraining if:
- Market conditions change significantly
- Your win rate drops below 40%
- You change DEX strategy

---

## Try Different Algorithms

### UCB1 (Default)
```python
from tip_bandit import run_simulation, AlgorithmType

bandit = run_simulation(
    num_rounds=1000,
    algorithm=AlgorithmType.UCB1
)
```

### Thompson Sampling
```python
bandit = run_simulation(
    num_rounds=1000,
    algorithm=AlgorithmType.THOMPSON
)
```

### Compare Both
```python
from tip_bandit import compare_algorithms
compare_algorithms(num_rounds=1000)
```

---

## Customize Tip Levels

```python
from tip_bandit import TipBandit, AlgorithmType

# Example: Higher tip range for competitive markets
custom_tips = [20_000, 35_000, 50_000, 75_000, 100_000, 150_000]

bandit = TipBandit(
    tip_levels=custom_tips,
    algorithm=AlgorithmType.UCB1,
    exploration_param=2.0
)

# Then run your simulation with this bandit
```

---

## Next Steps

1. ✅ Run basic simulation (you just did this!)
2. 🔍 Read the full `README.md` for integration details
3. 📊 Review `docs/TESTING_GUIDE.md` for production deployment
4. 🛠️ Integrate with your MEV bot
5. 🚀 Deploy in shadow mode first

---

## Need Help?

- **Algorithm not converging?** Increase exploration_param or run more rounds
- **Win rate too low?** Your tips might be too low for the market
- **Negative profit?** Tips too high relative to opportunity profits

Check `docs/TESTING_GUIDE.md` for detailed troubleshooting.
