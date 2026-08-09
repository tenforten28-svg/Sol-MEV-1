# CHANGELOG — Solana MEV Bot

**Rule: nothing in this file may be reverted or "refactored away" without explicit user approval in chat. Every entry represents a fix or feature the user has approved.**

---

## 2026-02 — Iteration 20 — QuickNode WSS 429 reconnect storm fix
- **Symptom** (live Railway): `connection_count: 20`, `last_error: "429 Invalid response status"`, `total_events_received: 0`. Every WSS connection attempt rejected by QuickNode with HTTP 429.
- **Root cause**: three parallel WSS subscribers (pumpfun_sniper + graduation PumpSwap + graduation LaunchLab) on the same QuickNode endpoint with 1s initial reconnect backoff. First rate-limit response triggers reconnect storm, extending the 429 window indefinitely.
- **Fix** (`backend/pumpfun_sniper.py` + `backend/graduation_monitor.py`): initial reconnect backoff bumped from 1s to 10s; on 429 detection specifically, backoff jumps to ≥60s; exponential growth cap raised from 60s to 300s.
- **User action also needed**: verify QuickNode plan allows ≥3 concurrent WSS subscriptions.

## 2026-02 — Iteration 19 — Production bug fixes (both surfaced by live Railway data)

### BUG 1: Pump.fun sniper detected 64 mints, made 0 buy attempts
- **Root cause**: mint extraction was scanning `Program log: mint: X` lines that pump.fun program does not emit. Every detection had `candidate_mint=None` so `maybe_buy()` was never dispatched.
- **Fix** (`backend/pumpfun_sniper.py`): fetch tx via `getTransaction` (3-retry, 0.8s backoff), pick accountKey with `...pump` vanity suffix. Removed unsafe `accountKeys[1]` fallback (would mis-dispatch creator/PDA accounts as fake mints).
- **New status counters** on `/api/live/pumpfun/status`: `mints_resolved`, `mints_unresolved`, `buys_dispatched`. Makes silent-fail patterns visible.

### BUG 2: Graduation sniper stuck in 2335-cycle sell_failed loop
- **Root cause**: position never removed from `self.positions` after failed sell → retried every 5s forever on illiquid mint.
- **Fix** (`backend/graduation_executor.py`): `GRADUATION_MAX_SELL_FAILURES=5` + `GRADUATION_SELL_RETRY_BACKOFF_SEC=30`. Position ABANDONED after N consecutive failures (removed from positions dict + realized-loss row written to `db.trades` for accurate PnL). `sell_failures` also resets on HOLD (not just successful sell).

## 2026-02 — Iteration 18 — mcap scaled-exit (Doc 1) + landing metrics (Doc 2 Phase 3)
- **`PUMPFUN_LADDER_MODE=ratio|mcap`** — pump.fun sniper supports absolute USD mcap milestones.
- **Default mcap ladder**: `10000:50:5000,60000:50:0,300000:100:0` (50% at $10k mcap w/ $5k trail, 50% of remainder at $60k grad no-floor moonbag, 100% at $300k).
- **Entry mcap gate** `PUMPFUN_ENTRY_MCAP_MAX_USD=5000` — refuses buys above ceiling. Fail-closed on unverifiable mcap.
- **Absolute rug stop** `PUMPFUN_RUG_STOP_MCAP_USD=1300` — hard exit before any milestone.
- **Fee-economic skip** `PUMPFUN_MIN_SELL_USD=0.20` — skip dust partial sells, silently advance ladder.
- **SOL/USD price cache** — 30s TTL via Jupiter SOL→USDC quote.
- **`floor_after=0`** = no trailing floor (moonbag support).
- **Supply pinned** at buy → entry-gate mcap and monitor mcap use same denominator.
- **`tx_landings.py`** — LandingTracker records every submit/land per module with latency + rate. Endpoint `GET /api/live/tx_landings`. `failed` vs `timed_out` correctly distinguished.

