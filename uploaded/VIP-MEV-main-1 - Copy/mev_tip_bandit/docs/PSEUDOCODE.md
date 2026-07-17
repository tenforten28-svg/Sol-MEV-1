# Adaptive Tip Bandit - Complete Pseudocode

## Overview
This module uses Multi-Armed Bandit (MAB) algorithms to optimize validator tips for MEV bundle submission on Solana.

---

## 1. DATA STRUCTURES

### Core Types
```
struct TipArm:
    lamports: u64           // Tip amount in lamports
    pulls: u64              // Number of times selected
    total_reward: f64       // Cumulative reward
    successes: u64          // Number of successful inclusions
    failures: u64           // Number of failed inclusions
    avg_reward: f64         // Average reward per pull
    confidence_bound: f64   // UCB1 upper confidence bound

struct Opportunity:
    token_pair: string
    expected_profit: f64    // Expected profit in lamports
    size: f64               // Trade size
    urgency: f64            // 0.0-1.0, higher = more urgent
    timestamp: u64

struct BundleResult:
    included: bool          // Was bundle included in block?
    tip_used: u64           // Tip amount in lamports
    actual_profit: f64      // Actual profit (0 if not included)
    latency_ms: u64         // Time to inclusion
    block_slot: u64
    validator_id: string

struct BanditState:
    arms: Vec<TipArm>       // Available tip levels
    total_pulls: u64        // Total selections across all arms
    algorithm: AlgorithmType // UCB1 or Thompson
    exploration_param: f64  // c parameter for UCB1
    alpha: f64              // Success prior for Thompson
    beta: f64               // Failure prior for Thompson

struct PerformanceMetrics:
    win_rate: Map<u64, f64>          // tip -> inclusion rate
    avg_roi: Map<u64, f64>           // tip -> ROI
    total_profit: f64
    total_cost: f64
    regret: f64                      // cumulative regret
    convergence_score: f64
```

---

## 2. STATE MACHINE

```
Enum BanditPhase:
    EXPLORATION     // Initial learning phase
    EXPLOITATION    // Confident decision making
    ADAPTIVE        // Continuous learning + exploitation

state_transition(current_phase, pulls, convergence):
    if pulls < 100:
        return EXPLORATION
    elif convergence > 0.95:
        return EXPLOITATION
    else:
        return ADAPTIVE
```

---

## 3. CORE ALGORITHM - UCB1

### Initialization
```
initialize_bandit(tip_levels: Vec<u64>) -> BanditState:
    arms = []
    for tip in tip_levels:
        arms.append(TipArm {
            lamports: tip,
            pulls: 0,
            total_reward: 0.0,
            successes: 0,
            failures: 0,
            avg_reward: 0.0,
            confidence_bound: INFINITY
        })
    
    return BanditState {
        arms: arms,
        total_pulls: 0,
        algorithm: UCB1,
        exploration_param: 2.0,  // Tunable c parameter
        alpha: 1.0,
        beta: 1.0
    }
```

### Arm Selection (UCB1)
```
select_arm_ucb1(state: BanditState, opportunity: Opportunity) -> u64:
    // Exploration phase: try each arm at least once
    for arm in state.arms:
        if arm.pulls == 0:
            return arm.lamports
    
    // Exploitation: select arm with highest UCB
    best_arm = null
    best_ucb = -INFINITY
    
    for arm in state.arms:
        exploitation = arm.avg_reward
        exploration = state.exploration_param * sqrt(
            (2 * ln(state.total_pulls)) / arm.pulls
        )
        ucb = exploitation + exploration
        
        // Opportunity-based adjustment
        if opportunity.urgency > 0.8:
            ucb = ucb * 1.2  // Bias toward higher tips for urgent opps
        
        if ucb > best_ucb:
            best_ucb = ucb
            best_arm = arm
    
    return best_arm.lamports
```

### Arm Selection (Thompson Sampling)
```
select_arm_thompson(state: BanditState) -> u64:
    best_arm = null
    best_sample = -INFINITY
    
    for arm in state.arms:
        // Sample from Beta distribution
        alpha_post = state.alpha + arm.successes
        beta_post = state.beta + arm.failures
        
        sample = beta_sample(alpha_post, beta_post)
        
        if sample > best_sample:
            best_sample = sample
            best_arm = arm
    
    return best_arm.lamports
```

---

## 4. REWARD CALCULATION

```
calculate_reward(result: BundleResult, opportunity: Opportunity) -> f64:
    if result.included:
        // Success: profit minus tip
        gross_profit = result.actual_profit
        tx_fees = 5000  // Base tx fee in lamports
        net_profit = gross_profit - tx_fees - result.tip_used
        
        // Normalize reward to 0-1 scale for bandit
        reward = net_profit / opportunity.expected_profit
        return max(reward, 0.0)
    else:
        // Failure: lost the tip
        penalty = -result.tip_used / opportunity.expected_profit
        return penalty
```

---

## 5. LEARNING UPDATE LOOP

