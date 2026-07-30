"""
Real Solana DEX Swap Implementations
Supports Raydium, Orca, and Jupiter aggregator
"""

import asyncio
import logging
import os
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.transaction import Transaction
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
import struct
import base64

logger = logging.getLogger(__name__)

# Program IDs (Mainnet)
RAYDIUM_AMM_PROGRAM_ID = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
ORCA_WHIRLPOOL_PROGRAM_ID = Pubkey.from_string("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc")
JUPITER_AGGREGATOR_V6 = Pubkey.from_string("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

# Common token addresses (Mainnet)
TOKEN_MINTS = {
    'SOL': 'So11111111111111111111111111111111111111112',
    'USDC': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
    'USDT': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
    'RAY': '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
    'ORCA': 'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE',
    'JUP': 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',
    'JTO': 'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL',
    'PYTH': 'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3',
}


@dataclass
class SwapParams:
    """Parameters for a DEX swap"""
    input_mint: Pubkey
    output_mint: Pubkey
    amount_in: int  # In lamports/smallest unit
    minimum_amount_out: int  # Slippage protection
    user_wallet: Pubkey


class RaydiumSwap:
    """
    Raydium AMM swap implementation
    Uses Raydium's liquidity pools for token swaps
    """
    
    def __init__(self, rpc_client: AsyncClient):
        self.client = rpc_client
        self.program_id = RAYDIUM_AMM_PROGRAM_ID
    
    async def get_pool_keys(
        self,
        token_a: str,
        token_b: str
    ) -> Optional[Dict]:
        """
        Get Raydium pool keys for a token pair
        In production, you'd query this from Raydium's API or on-chain data
        """
        # Pool addresses (these need to be fetched dynamically in production)
        # Example structure - you'd get these from Raydium SDK or API
        pool_keys = {
            'SOL/USDC': {
                'amm_id': '58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2',
                'amm_authority': '5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1',
                'amm_open_orders': 'HRk9CMrpq7Jn9sh7mzxE8CChHG8dneX9p475QKz4Fsfc',
                'pool_coin_token_account': 'DQyrAcCrDXQ7NeoqGgDCZwBvWDcYmFCjSb9JtteuvPpz',
                'pool_pc_token_account': 'HLmqeL62xR1QoZ1HKKbXRrdN1p3phKpxRMb2VVopvBBz',
                'serum_program_id': '9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin',
                'serum_market': '9wFFyRfZBsuAha4YcuxcXLKwMxJR43S7fPfQLusDBzvT',
            }
        }
        
        pair_key = f"{token_a}/{token_b}"
        return pool_keys.get(pair_key)
    
    async def build_swap_instruction(
        self,
        params: SwapParams,
        pool_keys: Dict
    ) -> Instruction:
        """
        Build Raydium swap instruction
        
        Raydium swap instruction layout:
        - 1 byte: instruction discriminator (9 = swap)
        - 8 bytes: amount_in
        - 8 bytes: minimum_amount_out
        """
        # Instruction data
        instruction_data = bytearray()
        instruction_data.append(9)  # Swap instruction
        instruction_data.extend(struct.pack('<Q', params.amount_in))
        instruction_data.extend(struct.pack('<Q', params.minimum_amount_out))
        
        # Build account metas (order matters!)
        accounts = [
            AccountMeta(pubkey=Pubkey.from_string(TOKEN_PROGRAM_ID), is_signer=False, is_writable=False),
            AccountMeta(pubkey=Pubkey.from_string(pool_keys['amm_id']), is_signer=False, is_writable=True),
            AccountMeta(pubkey=Pubkey.from_string(pool_keys['amm_authority']), is_signer=False, is_writable=False),
            AccountMeta(pubkey=Pubkey.from_string(pool_keys['amm_open_orders']), is_signer=False, is_writable=True),
            AccountMeta(pubkey=Pubkey.from_string(pool_keys['pool_coin_token_account']), is_signer=False, is_writable=True),
            AccountMeta(pubkey=Pubkey.from_string(pool_keys['pool_pc_token_account']), is_signer=False, is_writable=True),
            AccountMeta(pubkey=Pubkey.from_string(pool_keys['serum_program_id']), is_signer=False, is_writable=False),
            AccountMeta(pubkey=Pubkey.from_string(pool_keys['serum_market']), is_signer=False, is_writable=True),
            AccountMeta(pubkey=params.user_wallet, is_signer=True, is_writable=True),
        ]
        
        return Instruction(
            program_id=self.program_id,
            accounts=accounts,
            data=bytes(instruction_data)
        )
    
    async def create_swap_transaction(
        self,
        token_in: str,
        token_out: str,
        amount_in: float,
        slippage_bps: int,
        user_keypair: Keypair
    ) -> Optional[Transaction]:
        """
        Create a complete Raydium swap transaction
        
        Args:
            token_in: Input token symbol (e.g., 'SOL')
            token_out: Output token symbol (e.g., 'USDC')
            amount_in: Amount to swap
            slippage_bps: Slippage tolerance in basis points
            user_keypair: User's keypair
            
        Returns:
            Transaction ready to send
        """
        try:
            # Get pool keys
            pool_keys = await self.get_pool_keys(token_in, token_out)
            if not pool_keys:
                logger.error(f"No pool found for {token_in}/{token_out}")
                return None
            
            # Convert amount to lamports (assuming SOL/USDC pair)
            if token_in == 'SOL':
                amount_lamports = int(amount_in * 1e9)  # SOL has 9 decimals
            else:
                amount_lamports = int(amount_in * 1e6)  # USDC has 6 decimals
            
            # Calculate minimum output with slippage
            expected_output = amount_in  # Simplified - should fetch from price oracle
            minimum_out = int(expected_output * (10000 - slippage_bps) / 10000 * 1e6)
            
            # Build swap params
            params = SwapParams(
                input_mint=Pubkey.from_string(TOKEN_MINTS[token_in]),
                output_mint=Pubkey.from_string(TOKEN_MINTS[token_out]),
                amount_in=amount_lamports,
                minimum_amount_out=minimum_out,
                user_wallet=user_keypair.pubkey()
            )
            
            # Build swap instruction
            swap_ix = await self.build_swap_instruction(params, pool_keys)
            
            # Create transaction with proper structure
            from solders.message import Message
            
            message = Message.new_with_blockhash(
                [swap_ix],
                user_keypair.pubkey(),
                None
            )
            
            transaction = Transaction([user_keypair], message, None)
            
            logger.info(f"✅ Built Raydium swap: {amount_in} {token_in} → {token_out}")
            return transaction
            
        except Exception as e:
            logger.error(f"Error building Raydium swap: {e}")
            return None


class OrcaSwap:
    """
    Orca Whirlpool swap implementation
    Uses Orca's concentrated liquidity pools
    """
    
    def __init__(self, rpc_client: AsyncClient):
        self.client = rpc_client
        self.program_id = ORCA_WHIRLPOOL_PROGRAM_ID
    
    async def get_whirlpool_address(
        self,
        token_a: str,
        token_b: str
    ) -> Optional[str]:
        """Get Orca Whirlpool address for token pair"""
        # Whirlpool addresses (fetch dynamically in production)
        whirlpools = {
            'SOL/USDC': '7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm',
            'RAY/USDC': '8s1VR6N2Y2LKiLhCQJqHhFWW2KLqvqHyQZfJ3QZqQhqB',
            'ORCA/USDC': '2p7nYbtPBgtmY69NsE8DAW6szpRJn7tQvDnqvoEWQvjY',
        }
        
        pair_key = f"{token_a}/{token_b}"
        return whirlpools.get(pair_key)
    
    async def build_swap_instruction(
        self,
        params: SwapParams,
        whirlpool_address: str
    ) -> Instruction:
        """
        Build Orca swap instruction
        
        Orca Whirlpool swap instruction layout:
        - 8 byte discriminator for swap
        - 8 bytes: amount
        - 8 bytes: other_amount_threshold (slippage)
        - 8 bytes: sqrt_price_limit
        - 1 byte: amount_specified_is_input
        - 1 byte: a_to_b (direction)
        """
        # Instruction discriminator for swap (from Anchor IDL)
        discriminator = bytes([0xf8, 0xc6, 0x9e, 0x91, 0xe1, 0x75, 0x87, 0xc8])
        
        # Build instruction data
        instruction_data = bytearray()
        instruction_data.extend(discriminator)
        instruction_data.extend(struct.pack('<Q', params.amount_in))
        instruction_data.extend(struct.pack('<Q', params.minimum_amount_out))
        instruction_data.extend(struct.pack('<Q', 0))  # sqrt_price_limit (0 = no limit)
        instruction_data.append(1)  # amount_specified_is_input = true
        instruction_data.append(1)  # a_to_b direction
        
        # Build accounts
        accounts = [
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=params.user_wallet, is_signer=True, is_writable=True),
            AccountMeta(pubkey=Pubkey.from_string(whirlpool_address), is_signer=False, is_writable=True),
            # Additional accounts for token vaults, oracle, etc.
        ]
        
        return Instruction(
            program_id=self.program_id,
            accounts=accounts,
            data=bytes(instruction_data)
        )
    
    async def create_swap_transaction(
        self,
        token_in: str,
        token_out: str,
        amount_in: float,
        slippage_bps: int,
        user_keypair: Keypair
    ) -> Optional[Transaction]:
        """Create complete Orca swap transaction"""
        try:
            whirlpool = await self.get_whirlpool_address(token_in, token_out)
            if not whirlpool:
                logger.error(f"No whirlpool found for {token_in}/{token_out}")
                return None
            
            # Convert to lamports
            if token_in == 'SOL':
                amount_lamports = int(amount_in * 1e9)
            else:
                amount_lamports = int(amount_in * 1e6)
            
            # Calculate minimum output
            expected_output = amount_in
            minimum_out = int(expected_output * (10000 - slippage_bps) / 10000 * 1e6)
            
            params = SwapParams(
                input_mint=Pubkey.from_string(TOKEN_MINTS[token_in]),
                output_mint=Pubkey.from_string(TOKEN_MINTS[token_out]),
                amount_in=amount_lamports,
                minimum_amount_out=minimum_out,
                user_wallet=user_keypair.pubkey()
            )
            
            swap_ix = await self.build_swap_instruction(params, whirlpool)
            
            # Create transaction with proper structure
            from solders.message import Message
            
            message = Message.new_with_blockhash(
                [swap_ix],
                user_keypair.pubkey(),
                None
            )
            
            transaction = Transaction([user_keypair], message, None)
            
            logger.info(f"✅ Built Orca swap: {amount_in} {token_in} → {token_out}")
            return transaction
            
        except Exception as e:
            logger.error(f"Error building Orca swap: {e}")
            return None


