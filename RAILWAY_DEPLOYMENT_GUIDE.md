# 🚂 Railway Deployment Guide — Solana MEV Arbitrage Bot

Complete step-by-step guide to deploy this project **24/7 on Railway** with:
- **Backend + Bot** → Railway (Docker)
- **Database** → MongoDB Atlas M0 (free forever)
- **Frontend Dashboard** → Vercel (free forever)

Estimated setup time: **45–60 minutes** total.
Estimated monthly cost: **~$5** (Railway hobby plan; Atlas + Vercel are free).

---

## 📋 Prerequisites Checklist

- [x] GitHub account (already linked to this Emergent workspace ✅)
- [x] MongoDB Atlas account ✅
- [x] Vercel account ✅
- [ ] Railway account — sign up at https://railway.app (use GitHub login for easiest setup)
- [ ] A credit card for Railway (they charge ~$5/month after $5 trial credit)

---

## Step 1 — Push code to GitHub

In the Emergent chat input, click **"Save to GitHub"** and pick a repo name like `solana-mev-bot`.
Wait for the push to finish, then verify at `https://github.com/<your-user>/solana-mev-bot` that you see:
- `backend/` folder (with `Dockerfile`)
- `frontend/` folder
- `railway.json` at the root

---

## Step 2 — Set up MongoDB Atlas (free)

