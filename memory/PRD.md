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
- ✅ **[2026-02] Production bug fixes (iteration_19)** — both surfaced by user's live Railway deployment:
  - **BUG 1**: Pump.fun sniper detected 64 mints, made 0 buy attempts (safety_rejects=0). Mint extraction was scanning `Program log: mint: X` lines that pump.fun does not emit. FIXED by `getTransaction` with 3-retry, scanning accountKeys for pump-suffix (vanity `...pump`). Removed unsafe `accountKeys[1]` fallback (would mis-dispatch creator/PDA/fee accounts as mint). New status counters `mints_resolved / mints_unresolved / buys_dispatched` make this silent-failure pattern visible next time.
  - **BUG 2**: Graduation sniper had 2335 sell_failed events on one illiquid mint (`9SP2..pump`, ratio 0.0212x). Position never removed after failed sells → infinite retry loop every 5s. FIXED with `GRADUATION_MAX_SELL_FAILURES=5` + `GRADUATION_SELL_RETRY_BACKOFF_SEC=30`: after N consecutive failures the position is ABANDONED (removed from positions dict + realized-loss trade row written to `db.trades` so cumulative PnL stays correct). Backoff prevents hot-loop retries. `sell_failures` resets on HOLD (not just successful sell) so rug-stop isn't gated by stale retry state.
  - **520/520 tests passing** (iteration_19). Zero criticals.

- ✅ **[2026-02] Doc 1 mcap-based scaled exit + Doc 2 Phase 3 landing-rate metrics**:
  - `PUMPFUN_LADDER_MODE=ratio|mcap`. Default mcap ladder = `10000:50:5000,60000:50:0,300000:100:0` (50% at $10k with $5k trail, 50% of remainder at $60k grad no-floor moonbag, 100% at $300k).
  - Entry mcap gate (`PUMPFUN_ENTRY_MCAP_MAX_USD`, default $5k). Absolute mcap rug stop (`PUMPFUN_RUG_STOP_MCAP_USD`, default $1300). Fee-economic skip (`PUMPFUN_MIN_SELL_USD`, default $0.20) — silent milestone advance.
  - SOL/USD cache 30s TTL via Jupiter SOL→USDC. Supply pinned at buy so entry-gate + monitor use same denominator.
  - `floor_after=0` in ladder = no trailing floor (moonbag).
  - `tx_landings.py` shared LandingTracker — records every submit/land per module (pumpfun_autobuy / graduation_buy / graduation_sell) with latency + rate. Endpoint `GET /api/live/tx_landings`. Correctly distinguishes `failed` (RPC error / revert) vs `timed_out` (never confirmed).
  - 489/489 tests passing (iteration_18). Zero criticals.

- ✅ **[2026-02] Laddered moonbag exit with ratcheting trailing floor** — shared exit-ladder state machine (`exit_ladder.py`) applied to BOTH pump.fun bonding-curve sniper AND graduation sniper:
  - Default ladder: 5x→80%→floor5x, 20x→50%→floor10x, 100x→100%→floor50x (user's requested 10x gap after 20x milestone).
  - Rug stop at 0.5x before any milestone hit (hard emergency exit).
  - Floor auto-arms after peak > floor × 1.05 (5% arm bonus prevents self-triggering from own sell impact).
  - Ratchet advances floor only UP; new floor is auto-armed since peak has already reached the milestone that fired.
  - Pump.fun sniper: entry_price read from bonding-curve PDA at buy time (with lazy backfill if buy-time read fails); ticker reads virtual_sol/virtual_token every check interval. `tp_sl_enforced` now TRUE (was advisory only).
  - Graduation sniper: entry from Jupiter fill; ticker via reverse quote on remaining tokens.
  - Partial sells via PumpPortal `amount="XX%"` (pumpfun) / Jupiter partial swap (graduation). Failed sells don't advance milestone state.
  - Frontend: both panels show ladder config, rug stop mult, partial_sell events with purple badge, per-position ratio/peak/floor/remaining%.
  - **158/158 tests passing** (iteration_17): pure ladder state-machine tests + integration for both bots + endpoint regression.
  - **Monitor** (`graduation_monitor.py`): `logsSubscribe` on PumpSwap (`pAMMBay...`) + Raydium LaunchLab (`LanMV9...`) programs. Parses migration tx via `getTransaction`, extracts mint/pool/reserves, emits normalized `{source, mint, pool_address, dex, reserves_sol, signature, latency_ms, slot}` event. Dedup via mongo unique index on `(signature, source)`. Auto-reconnect w/ exponential backoff.
  - **Executor** (`graduation_executor.py`): fade-the-dump strategy — 3s settle delay, then Jupiter buy via existing `live_trader` (reuses safety gates + Jito). REAL price-based TP/SL via Jupiter reverse quotes. All decisions locked by `asyncio.Lock` (no race conditions). Kill-switch re-check after settle. Pre-reserves slot before sleep. Refunds budget on failed buy.
  - **Endpoints**: `/api/live/graduation/{status,events,positions}` + `POST /api/live/graduation/replay` (signature backtest) + `POST /api/live/emergency_stop` (in-process kill switch).
  - **Frontend**: `GraduationPanel.jsx` with monitor+executor badges, 6 stat tiles, 9-item config strip, detection list w/ latency, position events w/ real PnL %, emergency-stop button.
  - **Filters**: `min_pool_sol` (default 50 SOL), max_concurrent (2), daily budget cap (0.02 SOL), cooldown (20s), separate `rejects_gate` vs `rejects_filter` counters.
  - **Verified**: 28/28 tests iteration_16, all fail-closed paths + kill-switch + endpoint regression passing.

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
4. Tune `PUMPFUN_LADDER_MCAP` thresholds based on first 2-3 weeks of live trading data.
5. Evaluate secondary HTTP RPC (Alchemy) if Helius credits deplete.

## Next Tasks
1. **[2026-02 iter-21]** User to redeploy Railway with the RPC-indexing-lag fixes and observe:
   - `pumpfun autobuy_status.rejects_safety` should stop increasing purely from `dev_hold_unverifiable`; expect first successful buys.
   - `graduation.status.last_reason` should show fewer `low_liquidity: 0.0 SOL` rejects.
   - `graduation.last_error` keepalive timeouts should be less frequent.
2. Add auth to `/api/live/*` mutation endpoints (P0 #1).
