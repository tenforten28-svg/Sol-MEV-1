# MEV Backtesting & Data Pipeline System

Complete system for historical backtesting, data ingestion, execution optimization, and ML signal generation for Solana MEV operations.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Historical Data Layer                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────┐│
│  │   Serum    │  │  Raydium   │  │    Orca    │  │Jupiter ││
│  │  Orderbook │  │ Pool State │  │ Whirlpool  │  │ Quotes ││
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └────┬───┘│
└────────┼────────────────┼────────────────┼──────────────┼────┘
         │                │                │              │
         └────────────────┴────────────────┴──────────────┘
                                 │
         ┌───────────────────────▼───────────────────────┐
         │           Data Ingestion Pipeline             │
         │  • JSON Lines format                          │
         │  • RocksDB storage                            │
         │  • S3 archival                                │
         └───────────────────┬───────────────────────────┘
                             │
         ┌───────────────────▼───────────────────────────┐
         │          Event-Driven Backtest Engine         │
         │  • Tick-by-tick replay                        │
         │  • Slot-by-slot mode                          │
         │  • AMM curve simulation                       │
         │  • Slippage modeling                          │
         │  • Tip strategy testing                       │
         └───────────────────┬───────────────────────────┘
                             │
         ┌──────────────────┼──────────────────────────┐
         │                  │                          │
         ▼                  ▼                          ▼
┌─────────────────┐ ┌───────────────┐ ┌────────────────────┐
│   Execution     │ │  Performance  │ │   ML Feature       │
│   Optimizer     │ │   Reporter    │ │   Generator        │
│                 │ │               │ │                    │
│ • Route select  │ │ • Win rate    │ │ • Spread signals   │
│ • Risk scoring  │ │ • Sharpe      │ │ • Liquidity depth  │
│ • Tip adjust    │ │ • Drawdown    │ │ • Imbalance score  │
└─────────────────┘ └───────────────┘ └────────────────────┘
```

## Quick Start

### Run Backtest
```bash
POST /run_backtest
{
  "pair": "SOL/USDC",
  "start_slot": 250000000,
  "end_slot": 250100000,
  "initial_balance": 50,
  "max_slippage_bps": 20,
  "min_roi_bps": 5,
  "tip_strategy": "adaptive"
}
```

### Ingest Historical Data
```bash
cargo run --bin ingest_serum -- --pair SOL/USDC --start-slot 250000000
```

### Generate ML Dataset
```bash
cargo run --bin generate_features -- --input data/snapshots.jsonl --output ml/features.jsonl
```

## Module Overview

### 1. Backtesting Engine (`backtest/`)
- **engine.rs**: Main event-driven backtest loop
- **state.rs**: Backtest state management
- **event.rs**: Market event types
- **simulator.rs**: AMM curve simulation

### 2. Data Ingestion (`data/`)
- **sources/serum.rs**: Serum orderbook reader
- **sources/raydium.rs**: Raydium pool state fetcher
- **sources/orca.rs**: Orca Whirlpool reader  
- **sources/jupiter.rs**: Jupiter quote history
- **storage.rs**: RocksDB/S3 backend

### 3. Execution Optimizer (`execution/`)
- **optimizer.rs**: Route selection & tip adjustment
- **risk.rs**: Risk scoring
- **slippage.rs**: Slippage calculation

### 4. ML Framework (`ml/`)
- **features.rs**: Feature extraction
- **labels.rs**: Label generation
- **interface.rs**: Model integration trait

## Data Flow

```
Historical Data → Ingestion → Storage → Backtest → Analysis
                                    ↓
                                ML Features → Training
```

## File Locations

- **Schemas**: `/app/mev_backtest_system/schemas/`
- **Rust Code**: `/app/mev_backtest_system/rust_stubs/src/`
- **Docs**: `/app/mev_backtest_system/docs/`
- **Examples**: `/app/mev_backtest_system/examples/`

See `docs/PSEUDOCODE.md` for detailed algorithm logic.
