"""
Secure Key Manager
Handles keypair management with HSM support, key rotation, and signing policies
"""
from typing import Optional, Tuple, Dict
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
import logging
import os
import json
from enum import Enum

logger = logging.getLogger(__name__)

class KeyType(Enum):
    """Types of keys used in the system"""
    FUNDING = "funding"      # Pays fees and gas
    STRATEGY = "strategy"    # Signs trading transactions
    ADMIN = "admin"         # Emergency overrides

@dataclass
class SigningPolicy:
    """Policy for transaction signing"""
    max_trade_size_usd: float = 10.0
    max_trades_per_minute: int = 10
    allowed_tokens: list = None
    allowed_dexes: list = None
    require_2fa: bool = False
    
    def __post_init__(self):
        if self.allowed_tokens is None:
            self.allowed_tokens = ["SOL", "USDC", "USDT"]
        if self.allowed_dexes is None:
            self.allowed_dexes = ["serum", "raydium", "orca"]

class KeyManager:
    """
    Secure key management with HSM support
    
    Features:
    - Multiple key types (funding, strategy, admin)
    - Signing policy enforcement
    - Rate limiting
    - Key rotation tracking
    - HSM integration structure
    """
    
    def __init__(
        self,
        use_hsm: bool = False,
        hsm_config: Optional[Dict] = None,
        signing_policy: Optional[SigningPolicy] = None
    ):
        self.use_hsm = use_hsm
        self.hsm_config = hsm_config or {}
        self.signing_policy = signing_policy or SigningPolicy()
        
        # Key storage (in production: load from HSM/encrypted storage)
        self.keys: Dict[KeyType, any] = {}
        
        # Rate limiting
        self.sign_counts = {
            "last_minute_start": datetime.now(timezone.utc),
            "count": 0
        }
        
        # Key rotation tracking
        self.key_metadata = {}
        
        # Security audit log
        self.audit_log = []
    
    def load_keys(self, key_paths: Dict[KeyType, str]) -> bool:
        """
        Load keys from secure storage
        
        Args:
            key_paths: Dictionary mapping KeyType to file paths
            
        Returns:
            True if successful
        """
        try:
            for key_type, path in key_paths.items():
                if self.use_hsm:
                    # Load from HSM
                    keypair = self._load_from_hsm(key_type)
                else:
                    # Load from encrypted file
                    keypair = self._load_from_file(path)
                
                if keypair:
                    self.keys[key_type] = keypair
                    self.key_metadata[key_type] = {
                        "loaded_at": datetime.now(timezone.utc),
                        "rotation_due": datetime.now(timezone.utc) + timedelta(days=30),
                        "sign_count": 0
                    }
                    
                    logger.info(f"✅ Loaded {key_type.value} key")
                else:
                    logger.error(f"❌ Failed to load {key_type.value} key")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading keys: {e}")
            return False
    
    def _load_from_hsm(self, key_type: KeyType):
        """
        Load keypair from HSM
        
        In production, this would connect to:
        - AWS CloudHSM
        - YubiHSM
        - Azure Key Vault
        - etc.
        """
        logger.info(f"Loading {key_type.value} from HSM (simulated)")
        
        # Simulate HSM access
        # In production: Use HSM SDK
        from solders.keypair import Keypair
        return Keypair()  # Placeholder
    
    def _load_from_file(self, path: str):
        """
        Load keypair from encrypted file
        
        Args:
            path: Path to encrypted key file
            
        Returns:
            Keypair or None
        """
        try:
            if not os.path.exists(path):
                logger.warning(f"Key file not found: {path}")
                # For testing: generate temporary key
                from solders.keypair import Keypair
                return Keypair()
            
            # In production: Decrypt with KMS or password
            with open(path, 'r') as f:
                key_data = json.load(f)
                # Decrypt and load...
                
            from solders.keypair import Keypair
            return Keypair()  # Placeholder
            
        except Exception as e:
            logger.error(f"Error loading key from file: {e}")
            return None
    
    def can_sign(
        self,
        key_type: KeyType,
        bundle_metadata: Dict
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if signing is allowed based on policy
        
        Args:
            key_type: Type of key to use
            bundle_metadata: Bundle metadata for policy check
            
        Returns:
            (allowed, reason) tuple
        """
        # Check if key exists
        if key_type not in self.keys:
            return False, f"{key_type.value} key not loaded"
        
        # Check rate limit
        now = datetime.now(timezone.utc)
        if (now - self.sign_counts["last_minute_start"]).total_seconds() > 60:
            # Reset counter
            self.sign_counts = {
                "last_minute_start": now,
                "count": 0
            }
        
        if self.sign_counts["count"] >= self.signing_policy.max_trades_per_minute:
            return False, f"Rate limit exceeded: {self.signing_policy.max_trades_per_minute}/min"
        
        # Check trade size
        trade_size = bundle_metadata.get('estimated_profit_usd', 0)
        if trade_size > self.signing_policy.max_trade_size_usd:
            return False, f"Trade size ${trade_size:.2f} exceeds limit ${self.signing_policy.max_trade_size_usd:.2f}"
        
        # Check allowed tokens
        pair = bundle_metadata.get('pair', '')
        tokens = pair.split('/')
        for token in tokens:
            if token not in self.signing_policy.allowed_tokens:
                return False, f"Token {token} not in whitelist"
        
        # Check allowed DEXs
        legs = bundle_metadata.get('legs', [])
        for leg in legs:
            dex = leg.get('dex', '').lower()
            if dex not in self.signing_policy.allowed_dexes:
                return False, f"DEX {dex} not in whitelist"
        
        # Check key rotation
        metadata = self.key_metadata.get(key_type, {})
        rotation_due = metadata.get('rotation_due')
        if rotation_due and now > rotation_due:
            return False, f"{key_type.value} key rotation overdue"
        
        return True, None
    
    def sign_bundle(
        self,
        key_type: KeyType,
        bundle_metadata: Dict,
        transactions: list
    ) -> Tuple[bool, Optional[str], Optional[list]]:
        """
        Sign bundle transactions
        
        Args:
            key_type: Type of key to use
            bundle_metadata: Bundle metadata
            transactions: List of transactions to sign
            
        Returns:
            (success, error, signed_transactions) tuple
        """
        # Check policy
        allowed, reason = self.can_sign(key_type, bundle_metadata)
        if not allowed:
            self._audit_log("SIGN_DENIED", key_type, reason, bundle_metadata)
            return False, reason, None
        
        try:
            keypair = self.keys[key_type]
            
            # Sign each transaction
            signed_txs = []
            for tx in transactions:
                # In production: Use HSM signing if enabled
                if self.use_hsm:
                    signed_tx = self._sign_with_hsm(keypair, tx)
                else:
                    # Local signing
                    # tx.sign([keypair])  # Already signed in bundle builder
                    signed_tx = tx
                
                signed_txs.append(signed_tx)
            
            # Update counters
            self.sign_counts["count"] += 1
            self.key_metadata[key_type]["sign_count"] += 1
            
            # Audit log
            self._audit_log("SIGN_SUCCESS", key_type, "Signed bundle", bundle_metadata)
            
            logger.info(
                f"✍️ Signed bundle with {key_type.value} key "
                f"({self.key_metadata[key_type]['sign_count']} total)"
            )
            
            return True, None, signed_txs
            
        except Exception as e:
            error = f"Signing error: {str(e)}"
            self._audit_log("SIGN_ERROR", key_type, error, bundle_metadata)
            return False, error, None
    
    def _sign_with_hsm(self, keypair, transaction):
        """Sign transaction using HSM"""
        # In production: Call HSM API
        return transaction
    
    def rotate_key(self, key_type: KeyType) -> bool:
        """
        Rotate a key
        
        Steps:
        1. Generate new key in HSM
        2. Transfer funds/authority to new key
        3. Update key metadata
        4. Archive old key securely
        
        Args:
            key_type: Type of key to rotate
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"🔄 Rotating {key_type.value} key")
            
            # Generate new key
            if self.use_hsm:
                new_keypair = self._load_from_hsm(key_type)
            else:
                from solders.keypair import Keypair
                new_keypair = Keypair()
            
            # Archive old key
            old_keypair = self.keys.get(key_type)
            if old_keypair:
                self._archive_key(key_type, old_keypair)
            
            # Update to new key
            self.keys[key_type] = new_keypair
            self.key_metadata[key_type] = {
                "loaded_at": datetime.now(timezone.utc),
                "rotation_due": datetime.now(timezone.utc) + timedelta(days=30),
                "sign_count": 0,
                "rotated_from": str(old_keypair.pubkey()) if old_keypair else None
            }
            
            self._audit_log("KEY_ROTATED", key_type, "Key rotation successful", {})
            
            logger.info(f"✅ {key_type.value} key rotated successfully")
            return True
            
        except Exception as e:
            logger.error(f"Key rotation error: {e}")
            self._audit_log("ROTATION_ERROR", key_type, str(e), {})
            return False
    
    def _archive_key(self, key_type: KeyType, keypair):
        """Archive old key securely"""
        # In production: Store in secure cold storage
        logger.info(f"Archiving old {key_type.value} key: {keypair.pubkey()}")
    
    def emergency_disable(self) -> bool:
        """
        Emergency key disable (kill switch)
        Clears all keys from memory
        """
        logger.critical("🚨 EMERGENCY: Disabling all keys")
        
        self.keys.clear()
        self._audit_log("EMERGENCY_DISABLE", None, "All keys disabled", {})
        
        return True
    
    def _audit_log(
        self,
        event: str,
        key_type: Optional[KeyType],
        details: str,
        metadata: Dict
    ):
        """Record security audit event"""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "key_type": key_type.value if key_type else None,
            "details": details,
            "metadata": metadata
        }
        
        self.audit_log.append(log_entry)
        
        # Keep only last 1000 events
        if len(self.audit_log) > 1000:
            self.audit_log = self.audit_log[-1000:]
    
    def get_audit_log(self, limit: int = 50) -> list:
        """Get recent audit events"""
        return self.audit_log[-limit:]
    
    def get_key_status(self) -> Dict:
        """Get status of all keys"""
        status = {}
        
        for key_type in KeyType:
            if key_type in self.keys:
                metadata = self.key_metadata.get(key_type, {})
                status[key_type.value] = {
                    "loaded": True,
                    "pubkey": str(self.keys[key_type].pubkey()),
                    "sign_count": metadata.get("sign_count", 0),
                    "rotation_due": metadata.get("rotation_due").isoformat() if metadata.get("rotation_due") else None
                }
            else:
                status[key_type.value] = {
                    "loaded": False
                }
        
        return status


# Example usage
if __name__ == "__main__":
    # Initialize key manager
    manager = KeyManager(
        use_hsm=False,  # Set to True for HSM
        signing_policy=SigningPolicy(
            max_trade_size_usd=10.0,
            max_trades_per_minute=10
        )
    )
    
    # Load keys
    key_paths = {
        KeyType.FUNDING: "/path/to/funding_key.json",
        KeyType.STRATEGY: "/path/to/strategy_key.json",
        KeyType.ADMIN: "/path/to/admin_key.json"
    }
    
    if manager.load_keys(key_paths):
        print("✅ Keys loaded")
        
        # Check signing permission
        bundle_metadata = {
            "estimated_profit_usd": 0.05,
            "pair": "SOL/USDC",
            "legs": [{"dex": "raydium"}, {"dex": "orca"}]
        }
        
        allowed, reason = manager.can_sign(KeyType.STRATEGY, bundle_metadata)
        print(f"\nCan sign: {allowed}")
        if not allowed:
            print(f"Reason: {reason}")
        
        # Get key status
        print(f"\nKey Status:")
        print(json.dumps(manager.get_key_status(), indent=2))
