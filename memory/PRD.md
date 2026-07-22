# PRD — Solana MEV Arbitrage Bot (VIP-MEV)

## Original Problem Statement
User uploaded a Solana MEV/arbitrage bot zip, chose to deploy on Railway (~$5/mo), and wants to eventually go LIVE with a Phantom wallet (~$12) using QuickNode's 10M/mo free tier.

## Architecture (live)
- **Backend:** FastAPI on Railway (Docker). Runs simulated arbitrage monitor + NEW live-trading module.
- **DB:** MongoDB Atlas M0.
- **Frontend:** React on Vercel (`sol-mev-1.vercel.app`).
- **Live execution:** `live_trader.py` = Jupiter v6 quote+swap → sign with solders → submit via QuickNode.

## What's implemented (through 2026-07-22)
- ✅ Cleaned & deployed to Railway (Dockerfile fixed, PORT env expansion, MongoDB Atlas connected).
- ✅ Vercel frontend live, connected to Railway backend, no CORS issues.
- ✅ App.js routing shows the real Arbitrage Bot dashboard (not the empty Flash Loan tab).
- ✅ `/api/health` endpoint for Railway uptime checks.
- ✅ **`/app/backend/live_trader.py`** — Jupiter v6 + QuickNode + solders signing + safety guards.
- ✅ **`/api/live/status`**, **`/api/live/balance`**, **`/api/live/test_swap`** endpoints.
- ✅ **Safety-first design**: double kill switch (`SIMULATION_MODE` + `LIVE_TRADING_ENABLED`), max trade $2, min reserve 0.02 SOL, daily loss $3, max losing streak 3, cooldown 60s, whitelisted 5 pairs only.
- ✅ Manual `dry_run` endpoint for verification without submitting on-chain.
- ✅ **`/app/GO_LIVE_GUIDE.md`** — 9-step deployment/verification guide.

## What's NOT yet wired
- ❌ Auto-execution NOT connected to `monitor_arbitrage` loop (deliberate — manual testing first).
- ❌ Round-trip arbitrage detection (needs decimal math + reverse-pair whitelist).
- ❌ Frontend UI for live-trader controls (still using API endpoints via curl).

## Prioritized Backlog

### P0 — User's next actions
1. Push code to GitHub → Railway auto-redeploys.
2. Set env vars on Railway per `GO_LIVE_GUIDE.md` (keep `LIVE_TRADING_ENABLED=false` for now).
3. Verify `/api/live/status` returns correct config.
4. Do 5-10 manual `/api/live/test_swap` calls (start with `dry_run: true`, then `false` with tiny amounts).
5. Report results back for evaluation.

### P1 — After manual testing works
1. Wire live executor into `monitor_arbitrage` (auto-execute when opportunity found).
2. Add reverse-pair whitelist (`USDC/SOL`, etc.) to allow round-trip arbs.
3. Add proper round-trip profitability check.
4. Frontend UI panel for `/api/live/*` endpoints.

### P2 — Optimization
1. QuickNode Metis add-on for higher rate limits.
2. `accountSubscribe` WebSocket monitoring for top pairs.
3. Priority fee tuning based on real success rates.
4. Dashboard live vs simulation split view.

## Next Tasks
- Handoff to user for Railway env var setup + manual testing.
- Await results of first ~5 live swaps before wiring auto-exec.
