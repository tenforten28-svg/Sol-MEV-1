# 📋 Manual Download Guide - File-by-File List

## Complete list of files to download from Emergent

**Total files needed:** ~40 files
**Download time:** 20-30 minutes
**Your Windows location:** `C:\solana-bot\`

---

## 📂 Folder Structure to Create on Windows

Before downloading, create these folders:

```
C:\
└── solana-bot\
    ├── backend\
    └── database\
```

**How to create:**
1. Open File Explorer
2. Navigate to `C:\`
3. Right-click → New → Folder → Name it: `solana-bot`
4. Open `solana-bot` folder
5. Create folder: `backend`
6. Create folder: `database`

---

## 📥 BACKEND FILES (36 Python files + 1 requirements.txt)

**From Emergent:** `/app/backend/` folder
**Save to Windows:** `C:\solana-bot\backend\`

### Core Flash Loan Bot Files (REQUIRED - 14 files)
```
✅ flash_loan_bot_standalone.py         (Main bot - starts trading)
✅ flash_loan_monitor_integrated.py     (Monitors opportunities)
✅ flash_loan_api.py                    (API endpoints)
✅ flash_loan_config.py                 (Configuration)
✅ flash_loan_executor_production.py    (Production trading logic)
✅ flash_loan_executor.py               (Trade execution)
✅ flash_loan_monitor.py                (Price monitoring)
✅ flash_loan_arbitrage_detector.py     (Finds opportunities)
✅ server.py                            (API server - REQUIRED)
✅ solend_flash_loan.py                 (Flash loan integration)
✅ solana_dex_swaps.py                  (DEX swap logic)
✅ risk_manager.py                      (Risk management)
✅ dex_connectors.py                    (DEX connections)
✅ real_price_connector.py              (Live price data)
```

### Price & Data Connectors (REQUIRED - 5 files)
```
✅ real_dex_connector.py                (Real DEX prices)
✅ simple_real_dex.py                   (Simple DEX interface)
✅ meme_price_connector.py              (Meme coin prices)
✅ coinpaprika_connector.py             (Price API)
✅ pool_address_fetcher.py              (Liquidity pools)
```

### Supporting Files (REQUIRED - 10 files)
```
✅ key_manager.py                       (Wallet management)
✅ token_account_manager.py             (Token accounts)
✅ liquidity_verifier.py                (Check liquidity)
✅ failure_handler.py                   (Error handling)
✅ metrics_collector.py                 (Performance tracking)
✅ observability.py                     (Monitoring)
✅ execution_orchestrator.py            (Trade coordination)
✅ bundle_builder.py                    (Transaction building)
✅ jito_submitter.py                    (MEV protection)
✅ update_config_pairs.py               (Config updates)
```

### Other Bot Files (Optional but included - 7 files)
```
⚪ stablecoin_bot_standalone.py        (Stablecoin bot - disabled)
⚪ meme_bot_standalone.py              (Meme bot - disabled)
⚪ meme_arbitrage_detector.py          (Meme detection)
⚪ meme_risk_manager.py                (Meme risk)
⚪ meme_coin_config.py                 (Meme config)
⚪ meme_server_integration.py          (Meme API)
⚪ devnet_test_suite.py                (Testing - future use)
```

### CRITICAL: requirements.txt (REQUIRED)
```
✅ requirements.txt                     (Python dependencies list)
```

---

## 📊 DATABASE EXPORT

**You have 2 options:**

### Option A: Export from Emergent Terminal (RECOMMENDED)

**Step 1:** In Emergent terminal, run:
```bash
cd /app
mongodump --db=solana_arbitrage_bot --out=database_export --gzip
```

**Step 2:** Download the entire `database_export` folder
- Location in Emergent: `/app/database_export/`
- Save to Windows: `C:\solana-bot\database\`

**What's inside:**
```
database_export/
└── solana_arbitrage_bot/
    ├── flash_trades.bson.gz       (~5 MB - flash loan trades)
    ├── flash_trades.metadata.json
    ├── trades.bson.gz             (~20 MB - stablecoin trades)
    ├── trades.metadata.json
    ├── meme_trades.bson.gz        (~10 MB - meme trades)
    ├── meme_trades.metadata.json
    ├── opportunities.bson.gz
    ├── opportunities.metadata.json
    └── ... (other collections)
