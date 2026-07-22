# 💳 RPC Credit Budget Guide — Free Tier 10M/month

Target: use the **full 10M QuickNode credits per month** without going over (~333,333/day, ~13,889/hour).

---

## 🎯 TL;DR — Recommended Railway env-var settings

Copy these into your Railway → Variables:

```env
SCAN_INTERVAL_SECONDS=7
MONITORED_PAIRS=SOL/USDC,RAY/USDC,ORCA/USDC,JUP/USDC,JTO/USDC,PYTH/USDC,SOL/USDT,USDC/USDT
CREDITS_PER_PAIR_SCAN=3
CREDITS_PER_TRADE=10
```

**Projected usage:** ~8.9M credits/month (89% of budget) — leaves ~1.1M for trade executions + spikes.

Live URL to verify anytime:
```
https://<your-railway-url>/api/credit_estimate
```

---

## 📐 The Formula

```
credits_per_month = (86400 ÷ SCAN_INTERVAL_SECONDS)
                  × MONITORED_PAIR_COUNT
                  × CREDITS_PER_PAIR_SCAN
                  × 30
                  + (live_trades_per_day × CREDITS_PER_TRADE × 30)
```

Where:
- `86400` = seconds in a day
- `CREDITS_PER_PAIR_SCAN ≈ 3` — one `getAccountInfo` per DEX pool
- `CREDITS_PER_TRADE ≈ 10` — blockhash + simulate + send + confirm

---

## 📊 Preset Configurations

| Preset | Scan Interval | Pair Count | Monthly Scans | Monthly Credits | % of 10M | Verdict |
|---|---|---|---|---|---|---|
| **Current default (unsafe)** | 2.5s | 8 | 1.03M | 24.9M | 249% | ❌ OVER |
| **Balanced (5s)** | 5s | 8 | 519K | 12.4M | 124% | ❌ OVER |
| **⭐ RECOMMENDED (7s)** | 7s | 8 | 370K | **8.9M** | **89%** | 🎯 TARGET |
| **Safe (10s)** | 10s | 8 | 259K | 6.2M | 62% | ✅ SAFE |
| **Conservative (15s + 4 pairs)** | 15s | 4 | 86K | 2.1M | 21% | ✅ SAFE |

---

## 🎛️ Custom Tuning — Choose Your Trade-off

### More pairs → more opportunities, but more credits
Adding one pair to an 8-pair setup at 7s interval:
- Extra scans: 370K/mo × 1 pair × 3 credits = **+1.1M credits/mo**

### Faster scans → fresher prices, but more credits
Going from 10s → 5s at 8 pairs:
- Doubles scan count → **+6.2M credits/mo**

### Fewer pairs → less credits, focus on top opportunities
Dropping to just 4 major pairs (SOL/USDC, RAY/USDC, ORCA/USDC, JUP/USDC):
- Cuts scan credits in half → **save ~4.4M/mo**

---

## 🧮 Custom Formula — Fit YOUR Setup to 10M

**To find the max scan interval for N pairs to fit in 10M/month:**

```
min_interval = (86400 × 30 × N × 3) ÷ 10,000,000
             = 0.778 × N seconds
```

| Pair Count | Min interval to fit 10M/mo |
|---|---|
| 4 pairs | 3.1s |
| 6 pairs | 4.7s |
| 8 pairs | 6.2s (use 7s for safety) |
| 10 pairs | 7.8s (use 8s) |
| 12 pairs | 9.3s (use 10s) |
| 16 pairs | 12.4s (use 13s) |

---

## 🚦 Live Trade Credit Cost

When you set `SIMULATION_MODE=false`, each real trade adds:
- **~10 credits per trade** (blockhash + simulate + send + confirm polling)

Budget-planning:

| Live trades/day | Extra monthly credits | Fits with 7s-scan / 8 pairs? |
|---|---|---|
| 100 | 30K | ✅ (89.3% total) |
| 500 | 150K | ✅ (90.4%) |
| 1,000 | 300K | ✅ (91.9%) |
| 2,000 | 600K | ✅ (94.9%) |
| 5,000 | 1.5M | 🎯 (103.9%) — very close, cut interval to 8s |

Realistically, a well-tuned bot will attempt **200–800 real trades per day**, not thousands. Your simulation shows 8,000+ because there's no real-world friction filtering them out.

---

## 🚨 Safety Guards to Set on QuickNode

Even with the config above, always add these guardrails on QuickNode's dashboard:

1. **Rate limit:** Set request-per-second cap to 40 (below their 50/sec free-tier limit).
2. **Usage alerts:** Enable email alerts at 50%, 75%, 90% monthly usage.
3. **Auto-pause:** Some plans support auto-pause at 100%. Enable it.

On Railway also:
1. **Hard spending cap:** $15 (already set — see `RAILWAY_DEPLOYMENT_GUIDE.md`).
2. **Cost alerts:** Email at $3.

---

## 🔍 Real-Time Monitoring

Your bot exposes a live estimate endpoint:

```
GET https://<railway-url>/api/credit_estimate
```

Response includes:
- Current scan interval + pair count
- Projected credits/day and credits/month
- % of 10M budget
- Verdict: `FITS_WITH_MARGIN` / `TARGETED_FULL_USE` / `OVER_BUDGET`

Check this whenever you change env vars — it updates instantly on Railway redeploy.

Also check QuickNode dashboard daily during the first week to confirm reality matches projection.

---

## 🛠️ Steps to Apply the Recommended Config

1. Sign up at https://www.quicknode.com → create Solana Mainnet endpoint → copy HTTPS URL.
2. Railway → your service → **Variables** → set:
   ```
   SOLANA_RPC_URL=<your-quicknode-url>
   QUICKNODE_HTTP_URL=<same-quicknode-url>
   SCAN_INTERVAL_SECONDS=7
   MONITORED_PAIRS=SOL/USDC,RAY/USDC,ORCA/USDC,JUP/USDC,JTO/USDC,PYTH/USDC,SOL/USDT,USDC/USDT
   CREDITS_PER_PAIR_SCAN=3
   CREDITS_PER_TRADE=10
   ```
3. Save → Railway auto-redeploys.
4. Verify: open `https://<railway-url>/api/credit_estimate` — should show ~8.9M monthly + `TARGETED_FULL_USE`.
5. On QuickNode dashboard, watch first day's usage. Should be roughly:
   - Day 1: ~296K credits
   - Week 1: ~2.1M credits
   - Month 1: ~8.9M credits

If actual usage is much higher than projected, the `CREDITS_PER_PAIR_SCAN` assumption may be low — some heavy RPC methods cost 5–10 credits. Increase `CREDITS_PER_PAIR_SCAN` env var to 5 to recalibrate, then adjust `SCAN_INTERVAL_SECONDS` accordingly.

---

## 📝 Key Insight: Simulation vs Live

**In simulation mode (current):** bot uses free Jupiter API for prices → **near-zero RPC credits**. You could scan every second for a month and burn <1M credits.

**In live mode:** bot switches to direct pool queries + real transactions → credits get spent per the formula above.

**⚠️ Don't worry about your credits in simulation mode.** The formulas above only matter after you flip `SIMULATION_MODE=false`.
