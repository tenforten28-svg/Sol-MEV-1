# Probe Transaction System - Complete Pseudocode

## Overview
This system implements safe, low-cost probe transactions to measure Solana validator behavior, tip acceptance thresholds, and network conditions without risking capital.

---

## 1. DATA STRUCTURES

### Core Probe Types
```
Enum ProbeType:
    TIP_THRESHOLD      // Find minimum tip for inclusion
    LATENCY_TEST       // Measure propagation delay
    CONGESTION_PRESSURE // Simulate bundle complexity
    COMPETITION_TEST   // Test against other bots

Struct ProbeTransaction:
    probe_id: UUID
    probe_type: ProbeType
    validator_identity: PublicKey
    tip_amount: u64              // Lamports
    compute_units: u32
    account_count: u8
    priority_fee: u64
    timestamp_sent: u64          // Unix timestamp microseconds
    bundle_size_bytes: usize
    
    // Transaction data
    transaction: Transaction     // The actual Solana transaction
    signature: Signature
    
    // Metadata
    expected_slot: u64
    retry_count: u8
    parent_probe_id: Option<UUID> // For multi-probe tests

Struct ProbeResult:
    probe_id: UUID
    probe_type: ProbeType
    validator_identity: PublicKey
    
    // Input parameters
    tip_sent: u64
    compute_units: u32
    account_count: u8
    
    // Outcome
    included: bool
    slot_included: Option<u64>
    timestamp_confirmed: Option<u64>
    latency_ms: Option<u64>      // Time from send to confirm
    
    // Network state
    slot_sent: u64
    cluster_congestion: f64      // 0.0-1.0
    competing_transactions: u32  // Estimated
    
    // Error info
    error_code: Option<String>
    retry_count: u8

Struct ValidatorProfile:
    validator_identity: PublicKey
    total_probes_sent: u64
    total_probes_included: u64
    inclusion_rate: f64
    
    // Tip statistics
    min_tip_observed: u64
    avg_tip_for_inclusion: u64
    tip_acceptance_curve: Vec<(u64, f64)>  // (tip, probability)
    
    // Performance
    avg_latency_ms: f64
    latency_variance: f64
    best_slots: Vec<u64>         // Historical good slots
    
    // Behavior patterns
    accepts_low_priority: bool
    prefers_high_compute: bool
    last_updated: u64

Struct NetworkSnapshot:
    slot: u64
    timestamp: u64
    
    // Congestion metrics
    transactions_per_second: u32
    pending_queue_depth: u32
    average_priority_fee: u64
    
    // Validator state
    active_validators: Vec<PublicKey>
    leader_schedule: Vec<(u64, PublicKey)>  // (slot, leader)
    
    // Cost metrics
    median_tip: u64
    p95_tip: u64
    min_competitive_tip: u64
```

---

## 2. PROBE TRANSACTION PATTERNS

### Probe Type A: Tip Threshold Test
```
create_tip_threshold_probe(validator: PublicKey, tip: u64) -> ProbeTransaction:
    """
    Creates a minimal transaction to test tip acceptance.
    Uses a 0-lamport transfer that does nothing but costs a tip.
    """
    
    // Create no-op instruction
    instruction = SystemProgram.transfer(
        from: probe_wallet,
        to: probe_wallet,
        lamports: 0  // No actual transfer
    )
    
    // Add compute budget with tip
    compute_budget_ix = ComputeBudgetProgram.set_compute_unit_limit(
        units: 1400  // Minimal compute
    )
    
    priority_fee_ix = ComputeBudgetProgram.set_compute_unit_price(
        micro_lamports: tip
    )
    
    // Build transaction
    transaction = Transaction.new(
        instructions: [compute_budget_ix, priority_fee_ix, instruction],
        payer: probe_wallet,
        recent_blockhash: get_recent_blockhash()
    )
    
    // Sign
    transaction.sign([probe_wallet_keypair])
    
    return ProbeTransaction {
        probe_id: generate_uuid(),
        probe_type: TIP_THRESHOLD,
        validator_identity: validator,
        tip_amount: tip,
        compute_units: 1400,
        account_count: 1,
        transaction: transaction,
        signature: transaction.signatures[0],
        timestamp_sent: current_time_micros(),
        ...
    }
```

