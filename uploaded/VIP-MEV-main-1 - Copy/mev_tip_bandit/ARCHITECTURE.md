# Adaptive Tip Bandit - System Architecture

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     MEV Bot Integration Layer                   │
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌─────────────────┐   │
│  │ Opportunity  │───▶│  Tip Bandit  │◀───│ Bundle Result   │   │
│  │  Detection   │    │              │    │   Feedback      │   │
│  └──────────────┘    └──────┬───────┘    └─────────────────┘   │
│                             │                                    │
└─────────────────────────────┼────────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │   TipBandit Core   │
                    │                    │
                    │  ┌──────────────┐  │
                    │  │  Algorithm   │  │
                    │  │   Selector   │  │
                    │  └──────┬───────┘  │
                    │         │          │
                    │  ┌──────▼───────┐  │
                    │  │  UCB1  │ TS  │  │
                    │  └──────────────┘  │
                    └─────────┬──────────┘
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
   ┌────────▼────────┐ ┌──────▼──────┐ ┌───────▼────────┐
   │  Bandit State   │ │  Simulator  │ │    Metrics     │
   │                 │ │             │ │                │
   │ • TipArms       │ │ • Market    │ │ • Win Rates    │
   │ • Total Pulls   │ │ • Results   │ │ • ROI          │
   │ • Phase         │ │ • Latency   │ │ • Convergence  │
   └─────────────────┘ └─────────────┘ └────────────────┘
```

---

## Component Interaction Flow

### 1. Initialization Phase

```
┌──────────────┐
│ Start System │
└──────┬───────┘
       │
       ▼
┌────────────────────────────────┐
│ Initialize Bandit              │
│                                │
│ • Set tip_levels               │
│ • Choose algorithm (UCB1/TS)   │
│ • Set exploration_param        │
│ • Create empty TipArms         │
└────────┬───────────────────────┘
         │
         ▼
┌────────────────────────────────┐
│ Load Saved State (if exists)   │
│ or Start Fresh Exploration     │
└────────────────────────────────┘
```

### 2. Opportunity Processing Loop

```
┌─────────────────────────────────────────────────────────────┐
│                    Main Execution Loop                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
         ┌─────────────────────────────────────┐
         │  New Opportunity Detected           │
         │                                     │
         │  • token_pair: "SOL/USDC"          │
         │  • expected_profit: 50,000         │
         │  • urgency: 0.7                    │
         └──────────────┬──────────────────────┘
                        │
                        ▼
         ┌──────────────────────────────────────┐
         │  Bandit: select_tip()                │
         │                                      │
         │  IF UCB1:                            │
         │    1. Check unexplored arms          │
         │    2. Calculate UCB for each arm     │
         │    3. Apply urgency boost            │
         │    4. Select max UCB                 │
         │                                      │
         │  IF Thompson:                        │
         │    1. Sample from Beta distributions │
         │    2. Select max sample              │
         └──────────────┬───────────────────────┘
                        │
                        ▼
         ┌──────────────────────────────────────┐
         │  Submit Bundle to Validator          │
         │                                      │
         │  • transactions: [tx1, tx2, ...]    │
         │  • tip: selected_tip                │
         └──────────────┬───────────────────────┘
                        │
                        ▼
         ┌──────────────────────────────────────┐
         │  Observe Result                      │
         │                                      │
         │  • included: true/false              │
         │  • actual_profit: 45,000             │
         │  • latency_ms: 120                   │
         └──────────────┬───────────────────────┘
                        │
                        ▼
         ┌──────────────────────────────────────┐
         │  Bandit: update()                    │
         │                                      │
         │  1. Calculate reward                 │
         │  2. Update selected arm stats        │
         │  3. Increment total_pulls            │
         │  4. Recompute confidence bounds      │
         │  5. Update phase if needed           │
         └──────────────┬───────────────────────┘
                        │
                        ▼
         ┌──────────────────────────────────────┐
         │  Log Metrics                         │
         │  Save State (periodic)               │
         └──────────────────────────────────────┘
                        │
                        │ Loop back
                        └─────────────────────────┐
                                                  │
                                                  ▼
