# PRD — Solana MEV Arbitrage Bot (VIP-MEV)

## Original Problem Statement
User uploaded a Solana MEV/arbitrage bot zip, chose to deploy on Railway (~$5/mo), and wants to go LIVE with a Phantom wallet (~$12) using QuickNode + Jupiter + Jito + direct Pump.fun sniping.

## Architecture (current)
- **Backend:** FastAPI on Railway (Docker). Runs simulated arbitrage monitor + live trading + auto-arb monitor + Pump.fun sniper (detection + auto-buy).
- **DB:** MongoDB Atlas M0.
- **Frontend:** React on Vercel.
- **Live execution paths:**
  - `live_trader.py` — Jupiter v6 quote+swap → solders sign → QuickNode RPC (+ optional Jito bundle).
  - `live_arb_monitor.py` — autonomous round-trip quote scanner (gated by `AUTO_ARB_ENABLED`).
  - `pumpfun_sniper.py` — QuickNode WSS → detects new pump.fun mints.
  - `pumpfun_autobuy.py` — direct bonding-curve buy via **PumpPortal Local API** (builds unsigned tx) → solders sign locally → QuickNode `sendTransaction`. PumpPortal never has custody.

## What's implemented
- ✅ Railway/Vercel deployment, MongoDB Atlas, health endpoint.
- ✅ Full live-trading module with Jito bundles and 6-layer safety guards (double kill switch, max trade $2, min reserve, daily loss cap, losing streak, cooldown, whitelist).
- ✅ Autonomous arbitrage monitor + decision log.
- ✅ Pump.fun new-listing detector via QuickNode WSS.
- ✅ **[2026-02] Pump.fun anti-rug filter suite** (6 layers, all fail-closed):
  1. Mint authority revoked (required)
  2. Freeze authority revoked (required)
  3. Dev holds ≤ `PUMPFUN_MAX_DEV_HOLD_PCT` (default 15%) — verified via `getTransaction` post-token-balances with 3-retry
  4. Largest non-pool holder ≤ `PUMPFUN_MAX_HOLDER_PCT` (default 20%) — via `getTokenLargestAccounts` excluding derived bonding-curve ATA
  5. Top-10 non-pool holders ≤ `PUMPFUN_MAX_TOP10_PCT` (default 30%)
  6. Bonding curve state: `real_sol_reserves ≥ PUMPFUN_MIN_CURVE_SOL` (default 0.01) AND not graduated — direct PDA account read + Anchor struct decode
  7. Token-2022 honeypot extensions rejected: transferFeeConfig, permanentDelegate, nonTransferable, transferHook, mintCloseAuthority, defaultAccountState=Frozen
- ✅ **[2026-02] Pump.fun direct bonding-curve auto-buy** — PumpPortal Local API + local signing. Master gate `PUMPFUN_AUTO_BUY_ENABLED=false` by default. Time-limit auto-exit.
- ✅ **[2026-02] Pump.fun frontend panel** — detector + auto-buy status, 6 stat tiles, 9-item config strip, detection list with links, position event rows showing dev%/top1%/top10%/curve SOL inline color-coded.
- ✅ **79/79 anti-rug + fail-closed regression tests passing** (iteration_15).

## Known limitations (honest)
- ⚠️ TP/SL config values (`PUMPFUN_TAKE_PROFIT`, `PUMPFUN_STOP_LOSS`) are **advisory** — only `hold_max_seconds` is enforced. Price-based exits require bonding-curve on-chain decoding which is deliberately deferred. Status endpoint reports `tp_sl_enforced: false`.
- ⚠️ Live-trade POST endpoints (`/api/live/test_swap`, etc.) are unauthenticated. User chose "fast path" — auth layer is a P1 backlog item.
- ⚠️ Auto-arb decisions on meme pairs get Jupiter 429s; pacing/backoff improvements pending.
- ⚠️ PumpPortal is third-party; used only to build the unsigned instruction.

## Prioritized Backlog

### P0
1. Add auth layer (shared-secret header) on all mutating `/api/live/*` endpoints before any live gate is armed.
2. Implement TP/SL price-based exit via pump program bonding-curve PDA decode (or mark permanently as time-only).

### P1
1. Cancel `monitor_positions()` task + close aiohttp session on FastAPI lifespan shutdown.
2. Jupiter 429 pacing/backoff + configurable scan concurrency for meme pairs.
3. Split `server.py` (1281 lines) into routers (`live`, `pumpfun`, `arb`, `simulation`).
4. Return proper 5xx on the 4 pumpfun endpoints instead of 200 + `{error}`.
5. On-chain PnL reconciliation from confirmed tx balances rather than estimates.

### P2
1. Kill-switch UI (post-auth).
2. Populate `Position.token_amount` from post-buy `getTokenAccountsByOwner` and enable accurate PnL.
3. `accountSubscribe` for real-time bonding-curve price watching.

## Next Tasks
1. User to arm on Railway: set `PUMPFUN_SNIPER_ENABLED=true`, verify detections flow, then `PUMPFUN_AUTO_BUY_ENABLED=true` with a small budget.
2. Observe first snipes via dashboard; iterate on filters.