### Probe Type B: Latency Test
```
create_latency_probe(validator: PublicKey, tip: u64) -> ProbeTransaction:
    """
    Similar to tip threshold but includes timestamp in memo.
    Allows precise latency measurement.
    """
    
    // Encode timestamp in memo
    timestamp = current_time_micros()
    memo_data = encode_timestamp(timestamp)
    
    memo_ix = MemoProgram.create_memo(
        memo: memo_data,
        signers: [probe_wallet]
    )
    
    // Standard compute budget
    compute_budget_ix = ComputeBudgetProgram.set_compute_unit_limit(
        units: 2000
    )
    
    priority_fee_ix = ComputeBudgetProgram.set_compute_unit_price(
        micro_lamports: tip
    )
    
    transaction = Transaction.new(
        instructions: [compute_budget_ix, priority_fee_ix, memo_ix],
        payer: probe_wallet,
        recent_blockhash: get_recent_blockhash()
    )
    
    transaction.sign([probe_wallet_keypair])
    
    return ProbeTransaction {
        probe_type: LATENCY_TEST,
        ...
    }
```

### Probe Type C: Congestion Pressure Test
```
create_congestion_probe(validator: PublicKey, tip: u64, 
                       target_cu: u32, target_accounts: u8) -> ProbeTransaction:
    """
    Simulates a complex bundle without actually trading.
    Uses many accounts and compute units to mimic real arbitrage.
    """
    
    instructions = []
    
    // Add compute budget matching target complexity
    compute_budget_ix = ComputeBudgetProgram.set_compute_unit_limit(
        units: target_cu  // e.g., 200_000 for realistic arb
    )
    instructions.append(compute_budget_ix)
    
    priority_fee_ix = ComputeBudgetProgram.set_compute_unit_price(
        micro_lamports: tip
    )
    instructions.append(priority_fee_ix)
    
    // Add dummy account references to simulate complexity
    for i in 0..target_accounts:
        dummy_account = generate_dummy_account(i)
        // Add writable reference but don't modify
        no_op_ix = create_no_op_instruction(
            account: dummy_account,
            writable: true  // Signals complexity to validator
        )
        instructions.append(no_op_ix)
    
    transaction = Transaction.new(
        instructions: instructions,
        payer: probe_wallet,
        recent_blockhash: get_recent_blockhash()
    )
    
    transaction.sign([probe_wallet_keypair])
    
    return ProbeTransaction {
        probe_type: CONGESTION_PRESSURE,
        compute_units: target_cu,
        account_count: target_accounts,
        bundle_size_bytes: transaction.message.serialize().len(),
        ...
    }
```

---

## 3. PROBE SENDING & RECORDING

### Send Probe
```
async send_probe(probe: ProbeTransaction, rpc_client: RpcClient) -> Result<Signature>:
    """
    Sends probe transaction to specified validator.
    """
    
    // Record send time
    send_time = current_time_micros()
    probe.timestamp_sent = send_time
    
    // Get current slot
    current_slot = await rpc_client.get_slot()
    probe.expected_slot = current_slot + 1
    
    try:
        // Send with validator preference if available
        config = RpcSendTransactionConfig {
            skip_preflight: false,
            preflight_commitment: "processed",
            encoding: "base64",
            max_retries: 0  // No automatic retries
        }
        
        signature = await rpc_client.send_transaction(
            transaction: probe.transaction,
            config: config
        )
        
        // Log successful send
        log_info(f"Probe {probe.probe_id} sent: signature={signature}")
        
        return Ok(signature)
        
    catch error:
        log_error(f"Failed to send probe {probe.probe_id}: {error}")
        return Err(error)
```

