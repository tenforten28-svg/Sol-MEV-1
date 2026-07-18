# 🥧 Complete Raspberry Pi 4 Setup Guide for Flash Loan Bot
## Beginner-Friendly Step-by-Step Tutorial

**Last Updated:** December 31, 2025
**Difficulty:** Beginner-Friendly (No coding experience required!)
**Time Required:** 3-4 hours total setup
**Cost:** ~$150 total

---

## 📦 Part 1: What You Need to Buy

### Essential Hardware (Total: ~$120)

#### 1. Raspberry Pi 4 Model B - 8GB RAM ✅ REQUIRED
**Where to buy:**
- Official: https://www.raspberrypi.com/products/raspberry-pi-4-model-b/
- Amazon: Search "Raspberry Pi 4 8GB"
- Adafruit: https://www.adafruit.com
- CanaKit: Full kits available

**Price:** $75-95
**Why 8GB:** Your bot needs memory for MongoDB database

**⚠️ IMPORTANT:** Get the **8GB version**, not 4GB or 2GB!

---

#### 2. MicroSD Card - 128GB or 256GB ✅ REQUIRED
**Specifications:**
- Size: 128GB minimum (256GB recommended)
- Speed: Class 10 or UHS-I (U1)
- Brand: SanDisk, Samsung, or Kingston

**Where to buy:** Amazon, Best Buy, Walmart
**Price:** $15-25
**Why:** This is your "hard drive" where everything is stored

**Recommended:**
- SanDisk Ultra 128GB ($18)
- Samsung EVO Select 256GB ($25)

---

#### 3. Power Supply - USB-C 5V/3A ✅ REQUIRED
**Official Raspberry Pi Power Supply**
- Output: 5V 3A (15W)
- Connector: USB-C
- Must be official or certified!

**Where to buy:** Same as Raspberry Pi
**Price:** $8-12
**Why:** Cheap chargers cause crashes and corruption

**⚠️ WARNING:** Phone chargers are NOT enough! Use official supply only.

---

#### 4. Ethernet Cable ✅ HIGHLY RECOMMENDED
**Any standard Ethernet cable**
- Length: 3-25 feet (depends on your setup)
- Speed: Cat5e or better

**Where to buy:** Anywhere
**Price:** $5-10
**Why:** More reliable than WiFi for 24/7 operation

**Alternative:** WiFi works but not recommended for trading

---

### Optional but Recommended ($30-60)

#### 5. Raspberry Pi Case 
**With active cooling (fan)**
- Price: $10-15
- Why: Protects Pi and keeps it cool
- Recommended: Flirc case or any with fan

#### 6. Micro HDMI to HDMI Cable
- Price: $8
- Why: Connect to TV/monitor for setup
- Note: Only needed during initial setup

#### 7. USB Keyboard + Mouse
- Price: $15-20 (if you don't have)
- Why: For initial setup only
- Alternative: Borrow from another computer

#### 8. UPS Battery Backup (Optional)
- Price: $40-60
- Why: Protects against power outages
- Recommended for serious trading

---

### What You Don't Need to Buy

❌ **Monitor** - Borrow one for 30 minutes of setup
❌ **Permanent Keyboard/Mouse** - Only for initial setup
❌ **WiFi Adapter** - Built into Raspberry Pi 4
❌ **Extra Storage** - MicroSD is enough

---

## 🛠️ Part 2: Initial Setup (First Time)

### Step 1: Prepare Your Workspace (5 minutes)

**You'll need:**
- [ ] A desk with power outlet nearby
- [ ] Your home WiFi password (write it down!)
- [ ] A computer (Windows, Mac, or Linux)
- [ ] All the hardware from Part 1

**Setup location:**
- Near your router (for Ethernet)
- Good ventilation (Pi will get warm)
- Away from sunlight
- On solid surface (not carpet)

---

### Step 2: Install Raspberry Pi OS (30 minutes)

#### Option A: Using Another Computer (Easier)

**What you'll do:**
1. Download Raspberry Pi Imager software
2. Write OS to MicroSD card
3. Configure WiFi (optional)

**Step-by-step:**

**2.1) Download Raspberry Pi Imager**
- Go to: https://www.raspberrypi.com/software/
- Click "Download for Windows" (or Mac/Linux)
- Install the program

**2.2) Insert MicroSD Card**
- Put MicroSD card in your computer
- You may need a USB adapter (usually included with SD card)

