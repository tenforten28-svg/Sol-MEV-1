# 🛒 Raspberry Pi Bot - Shopping List & Quick Reference

## Shopping List (Copy This!)

### Essential Items - Total: ~$120

**1. Raspberry Pi 4 Model B - 8GB RAM**
- Quantity: 1
- Price: $75-95
- Where: Amazon, Adafruit, CanaKit
- Search: "Raspberry Pi 4 8GB"
- ⚠️ MUST be 8GB version!

**2. MicroSD Card - 128GB or 256GB**
- Quantity: 1
- Price: $15-25
- Where: Amazon, Best Buy
- Brand: SanDisk Ultra or Samsung EVO
- Speed: Class 10 minimum

**3. Official Power Supply - USB-C 5V/3A**
- Quantity: 1
- Price: $8-12
- Where: Same as Pi
- ⚠️ Must be official or approved!

**4. Ethernet Cable - Cat5e or better**
- Quantity: 1
- Price: $5-10
- Length: Based on setup
- Where: Anywhere

### Optional Items - Total: ~$30-60

**5. Raspberry Pi Case with Fan**
- Price: $10-15
- Recommended: Flirc or any with active cooling

**6. Micro HDMI to HDMI Cable**
- Price: $8
- Only for initial setup

**7. USB Keyboard + Mouse**
- Price: $15-20
- Only if you don't have extras

**8. UPS Battery Backup**
- Price: $40-60
- Brand: APC or CyberPower
- Important for 24/7 trading

---

## Quick Start Commands

### Check Everything is Working
```bash
# Check services
sudo systemctl status flashbot-backend
sudo systemctl status flashbot-api
sudo systemctl status flashbot-frontend

# View logs
sudo journalctl -u flashbot-backend -n 50

# Check temperature
vcgencmd measure_temp

# Check memory
free -h
```

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

### Start Bot
```bash
sudo systemctl start flashbot-backend
sudo systemctl start flashbot-api
sudo systemctl start flashbot-frontend
```

### View Recent Trades
```bash
mongosh solana_arbitrage_bot
db.flash_trades.find().sort({timestamp: -1}).limit(10)
exit
```

### Backup Database
```bash
mongodump --db=solana_arbitrage_bot --out=~/backup-$(date +%Y%m%d)
```

### Update System
```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

### Check Disk Space
```bash
df -h
```

### Check Network
```bash
ping -c 4 google.com
hostname -I
```

---

## Common Issues - Quick Fixes

### Dashboard Won't Load
```bash
sudo systemctl restart flashbot-frontend
sudo systemctl restart flashbot-api
```

### Bot Not Trading
```bash
sudo journalctl -u flashbot-backend -n 100
sudo systemctl restart flashbot-backend
```

### MongoDB Not Working
```bash
sudo systemctl status mongod
sudo systemctl restart mongod
```

### Pi Running Hot
- Check: `vcgencmd measure_temp`
- If >70°C: Add cooling or reduce load
- Stop frontend: `sudo systemctl stop flashbot-frontend`

### Can't SSH Connect
- Find IP: Login with monitor, run `hostname -I`
- Check SSH: `sudo systemctl status ssh`

---

## Access URLs

**On Raspberry Pi (with monitor):**
- Dashboard: http://localhost:3000
- API: http://localhost:8001/api/flash/stats

**From another computer (same network):**
- Dashboard: http://[PI_IP]:3000
- API: http://[PI_IP]:8001/api/flash/stats
- SSH: ssh pi@[PI_IP]

**Example (if Pi IP is 192.168.1.150):**
- Dashboard: http://192.168.1.150:3000
- SSH: ssh pi@192.168.1.150

---

## Important Files & Locations

```
/home/pi/solana-bot/                  # Main bot directory
├── backend/                          # Python bot code
│   ├── flash_loan_bot_standalone.py  # Main bot
│   ├── server.py                     # API server
│   ├── .env                          # Configuration
│   └── venv/                         # Python environment
├── frontend/                         # React dashboard
│   ├── src/                          # Dashboard code
│   └── .env                          # Frontend config
└── database/                         # MongoDB backups

/var/log/                             # System logs
/etc/systemd/system/                  # Service files
```

---

## Performance Benchmarks

**Expected on Raspberry Pi 4 (8GB):**
- Trades/hour: 50-100
- CPU usage: 20-40%
- Memory usage: 2-4GB
- Temperature: 45-60°C (with cooling)
- Power consumption: ~15W
- Boot time: 30-60 seconds

**Network Requirements:**
- Minimum: 5 Mbps download, 1 Mbps upload
- Recommended: 25 Mbps download, 5 Mbps upload
- Latency: <100ms to Solana RPC

---

## Maintenance Schedule

**Daily:**
- Check dashboard for trades
- Verify bot is running
- Monitor temperature

**Weekly:**
- Review trade performance
- Check disk space
- Update system packages
- Backup database

**Monthly:**
- Deep clean logs
- Check for software updates
- Test failover procedures
- Verify backup integrity

---

## Emergency Contacts

**Raspberry Pi Support:**
- Forums: https://forums.raspberrypi.com/
- Discord: https://discord.gg/raspberry-pi

**Bot Issues:**
- Refer to full guide: RASPBERRY_PI_SETUP_GUIDE.md
- Check logs: `sudo journalctl -u flashbot-backend`

**Solana Issues:**
- Status: https://status.solana.com/
- Discord: https://discord.gg/solana

---

## Power Consumption & Costs

**Raspberry Pi 4:**
- Idle: 3W
- Under load: 8W
- Max: 15W

**Monthly Electricity Cost:**
- Average use: 10W × 24h × 30d = 7.2 kWh/month
- At $0.12/kWh: ~$0.86/month
- At $0.20/kWh: ~$1.44/month

**Very affordable for 24/7 operation!**

---

## Security Reminders

✅ **DO:**
- Keep system updated
- Use strong passwords
- Enable firewall
- Backup regularly
- Use SSH keys
- Monitor logs

❌ **DON'T:**
- Expose to public internet without VPN
- Store private keys in plain text
- Use default passwords
- Disable firewall
- Skip backups
- Ignore security updates

---

## Quick Stats Check

**One command to check everything:**
```bash
echo "=== System Status ===" && \
echo "Services:" && sudo systemctl is-active flashbot-* && \
echo "Temperature: $(vcgencmd measure_temp)" && \
echo "Memory:" && free -h | grep Mem && \
echo "Disk:" && df -h / | tail -1 && \
echo "Network:" && hostname -I && \
echo "Trades Today:" && mongosh solana_arbitrage_bot --quiet --eval "db.flash_trades.countDocuments({timestamp: {\$gte: new Date(new Date().setHours(0,0,0,0))}})"
```

---

## Upgrade Path

**Future Improvements:**

**Month 1:** Basic Operation
- Just run and monitor

**Month 2:** Optimization
- Add more trading pairs
- Fine-tune parameters
- Improve monitoring

**Month 3:** Scaling
- Consider upgrading to Mini PC
- Add redundancy
- Implement advanced strategies

**Month 6+:** Production
- Move to mainnet
- Scale up capital
- Professional setup

---

## Cost Comparison

**1 Year Total Cost:**

| Option | Hardware | Hosting | Electricity | Total |
|--------|----------|---------|-------------|-------|
| Raspberry Pi | $120 | $0 | $12 | **$132** |
| VPS | $0 | $288 | $0 | $288 |
| Emergent | $0 | $??? | $0 | ??? |

**Winner: Raspberry Pi** (saves $156+/year)

---

**Print this page for quick reference! 📄**
