"""
WEBSOCKET LISTENER - Real-Time Pool Monitoring
===============================================
Subscribes to Solana account changes via WebSocket
NO polling - pure event-driven architecture
"""

import asyncio
import logging
import struct
import base64
from typing import Dict, Optional, Any, Callable
from dataclasses import dataclass

from solana.rpc.websocket_api import connect
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

from config import (
    WSS_ENDPOINT, 
    RPC_ENDPOINT,
    POOLS, 
    VAULT_SUBSCRIPTIONS,
    TOKEN_DECIMALS,
    RAYDIUM_AMM_PROGRAM,
    ORCA_WHIRLPOOL_PROGRAM,
    METEORA_DLMM_PROGRAM
)
from pool_cache import update_pool, update_vault_reserve, register_vault, get_pool_stats
from arb_detector import check_arbitrage, check_single_pool_update

logger = logging.getLogger('ws_listener')

# =============================================================================
# ACCOUNT DATA DECODERS
# =============================================================================

def decode_token_account(data: bytes) -> Optional[int]:
    """
    Decode SPL Token account to get balance
    Token account layout: mint (32) + owner (32) + amount (8) + ...
    """
    if len(data) < 72:
        return None
    
    # Amount is at offset 64, 8 bytes, little-endian
    amount = struct.unpack('<Q', data[64:72])[0]
    return amount


def decode_raydium_amm_pool(data: bytes) -> Optional[Dict]:
    """
    Decode Raydium AMM pool account data
    Extract base and quote reserves
    """
    if len(data) < 752:  # Minimum Raydium AMM account size
        return None
    
    try:
        # Raydium AMM layout offsets (approximate - may need adjustment)
        # These offsets are for the standard AMM pool
        base_vault_offset = 336
        quote_vault_offset = 368
        
        # For now, we rely on vault subscriptions for reserves
        # Pool account gives us validation that pool exists
        return {"valid": True}
    except Exception as e:
        logger.debug(f"Raydium decode error: {e}")
        return None


def decode_orca_whirlpool(data: bytes) -> Optional[Dict]:
    """
    Decode Orca Whirlpool account data
    """
    if len(data) < 653:  # Whirlpool account size
        return None
    
    try:
        # Whirlpool layout
        # sqrt_price is at offset 65, 16 bytes (u128)
        sqrt_price_bytes = data[65:81]
        sqrt_price = int.from_bytes(sqrt_price_bytes, 'little')
        
        # Liquidity at offset 81, 16 bytes (u128)
        liquidity = int.from_bytes(data[81:97], 'little')
        
        # Current tick at offset 97, 4 bytes (i32)
        tick = struct.unpack('<i', data[97:101])[0]
        
        return {
            "sqrt_price": sqrt_price,
            "liquidity": liquidity,
            "tick": tick,
        }
    except Exception as e:
        logger.debug(f"Orca decode error: {e}")
        return None


def decode_meteora_dlmm(data: bytes) -> Optional[Dict]:
    """
    Decode Meteora DLMM pair account data
    """
    if len(data) < 904:  # LbPair account size
        return None
    
    try:
        # DLMM layout offsets
        # active_id at offset 112, 4 bytes (i32)
        active_id = struct.unpack('<i', data[112:116])[0]
        
        # bin_step at offset 116, 2 bytes (u16)
        bin_step = struct.unpack('<H', data[116:118])[0]
        
        return {
            "active_bin_id": active_id,
            "bin_step": bin_step,
        }
    except Exception as e:
        logger.debug(f"Meteora decode error: {e}")
        return None


# =============================================================================
# WEBSOCKET LISTENER
# =============================================================================