**2.3) Launch Raspberry Pi Imager**
```
1. Click "Choose Device" → Raspberry Pi 4
2. Click "Choose OS" → Raspberry Pi OS (64-bit) - First option
3. Click "Choose Storage" → Your MicroSD card
```

**2.4) Configure Settings (IMPORTANT!)**
```
1. Click the gear icon ⚙️ (bottom right)
2. Set hostname: flashbot
3. Enable SSH ✓
4. Set username: pi
5. Set password: [choose a strong password, write it down!]
6. Configure WiFi (if not using Ethernet):
   - SSID: [your WiFi name]
   - Password: [your WiFi password]
   - Country: US (or your country)
7. Click "Save"
```

**2.5) Write to Card**
```
1. Click "Write"
2. Confirm warning (this erases the card)
3. Wait 5-10 minutes
4. Click "Continue" when done
```

**2.6) Eject and Insert**
```
1. Safely eject MicroSD from computer
2. Insert into Raspberry Pi (bottom slot)
```

---

#### Option B: Using Pre-Configured NOOBS (Slightly easier)

**If you bought a kit with NOOBS pre-installed:**
1. Insert the MicroSD card that came with kit
2. Connect monitor, keyboard, mouse
3. Follow on-screen installation wizard
4. Choose "Raspberry Pi OS (64-bit)"
5. Wait 15 minutes for installation

---

### Step 3: First Boot (15 minutes)

**3.1) Connect Everything**
```
1. Insert MicroSD card (if not already)
2. Connect Ethernet cable (recommended)
   OR ensure WiFi was configured
3. Connect monitor via Micro HDMI
4. Connect keyboard and mouse
5. Connect power supply LAST
```

**3.2) Power On**
```
1. Plug in power supply
2. Green LED will blink (activity)
3. Red LED stays on (power)
4. Wait 1-2 minutes for first boot
```

**3.3) First Login**
```
Screen will show:
raspberrypi login: pi
Password: [the password you set earlier]
```

**3.4) Initial Configuration (if using monitor)**
```
The setup wizard will appear:
1. Set country: United States (or yours)
2. Change password: [if you didn't already]
3. Select WiFi: [if using WiFi]
4. Update software: Yes (wait 10-15 min)
5. Reboot: Yes
```

**3.5) Open Terminal**
```
Top left corner: Click the terminal icon 
(looks like >_)
```

---

### Step 4: Update System (10 minutes)

**In the terminal, type these commands one by one:**

```bash
# Update package list
sudo apt update

# Upgrade all packages (this takes 5-10 minutes)
sudo apt upgrade -y

# Install essential tools
sudo apt install -y git curl wget nano htop

# Reboot
sudo reboot
```

**What this does:**
- Updates all software to latest versions
- Installs tools we'll need later
- Restarts the system

**Wait:** 2 minutes for reboot, then log in again

---

## 🔧 Part 3: Install Bot Dependencies (1 hour)

### Step 5: Install Python and Node.js (15 minutes)

**5.1) Install Python 3.11**
```bash
# Check current Python version
python3 --version
# Should show 3.9 or 3.11

# Install Python development tools
sudo apt install -y python3-pip python3-venv python3-dev

# Verify installation
python3 --version
pip3 --version
```

**5.2) Install Node.js (for dashboard)**
```bash
# Install Node.js 18.x
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Install Yarn (package manager)
sudo npm install -g yarn

# Verify installation
node --version  # Should show v18.x
yarn --version  # Should show 1.22.x
```

---

### Step 6: Install MongoDB (20 minutes)

**6.1) Install MongoDB**
```bash
# Import MongoDB public key
curl -fsSL https://www.mongodb.org/static/pgp/server-6.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-6.0.gpg --dearmor

# Add MongoDB repository
echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-6.0.gpg ] \
http://repo.mongodb.org/apt/debian bullseye/mongodb-org/6.0 main" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-6.0.list

# Update and install
sudo apt update
sudo apt install -y mongodb-org

# Start MongoDB
sudo systemctl start mongod
sudo systemctl enable mongod

# Verify it's running
sudo systemctl status mongod
# Should show "active (running)" in green
```

**6.2) Test MongoDB**
```bash
# Connect to MongoDB
mongosh

# You should see:
# Current Mongosh Log ID: ...
# Connecting to: mongodb://127.0.0.1:27017

# Type "exit" to quit
exit
```

---

### Step 7: Install Docker (Optional, 15 minutes)

**Docker makes deployment easier but uses more resources**

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group
sudo usermod -aG docker pi