```

### Option B: Skip Database for Now (Start Fresh)

If database download is too large or complicated:
- Skip database download
- Bot will create new empty database
- Start trading from scratch (no historical data)
- Simpler but loses historical records

---

## 📝 CONFIGURATION FILES TO CREATE

You'll need to create these files manually on Windows:

### File 1: .env (Configuration)
**Location:** `C:\solana-bot\backend\.env`

**Create with Notepad:**
1. Right-click in backend folder → New → Text Document
2. Name it: `.env` (delete .txt extension)
3. Paste this content:

```env
# Database
MONGO_URL=mongodb://localhost:27017/solana_arbitrage_bot
DB_NAME=solana_arbitrage_bot

# Network (Simulation Mode - Safe)
SOLANA_NETWORK=mainnet-beta
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com

# Trading Settings
MIN_PROFIT_BPS=20
MAX_LOAN_SIZE=50000
AUTO_EXECUTE=false
SIMULATE_FIRST=true

# Monitoring
LOG_LEVEL=INFO
```

### File 2: start-backend-only.bat (Startup Script)
**Location:** `C:\solana-bot\start-backend-only.bat`

**Create with Notepad:**
```batch
@echo off
echo Starting Flash Loan Bot - Backend Only Mode
echo.

cd /d "%~dp0backend"

if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
    echo Done!
)

echo Activating virtual environment...
call venv\Scripts\activate

echo.
echo Starting Flash Loan Bot in background...
start "FlashBot" /MIN python flash_loan_bot_standalone.py

echo Waiting 5 seconds...
timeout /t 5 /nobreak > nul

echo.
echo Starting API Server...
echo API: http://localhost:8001
echo.

python server.py

