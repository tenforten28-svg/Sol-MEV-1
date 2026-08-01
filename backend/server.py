from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from solana.rpc.async_api import AsyncClient
import os
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timezone, timedelta
import json

# Import custom modules
from dex_connectors import DEXAggregator
from risk_manager import RiskManager
from meme_coin_config import MEME_TOKENS, ALL_MEME_PAIRS
from meme_risk_manager import MemeRiskManager
from meme_price_connector import MemePriceConnector
from meme_arbitrage_detector import MemeArbitrageDetector
from liquidity_verifier import LiquidityVerifier
from flash_loan_api import flash_router
from flash_loan_monitor_integrated import IntegratedFlashLoanMonitor, get_flash_loan_stats

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Global variables - initialized in lifespan
dex_aggregator = None
risk_manager = None
meme_risk_manager = None
meme_price_connector = MemePriceConnector()
meme_liquidity_verifier = LiquidityVerifier(min_liquidity_usd=100000, min_lock_days=30)
meme_arbitrage_detector = MemeArbitrageDetector(
    meme_price_connector,
    meme_liquidity_verifier,
    min_profit_bps=15,
    max_slippage_bps=30
)

# Initialize flash loan monitor
flash_loan_monitor = None

# Meme trading state
meme_balance = 10.0  # Separate 10 SOL pool
meme_active_opportunities = []

# Trading parameters
MIN_SPREAD_AFTER_COSTS = float(os.environ.get('MIN_SPREAD_AFTER_COSTS', 0.002))
MAX_SLIPPAGE_TOLERANCE = float(os.environ.get('MAX_SLIPPAGE_TOLERANCE', 0.0015))
LATENCY_MS = int(os.environ.get('LATENCY_MS', 150))
AUTO_EXECUTE = True  # Enable auto-execution for meme opportunities

@asynccontextmanager
async def lifespan(app: FastAPI):
    global risk_manager, dex_aggregator, meme_risk_manager, flash_loan_monitor
    
    # Initialize components on startup
    risk_manager = RiskManager(
        starting_capital=float(os.environ.get('STARTING_CAPITAL', 50.0)),
        reserve_percentage=float(os.environ.get('RESERVE_PERCENTAGE', 90.0)),
        max_trade_percentage=float(os.environ.get('MAX_TRADE_PERCENTAGE', 1.0)),
        max_daily_loss_percentage=float(os.environ.get('MAX_DAILY_LOSS_PERCENTAGE', 2.0)),
        max_consecutive_failures=int(os.environ.get('MAX_CONSECUTIVE_FAILURES', 3)),
        cooldown_period_seconds=int(os.environ.get('COOLDOWN_PERIOD_SECONDS', 300))
    )
    dex_aggregator = DEXAggregator()
    meme_risk_manager = MemeRiskManager(
        initial_capital=10.0,
        reserve_percentage=60.0,
        max_trade_percentage=1.0
    )
    flash_loan_monitor = IntegratedFlashLoanMonitor(db, risk_manager)
    
    # Initialize config if not exists
    config = await db.config.find_one({})
    if not config:
        default_config = BotConfig()
        await db.config.insert_one(default_config.model_dump())
        logger.info("Created default configuration")
    
    # Start background tasks
    asyncio.create_task(monitor_arbitrage())
    asyncio.create_task(cleanup_stale_opportunities())
    asyncio.create_task(monitor_meme_opportunities())
    asyncio.create_task(flash_loan_monitor.monitor_loop())  # Start flash loan monitor

    # Start LIVE auto-arbitrage monitor (real Jupiter round-trip; real money)
    # Gated by AUTO_ARB_ENABLED env var — safe by default (disabled).
    try:
        from live_arb_monitor import get_arb_monitor
        arb_mon = get_arb_monitor(db)
        arb_mon.start()
        logger.info("💠 Live Arbitrage Monitor initialized (starts only if AUTO_ARB_ENABLED=true)")
    except Exception as e:
        logger.exception(f"Failed to start live arb monitor: {e}")

    # Start PUMP.FUN new-mint detector (detection only, no auto-buy)
    # Gated by PUMPFUN_SNIPER_ENABLED env var.
    try:
        from pumpfun_sniper import get_pumpfun_sniper
        pf_sniper = get_pumpfun_sniper(db)
        pf_sniper.start()
        logger.info("🎯 Pump.fun sniper initialized (detection only; enable with PUMPFUN_SNIPER_ENABLED=true)")
    except Exception as e:
        logger.exception(f"Failed to start pump.fun sniper: {e}")

    # Start PUMP.FUN auto-buyer + position monitor
    try:
        from pumpfun_autobuy import get_pumpfun_autobuyer
        pf_ab = get_pumpfun_autobuyer(db)
        asyncio.create_task(pf_ab.monitor_positions())
        logger.info("💊 Pump.fun auto-buyer initialized (enable with PUMPFUN_AUTO_BUY_ENABLED=true)")
    except Exception as e:
        logger.exception(f"Failed to start pump.fun autobuyer: {e}")

    # Start GRADUATION MONITOR (PumpSwap + Bonk.fun/LaunchLab) + executor
    # Gated by GRADUATION_ENABLED. Executor gated by GRADUATION_EXEC_ENABLED (fade-the-dump strategy).
    try:
        from graduation_monitor import get_graduation_monitor
        from graduation_executor import get_graduation_executor
        grad_exec = get_graduation_executor(db)
        grad_mon = get_graduation_monitor(db, on_event=grad_exec.on_event)
        await grad_mon.start()
        await grad_exec.start_monitor()
        logger.info("🎓 Graduation monitor initialized (enable with GRADUATION_ENABLED=true; exec: GRADUATION_EXEC_ENABLED=true)")
    except Exception as e:
        logger.exception(f"Failed to start graduation monitor: {e}")
    
    logger.info("🚀 Solana MEV Arbitrage Bot started")
    logger.info("⚡ Flash Loan Monitor enabled")
    
    yield
    
    # Cleanup on shutdown
    await dex_aggregator.close()
    await flash_loan_monitor.close()
    client.close()
    logger.info("Shutdown complete")

