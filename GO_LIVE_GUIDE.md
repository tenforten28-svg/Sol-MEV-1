# 🔴 Going LIVE — Complete Step-by-Step Guide

Real Solana trading with **Jupiter v6 Swap API + QuickNode RPC**. Small wallet, safety-first.

⚠️ **Real money can be lost. Read every step. Do not skip the dry runs.**

---

## 🛡️ How the Safety System Works

The bot has **two independent kill switches** — BOTH must be `false`/`true` respectively for real trades to fire:

```
Real trades happen ONLY when:
  ✓ SIMULATION_MODE=false
  ✓ LIVE_TRADING_ENABLED=true
  ✓ SOLANA_RPC_URL is set
  ✓ SOLANA_PRIVATE_KEY is set
  ✓ Trade passes ALL safety gates below
```

**Safety gates (checked before every real trade):**

| Gate | Default | What it does |
|---|---|---|
| `MAX_TRADE_USD` | $2.00 | No single trade above $2 |
| `MIN_RESERVE_SOL` | 0.02 SOL | Wallet must keep 0.02 SOL for gas |
| `DAILY_LOSS_LIMIT_USD` | $3.00 | Halts trading for the day if PnL ≤ -$3 |
| `MAX_LOSING_STREAK` | 3 | Halts after 3 consecutive losing trades |
| `LIVE_COOLDOWN_SECONDS` | 60 | Minimum 60s between real trades |
| `LIVE_SLIPPAGE_BPS` | 50 | Max 0.5% price slippage allowed |
| **Whitelisted pairs only** | 5 pairs | Only SOL/USDC, JitoSOL/SOL, mSOL/SOL, USDC/USDT, JUP/USDC |

**Result:** worst-case daily loss ≈ $3. Even a runaway bug can't drain more than 25% of a $12 wallet in a day.

---

## ✅ Step 1 — Verify the Deployment First (do this NOW)

Push the new code to GitHub and confirm the live endpoints work in **safe/blocked** state:

1. Click **"Save to GitHub"** in the Emergent chat input.
2. Wait for Railway to redeploy (~3 min).
3. Test the new endpoints:

```bash
# Should return ready=false, live_enabled=false
curl https://<your-railway-url>/api/live/status
```

Expected response includes:
```json
{
  "ready": false,
  "simulation_mode": true,
  "live_enabled": false,
  "has_rpc_url": true,
  "has_private_key": false,
  "limits": {...},
  "whitelisted_pairs": ["JUP/USDC", "JitoSOL/SOL", "SOL/USDC", "USDC/USDT", "mSOL/SOL"]
}
```

If you see this — the code is deployed. Continue.

---

## ✅ Step 2 — Prepare Your QuickNode Endpoint

You said you have QuickNode. Confirm you have BOTH:

1. **HTTPS URL** — `https://xxx.solana-mainnet.quiknode.pro/xxx/`
2. **WSS URL** — `wss://xxx.solana-mainnet.quiknode.pro/xxx/` (optional for phase 1)

Test it works:
```bash
curl -X POST <your-quicknode-https-url> \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}'
```
Should return `{"jsonrpc":"2.0","result":"ok","id":1}`.

**Recommended:** install QuickNode's **Metis Jupiter v6 add-on** (free, gives you the Jupiter API through your QuickNode account for higher rate limits). If enabled, use its URL as `JUPITER_BASE_URL` (path is `/quote` NOT `/v6/quote`).

---

## ✅ Step 3 — Fund Your Phantom Wallet

You confirmed $12 (~0.08 SOL). That's borderline for gas. **Send an additional 0.02–0.05 SOL** so the wallet has BOTH:
- ~0.06 SOL trading capital
- ~0.02 SOL untouchable reserve for gas fees

Total: ~$12 trading + ~$3 gas reserve ≈ $15. This gives you meaningful room to actually attempt trades.

---

## ✅ Step 4 — Export Phantom Private Key

⚠️ **This step is dangerous. Do it in private. Never share this key.**