### Confirm Probe
```
async confirm_probe(probe: ProbeTransaction, rpc_client: RpcClient, 
                   timeout_slots: u64) -> ProbeResult:
    """
    Waits for probe confirmation and records result.
    """
    
    start_slot = await rpc_client.get_slot()
    start_time = current_time_micros()
    
    // Poll for confirmation
    while true:
        current_slot = await rpc_client.get_slot()
        
        // Check if timed out
        if current_slot > start_slot + timeout_slots:
            return ProbeResult {
                probe_id: probe.probe_id,
                included: false,
                error_code: Some("TIMEOUT"),
                slot_sent: start_slot,
                ...
            }
        
        // Check transaction status
        status = await rpc_client.get_signature_status(
            signature: probe.signature,
            search_transaction_history: true
        )
        
        if status.is_confirmed():
            confirm_time = current_time_micros()
            latency = confirm_time - start_time
            
            return ProbeResult {
                probe_id: probe.probe_id,
                probe_type: probe.probe_type,
                validator_identity: probe.validator_identity,
                tip_sent: probe.tip_amount,
                compute_units: probe.compute_units,
                account_count: probe.account_count,
                included: true,
                slot_included: Some(current_slot),
                timestamp_confirmed: Some(confirm_time),
                latency_ms: Some(latency / 1000),
                slot_sent: start_slot,
                retry_count: probe.retry_count,
                ...
            }
        
        // Wait before next poll
        await sleep(400)  // 400ms between polls
```

### Record Result
```
async record_probe_result(result: ProbeResult, storage: Storage):
    """
    Stores probe result for analysis.
    """
    
    // Store in database/memory
    await storage.insert_probe_result(result)
    
    // Update validator profile
    validator_profile = await storage.get_validator_profile(
        result.validator_identity
    )
    
    validator_profile.total_probes_sent += 1
    
    if result.included:
        validator_profile.total_probes_included += 1
        validator_profile.inclusion_rate = 
            validator_profile.total_probes_included / 
            validator_profile.total_probes_sent
        
        // Update tip statistics
        if result.tip_sent < validator_profile.min_tip_observed:
            validator_profile.min_tip_observed = result.tip_sent
        
        // Update latency statistics
        if let Some(latency) = result.latency_ms:
            update_latency_stats(validator_profile, latency)
    
    validator_profile.last_updated = current_time()
    
    await storage.update_validator_profile(validator_profile)
    
    // Log for monitoring
    log_metric("probe.result", {
        "validator": result.validator_identity,
        "included": result.included,
        "tip": result.tip_sent,
        "latency_ms": result.latency_ms
    })
```

---

## 4. ANALYSIS ALGORITHMS

### Calculate Inclusion Probability Curve
```
calculate_inclusion_curve(results: Vec<ProbeResult>) -> Vec<(u64, f64)>:
    """
    Computes probability of inclusion at each tip level.
    Returns: [(tip_amount, inclusion_probability), ...]
    """
    
    // Group results by tip bucket
    tip_buckets = {}
    
    for result in results:
        bucket = round_to_bucket(result.tip_sent, bucket_size=5000)
        
        if bucket not in tip_buckets:
            tip_buckets[bucket] = {
                "total": 0,
                "included": 0
            }
        
        tip_buckets[bucket]["total"] += 1
        if result.included:
            tip_buckets[bucket]["included"] += 1
    
    // Calculate probabilities
    curve = []
    for tip, stats in sorted(tip_buckets.items()):
        probability = stats["included"] / stats["total"]
        curve.append((tip, probability))
    
    return curve
```