1. Sign into https://cloud.mongodb.com/
2. Click **"Build a Database"** → choose **M0 Free** tier.
3. Cloud provider: **AWS**, region: pick the one closest to Railway's US-East (e.g. `us-east-1`).
4. Name the cluster `solana-mev-cluster`. Click **Create**.
5. Under **"Security Quickstart"**:
   - Create a database user: username `mevbot`, generate a strong password (save it!).
   - Add IP access: click **"Allow Access from Anywhere"** → `0.0.0.0/0`. (Railway IPs are dynamic; we'll rely on strong credentials.)
6. Once the cluster is ready, click **"Connect"** → **"Drivers"** → **Python 3.12+**.
   - Copy the connection string, it looks like:
     `mongodb+srv://mevbot:<PASSWORD>@solana-mev-cluster.xxxxx.mongodb.net/?retryWrites=true&w=majority`
   - Replace `<PASSWORD>` with the real password (URL-encode any special characters).
7. Save this string — you'll paste it into Railway.

---

## Step 3 — Deploy backend to Railway

1. Go to https://railway.app/new
2. Click **"Deploy from GitHub repo"** → authorize Railway → pick `solana-mev-bot`.
3. Railway detects the `Dockerfile` at `backend/Dockerfile` and starts building.
   - If Railway doesn't pick it up, click **Settings → Build → Builder → Dockerfile** and set path to `backend/Dockerfile`.
4. While building, click **"Variables"** and add ALL of these:

   | Variable | Value |
   |---|---|
   | `MONGO_URL` | *(paste your Atlas connection string)* |
   | `DB_NAME` | `solana_arbitrage_bot` |
   | `CORS_ORIGINS` | `*` (tighten to your Vercel URL later) |
   | `SOLANA_RPC_URL` | `https://api.mainnet-beta.solana.com` |
   | `SIMULATION_MODE` | `true` |
   | `STARTING_CAPITAL` | `50.0` |
   | `RESERVE_PERCENTAGE` | `75.0` |
   | `MAX_TRADE_PERCENTAGE` | `3.0` |
   | `MIN_PROFIT_THRESHOLD` | `0.002` |
   | `MAX_SLIPPAGE_TOLERANCE` | `0.0015` |
   | `MIN_SPREAD_AFTER_COSTS` | `0.0005` |
   | `MAX_DAILY_LOSS_PERCENTAGE` | `2.0` |
   | `MAX_CONSECUTIVE_FAILURES` | `3` |
   | `COOLDOWN_PERIOD_SECONDS` | `300` |
   | `SOLANA_TX_FEE` | `0.000005` |
   | `SERUM_TAKER_FEE` | `0.0022` |
   | `RAYDIUM_FEE` | `0.0025` |
   | `ORCA_FEE` | `0.003` |
   | `LATENCY_MS` | `150` |
   | `EXECUTION_BUFFER_MS` | `50` |
   | `SOLANA_PRIVATE_KEY` | *leave BLANK for now — add later for live trading* |
   | `QUICKNODE_HTTP_URL` | *leave BLANK unless you have a paid RPC* |

5. Once deployed, click **Settings → Networking → Generate Domain**.
   You'll get a URL like `https://solana-mev-bot-production.up.railway.app`.
6. Test it: open `https://<your-railway-url>/api/health` — should return `{"status":"ok","db":true,...}`.

---

## Step 4 — Deploy frontend to Vercel

1. Go to https://vercel.com/new
2. Import the same GitHub repo `solana-mev-bot`.
3. **Framework Preset:** Create React App (auto-detected).
4. **Root Directory:** click "Edit" and set to `frontend`.
5. Under **Environment Variables**, add:

   | Name | Value |
   |---|---|
   | `REACT_APP_BACKEND_URL` | `https://<your-railway-url>` (from Step 3.5, no trailing slash) |

6. Click **Deploy**. Wait ~2 min.
7. Vercel gives you a URL like `https://solana-mev-bot.vercel.app`. Open it → dashboard loads → done.

---

## Step 5 — Tighten CORS (recommended)

Once you know your Vercel URL:
1. Go back to Railway → Variables → edit `CORS_ORIGINS`
2. Set to: `https://solana-mev-bot.vercel.app`
3. Railway auto-redeploys.

---

## Step 6 — Set up uptime monitoring (free)

Railway can spin down if it thinks the service is idle. Prevent this + get alerts:

**Option A: UptimeRobot (free)** — https://uptimerobot.com
- Add a monitor pointing at `https://<railway-url>/api/health`
- Interval: 5 minutes
- You'll get email/SMS alerts if the bot goes down.

**Option B: Cronitor / BetterStack** — similar, both have free tiers.

---

## Step 7 — Going LIVE with real wallet (later)

⚠️ Only do this AFTER you've watched the bot run in simulation for at least a week.

1. Export your Phantom wallet private key:
   - Phantom → Settings → Security & Privacy → Export Private Key.
   - This gives you a base58 string. **NEVER share it or commit it.**
2. In Railway → Variables:
   - Set `SOLANA_PRIVATE_KEY` to that base58 string.
   - Set `SIMULATION_MODE` to `false`.
3. Fund the wallet:
   - Send a small amount of SOL first (0.5 SOL for gas + $50 worth of trading capital).
4. Get a real RPC (public mainnet is too rate-limited for real trading):
   - Sign up at https://quicknode.com or https://helius.dev (both have free tiers).
   - Create a Solana Mainnet endpoint.
   - Copy the HTTPS URL into `QUICKNODE_HTTP_URL` and `SOLANA_RPC_URL` on Railway.
5. Restart Railway service.
6. **Watch it for the first 30 minutes.** Kill switch: set `SIMULATION_MODE=true` again to halt real trades instantly.

---

## 🆘 Troubleshooting

**Railway build fails on `pip install`**  
Solana Python packages need build tools. The `Dockerfile` already installs `build-essential`. If still failing, check Railway build logs — most fixes involve pinning a package version.

**Frontend loads but shows no data**  
Open browser DevTools → Network tab. If you see CORS errors:
- Verify `REACT_APP_BACKEND_URL` on Vercel matches your Railway URL exactly (no trailing slash).
- Verify `CORS_ORIGINS` on Railway allows the Vercel domain.

**MongoDB "connection refused"**  
- Confirm Atlas IP whitelist includes `0.0.0.0/0`.
- Confirm the connection string password is URL-encoded (`@` becomes `%40`, etc).

**Railway cost creeping up**  
- Free trial gives $5/month for personal accounts.
- Hobby plan ($5/mo flat) covers this bot fully — CPU is low, RAM ~500MB.
- If you see higher usage, check Railway → Observability for a runaway process.

---

## 💰 Monthly Cost Estimate

| Item | Cost |
|---|---|
| Railway Hobby (backend + bot 24/7) | ~$5/mo |
| MongoDB Atlas M0 | $0 |
| Vercel (frontend) | $0 |
| UptimeRobot | $0 |
| **Total** | **~$5/mo** |

Once profitable, you can upgrade Atlas to M10 ($9/mo) for better performance or move to Oracle Cloud for full free-tier 24/7.

---

## ✅ Post-deployment checklist

- [ ] `/api/health` returns 200 OK
- [ ] Dashboard loads on Vercel URL
- [ ] Opportunities appear in "Live Opportunities" section
- [ ] MongoDB Atlas shows collections being written
- [ ] UptimeRobot monitor is green
- [ ] `SIMULATION_MODE=true` confirmed (until live-trading day)
- [ ] Wallet private key NOT committed to Git (double-check `.gitignore`)
