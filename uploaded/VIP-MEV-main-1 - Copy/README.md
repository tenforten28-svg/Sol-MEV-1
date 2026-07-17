# Solana MEV Arbitrage Bot

A high-performance arbitrage bot for the Solana ecosystem that monitors price discrepancies across Serum, Raydium, and Orca DEXs to identify and execute profitable arbitrage opportunities.

## Features

### Core Functionality
- **Multi-DEX Monitoring**: Real-time price tracking across Serum (order book), Raydium (AMM), and Orca (AMM)
- **Arbitrage Detection**: Intelligent algorithm to identify profitable price discrepancies
- **Simulation Mode**: Test trading strategies without risking real funds
- **Real-time Dashboard**: Beautiful web interface with live opportunity feeds
- **Trade Execution**: Automated or manual trade execution with configurable parameters
- **WebSocket Updates**: Live data streaming for instant opportunity alerts

### Technical Features
- **FastAPI Backend**: High-performance async API server
- **MongoDB Database**: Persistent storage for opportunities, trades, and configuration
- **React Frontend**: Modern, responsive dashboard with real-time updates
- **Solana Integration**: Native Solana blockchain integration using solana-py

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React)                         │
│  - Dashboard with real-time data visualization              │
│  - Opportunity monitor & trade history                      │
│  - Configuration panel                                       │
└────────────────────┬────────────────────────────────────────┘
                     │ WebSocket + REST API
┌────────────────────▼────────────────────────────────────────┐
│                  Backend (FastAPI)                           │
│  - REST API endpoints                                        │
│  - WebSocket server for real-time updates                   │
│  - Background arbitrage monitoring task                      │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│              Solana Blockchain (Devnet)                      │
│  - Serum DEX (Order Book)                                   │
│  - Raydium DEX (AMM)                                        │
│  - Orca DEX (AMM)                                           │
└─────────────────────────────────────────────────────────────┘
```

## Setup Instructions

### Prerequisites
- Node.js >= 16
- Python >= 3.11
- MongoDB
- Solana wallet keypair
- QuickNode RPC endpoint (optional but recommended)

### Backend Setup

1. **Navigate to backend directory**:
```bash
cd /app/backend
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Configure environment variables** in `/app/backend/.env`:
```env
# Database
MONGO_URL="mongodb://localhost:27017"
DB_NAME="solana_arbitrage_bot"
CORS_ORIGINS="*"

# Solana Configuration
SOLANA_RPC_URL="https://api.devnet.solana.com"
SOLANA_PRIVATE_KEY="your_wallet_private_key_here"
QUICKNODE_RPC_URL="your_quicknode_endpoint_here"

# Bot Configuration
MIN_PROFIT_THRESHOLD=0.001
MAX_TRADE_SIZE=0.1
SIMULATION_MODE=true
```

4. **Start the backend**:
```bash
uvicorn server:app --host 0.0.0.0 --port 8001
```

### Frontend Setup

1. **Navigate to frontend directory**:
```bash
cd /app/frontend
```

2. **Install dependencies**:
```bash
yarn install
```

3. **Configure environment variables** in `/app/frontend/.env`:
```env
REACT_APP_BACKEND_URL=http://localhost:8001
```

4. **Start the frontend**:
```bash
yarn start
```

5. **Access the dashboard**:
Open your browser and navigate to `http://localhost:3000`

## Configuration

### Bot Settings

The bot can be configured through the dashboard or by directly updating the database. Key configuration options:

- **Simulation Mode**: When enabled, trades are executed in simulation only (no real transactions)
- **Min Profit Threshold**: Minimum profit percentage required to execute a trade (default: 0.001%)
- **Max Trade Size**: Maximum amount per arbitrage trade (default: 0.1 SOL)
- **Enabled DEXs**: Select which DEXs to monitor (Serum, Raydium, Orca)
- **Monitored Pairs**: Token pairs to watch for arbitrage opportunities

### Wallet Setup

1. Create a Solana wallet for devnet:
```bash
solana-keygen new --outfile ~/solana-wallet.json
```

2. Get devnet SOL:
```bash
solana airdrop 2 --url devnet
```

3. Copy your private key to the `.env` file

### QuickNode Setup (Recommended)

For faster and more reliable RPC access:

