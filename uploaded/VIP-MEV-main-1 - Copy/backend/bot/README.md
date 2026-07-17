# Phase 1: WebSocket Detection Engine

## Architecture

```
/bot
├── config.py              # Configuration & pool addresses
├── pool_cache.py          # Global in-memory pool state
├── pricing.py             # Local price calculation (no APIs)
├── arb_detector.py        # Arbitrage detection logic
├── websocket_listener.py  # Real-time WebSocket subscriptions
└── main.py                # Entry point
```

## Key Features

- **NO POLLING** - Pure WebSocket event-driven
- **NO REST APIs** for detection - All prices calculated locally
- **Real-time** - Reacts instantly to on-chain changes
- **Thread-safe** - Concurrent update handling
- **Auto-reconnect** - Exponential backoff on disconnect

## How It Works

1. **Startup**: Fetches initial pool states via HTTP (one-time)
2. **Subscribe**: Opens WebSocket connections to pool accounts
3. **Listen**: Receives account change notifications
4. **Decode**: Extracts reserves from raw account data
5. **Calculate**: Computes prices locally (constant product formula)
6. **Detect**: Compares prices across DEXs
7. **Alert**: Logs opportunities when spread > 8 bps

## Supported DEXs

- Raydium AMM
- Orca Whirlpool
- Meteora DLMM

## Installation

```bash
cd /bot
pip install solana solders websockets python-dotenv
```

## Configuration

Edit `config.py` to add your pool addresses:

```python
POOLS = {
    "raydium_sol_usdc": {
        "address": "POOL_ADDRESS",
        "dex": "raydium",
        "base_mint": "...",
        "quote_mint": "...",
        "base_vault": "...",
        "quote_vault": "...",
    },
    # Add more pools...
}
```

## Environment Variables

Create `.env`:

```
QUICKNODE_WSS_URL=wss://YOUR-QUICKNODE-MAINNET-ENDPOINT
SOLANA_RPC_URL=https://YOUR-RPC-ENDPOINT
```

## Run

```bash
python main.py
```

## Expected Output

```
======================================================================
HFT WEBSOCKET BOT - PHASE 1: DETECTION ENGINE
======================================================================
Mode: Real-time WebSocket detection (NO polling)
Config: Min spread 8bps | Min profit $0.1
======================================================================
Fetching initial pool states...
✓ Initialized raydium_sol_usdc: base=1000000, quote=2000000
✓ Initialized orca_sol_usdc: base=1000000, quote=2000000
Connecting to WebSocket...
WebSocket connected!
✓ Subscribed to raydium_sol_usdc (58oQChx4...)
✓ Subscribed to orca_sol_usdc (HJPjoWUr...)
Listening for 4 subscriptions...
Bot started. Listening for opportunities...

⚡ ARB DETECTED | SOL/USDC | raydium -> orca | Spread: 12.5bps | Profit: $0.45
```

## Success Criteria

Phase 1 is complete when:
- [x] Bot reacts instantly to pool updates
- [x] No polling exists
- [x] Spread prints live
- [x] Detection happens under 300ms

## Next Phase

Phase 2: Add execution logic
- Build swap transactions
- Jito bundle submission
- Flash loan integration
