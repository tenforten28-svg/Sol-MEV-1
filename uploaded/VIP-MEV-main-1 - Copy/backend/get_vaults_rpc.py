"""
DIRECT RPC Pool Data Fetcher
============================
Fetches vault addresses directly from on-chain pool state via RPC.
This is a ONE-TIME lookup to get correct addresses for the bot config.
No slow APIs - direct blockchain query.
"""

import asyncio
import os
import json
from dotenv import load_dotenv
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

load_dotenv()

RPC_URL = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Known Raydium AMM Program
RAYDIUM_AMM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

# The pool we want
RAYDIUM_SOL_USDC_POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"


async def get_pool_accounts():
    """
    Query the pool's associated accounts using getProgramAccounts
    or by parsing the AMM state directly.
    """
    print(f"RPC: {RPC_URL[:50]}...")
    client = AsyncClient(RPC_URL)
    
    try:
        # Method 1: Get the pool account and find related token accounts
        pool_pubkey = Pubkey.from_string(RAYDIUM_SOL_USDC_POOL)
        
        # Get all token accounts owned by the pool authority
        # Raydium pools have a PDA authority that owns the vault accounts
        
        # First, let's find accounts associated with this pool
        # by getting token accounts that reference the pool
        
        print("\n" + "="*60)
        print("FINDING RAYDIUM POOL TOKEN VAULTS")
        print("="*60)
        
        # The Raydium AMM pool state contains vault addresses at specific offsets
        # Let's fetch the raw data and print byte ranges to analyze
        
        resp = await client.get_account_info(pool_pubkey)
        
        if resp.value:
            import base64 as b64
            raw_data = resp.value.data
            
            # Handle different data formats
            if isinstance(raw_data, bytes):
                data = raw_data
            elif isinstance(raw_data, (list, tuple)):
                if isinstance(raw_data[0], int):
                    data = bytes(raw_data)
                elif isinstance(raw_data[0], str):
                    data = b64.b64decode(raw_data[0])
                else:
                    data = bytes(raw_data)
            elif isinstance(raw_data, str):
                data = b64.b64decode(raw_data)
            else:
                data = bytes(raw_data)
            print(f"\nPool account data: {len(data)} bytes")
            
            # Raydium AMM V4 AccountLayout (from SDK source):
            # Offset 0: status (u64)
            # Offset 8: nonce (u64)
            # Offset 16: orderNum (u64)
            # Offset 24: depth (u64)
            # Offset 32: coinDecimals (u64)
            # Offset 40: pcDecimals (u64)
            # Offset 48: state (u64)
            # Offset 56: resetFlag (u64)
            # Offset 64: minSize (u64)
            # Offset 72: volMaxCutRatio (u64)
            # Offset 80: amountWaveRatio (u64)
            # Offset 88: coinLotSize (u64)
            # Offset 96: pcLotSize (u64)
            # Offset 104: minPriceMultiplier (u64)
            # Offset 112: maxPriceMultiplier (u64)
            # Offset 120: systemDecimalsValue (u64)
            # Offset 128: minSeparateNumerator (u64)
            # Offset 136: minSeparateDenominator (u64)
            # Offset 144: tradeFeeNumerator (u64)
            # Offset 152: tradeFeeDenominator (u64)
            # Offset 160: pnlNumerator (u64)
            # Offset 168: pnlDenominator (u64)
            # Offset 176: swapFeeNumerator (u64)
            # Offset 184: swapFeeDenominator (u64)
            # Offset 192: needTakePnlCoin (u64)
            # Offset 200: needTakePnlPc (u64)
            # Offset 208: totalPnlPc (u64)
            # Offset 216: totalPnlCoin (u64)
            # Offset 224: poolOpenTime (u64)
            # Offset 232: punishPcAmount (u64)
            # Offset 240: punishCoinAmount (u64)
            # Offset 248: orderbookToInitTime (u64)
            # Offset 256: swapCoinInAmount (u128)
            # Offset 272: swapPcOutAmount (u128)
            # Offset 288: swapCoin2PcFee (u64)
            # Offset 296: swapPcInAmount (u128)
            # Offset 312: swapCoinOutAmount (u128)
            # Offset 328: swapPc2CoinFee (u64)
            # Offset 336: poolCoinTokenAccount (Pubkey) <-- BASE VAULT
            # Offset 368: poolPcTokenAccount (Pubkey)   <-- QUOTE VAULT
            # Offset 400: coinMintAddress (Pubkey)
            # Offset 432: pcMintAddress (Pubkey)
            # Offset 464: lpMintAddress (Pubkey)
            # Offset 496: ammOpenOrders (Pubkey)
            # Offset 528: serumMarket (Pubkey)
            # Offset 560: serumProgramId (Pubkey)
            # Offset 592: ammTargetOrders (Pubkey)
            # Offset 624: poolWithdrawQueue (Pubkey)
            # Offset 656: poolTempLpTokenAccount (Pubkey)
            # Offset 688: ammOwner (Pubkey)
            # Offset 720: pnlOwner (Pubkey)
            
            if len(data) >= 464:
                # Extract key pubkeys
                pool_coin_vault = Pubkey.from_bytes(data[336:368])  # BASE (SOL)
                pool_pc_vault = Pubkey.from_bytes(data[368:400])    # QUOTE (USDC)
                coin_mint = Pubkey.from_bytes(data[400:432])
                pc_mint = Pubkey.from_bytes(data[432:464])
                lp_mint = Pubkey.from_bytes(data[464:496])
                
                print(f"\n✅ FOUND VAULT ADDRESSES:")
                print(f"   Base Vault (SOL):  {pool_coin_vault}")
                print(f"   Quote Vault (USDC): {pool_pc_vault}")
                print(f"   Coin Mint:  {coin_mint}")
                print(f"   PC Mint:    {pc_mint}")
                print(f"   LP Mint:    {lp_mint}")
                
                # Verify mints
                expected_sol = "So11111111111111111111111111111111111111112"
                expected_usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                
                print(f"\n   Coin Mint is SOL: {str(coin_mint) == expected_sol}")
                print(f"   PC Mint is USDC: {str(pc_mint) == expected_usdc}")
                
                # Now fetch the actual balances from these vaults
                print("\n" + "-"*60)
                print("FETCHING CURRENT VAULT BALANCES")
                print("-"*60)
                
                # Fetch SOL vault balance
                sol_resp = await client.get_account_info(pool_coin_vault)
                if sol_resp.value:
                    sol_raw = sol_resp.value.data
                    if isinstance(sol_raw, bytes):
                        sol_data = sol_raw
                    elif isinstance(sol_raw, (list, tuple)):
                        sol_data = bytes(sol_raw) if isinstance(sol_raw[0], int) else b64.b64decode(sol_raw[0])
                    else:
                        sol_data = bytes(sol_raw)
                    
                    if len(sol_data) >= 72:
                        import struct
                        sol_amount = struct.unpack_from("<Q", sol_data, 64)[0]
                        print(f"   SOL Vault Balance: {sol_amount / 1e9:.4f} SOL")
                
                # Fetch USDC vault balance  
                usdc_resp = await client.get_account_info(pool_pc_vault)
                if usdc_resp.value:
                    usdc_raw = usdc_resp.value.data
                    if isinstance(usdc_raw, bytes):
                        usdc_data = usdc_raw
                    elif isinstance(usdc_raw, (list, tuple)):
                        usdc_data = bytes(usdc_raw) if isinstance(usdc_raw[0], int) else b64.b64decode(usdc_raw[0])
                    else:
                        usdc_data = bytes(usdc_raw)
                    
                    if len(usdc_data) >= 72:
                        import struct
                        usdc_amount = struct.unpack_from("<Q", usdc_data, 64)[0]
                        print(f"   USDC Vault Balance: {usdc_amount / 1e6:.2f} USDC")
                        
                        if sol_amount > 0:
                            price = (usdc_amount / 1e6) / (sol_amount / 1e9)
                            print(f"\n   💰 CALCULATED PRICE: ${price:.4f} per SOL")
                
                # Output the config
                print("\n" + "="*60)
                print("COPY THIS CONFIG TO YOUR BOT:")
                print("="*60)
                print(f"""
'raydium_sol_usdc': {{
    'address': '{RAYDIUM_SOL_USDC_POOL}',
    'base_vault': '{pool_coin_vault}',
    'quote_vault': '{pool_pc_vault}',
    'base_mint': '{coin_mint}',
    'quote_mint': '{pc_mint}',
    'base_decimals': 9,
    'quote_decimals': 6,
    'dex': 'raydium',
    'fee_bps': 25,
    'pair': 'SOL/USDC'
}},
""")
                
                return {
                    'base_vault': str(pool_coin_vault),
                    'quote_vault': str(pool_pc_vault),
                }
        else:
            print("❌ Could not fetch pool data")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()
    
    return None


async def main():
    print("="*60)
    print("DIRECT RPC VAULT ADDRESS FETCHER")
    print("="*60)
    print("This fetches vault addresses directly from chain.")
    print("Run once to get correct addresses for your bot config.")
    
    await get_pool_accounts()


if __name__ == "__main__":
    asyncio.run(main())