### Find Optimal Tip
```
find_optimal_tip(inclusion_curve: Vec<(u64, f64)>, 
                target_probability: f64) -> u64:
    """
    Finds minimum tip to achieve target inclusion probability.
    """
    
    // Linear interpolation
    for i in 0..inclusion_curve.len() - 1:
        (tip1, prob1) = inclusion_curve[i]
        (tip2, prob2) = inclusion_curve[i + 1]
        
        if prob1 <= target_probability <= prob2:
            // Interpolate
            ratio = (target_probability - prob1) / (prob2 - prob1)
            optimal_tip = tip1 + ratio * (tip2 - tip1)
            return round_up(optimal_tip)
    
    // If not found, return highest tip (need more data)
    return inclusion_curve.last().tip
```

### Detect Validator Anomalies
```
detect_anomalies(validator_profile: ValidatorProfile, 
                recent_results: Vec<ProbeResult>) -> Vec<Anomaly>:
    """
    Identifies unusual validator behavior.
    """
    
    anomalies = []
    
    // Check sudden inclusion rate drop
    recent_inclusion_rate = calculate_recent_inclusion_rate(recent_results, window=50)
    
    if recent_inclusion_rate < validator_profile.inclusion_rate * 0.5:
        anomalies.append(Anomaly {
            type: "INCLUSION_DROP",
            severity: "HIGH",
            message: f"Inclusion rate dropped from {validator_profile.inclusion_rate:.2%} "
                    f"to {recent_inclusion_rate:.2%}",
            validator: validator_profile.validator_identity
        })
    
    // Check latency spike
    recent_avg_latency = calculate_recent_avg_latency(recent_results, window=20)
    
    if recent_avg_latency > validator_profile.avg_latency_ms * 2.0:
        anomalies.append(Anomaly {
            type: "LATENCY_SPIKE",
            severity: "MEDIUM",
            message: f"Latency spiked from {validator_profile.avg_latency_ms:.0f}ms "
                    f"to {recent_avg_latency:.0f}ms",
            validator: validator_profile.validator_identity
        })
    
    // Check tip threshold increase
    recent_min_tip = calculate_recent_min_successful_tip(recent_results, window=30)
    
    if recent_min_tip > validator_profile.min_tip_observed * 1.5:
        anomalies.append(Anomaly {
            type: "TIP_INCREASE",
            severity: "MEDIUM",
            message: f"Minimum competitive tip increased from "
                    f"{validator_profile.min_tip_observed} to {recent_min_tip}",
            validator: validator_profile.validator_identity
        })
    
    return anomalies
```

---

## 5. SIMULATION ENGINE

### Simulation State
```
Struct SimulationState:
    current_slot: u64
    current_timestamp: u64
    
    // Market conditions
    base_inclusion_probability: f64
    congestion_level: f64        // 0.0-1.0
    competing_bots: u32
    
    // Validator configuration
    validators: Vec<ValidatorConfig>
    current_leader: PublicKey
    
    // Tracking
    probes_sent: u64
    probes_included: u64
    total_cost: u64

Struct ValidatorConfig:
    identity: PublicKey
    
    // Tip acceptance
    min_tip: u64
    tip_sensitivity: f64         // How much tip affects inclusion
    
    // Performance characteristics
    base_latency_ms: u64
    latency_variance: f64
    
    // Behavior
    accepts_low_priority: bool
    compute_preference: f64      // Preference for high-CU txs
```