# Start Docker
sudo systemctl start docker
sudo systemctl enable docker

# Log out and back in for group changes
exit
```

---

### Step 8: Configure Firewall (10 minutes)

**8.1) Install and enable firewall**
```bash
# Install UFW (Uncomplicated Firewall)
sudo apt install -y ufw

# Allow SSH (so you can access remotely)
sudo ufw allow 22/tcp

# Allow web dashboard
sudo ufw allow 3000/tcp

# Allow API
sudo ufw allow 8001/tcp

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status
```

**You should see:**
```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
3000/tcp                   ALLOW       Anywhere
8001/tcp                   ALLOW       Anywhere
```

---

## 📥 Part 4: Download and Install Bot (30 minutes)

### Step 9: Create Directory Structure

```bash
# Create main directory
mkdir -p ~/solana-bot
cd ~/solana-bot

# Create subdirectories
mkdir -p backend frontend database logs
```

---

### Step 10: Download Bot Code

**Option A: Download from Emergent (I'll help)**

I'll create a download package for you with all files. Then:

```bash
# Download the package (link provided by me)
wget [DOWNLOAD_LINK_HERE] -O bot-package.tar.gz

# Extract
tar -xzf bot-package.tar.gz

# Should see:
# backend/
# frontend/
# database/
# README.md
```

**Option B: Manual File Transfer (if Option A doesn't work)**

Using WinSCP or FileZilla:
1. Connect to Raspberry Pi (IP address, username: pi)
2. Upload files to /home/pi/solana-bot/

---

### Step 11: Install Backend Dependencies

```bash
# Navigate to backend
cd ~/solana-bot/backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# You should see (venv) in your prompt

# Install requirements
pip install -r requirements.txt

# This takes 10-15 minutes on Raspberry Pi
# Be patient!
```

**What's happening:**
- Installing all Python libraries needed
- Downloading dependencies from internet
- Compiling some packages for ARM architecture

---

### Step 12: Install Frontend Dependencies

```bash
# Open new terminal or deactivate venv
deactivate

# Navigate to frontend
cd ~/solana-bot/frontend

# Install dependencies
yarn install

# This takes 5-10 minutes
```

---

### Step 13: Import Database

```bash
# Navigate to database folder
cd ~/solana-bot/database

# Restore MongoDB backup
mongorestore --drop ./

# This imports your historical trading data
```

---

## ⚙️ Part 5: Configuration (30 minutes)

### Step 14: Configure Backend Environment

```bash
# Navigate to backend
cd ~/solana-bot/backend

# Create .env file
nano .env
```

**Type this (or paste from your export):**
```bash
# Database
MONGO_URL=mongodb://localhost:27017/solana_arbitrage_bot
DB_NAME=solana_arbitrage_bot

# Network (SIMULATION MODE - Safe for testing)
SOLANA_NETWORK=mainnet-beta
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com

# Bot Settings
MIN_PROFIT_BPS=20
MAX_LOAN_SIZE=50000
AUTO_EXECUTE=false
SIMULATE_FIRST=true

# Monitoring
LOG_LEVEL=INFO
```

**Save and exit:**
- Press `Ctrl + X`
- Press `Y` to confirm
- Press `Enter` to save

---

### Step 15: Configure Frontend Environment

```bash
# Navigate to frontend
cd ~/solana-bot/frontend

# Create .env file
nano .env
```

**Type this:**
```bash
REACT_APP_BACKEND_URL=http://localhost:8001
```

**Save:** Ctrl + X, Y, Enter

---

### Step 16: Create Startup Scripts

**16.1) Create backend startup script**
```bash
cd ~/solana-bot
nano start-backend.sh
```

**Type:**
```bash
#!/bin/bash
cd /home/pi/solana-bot/backend
source venv/bin/activate
python3 flash_loan_bot_standalone.py &
python3 server.py
```

**Save and make executable:**
```bash
chmod +x start-backend.sh
```

---

**16.2) Create frontend startup script**
```bash
nano start-frontend.sh
```

**Type:**
```bash
#!/bin/bash
cd /home/pi/solana-bot/frontend
yarn start
```

**Save and make executable:**
```bash
chmod +x start-frontend.sh
```

---

## 🚀 Part 6: First Run (Testing)

### Step 17: Start Backend (Test Mode)

```bash
# Start MongoDB (if not running)
sudo systemctl start mongod

