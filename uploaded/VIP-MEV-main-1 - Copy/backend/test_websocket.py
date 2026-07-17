"""
WebSocket Test Script
Test account subscription to diagnose issues
"""
import asyncio
import os
from dotenv import load_dotenv
from solana.rpc.websocket_api import connect
from solders.pubkey import Pubkey

load_dotenv()

WSS_URL = os.environ.get('QUICKNODE_WSS_URL', 'wss://api.mainnet-beta.solana.com')

# Test vault address (Raydium SOL/USDC pool base vault)
TEST_VAULT = "8BnEgHoWFysVcuFFX7QztDmzuH8r5ZFvyP3sYwn1XTh6"

async def test_subscription():
    print(f"WSS URL: {WSS_URL}")
    print(f"Test vault: {TEST_VAULT}")
    print()
    
    try:
        print("Connecting...")
        async with connect(WSS_URL) as websocket:
            print("✓ Connected!")
            
            print(f"\nSubscribing to {TEST_VAULT}...")
            
            # Try subscription
            result = await websocket.account_subscribe(
                Pubkey.from_string(TEST_VAULT),
                commitment="processed",
                encoding="base64"
            )
            
            print(f"Subscribe result: {result}")
            print(f"Result type: {type(result)}")
            
            if result is not None:
                print(f"✓ Got subscription ID: {result}")
            else:
                print("Result is None, waiting for first message...")
            
            # Wait for messages
            print("\nWaiting for account updates (30 seconds)...")
            msg_count = 0
            subscription_id = None
            
            try:
                async for msg in websocket:
                    msg_count += 1
                    print(f"\n[Message {msg_count}]")
                    print(f"  Type: {type(msg)}")
                    print(f"  Content: {msg}")
                    
                    # If it's a list, check first element
                    if isinstance(msg, list) and len(msg) > 0:
                        first = msg[0]
                        print(f"  First element type: {type(first)}")
                        print(f"  First element: {first}")
                        
                        # Check if this is subscription confirmation
                        if hasattr(first, 'result'):
                            subscription_id = first.result
                            print(f"  ✓ Got subscription ID: {subscription_id}")
                    
                    if hasattr(msg, 'result'):
                        print(f"  Result: {msg.result}")
                    if hasattr(msg, 'value'):
                        print(f"  Has value: True")
                        if hasattr(msg.value, 'lamports'):
                            print(f"  Lamports: {msg.value.lamports}")
                    
                    if msg_count >= 5:
                        print("\nReceived 5 messages, stopping...")
                        break
                        
            except asyncio.TimeoutError:
                print("Timeout waiting for messages")
                
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_subscription())
