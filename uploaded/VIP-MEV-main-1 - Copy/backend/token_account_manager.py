"""
Token Account Manager
Handles Associated Token Account (ATA) creation and management
"""

import asyncio
import logging
from typing import Optional, List
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.system_program import ID as SYS_PROGRAM_ID
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
import struct

logger = logging.getLogger(__name__)

# Program IDs
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
RENT_PROGRAM_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")


class TokenAccountManager:
    """
    Manages token accounts and Associated Token Accounts (ATAs)
    """
    
    def __init__(self, rpc_client: AsyncClient):
        self.client = rpc_client
    
    def get_associated_token_address(
        self,
        wallet: Pubkey,
        mint: Pubkey
    ) -> Pubkey:
        """
        Derive Associated Token Account address
        
        ATA = findProgramAddress([wallet, TOKEN_PROGRAM_ID, mint], ASSOCIATED_TOKEN_PROGRAM_ID)
        """
        seeds = [
            bytes(wallet),
            bytes(TOKEN_PROGRAM_ID),
            bytes(mint)
        ]
        
        # Find program address
        ata, _ = Pubkey.find_program_address(seeds, ASSOCIATED_TOKEN_PROGRAM_ID)
        return ata
    
    async def get_token_account_balance(
        self,
        token_account: Pubkey
    ) -> Optional[int]:
        """Get token account balance"""
        try:
            response = await self.client.get_token_account_balance(token_account)
            if response.value:
                return int(response.value.amount)
            return None
        except Exception as e:
            logger.debug(f"Account doesn't exist or error: {e}")
            return None
    
    async def account_exists(self, account: Pubkey) -> bool:
        """Check if account exists"""
        try:
            response = await self.client.get_account_info(account)
            return response.value is not None
        except Exception:
            return False
    
    def create_associated_token_account_instruction(
        self,
        payer: Pubkey,
        wallet: Pubkey,
        mint: Pubkey
    ) -> Instruction:
        """
        Create instruction to create Associated Token Account
        
        If ATA doesn't exist, this instruction creates it
        If it exists, this is a no-op
        """
        # Get ATA address
        ata = self.get_associated_token_address(wallet, mint)
        
        # Build instruction
        # No data needed - instruction discriminator is implicit
        accounts = [
            AccountMeta(pubkey=payer, is_signer=True, is_writable=True),  # Payer
            AccountMeta(pubkey=ata, is_signer=False, is_writable=True),  # ATA to create
            AccountMeta(pubkey=wallet, is_signer=False, is_writable=False),  # Wallet
            AccountMeta(pubkey=mint, is_signer=False, is_writable=False),  # Mint
            AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),  # System program
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),  # Token program
        ]
        
        return Instruction(
            program_id=ASSOCIATED_TOKEN_PROGRAM_ID,
            accounts=accounts,
            data=bytes()  # No data for create ATA
        )
    
    async def ensure_token_accounts_exist(
        self,
        wallet: Pubkey,
        mints: List[Pubkey],
        payer: Pubkey
    ) -> List[Instruction]:
        """
        Ensure all token accounts exist
        Returns list of create instructions for missing accounts
        
        Args:
            wallet: Wallet that owns the accounts
            mints: List of token mints
            payer: Who pays for account creation
            
        Returns:
            List of create instructions (empty if all exist)
        """
        create_instructions = []
        
        for mint in mints:
            # Get ATA address
            ata = self.get_associated_token_address(wallet, mint)
            
            # Check if exists
            exists = await self.account_exists(ata)
            
            if not exists:
                logger.info(f"Creating ATA for mint {mint}")
                create_ix = self.create_associated_token_account_instruction(
                    payer,
                    wallet,
                    mint
                )
                create_instructions.append(create_ix)
            else:
                logger.debug(f"ATA exists for mint {mint}")
        
        return create_instructions
    
    async def get_or_create_token_accounts(
        self,
        wallet: Pubkey,
        mints: List[Pubkey],
        payer: Pubkey
    ) -> dict:
        """
        Get token account addresses and creation instructions if needed
        
        Returns:
            {
                'accounts': {mint: ata_address},
                'create_instructions': [instructions]
            }
        """
        accounts = {}
        create_instructions = []
        
        for mint in mints:
            ata = self.get_associated_token_address(wallet, mint)
            accounts[str(mint)] = ata
            
            # Check if needs creation
            exists = await self.account_exists(ata)
            if not exists:
                create_ix = self.create_associated_token_account_instruction(
                    payer,
                    wallet,
                    mint
                )
                create_instructions.append(create_ix)
        
        return {
            'accounts': accounts,
            'create_instructions': create_instructions
        }


# Testing
async def test_token_account_manager():
    """Test token account manager"""
    print("🧪 Testing Token Account Manager")
    print("=" * 70)
    
    # Mock RPC
    rpc = AsyncClient("https://api.mainnet-beta.solana.com")
    manager = TokenAccountManager(rpc)
    
    # Test wallet
    wallet = Keypair().pubkey()
    
    # USDC mint
    usdc_mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    
    print(f"\n1. Deriving ATA address...")
    print(f"   Wallet: {wallet}")
    print(f"   Mint: {usdc_mint}")
    
    ata = manager.get_associated_token_address(wallet, usdc_mint)
    print(f"   ATA: {ata}")
    
    print(f"\n2. Creating ATA instruction...")
    create_ix = manager.create_associated_token_account_instruction(
        wallet,  # payer
        wallet,  # owner
        usdc_mint
    )
    print(f"   ✅ Instruction created")
    print(f"   Program: {create_ix.program_id}")
    print(f"   Accounts: {len(create_ix.accounts)}")
    
    print(f"\n3. Testing multi-token setup...")
    mints = [
        Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),  # USDC
        Pubkey.from_string("So11111111111111111111111111111111111111112"),  # SOL
    ]
    
    result = await manager.get_or_create_token_accounts(wallet, mints, wallet)
    print(f"   Token accounts: {len(result['accounts'])}")
    print(f"   Create instructions needed: {len(result['create_instructions'])}")
    
    await rpc.close()
    print("\n" + "=" * 70)
    print("✅ Token account manager test complete!")


if __name__ == "__main__":
    asyncio.run(test_token_account_manager())