1. Open Phantom browser extension.
2. Click gear icon → **Manage Accounts** → click your wallet.
3. Click **Show Private Key** → enter your Phantom password.
4. Copy the **base58 string** (about 88 characters, mixed letters + numbers, no spaces).
5. Keep this in a safe place (password manager or offline note). **NEVER paste it in chat, code, or Git.**

---

## ✅ Step 5 — Configure Railway Variables

Go to Railway → your service → **Variables** tab. Set these:

### Existing (verify these still there)
```
MONGO_URL=mongodb+srv://... (your Atlas string)
DB_NAME=solana_arbitrage_bot
CORS_ORIGINS=https://sol-mev-1.vercel.app
```

### Solana RPC + Wallet (SET NOW)
```
SOLANA_RPC_URL=<paste your QuickNode HTTPS URL>
QUICKNODE_HTTP_URL=<same URL>
SOLANA_PRIVATE_KEY=<paste your Phantom base58 key>
JUPITER_BASE_URL=https://quote-api.jup.ag/v6
```
(If you enabled QuickNode's Metis add-on, use its URL as `JUPITER_BASE_URL` instead. Otherwise leave as public.)

### Kill switches — KEEP BLOCKED for now
```
SIMULATION_MODE=true              ← LEAVE TRUE
LIVE_TRADING_ENABLED=false        ← LEAVE FALSE
```

### Safety limits (defaults are fine, tune later)
```
MAX_TRADE_USD=2.0
MIN_RESERVE_SOL=0.02
DAILY_LOSS_LIMIT_USD=3.0
MAX_LOSING_STREAK=3
LIVE_COOLDOWN_SECONDS=60
LIVE_SLIPPAGE_BPS=50
LIVE_PROFIT_THRESHOLD_BPS=30
```

Save. Railway auto-redeploys (~30 sec).

---

## ✅ Step 6 — Verify Wallet Connects (Still Safe)

The wallet is now configured but `LIVE_TRADING_ENABLED=false`, so nothing can trade yet.

```bash
curl https://<railway-url>/api/live/status
```

Should now show `has_private_key: true`, `wallet_pubkey: "<your-wallet-address>"`, but `ready: false` (still blocked because live not enabled).

```bash
curl https://<railway-url>/api/live/balance
```

Still returns `ready: false`. That's correct — you're still safely in simulation.

---

## ✅ Step 7 — Enable the Live Trader (still no trades yet)

⚠️ **Point of no return for gate-checking, but still no auto-trading.**

Railway → Variables → change these two:
```
SIMULATION_MODE=false
LIVE_TRADING_ENABLED=true
```

Save. After redeploy (~30 sec):

```bash
curl https://<railway-url>/api/live/status
```

Should NOW show:
```json
{
  "ready": true,           ← ← ← THE BIG CHANGE
  "simulation_mode": false,
  "live_enabled": true,
  "has_rpc_url": true,
  "has_private_key": true,
  "wallet_pubkey": "<your address>",
  ...
}
```

```bash
curl https://<railway-url>/api/live/balance
```

Should return your actual SOL balance from Solana mainnet! Something like:
```json
{"ready": true, "wallet": "abc...", "sol": 0.0812, "meets_reserve": true}
```

**If sol > 0 and meets_reserve: true → you're now live-capable.** But still no auto-trades happen because the auto-execution isn't wired to `monitor_arbitrage` yet (deliberate — dry-run first).

---

## ✅ Step 8 — Manual Dry-Run Quote (no funds moved)

Test that Jupiter routing works end-to-end without risking a cent:

```bash
curl -X POST https://<railway-url>/api/live/test_swap \
  -H "Content-Type: application/json" \
  -d '{"input_symbol":"USDC","output_symbol":"SOL","amount_usd":1.0,"dry_run":true}'
```

Expected:
```json
{
  "ok": true,
  "dry_run": true,
  "pair": "USDC/SOL",
  "amount_usd": 1.0,
  "quote_in_amount": "1000000",
  "quote_out_amount": "6543210",
  "price_impact_pct": "0.0001",
  "route_labels": ["Meteora", "Raydium"]
}
```

If this works → **Jupiter is routing correctly through YOUR QuickNode. Everything is wired.**

Note: `USDC/SOL` isn't in your whitelist (`SOL/USDC` is, but not reverse). You'll get `pair not in whitelist`. Try `SOL/USDC` direction:

```bash
curl -X POST https://<railway-url>/api/live/test_swap \
  -H "Content-Type: application/json" \
  -d '{"input_symbol":"SOL","output_symbol":"USDC","amount_usd":0.5,"dry_run":true}'
```

---

## ✅ Step 9 — FIRST REAL TRADE (0.5 SOL → USDC, tiny amount)

⚠️ **This is your first real on-chain transaction. Expect to lose ~$0.01 to gas.**

```bash
curl -X POST https://<railway-url>/api/live/test_swap \
  -H "Content-Type: application/json" \
  -d '{"input_symbol":"SOL","output_symbol":"USDC","amount_usd":0.5,"dry_run":false}'
```

Expected response after ~10-30 seconds:
```json
{
  "ok": true,
  "dry_run": false,
  "pair": "SOL/USDC",
  "success": true,
  "signature": "5xY7z...",
  "in_amount": "3300000",
  "out_amount": "494000",
  "error": null
}
```

**Verify on-chain:**
- Open `https://solscan.io/tx/<signature>` in browser
- You should see the swap executed
- Your Phantom wallet should show slightly less SOL, slightly more USDC

Then swap it back:
```bash
curl -X POST https://<railway-url>/api/live/test_swap \
  -H "Content-Type: application/json" \
  -d '{"input_symbol":"USDC","output_symbol":"SOL","amount_usd":0.45,"dry_run":false}'
```

Wait — this fails because `USDC/SOL` is not whitelisted. To do a round-trip test, we'd need to add `USDC/SOL` to whitelist OR just leave USDC in the wallet. Your call.

---

## 🚦 What's NOT Yet Enabled (deliberate)

- ❌ **Auto-arbitrage isn't wired to `monitor_arbitrage` yet.** The dashboard's "opportunity" simulation still runs in fake mode.
- ❌ **Round-trip arbitrage detection** exists in the playbook but I didn't wire it (would need proper decimal math + reverse-pair whitelist).

This is intentional. **Test manual swaps first** for a few days. If those work reliably, I'll wire auto-execution as the next step.

---

## 📊 Monitor Your Live Trading

- **Wallet balance:** `curl https://<railway-url>/api/live/balance`
- **Risk state:** `curl https://<railway-url>/api/live/status` (check `risk` field for `day_pnl_usd`, `losing_streak`, `blocked_reason`)
- **Trades history:** All live trades are stored in MongoDB `trades` collection with `simulation: false` flag
- **On-chain proof:** Every signature is a Solscan link — verify each trade actually happened

---

## 🛑 Kill Switch (Instant Halt)

If anything goes wrong, IMMEDIATELY set on Railway:
```
LIVE_TRADING_ENABLED=false
```
Save. Within 30 sec, all live trading endpoints will refuse new trades.

For **nuclear kill** — also set:
```
SIMULATION_MODE=true
```
Both together = zero possibility of any real trade until you flip them back.

---

## 💰 Realistic Expectations (I have to say this)

| Timeframe | Realistic outcome |
|---|---|
| Day 1 (3-5 manual test swaps) | Lose ~$0.05-0.15 to gas. This is expected tuition. |
| Week 1 (manual testing only) | ~$0.50-2 lost. Learning phase. |
| Week 2-4 (if you wire auto-arb) | -$3 to +$1 net. Most likely negative for a small wallet. |
| Month 2+ | Only positive if you found a specific niche + tuned it. |

**Real MEV bots need:** millisecond-latency infra, colocated hardware, private mempool access via Jito, dozens of concurrent strategies, and often trade at loss to gather data. A $12 wallet from a Railway container is fighting billion-dollar operations.

This is **valuable learning**, not a get-rich scheme. Enjoy the process.

---

## 🎯 Next Question for Me (when you're ready)

After you've done 5-10 manual `/api/live/test_swap` calls with `dry_run: false` and confirmed they work, come back and tell me:
- Success rate
- Net PnL (Solscan wallet history)
- Average slippage vs quote

Then I'll help you wire the auto-execution path into `monitor_arbitrage` if the results warrant it.

Good luck. 🚀