```

---

## Data Flow Diagram

```
┌──────────────┐
│ Opportunity  │
│   {o}        │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────┐
│         TipBandit.select_tip(o)     │
│                                     │
│  Input:  Opportunity                │
│  Output: tip (u64)                  │
└──────┬──────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────┐
│    Algorithm Selection Logic         │
│                                      │
│    if UCB1:                          │
│      for each arm:                   │
│        ucb = avg + c*sqrt(ln(t)/n)  │
│      return max_ucb_arm.tip         │
│                                      │
│    if Thompson:                      │
│      for each arm:                   │
│        sample ~ Beta(α+s, β+f)      │
│      return max_sample_arm.tip      │
└──────┬───────────────────────────────┘
       │
       ▼
┌──────────────────┐
│  Recommended Tip │
│   35,000 SOL     │
└──────┬───────────┘
       │
       ▼ (Used in bundle submission)
       │
┌──────▼───────────────────────────────┐
│       Bundle Submission Result       │
│                                      │
│  • included: true                    │
│  • tip_used: 35,000                  │
│  • actual_profit: 45,000             │
│  • latency_ms: 120                   │
└──────┬───────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────┐
│      TipBandit.update(result, o)     │
│                                      │
│  1. reward = calc_reward(result, o)  │
│  2. arm = find_arm(35,000)           │
│  3. arm.update(reward, included)     │
│  4. total_pulls += 1                 │
│  5. recompute_bounds()               │
└──────┬───────────────────────────────┘
       │
       ▼
┌──────────────────┐
│  Updated State   │
└──────────────────┘
```

---

## State Machine

```
┌─────────────────────────────────────────────────────────┐
│                    Bandit Phases                         │
└─────────────────────────────────────────────────────────┘

    EXPLORATION                ADAPTIVE               EXPLOITATION
  (pulls < 100)          (100 ≤ pulls < 1000)        (convergence > 95%)
        │                         │                          │
        │                         │                          │
┌───────▼──────────┐    ┌─────────▼────────┐    ┌──────────▼─────────┐
│                  │    │                  │    │                    │
│  Try all arms    │───▶│  Balance         │───▶│  Mostly exploit    │
│  at least once   │    │  exploration &   │    │  best arm          │
│                  │    │  exploitation    │    │                    │
│  High variance   │    │  Learning        │    │  Low variance      │
│  Low confidence  │    │  Moderate conf.  │    │  High confidence   │
│                  │    │                  │    │                    │
└──────────────────┘    └──────────────────┘    └────────────────────┘
         │                         │                          │
         │                         │                          │
         └─────────────────────────┴──────────────────────────┘
                                   │
                        (Market changes detected)
                                   │
                                   ▼
                        ┌────────────────────┐
                        │  Reset to ADAPTIVE │
                        │  Continue learning │
                        └────────────────────┘
```

---

## Reward Calculation Pipeline

```
┌──────────────────────────────────────────────────────────┐
│                 Bundle Result Input                       │
│                                                           │
│  included: true                                          │
│  tip_used: 35,000 lamports                               │
│  actual_profit: 45,000 lamports                          │
│  expected_profit: 50,000 lamports (from opportunity)     │
└──────────────┬───────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│            Reward Calculation Logic                       │
│                                                           │
│  IF included == true:                                    │
│    ┌──────────────────────────────────────┐             │
│    │ tx_fees = 5,000                      │             │
│    │ net_profit = actual_profit           │             │
│    │            - tx_fees                 │             │
│    │            - tip_used                │             │
│    │           = 45,000 - 5,000 - 35,000  │             │
│    │           = 5,000                    │             │
│    │                                      │             │
│    │ normalized_reward = net_profit /     │             │
│    │                    expected_profit   │             │
│    │                  = 5,000 / 50,000    │             │
│    │                  = 0.10              │             │
│    └──────────────────────────────────────┘             │
│                                                           │
│  ELSE (not included):                                    │
│    ┌──────────────────────────────────────┐             │
│    │ penalty = -tip_used / expected_profit│             │
│    │         = -35,000 / 50,000           │             │
│    │         = -0.70                      │             │
│    └──────────────────────────────────────┘             │
└──────────────┬───────────────────────────────────────────┘
               │
               ▼
        ┌──────────────┐
        │  reward: 0.10 │  ◄── Used to update arm statistics
        └──────────────┘
```

---

## UCB1 Selection Algorithm (Detailed)

```
┌────────────────────────────────────────────────────────────┐
│              UCB1 Arm Selection Process                     │
└────────────────────────────────────────────────────────────┘

