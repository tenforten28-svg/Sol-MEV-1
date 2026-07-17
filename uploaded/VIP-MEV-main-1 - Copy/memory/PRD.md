# Solana HFT Arbitrage Bot - Product Requirements Document

## Original Problem Statement
Build a production-grade Solana High-Frequency Trading (HFT) arbitrage bot that:
- Monitors new token launches on Pump.fun, Raydium, and Meteora
- Detects price discrepancies when tokens appear on multiple DEXes
- Executes arbitrage trades using flash loans for capital
- Uses Jito bundles for MEV protection
- **NEW**: AI-powered trade validation via AutoHedge multi-agent system

## Current Status: AutoHedge AI Integration COMPLETE

### What's Working
- **WebSocket Monitoring**: Successfully connects to Solana mainnet and subscribes to DEX program logs
- **Event Detection**: Detects pool creation events from PumpFun, Raydium CLMM, Raydium AMM, Meteora DLMM
- **Transaction Parsing**: Fetches and parses transactions to extract new token mints
- **Token Tracking**: Tracks new tokens and detects when they appear on multiple DEXes
- **Stats Reporting**: Displays periodic stats showing tokens tracked, pool creations, and DEX breakdown
- **AutoHedge AI Bridge**: Multi-agent AI validation for trade opportunities (Director/Quant/Risk agents)

### AutoHedge Integration (NEW - 2026-03-15)
Created `autohedge_bridge.py` providing:
- **Director Agent**: Evaluates market conditions and opportunity quality
- **Quant Agent**: Validates spreads and technical indicators
- **Risk Manager**: Determines optimal position size based on risk profile
- **Fallback Mode**: Heuristic-based validation when AutoHedge unavailable
- Supports three opportunity types: Cross-DEX, LP Unlock, Migration

### Known Limitations
- **Rate Limiting**: Public Solana RPC has strict rate limits (100 req/10s). Bot uses semaphore to limit requests, which may cause some events to be missed
- **Monitor-Only Mode**: Trade execution is implemented but untested (no wallet configured)

## Architecture

```
/app/backend/
├── arb_bot.py              # Main integrated bot (WORKING)
├── autohedge_bridge.py     # AutoHedge AI integration (NEW)
├── arb_executor.py         # Jito bundle trade execution (IMPLEMENTED, UNTESTED)
├── flash_arb.py            # Solend flash loan logic (IMPLEMENTED, UNTESTED)
├── simple_bot.py           # Debug script for CLMM price monitoring
├── AUTOHEDGE_INTEGRATION_GUIDE.md  # Integration documentation (NEW)
├── .env                    # Configuration (mainnet endpoints + AI keys)
└── requirements.txt        # Python dependencies
```

## Configuration (.env)

| Variable | Description | Current Value |
|----------|-------------|---------------|
| SOLANA_RPC_URL | Solana RPC endpoint | https://api.mainnet-beta.solana.com |
| QUICKNODE_WSS_URL | WebSocket endpoint | wss://api.mainnet-beta.solana.com |
| SOLANA_PRIVATE_KEY | Wallet private key (Base58) | Empty (monitor-only) |
| OPENAI_API_KEY | OpenAI key for AutoHedge | (User provides) |
| ANTHROPIC_API_KEY | Alternative: Anthropic key | (User provides) |

## Completed Tasks

### 2026-03-15: AutoHedge AI Integration
- Created `autohedge_bridge.py` - bridges arbitrage detection to AI validation
- Supports Cross-DEX, LP Unlock, and Migration opportunity types
- Director/Quant/Risk multi-agent pipeline for intelligent trade decisions
- Fallback heuristic mode when AutoHedge not installed
- Integration guide with code snippets for local files
- Configurable confidence thresholds and risk limits

### 2026-03-06: P0 Token Extraction Bug Fixed
- Fixed Signature type mismatch (string vs Signature object)
- Added rate limiting with semaphore to avoid 429 errors
- Switched from devnet to mainnet endpoints
- Bot now successfully:
  - Detects 15-25 pool creations per minute from PumpFun
  - Extracts token mints from transactions
  - Tracks tokens across multiple DEXes
  - Reports stats every 60 seconds

## Prioritized Backlog

### P0 - Critical (Blockers)
- [x] Fix token extraction from transaction logs
- [x] AutoHedge AI integration for trade validation
- [ ] Live test with real wallet (small amount)

### P1 - High Priority
- [ ] Integrate AutoHedge into local pumpfun_arbitrage.py
- [ ] Integrate AutoHedge into local lp_unlock_arbitrage.py
- [ ] Verify wallet key loading with real Base58 key
- [ ] Test arbitrage detection when token appears on 2+ DEXes
- [ ] Implement and test trade execution path

### P2 - Medium Priority
- [ ] Use dedicated RPC provider (QuickNode/Helius) for better rate limits
- [ ] Add exponential backoff to WebSocket reconnection
- [ ] Implement persistent logging to database

### P3 - Low Priority / Future
- [ ] Integrate Jupiter routing for optimal swap paths
- [ ] Add profit/loss tracking and reporting
- [ ] Create dashboard UI for monitoring
- [ ] Add Telegram/Discord notifications

## Technical Notes

### Token Extraction
Tokens are extracted from `meta.post_token_balances` in transaction data. Each balance entry has a `mint` attribute containing the token address.

### Rate Limiting Strategy
- Semaphore limits to 1 concurrent RPC call
- 5-second delay between transaction fetches
- Retry with exponential backoff on 429 errors

### Supported Key Formats
1. Base58 string (87 chars for full keypair)
2. JSON array [1, 2, 3, ..., 64 numbers]
3. Comma-separated numbers
4. Hex string

## Next Steps
1. **Copy files to local machine**: `autohedge_bridge.py` and `AUTOHEDGE_INTEGRATION_GUIDE.md`
2. **Install AutoHedge**: `pip install -U autohedge`
3. **Add API key**: Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in local `.env`
4. **Test bridge**: `python autohedge_bridge.py` (runs test suite)
5. **Integrate into existing files**: Follow guide to add imports and validation calls
6. **Run in simulation mode**: Verify AI decisions make sense
7. **Enable live trading**: Set `simulation_mode=False` with small capital