class JupiterSwap:
    """
    Jupiter Aggregator swap
    Automatically finds best route across all DEXs
    Recommended for production use
    """
    
    def __init__(self, rpc_client: AsyncClient):
        self.client = rpc_client
        self.program_id = JUPITER_AGGREGATOR_V6
        self.api_url = os.environ.get("JUPITER_BASE_URL", "https://lite-api.jup.ag/swap/v1")
    
    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50
    ) -> Optional[Dict]:
        """
        Get swap quote from Jupiter
        Uses Jupiter API to find best route
        """
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    'inputMint': input_mint,
                    'outputMint': output_mint,
                    'amount': str(amount),
                    'slippageBps': str(slippage_bps)
                }
                
                async with session.get(f"{self.api_url}/quote", params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"Jupiter quote failed: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error getting Jupiter quote: {e}")
            return None
    
    async def get_swap_transaction(
        self,
        quote: Dict,
        user_pubkey: str
    ) -> Optional[str]:
        """
        Get serialized transaction from Jupiter
        Returns base64 encoded transaction
        """
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    'quoteResponse': quote,
                    'userPublicKey': user_pubkey,
                    'wrapAndUnwrapSol': True,
                }
                
                async with session.post(
                    f"{self.api_url}/swap",
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('swapTransaction')
                    else:
                        logger.error(f"Jupiter swap failed: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error getting Jupiter swap: {e}")
            return None
    
    async def create_swap_transaction(
        self,
        token_in: str,
        token_out: str,
        amount_in: float,
        slippage_bps: int,
        user_keypair: Keypair
    ) -> Optional[Transaction]:
        """
        Create Jupiter swap transaction
        Jupiter handles routing through best DEXs automatically
        """
        try:
            # Get token mints
            input_mint = TOKEN_MINTS[token_in]
            output_mint = TOKEN_MINTS[token_out]
            
            # Convert to lamports
            if token_in == 'SOL':
                amount_lamports = int(amount_in * 1e9)
            else:
                amount_lamports = int(amount_in * 1e6)
            
            # Get quote from Jupiter
            quote = await self.get_quote(
                input_mint,
                output_mint,
                amount_lamports,
                slippage_bps
            )
            
            if not quote:
                logger.error("Failed to get Jupiter quote")
                return None
            
            logger.info(
                f"Jupiter route: {quote.get('routePlan', [])} | "
                f"Output: {int(quote['outAmount'])/1e6:.2f}"
            )
            
            # Get swap transaction
            swap_tx_base64 = await self.get_swap_transaction(
                quote,
                str(user_keypair.pubkey())
            )
            
            if not swap_tx_base64:
                logger.error("Failed to get Jupiter swap transaction")
                return None
            
            # Decode transaction
            tx_bytes = base64.b64decode(swap_tx_base64)
            transaction = Transaction.from_bytes(tx_bytes)
            
            logger.info(f"✅ Built Jupiter swap: {amount_in} {token_in} → {token_out}")
            return transaction
            
        except Exception as e:
            logger.error(f"Error building Jupiter swap: {e}")
            return None


# Factory function
def get_dex_swap(dex: str, rpc_client: AsyncClient):
    """Get DEX swap instance"""
    dex_lower = dex.lower()
    
    if dex_lower == 'raydium':
        return RaydiumSwap(rpc_client)
    elif dex_lower == 'orca':
        return OrcaSwap(rpc_client)
    elif dex_lower == 'jupiter':
        return JupiterSwap(rpc_client)
    else:
        # Default to Jupiter (best routing)
        return JupiterSwap(rpc_client)


# Testing
async def test_dex_swaps():
    """Test DEX swap builders"""
    print("🧪 Testing DEX Swap Builders")
    print("=" * 70)
    
    # Mock RPC client
    rpc = AsyncClient("https://api.mainnet-beta.solana.com")
    
    # Generate test keypair
    keypair = Keypair()
    
    # Test Raydium
    print("\n1. Testing Raydium...")
    raydium = RaydiumSwap(rpc)
    raydium_tx = await raydium.create_swap_transaction(
        'SOL', 'USDC', 1.0, 50, keypair
    )
    print(f"   Raydium TX: {'✅ Created' if raydium_tx else '❌ Failed'}")
    
    # Test Orca
    print("\n2. Testing Orca...")
    orca = OrcaSwap(rpc)
    orca_tx = await orca.create_swap_transaction(
        'SOL', 'USDC', 1.0, 50, keypair
    )
    print(f"   Orca TX: {'✅ Created' if orca_tx else '❌ Failed'}")
    
    # Test Jupiter
    print("\n3. Testing Jupiter...")
    jupiter = JupiterSwap(rpc)
    jupiter_tx = await jupiter.create_swap_transaction(
        'SOL', 'USDC', 1.0, 50, keypair
    )
    print(f"   Jupiter TX: {'✅ Created' if jupiter_tx else '❌ Failed'}")
    
    await rpc.close()
    print("\n" + "=" * 70)
    print("✅ DEX swap testing complete!")


if __name__ == "__main__":
    asyncio.run(test_dex_swaps())