class WebSocketListener:
    """
    Real-time WebSocket listener for Solana account changes
    """
    
    def __init__(self):
        self.ws = None
        self.subscriptions: Dict[int, str] = {}  # subscription_id -> pool_name or vault_name
        self.running = False
        self.reconnect_delay = 1
        self.max_reconnect_delay = 30
        
        # Stats
        self.messages_received = 0
        self.updates_processed = 0
        self.last_update_time = 0
    
    async def subscribe_to_account(self, address: str, name: str):
        """Subscribe to account changes"""
        try:
            pubkey = Pubkey.from_string(address)
            subscription_id = await self.ws.account_subscribe(
                pubkey,
                commitment="confirmed",
                encoding="base64"
            )
            
            # Extract subscription ID from response
            if hasattr(subscription_id, 'result'):
                sub_id = subscription_id.result
                self.subscriptions[sub_id] = name
                logger.info(f"✓ Subscribed to {name} ({address[:8]}...)")
            else:
                logger.warning(f"Failed to subscribe to {name}")
                
        except Exception as e:
            logger.error(f"Subscribe error for {name}: {e}")
    
    async def initialize_pool_state(self):
        """Fetch initial pool states via HTTP before starting WebSocket"""
        logger.info("Fetching initial pool states...")
        
        async with AsyncClient(RPC_ENDPOINT) as client:
            # Fetch vault balances for each pool
            for pool_name, pool_config in POOLS.items():
                try:
                    dex = pool_config.get("dex", "unknown")
                    base_mint = pool_config.get("base_mint")
                    quote_mint = pool_config.get("quote_mint")
                    
                    # Get vault addresses based on DEX type
                    if dex == "raydium":
                        base_vault = pool_config.get("base_vault")
                        quote_vault = pool_config.get("quote_vault")
                    elif dex == "orca":
                        base_vault = pool_config.get("token_vault_a")
                        quote_vault = pool_config.get("token_vault_b")
                    elif dex == "meteora":
                        base_vault = pool_config.get("reserve_x")
                        quote_vault = pool_config.get("reserve_y")
                    else:
                        continue
                    
                    if not base_vault or not quote_vault:
                        continue
                    
                    # Fetch vault balances
                    base_resp = await client.get_token_account_balance(Pubkey.from_string(base_vault))
                    quote_resp = await client.get_token_account_balance(Pubkey.from_string(quote_vault))
                    
                    if base_resp.value and quote_resp.value:
                        base_reserve = int(base_resp.value.amount)
                        quote_reserve = int(quote_resp.value.amount)
                        base_decimals = base_resp.value.decimals
                        quote_decimals = quote_resp.value.decimals
                        
                        # Update pool cache
                        update_pool(pool_name, {
                            "dex": dex,
                            "base_reserve": base_reserve,
                            "quote_reserve": quote_reserve,
                            "base_decimals": base_decimals,
                            "quote_decimals": quote_decimals,
                            "slot": 0
                        })
                        
                        # Register vaults for WebSocket updates
                        register_vault(base_vault, pool_name, "base")
                        register_vault(quote_vault, pool_name, "quote")
                        
                        logger.info(f"✓ Initialized {pool_name}: base={base_reserve}, quote={quote_reserve}")
                        
                except Exception as e:
                    logger.warning(f"Failed to initialize {pool_name}: {e}")
    
    async def process_message(self, msg):
        """Process incoming WebSocket message"""
        self.messages_received += 1
        
        try:
            # Extract notification data
            if hasattr(msg, 'result'):
                # This is a subscription confirmation
                return
            
            if not hasattr(msg, 'params'):
                return
            
            params = msg.params
            subscription_id = params.get('subscription')
            result = params.get('result')
            
            if not result or not subscription_id:
                return
            
            # Get pool/vault name from subscription
            name = self.subscriptions.get(subscription_id)
            if not name:
                return
            
            # Extract account data
            value = result.get('value', {})
            slot = result.get('context', {}).get('slot', 0)
            
            account_data = value.get('data')
            if not account_data:
                return
            
            # Decode base64 data
            if isinstance(account_data, list) and len(account_data) >= 1:
                data = base64.b64decode(account_data[0])
            else:
                return
            
            # Process based on subscription type
            if name.endswith("_base") or name.endswith("_quote"):
                # This is a vault update
                amount = decode_token_account(data)
                if amount is not None:
                    pool_name = update_vault_reserve(name.rsplit('_', 1)[0], amount, slot)
                    if pool_name:
                        self.updates_processed += 1
                        self.last_update_time = asyncio.get_event_loop().time()
                        # Trigger arbitrage check
                        check_single_pool_update(pool_name)
            else:
                # This is a pool account update
                # Decode based on DEX type
                pool_config = POOLS.get(name, {})
                dex = pool_config.get("dex")
                
                decoded = None
                if dex == "raydium":
                    decoded = decode_raydium_amm_pool(data)
                elif dex == "orca":
                    decoded = decode_orca_whirlpool(data)
                elif dex == "meteora":
                    decoded = decode_meteora_dlmm(data)
                
                if decoded:
                    decoded["slot"] = slot
                    decoded["dex"] = dex
                    update_pool(name, decoded)
                    self.updates_processed += 1
                    check_single_pool_update(name)
                    
        except Exception as e:
            logger.debug(f"Message processing error: {e}")
    
    async def listen(self):
        """Main WebSocket listening loop"""
        self.running = True
        
        # Initialize pool states first
        await self.initialize_pool_state()
        
        while self.running:
            try:
                logger.info(f"Connecting to WebSocket: {WSS_ENDPOINT[:50]}...")
                
                async with connect(WSS_ENDPOINT) as websocket:
                    self.ws = websocket
                    self.reconnect_delay = 1  # Reset delay on successful connect
                    
                    logger.info("WebSocket connected!")
                    
                    # Subscribe to all pool accounts
                    for pool_name, pool_config in POOLS.items():
                        address = pool_config.get("address")
                        if address:
                            await self.subscribe_to_account(address, pool_name)
                    
                    # Subscribe to vault accounts for reserve tracking
                    for vault_name, vault_address in VAULT_SUBSCRIPTIONS.items():
                        await self.subscribe_to_account(vault_address, vault_name)
                    
                    logger.info(f"Listening for {len(self.subscriptions)} subscriptions...")
                    
                    # Process incoming messages
                    async for msg in websocket:
                        await self.process_message(msg)
                        
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                
                # Exponential backoff
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
    
    async def stop(self):
        """Stop the listener"""
        self.running = False
        if self.ws:
            await self.ws.close()
    
    def get_stats(self) -> Dict:
        """Get listener statistics"""
        return {
            "messages_received": self.messages_received,
            "updates_processed": self.updates_processed,
            "subscriptions": len(self.subscriptions),
            "running": self.running,
        }


# Global listener instance
listener = WebSocketListener()


async def start_listener():
    """Start the WebSocket listener"""
    await listener.listen()


async def stop_listener():
    """Stop the WebSocket listener"""
    await listener.stop()


def get_listener_stats() -> Dict:
    """Get listener statistics"""
    return listener.get_stats()