1. Sign up at [QuickNode.com](https://quicknode.com)
2. Create a Solana Devnet endpoint
3. Copy the HTTP URL to `QUICKNODE_RPC_URL` in `.env`

## API Endpoints

### Opportunities
- `GET /api/opportunities` - Get current arbitrage opportunities
- Query params: `limit` (default: 50)

### Trades
- `GET /api/trades` - Get trade execution history
- `POST /api/execute` - Execute a trade
- Query params: `limit` (default: 100)

### Configuration
- `GET /api/config` - Get bot configuration
- `POST /api/config` - Update bot configuration

### Stats
- `GET /api/stats` - Get bot statistics (opportunities, trades, profit)

### WebSocket
- `WS /api/ws` - Real-time updates for opportunities and trades

## Usage

### Monitor Opportunities

1. Open the dashboard
2. Navigate to the "Live Opportunities" tab
3. View real-time arbitrage opportunities with:
   - Token pair
   - Buy/sell DEXs
   - Prices on each DEX
   - Profit percentage and amount
   - Execute button

### Execute Trades

**Manual Execution:**
1. Find an opportunity you want to execute
2. Click the "Execute" button
3. Trade will be executed based on current configuration (simulation or live)

**Automated Execution:**
1. Go to Configuration
2. Enable "Auto Execute"
3. Bot will automatically execute trades above the profit threshold

### View Trade History

1. Navigate to "Trade History" tab
2. View all executed trades with:
   - Token pair
   - Route (DEX → DEX)
   - Profit/loss
   - Status (simulated, completed, failed)
   - Timestamp

### Simulation Mode

**Testing with Simulation Mode:**
1. Ensure `SIMULATION_MODE=true` in configuration
2. Execute trades as normal
3. All trades will be marked as "simulated"
4. No real blockchain transactions occur

**Go Live:**
1. Thoroughly test in simulation mode
2. Set `SIMULATION_MODE=false`
3. Ensure sufficient SOL balance in wallet
4. Monitor first few trades closely

## Development

### Project Structure

```
/app/
├── backend/
│   ├── server.py           # Main FastAPI application
│   ├── requirements.txt    # Python dependencies
│   └── .env               # Backend configuration
├── frontend/
│   ├── src/
│   │   ├── App.js         # Main React component
│   │   ├── App.css        # Global styles
│   │   └── components/
│   │       └── Dashboard.js  # Main dashboard component
│   ├── package.json       # Node dependencies
│   └── .env              # Frontend configuration
└── README.md             # This file
```

### Adding New DEXs

To add support for additional DEXs:

1. Update the monitoring logic in `server.py`
2. Add DEX-specific price fetching functions
3. Update the `enabled_dexes` configuration
4. Test thoroughly in simulation mode

### Customizing Strategies

The bot uses a simple arbitrage strategy. To customize:

1. Modify the `monitor_arbitrage()` function in `server.py`
2. Implement your own profit calculation logic
3. Add additional filters or conditions
4. Update the `ArbitrageOpportunity` model if needed

## Production Deployment

### Security Considerations

⚠️ **Important Security Notes:**

1. **Never commit private keys**: Use environment variables only
2. **Secure your RPC endpoint**: Use authenticated endpoints in production
3. **Rate limiting**: Implement rate limiting on API endpoints
4. **Wallet security**: Use hardware wallets for large amounts
5. **HTTPS**: Always use HTTPS in production
6. **CORS**: Configure proper CORS origins (not "*")

### Switching to Mainnet

1. Update `SOLANA_RPC_URL` to mainnet endpoint
2. Use a mainnet wallet with sufficient balance
3. Start with small trade sizes
4. Monitor gas fees and slippage
5. Set appropriate profit thresholds accounting for fees

### Monitoring & Alerts

Consider setting up:
- Error logging (e.g., Sentry)
- Performance monitoring (e.g., Datadog)
- Alert notifications (e.g., Telegram, Discord)
- Database backups

## Troubleshooting

### Common Issues

**Bot not finding opportunities:**
- Check RPC connection
- Verify DEX endpoints are accessible
- Ensure monitored pairs are valid
- Lower the profit threshold for testing

**Trades failing:**
- Check wallet balance
- Verify private key is correct
- Ensure sufficient SOL for gas fees
- Check slippage settings

**WebSocket disconnecting:**
- Check network stability
- Verify CORS configuration
- Increase timeout settings

**Database errors:**
- Ensure MongoDB is running
- Check connection string
- Verify database permissions

## Performance Optimization

### For High-Frequency Trading

1. **Use dedicated RPC endpoint**: QuickNode or Helius
2. **Optimize database queries**: Add indexes for frequently queried fields
3. **Connection pooling**: Configure MongoDB connection pool
4. **Caching**: Implement Redis for frequently accessed data
5. **Load balancing**: Use multiple backend instances

### Network Optimization

- Use RPC endpoints geographically close to you
- Enable connection keep-alive
- Batch blockchain requests when possible
- Implement retry logic with exponential backoff

## License

MIT License - Feel free to use and modify for your own projects.

## Disclaimer

⚠️ **Trading cryptocurrencies involves substantial risk of loss. This bot is provided for educational purposes only. Always test thoroughly in simulation mode before risking real funds. The developers are not responsible for any financial losses incurred while using this software.**

## Roadmap

Future enhancements planned:
- [ ] Support for additional Solana DEXs (Jupiter, Saber)
- [ ] Advanced trading strategies (multi-hop arbitrage)
- [ ] Machine learning-based opportunity prediction
- [ ] Mobile app for monitoring
- [ ] Telegram/Discord bot integration
- [ ] Historical performance analytics
- [ ] Gas fee optimization
- [ ] Slippage protection
- [ ] Multi-wallet support

---

Built with ❤️ for the Solana ecosystem