# Start backend
cd ~/solana-bot
./start-backend.sh
```

**You should see:**
```
⚡ Flash Loan Monitor initialized
   Target: unlimited trades/day
   Min profit: 20 bps
   Pairs: SOL/USDC, RAY/USDC, ORCA/USDC, JUP/USDC
   
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8001
```

**Keep this terminal open!**

---

### Step 18: Start Frontend (New Terminal)

**Open new terminal:** File → New Window

```bash
cd ~/solana-bot
./start-frontend.sh
```

**You should see:**
```
Compiled successfully!

You can now view frontend in the browser.

  Local:            http://localhost:3000
  On Your Network:  http://192.168.1.XXX:3000
```

**Keep this terminal open too!**

---

### Step 19: Access Dashboard

**19.1) On the Raspberry Pi (with monitor):**
- Open Chromium browser
- Go to: http://localhost:3000
- You should see your Flash Loan Dashboard!

**19.2) From another computer on same network:**
- Find Raspberry Pi IP address:
  ```bash
  hostname -I
  ```
- On other computer, open browser
- Go to: http://[PI_IP_ADDRESS]:3000
- Example: http://192.168.1.150:3000

---

### Step 20: Verify Everything Works

**Checklist:**
- [ ] Dashboard loads
- [ ] Shows "Trades Today" number
- [ ] Shows "Total Net Profit"
- [ ] Shows "Daily Performance History" table
- [ ] Live opportunities updating every 5 seconds
- [ ] Recent trades showing up

**If all checked ✅ - Your bot is working!**

---

## 🔄 Part 7: Auto-Start on Boot (30 minutes)

### Step 21: Create Systemd Services

**Why:** So bot starts automatically if Pi reboots

**21.1) Backend Service**
```bash
sudo nano /etc/systemd/system/flashbot-backend.service
```

**Type:**
```ini
[Unit]
Description=Flash Loan Bot Backend
After=network.target mongod.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/solana-bot/backend
ExecStart=/home/pi/solana-bot/backend/venv/bin/python3 flash_loan_bot_standalone.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Save** (Ctrl+X, Y, Enter)

---

**21.2) API Server Service**
```bash
sudo nano /etc/systemd/system/flashbot-api.service
```

**Type:**
```ini
[Unit]
Description=Flash Loan Bot API Server
After=network.target mongod.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/solana-bot/backend
ExecStart=/home/pi/solana-bot/backend/venv/bin/python3 server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Save**

---

**21.3) Frontend Service**
```bash
sudo nano /etc/systemd/system/flashbot-frontend.service
```

**Type:**
```ini
[Unit]
Description=Flash Loan Bot Frontend
After=network.target flashbot-api.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/solana-bot/frontend
Environment=PORT=3000
ExecStart=/usr/bin/yarn start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Save**

---

**21.4) Enable Services**
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable services (start on boot)
sudo systemctl enable flashbot-backend
sudo systemctl enable flashbot-api
sudo systemctl enable flashbot-frontend

# Start services now
sudo systemctl start flashbot-backend
sudo systemctl start flashbot-api
sudo systemctl start flashbot-frontend

# Check status
sudo systemctl status flashbot-backend
sudo systemctl status flashbot-api
sudo systemctl status flashbot-frontend
```

**All should show "active (running)" in green**

---

### Step 22: Test Auto-Start

```bash
# Reboot
sudo reboot

# Wait 2-3 minutes

# Check services
sudo systemctl status flashbot-backend
sudo systemctl status flashbot-api
sudo systemctl status flashbot-frontend

# Open browser to http://localhost:3000
# Dashboard should load automatically!
```

**✅ If dashboard loads, auto-start is working!**

---

## 🌐 Part 8: Remote Access Setup (30 minutes)

### Step 23: Enable SSH Access

**Already enabled during setup, but verify:**

```bash
# Check if SSH is running
sudo systemctl status ssh

# Should show "active (running)"
```

**Find your Pi's IP address:**
```bash
hostname -I
# Example output: 192.168.1.150
```

---

### Step 24: Connect from Another Computer

**From Windows:**
1. Download PuTTY: https://www.putty.org/
2. Open PuTTY
3. Enter Pi IP address (e.g., 192.168.1.150)
4. Click "Open"
5. Login: pi
6. Password: [your password]

**From Mac/Linux:**
```bash
# Open terminal on your Mac/Linux
ssh pi@192.168.1.150
# Enter password when prompted
```

**✅ You're now controlling the Pi remotely!**

---

### Step 25: Set Up VPN (Optional - Advanced)

**Why:** Access your bot from anywhere (coffee shop, work, etc.)

**Easiest option: Tailscale (Free)**

**On Raspberry Pi:**
```bash
# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Start Tailscale
sudo tailscale up

