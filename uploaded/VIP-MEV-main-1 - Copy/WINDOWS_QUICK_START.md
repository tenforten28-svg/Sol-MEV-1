# 🪟 Flash Loan Bot - Windows Quick Start Guide
## Ready-to-Use Installation Package

**Your System:** ✅ Windows with 8GB+ RAM
**Time Required:** 1-2 hours
**Cost:** $0

---

## 📦 Step 1: Download Required Software (30 minutes)

### 1.1 Python 3.11 (Required)

**Download:**
1. Go to: https://www.python.org/downloads/
2. Click: "Download Python 3.11.7" (or latest 3.11.x)
3. Save to Downloads folder

**Install:**
1. Double-click downloaded file
2. ⚠️ **CRITICAL:** Check ✓ "Add Python to PATH"
3. Click "Install Now"
4. Wait 5 minutes
5. Click "Close"

**Verify:**
```
Press Windows + R
Type: cmd
Press Enter

In Command Prompt, type:
python --version

Should show: Python 3.11.x
```

---

### 1.2 Node.js 20 LTS (Required)

**Download:**
1. Go to: https://nodejs.org/
2. Click: "Download LTS" (green button, v20.x.x)
3. Save to Downloads

**Install:**
1. Double-click downloaded .msi file
2. Click "Next" through wizard
3. Accept all defaults
4. Click "Install"
5. Wait 3 minutes
6. Click "Finish"

**Verify:**
```
In Command Prompt:
node --version
npm --version

Should show:
v20.x.x
10.x.x
```

**Install Yarn:**
```
npm install -g yarn
```

---

### 1.3 MongoDB 7.0 (Required)

**Download:**
1. Go to: https://www.mongodb.com/try/download/community
2. Select:
   - Version: 7.0.x (latest)
   - Platform: Windows
   - Package: MSI
3. Click "Download"
4. Save to Downloads (large file ~300MB)

**Install:**
1. Double-click downloaded .msi file
2. Click "Next"
3. Select "Complete" installation
4. ⚠️ **CHECK:** "Install MongoDB as a Service"
5. ⚠️ **CHECK:** "Run service as Network Service user"
6. ⚠️ **CHECK:** "Install MongoDB Compass" (optional but recommended)
7. Click "Install"
8. Wait 10 minutes
9. Click "Finish"

**Verify MongoDB Service:**
```
Press Windows + R
Type: services.msc
Press Enter

Find: "MongoDB Server"
Status should be: Running
```

**Test Connection:**
```
In Command Prompt:
mongosh

Should see: "Connecting to: mongodb://127.0.0.1:27017"
Type: exit
```

---

### 1.4 Git (Required)

**Download:**
1. Go to: https://git-scm.com/download/win
2. Download starts automatically
3. Save to Downloads

**Install:**
1. Double-click downloaded file
2. Click "Next" through all screens
3. Accept all defaults
4. Click "Install"
5. Click "Finish"

**Verify:**
```
In Command Prompt:
git --version

Should show: git version 2.x.x
```

---

## 📂 Step 2: Create Project Folder (5 minutes)

### 2.1 Create Main Directory

**Using File Explorer:**
```
1. Open File Explorer
2. Navigate to C:\
3. Right-click → New → Folder
4. Name it: solana-bot
5. Open the folder
```

**Or using Command Prompt:**
```
cd C:\
mkdir solana-bot
cd solana-bot
```

---

## 💾 Step 3: Download Bot Code (Method 1 - Export from Emergent)

### 3.1 Export Database First

**In Emergent terminal:**
```bash
# Navigate to app directory
cd /app

# Export MongoDB database
mongodump --db=solana_arbitrage_bot --out=/tmp/db_backup --gzip

# Create tarball with all files
tar -czf /tmp/flashbot-export.tar.gz \
  backend/*.py \
  backend/requirements.txt \
  backend/.env \
  frontend/src \
  frontend/package.json \
  frontend/public \
  /tmp/db_backup

# Check size
ls -lh /tmp/flashbot-export.tar.gz
```

### 3.2 Download Export Package

**Option A: Direct Download**
```bash
# I'll provide a download link after creating the package
# Download to: C:\Users\[YourName]\Downloads\flashbot-export.tar.gz
```

**Option B: Using Git (if available)**
```bash
# Alternative: Clone from repository (if set up)
cd C:\solana-bot
git clone [REPOSITORY_URL] .
```

### 3.3 Extract Files

**If you have 7-Zip or WinRAR:**
```
1. Right-click flashbot-export.tar.gz
2. Extract Here
3. Extract again (tar file inside)
4. Copy all folders to C:\solana-bot\
```

**Using Windows built-in:**
```
1. Rename .tar.gz to .zip
2. Right-click → Extract All
3. Copy contents to C:\solana-bot\
```