### Simulation Tick
```
simulation_tick(state: SimulationState, probe: ProbeTransaction) -> ProbeResult:
    """
    Simulates one probe transaction in synthetic environment.
    """
    
    // Get current leader validator
    leader = get_leader_for_slot(state.current_slot, state.validators)
    
    // Calculate base inclusion probability
    base_prob = leader.base_inclusion_probability
    
    // Adjust for tip
    if probe.tip_amount >= leader.min_tip:
        tip_factor = log(1 + probe.tip_amount - leader.min_tip) / log(1 + 100_000)
        tip_boost = tip_factor * leader.tip_sensitivity
    else:
        tip_boost = 0.0  // Below minimum, very low chance
    
    // Adjust for congestion
    congestion_penalty = state.congestion_level * 0.3
    
    // Adjust for competition
    competition_penalty = min(state.competing_bots / 50.0, 0.4)
    
    // Final inclusion probability
    inclusion_prob = base_prob + tip_boost - congestion_penalty - competition_penalty
    inclusion_prob = clamp(inclusion_prob, 0.0, 0.99)
    
    // Simulate outcome
    included = random() < inclusion_prob
    
    // Simulate latency
    if included:
        base_latency = leader.base_latency_ms
        latency_noise = gaussian_random(0, leader.latency_variance)
        actual_latency = max(base_latency + latency_noise, 50.0)  // Min 50ms
        
        slot_included = state.current_slot + 1
    else:
        actual_latency = None
        slot_included = None
    
    // Update state
    state.probes_sent += 1
    if included:
        state.probes_included += 1
    state.total_cost += probe.tip_amount
    state.current_slot += 1
    
    // Return result
    return ProbeResult {
        probe_id: probe.probe_id,
        probe_type: probe.probe_type,
        validator_identity: leader.identity,
        tip_sent: probe.tip_amount,
        compute_units: probe.compute_units,
        account_count: probe.account_count,
        included: included,
        slot_included: slot_included,
        latency_ms: actual_latency,
        slot_sent: state.current_slot,
        cluster_congestion: state.congestion_level,
        competing_transactions: state.competing_bots,
        ...
    }
```

### Run Full Simulation
```
run_simulation(config: SimulationConfig) -> SimulationReport:
    """
    Runs complete probe simulation scenario.
    """
    
    // Initialize state
    state = SimulationState {
        current_slot: 1_000_000,
        current_timestamp: current_time(),
        base_inclusion_probability: config.base_probability,
        congestion_level: config.initial_congestion,
        competing_bots: config.num_competing_bots,
        validators: load_validator_configs(config),
        ...
    }
    
    results = []
    
    // Run simulation rounds
    for round in 0..config.num_rounds:
        // Generate probe based on strategy
        probe = generate_probe_for_round(round, state, config)
        
        // Simulate
        result = simulation_tick(state, probe)
        results.append(result)
        
        // Update market conditions periodically
        if round % 100 == 0:
            update_market_conditions(state)
        
        // Log progress
        if round % 1000 == 0:
            log_info(f"Round {round}: Inclusion rate = "
                    f"{state.probes_included / state.probes_sent:.2%}")
    
    // Generate report
    report = generate_simulation_report(results, state)
    
    return report
```

---

## 6. REPORTING & VISUALIZATION

### Generate Report
```
generate_simulation_report(results: Vec<ProbeResult>, 
                          state: SimulationState) -> SimulationReport:
    """
    Creates comprehensive simulation report.
    """
    
    // Calculate metrics
    overall_inclusion_rate = state.probes_included / state.probes_sent
    avg_cost_per_probe = state.total_cost / state.probes_sent
    avg_cost_per_inclusion = state.total_cost / max(state.probes_included, 1)
    
    // Inclusion by tip level
    inclusion_curve = calculate_inclusion_curve(results)
    
    // Latency statistics
    latencies = [r.latency_ms for r in results if r.included]
    avg_latency = mean(latencies)
    p50_latency = percentile(latencies, 50)
    p95_latency = percentile(latencies, 95)
    
    // Per-validator breakdown
    validator_stats = calculate_per_validator_stats(results)
    
    // Optimal tip recommendation
    optimal_tip_60 = find_optimal_tip(inclusion_curve, 0.60)
    optimal_tip_75 = find_optimal_tip(inclusion_curve, 0.75)
    optimal_tip_90 = find_optimal_tip(inclusion_curve, 0.90)
    
    // Cost-benefit analysis
    cost_benefit = calculate_cost_benefit_ratio(results)
    
    return SimulationReport {
        timestamp: current_time(),
        total_probes: state.probes_sent,
        total_included: state.probes_included,
        overall_inclusion_rate: overall_inclusion_rate,
        
        // Cost metrics
        total_cost_lamports: state.total_cost,
        avg_cost_per_probe: avg_cost_per_probe,
        avg_cost_per_inclusion: avg_cost_per_inclusion,
        
        // Performance metrics
        avg_latency_ms: avg_latency,
        p50_latency_ms: p50_latency,
        p95_latency_ms: p95_latency,
        
        // Recommendations
        optimal_tip_60pct: optimal_tip_60,
        optimal_tip_75pct: optimal_tip_75,
        optimal_tip_90pct: optimal_tip_90,
        
        // Detailed data
        inclusion_curve: inclusion_curve,
        validator_stats: validator_stats,
        cost_benefit_ratio: cost_benefit,
        
        // Metadata
        simulation_config: state.config,
        market_conditions: state.market_snapshot()
    }
```

