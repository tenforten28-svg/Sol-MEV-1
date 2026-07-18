"""
Bundle Builder - Constructs atomic transaction bundles for MEV execution
Handles Jito bundle format and Solana transaction building
"""
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import base58
from solders.transaction import Transaction
from solders.message import Message
from solders.instruction import Instruction, AccountMeta
from solders.pubkey import Pubkey
from solders.hash import Hash
from solders.keypair import Keypair
from solders.system_program import TransferParams, transfer
import os

logger = logging.getLogger(__name__)

@dataclass
class TradeLeg:
    """Single leg of an arbitrage trade"""
    dex: str
    action: str  # "buy" or "sell"
    token_in: str
    token_out: str
    amount_in: float
    min_amount_out: float
    pool_address: Optional[str] = None
    
@dataclass
class Bundle:
    """Atomic transaction bundle"""
    transactions: List[Transaction]
    legs: List[TradeLeg]
    estimated_profit: float
    tip_lamports: int
    max_compute_units: int
    priority_fee: int
    created_at: datetime
    bundle_id: str

class BundleBuilder:
    """Builds atomic transaction bundles for MEV execution"""
    
    def __init__(
        self,
        keypair: Optional[Keypair] = None,
        compute_budget: int = 200_000,
        base_priority_fee: int = 10_000
    ):
        self.keypair = keypair
        self.compute_budget = compute_budget
        self.base_priority_fee = base_priority_fee
        
        # DEX Program IDs (mainnet)
        self.SERUM_PROGRAM_ID = Pubkey.from_string("9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin")
        self.RAYDIUM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
        self.ORCA_PROGRAM_ID = Pubkey.from_string("9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP")
        
        # Compute Budget Program
        self.COMPUTE_BUDGET_PROGRAM = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
        
    def create_compute_budget_instructions(self, units: int, priority_fee: int) -> List[Instruction]:
        """Create compute budget instructions for priority"""
        instructions = []
        
        # Set compute unit limit
        set_units_data = bytes([0]) + units.to_bytes(4, 'little')
        instructions.append(Instruction(
            program_id=self.COMPUTE_BUDGET_PROGRAM,
            accounts=[],
            data=set_units_data
        ))
        
        # Set compute unit price (micro-lamports per compute unit)
        set_price_data = bytes([3]) + priority_fee.to_bytes(8, 'little')
        instructions.append(Instruction(
            program_id=self.COMPUTE_BUDGET_PROGRAM,
            accounts=[],
            data=set_price_data
        ))
        
        return instructions
    
    def build_serum_swap_instruction(
        self,
        leg: TradeLeg,
        user_pubkey: Pubkey
    ) -> Instruction:
        """Build Serum DEX swap instruction (simplified)"""
        # This is a placeholder - real implementation would use Serum SDK
        # and construct proper market, order book, and vault accounts
        
        logger.info(f"Building Serum swap: {leg.action} {leg.amount_in} {leg.token_in}")
        
        # Placeholder instruction
        accounts = [
            AccountMeta(pubkey=user_pubkey, is_signer=True, is_writable=True),
        ]
        
        return Instruction(
            program_id=self.SERUM_PROGRAM_ID,
            accounts=accounts,
            data=bytes([1])  # Placeholder
        )
    
    def build_raydium_swap_instruction(
        self,
        leg: TradeLeg,
        user_pubkey: Pubkey
    ) -> Instruction:
        """Build Raydium AMM swap instruction"""
        logger.info(f"Building Raydium swap: {leg.action} {leg.amount_in} {leg.token_in}")
        
        # Simplified - real implementation would use Raydium SDK
        accounts = [
            AccountMeta(pubkey=user_pubkey, is_signer=True, is_writable=True),
        ]
        
        return Instruction(
            program_id=self.RAYDIUM_PROGRAM_ID,
            accounts=accounts,
            data=bytes([9])  # Swap instruction discriminator
        )
    
    def build_orca_swap_instruction(
        self,
        leg: TradeLeg,
        user_pubkey: Pubkey
    ) -> Instruction:
        """Build Orca Whirlpool swap instruction"""
        logger.info(f"Building Orca swap: {leg.action} {leg.amount_in} {leg.token_in}")
        
        # Simplified - real implementation would use Orca SDK
        accounts = [
            AccountMeta(pubkey=user_pubkey, is_signer=True, is_writable=True),
        ]
        
        return Instruction(
            program_id=self.ORCA_PROGRAM_ID,
            accounts=accounts,
            data=bytes([248, 198, 158, 145, 225, 117, 135, 200])  # Swap discriminator
        )
    
    def build_bundle(
        self,
        legs: List[TradeLeg],
        estimated_profit: float,
        recent_blockhash: Hash,
        tip_lamports: int = 10_000
    ) -> Optional[Bundle]:
        """
        Build an atomic transaction bundle for arbitrage
        
        Args:
            legs: List of trade legs to execute atomically
            estimated_profit: Expected profit in USD
            recent_blockhash: Recent Solana blockhash
            tip_lamports: Jito tip amount
            
        Returns:
            Bundle object ready for signing and submission
        """
        try:
            if not self.keypair:
                logger.error("No keypair provided for bundle building")
                return None
            
            user_pubkey = self.keypair.pubkey()
            instructions = []
            
            # 1. Add compute budget instructions (priority)
            compute_instructions = self.create_compute_budget_instructions(
                units=self.compute_budget,
                priority_fee=self.base_priority_fee
            )
            instructions.extend(compute_instructions)
            
            # 2. Build swap instructions for each leg
            for leg in legs:
                if leg.dex.lower() == "serum":
                    instr = self.build_serum_swap_instruction(leg, user_pubkey)
                elif leg.dex.lower() == "raydium":
                    instr = self.build_raydium_swap_instruction(leg, user_pubkey)
                elif leg.dex.lower() == "orca":
                    instr = self.build_orca_swap_instruction(leg, user_pubkey)
                else:
                    logger.warning(f"Unknown DEX: {leg.dex}")
                    continue
                
                instructions.append(instr)
            
            # 3. Add Jito tip transfer (to tip account)
            # Jito tip accounts: https://jito-labs.gitbook.io/mev/searcher-resources/tip-payment
            jito_tip_accounts = [
                "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
                "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
                "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
                "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
                "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
                "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
                "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
                "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT"
            ]
            
            # Use first tip account (randomize in production)
            tip_account = Pubkey.from_string(jito_tip_accounts[0])
            
            tip_instruction = transfer(
                TransferParams(
                    from_pubkey=user_pubkey,
                    to_pubkey=tip_account,
                    lamports=tip_lamports
                )
            )
            instructions.append(tip_instruction)
            
            # 4. Create transaction
            message = Message.new_with_blockhash(
                instructions,
                user_pubkey,
                recent_blockhash
            )
            
            transaction = Transaction.new_unsigned(message)
            
            # 5. Sign transaction
            transaction.sign([self.keypair], recent_blockhash)
            
            # 6. Create bundle
            import uuid
            bundle = Bundle(
                transactions=[transaction],
                legs=legs,
                estimated_profit=estimated_profit,
                tip_lamports=tip_lamports,
                max_compute_units=self.compute_budget,
                priority_fee=self.base_priority_fee,
                created_at=datetime.now(timezone.utc),
                bundle_id=str(uuid.uuid4())
            )
            
            logger.info(
                f"✅ Bundle built: {len(legs)} legs, "
                f"profit=${estimated_profit:.4f}, "
                f"tip={tip_lamports} lamports"
            )
            
            return bundle
            
        except Exception as e:
            logger.error(f"Error building bundle: {e}")
            return None
    
    def estimate_bundle_size(self, legs: List[TradeLeg]) -> int:
        """Estimate transaction size in bytes"""
        # Base transaction overhead
        size = 64  # Signature
        size += 32  # Recent blockhash
        size += 3   # Message header
        
        # Compute budget instructions
        size += 2 * 40  # ~40 bytes per instruction
        
        # Swap instructions (estimate)
        size += len(legs) * 200  # ~200 bytes per swap
        
        # Tip transfer
        size += 40
        
        return size
    
    def validate_bundle(self, bundle: Bundle) -> Tuple[bool, Optional[str]]:
        """Validate bundle before submission"""
        
        # Check transaction size
        for tx in bundle.transactions:
            tx_bytes = bytes(tx)
            if len(tx_bytes) > 1232:  # Solana max tx size
                return False, f"Transaction too large: {len(tx_bytes)} bytes"
        
        # Check compute units
        if bundle.max_compute_units > 1_400_000:
            return False, f"Compute units too high: {bundle.max_compute_units}"
        
        # Check legs
        if not bundle.legs:
            return False, "No trade legs in bundle"
        
        if len(bundle.legs) > 5:
            return False, f"Too many legs: {len(bundle.legs)}"
        
        # Check profit
        if bundle.estimated_profit <= 0:
            return False, f"Negative profit: ${bundle.estimated_profit}"
        
        return True, None