## 2026-02 — Iteration 17 — Laddered moonbag exit + ratcheting trailing floor
- **Shared state machine** `backend/exit_ladder.py` — used by pump.fun sniper AND graduation sniper.
- **Default ratio ladder**: `5:80:5,20:50:10,100:100:50` — 80% at 5x (floor 5x), 50% of remainder at 20x (floor 10x — user's 10x-gap requirement), 100% at 100x (floor 50x).
- **Rug stop at 0.5x** before any milestone.
- **Peak-armed floor** — floor arms only after peak > floor × 1.05 (prevents self-triggering from own sell impact).
- **Ratchet auto-arms** new floor immediately (peak already ≥ milestone that fired).
- **Partial sells**: PumpPortal `amount="XX%"` for pump.fun; Jupiter partial swap for graduation.
- **Failed sells don't advance milestone state**.

## 2026-02 — Iteration 16 — Graduation snipe system (fade-the-dump)
- **Monitor** `backend/graduation_monitor.py`: WSS `logsSubscribe` on PumpSwap (`pAMMBay...`) + Raydium LaunchLab (`LanMV9...`). Parses migration tx via `getTransaction`. Normalized event `{source, mint, pool_address, dex, reserves_sol, signature, latency_ms, slot}`. Dedup via mongo unique index on `(signature, source)`. Auto-reconnect w/ exponential backoff.
- **Executor** `backend/graduation_executor.py`: 3s settle → Jupiter buy via `live_trader` (reuses safety gates + Jito). Real price-based TP/SL via Jupiter reverse quotes. `asyncio.Lock`-serialized (no concurrent-detection races). Kill-switch re-checked after settle. Pre-reserves slot before sleep. Refunds budget on failed buy.
- **Endpoints**: `/api/live/graduation/{status,events,positions,replay}` + `POST /api/live/emergency_stop`.

## 2026-02 — Iteration 13-15 — Anti-rug filter suite (6 layers, all fail-closed)
- **Mint authority revoked** required
- **Freeze authority revoked** required
- **Dev holds ≤ `PUMPFUN_MAX_DEV_HOLD_PCT`** (default 15%) — via `getTransaction` postTokenBalances + 3-retry.
- **Largest non-pool holder ≤ `PUMPFUN_MAX_HOLDER_PCT`** (default 20%) — `getTokenLargestAccounts` excluding bonding-curve ATA.
- **Top-10 non-pool ≤ `PUMPFUN_MAX_TOP10_PCT`** (default 30%).
- **Bonding curve real_sol_reserves ≥ `PUMPFUN_MIN_CURVE_SOL`** (default 0.01) AND not graduated — direct PDA read + Anchor decode.
- **Token-2022 honeypot extensions rejected**: transferFeeConfig, permanentDelegate, nonTransferable, transferHook, mintCloseAuthority, defaultAccountState=Frozen.
- **All fail-CLOSED** — any RPC error, missing signature, empty holder list, or parse failure → REJECT.

## 2026-02 — Iteration 12 — Pump.fun direct bonding-curve auto-buy
- **Execution**: PumpPortal `/api/trade-local` builds unsigned tx → local solders signing → QuickNode `sendTransaction`. Wallet key never leaves server.
- **Master gate** `PUMPFUN_AUTO_BUY_ENABLED=false` by default.
- **6-layer budget/concurrency/cooldown safety** + all anti-rug filters above.

## Earlier — Base bot
- FastAPI backend + React frontend + MongoDB.
- Railway backend deployment, Vercel frontend deployment.
- Simulation dashboard separate from live trading.
- Live trader (`live_trader.py`): Jupiter quotes + swap, Jito bundles, safety gates (`SIMULATION_MODE`, `LIVE_TRADING_ENABLED`, wallet whitelist, size caps, cooldown, kill switches).
- Auto-arbitrage monitor (`live_arb_monitor.py`): round-trip Jupiter quote scanner with meme-pair whitelist.
- Pump.fun new-mint detector via QuickNode WSS.

---

## Design decisions that MUST NOT be reverted

1. **All safety gates are fail-CLOSED**. Any RPC error, missing signature, or parse failure → REJECT the buy. Never silently proceed.
2. **Fade-the-dump strategy** (3s settle delay for graduation sniper) — NOT first-slot MEV. Colocated bots would beat us anyway.
3. **Emergency stop is in-process only** — flips gates in memory, does NOT modify Railway env. Restart re-reads env.
4. **PumpPortal is third-party tx BUILDER only** — never has custody or send rights. All signing and submission happens on our backend with QuickNode RPC.
5. **Milestones measured relative to entry price** in ratio mode; **absolute USD mcap** in mcap mode. User confirmed choice A (entry-relative) for ratio mode.
6. **Trailing floor after 20x milestone = 10x** (user's requirement — 10x gap below milestone for pullback breathing room).
7. **No accountKeys[1] fallback for mint extraction** — heuristic would mis-dispatch creator/PDA/fee accounts as mints. Prefer skipping a detection over firing on a wrong address.
8. **Sell-retry backoff is 30s + max 5 failures** — prevents infinite loops on illiquid/rugged tokens.