### JSON Report Contract
```json
{
  "timestamp": 1234567890,
  "simulation_id": "uuid",
  "summary": {
    "total_probes": 10000,
    "total_included": 6543,
    "inclusion_rate": 0.6543,
    "total_cost_lamports": 327150000,
    "avg_cost_per_probe": 32715,
    "avg_cost_per_inclusion": 50000
  },
  "performance": {
    "avg_latency_ms": 450.5,
    "p50_latency_ms": 420,
    "p95_latency_ms": 780,
    "p99_latency_ms": 1200
  },
  "inclusion_curve": [
    {"tip_lamports": 5000, "inclusion_probability": 0.12},
    {"tip_lamports": 10000, "inclusion_probability": 0.35},
    {"tip_lamports": 20000, "inclusion_probability": 0.58},
    {"tip_lamports": 35000, "inclusion_probability": 0.75},
    {"tip_lamports": 50000, "inclusion_probability": 0.87},
    {"tip_lamports": 75000, "inclusion_probability": 0.93}
  ],
  "recommendations": {
    "optimal_tip_60pct_confidence": 23000,
    "optimal_tip_75pct_confidence": 35000,
    "optimal_tip_90pct_confidence": 52000,
    "recommended_tip_range": [20000, 40000],
    "adaptive_strategy": "Use tip_bandit with these levels"
  },
  "validator_analysis": [
    {
      "validator_identity": "...",
      "probes_sent": 500,
      "inclusion_rate": 0.72,
      "avg_latency_ms": 420,
      "min_successful_tip": 18000,
      "behavior": "consistent_fast"
    }
  ],
  "anomalies_detected": [
    {
      "type": "SUDDEN_TIP_INCREASE",
      "validator": "...",
      "severity": "medium",
      "description": "Min tip jumped from 20k to 45k"
    }
  ],
  "market_conditions": {
    "avg_congestion": 0.45,
    "competing_bots_estimated": 25,
    "cluster_tps": 2400
  }
}
```

---

## 7. INTEGRATION WITH TIP BANDIT

### Feed Simulation Data to Bandit
```
integrate_with_bandit(simulation_report: SimulationReport, 
                     bandit: TipBandit) -> TipBandit:
    """
    Uses simulation results to initialize or update tip bandit.
    """
    
    // Extract recommended tip levels from simulation
    recommended_tips = extract_tip_levels_from_curve(
        simulation_report.inclusion_curve,
        num_arms=7
    )
    
    // Create or update bandit with these levels
    if bandit is None:
        bandit = TipBandit::new(
            tip_levels=recommended_tips,
            algorithm=UCB1
        )
    else:
        // Warm-start with simulation data
        for (tip, inclusion_prob) in simulation_report.inclusion_curve:
            arm = bandit.find_arm(tip)
            if arm exists:
                // Initialize with synthetic pulls
                arm.pulls = 100
                arm.successes = int(inclusion_prob * 100)
                arm.failures = 100 - arm.successes
                arm.avg_reward = estimate_reward_from_prob(inclusion_prob)
    
    return bandit
```

---

## END OF PSEUDOCODE