# Test/Example usage
if __name__ == "__main__":
    # Example: Create a test bundle
    from solders.hash import Hash
    
    # Generate test keypair (DO NOT use in production)
    test_keypair = Keypair()
    
    builder = BundleBuilder(keypair=test_keypair)
    
    # Example arbitrage legs
    legs = [
        TradeLeg(
            dex="raydium",
            action="buy",
            token_in="USDC",
            token_out="SOL",
            amount_in=5.0,
            min_amount_out=0.03
        ),
        TradeLeg(
            dex="orca",
            action="sell",
            token_in="SOL",
            token_out="USDC",
            amount_in=0.03,
            min_amount_out=5.01
        )
    ]
    
    # Build bundle (with dummy blockhash)
    bundle = builder.build_bundle(
        legs=legs,
        estimated_profit=0.01,
        recent_blockhash=Hash.default(),
        tip_lamports=10_000
    )
    
    if bundle:
        print(f"✅ Bundle created: {bundle.bundle_id}")
        print(f"   Legs: {len(bundle.legs)}")
        print(f"   Profit: ${bundle.estimated_profit}")
        print(f"   Tip: {bundle.tip_lamports} lamports")
        
        # Validate
        valid, error = builder.validate_bundle(bundle)
        print(f"   Valid: {valid}")
        if error:
            print(f"   Error: {error}")
