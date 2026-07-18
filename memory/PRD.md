# PRD — Solana MEV Arbitrage Bot (VIP-MEV)

## Original Problem Statement
User uploaded a zip of an existing Solana MEV / flash-loan arbitrage bot project (`VIP-MEV-main-1`) and asked to (1) see what's inside, (2) understand deployment options, and (3) get it running for **free/cheap** first with a path to upgrade later. After weighing options A (Emergent), B (local PC), C (free cloud), user chose **Railway** (~$5/mo) because they'd already tried A and B locally. Plan: clean up the code, get it working in this workspace, then hand off with a deploy-ready repo + step-by-step Railway guide. Real wallet (Phantom) integration is deferred until after everything works in simulation.

## Architecture
- **Backend:** FastAPI (`/app/backend/server.py`) + 37 supporting Python modules (DEX connectors, risk manager, flash-loan monitor, meme detector, etc). MongoDB via `motor`.
- **Frontend:** React 19 + CRA (craco) + Tailwind + shadcn UI. Uses `REACT_APP_BACKEND_URL` for API + WebSocket.
- **Bot loops:** run inside FastAPI lifespan (async background tasks).
- **Deployment stack (chosen):** Railway (backend) + MongoDB Atlas M0 (DB) + Vercel (frontend). Cost: ~$5/mo total.

## Personas
- **User** — semi-technical, has run the bot locally, wants 24/7 cloud uptime cheaply, plans to eventually go live with a Phantom wallet.

## Core Requirements (static)
1. Bot must run 24/7 in the cloud.
2. Deployment must be **cheap** (<$10/mo) initially.
3. Simulation mode by default; no real money at risk until user opts in.
4. Real-time dashboard accessible via public URL.
5. Wallet keys / RPC secrets must NEVER be committed to Git.
6. Easy path to add real Phantom wallet later.

## What's been implemented (2026-07-18)
- ✅ Extracted zip → clean repo at `/app/` (removed 15+ duplicate/experimental files: `hft_flashloan_bot_v1-v8`, `find_*.py`, `fetch_*.py`, `scan_*.py`, misc standalone bots).
- ✅ Backend running under supervisor. All Python imports resolved. Live opportunities being generated (~50 in first minutes, 82 sim trades, 100% success).
- ✅ Frontend compiled and rendering `FlashLoanDashboard`.
- ✅ MongoDB working (`db.ping` OK via `/api/health`).
- ✅ Added `GET /api/health` endpoint for Railway uptime checks.
- ✅ Wrote `/app/backend/Dockerfile` + `/app/backend/.dockerignore` for Railway.
- ✅ Wrote `/app/railway.json` with Docker builder + healthcheck config.
- ✅ Wrote `/app/frontend/vercel.json` (CRA framework, SPA rewrites).
- ✅ Added `.env.example` template + strengthened root `.gitignore` (`.env`, `SOLANA_PRIVATE_KEY` protection).
- ✅ Wrote comprehensive `/app/RAILWAY_DEPLOYMENT_GUIDE.md` — 7 steps from GitHub push → Atlas → Railway → Vercel → CORS lockdown → uptime monitoring → going live with Phantom.
- ✅ Consolidated original setup docs into `/app/docs/` (Pi guide, Windows guide, low-RAM guide, etc — kept as reference).

## Prioritized Backlog

### P0 — Do next
1. **User: push to GitHub** via "Save to GitHub" button in the chat input.
2. **User: sign up for Railway** + **create MongoDB Atlas M0 cluster**.
3. **Follow `RAILWAY_DEPLOYMENT_GUIDE.md`** — should take ~45 min.

### P1 — After first successful cloud run
1. Set up **UptimeRobot** health monitor pointing at `/api/health`.
2. Tighten `CORS_ORIGINS` to the specific Vercel URL (drop `*`).
3. Add a "kill switch" env var toggle in the dashboard UI (currently only in `.env`).

### P2 — Going live with real money
1. Get a paid RPC (QuickNode or Helius free tier).
2. Add `SOLANA_PRIVATE_KEY` to Railway env vars from Phantom export.
3. Set `SIMULATION_MODE=false`.
4. Fund wallet with small amount (0.5 SOL for gas + $50 trading capital).
5. Watch first 30 min of live trades closely.

### Future / nice-to-have
- Rust price feed deployment (adds real DEX prices instead of simulated).
- Auth on the dashboard (currently anyone with URL can view).
- Discord/Telegram alerts on big trades.
- Historical PnL charts.
- Multi-wallet support.

## Next Tasks (immediate)
- Hand off to user: follow `RAILWAY_DEPLOYMENT_GUIDE.md`.
- Assist with any Railway build failures.
- After live URL is up, help wire up Phantom wallet integration.