pause
```

### File 3: simple-dashboard.html (Viewer)
**Location:** `C:\solana-bot\simple-dashboard.html`

I'll provide this in next message (it's long)

---

## ✅ DOWNLOAD CHECKLIST

Use this checklist as you download:

### Backend Python Files (37 files total)
- [ ] flash_loan_bot_standalone.py
- [ ] flash_loan_monitor_integrated.py
- [ ] flash_loan_api.py
- [ ] flash_loan_config.py
- [ ] flash_loan_executor_production.py
- [ ] flash_loan_executor.py
- [ ] flash_loan_monitor.py
- [ ] flash_loan_arbitrage_detector.py
- [ ] server.py
- [ ] solend_flash_loan.py
- [ ] solana_dex_swaps.py
- [ ] risk_manager.py
- [ ] dex_connectors.py
- [ ] real_price_connector.py
- [ ] real_dex_connector.py
- [ ] simple_real_dex.py
- [ ] meme_price_connector.py
- [ ] coinpaprika_connector.py
- [ ] pool_address_fetcher.py
- [ ] key_manager.py
- [ ] token_account_manager.py
- [ ] liquidity_verifier.py
- [ ] failure_handler.py
- [ ] metrics_collector.py
- [ ] observability.py
- [ ] execution_orchestrator.py
- [ ] bundle_builder.py
- [ ] jito_submitter.py
- [ ] update_config_pairs.py
- [ ] stablecoin_bot_standalone.py
- [ ] meme_bot_standalone.py
- [ ] meme_arbitrage_detector.py
- [ ] meme_risk_manager.py
- [ ] meme_coin_config.py
- [ ] meme_server_integration.py
- [ ] devnet_test_suite.py
- [ ] requirements.txt ⚠️ CRITICAL

### Database (Optional)
- [ ] Export database from Emergent
- [ ] Download to C:\solana-bot\database\

### Config Files (Create Manually)
- [ ] .env created
- [ ] start-backend-only.bat created
- [ ] simple-dashboard.html created (see next message)

---

## 🎯 PRIORITY DOWNLOAD ORDER

**Do in this order:**

### Priority 1: Minimum to Start (10 files)
```
1. requirements.txt                    ⚠️ FIRST!
2. server.py
3. flash_loan_bot_standalone.py
4. flash_loan_monitor_integrated.py
5. flash_loan_api.py
6. flash_loan_config.py
7. dex_connectors.py
8. risk_manager.py
9. real_price_connector.py
10. solend_flash_loan.py
```

### Priority 2: Core Trading (10 files)
```
11. flash_loan_executor.py
12. flash_loan_executor_production.py
13. flash_loan_monitor.py
14. flash_loan_arbitrage_detector.py
15. solana_dex_swaps.py
16. real_dex_connector.py
17. simple_real_dex.py
18. pool_address_fetcher.py
19. liquidity_verifier.py
20. failure_handler.py
```

### Priority 3: Supporting Files (17 files)
```
21-37. All remaining Python files
```

### Priority 4: Database (If you want historical data)
```
38. database_export folder
```

---

## 📂 FINAL FOLDER STRUCTURE

After all downloads, you should have:

```
C:\solana-bot\
│
├── backend\
│   ├── flash_loan_bot_standalone.py
│   ├── flash_loan_monitor_integrated.py
│   ├── flash_loan_api.py
│   ├── server.py
│   ├── requirements.txt
│   ├── .env  (create manually)
│   └── ... (33 more .py files)
│
├── database\
│   └── solana_arbitrage_bot\
│       ├── flash_trades.bson.gz
│       ├── trades.bson.gz
│       └── ... (database files)
│
├── start-backend-only.bat  (create manually)
└── simple-dashboard.html    (create manually)
```

---

## 🚀 AFTER DOWNLOADING ALL FILES

**Step 1:** Install Python & MongoDB
- Python 3.11: https://www.python.org/downloads/
- MongoDB 7.0: https://www.mongodb.com/try/download/community

**Step 2:** Install Dependencies
```cmd
cd C:\solana-bot\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**Step 3:** Import Database (if downloaded)
```cmd
cd C:\solana-bot\database
mongorestore --gzip solana_arbitrage_bot
```

**Step 4:** Start Bot
```cmd
cd C:\solana-bot
start-backend-only.bat
```

---

## 💡 DOWNLOAD TIPS

**From Emergent File Browser:**
1. Click on each file
2. Look for Download button/icon
3. Or right-click → Download
4. Save to correct Windows folder

**Batch Download:**
- If Emergent allows folder download
- Download entire `/app/backend/` folder at once
- Saves time!

**Alternative: Use Git**
- If project saved to GitHub
- Clone entire repo
- Much faster than individual files

---

## ⚠️ CRITICAL FILES (Don't Miss These!)

**MUST HAVE:**
1. ✅ requirements.txt (Can't install without this!)
2. ✅ server.py (Can't start API without this!)
3. ✅ flash_loan_bot_standalone.py (Main bot file!)
4. ✅ .env file (Must create manually!)

**If you miss any Python file:**
- Bot will show "ModuleNotFoundError"
- Just download the missing file
- Put in backend folder
- Restart bot

---

## 📞 NEED HELP?

**Can't find a file?**
- Check `/app/backend/` in Emergent
- All files should be there

**Download taking too long?**
- Skip database for now
- Download only Priority 1 + 2 files (20 files)
- Bot will work without others

**Confused about structure?**
- Just create the folders as shown
- Download everything to `C:\solana-bot\backend\`
- Bot will work!

---

**Next: I'll provide the simple-dashboard.html code in the next message!**
