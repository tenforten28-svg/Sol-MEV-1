# 🚀 Quick Start - Real DEX Price Feed

## Install & Run in 3 Commands

```bash
# 1. Go to the rust directory
cd /app/rust_price_feed

# 2. Run the installer (installs Rust + builds project)
./install.sh

# 3. Start the service
./target/release/solana-price-feed
```

That's it! The service will start fetching **real prices** from Solana DEXs every 3 seconds.

## What You'll See

```
🚀 Starting Solana Real Price Feed Service...
✅ Connected to Solana Devnet
🌐 API listening on http://localhost:8002
   - GET /health - Health check
   - GET /prices - Real-time DEX prices
   - GET /opportunities - Arbitrage opportunities
✅ Updated prices from DEXs
✅ Updated prices from DEXs
...
```

## Test It's Working

Open another terminal and run:

```bash
# Check health
curl http://localhost:8002/health

# Get current prices
curl http://localhost:8002/prices | jq .

# See arbitrage opportunities
curl http://localhost:8002/opportunities | jq .
```

## Example Output

```json
// GET /prices
[
  {
    "dex": "serum",
    "token_pair": "SOL/USDC",
    "price": 152.48,
    "liquidity": 50000.0,
    "timestamp": 1699459200
  },
  {
    "dex": "raydium",
    "token_pair": "SOL/USDC", 
    "price": 152.51,
    "liquidity": 100000.0,
    "timestamp": 1699459200
  },
  {
    "dex": "orca",
    "token_pair": "SOL/USDC",
    "price": 152.43,
    "liquidity": 80000.0,
    "timestamp": 1699459200
  }
]

// GET /opportunities
[
  {
    "token_pair": "SOL/USDC",
    "buy_dex": "orca",
    "sell_dex": "raydium",
    "buy_price": 152.43,
    "sell_price": 152.51,
    "spread_percentage": 0.0525,
    "timestamp": 1699459200
  }
]
```

## Run in Background

```bash
# Start in background
nohup ./target/release/solana-price-feed > price_feed.log 2>&1 &

# Check logs
tail -f price_feed.log

# Stop service
pkill solana-price-feed
```

## Connect to Python Bot

```bash
# Test Python connector
cd /app/backend
python real_dex_connector.py
```

Expected output:
```
Rust service healthy: True

Real DEX Prices:
  SERUM: $152.48
  RAYDIUM: $152.51
  ORCA: $152.43

Found 1 arbitrage opportunities
  orca → raydium: 0.05%
```

## Troubleshooting

### Port 8002 already in use
```bash
# Find and kill the process
sudo lsof -i :8002
kill <PID>
```

### Build errors
```bash
# Install dependencies
sudo apt-get update
sudo apt-get install build-essential pkg-config libssl-dev

# Try again
cargo clean
cargo build --release
```

### Can't fetch prices
```bash
# Check internet connection
curl https://api.jup.ag/price/v2?ids=SOL

# Check service logs
tail -f price_feed.log
```

## What's Next?

1. **Monitor for 1 hour** - See how real spreads behave
2. **Compare** - Real vs simulated opportunity frequency  
3. **Analyze** - Are spreads profitable after fees?
4. **Decide** - Is real trading viable?

## Key Differences: Real vs Simulated

| Metric | Simulated | Real |
|--------|-----------|------|
| Spreads | 0.1% - 40% | 0.05% - 1% |
| Frequency | Every scan | Few per hour |
| Profitability | Often | Rarely |
| Reality | Learning | Production |

## Remember

- ✅ This fetches REAL prices
- ✅ Still 100% paper trading
- ✅ No wallet needed
- ✅ Zero financial risk
- ✅ Production-ready data

---

**You're now running a production-grade price feed that shows you EXACTLY what the market looks like!** 🎯
