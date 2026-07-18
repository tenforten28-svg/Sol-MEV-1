"""
KERNEL MODEL - Nonlinear Predictor (ML)
=======================================
Step 11: Train kernel model offline from SQLite data.

Predicts:
- P_success: Probability of trade success
- slippage: Expected slippage
- TTL: Time-to-live before opportunity decays

Uses rolling window + regularization for online learning.
"""

import os
import time
import math
import json
import logging
import pickle
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np

logger = logging.getLogger('kernel')

# ============================================================================
# CONFIG
# ============================================================================

# Feature flag
KERNEL_MODEL_ENABLED = os.environ.get('KERNEL_MODEL', 'false').lower() == 'true'

# Model paths
MODEL_DIR = Path(__file__).parent.parent / 'data' / 'models'
P_SUCCESS_MODEL_PATH = MODEL_DIR / 'p_success_model.pkl'
SLIPPAGE_MODEL_PATH = MODEL_DIR / 'slippage_model.pkl'
TTL_MODEL_PATH = MODEL_DIR / 'ttl_model.pkl'

# Training config
ROLLING_WINDOW_SIZE = 1000  # Number of recent samples for training
REGULARIZATION_LAMBDA = 0.01  # L2 regularization
LEARNING_RATE = 0.01
MIN_SAMPLES_FOR_TRAINING = 50

# Feature normalization
FEATURE_MEANS: Dict[str, float] = {}
FEATURE_STDS: Dict[str, float] = {}

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ModelFeatures:
    """Features for ML model input"""
    ev_net: float
    spread_bps: float
    liquidity_depth_usd: float
    crowding_score: float
    half_life_ms: float
    latency_ms: float
    recent_success_rate: float
    recent_failure_rate: float
    pool_update_rate: float  # Updates per second
    time_of_day_hour: int
    
    def to_vector(self) -> np.ndarray:
        """Convert to feature vector"""
        return np.array([
            self.ev_net,
            self.spread_bps,
            math.log1p(self.liquidity_depth_usd),  # Log transform
            self.crowding_score,
            math.log1p(self.half_life_ms),
            math.log1p(self.latency_ms),
            self.recent_success_rate,
            self.recent_failure_rate,
            self.pool_update_rate,
            self.time_of_day_hour / 24.0  # Normalize
        ])
    
    def to_dict(self) -> Dict:
        return {
            'ev_net': self.ev_net,
            'spread_bps': self.spread_bps,
            'liquidity_depth_usd': self.liquidity_depth_usd,
            'crowding_score': self.crowding_score,
            'half_life_ms': self.half_life_ms,
            'latency_ms': self.latency_ms,
            'recent_success_rate': self.recent_success_rate,
            'recent_failure_rate': self.recent_failure_rate,
            'pool_update_rate': self.pool_update_rate,
            'time_of_day_hour': self.time_of_day_hour
        }


@dataclass
class ModelPrediction:
    """Prediction from kernel model"""
    p_success: float
    slippage_bps: float
    ttl_ms: float
    confidence: float
    features_used: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'p_success': self.p_success,
            'slippage_bps': self.slippage_bps,
            'ttl_ms': self.ttl_ms,
            'confidence': self.confidence,
            'features_used': self.features_used
        }


@dataclass
class TrainingSample:
    """Single training sample"""
    features: np.ndarray
    success: bool
    slippage_bps: float
    ttl_ms: float
    ts_ms: int


# ============================================================================
# KERNEL FUNCTIONS
# ============================================================================

def rbf_kernel(x1: np.ndarray, x2: np.ndarray, gamma: float = 0.1) -> float:
    """Radial Basis Function (Gaussian) kernel"""
    diff = x1 - x2
    return math.exp(-gamma * np.dot(diff, diff))


def polynomial_kernel(x1: np.ndarray, x2: np.ndarray, degree: int = 2, c: float = 1.0) -> float:
    """Polynomial kernel"""
    return (np.dot(x1, x2) + c) ** degree


def linear_kernel(x1: np.ndarray, x2: np.ndarray) -> float:
    """Linear kernel (dot product)"""
    return np.dot(x1, x2)


# ============================================================================
# KERNEL MODEL
# ============================================================================