Input: current_state, opportunity
Output: selected_tip

Step 1: Exploration Check
┌──────────────────────────────────┐
│ FOR each arm in state.arms:      │
│   IF arm.pulls == 0:             │
│     RETURN arm.lamports          │  ◄── Ensure all arms tried once
└──────────────────────────────────┘

Step 2: UCB Calculation
┌────────────────────────────────────────────────────────────┐
│ best_ucb = -∞                                               │
│ best_arm = None                                             │
│                                                             │
│ FOR each arm in state.arms:                                │
│                                                             │
│   exploitation = arm.avg_reward                            │
│   │                                                         │
│   │   exploration = c * sqrt(2 * ln(total_pulls) / pulls)  │
│   │                                                         │
│   ├─▶ ucb = exploitation + exploration                     │
│   │                                                         │
│   │   IF opportunity.urgency > 0.8:                        │
│   │     ucb = ucb * 1.2  ◄── Urgency boost                 │
│   │                                                         │
│   │   IF ucb > best_ucb:                                   │
│   │     best_ucb = ucb                                     │
│   │     best_arm = arm                                     │
│                                                             │
│ RETURN best_arm.lamports                                    │
└────────────────────────────────────────────────────────────┘

Example Calculation (c=2.0, total_pulls=500):
┌─────────┬──────────┬────────────┬─────────────┬──────────┐
│   Tip   │  Pulls   │ Avg Reward │ Exploration │   UCB    │
├─────────┼──────────┼────────────┼─────────────┼──────────┤
│  5,000  │    50    │   -0.12    │    0.529    │  0.409   │
│ 10,000  │    85    │    0.05    │    0.408    │  0.458   │
│ 20,000  │   120    │    0.18    │    0.343    │  0.523   │
│ 35,000  │   180    │    0.42    │    0.280    │  0.700 ← │
│ 50,000  │    45    │    0.25    │    0.562    │  0.812 ← MAX
│ 75,000  │    15    │    0.10    │    0.970    │  1.070 ← │
│100,000  │     5    │   -0.15    │    1.497    │  1.347 ← │
└─────────┴──────────┴────────────┴─────────────┴──────────┘

Result: Select 100,000 lamports (highest UCB)
```

---

## Thompson Sampling Selection Algorithm (Detailed)

```
┌────────────────────────────────────────────────────────────┐
│        Thompson Sampling Arm Selection Process             │
└────────────────────────────────────────────────────────────┘

Input: current_state
Output: selected_tip

Prior Parameters:
  α₀ (alpha) = 1.0
  β₀ (beta)  = 1.0

┌────────────────────────────────────────────────────────────┐
│ best_sample = -∞                                            │
│ best_arm = None                                             │
│                                                             │
│ FOR each arm in state.arms:                                │
│                                                             │
│   α_posterior = α₀ + arm.successes                         │
│   β_posterior = β₀ + arm.failures                          │
│   │                                                         │
│   ├─▶ sample ~ Beta(α_posterior, β_posterior)              │
│   │                                                         │
│   │   IF sample > best_sample:                             │
│   │     best_sample = sample                               │
│   │     best_arm = arm                                     │
│                                                             │
│ RETURN best_arm.lamports                                    │
└────────────────────────────────────────────────────────────┘

Example Sampling (α₀=1, β₀=1):
┌─────────┬───────────┬──────────┬────────┬────────┬────────┐
│   Tip   │ Successes │ Failures │   α'   │   β'   │ Sample │
├─────────┼───────────┼──────────┼────────┼────────┼────────┤
│  5,000  │     5     │    45    │    6   │   46   │  0.089 │
│ 10,000  │    30     │    55    │   31   │   56   │  0.342 │
│ 20,000  │    70     │    50    │   71   │   51   │  0.578 │
│ 35,000  │   130     │    50    │  131   │   51   │  0.721 ← MAX
│ 50,000  │    38     │     7    │   39   │    8   │  0.804 │
│ 75,000  │     8     │     7    │    9   │    8   │  0.523 │
│100,000  │     3     │     2    │    4   │    3   │  0.612 │
└─────────┴───────────┴──────────┴────────┴────────┴────────┘