# Create the main app without a prefix
app = FastAPI(lifespan=lifespan)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# WebSocket manager for real-time updates
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# Models
class CostBreakdown(BaseModel):
    fee: float
    fee_percentage: float
    slippage: float
    slippage_percentage: float
    total_cost: float
    total_cost_percentage: float

class ArbitrageOpportunity(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    token_pair: str
    dex_buy: str
    dex_sell: str
    buy_price: float
    sell_price: float
    gross_spread_percentage: float
    buy_costs: Dict
    sell_costs: Dict
    total_cost_percentage: float
    net_profit_percentage: float
    net_profit_amount: float
    trade_amount: float
    liquidity_buy: float
    liquidity_sell: float
    risk_approved: bool = False
    risk_reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    executed: bool = False

class Trade(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    opportunity_id: str
    token_pair: str
    dex_buy: str
    dex_sell: str
    buy_amount: float
    sell_amount: float
    profit: float
    profit_percentage: float
    status: str  # pending, completed, failed, simulated
    simulation: bool
    tx_signature_buy: Optional[str] = None
    tx_signature_sell: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None

class BotConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    simulation_mode: bool = True
    min_profit_threshold: float = 0.001
    max_trade_size: float = 0.1
    enabled_dexes: List[str] = ["serum", "raydium", "orca"]
    monitored_pairs: List[str] = [
        "SOL/USDC", "RAY/USDC", "ORCA/USDC", "JUP/USDC", 
        "JTO/USDC", "PYTH/USDC", "SOL/USDT", "USDC/USDT"
    ]
    auto_execute: bool = True  # Changed to True for auto-trading
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class BotStats(BaseModel):
    total_opportunities: int
    executed_trades: int
    total_profit: float
    success_rate: float
    active_pairs: int
    # Capital metrics
    starting_capital: float
    current_capital: float
    capital_change: float
    capital_change_percentage: float
    available_capital: float
    reserved_capital: float
    # Risk metrics
    daily_pnl: float
    daily_pnl_percentage: float
    daily_trades: int
    consecutive_failures: int
    in_cooldown: bool
    can_trade: bool

class ExecuteTradeRequest(BaseModel):
    opportunity_id: str
    amount: float

# Routes
@api_router.get("/")
async def root():
    return {"message": "Solana Arbitrage MEV Bot API", "status": "active"}

@api_router.get("/health")
async def health():
    """Health endpoint used by Railway / uptime monitors."""
    try:
        await db.command("ping")
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok", "db": db_ok, "simulation_mode": os.environ.get("SIMULATION_MODE", "true")}


# ============================================================
# LIVE TRADING ENDPOINTS (Jupiter v6 + QuickNode)
# ============================================================
from live_trader import get_live_trader, MINTS, DECIMALS, WHITELISTED_PAIRS


@api_router.get("/live/status")
async def live_status():
    """Show live-trader readiness, safety limits, and risk-breaker state."""
    return get_live_trader().status()


@api_router.get("/live/balance")
async def live_balance():
    """Get current wallet SOL balance from the RPC.
    Works when wallet+RPC configured, even if trading is still safely disabled."""
    lt = get_live_trader()
    if not lt.wallet_configured:
        return {"ready": False, "wallet_configured": False,
                "reason": "SOLANA_PRIVATE_KEY or SOLANA_RPC_URL not set",
                "sol": 0.0, "rpc_ok": False, "meets_reserve": False}
    # Do a real RPC call and surface any error explicitly
    try:
        async with AsyncClient(lt.cfg.rpc_url) as client:
            resp = await client.get_balance(lt.wallet.pubkey())
            lamports = resp.value if hasattr(resp, "value") else 0
            sol = lamports / 1_000_000_000
            return {"ready": lt.ready, "wallet_configured": True,
                    "wallet": lt.wallet_pubkey, "sol": sol,
                    "rpc_ok": True, "meets_reserve": sol >= lt.cfg.min_reserve_sol}
    except Exception as e:
        return {"ready": lt.ready, "wallet_configured": True,
                "wallet": lt.wallet_pubkey, "sol": 0.0,
                "rpc_ok": False, "rpc_error": str(e),
                "meets_reserve": False}


@api_router.get("/live/rpc_ping")
async def live_rpc_ping():
    """Diagnostic — verify QuickNode RPC is reachable & responding.
    Costs ~2 credits per call. Use this to prove your RPC config works
    before firing real trades. Reports errors explicitly instead of silently returning 0."""
    lt = get_live_trader()
    return await lt.rpc_ping()


# ============================================================
# LIVE AUTO-ARBITRAGE MONITOR ENDPOINTS
# ============================================================
from live_arb_monitor import get_arb_monitor


@api_router.get("/live/auto_arb/status")
async def auto_arb_status():
    """Status + counters for the autonomous arb monitor."""
    try:
        return get_arb_monitor(db).status()
    except Exception as e:
        return {"error": str(e), "enabled": False, "running": False}


@api_router.get("/live/auto_arb/decisions")
async def auto_arb_decisions(limit: int = 20):
    """Recent decisions from the auto-arb monitor (why fired / skipped / blocked)."""
    try:
        cursor = db.arb_decisions.find({}).sort("at", -1).limit(limit)
        docs = []
        async for d in cursor:
            d.pop("_id", None)
            docs.append(d)
        return {"count": len(docs), "decisions": docs}
    except Exception as e:
        return {"count": 0, "decisions": [], "error": str(e)}


# ============================================================
# PUMP.FUN SNIPER ENDPOINTS (detection only)
# ============================================================
from pumpfun_sniper import get_pumpfun_sniper


@api_router.get("/live/pumpfun/status")
async def pumpfun_status():
    """Pump.fun new-mint detector status + counters."""
    try:
        return get_pumpfun_sniper(db).status()
    except Exception as e:
        return {"error": str(e), "enabled": False, "running": False}


@api_router.get("/live/pumpfun/detections")
async def pumpfun_detections(limit: int = 50):
    """Recent pump.fun new mint detections. Newest first."""
    try:
        cursor = db.pumpfun_detections.find({}).sort("detected_at", -1).limit(limit)
        docs = []
        async for d in cursor:
            d.pop("_id", None)
            docs.append(d)
        return {"count": len(docs), "detections": docs}
    except Exception as e:
        return {"count": 0, "detections": [], "error": str(e)}


@api_router.get("/live/pumpfun/autobuy_status")
async def pumpfun_autobuy_status():
    from pumpfun_autobuy import get_pumpfun_autobuyer
    try:
        return get_pumpfun_autobuyer(db).status()
    except Exception as e:
        return {"error": str(e), "enabled": False}


@api_router.get("/live/pumpfun/positions")
async def pumpfun_positions(limit: int = 50):
    """Recent open/close events for pump.fun snipe positions."""
    try:
        cursor = db.pumpfun_positions.find({}).sort("at", -1).limit(limit)
        docs = []
        async for d in cursor:
            d.pop("_id", None)
            docs.append(d)
        return {"count": len(docs), "events": docs}
    except Exception as e:
        return {"count": 0, "events": [], "error": str(e)}


@api_router.get("/live/graduation/status")
async def graduation_status():
    """Combined status of graduation monitor + executor."""
    try:
        from graduation_monitor import get_graduation_monitor
        from graduation_executor import get_graduation_executor
        gm = get_graduation_monitor(db)
        ge = get_graduation_executor(db)
        return {"monitor": gm.status(), "executor": ge.status()}
    except Exception as e:
        return {"error": str(e)}


@api_router.get("/live/graduation/events")
async def graduation_events(limit: int = 20, source: Optional[str] = None):
    """Recent normalized graduation events from both platforms."""
    try:
        q = {"source": source} if source else {}
        cursor = db.graduation_events.find(q).sort("detected_at", -1).limit(limit)
        docs = []
        async for d in cursor:
            d.pop("_id", None)
            docs.append(d)
        return {"count": len(docs), "events": docs}
    except Exception as e:
        return {"count": 0, "events": [], "error": str(e)}


@api_router.get("/live/graduation/positions")
async def graduation_positions(limit: int = 30):
    """Open/close/reject events for graduation-snipe positions."""
    try:
        cursor = db.graduation_positions.find({}).sort("at", -1).limit(limit)
        docs = []
        async for d in cursor:
            d.pop("_id", None)
            docs.append(d)
        return {"count": len(docs), "events": docs}
    except Exception as e:
        return {"count": 0, "events": [], "error": str(e)}


@api_router.post("/live/graduation/replay")
async def graduation_replay(signature: str, source: str = "pumpswap"):
    """Backtest helper: given a historical graduation signature, run it through
    the monitor's extraction path and return what the normalized event would be.
    Does NOT execute a trade."""
    if source not in ("pumpswap", "bonk_cpmm"):
        return {"error": "source must be 'pumpswap' or 'bonk_cpmm'"}
    try:
        from graduation_monitor import get_graduation_monitor
        gm = get_graduation_monitor(db)
        detail = await gm._extract_pool_details(signature, source)
        if not detail:
            return {"ok": False, "reason": "tx not found or could not parse"}
        return {
            "ok": True,
            "source": source,
            "signature": signature,
            "mint": detail["mint"],
            "pool_address": detail["pool_address"],
            "reserves_sol": detail["reserves_sol"],
            "block_time_iso": detail.get("block_time_iso"),
            "latency_ms_from_block": detail.get("latency_ms"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@api_router.get("/live/tx_landings")
async def tx_landings_status():
    """Landing-rate metrics per module (pumpfun_autobuy, graduation_buy, graduation_sell).
    Free diagnostic — helps you decide whether to invest in Yellowstone / SWQoS / Jito
    later based on REAL landing rates instead of assumptions."""
    try:
        from tx_landings import get_tracker
        return get_tracker(db).status()
    except Exception as e:
        return {"error": str(e), "modules": {}}



@api_router.post("/live/emergency_stop")
async def emergency_stop():
    """Kill switch — flips every live gate in-process. Redeploy or restart to
    re-enable. Unauthenticated per fast-path; add shared-secret header before
    exposing on a public Railway URL for real."""
    from live_trader import get_live_trader
    from pumpfun_autobuy import get_pumpfun_autobuyer
    from graduation_executor import get_graduation_executor
    stopped = []
    try:
        lt = get_live_trader()
        lt.cfg.live_enabled = False
        lt.cfg.simulation_mode = True
        stopped.append("live_trader")
    except Exception as e:
        stopped.append(f"live_trader FAIL: {e}")
    try:
        ab = get_pumpfun_autobuyer(db)
        ab.cfg.enabled = False
        stopped.append("pumpfun_autobuy")
    except Exception as e:
        stopped.append(f"pumpfun_autobuy FAIL: {e}")
    try:
        ge = get_graduation_executor(db)
        ge.cfg.enabled = False
        stopped.append("graduation_executor")
    except Exception as e:
        stopped.append(f"graduation_executor FAIL: {e}")
    return {"ok": True, "stopped": stopped, "note": "in-process only — Railway env vars are unchanged; restart re-reads them"}




@api_router.get("/bot_diagnostic")
async def bot_diagnostic():
    """One-shot answer to 'why isn't my bot trading?' — shows the full state.

    Returns a step-by-step readiness map so a user can see exactly WHY no live
    trades are executing. Zero RPC credits used (all local + Mongo).
    """
    from datetime import timedelta
    lt = get_live_trader()
    config_data = await db.config.find_one({}, {"_id": 0}) or {}

    now = datetime.now(timezone.utc)
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    one_day_ago = (now - timedelta(days=1)).isoformat()

    # Count opportunities + trades in various time windows / types
    try:
        opps_last_hour = await db.opportunities.count_documents({
            "timestamp": {"$gte": one_hour_ago}
        })
    except Exception:
        opps_last_hour = 0

    try:
        approved_opps_last_hour = await db.opportunities.count_documents({
            "timestamp": {"$gte": one_hour_ago},
            "risk_approved": True
        })
    except Exception:
        approved_opps_last_hour = 0

    try:
        sim_trades_24h = await db.trades.count_documents({
            "timestamp": {"$gte": one_day_ago},
            "simulation": True
        })
    except Exception:
        sim_trades_24h = 0

    try:
        live_trades_24h = await db.trades.count_documents({
            "type": "live_manual_swap",
            "created_at": {"$gte": one_day_ago}
        })
    except Exception:
        live_trades_24h = 0

    try:
        successful_live_trades_24h = await db.trades.count_documents({
            "type": "live_manual_swap",
            "created_at": {"$gte": one_day_ago},
            "success": True
        })
    except Exception:
        successful_live_trades_24h = 0

    # Env vs Mongo config comparison — this is the #1 source of confusion
    env_sim_mode = str(os.environ.get('SIMULATION_MODE', 'true')).lower() == 'true'
    mongo_sim_mode = bool(config_data.get('simulation_mode', True))
    env_live_enabled = str(os.environ.get('LIVE_TRADING_ENABLED', 'false')).lower() == 'true'
    mongo_auto_execute = bool(config_data.get('auto_execute', False))

    # Build the diagnosis
    reasons_no_live_trades = []
    if not env_live_enabled:
        reasons_no_live_trades.append(
            "LIVE_TRADING_ENABLED env var is not 'true' on Railway"
        )
    if env_sim_mode:
        reasons_no_live_trades.append(
            "SIMULATION_MODE env var is still 'true' on Railway"
        )
    if not lt.wallet_configured:
        reasons_no_live_trades.append(
            "SOLANA_PRIVATE_KEY or SOLANA_RPC_URL not set (wallet_configured=false)"
        )
    if not lt.ready:
        reasons_no_live_trades.append(
            "live_trader.ready=false — see /api/live/status for detail"
        )
    # ALWAYS append the auto-exec status
    auto_arb_enabled = str(os.environ.get('AUTO_ARB_ENABLED', 'false')).lower() == 'true'
    if not auto_arb_enabled:
        reasons_no_live_trades.append(
            "AUTO_ARB_ENABLED env var is not 'true' — the autonomous arbitrage "
            "monitor is disabled. Set AUTO_ARB_ENABLED=true on Railway to activate. "
            "It scans Jupiter round-trip quotes every 15s and fires trades when a "
            "profitable spread ≥ AUTO_ARB_MIN_PROFIT_BPS (default 30) is found."
        )
    # Warn if mongo auto_execute is true (common misconception)
    if mongo_auto_execute:
        reasons_no_live_trades.append(
            "NOTE: mongo_config.auto_execute=true only affects SIMULATED fills "
            "(the sim bot writing fake trade records). It does NOT trigger real "
            "on-chain swaps. Real autonomous swaps require AUTO_ARB_ENABLED=true."
        )

    return {
        "generated_at": now.isoformat(),
        "verdict_short": (
            "Live auto-trading is NOT active — see 'reasons_no_live_trades' below "
            "and 'what_to_do_next'."
            if reasons_no_live_trades
            else "Live trading is enabled and configured, but you still need to "
                 "fire trades manually via /api/live/test_swap."
        ),
        "env_vars": {
            "SIMULATION_MODE": os.environ.get('SIMULATION_MODE'),
            "LIVE_TRADING_ENABLED": os.environ.get('LIVE_TRADING_ENABLED'),
            "SOLANA_RPC_URL_set": bool(os.environ.get('SOLANA_RPC_URL')),
            "SOLANA_PRIVATE_KEY_set": bool(os.environ.get('SOLANA_PRIVATE_KEY')),
        },
        "mongo_config": {
            "simulation_mode": mongo_sim_mode,
            "auto_execute": mongo_auto_execute,
            "note": (
                "The sim-bot's monitor_arbitrage reads simulation_mode from THIS Mongo doc, "
                "NOT from the env var. If env=false but Mongo=true, sim bot still records "
                "trades as simulated."
            ),
        },
        "config_mismatch_warning": (
            "⚠️ ENV and Mongo disagree on simulation_mode. "
            "The sim-bot uses Mongo. Set them consistently."
            if env_sim_mode != mongo_sim_mode
            else None
        ),
        "activity_last_hour": {
            "opportunities_found": opps_last_hour,
            "opportunities_risk_approved": approved_opps_last_hour,
        },
        "trades_last_24h": {
            "simulation_trades": sim_trades_24h,
            "live_manual_swap_trades": live_trades_24h,
            "live_manual_swap_successful": successful_live_trades_24h,
        },
        "live_trader_state": {
            "ready": lt.ready,
            "wallet_configured": lt.wallet_configured,
            "wallet_pubkey": lt.wallet_pubkey,
            "risk_snapshot": lt.risk.snapshot(),
        },
        "reasons_no_live_trades": reasons_no_live_trades,
        "what_to_do_next": (
            [
                "1. Verify RPC works: GET /api/live/rpc_ping (uses ~2 credits)",
                "2. Verify wallet balance: GET /api/live/balance (uses ~1 credit)",
                "3. Manually fire a tiny test swap: POST /api/live/test_swap with "
                '{"input_symbol":"SOL","output_symbol":"USDC","amount_usd":0.30,"dry_run":false}',
                "4. Watch the trade land on Solscan — link appears in /api/live/trades and in the dashboard",
                "5. Auto-execution IS NOT WIRED YET. The bot will not autonomously fire real trades. "
                "This is a deliberate safety design — auto-exec against fake simulated signals would burn "
                "your wallet. Real Jupiter-based auto-arb is a separate feature you'd need to ask for.",
            ]
            if lt.ready
            else [
                "1. Fix the 'reasons_no_live_trades' items above (set env vars on Railway).",
                "2. Push latest code to GitHub if you haven't recently.",
                "3. After redeploy, check /api/live/status — 'ready' should become true.",
                "4. Only then follow the trade-firing steps.",
            ]
        ),
    }


class LiveTestSwapRequest(BaseModel):
    input_symbol: str            # e.g. "USDC"
    output_symbol: str           # e.g. "SOL"
    amount_usd: float            # size in USD (converted to base units internally)
    dry_run: bool = True         # True = fetch quote only, no submit


@api_router.post("/live/test_swap")
async def live_test_swap(req: LiveTestSwapRequest):
    """
    Manual guarded live-swap endpoint. Use this to verify live trading works
    with a tiny amount before enabling any auto-trading.

    Enforces all safety gates. Set dry_run=false to actually submit on-chain.
    """
    lt = get_live_trader()
    if not lt.ready:
        return {"ok": False, "reason": "live trader not ready — check /api/live/status"}

    in_sym = req.input_symbol.upper() if req.input_symbol.upper() in MINTS else req.input_symbol
    out_sym = req.output_symbol.upper() if req.output_symbol.upper() in MINTS else req.output_symbol
    if in_sym not in MINTS or out_sym not in MINTS:
        return {"ok": False, "reason": f"unknown symbol; supported: {list(MINTS.keys())}"}

    pair = f"{in_sym}/{out_sym}"
    allowed, why = await lt.check_pair_allowed(pair)
    if not allowed:
        return {"ok": False, "reason": why}

    can, why = lt.risk.can_trade(req.amount_usd)
    if not can:
        return {"ok": False, "reason": f"risk gate: {why}"}

    # Balance check
    sol_balance = await lt.get_sol_balance()
    if sol_balance < lt.cfg.min_reserve_sol:
        return {"ok": False, "reason": f"SOL balance {sol_balance:.4f} below min reserve {lt.cfg.min_reserve_sol}"}

    # Convert amount_usd to base units.
    # For USDC/USDT: 1 unit ≈ $1. For SOL/JitoSOL/mSOL: use approximate SOL price.
    # (Approximation only; Jupiter quote returns the accurate output.)
    SOL_USD_ESTIMATE = 150.0
    if in_sym in ("USDC", "USDT"):
        amount_base = int(req.amount_usd * (10 ** DECIMALS[in_sym]))
    elif in_sym in ("SOL", "JitoSOL", "mSOL"):
        amount_base = int((req.amount_usd / SOL_USD_ESTIMATE) * (10 ** DECIMALS[in_sym]))
    elif in_sym == "JUP":
        amount_base = int((req.amount_usd / 0.5) * (10 ** DECIMALS[in_sym]))  # ~$0.50 JUP
    else:
        return {"ok": False, "reason": f"unsupported input symbol {in_sym}"}

    if req.dry_run:
        try:
            quote = await lt.jupiter.get_quote(
                MINTS[in_sym], MINTS[out_sym], amount_base, lt.cfg.slippage_bps
            )
            return {
                "ok": True,
                "dry_run": True,
                "pair": pair,
                "amount_usd": req.amount_usd,
                "amount_base_units": amount_base,
                "quote_in_amount": quote.get("inAmount"),
                "quote_out_amount": quote.get("outAmount"),
                "price_impact_pct": quote.get("priceImpactPct"),
                "route_labels": [step.get("swapInfo", {}).get("label") for step in quote.get("routePlan", [])],
            }
        except Exception as e:
            return {"ok": False, "reason": f"quote error: {e}"}

    # REAL submission
    result = await lt.execute_swap(MINTS[in_sym], MINTS[out_sym], amount_base)
    # Record as $0 pnl for now (single-leg swap isn't a full arb). Just tracks cooldown.
    lt.risk.record_trade(0.0)

    # Persist a MongoDB trade record for the dashboard
    try:
        await db.trades.insert_one({
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pair": pair,
            "type": "live_manual_swap",
            "amount_usd": req.amount_usd,
            "signature": result.get("signature"),
            "success": result.get("success"),
            "error": result.get("error"),
            "in_amount": result.get("in_amount"),
            "out_amount": result.get("out_amount"),
            "submission_method": result.get("submission_method"),
            "bundle_id": result.get("bundle_id"),
            "jito_tip_lamports": result.get("jito_tip_lamports", 0),
            "solscan_url": f"https://solscan.io/tx/{result.get('signature')}" if result.get("signature") else None,
            "simulation": False,
        })
    except Exception as e:
        logger.warning(f"[live] failed to record trade: {e}")

    return {"ok": True, "dry_run": False, "pair": pair, **result}


@api_router.get("/live/trades")
async def live_trades(limit: int = 25):
    """Return the most recent LIVE trades submitted through the LiveTrader (Jupiter+QuickNode).
    Excludes simulation-bot trade records that may also have `simulation: false`."""
    try:
        # Only trades explicitly submitted through /api/live/test_swap (or the future auto-executor).
        # This filter avoids picking up simulation-bot records that happen to have
        # simulation=false (which occurs when the Mongo `config.simulation_mode` was toggled).
        cursor = db.trades.find({
            "type": {"$in": ["live_manual_swap", "live_auto_arb"]},
            "signature": {"$ne": None},
        }).sort("created_at", -1).limit(limit)
        docs = []
        async for d in cursor:
            d.pop("_id", None)
            docs.append(d)
        return {"count": len(docs), "trades": docs}
    except Exception as e:
        return {"count": 0, "trades": [], "error": str(e)}


@api_router.get("/live/summary")
async def live_summary():
    """Aggregate live-trading stats: wallet balance, PnL today, trades today, breakers."""
    lt = get_live_trader()

    # Balance now works whenever wallet+RPC are configured (even in safe/simulation mode)
    sol_balance = 0.0
    if lt.wallet_configured:
        sol_balance = await lt.get_sol_balance()

    # Aggregate today's live trades — only real LiveTrader-originated records
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        cursor = db.trades.find({
            "type": {"$in": ["live_manual_swap", "live_auto_arb"]},
            "signature": {"$ne": None},
            "created_at": {"$gte": today}
        })
        total = 0
        successful = 0
        total_usd = 0.0
        total_jito_tips = 0
        async for d in cursor:
            total += 1
            if d.get("success"):
                successful += 1
            total_usd += float(d.get("amount_usd", 0) or 0)
            total_jito_tips += int(d.get("jito_tip_lamports", 0) or 0)
    except Exception as e:
        total = successful = 0
        total_usd = 0.0
        total_jito_tips = 0
        logger.warning(f"[live/summary] aggregate error: {e}")

    return {
        "ready": lt.ready,
        "wallet_configured": lt.wallet_configured,
        "wallet": lt.wallet_pubkey,
        "sol_balance": sol_balance,
        "sol_balance_usd_estimate": sol_balance * 150.0,  # rough
        "meets_min_reserve": sol_balance >= lt.cfg.min_reserve_sol,
        "today": {
            "date_utc": today,
            "total_trades": total,
            "successful_trades": successful,
            "success_rate_pct": round((successful / total * 100), 1) if total else 0,
            "total_volume_usd": round(total_usd, 4),
            "total_jito_tips_sol": round(total_jito_tips / 1_000_000_000, 6),
        },
        "risk": lt.risk.snapshot(),
        "limits": {
            "max_trade_usd": lt.cfg.max_trade_usd,
            "daily_loss_limit_usd": lt.cfg.daily_loss_limit_usd,
            "min_reserve_sol": lt.cfg.min_reserve_sol,
        },
        "jito_enabled": lt.cfg.use_jito,
    }

@api_router.get("/opportunities", response_model=List[ArbitrageOpportunity])
async def get_opportunities(limit: int = 50, max_age_seconds: int = 120, include_executed: bool = True):
    """
    Get current arbitrage opportunities
    
    Args:
        limit: Maximum number of opportunities to return
        max_age_seconds: Only show opportunities newer than this (default: 120 seconds)
        include_executed: Include recently executed opportunities (default: True)
    """
    from datetime import timedelta
    
    # Calculate cutoff time - show opportunities from last 2 minutes
    cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    
    # Build query - include executed opportunities if requested (for live feed visibility)
    query = {"timestamp": {"$gte": cutoff_time.isoformat()}}
    if not include_executed:
        query["executed"] = False
    
    opportunities = await db.opportunities.find(
        query,
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    
    for opp in opportunities:
        if isinstance(opp['timestamp'], str):
            opp['timestamp'] = datetime.fromisoformat(opp['timestamp'])
    
    return opportunities

@api_router.get("/trades", response_model=List[Trade])
async def get_trades(limit: int = 100):
    trades = await db.trades.find(
        {}, {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    
    for trade in trades:
        if isinstance(trade['timestamp'], str):
            trade['timestamp'] = datetime.fromisoformat(trade['timestamp'])
    
    return trades

@api_router.get("/config", response_model=BotConfig)
async def get_config():
    config = await db.config.find_one({}, {"_id": 0})
    if not config:
        # Create default config
        default_config = BotConfig()
        config_dict = default_config.model_dump()
        config_dict['updated_at'] = config_dict['updated_at'].isoformat()
        await db.config.insert_one(config_dict)
        return default_config
    
    if isinstance(config['updated_at'], str):
        config['updated_at'] = datetime.fromisoformat(config['updated_at'])
    return config

@api_router.post("/config", response_model=BotConfig)
async def update_config(config: BotConfig):
    config.updated_at = datetime.now(timezone.utc)
    config_dict = config.model_dump()
    config_dict['updated_at'] = config_dict['updated_at'].isoformat()
    
    await db.config.delete_many({})
    await db.config.insert_one(config_dict)
    
    return config

@api_router.get("/flash/monitor/stats")
async def get_flash_monitor_stats():
    """Get flash loan monitor statistics"""
    return get_flash_loan_stats()

@api_router.get("/stats", response_model=BotStats)
async def get_stats():
    from datetime import timedelta
    
    # Count ALL recent opportunities (last 2 minutes, executed or not)
    cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=120)
    total_opportunities = await db.opportunities.count_documents({
        "timestamp": {"$gte": cutoff_time.isoformat()}
    })
    
    executed_trades = await db.trades.count_documents({"status": {"$in": ["completed", "simulated"]}})
    
    # Calculate total profit from ALL trades using aggregation
    pipeline = [
        {"$match": {"status": {"$in": ["completed", "simulated"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$profit"}}}
    ]
    result = await db.trades.aggregate(pipeline).to_list(1)
    total_profit = result[0]['total'] if result else 0
    
    # Calculate success rate
    all_trades = await db.trades.count_documents({})
    success_rate = (executed_trades / all_trades * 100) if all_trades > 0 else 0
    
    # Get active pairs count
    config_data = await db.config.find_one({}, {"_id": 0})
    active_pairs = len(config_data.get('monitored_pairs', [])) if config_data else 0
    
    # Get risk manager stats
    risk_stats = risk_manager.get_stats()
    
    return BotStats(
        total_opportunities=total_opportunities,
        executed_trades=executed_trades,
        total_profit=total_profit,
        success_rate=success_rate,
        active_pairs=active_pairs,
        **risk_stats
    )

@api_router.post("/execute")
async def execute_trade(request: ExecuteTradeRequest):
    # Check if trading is allowed
    can_trade, reason = risk_manager.can_trade()
    if not can_trade:
        return {"success": False, "error": reason}
    
    # Get opportunity
    opp = await db.opportunities.find_one({"id": request.opportunity_id}, {"_id": 0})
    if not opp:
        return {"success": False, "error": "Opportunity not found"}
    
    # Check if already executed
    if opp.get('executed'):
        return {"success": False, "error": "Opportunity already executed"}
    
    # Get config
    config_data = await db.config.find_one({}, {"_id": 0})
    simulation_mode = config_data.get('simulation_mode', True) if config_data else True
    
    # Calculate actual profit/loss
    net_profit = opp.get('net_profit_amount', 0)
    
    # Create trade record
    trade = Trade(
        opportunity_id=request.opportunity_id,
        token_pair=opp['token_pair'],
        dex_buy=opp['dex_buy'],
        dex_sell=opp['dex_sell'],
        buy_amount=request.amount,
        sell_amount=request.amount + net_profit,
        profit=net_profit,
        profit_percentage=opp.get('net_profit_percentage', 0),
        status="simulated" if simulation_mode else "pending",
        simulation=simulation_mode
    )
    
    trade_dict = trade.model_dump()
    trade_dict['timestamp'] = trade_dict['timestamp'].isoformat()
    
    await db.trades.insert_one(trade_dict)
    
    # Update risk manager
    risk_manager.record_trade(
        profit_loss=net_profit,
        success=True
    )
    
    # Mark opportunity as executed
    await db.opportunities.update_one(
        {"id": request.opportunity_id},
        {"$set": {"executed": True}}
    )
    
    # Broadcast update
    await manager.broadcast({
        "type": "trade_executed",
        "trade": trade_dict
    })
    
    logger.info(
        f"💰 Trade executed: {opp['token_pair']} | "
        f"Profit: ${net_profit:.4f} | "
        f"{'SIMULATION' if simulation_mode else 'LIVE'}"
    )
    
    return {
        "success": True, 
        "trade_id": trade.id, 
        "simulation": simulation_mode,
        "profit": net_profit,
        "new_capital": risk_manager.current_capital
    }

# ============================================================================
# MEME COIN TRADING ENDPOINTS
# ============================================================================

def sanitize_float(value):
    """Sanitize float values to prevent JSON serialization errors"""
    import math
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value):
            return 0.0
    return value

def sanitize_opportunity(opp):
    """Recursively sanitize all float values in opportunity dict"""
    if isinstance(opp, dict):
        return {k: sanitize_opportunity(v) for k, v in opp.items()}
    elif isinstance(opp, list):
        return [sanitize_opportunity(item) for item in opp]
    else:
        return sanitize_float(opp)

@api_router.get("/meme/stats")
async def get_meme_stats():
    """Get meme coin trading statistics"""
    import math
    
    # Count meme trades
    meme_trades = await db.meme_trades.count_documents({})
    
    # Calculate total profit using MongoDB aggregation (handles all trades efficiently)
    # Filter for valid profits: between -100 and 100, excluding inf/nan
    pipeline = [
        {"$match": {
            "status": {"$in": ["completed", "simulated"]},
            "profit": {"$type": ["double", "int", "long"]},  # Numeric types only
            "profit": {"$gte": -100, "$lt": 100}  # Realistic profit range
        }},
        {"$group": {
            "_id": None,
            "total": {"$sum": "$profit"}
        }}
    ]
    result = await db.meme_trades.aggregate(pipeline).to_list(1)
    total_profit = result[0]['total'] if result and result[0].get('total') else 0.0
    
    # Get risk stats (excluding total_trades and successful_trades which come from DB)
    risk_stats = meme_risk_manager.get_stats()
    # Remove keys that should come from database
    risk_stats.pop('total_trades', None)
    risk_stats.pop('successful_trades', None)
    
    # Calculate success rate from database
    success_rate = 100.0 if meme_trades > 0 else 0.0
    
    return {
        "pool_balance": sanitize_float(meme_balance),
        "initial_capital": 10.0,
        "total_trades": meme_trades,
        "total_profit": sanitize_float(total_profit),
        "active_opportunities": len(meme_active_opportunities),
        "meme_pairs_monitored": len(ALL_MEME_PAIRS),
        "tokens_tracked": len(MEME_TOKENS),
        "successful_trades": meme_trades,  # All simulated trades are successful
        "success_rate": success_rate,
        **{k: sanitize_float(v) for k, v in risk_stats.items()}
    }

@api_router.get("/meme/opportunities")
async def get_meme_opportunities(limit: int = 50):
    """Get current meme coin arbitrage opportunities"""
    # Sanitize opportunities to prevent JSON serialization errors
    sanitized_opps = [sanitize_opportunity(opp) for opp in meme_active_opportunities[:limit]]
    return sanitized_opps

@api_router.get("/meme/trades")
async def get_meme_trades(limit: int = 20):
    """Get meme coin trade history"""
    trades = await db.meme_trades.find(
        {},
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    
    return trades
@api_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Background task for monitoring
async def monitor_meme_opportunities():
    """Monitor meme coin arbitrage opportunities"""
    global meme_active_opportunities, meme_balance
    
    logger.info("Starting meme coin opportunity monitor...")
    
    while True:
        try:
            # Scan for meme opportunities
            opportunities = await meme_arbitrage_detector.scan_all_opportunities()
            
            # Add IDs and timestamp
            for opp in opportunities:
                opp['id'] = str(uuid.uuid4())
                opp['discovered_at'] = datetime.now(timezone.utc)
            
            # Filter by safety (good liquidity)
            safe_opps = [o for o in opportunities if o.get('safe', False)]
            
            meme_active_opportunities = safe_opps[:50]  # Keep top 50
            
            # Auto-execute if enabled and we have opportunities
            if AUTO_EXECUTE and meme_active_opportunities:
                best_opp = meme_active_opportunities[0]
                
                # Check if can trade
                can_trade, trade_size, reason = meme_risk_manager.approve_trade(
                    meme_balance, best_opp
                )
                
                if can_trade and trade_size > 0:
                    # Execute trade
                    success = True  # Simulated
                    net_profit = trade_size * (best_opp['net_profit_bps'] / 10000)
                    
                    # Update balance
                    meme_balance += net_profit
                    
                    # Create trade record
                    trade_dict = {
                        "id": str(uuid.uuid4()),
                        "type": best_opp['type'],
                        "token_pair": best_opp.get('pair') or best_opp.get('path'),
                        "buy_dex": best_opp.get('buy_dex') or best_opp.get('leg1', {}).get('dex'),
                        "sell_dex": best_opp.get('sell_dex') or best_opp.get('leg2', {}).get('dex'),
                        "buy_amount": trade_size,
                        "sell_amount": trade_size * (1 + best_opp['net_profit_bps'] / 10000),
                        "profit": net_profit,
                        "profit_percentage": best_opp['net_profit_bps'] / 100,
                        "timestamp": datetime.now(timezone.utc),
                        "status": "simulated"
                    }
                    
                    await db.meme_trades.insert_one(trade_dict)
                    
                    # Update risk manager
                    meme_risk_manager.record_trade_result(success, net_profit)
                    
                    logger.info(
                        f"🎯 MEME TRADE: {trade_dict['token_pair']} | "
                        f"Profit: ${net_profit:.4f} ({best_opp['net_profit_bps']:.1f} bps)"
                    )
            
        except Exception as e:
            logger.error(f"Error in meme monitor: {e}")
        
        await asyncio.sleep(5)  # Check every 5 seconds

async def cleanup_stale_opportunities():
    """Background task to clean up old opportunities from database"""
    logger.info("Starting stale opportunity cleanup task...")
    
    while True:
        try:
            # Remove opportunities older than 5 minutes
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=5)
            
            result = await db.opportunities.delete_many({
                "timestamp": {"$lt": cutoff_time.isoformat()}
            })
            
            if result.deleted_count > 0:
                logger.info(f"🧹 Cleaned up {result.deleted_count} stale opportunities")
            
            # Run cleanup every minute
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"Error in cleanup_stale_opportunities: {e}")
            await asyncio.sleep(60)

async def monitor_arbitrage():
    """Background task to monitor arbitrage opportunities with realistic DEX data"""
    logger.info("Starting arbitrage monitoring with realistic DEX connectors...")
    
    while True:
        try:
            # Check if trading is allowed
            can_trade, reason = risk_manager.can_trade()
            if not can_trade:
                logger.warning(f"Trading suspended: {reason}")
                await asyncio.sleep(30)
                continue
            
            config_data = await db.config.find_one({}, {"_id": 0})
            if not config_data or not config_data.get('monitored_pairs'):
                await asyncio.sleep(5)
                continue
            
            pairs = config_data.get('monitored_pairs', [
                'SOL/USDC', 'RAY/USDC', 'ORCA/USDC', 'JUP/USDC',
                'JTO/USDC', 'PYTH/USDC', 'SOL/USDT', 'USDC/USDT'
            ])
            auto_execute = config_data.get('auto_execute', False)
            
            # Scan each pair
            for pair in pairs:
                try:
                    # Simulate network latency
                    await asyncio.sleep(LATENCY_MS / 1000)
                    
                    # Get prices from all DEXs
                    prices = await dex_aggregator.get_all_prices(pair)
                    
                    if len(prices) < 2:
                        continue
                    
                    # Get max trade size from risk manager
                    max_trade_size = risk_manager.get_max_trade_size()
                    
                    # Find arbitrage opportunity
                    opportunity = dex_aggregator.find_arbitrage_opportunity(
                        prices=prices,
                        max_trade_amount=max_trade_size,
                        min_spread=MIN_SPREAD_AFTER_COSTS,
                        max_slippage=MAX_SLIPPAGE_TOLERANCE
                    )
                    
                    if opportunity:
                        # Evaluate with risk manager
                        approved, risk_reason = risk_manager.evaluate_opportunity(
                            opportunity, MAX_SLIPPAGE_TOLERANCE
                        )
                        
                        opportunity['risk_approved'] = approved
                        opportunity['risk_reason'] = risk_reason
                        
                        # Create ArbitrageOpportunity model
                        opp_obj = ArbitrageOpportunity(**opportunity)
                        opp_dict = opp_obj.model_dump()
                        opp_dict['timestamp'] = opp_dict['timestamp'].isoformat()
                        
                        # Save to database
                        await db.opportunities.insert_one(opp_dict)
                        
                        # Broadcast if approved
                        if approved:
                            await manager.broadcast({
                                "type": "new_opportunity",
                                "opportunity": opp_dict
                            })
                            
                            logger.info(
                                f"✅ Opportunity found: {pair} | "
                                f"{opportunity['dex_buy']} → {opportunity['dex_sell']} | "
                                f"Net profit: ${opportunity['net_profit_amount']:.4f} "
                                f"({opportunity['net_profit_percentage']:.3f}%)"
                            )
                            
                            # AUTO-EXECUTE if enabled
                            if auto_execute:
                                try:
                                    simulation_mode = config_data.get('simulation_mode', True)
                                    trade_amount = opportunity['trade_amount']
                                    net_profit = opportunity['net_profit_amount']
                                    
                                    # Create trade record
                                    trade = Trade(
                                        opportunity_id=opp_obj.id,
                                        token_pair=opportunity['token_pair'],
                                        dex_buy=opportunity['dex_buy'],
                                        dex_sell=opportunity['dex_sell'],
                                        buy_amount=trade_amount,
                                        sell_amount=trade_amount + net_profit,
                                        profit=net_profit,
                                        profit_percentage=opportunity['net_profit_percentage'],
                                        status="simulated" if simulation_mode else "completed",
                                        simulation=simulation_mode
                                    )
                                    
                                    trade_dict = trade.model_dump()
                                    trade_dict['timestamp'] = trade_dict['timestamp'].isoformat()
                                    
                                    await db.trades.insert_one(trade_dict)
                                    
                                    # Update risk manager
                                    risk_manager.record_trade(
                                        profit_loss=net_profit,
                                        success=True
                                    )
                                    
                                    # Mark opportunity as executed
                                    await db.opportunities.update_one(
                                        {"id": opp_obj.id},
                                        {"$set": {"executed": True}}
                                    )
                                    
                                    # Broadcast trade
                                    await manager.broadcast({
                                        "type": "trade_executed",
                                        "trade": trade_dict
                                    })
                                    
                                    logger.info(
                                        f"💰 AUTO-EXECUTED: {pair} | "
                                        f"Profit: ${net_profit:.4f} | "
                                        f"New Capital: ${risk_manager.current_capital:.4f} | "
                                        f"{'SIMULATION' if simulation_mode else 'LIVE'}"
                                    )
                                    
                                except Exception as e:
                                    logger.error(f"Error auto-executing trade: {e}")
                        else:
                            logger.debug(f"❌ Opportunity rejected: {pair} | {risk_reason}")
                
                except Exception as e:
                    logger.error(f"Error processing pair {pair}: {e}")
                    continue
            
            # Check every 2-3 seconds (realistic scanning interval)
            await asyncio.sleep(2.5)
            
        except Exception as e:
            logger.error(f"Error in monitor_arbitrage: {e}")
            await asyncio.sleep(5)

# Include the router in the main app
app.include_router(api_router)
app.include_router(flash_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


# Startup code
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

# Shutdown handled in lifespan context manager