**Your folder structure should look like:**
```
C:\solana-bot\
├── backend\
│   ├── flash_loan_bot_standalone.py
│   ├── flash_loan_monitor_integrated.py
│   ├── flash_loan_api.py
│   ├── server.py
│   ├── requirements.txt
│   └── ... (other files)
├── frontend\
│   ├── src\
│   ├── public\
│   └── package.json
└── database\
    └── solana_arbitrage_bot\
        └── ... (MongoDB backup files)
```

---

## 🔧 Step 4: Install Dependencies (30 minutes)

### 4.1 Backend Python Dependencies

**Open Command Prompt as Administrator:**
```
Press Windows key
Type: cmd
Right-click "Command Prompt"
Select: "Run as administrator"
```

**Navigate and Install:**
```bash
cd C:\solana-bot\backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
venv\Scripts\activate

# You should see (venv) in prompt

# Upgrade pip
python -m pip install --upgrade pip

# Install requirements (takes 10-15 minutes)
pip install -r requirements.txt

# Wait patiently - this installs many packages
```

**If you see errors about missing Visual C++:**
```
Download and install:
https://aka.ms/vs/17/release/vc_redist.x64.exe
Then retry: pip install -r requirements.txt
```

---

### 4.2 Frontend Node.js Dependencies

**Open NEW Command Prompt (don't close backend one):**
```bash
cd C:\solana-bot\frontend

# Install dependencies (takes 5-10 minutes)
yarn install

# Or if yarn doesn't work:
npm install
```

---

## 🗄️ Step 5: Import Database (10 minutes)

**In Command Prompt:**
```bash
cd C:\solana-bot\database

# Restore MongoDB backup
mongorestore --gzip --drop solana_arbitrage_bot

# Should see progress bars and "done"
```

**Verify Import:**
```bash
mongosh solana_arbitrage_bot

# In MongoDB shell:
show collections
db.flash_trades.countDocuments()
# Should show: thousands of documents

exit
```

---

## ⚙️ Step 6: Configure Environment Variables (10 minutes)

### 6.1 Backend Configuration

**Create .env file:**
```bash
cd C:\solana-bot\backend

# Open Notepad
notepad .env
```

**In Notepad, paste this:**
```env
# Database Configuration
MONGO_URL=mongodb://localhost:27017/solana_arbitrage_bot
DB_NAME=solana_arbitrage_bot

# Network Configuration (Simulation Mode)
SOLANA_NETWORK=mainnet-beta
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com

# Trading Configuration
MIN_PROFIT_BPS=20
MAX_LOAN_SIZE=50000
AUTO_EXECUTE=false
SIMULATE_FIRST=true

# Monitoring
LOG_LEVEL=INFO
```

**Save:**
```
File → Save As
File name: .env
Save as type: All Files (*)
Save in: C:\solana-bot\backend\
Click Save
```

---

### 6.2 Frontend Configuration

**Create frontend .env:**
```bash
cd C:\solana-bot\frontend

notepad .env
```

**Paste:**
```env
REACT_APP_BACKEND_URL=http://localhost:8001
```

**Save as: .env** (same process as above)

---

## 🚀 Step 7: Create Startup Scripts (10 minutes)

### 7.1 Backend Startup Script

**Create start-backend.bat:**
```bash
cd C:\solana-bot

notepad start-backend.bat
```

**Paste this:**
```batch
@echo off
echo Starting Flash Loan Bot Backend...
echo.

cd C:\solana-bot\backend

echo Activating Python virtual environment...
call venv\Scripts\activate

echo Starting Flash Loan Bot (background)...
start "FlashBot" python flash_loan_bot_standalone.py

echo Waiting 5 seconds...
timeout /t 5 /nobreak

echo Starting API Server...
python server.py

pause
```

**Save as: start-backend.bat**

---

### 7.2 Frontend Startup Script

**Create start-frontend.bat:**
```bash
notepad start-frontend.bat
```

**Paste:**
```batch
@echo off
echo Starting Flash Loan Dashboard...
echo.

cd C:\solana-bot\frontend

echo Installing/updating dependencies...
call yarn install

echo Starting development server...
echo Dashboard will open at http://localhost:3000
echo.
call yarn start

pause
```

**Save as: start-frontend.bat**

---

### 7.3 Quick Start Script (Optional)

**Create start-all.bat:**
```batch
@echo off
echo.
echo ╔══════════════════════════════════════════╗
echo ║   Flash Loan Bot - Starting Services    ║
echo ╚══════════════════════════════════════════╝
echo.

echo [1/3] Starting MongoDB...
net start MongoDB

echo.
echo [2/3] Starting Backend...
start "Backend" cmd /k "cd C:\solana-bot && start-backend.bat"

echo.
echo [3/3] Waiting 10 seconds before starting frontend...
timeout /t 10 /nobreak

echo Starting Frontend...
start "Frontend" cmd /k "cd C:\solana-bot && start-frontend.bat"

echo.
echo ✓ All services started!
echo ✓ Dashboard will open at: http://localhost:3000
echo.
pause
```

**Save as: start-all.bat**

---

## 🎯 Step 8: First Run! (Testing)

### 8.1 Start Backend

**Method 1: Double-click**
```
1. Open File Explorer
2. Go to: C:\solana-bot
3. Double-click: start-backend.bat
4. A black Command Prompt window opens
5. Wait 10 seconds
6. Should see: "Uvicorn running on http://0.0.0.0:8001"
```

**Method 2: From Command Prompt**
```bash
cd C:\solana-bot
start-backend.bat
```

**✅ Backend is running when you see:**
```
INFO:     Uvicorn running on http://0.0.0.0:8001 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
```

**⚠️ Keep this window open!**

---

### 8.2 Start Frontend

**Method 1: Double-click**
```
1. Double-click: start-frontend.bat
2. Another Command Prompt window opens
3. Wait 30 seconds
4. Browser opens automatically to http://localhost:3000
```

**Method 2: Manual**
```bash
# In new Command Prompt
cd C:\solana-bot
start-frontend.bat
```

**✅ Frontend is running when you see:**
```
Compiled successfully!

You can now view frontend in the browser.

  Local:            http://localhost:3000
  On Your Network:  http://192.168.x.x:3000
```

**⚠️ Keep this window open too!**

---

### 8.3 Access Dashboard

**Automatic:**
- Browser should open to http://localhost:3000

**Manual:**
1. Open any browser (Chrome, Edge, Firefox)
2. Go to: http://localhost:3000

**✅ Success if you see:**
- Flash Loan Dashboard loads
- "Today's Performance" card showing trades
- "Daily Performance History" table
- Numbers updating

---

## ✅ Step 9: Verification Checklist

**Check these:**
- [ ] Backend window shows "Uvicorn running"
- [ ] Frontend window shows "Compiled successfully"
- [ ] Dashboard loads at http://localhost:3000
- [ ] "Trades Today" shows a number
- [ ] "Total Net Profit" shows amount
- [ ] "Daily Performance History" has data
- [ ] No error messages in windows

**If all checked ✅ - YOU'RE DONE!**

---

## 🔄 Step 10: Power Settings (IMPORTANT)

### 10.1 Disable Sleep Mode

**Method 1: Settings App**
```
1. Press Windows + I (opens Settings)
2. Click "System"
3. Click "Power & battery" (or "Power & sleep")
4. Under "Screen and sleep":
   - When plugged in, turn off after: Never
   - When plugged in, PC goes to sleep after: Never
5. Click "Additional power settings"
6. Click "Change plan settings"
7. Set "Turn off display" to: Never
8. Set "Put computer to sleep" to: Never
9. Click "Change advanced power settings"
10. Expand "Sleep"
11. Set "Sleep after" to: 0 minutes (Never)
12. Set "Hibernate after" to: 0 minutes (Never)
13. Click OK
```

**Method 2: Command Prompt (Quick)**
```bash
# Run as Administrator
powercfg /change standby-timeout-ac 0
powercfg /change standby-timeout-dc 0
powercfg /change hibernate-timeout-ac 0
powercfg /change hibernate-timeout-dc 0
```

---

### 10.2 Prevent Monitor Sleep (Optional)

**Download Caffeine (Tiny App):**
```
1. Go to: https://www.zhornsoftware.co.uk/caffeine/
2. Download: caffeine.exe (65 KB)
3. Run it
4. Icon appears in system tray (coffee cup)
5. Double-click to activate (stays awake)
```

---

## 🔁 Step 11: Auto-Start on Windows Boot (Optional)

### Method 1: Task Scheduler (Recommended)

**Create Backend Task:**
```
1. Press Windows + R
2. Type: taskschd.msc
3. Press Enter
4. Click "Create Task" (right panel)

General Tab:
- Name: Flash Loan Bot Backend
- Description: Starts backend on boot
- ✓ Run with highest privileges
- ✓ Run whether user is logged on or not
- Configure for: Windows 10/11

Triggers Tab:
- Click "New"
- Begin the task: At startup
- Delay task for: 30 seconds
- ✓ Enabled
- Click OK

Actions Tab:
- Click "New"
- Action: Start a program
- Program: C:\solana-bot\start-backend.bat
- Start in: C:\solana-bot
- Click OK

Conditions Tab:
- ✓ Start only if the computer is on AC power
- Uncheck: Stop if computer switches to battery

Settings Tab:
- ✓ Allow task to be run on demand
- ✓ Run task as soon as possible after scheduled start
- If task fails, restart every: 1 minute
- Attempt to restart up to: 3 times
- Click OK

6. Enter Windows password when prompted
7. Click OK
```

**Create Frontend Task:**
```
Repeat above steps with:
- Name: Flash Loan Bot Frontend
- Program: C:\solana-bot\start-frontend.bat
- Delay: 60 seconds (start after backend)
```

---

### Method 2: Startup Folder (Simple but less reliable)

```
1. Press Windows + R
2. Type: shell:startup
3. Press Enter
4. Folder opens
5. Right-click → New → Shortcut
6. Location: C:\solana-bot\start-all.bat
7. Name: Flash Loan Bot
8. Click Finish
```

**Test:**
1. Restart computer
2. Wait 2 minutes after login
3. Check if Command Prompt windows open
4. Open browser to http://localhost:3000

---

## 📊 Step 12: Daily Usage

### Starting Manually

**Quick Start:**
```
Double-click: C:\solana-bot\start-all.bat
Wait 1-2 minutes
Open browser: http://localhost:3000
```

**Or individual services:**
```
1. Double-click: start-backend.bat
2. Wait 10 seconds
3. Double-click: start-frontend.bat
4. Wait 30 seconds
5. Browser opens automatically
```

---

### Stopping

**Close both Command Prompt windows:**
1. Click X on backend window
2. Click X on frontend window

**Or press Ctrl+C in each window**

---

### Checking Status

**Task Manager:**
```
Press Ctrl + Shift + Esc
Look for:
- python.exe (backend)
- node.exe (frontend)
```

**Or check services:**
```
netstat -ano | findstr "8001"   # Backend
netstat -ano | findstr "3000"   # Frontend
```

---

## 🛠️ Troubleshooting

### Backend Won't Start

**Error: "Python not found"**
```
Solution: Reinstall Python with "Add to PATH" checked
```

**Error: "MongoDB connection failed"**
```
Solution 1: Check MongoDB service running
- Windows + R → services.msc
- Find "MongoDB Server"
- Right-click → Start

Solution 2: Restart MongoDB
- net stop MongoDB
- net start MongoDB
```

**Error: "No module named ..."**
```
Solution: Reinstall dependencies
cd C:\solana-bot\backend
venv\Scripts\activate
pip install -r requirements.txt --force-reinstall
```

---

### Frontend Won't Start

**Error: "yarn command not found"**
```
Solution: Use npm instead
cd C:\solana-bot\frontend
npm install
npm start
```

**Error: "Port 3000 already in use"**
```
Solution: Kill process using port
netstat -ano | findstr "3000"
taskkill /PID [number] /F
```

---

### Dashboard Won't Load

**Check 1: Backend running?**
```
Open: http://localhost:8001/api/flash/stats
Should see JSON data
```

**Check 2: Frontend compiled?**
```
Look for: "Compiled successfully!" in window
```

**Check 3: Firewall blocking?**
```
Windows Defender Firewall → Allow an app
Add: python.exe and node.exe
```

---

## 📈 Monitoring

### View Trade Data

**Dashboard:** http://localhost:3000

**API Stats:** http://localhost:8001/api/flash/stats

**Database:**
```bash
mongosh solana_arbitrage_bot

db.flash_trades.find().sort({timestamp: -1}).limit(10)
```

---

### Check Logs

**Backend logs:** Check Command Prompt window

**Frontend logs:** Check browser console (F12)

---

## 🎉 Success! What's Next?

**Week 1: Observation**
- Let bot run 24/7
- Check dashboard 2x daily
- Monitor for crashes
- Track total profit

**Week 2-4: Analysis**
- Calculate profitability
- Review success rate
- Check electricity cost
- Decide on Raspberry Pi

**Month 2+: Upgrade**
- Order Raspberry Pi if profitable
- Migrate when ready
- Free up PC!

---

## 📞 Need Help?

**Common Issues:**
1. Backend window closes immediately → Check MongoDB running
2. Import errors → Reinstall requirements.txt
3. Dashboard blank → Clear browser cache
4. Slow performance → Close other apps

**Resources:**
- Full Guide: PERSONAL_COMPUTER_SETUP_GUIDE.md
- Raspberry Pi Migration: RASPBERRY_PI_SETUP_GUIDE.md
- Algorithm Details: FLASH_LOAN_BOT_ANALYSIS.md

---

**YOU'RE ALL SET! Bot is now running on your Windows PC! 💻**

**Dashboard:** http://localhost:3000
**Cost:** $0
**Next:** Let it run and monitor profits!