Result: Select 50,000 lamports (highest sample this round)
Note: Result is probabilistic and changes each iteration
```

---

## Metrics Collection Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Metrics Collector                         │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
    ┌─────────────┐  ┌────────────┐  ┌──────────────┐
    │  Per-Arm    │  │  Global    │  │  Convergence │
    │  Metrics    │  │  Metrics   │  │  Tracking    │
    └─────────────┘  └────────────┘  └──────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
    ┌─────────────────────────────────────────────┐
    │  • Win rate per tip                         │
    │  • Avg reward per tip                       │
    │  • Pulls per tip                            │
    │  • Confidence bounds                        │
    │                                             │
    │  • Overall win rate                         │
    │  • Total profit                             │
    │  • Total cost                               │
    │  • Net profit                               │
    │                                             │
    │  • Convergence score                        │
    │  • Cumulative regret                        │
    │  • Best arm selection %                     │
    └─────────────┬───────────────────────────────┘
                  │
                  ▼
    ┌─────────────────────────────────────────────┐
    │           Outputs                            │
    │                                             │
    │  • JSON reports                             │
    │  • Console summaries                        │
    │  • Visualization plots                      │
    │  • Real-time dashboards                     │
    └─────────────────────────────────────────────┘
```

---

## Module Dependencies (Rust)

```
mev_tip_bandit
├── tokio (async runtime)
├── serde (serialization)
│   └── serde_json
├── rand (random sampling)
├── statrs (Beta distribution)
├── log (logging)
└── thiserror (error handling)

Dependency Graph:
┌────────────┐
│   main.rs  │
└──────┬─────┘
       │
       ▼
┌────────────────┐
│  tip_bandit/   │
│     mod.rs     │
└───────┬────────┘
        │
        ├─────────┬─────────┬──────────┬──────────┐
        │         │         │          │          │
        ▼         ▼         ▼          ▼          ▼
   ┌────────┐ ┌──────┐ ┌─────────┐ ┌──────┐ ┌─────────┐
   │bandit.rs│ │state.rs│ │simulator│ │metrics│ │external│
   └────────┘ └───┬───┘ └─────────┘ └──────┘ │  deps   │
                  │                           └─────────┘
                  └──────────┐
                             ▼
                    ┌─────────────────┐
                    │  • serde        │
                    │  • rand         │
                    │  • statrs       │
                    └─────────────────┘
```

---

## Integration Points

### 1. With Opportunity Detector
```
OpportunityDetector ──▶ Opportunity ──▶ TipBandit.select_tip()
                                              │
                                              ▼
                                       recommended_tip
```

### 2. With Bundle Builder
```
TipBandit.select_tip() ──▶ recommended_tip ──▶ BundleBuilder
                                                      │
                                                      ▼
                                               Bundle + Tip
```

### 3. With Jito Submitter
```
Bundle + Tip ──▶ JitoSubmitter.submit() ──▶ BundleResult
                                                  │
                                                  ▼
                                    TipBandit.update(result)
```

### 4. With Monitoring System
```
TipBandit ──▶ Metrics ──▶ Monitoring Dashboard
                              │
                              ├─▶ Prometheus
                              ├─▶ Grafana
                              └─▶ Alerting
```

---

## Performance Considerations

### Time Complexity
- `select_tip()`: O(n) where n = number of arms
- `update()`: O(1) for single arm update
- `metrics calculation`: O(n)

### Space Complexity
- State storage: O(n) where n = number of arms
- History tracking: O(m) where m = number of rounds

### Optimization Strategies
1. **Caching:** Precompute UCB bounds
2. **Lazy Updates:** Batch state saves
3. **Pruning:** Remove underperforming arms after convergence
4. **Parallel:** Evaluate arms concurrently (Rust)

---

## Error Handling Flow

```
┌──────────────┐
│ Operation    │
└──────┬───────┘
       │
       ▼
┌──────────────────────┐
│ Try Operation        │
└──────┬───────────────┘
       │
       ├─ Success ────▶ Continue
       │
       └─ Failure
           │
           ▼
   ┌────────────────────┐
   │ Error Type?        │
   └──────┬─────────────┘
          │
          ├─ InvalidTip ──▶ Use fallback (35,000)
          │
          ├─ StateCorrupt ──▶ Reset to defaults
          │
          ├─ SimTimeout ──▶ Retry with backoff
          │
          └─ Unknown ──▶ Log + Alert + Fallback
```

---

**End of Architecture Documentation**