# Follow the link to authenticate
```

**On your phone/laptop:**
1. Install Tailscale app
2. Login with same account
3. You can now access Pi from anywhere!

**Access dashboard via Tailscale:**
- http://[TAILSCALE_IP]:3000

---

## 📊 Part 9: Monitoring & Maintenance

### Step 26: Check Bot Status

**Quick health check:**
```bash
# Check all services
sudo systemctl status flashbot-*

# View recent logs
sudo journalctl -u flashbot-backend -n 50

# Check MongoDB
sudo systemctl status mongod

# Check system resources
htop
# Press 'q' to quit
```

---

### Step 27: View Logs

**Backend logs:**
```bash
sudo journalctl -u flashbot-backend -f
# Press Ctrl+C to stop
```

**API logs:**
```bash
sudo journalctl -u flashbot-api -f
```

**Frontend logs:**
```bash
sudo journalctl -u flashbot-frontend -f
```

---

### Step 28: Monitor Performance

**Check CPU temperature:**
```bash
vcgencmd measure_temp
# Should be: temp=45.0'C (below 60°C is good)
```

**Check memory usage:**
```bash
free -h
```

**Check disk space:**
```bash
df -h
```

---

### Step 29: Set Up Alerts (Optional)

**Install alert tool:**
```bash
sudo apt install -y mailutils
```

**Create monitoring script:**
```bash
nano ~/check-bot.sh
```

**Type:**
```bash
#!/bin/bash
# Check if bot is running
if ! systemctl is-active --quiet flashbot-backend; then
    echo "⚠️ Bot is down!" | mail -s "Bot Alert" your@email.com
fi

# Check temperature
TEMP=$(vcgencmd measure_temp | cut -d'=' -f2 | cut -d"'" -f1)
if (( $(echo "$TEMP > 70" | bc -l) )); then
    echo "🔥 High temperature: $TEMP°C" | mail -s "Temperature Alert" your@email.com
fi
```

**Make executable:**
```bash
chmod +x ~/check-bot.sh
```

**Add to cron (run every 5 minutes):**
```bash
crontab -e
# Add this line:
*/5 * * * * /home/pi/check-bot.sh
```

---

## 🔧 Part 10: Common Tasks

### Restart Bot
```bash
sudo systemctl restart flashbot-backend
sudo systemctl restart flashbot-api
sudo systemctl restart flashbot-frontend
```

### Stop Bot
```bash
sudo systemctl stop flashbot-backend
sudo systemctl stop flashbot-api
sudo systemctl stop flashbot-frontend
```

### View Trades in Database
```bash
mongosh solana_arbitrage_bot

db.flash_trades.find().sort({timestamp: -1}).limit(5)
```

### Update Bot Code
```bash
cd ~/solana-bot
# Download new version
# Then:
sudo systemctl restart flashbot-*
```

### Backup Database
```bash
mongodump --db=solana_arbitrage_bot --out=~/backup-$(date +%Y%m%d)
```

### Check Network Speed
```bash
curl -s https://raw.githubusercontent.com/sivel/speedtest-cli/master/speedtest.py | python3 -
```

---

## 🚨 Troubleshooting Guide

### Problem: Dashboard won't load

**Solution 1:** Check services
```bash
sudo systemctl status flashbot-frontend
sudo systemctl status flashbot-api
```

**Solution 2:** Check firewall
```bash
sudo ufw status
# Should show 3000/tcp and 8001/tcp allowed
```

**Solution 3:** Restart everything
```bash
sudo systemctl restart flashbot-*
```

---

### Problem: Bot not executing trades

**Solution 1:** Check logs
```bash
sudo journalctl -u flashbot-backend -n 100
```

**Solution 2:** Check MongoDB
```bash
sudo systemctl status mongod
# Should be active
```

**Solution 3:** Check network
```bash
ping -c 4 google.com
# Should get responses
```

---

### Problem: High temperature

**Solution 1:** Add cooling
- Buy case with fan
- Or USB fan pointed at Pi

**Solution 2:** Reduce load
```bash
# Stop frontend if not needed
sudo systemctl stop flashbot-frontend
```

**Solution 3:** Check environment
- Move away from heat sources
- Ensure good airflow

---

### Problem: MicroSD card corruption

**Prevention:**
```bash
# Install log2ram (reduces SD writes)
curl -L https://github.com/azlux/log2ram/archive/master.tar.gz | tar zxf -
cd log2ram-master
sudo ./install.sh
sudo reboot
```

**Recovery:**
- Backup important data regularly
- Keep spare MicroSD card with OS

---

### Problem: Can't connect via SSH

**Solution 1:** Find IP address
- Login to router admin page
- Look for "flashbot" in connected devices

**Solution 2:** Connect monitor
- Login directly on Pi
- Run: `hostname -I`

**Solution 3:** Check SSH status
```bash
sudo systemctl status ssh
sudo systemctl start ssh
```

---

## 📱 Part 11: Mobile Access

### Android/iOS Dashboard Access

**Option 1: Tailscale** (Recommended)
1. Install Tailscale app
2. Access http://[TAILSCALE_IP]:3000

**Option 2: Port Forwarding** (Advanced)
1. Login to router
2. Forward port 3000 to Pi IP
3. Access http://[YOUR_PUBLIC_IP]:3000
⚠️ Security risk - use HTTPS and authentication!

**Option 3: Termux (Android) or iSH (iOS)**
- Install SSH client app
- Connect to Pi IP
- Monitor via command line

---

## 📈 Part 12: Performance Optimization

### Optimize Raspberry Pi

**Increase swap space:**
```bash
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile
# Change: CONF_SWAPSIZE=2048
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

