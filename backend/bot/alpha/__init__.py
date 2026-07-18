"""
Alpha Package - Trading Intelligence
"""

from .fingerprint import (
    build_fingerprint,
    build_fingerprint_from_opportunity,
    fingerprint_hash,
    parse_fingerprint,
    mint_to_symbol
)

from .failure_taxonomy import (
    classify_failure,
    get_failure_details,
    should_retry,
    FailureTag
)

from .ev_net import (
    calculate_ev_net,
    quick_ev_check,
    optimal_priority_fee,
    EVCalculation,
    CostBreakdown
)

from .half_life import (
    check_ttl_gate,
    record_spread_observation,
    record_latency,
    get_half_life_stats,
    HalfLifeCalculator,
    HalfLifeStats,
    TTLDecision,
    TTL_GATE_ENABLED
)

from .crowding import (
    check_crowding_gate,
    record_spread,
    record_pool_update,
    record_trade_outcome,
    get_crowding_score,
    CrowdingCalculator,
    CrowdingScore,
    CrowdingDecision,
    CROWDING_GATE_ENABLED,
    HIGH_CROWDING_THRESHOLD,
    MEDIUM_CROWDING_THRESHOLD
)

from .markov import (
    calculate_ev_adj,
    record_trade_outcome as record_markov_outcome,
    get_markov_stats,
    MarkovModel,
    MarkovState,
    MarkovDecision,
    StateFeatures,
    features_to_state,
    MARKOV_POLICY_ENABLED
)

from .kelly import (
    calculate_optimal_size,
    get_kelly_sizing,
    update_risk_state,
    reset_daily_risk_state,
    should_stop_trading,
    get_risk_state,
    KellyResult,
    RiskState,
    KELLY_SIZING_ENABLED
)

from .kernel import (
    predict as kernel_predict,
    add_training_sample,
    save_model as save_kernel_model,
    get_model_stats as get_kernel_stats,
    KernelModel,
    ModelFeatures,
    ModelPrediction,
    KERNEL_MODEL_ENABLED
)

from .reporting import (
    generate_report,
    print_report,
    ReportGenerator,
    DailyReport,
    FingerprintStats
)

__all__ = [
    # Fingerprint
    'build_fingerprint',
    'build_fingerprint_from_opportunity', 
    'fingerprint_hash',
    'parse_fingerprint',
    'mint_to_symbol',
    
    # Failure taxonomy
    'classify_failure',
    'get_failure_details',
    'should_retry',
    'FailureTag',
    
    # EV Net
    'calculate_ev_net',
    'quick_ev_check',
    'optimal_priority_fee',
    'EVCalculation',
    'CostBreakdown',
    
    # Half-life / TTL (Step 8)
    'check_ttl_gate',
    'record_spread_observation',
    'record_latency',
    'get_half_life_stats',
    'HalfLifeCalculator',
    'HalfLifeStats',
    'TTLDecision',
    'TTL_GATE_ENABLED',
    
    # Crowding (Step 9)
    'check_crowding_gate',
    'record_spread',
    'record_pool_update',
    'record_trade_outcome',
    'get_crowding_score',
    'CrowdingCalculator',
    'CrowdingScore',
    'CrowdingDecision',
    'CROWDING_GATE_ENABLED',
    'HIGH_CROWDING_THRESHOLD',
    'MEDIUM_CROWDING_THRESHOLD',
    
    # Markov (Step 10)
    'calculate_ev_adj',
    'record_markov_outcome',
    'get_markov_stats',
    'MarkovModel',
    'MarkovState',
    'MarkovDecision',
    'StateFeatures',
    'features_to_state',
    'MARKOV_POLICY_ENABLED',
    
    # Kelly Sizing (Step 12)
    'calculate_optimal_size',
    'get_kelly_sizing',
    'update_risk_state',
    'reset_daily_risk_state',
    'should_stop_trading',
    'get_risk_state',
    'KellyResult',
    'RiskState',
    'KELLY_SIZING_ENABLED',
    
    # Kernel Model (Step 11)
    'kernel_predict',
    'add_training_sample',
    'save_kernel_model',
    'get_kernel_stats',
    'KernelModel',
    'ModelFeatures',
    'ModelPrediction',
    'KERNEL_MODEL_ENABLED',
    
    # Reporting (Step 13)
    'generate_report',
    'print_report',
    'ReportGenerator',
    'DailyReport',
    'FingerprintStats',
]