class KernelModel:
    """
    Simple kernel-based model for prediction.
    
    Uses weighted k-nearest neighbors with kernel similarity.
    Lightweight alternative to full SVM for online updates.
    """
    
    def __init__(self, kernel_type: str = 'rbf', gamma: float = 0.1):
        self.kernel_type = kernel_type
        self.gamma = gamma
        
        # Training data (rolling window)
        self.samples: List[TrainingSample] = []
        self.max_samples = ROLLING_WINDOW_SIZE
        
        # Feature statistics for normalization
        self.feature_means: Optional[np.ndarray] = None
        self.feature_stds: Optional[np.ndarray] = None
        
        # Model weights (for weighted prediction)
        self.weights: Optional[np.ndarray] = None
    
    def _kernel(self, x1: np.ndarray, x2: np.ndarray) -> float:
        """Compute kernel similarity"""
        if self.kernel_type == 'rbf':
            return rbf_kernel(x1, x2, self.gamma)
        elif self.kernel_type == 'polynomial':
            return polynomial_kernel(x1, x2)
        else:
            return linear_kernel(x1, x2)
    
    def _normalize(self, x: np.ndarray) -> np.ndarray:
        """Normalize features"""
        if self.feature_means is None or self.feature_stds is None:
            return x
        
        # Avoid division by zero
        stds = np.where(self.feature_stds > 1e-8, self.feature_stds, 1.0)
        return (x - self.feature_means) / stds
    
    def _update_normalization(self):
        """Update feature statistics from samples"""
        if len(self.samples) < 10:
            return
        
        features = np.array([s.features for s in self.samples])
        self.feature_means = np.mean(features, axis=0)
        self.feature_stds = np.std(features, axis=0)
    
    def add_sample(
        self,
        features: ModelFeatures,
        success: bool,
        slippage_bps: float = 0,
        ttl_ms: float = 500
    ):
        """Add a training sample"""
        sample = TrainingSample(
            features=features.to_vector(),
            success=success,
            slippage_bps=slippage_bps,
            ttl_ms=ttl_ms,
            ts_ms=int(time.time() * 1000)
        )
        
        self.samples.append(sample)
        
        # Trim to rolling window
        if len(self.samples) > self.max_samples:
            self.samples = self.samples[-self.max_samples:]
        
        # Update normalization periodically
        if len(self.samples) % 50 == 0:
            self._update_normalization()
    
    def predict_p_success(self, features: ModelFeatures, k: int = 20) -> Tuple[float, float]:
        """
        Predict success probability using kernel-weighted k-NN.
        
        Returns:
            Tuple of (probability, confidence)
        """
        if len(self.samples) < MIN_SAMPLES_FOR_TRAINING:
            return 0.5, 0.0  # Default with zero confidence
        
        x = self._normalize(features.to_vector())
        
        # Compute kernel similarities to all samples
        similarities = []
        for sample in self.samples:
            sample_x = self._normalize(sample.features)
            sim = self._kernel(x, sample_x)
            similarities.append((sim, sample.success))
        
        # Sort by similarity and take top k
        similarities.sort(key=lambda x: x[0], reverse=True)
        top_k = similarities[:k]
        
        # Weighted vote
        total_weight = sum(s[0] for s in top_k)
        if total_weight < 1e-8:
            return 0.5, 0.0
        
        p_success = sum(s[0] * (1.0 if s[1] else 0.0) for s in top_k) / total_weight
        
        # Confidence based on weight concentration
        confidence = min(1.0, total_weight / k)
        
        return p_success, confidence
    
    def predict_slippage(self, features: ModelFeatures, k: int = 20) -> Tuple[float, float]:
        """
        Predict expected slippage using kernel-weighted k-NN.
        
        Returns:
            Tuple of (slippage_bps, confidence)
        """
        if len(self.samples) < MIN_SAMPLES_FOR_TRAINING:
            return 10.0, 0.0  # Default 10 bps
        
        x = self._normalize(features.to_vector())
        
        similarities = []
        for sample in self.samples:
            sample_x = self._normalize(sample.features)
            sim = self._kernel(x, sample_x)
            similarities.append((sim, sample.slippage_bps))
        
        similarities.sort(key=lambda x: x[0], reverse=True)
        top_k = similarities[:k]
        
        total_weight = sum(s[0] for s in top_k)
        if total_weight < 1e-8:
            return 10.0, 0.0
        
        slippage = sum(s[0] * s[1] for s in top_k) / total_weight
        confidence = min(1.0, total_weight / k)
        
        return slippage, confidence
    
    def predict_ttl(self, features: ModelFeatures, k: int = 20) -> Tuple[float, float]:
        """
        Predict time-to-live using kernel-weighted k-NN.
        
        Returns:
            Tuple of (ttl_ms, confidence)
        """
        if len(self.samples) < MIN_SAMPLES_FOR_TRAINING:
            return 500.0, 0.0  # Default 500ms
        
        x = self._normalize(features.to_vector())
        
        similarities = []
        for sample in self.samples:
            sample_x = self._normalize(sample.features)
            sim = self._kernel(x, sample_x)
            similarities.append((sim, sample.ttl_ms))
        
        similarities.sort(key=lambda x: x[0], reverse=True)
        top_k = similarities[:k]
        
        total_weight = sum(s[0] for s in top_k)
        if total_weight < 1e-8:
            return 500.0, 0.0
        
        ttl = sum(s[0] * s[1] for s in top_k) / total_weight
        confidence = min(1.0, total_weight / k)
        
        return ttl, confidence
    
    def predict(self, features: ModelFeatures) -> ModelPrediction:
        """Get all predictions"""
        p_success, p_conf = self.predict_p_success(features)
        slippage, s_conf = self.predict_slippage(features)
        ttl, t_conf = self.predict_ttl(features)
        
        # Overall confidence is minimum
        confidence = min(p_conf, s_conf, t_conf)
        
        return ModelPrediction(
            p_success=p_success,
            slippage_bps=slippage,
            ttl_ms=ttl,
            confidence=confidence,
            features_used=features.to_dict()
        )
    
    def save(self, path: Path):
        """Save model to file"""
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'kernel_type': self.kernel_type,
            'gamma': self.gamma,
            'samples': [(s.features.tolist(), s.success, s.slippage_bps, s.ttl_ms, s.ts_ms) 
                       for s in self.samples],
            'feature_means': self.feature_means.tolist() if self.feature_means is not None else None,
            'feature_stds': self.feature_stds.tolist() if self.feature_stds is not None else None
        }
        
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        
        logger.info(f"Model saved to {path}")
    
    def load(self, path: Path) -> bool:
        """Load model from file"""
        if not path.exists():
            logger.warning(f"Model file not found: {path}")
            return False
        
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            
            self.kernel_type = data['kernel_type']
            self.gamma = data['gamma']
            self.samples = [
                TrainingSample(
                    features=np.array(s[0]),
                    success=s[1],
                    slippage_bps=s[2],
                    ttl_ms=s[3],
                    ts_ms=s[4]
                ) for s in data['samples']
            ]
            
            if data['feature_means']:
                self.feature_means = np.array(data['feature_means'])
            if data['feature_stds']:
                self.feature_stds = np.array(data['feature_stds'])
            
            logger.info(f"Model loaded from {path} ({len(self.samples)} samples)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False
    
    def get_stats(self) -> Dict:
        """Get model statistics"""
        if len(self.samples) == 0:
            return {'samples': 0, 'ready': False}
        
        successes = sum(1 for s in self.samples if s.success)
        
        return {
            'samples': len(self.samples),
            'success_rate': successes / len(self.samples),
            'avg_slippage': np.mean([s.slippage_bps for s in self.samples]),
            'avg_ttl': np.mean([s.ttl_ms for s in self.samples]),
            'ready': len(self.samples) >= MIN_SAMPLES_FOR_TRAINING,
            'kernel_type': self.kernel_type,
            'gamma': self.gamma
        }


# ============================================================================
# GLOBAL MODEL ACCESS
# ============================================================================

_model: Optional[KernelModel] = None


def get_model() -> KernelModel:
    """Get the global kernel model"""
    global _model
    if _model is None:
        _model = KernelModel()
        # Try to load saved model
        _model.load(P_SUCCESS_MODEL_PATH)
    return _model


def predict(features: ModelFeatures) -> ModelPrediction:
    """Get prediction from kernel model"""
    if not KERNEL_MODEL_ENABLED:
        return ModelPrediction(
            p_success=0.5,
            slippage_bps=10.0,
            ttl_ms=500.0,
            confidence=0.0,
            features_used={'note': 'KERNEL_MODEL disabled'}
        )
    
    return get_model().predict(features)


def add_training_sample(
    features: ModelFeatures,
    success: bool,
    slippage_bps: float = 0,
    ttl_ms: float = 500
):
    """Add a training sample to the model"""
    get_model().add_sample(features, success, slippage_bps, ttl_ms)


def save_model():
    """Save current model to disk"""
    get_model().save(P_SUCCESS_MODEL_PATH)


def get_model_stats() -> Dict:
    """Get model statistics"""
    return get_model().get_stats()


# ============================================================================
# TRAINING SCRIPT
# ============================================================================

def train_from_sqlite(db_path: str, output_dir: Optional[str] = None):
    """
    Train kernel model from SQLite database.
    
    This is meant to be run offline:
    python -m bot.alpha.kernel --train --db ./data/bot_events.sqlite
    """
    import sqlite3
    
    logger.info(f"Training from database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Load opportunity + decision + tx_result event triplets
    query = """
    SELECT 
        o.payload_json as opp_payload,
        d.payload_json as dec_payload,
        t.payload_json as tx_payload
    FROM events o
    JOIN events d ON d.fingerprint = o.fingerprint 
        AND d.type = 'decision'
        AND d.ts_ms > o.ts_ms 
        AND d.ts_ms < o.ts_ms + 5000
    LEFT JOIN events t ON t.fingerprint = o.fingerprint
        AND t.type = 'tx_result'
        AND t.ts_ms > d.ts_ms
        AND t.ts_ms < d.ts_ms + 60000
    WHERE o.type = 'opportunity_detected'
    ORDER BY o.ts_ms DESC
    LIMIT 10000
    """
    
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Database query failed: {e}")
        conn.close()
        return
    
    logger.info(f"Found {len(rows)} training samples")
    
    model = KernelModel()
    
    for opp_json, dec_json, tx_json in rows:
        try:
            opp = json.loads(opp_json)
            dec = json.loads(dec_json)
            tx = json.loads(tx_json) if tx_json else None
            
            # Extract features
            features = ModelFeatures(
                ev_net=dec.get('ev_net_est', 0),
                spread_bps=opp.get('spread_bps', 0),
                liquidity_depth_usd=opp.get('liquidity_depth_usd', 10000),
                crowding_score=dec.get('crowding_score', 0.5),
                half_life_ms=opp.get('half_life_ms', 500),
                latency_ms=opp.get('detect_latency_ms', 100),
                recent_success_rate=0.5,  # Would need to compute
                recent_failure_rate=0.5,
                pool_update_rate=1.0,
                time_of_day_hour=12
            )
            
            # Determine success
            success = tx is not None and tx.get('status') == 'SUCCESS'
            slippage = tx.get('slippage_bps', 0) if tx else 0
            
            model.add_sample(features, success, slippage)
            
        except (json.JSONDecodeError, KeyError) as e:
            continue
    
    conn.close()
    
    # Save model
    if output_dir:
        out_path = Path(output_dir) / 'p_success_model.pkl'
    else:
        out_path = P_SUCCESS_MODEL_PATH
    
    model.save(out_path)
    
    stats = model.get_stats()
    logger.info(f"Training complete: {stats}")


# ============================================================================
# TESTS
# ============================================================================

def test_kernel_model():
    """Test kernel model"""
    model = KernelModel()
    
    # Generate synthetic training data
    for i in range(100):
        features = ModelFeatures(
            ev_net=0.1 + (i % 10) * 0.05,
            spread_bps=10 + (i % 20),
            liquidity_depth_usd=50000 + i * 1000,
            crowding_score=0.3 + (i % 5) * 0.1,
            half_life_ms=300 + i * 10,
            latency_ms=100 + (i % 10) * 20,
            recent_success_rate=0.6,
            recent_failure_rate=0.4,
            pool_update_rate=2.0,
            time_of_day_hour=i % 24
        )
        
        # Success correlates with EV and low crowding
        success = (features.ev_net > 0.2 and features.crowding_score < 0.5)
        slippage = 5 + features.crowding_score * 20
        
        model.add_sample(features, success, slippage)
    
    # Test prediction
    test_features = ModelFeatures(
        ev_net=0.3,
        spread_bps=15,
        liquidity_depth_usd=80000,
        crowding_score=0.4,
        half_life_ms=400,
        latency_ms=150,
        recent_success_rate=0.7,
        recent_failure_rate=0.3,
        pool_update_rate=1.5,
        time_of_day_hour=14
    )
    
    prediction = model.predict(test_features)
    
    print(f"Prediction:")
    print(f"  P_success: {prediction.p_success:.3f}")
    print(f"  Slippage: {prediction.slippage_bps:.1f} bps")
    print(f"  TTL: {prediction.ttl_ms:.0f} ms")
    print(f"  Confidence: {prediction.confidence:.2f}")
    
    stats = model.get_stats()
    print(f"\nModel stats: {stats}")


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    
    parser = argparse.ArgumentParser(description='Kernel Model Training')
    parser.add_argument('--train', action='store_true', help='Train from database')
    parser.add_argument('--db', type=str, default='./data/bot_events.sqlite', help='Database path')
    parser.add_argument('--output', type=str, help='Output directory')
    parser.add_argument('--test', action='store_true', help='Run tests')
    
    args = parser.parse_args()
    
    if args.train:
        train_from_sqlite(args.db, args.output)
    elif args.test:
        test_kernel_model()
    else:
        test_kernel_model()