**Disable unnecessary services:**
```bash
sudo systemctl disable bluetooth
sudo systemctl disable avahi-daemon
```

**Overclock (optional, voids warranty):**
```bash
sudo nano /boot/config.txt
# Add:
# over_voltage=2
# arm_freq=1750
sudo reboot
```

---

## 🎓 Part 13: Learning Resources

### Useful Commands

**System Info:**
```bash
cat /proc/cpuinfo          # CPU info
free -h                    # Memory usage
df -h                      # Disk usage
top                        # Real-time processes
htop                       # Better process viewer
```

**Networking:**
```bash
ifconfig                   # Network interfaces
ping google.com           # Test connectivity
netstat -tulpn            # Show open ports
```

**Services:**
```bash
sudo systemctl list-units --type=service  # All services
sudo journalctl -xe                       # System logs
```

---

### Further Reading

**Raspberry Pi:**
- Official docs: https://www.raspberrypi.com/documentation/
- Forums: https://forums.raspberrypi.com/

**Linux Basics:**
- Command line tutorial: https://ubuntu.com/tutorials/command-line-for-beginners
- Bash guide: https://www.learnshell.org/

**MongoDB:**
- Tutorial: https://www.mongodb.com/docs/manual/tutorial/

---

## 🎯 Part 14: Next Steps

### Week 1: Testing (Current)
- [ ] Complete hardware setup
- [ ] Install all software
- [ ] Verify bot runs in simulation
- [ ] Monitor for 7 days

### Week 2: Optimization
- [ ] Add more trading pairs
- [ ] Optimize settings
- [ ] Set up monitoring alerts
- [ ] Test remote access

### Week 3: Preparation
- [ ] Read deployment checklist
- [ ] Test on devnet
- [ ] Get premium RPC provider
- [ ] Fund wallet

### Week 4: Go Live (Your Choice)
- [ ] Switch to production mode
- [ ] Start with small trades
- [ ] Monitor 24/7
- [ ] Scale gradually

---

## ✅ Final Checklist

**Hardware Setup:**
- [x] Raspberry Pi 4 - 8GB
- [x] MicroSD Card - 128GB+
- [x] Power Supply - Official
- [x] Ethernet Cable
- [x] Case with cooling

**Software Installation:**
- [x] Raspberry Pi OS installed
- [x] Python 3.11 working
- [x] Node.js 18 working
- [x] MongoDB running
- [x] Bot code deployed

**Configuration:**
- [x] Backend .env configured
- [x] Frontend .env configured
- [x] Firewall configured
- [x] Auto-start enabled

**Testing:**
- [x] Dashboard loads
- [x] Bot executes trades (simulation)
- [x] Database saves trades
- [x] Remote access works

**You're Ready! 🎉**

---

**Questions? Issues?**
Refer to troubleshooting section or ask for help!

**Remember:**
- Start in simulation mode
- Test thoroughly before using real money
- Monitor constantly in first week
- Backup regularly

**Your bot is now running 24/7 on your private Raspberry Pi! 🥧**

Total Cost: ~$120-150
Total Time: 3-4 hours
Privacy Level: MAXIMUM 🔒🔒