```
update_bandit(state: BanditState, tip_used: u64, result: BundleResult, 
              opportunity: Opportunity) -> void:
    
    // Find the arm that was used
    arm = find_arm_by_tip(state.arms, tip_used)
    
    // Calculate reward
    reward = calculate_reward(result, opportunity)
    
    // Update arm statistics
    arm.pulls += 1
    arm.total_reward += reward
    arm.avg_reward = arm.total_reward / arm.pulls
    
    if result.included:
        arm.successes += 1
    else:
        arm.failures += 1
    
    // Update global state
    state.total_pulls += 1
    
    // Recompute confidence bounds for all arms
    if state.algorithm == UCB1:
        for a in state.arms:
            if a.pulls > 0:
                a.confidence_bound = a.avg_reward + 
                    state.exploration_param * sqrt(
                        (2 * ln(state.total_pulls)) / a.pulls
                    )
```

---

## 6. SIMULATION LOGIC

```
simulate_market_condition() -> MarketCondition:
    return MarketCondition {
        base_inclusion_prob: random(0.3, 0.9),
        competing_bots: random(5, 50),
        validator_latency_ms: random(10, 200),
        min_competitive_tip: random(10_000, 80_000)
    }

simulate_bundle_submission(tip: u64, market: MarketCondition) -> BundleResult:
    // Calculate inclusion probability based on tip
    if tip < market.min_competitive_tip:
        inclusion_prob = 0.1  // Very low chance
    else:
        // Higher tip = higher probability (logarithmic)
        tip_factor = ln(1 + tip) / ln(1 + 100_000)
        inclusion_prob = market.base_inclusion_prob * tip_factor
    
    // Random outcome
    included = random() < inclusion_prob
    
    // Simulate actual profit if included
    actual_profit = if included:
        random(10_000, 100_000)  // Simulated arb profit
    else:
        0
    
    return BundleResult {
        included: included,
        tip_used: tip,
        actual_profit: actual_profit,
        latency_ms: market.validator_latency_ms,
        block_slot: current_slot(),
        validator_id: "sim_validator"
    }
```

---

## 7. MAIN EXECUTION LOOP

```
run_adaptive_tip_bandit(num_rounds: u64) -> PerformanceMetrics:
    // Initialize
    tip_levels = [5000, 10000, 20000, 35000, 50000, 75000, 100000]
    state = initialize_bandit(tip_levels)
    metrics = PerformanceMetrics::new()
    
    for round in 0..num_rounds:
        // Generate random opportunity
        opp = Opportunity {
            expected_profit: random(20_000, 150_000),
            urgency: random(0.0, 1.0),
            ...
        }
        
        // Select tip using bandit
        tip = select_arm_ucb1(state, opp)
        
        // Simulate market
        market = simulate_market_condition()
        
        // Simulate submission
        result = simulate_bundle_submission(tip, market)
        
        // Update bandit
        update_bandit(state, tip, result, opp)
        
        // Update metrics
        metrics.update(result, tip)
        
        // Log progress every 100 rounds
        if round % 100 == 0:
            print_progress(state, metrics)
    
    return metrics
```

---

## 8. METRICS & REPORTING

```
calculate_metrics(state: BanditState, results: Vec<BundleResult>) -> Report:
    report = Report::new()
    
    for arm in state.arms:
        win_rate = arm.successes / arm.pulls
        avg_roi = arm.avg_reward
        
        report.add_arm_stats(arm.lamports, {
            pulls: arm.pulls,
            win_rate: win_rate,
            avg_roi: avg_roi,
            avg_reward: arm.avg_reward
        })
    
    // Calculate regret (difference from optimal)
    optimal_arm = state.arms.max_by(|a| a.avg_reward)
    total_regret = 0.0
    
    for result in results:
        actual_reward = result.reward
        optimal_reward = optimal_arm.avg_reward
        total_regret += (optimal_reward - actual_reward)
    
    report.regret = total_regret
    report.convergence_score = calculate_convergence(state)
    
    return report

calculate_convergence(state: BanditState) -> f64:
    // Measure how stable arm selection has become
    best_arm = state.arms.max_by(|a| a.avg_reward)
    total_weight = 0.0
    best_weight = 0.0
    
    for arm in state.arms:
        weight = arm.pulls
        total_weight += weight
        if arm == best_arm:
            best_weight = weight
    
    return best_weight / total_weight  // Close to 1.0 = converged
```

---

## 9. I/O API

```
// Input: Request tip recommendation
struct TipRequest:
    opportunity: Opportunity
    current_state: BanditState

// Output: Recommended tip
struct TipResponse:
    recommended_tip: u64
    confidence: f64
    expected_inclusion_prob: f64
    expected_roi: f64

// API function
get_tip_recommendation(req: TipRequest) -> TipResponse:
    tip = select_arm_ucb1(req.current_state, req.opportunity)
    arm = find_arm_by_tip(req.current_state.arms, tip)
    
    confidence = arm.pulls / req.current_state.total_pulls
    inclusion_prob = arm.successes / max(arm.pulls, 1)
    expected_roi = arm.avg_reward
    
    return TipResponse {
        recommended_tip: tip,
        confidence: confidence,
        expected_inclusion_prob: inclusion_prob,
        expected_roi: expected_roi
    }
```

---

## END OF PSEUDOCODE
