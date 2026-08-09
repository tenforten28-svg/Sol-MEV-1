"""
PUMP.FUN AUTO-SNIPER (bonding-curve direct)
===========================================
Detects new pump.fun mints and (when PUMPFUN_AUTO_BUY_ENABLED=true) fires a small buy
DIRECTLY against the pump.fun bonding curve via PumpPortal's Local Trading API.

Why PumpPortal Local API and not Jupiter:
  Freshly-minted pump.fun tokens live on the bonding curve BEFORE graduation.
  Jupiter cannot route trades on them until they migrate to PumpSwap/Raydium.
  PumpPortal's /api/trade-local endpoint builds an unsigned VersionedTransaction
  for the pump.fun program directly. We sign locally with our wallet (key never
  leaves the server) and submit via our own QuickNode RPC. This is the pragmatic
  path documented by the pump.fun integration playbook.

  NOTE: PumpPortal is a third-party service (unaffiliated with pump.fun).
  We rely on it only to construct the instruction; signing + submission are
  done locally so PumpPortal never has custody or send rights.

SAFETY (non-negotiable, off-by-default):
- Master gate: PUMPFUN_AUTO_BUY_ENABLED=false by default
- LiveTrader must be ready (SIMULATION_MODE=false + LIVE_TRADING_ENABLED=true + wallet)
- Hard buy size cap (PUMPFUN_BUY_SOL default 0.002 SOL ≈ $0.30)
- Daily SOL budget cap (PUMPFUN_DAILY_BUDGET_SOL default 0.015 SOL ≈ $2)
- Max concurrent positions (PUMPFUN_MAX_CONCURRENT default 3)
- Cooldown between buys (PUMPFUN_COOLDOWN_SEC default 30s)
- Mint authority + freeze authority MUST be revoked (rug-risk gate)
- Auto-exit on stop-loss (default -50%) / take-profit (default 2x) / time (default 5min)
- Every buy/sell result stored in mongo (pumpfun_positions + trades collections)
"""
import os
import time
import base64
import struct
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import aiohttp
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from live_trader import get_live_trader
from exit_ladder import (
    parse_ladder, evaluate_ladder, record_milestone_hit,
    LadderState, LadderActionType, DEFAULT_LADDER_CFG, DEFAULT_RUG_STOP,
)

logger = logging.getLogger("pumpfun_autobuy")

PUMPPORTAL_TRADE_LOCAL_URL = "https://pumpportal.fun/api/trade-local"
LAMPORTS_PER_SOL = 1_000_000_000
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT = "So11111111111111111111111111111111111111112"

# Shared SOL/USD price cache (30s TTL). Populated via Jupiter SOL→USDC quote.
_sol_usd_cache = {"price": None, "at": 0.0}

# Pump.fun on-chain constants
PUMPFUN_PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022_PROGRAM = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ATA_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")

# Token-2022 extensions that are honeypot red flags
DANGEROUS_T22_EXTENSIONS = {
    "transferFeeConfig",       # dev can drain via transfer fees
    "permanentDelegate",       # someone can take your tokens forever
    "nonTransferable",         # you literally can't sell
    "transferHook",            # arbitrary program can block/steal your transfer
    "mintCloseAuthority",      # can close the mint entirely
}
# defaultAccountState is checked separately — only rejected if state == "Frozen"


def _fbool(k, d=False):
    return str(os.environ.get(k, str(d))).strip().lower() in ("true", "1", "yes", "on")


def _fflt(k, d):
    try:
        return float(os.environ.get(k, d))
    except Exception:
        return d


def _fint(k, d):
    try:
        return int(os.environ.get(k, d))
    except Exception:
        return d


class AutoBuyConfig:
    def __init__(self):
        # Master enable gate
        self.enabled = _fbool("PUMPFUN_AUTO_BUY_ENABLED", False)
        # Size (SOL denominated because pump.fun bonding curve trades in SOL)
        self.buy_sol = _fflt("PUMPFUN_BUY_SOL", 0.002)
        self.daily_budget_sol = _fflt("PUMPFUN_DAILY_BUDGET_SOL", 0.015)
        # Position / rate limits
        self.max_concurrent = _fint("PUMPFUN_MAX_CONCURRENT", 3)
        self.cooldown_sec = _fint("PUMPFUN_COOLDOWN_SEC", 30)
        # Safety filters
        self.require_authorities_revoked = _fbool("PUMPFUN_REQUIRE_AUTH_REVOKED", True)
        self.settle_delay_sec = _fint("PUMPFUN_SETTLE_DELAY", 4)
        # Exit rules
        self.hold_max_seconds = _fint("PUMPFUN_HOLD_MAX_SEC", 300)
        self.take_profit_mult = _fflt("PUMPFUN_TAKE_PROFIT", 2.0)
        self.stop_loss_mult = _fflt("PUMPFUN_STOP_LOSS", 0.5)
        self.check_interval_sec = _fint("PUMPFUN_CHECK_INTERVAL", 10)
        # Trading params
        self.slippage_pct = _fflt("PUMPFUN_SLIPPAGE_PCT", 10.0)  # 10% for volatile snipes
        self.priority_fee_sol = _fflt("PUMPFUN_PRIORITY_FEE_SOL", 0.0001)
        # Dev-hold rug filter — reject if creator holds more than this % of supply right after mint.
        # Typical safe range: 5-15%. Set to 100 to disable.
        self.max_dev_hold_pct = _fflt("PUMPFUN_MAX_DEV_HOLD_PCT", 15.0)
        # Top-10 non-pool holders combined must be <= this % of supply. Catches "10-burner-wallet" rugs.
        self.max_top10_pct = _fflt("PUMPFUN_MAX_TOP10_PCT", 30.0)
        # Largest single non-pool holder must be <= this % of supply. Catches single-whale traps.
        self.max_holder_pct = _fflt("PUMPFUN_MAX_HOLDER_PCT", 20.0)
        # Minimum real SOL in the bonding curve — rejects illiquid dust launches.
        # Fresh pump.fun mints start at ~0.01-0.03 SOL after the creator's initial buy;
        # this default is essentially "is the curve initialized". Raise it if you want
        # to snipe only launches that already have real buy volume.
        self.min_curve_sol = _fflt("PUMPFUN_MIN_CURVE_SOL", 0.01)
        # Reject Token-2022 mints that have honeypot extensions (transfer fee, permanent delegate, etc.)
        self.reject_dangerous_t22 = _fbool("PUMPFUN_REJECT_DANGEROUS_T22", True)
        # Laddered exit — same format as graduation: "mult:pct_of_remaining:floor_after,..."
        self.ladder_cfg = os.environ.get("PUMPFUN_LADDER", DEFAULT_LADDER_CFG).strip()
        self.rug_stop_mult = _fflt("PUMPFUN_RUG_STOP", DEFAULT_RUG_STOP)
        self.ladder = parse_ladder(self.ladder_cfg)
        # Ladder mode: 'ratio' (multiples of entry price, existing default) OR
        # 'mcap' (absolute USD market cap thresholds, per Doc 1 scaled-exit spec)
        self.ladder_mode = os.environ.get("PUMPFUN_LADDER_MODE", "ratio").strip().lower()
        # Mcap-mode configuration (only used when ladder_mode == 'mcap')
        # Default ladder matches Doc 1: sell 50% at $10k (trail $5k), 50% remainder at $60k
        # (graduation, no floor after), moonbag exit at $300k (5x graduation mcap, no floor).
        self.ladder_mcap_cfg = os.environ.get(
            "PUMPFUN_LADDER_MCAP", "10000:50:5000,60000:50:0,300000:100:0"
        ).strip()
        self.ladder_mcap = parse_ladder(self.ladder_mcap_cfg)
        # Absolute USD mcap under which the position is force-closed BEFORE any milestone hit
        self.rug_stop_mcap_usd = _fflt("PUMPFUN_RUG_STOP_MCAP_USD", 1300.0)
        # Entry gate: skip buy if detected mcap is above this (avoid chasing pumps)
        self.entry_mcap_max_usd = _fflt("PUMPFUN_ENTRY_MCAP_MAX_USD", 5000.0)
        # Fee-economic gate: skip a partial sell if the sale value < this USD (fees eat gains)
        self.min_sell_usd = _fflt("PUMPFUN_MIN_SELL_USD", 0.20)


class Position:
    def __init__(self, mint: str, buy_sol: float, token_amount: float,
                 buy_signature: str, opened_at: float,
                 entry_price: float = 0.0,
                 entry_mcap_usd: float = 0.0,
                 supply_raw: int = 0):
        self.mint = mint
        self.buy_sol = buy_sol          # SOL spent
        self.token_amount = token_amount  # tokens received (whole units)
        self.buy_signature = buy_signature
        self.opened_at = opened_at
        self.closed = False
        # Ladder-exit state
        self.entry_price = entry_price   # SOL per raw token unit (from bonding curve at buy time)
        self.entry_mcap_usd = entry_mcap_usd
        self.supply_raw = supply_raw     # on-chain total supply (raw units) — pinned at buy for consistent mcap math
        self.remaining_pct_of_original = 100.0
        self.ladder_state = LadderState()
        self.partial_sells: list = []


class PumpFunAutoBuyer:
    def __init__(self, db):
        self.db = db
        self.cfg = AutoBuyConfig()
        self.lt = get_live_trader()
        self.positions: Dict[str, Position] = {}
        self.last_buy_at = 0.0
        self.day_start = datetime.now(timezone.utc).date()
        self.day_spent_sol = 0.0
        # Counters
        self.attempts = 0
        self.buys_fired = 0
        self.buys_successful = 0
        self.sells_fired = 0
        self.rejects_safety = 0
        self.last_reason: Optional[str] = None
        # HTTP session (lazy)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _reset_day_if_needed(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day_start:
            self.day_start = today
            self.day_spent_sol = 0.0

    # -------- safety pre-checks --------
    async def _check_mint_safety(self, mint: str) -> Dict[str, Any]:
        """Fetch mint account via QuickNode RPC. Reject if mintAuthority or
        freezeAuthority is still active (dev can mint more supply / freeze users)."""
        if not self.lt.cfg.rpc_url:
            return {"ok": False, "reason": "no rpc"}
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
            "params": [mint, {"encoding": "jsonParsed", "commitment": "confirmed"}],
        }
        try:
            s = await self._http()
            async with s.post(self.lt.cfg.rpc_url, json=payload, timeout=10) as r:
                data = await r.json()
            val = (data.get("result") or {}).get("value") or {}
            program_owner = val.get("owner")
            is_token_2022 = program_owner == str(TOKEN_2022_PROGRAM)
            parsed = (((val.get("data") or {}).get("parsed") or {}).get("info") or {})
            mint_auth = parsed.get("mintAuthority")
            freeze_auth = parsed.get("freezeAuthority")
            decimals = parsed.get("decimals")
            supply = parsed.get("supply")
            authorities_ok = (mint_auth is None) and (freeze_auth is None)

            # Detect dangerous Token-2022 extensions
            dangerous_exts = []
            extensions = parsed.get("extensions") or []
            for ext in extensions:
                if not isinstance(ext, dict):
                    continue
                name = ext.get("extension") or ext.get("type")
                if name in DANGEROUS_T22_EXTENSIONS:
                    dangerous_exts.append(name)
                elif name == "defaultAccountState":
                    # Only dangerous if accounts default to Frozen (untradable)
                    state_val = ((ext.get("state") or {}).get("accountState")
                                 or (ext.get("state") or {}).get("state")
                                 or ext.get("accountState"))
                    if isinstance(state_val, str) and state_val.lower() == "frozen":
                        dangerous_exts.append("defaultAccountState=Frozen")

            return {
                "ok": True,
                "mint_authority_revoked": mint_auth is None,
                "freeze_authority_revoked": freeze_auth is None,
                "authorities_safe": authorities_ok,
                "decimals": decimals,
                "supply": supply,
                "is_token_2022": is_token_2022,
                "dangerous_extensions": dangerous_exts,
                "extensions_safe": len(dangerous_exts) == 0,
            }
        except Exception as e:
            return {"ok": False, "reason": f"rpc lookup failed: {e}"}

    async def _check_dev_hold(self, signature: str, mint: str, total_supply: Optional[str]) -> Dict[str, Any]:
        """Fetch the mint's creation tx and compute how much of the supply the creator
        (= fee payer) is holding after their initial buy. Reject if > max_dev_hold_pct.

        We use postTokenBalances from the tx meta — one RPC call, no extra queries."""
        if not self.lt.cfg.rpc_url or not signature:
            return {"ok": False, "reason": "no rpc or signature"}
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [signature, {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0,
            }],
        }
        try:
            s = await self._http()
            async with s.post(self.lt.cfg.rpc_url, json=payload, timeout=10) as r:
                data = await r.json()
            result = data.get("result")
            if not result:
                return {"ok": False, "reason": "tx not found (may not be confirmed yet)"}

            # Fee payer = first signer = creator on pump.fun mint tx
            keys = ((result.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
            creator = None
            if keys:
                first = keys[0]
                creator = first.get("pubkey") if isinstance(first, dict) else first

            # postTokenBalances lists every touched token account with owner + balance
            post_balances = ((result.get("meta") or {}).get("postTokenBalances") or [])
            creator_balance_raw = 0
            for b in post_balances:
                if b.get("mint") != mint:
                    continue
                if b.get("owner") == creator:
                    ui = b.get("uiTokenAmount") or {}
                    try:
                        creator_balance_raw = int(ui.get("amount") or 0)
                    except Exception:
                        creator_balance_raw = 0
                    break

            try:
                supply_raw = int(total_supply or 0)
            except Exception:
                supply_raw = 0
            if supply_raw <= 0:
                return {"ok": False, "reason": "supply unknown"}

            pct = (creator_balance_raw / supply_raw) * 100.0
            return {
                "ok": True,
                "creator": creator,
                "creator_balance_raw": creator_balance_raw,
                "supply_raw": supply_raw,
                "dev_hold_pct": round(pct, 3),
                "within_limit": pct <= self.cfg.max_dev_hold_pct,
                "limit_pct": self.cfg.max_dev_hold_pct,
            }
        except Exception as e:
            return {"ok": False, "reason": f"tx lookup failed: {e}"}

    def _bonding_curve_pda(self, mint: str) -> Pubkey:
        mint_pk = Pubkey.from_string(mint)
        pda, _ = Pubkey.find_program_address([b"bonding-curve", bytes(mint_pk)], PUMPFUN_PROGRAM_ID)
        return pda

    def _bonding_curve_ata(self, mint: str, is_token_2022: bool) -> Pubkey:
        """Associated token account owned by the bonding curve PDA (holds the pool's tokens)."""
        curve = self._bonding_curve_pda(mint)
        mint_pk = Pubkey.from_string(mint)
        token_prog = TOKEN_2022_PROGRAM if is_token_2022 else TOKEN_PROGRAM
        ata, _ = Pubkey.find_program_address(
            [bytes(curve), bytes(token_prog), bytes(mint_pk)], ATA_PROGRAM
        )
        return ata

    async def _check_holders_concentration(self, mint: str, supply_raw: int,
                                            is_token_2022: bool) -> Dict[str, Any]:
        """Fetch top holders via getTokenLargestAccounts, exclude the bonding-curve
        pool ATA, then compute top-1 and top-10 concentration percentages."""
        if not self.lt.cfg.rpc_url or supply_raw <= 0:
            return {"ok": False, "reason": "no rpc or supply"}
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts",
            "params": [mint, {"commitment": "confirmed"}],
        }
        try:
            s = await self._http()
            async with s.post(self.lt.cfg.rpc_url, json=payload, timeout=10) as r:
                data = await r.json()
            # Fail-closed if the RPC returned an error object
            if data.get("error"):
                return {"ok": False, "reason": f"rpc error: {data.get('error')}"}
            result = data.get("result")
            if result is None:
                return {"ok": False, "reason": "no result from getTokenLargestAccounts"}
            accounts = result.get("value") or []
            if not accounts:
                return {"ok": False, "reason": "empty holder list (mint may not be indexed yet)"}
            pool_ata = str(self._bonding_curve_ata(mint, is_token_2022))
            non_pool = [a for a in accounts if a.get("address") != pool_ata]
            # If we somehow didn't identify the pool ATA in the list (edge case),
            # heuristically skip the single largest account which is almost always the pool.
            if len(non_pool) == len(accounts) and accounts:
                non_pool = accounts[1:]

            def _amt(a):
                """Extract the raw (integer, atomic) balance from a getTokenLargestAccounts
                entry. Fail-CLOSED — if we can't parse, raise so the caller aborts."""
                # Primary: uiTokenAmount.amount is a string of base units (integer)
                ui_amt = a.get("uiTokenAmount") or {}
                raw_amt = ui_amt.get("amount")
                if raw_amt is None:
                    # Older RPC shape puts `amount` at the top level as a stringified int
                    raw_amt = a.get("amount")
                if raw_amt is None:
                    raise ValueError(f"holder entry has no amount: {a}")
                return int(raw_amt)

            balances = [_amt(a) for a in non_pool[:10]]
            if not balances:
                # No non-pool holders at all — mint just created with only bonding curve.
                # Fail-closed: we can't verify concentration.
                return {"ok": False, "reason": "no non-pool holders (only bonding curve present)"}
            top1 = balances[0] if balances else 0
            top10_sum = sum(balances)
            top1_pct = (top1 / supply_raw) * 100.0
            top10_pct = (top10_sum / supply_raw) * 100.0
            return {
                "ok": True,
                "top1_pct": round(top1_pct, 3),
                "top10_pct": round(top10_pct, 3),
                "top1_within_limit": top1_pct <= self.cfg.max_holder_pct,
                "top10_within_limit": top10_pct <= self.cfg.max_top10_pct,
                "top1_limit_pct": self.cfg.max_holder_pct,
                "top10_limit_pct": self.cfg.max_top10_pct,
                "non_pool_holder_count": len(non_pool),
                "pool_ata": pool_ata,
            }
        except Exception as e:
            return {"ok": False, "reason": f"holders lookup failed: {e}"}

    async def _check_curve_state(self, mint: str) -> Dict[str, Any]:
        """Read the bonding-curve PDA account. Layout after 8-byte anchor discriminator:
        virtual_token_reserves u64, virtual_sol_reserves u64, real_token_reserves u64,
        real_sol_reserves u64, token_total_supply u64, complete u8."""
        if not self.lt.cfg.rpc_url:
            return {"ok": False, "reason": "no rpc"}
        try:
            curve_pda = self._bonding_curve_pda(mint)
        except Exception as e:
            return {"ok": False, "reason": f"pda derive failed: {e}"}
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
            "params": [str(curve_pda), {"encoding": "base64", "commitment": "confirmed"}],
        }
        try:
            s = await self._http()
            async with s.post(self.lt.cfg.rpc_url, json=payload, timeout=10) as r:
                data = await r.json()
            val = (data.get("result") or {}).get("value") or {}
            data_field = val.get("data") or []
            if not data_field or not isinstance(data_field, list) or len(data_field) < 1:
                return {"ok": False, "reason": "curve account has no data (mint may not be indexed yet)"}
            raw = base64.b64decode(data_field[0])
            if len(raw) < 49:
                return {"ok": False, "reason": f"curve data too short: {len(raw)} bytes"}
            # Skip 8-byte anchor discriminator
            vtr, vsr, rtr, rsr, tts = struct.unpack("<QQQQQ", raw[8:48])
            complete = bool(raw[48])
            real_sol = rsr / LAMPORTS_PER_SOL
            return {
                "ok": True,
                "curve_pda": str(curve_pda),
                "virtual_sol_reserves": vsr,
                "real_sol_reserves_lamports": rsr,
                "real_sol_reserves": round(real_sol, 6),
                "real_token_reserves": rtr,
                "token_total_supply": tts,
                "complete": complete,
                "liquidity_ok": (real_sol >= self.cfg.min_curve_sol) and (not complete),
                "min_curve_sol": self.cfg.min_curve_sol,
            }
        except Exception as e:
            return {"ok": False, "reason": f"curve read failed: {e}"}




    # -------- pumpportal tx build --------
    async def _pumpportal_build_tx(self, action: str, mint: str, amount, denominated_in_sol: bool) -> bytes:
        """Ask PumpPortal to build an unsigned VersionedTransaction for a bonding-curve trade.
        Returns raw serialized tx bytes."""
        if not self.lt.wallet_pubkey:
            raise RuntimeError("wallet not loaded")
        body = {
            "publicKey": self.lt.wallet_pubkey,
            "action": action,                        # "buy" or "sell"
            "mint": mint,
            "amount": amount,                        # SOL (for buy denominatedInSol=true) or token count (for sell w/ false)
            "denominatedInSol": "true" if denominated_in_sol else "false",
            "slippage": self.cfg.slippage_pct,
            "priorityFee": self.cfg.priority_fee_sol,
            "pool": "pump",                          # target bonding curve directly
        }
        s = await self._http()
        async with s.post(PUMPPORTAL_TRADE_LOCAL_URL, json=body, timeout=15) as r:
            if r.status != 200:
                err = await r.text()
                raise RuntimeError(f"pumpportal {r.status}: {err[:200]}")
            return await r.read()

    async def _sign_and_send(self, tx_bytes: bytes) -> Dict[str, Any]:
        """Sign the pumpportal-built tx with our local wallet, submit via QuickNode.
        Records submit/landing metrics via tx_landings for landing-rate analysis."""
        from tx_landings import get_tracker
        tracker = get_tracker(self.db)

        unsigned = VersionedTransaction.from_bytes(tx_bytes)
        signed = VersionedTransaction(unsigned.message, [self.lt.wallet])
        signed_bytes = bytes(signed)
        sig = str(signed.signatures[0])

        # Submit via QuickNode sendTransaction (base64)
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
            "params": [base64.b64encode(signed_bytes).decode(),
                       {"encoding": "base64", "skipPreflight": False, "maxRetries": 3}],
        }
        submitted_at = time.time()
        s = await self._http()
        async with s.post(self.lt.cfg.rpc_url, json=payload, timeout=20) as r:
            data = await r.json()
        if "error" in data:
            await tracker.record("pumpfun_autobuy", sig, submitted_at, None, False, str(data["error"]))
            return {"success": False, "error": str(data["error"]), "signature": sig}

        # Poll confirmation (up to 60s)
        deadline = time.time() + 60
        confirmed = False
        err = None
        landed_at = None
        while time.time() < deadline:
            await asyncio.sleep(2)
            try:
                q = {"jsonrpc": "2.0", "id": 1, "method": "getSignatureStatuses",
                     "params": [[sig], {"searchTransactionHistory": False}]}
                async with s.post(self.lt.cfg.rpc_url, json=q, timeout=10) as r:
                    st_data = await r.json()
                v = ((st_data.get("result") or {}).get("value") or [None])[0]
                if v:
                    if v.get("err"):
                        err = str(v.get("err"))
                        break
                    if v.get("confirmationStatus") in ("confirmed", "finalized"):
                        confirmed = True
                        landed_at = time.time()
                        break
            except Exception:
                pass
        await tracker.record("pumpfun_autobuy", sig, submitted_at, landed_at, confirmed, err)
        return {"success": confirmed, "signature": sig, "error": err}

    # -------- main buy path (called by sniper on detection) --------
    async def maybe_buy(self, mint: str, signature: Optional[str] = None) -> Dict[str, Any]:
        self.attempts += 1
        self._reset_day_if_needed()

        if not self.cfg.enabled:
            self.last_reason = "auto-buy disabled (PUMPFUN_AUTO_BUY_ENABLED=false)"
            return {"ok": False, "reason": self.last_reason}
        if not self.lt.ready:
            self.last_reason = "live_trader not ready (SIMULATION_MODE / LIVE_TRADING_ENABLED / wallet)"
            return {"ok": False, "reason": self.last_reason}
        if len(self.positions) >= self.cfg.max_concurrent:
            self.last_reason = f"max_concurrent {self.cfg.max_concurrent} positions open"
            return {"ok": False, "reason": self.last_reason}
        if self.day_spent_sol + self.cfg.buy_sol > self.cfg.daily_budget_sol:
            self.last_reason = f"daily SOL budget {self.cfg.daily_budget_sol} exhausted"
            return {"ok": False, "reason": self.last_reason}
        elapsed = time.time() - self.last_buy_at
        if elapsed < self.cfg.cooldown_sec:
            self.last_reason = f"cooldown {int(self.cfg.cooldown_sec - elapsed)}s"
            return {"ok": False, "reason": self.last_reason}
        if not mint or len(mint) < 32:
            self.last_reason = "invalid mint"
            return {"ok": False, "reason": self.last_reason}

        # Wait for the initial buy/liquidity to settle
        await asyncio.sleep(self.cfg.settle_delay_sec)

        # Safety pre-check: mint/freeze authorities + Token-2022 extensions.
        # Helius (and Solana RPC in general) has indexing lag AFTER a fresh mint —
        # the mint account can return empty data for several seconds. Retry until
        # we get a parsed mint account or exhaust attempts.
        safety = None
        for _ in range(5):
            safety = await self._check_mint_safety(mint)
            if safety.get("ok") and safety.get("decimals") is not None:
                break
            await asyncio.sleep(1.0)
        if self.cfg.require_authorities_revoked and not safety.get("authorities_safe"):
            self.rejects_safety += 1
            self.last_reason = f"safety_fail: mint_rev={safety.get('mint_authority_revoked')} freeze_rev={safety.get('freeze_authority_revoked')}"
            await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety})
            return {"ok": False, "reason": self.last_reason, "safety": safety}

        if self.cfg.reject_dangerous_t22 and safety.get("is_token_2022") and not safety.get("extensions_safe"):
            self.rejects_safety += 1
            self.last_reason = f"t22_extensions_fail: {safety.get('dangerous_extensions')}"
            await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety})
            return {"ok": False, "reason": self.last_reason, "safety": safety}

        # Dev-hold rug filter (STRICT: fail-closed — if we can't verify, we don't buy)
        dev = None
        if self.cfg.max_dev_hold_pct < 100.0:
            if not signature:
                self.rejects_safety += 1
                self.last_reason = "dev_hold_unknown: no detection signature (cannot verify creator holdings)"
                await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety})
                return {"ok": False, "reason": self.last_reason}
            # Retry the tx fetch up to 6 times (~9s) because Helius often returns
            # null on `getTransaction` for the first few seconds after a fresh mint
            # (WSS pushes on `processed`, but the HTTP node needs to advance to
            # `confirmed` and finish indexing before the tx meta is queryable).
            dev = None
            for attempt in range(6):
                dev = await self._check_dev_hold(signature, mint, safety.get("supply"))
                if dev.get("ok"):
                    break
                await asyncio.sleep(1.5)
            if not dev.get("ok"):
                self.rejects_safety += 1
                self.last_reason = f"dev_hold_unverifiable: {dev.get('reason')}"
                await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety, "dev": dev})
                return {"ok": False, "reason": self.last_reason, "dev": dev}
            if not dev.get("within_limit"):
                self.rejects_safety += 1
                self.last_reason = f"dev_hold_fail: {dev.get('dev_hold_pct')}% > {self.cfg.max_dev_hold_pct}% limit"
                await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety, "dev": dev})
                return {"ok": False, "reason": self.last_reason, "dev": dev}

        # Bonding curve liquidity + not-graduated check. Also indexing-lag-sensitive
        # (the PDA read can return an empty account for a few seconds post-mint).
        curve = None
        for _ in range(5):
            curve = await self._check_curve_state(mint)
            if curve.get("ok"):
                break
            await asyncio.sleep(1.0)
        if not curve.get("ok"):
            self.rejects_safety += 1
            self.last_reason = f"curve_read_fail: {curve.get('reason')}"
            await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety, "dev": dev, "curve": curve})
            return {"ok": False, "reason": self.last_reason, "curve": curve}
        if curve.get("complete"):
            self.rejects_safety += 1
            self.last_reason = "curve_graduated (already migrated to PumpSwap)"
            await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety, "dev": dev, "curve": curve})
            return {"ok": False, "reason": self.last_reason, "curve": curve}
        if not curve.get("liquidity_ok"):
            self.rejects_safety += 1
            self.last_reason = f"low_liquidity: curve_sol={curve.get('real_sol_reserves')} < min {self.cfg.min_curve_sol}"
            await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety, "dev": dev, "curve": curve})
            return {"ok": False, "reason": self.last_reason, "curve": curve}

        # Top-holder concentration filter (STRICT: fail-closed)
        holders = None
        if self.cfg.max_top10_pct < 100.0 or self.cfg.max_holder_pct < 100.0:
            try:
                supply_int = int(safety.get("supply") or 0)
            except Exception:
                supply_int = 0
            holders = await self._check_holders_concentration(
                mint, supply_int, bool(safety.get("is_token_2022"))
            )
            if not holders.get("ok"):
                self.rejects_safety += 1
                self.last_reason = f"holders_unverifiable: {holders.get('reason')}"
                await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety, "dev": dev, "curve": curve, "holders": holders})
                return {"ok": False, "reason": self.last_reason, "holders": holders}
            if not holders.get("top1_within_limit"):
                self.rejects_safety += 1
                self.last_reason = f"top1_holder_fail: {holders.get('top1_pct')}% > {self.cfg.max_holder_pct}% limit"
                await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety, "dev": dev, "curve": curve, "holders": holders})
                return {"ok": False, "reason": self.last_reason, "holders": holders}
            if not holders.get("top10_within_limit"):
                self.rejects_safety += 1
                self.last_reason = f"top10_holders_fail: {holders.get('top10_pct')}% > {self.cfg.max_top10_pct}% limit"
                await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety, "dev": dev, "curve": curve, "holders": holders})
                return {"ok": False, "reason": self.last_reason, "holders": holders}

        # Entry-mcap window gate (mcap mode only) — refuse to buy above ceiling
        entry_mcap_usd = 0.0
        if self.cfg.ladder_mode == "mcap":
            try:
                entry_mcap_usd = await self._current_mcap_usd(mint, supply_raw_hint=int(safety.get("supply") or 0)) or 0.0
            except Exception:
                entry_mcap_usd = 0.0
            if entry_mcap_usd <= 0:
                self.rejects_safety += 1
                self.last_reason = "entry_mcap_unverifiable"
                await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety})
                return {"ok": False, "reason": self.last_reason}
            if entry_mcap_usd > self.cfg.entry_mcap_max_usd:
                self.rejects_safety += 1
                self.last_reason = f"entry_mcap_too_high: ${entry_mcap_usd:.0f} > ${self.cfg.entry_mcap_max_usd:.0f}"
                await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "entry_mcap_usd": entry_mcap_usd})
                return {"ok": False, "reason": self.last_reason}

        # Build tx via pumpportal
        try:
            tx_bytes = await self._pumpportal_build_tx("buy", mint, self.cfg.buy_sol, denominated_in_sol=True)
        except Exception as e:
            self.last_reason = f"pumpportal build failed: {str(e)[:120]}"
            return {"ok": False, "reason": self.last_reason}

        # FIRE
        logger.info(f"[pumpfun-buy] FIRING {mint[:8]}... size={self.cfg.buy_sol} SOL")
        result = await self._sign_and_send(tx_bytes)
        self.buys_fired += 1
        self.last_buy_at = time.time()
        self.day_spent_sol += self.cfg.buy_sol
        self.last_reason = f"BUY sent for {mint[:8]}..."

        if not result.get("success"):
            await self._record_position_event(mint, "buy_failed", {
                "reason": result.get("error"),
                "signature": result.get("signature"),
                "solscan_url": f"https://solscan.io/tx/{result.get('signature')}" if result.get("signature") else None,
            })
            return {"ok": False, "reason": f"buy tx failed: {result.get('error')}", "signature": result.get("signature")}

        # Position opened. Capture entry price + mcap from bonding curve NOW (right after buy)
        # so the ladder has a reference. Slight over-estimate of fill price (curve moved by
        # our own buy) but close enough for milestone multipliers.
        entry_price = 0.0
        try:
            entry_curve = await self._check_curve_state_full(mint)
            if entry_curve.get("ok"):
                vsr = entry_curve.get("virtual_sol_reserves") or 0
                vtr = entry_curve.get("virtual_token_reserves") or 0
                if vsr and vtr:
                    entry_price = vsr / vtr
        except Exception:
            pass

        # If mcap mode, capture post-buy mcap too (or reuse gate's pre-buy value)
        pos_entry_mcap_usd = entry_mcap_usd if self.cfg.ladder_mode == "mcap" else 0.0
        if self.cfg.ladder_mode == "mcap" and pos_entry_mcap_usd == 0:
            try:
                pos_entry_mcap_usd = await self._current_mcap_usd(mint, supply_raw_hint=int(safety.get("supply") or 0)) or 0.0
            except Exception:
                pos_entry_mcap_usd = 0.0

        pos = Position(
            mint=mint,
            buy_sol=self.cfg.buy_sol,
            token_amount=0.0,  # unknown; sell path uses percentage of token account balance
            buy_signature=result["signature"],
            opened_at=time.time(),
            entry_price=entry_price,
            entry_mcap_usd=pos_entry_mcap_usd,
            supply_raw=int(safety.get("supply") or 0),
        )
        self.positions[mint] = pos
        self.buys_successful += 1

        await self._record_position_event(mint, "opened", {
            "buy_signature": result["signature"],
            "buy_sol": self.cfg.buy_sol,
            "solscan_url": f"https://solscan.io/tx/{result['signature']}",
            "pumpfun_url": f"https://pump.fun/coin/{mint}",
            "safety": safety,
            "dev": dev,
            "curve": curve,
            "holders": holders,
            "ladder_mode": self.cfg.ladder_mode,
            "entry_mcap_usd": pos_entry_mcap_usd,
        })
        return {"ok": True, "signature": result["signature"], "mint": mint}

    # -------- monitor / exit loop --------
    async def monitor_positions(self):
        while True:
            try:
                await asyncio.sleep(self.cfg.check_interval_sec)
                if not self.positions or not self.lt.ready:
                    continue
                to_close = []
                for mint, pos in list(self.positions.items()):
                    decision = await self._evaluate_position(pos)
                    if decision:
                        to_close.append((mint, decision))
                for mint, decision in to_close:
                    await self._sell(mint, decision)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[pumpfun-monitor] loop error: {e}")

    async def _get_sol_usd(self) -> float:
        """Return SOL/USD spot price, cached 30s. Uses Jupiter SOL→USDC quote."""
        now = time.time()
        cached_price = _sol_usd_cache["price"]
        if cached_price and (now - _sol_usd_cache["at"]) < 30:
            return cached_price
        try:
            q = await self.lt.jupiter.get_quote(SOL_MINT, USDC_MINT, LAMPORTS_PER_SOL, 500)
            usdc_out = int(q.get("outAmount") or 0) / 1_000_000  # USDC has 6 decimals
            if usdc_out > 0:
                _sol_usd_cache["price"] = usdc_out
                _sol_usd_cache["at"] = now
                return usdc_out
        except Exception:
            pass
        return cached_price or 150.0    # fallback if all price sources fail

    async def _current_mcap_usd(self, mint: str, supply_raw_hint: int = 0) -> Optional[float]:
        """Fully-diluted market cap in USD from bonding-curve state × SOL/USD price."""
        curve = await self._check_curve_state_full(mint)
        if not curve.get("ok"):
            return None
        vsr = curve.get("virtual_sol_reserves") or 0
        vtr = curve.get("virtual_token_reserves") or 0
        if not vsr or not vtr:
            return None
        # pump.fun tokens use 6 decimals and standard 1B supply.
        # If caller passed the exact supply from getAccountInfo, prefer that; else 1e15 raw.
        supply_raw = supply_raw_hint or int(1e15)
        # mcap in lamports = price_per_raw × supply_raw = (vsr / vtr) × supply_raw
        mcap_lamports = (vsr / vtr) * supply_raw
        mcap_sol = mcap_lamports / LAMPORTS_PER_SOL
        sol_usd = await self._get_sol_usd()
        return mcap_sol * sol_usd

    async def _current_curve_price(self, mint: str) -> Optional[float]:
        """Live bonding-curve price in SOL per raw token unit.
        price = virtual_sol_reserves / virtual_token_reserves. Single RPC call."""
        curve = await self._check_curve_state_full(mint)
        if not curve.get("ok"):
            return None
        vsr = curve.get("virtual_sol_reserves") or 0
        vtr = curve.get("virtual_token_reserves") or 0
        if not vsr or not vtr:
            return None
        return vsr / vtr

    async def _check_curve_state_full(self, mint: str) -> Dict[str, Any]:
        """Same as _check_curve_state but also returns virtual_token_reserves.
        (Kept separate to avoid changing the safety-filter's public shape.)"""
        if not self.lt.cfg.rpc_url:
            return {"ok": False, "reason": "no rpc"}
        try:
            curve_pda = self._bonding_curve_pda(mint)
        except Exception as e:
            return {"ok": False, "reason": f"pda derive failed: {e}"}
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
            "params": [str(curve_pda), {"encoding": "base64", "commitment": "confirmed"}],
        }
        try:
            s = await self._http()
            async with s.post(self.lt.cfg.rpc_url, json=payload, timeout=10) as r:
                data = await r.json()
            val = (data.get("result") or {}).get("value") or {}
            data_field = val.get("data") or []
            if not data_field or len(data_field) < 1:
                return {"ok": False, "reason": "no data"}
            raw = base64.b64decode(data_field[0])
            if len(raw) < 49:
                return {"ok": False, "reason": "too short"}
            vtr, vsr, rtr, rsr, tts = struct.unpack("<QQQQQ", raw[8:48])
            complete = bool(raw[48])
            return {
                "ok": True,
                "virtual_token_reserves": vtr,
                "virtual_sol_reserves": vsr,
                "real_sol_reserves": rsr,
                "complete": complete,
            }
        except Exception as e:
            return {"ok": False, "reason": f"read: {e}"}

    async def _evaluate_position(self, pos: Position) -> Optional[Dict[str, Any]]:
        """Return {action, sell_pct, reason, ratio, milestone_index, mode} or None.
        Dispatches between ratio-mode and mcap-mode based on self.cfg.ladder_mode."""
        age = time.time() - pos.opened_at
        hold_expired = age >= self.cfg.hold_max_seconds
        mode = self.cfg.ladder_mode

        if mode == "mcap":
            # Absolute USD mcap thresholds; state machine treats them as generic signal values
            signal = await self._current_mcap_usd(pos.mint, supply_raw_hint=pos.supply_raw)
            if signal is None:
                if hold_expired:
                    return {"action": "sell_all", "sell_pct": 100.0,
                            "reason": "time_limit_no_mcap", "ratio": None,
                            "milestone_index": None, "mode": "mcap"}
                return None
            action = evaluate_ladder(
                ratio=signal,
                milestones=self.cfg.ladder_mcap,
                state=pos.ladder_state,
                rug_stop_mult=self.cfg.rug_stop_mcap_usd,
                hold_expired=hold_expired,
            )
            signal_display = signal
        else:
            # ratio mode (existing behavior)
            # Lazily recover entry_price if the buy-time curve read failed
            if not pos.entry_price:
                price = await self._current_curve_price(pos.mint)
                if price:
                    pos.entry_price = price
                    logger.info(f"[pumpfun-eval] lazy entry_price backfill for {pos.mint[:8]}: {price:g}")
            ratio = None
            if pos.entry_price and pos.entry_price > 0:
                current_price = await self._current_curve_price(pos.mint)
                if current_price is not None:
                    ratio = current_price / pos.entry_price
            if ratio is None:
                if hold_expired:
                    return {"action": "sell_all", "sell_pct": 100.0,
                            "reason": "time_limit_no_quote", "ratio": None,
                            "milestone_index": None, "mode": "ratio"}
                return None
            action = evaluate_ladder(
                ratio=ratio,
                milestones=self.cfg.ladder,
                state=pos.ladder_state,
                rug_stop_mult=self.cfg.rug_stop_mult,
                hold_expired=hold_expired,
            )
            signal_display = ratio

        if action.type == LadderActionType.HOLD:
            return None

        # Fee-economic gate on partial sells (mcap mode only, where signal is USD).
        # Skip a partial sell that would net less than min_sell_usd worth after fees.
        if mode == "mcap" and action.type == LadderActionType.SELL_PARTIAL:
            sol_usd = await self._get_sol_usd()
            if pos.entry_mcap_usd > 0:
                ratio_from_entry = signal_display / pos.entry_mcap_usd
                partial_value_usd = pos.buy_sol * sol_usd * ratio_from_entry * (action.sell_pct / 100.0) * (pos.remaining_pct_of_original / 100.0)
                if partial_value_usd < self.cfg.min_sell_usd:
                    logger.info(f"[pumpfun-eval] skipping {action.reason}: partial value ${partial_value_usd:.3f} < min ${self.cfg.min_sell_usd}")
                    # Mark milestone as consumed WITHOUT selling — advance so ladder progresses
                    if action.milestone_index is not None:
                        pos.ladder_state.milestones_hit.append(action.milestone_index)
                        m = self.cfg.ladder_mcap[action.milestone_index]
                        if pos.ladder_state.current_floor is None or m.floor_after > pos.ladder_state.current_floor:
                            pos.ladder_state.current_floor = m.floor_after
                    return None

        return {
            "action": "sell_all" if action.type == LadderActionType.SELL_ALL else "sell_partial",
            "sell_pct": action.sell_pct,
            "reason": action.reason,
            "ratio": signal_display,
            "milestone_index": action.milestone_index,
            "mode": mode,
        }

    async def _sell(self, mint: str, decision: Dict[str, Any]):
        """Ladder-aware sell: partial or full, via PumpPortal amount='XX%' (of current
        wallet balance) — no need to track exact token count."""
        pos = self.positions.get(mint)
        if not pos or pos.closed:
            return
        sell_pct = float(decision.get("sell_pct") or 100.0)
        # PumpPortal wants a string like "80%"; clamp to sensible bounds
        sell_pct = max(1.0, min(100.0, sell_pct))
        reason = decision.get("reason") or "unknown"
        ratio = decision.get("ratio")
        milestone_index = decision.get("milestone_index")
        is_partial = decision.get("action") == "sell_partial"

        logger.info(f"[pumpfun-sell] {mint[:8]} {reason} pct={sell_pct:.1f}%")
        try:
            tx_bytes = await self._pumpportal_build_tx(
                "sell", mint, f"{sell_pct:g}%", denominated_in_sol=False
            )
        except Exception as e:
            logger.warning(f"[pumpfun-sell] build failed: {e}")
            return
        result = await self._sign_and_send(tx_bytes)
        self.sells_fired += 1

        if not result.get("success"):
            await self._record_position_event(mint, "sell_failed", {
                "reason": reason, "sell_pct": sell_pct, "ratio": ratio,
                "signature": result.get("signature"),
                "error": result.get("error"),
                "solscan_url": f"https://solscan.io/tx/{result.get('signature')}" if result.get("signature") else None,
            })
            return

        # Success — advance ladder state, decrement remaining_pct
        pos.remaining_pct_of_original *= (1 - sell_pct / 100.0)
        if is_partial and milestone_index is not None:
            record_milestone_hit(pos.ladder_state, self.cfg.ladder, milestone_index)

        pos.partial_sells.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "ratio": round(ratio, 3) if ratio else None,
            "sell_pct_of_current": round(sell_pct, 2),
            "signature": result["signature"],
            "milestone_index": milestone_index,
        })

        fully_closed = (not is_partial) or pos.remaining_pct_of_original < 0.5   # sub-0.5% is dust
        if fully_closed:
            pos.closed = True
            await self._record_position_event(mint, "closed", {
                "verdict": reason,
                "buy_signature": pos.buy_signature,
                "sell_signature": result["signature"],
                "buy_sol": pos.buy_sol,
                "peak_ratio": round(pos.ladder_state.peak_ratio, 3),
                "milestones_hit": pos.ladder_state.milestones_hit,
                "partial_sells": pos.partial_sells,
                "hold_seconds": round(time.time() - pos.opened_at, 1),
                "solscan_sell": f"https://solscan.io/tx/{result['signature']}",
                "success": True,
            })
            try:
                await self.db.trades.insert_one({
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "pair": f"SOL->{mint[:6]}..->SOL",
                    "type": "live_pumpfun_snipe",
                    "amount_sol": pos.buy_sol,
                    "success": True,
                    "signature": result["signature"],
                    "buy_signature": pos.buy_signature,
                    "solscan_url": f"https://solscan.io/tx/{result['signature']}",
                    "simulation": False,
                    "mint": mint,
                    "verdict": reason,
                    "peak_ratio": round(pos.ladder_state.peak_ratio, 3),
                    "milestones_hit": len(pos.ladder_state.milestones_hit),
                })
            except Exception as e:
                logger.warning(f"[pumpfun-sell] mongo insert failed: {e}")
            self.positions.pop(mint, None)
        else:
            await self._record_position_event(mint, "partial_sell", {
                "reason": reason,
                "ratio": round(ratio, 3) if ratio else None,
                "sell_pct_of_current": round(sell_pct, 2),
                "remaining_pct_of_original": round(pos.remaining_pct_of_original, 2),
                "sell_signature": result["signature"],
                "solscan_sell": f"https://solscan.io/tx/{result['signature']}",
                "milestone_index": milestone_index,
                "milestones_hit": list(pos.ladder_state.milestones_hit),
                "current_floor": pos.ladder_state.current_floor,
                "peak_ratio": round(pos.ladder_state.peak_ratio, 3),
            })

    async def _record_position_event(self, mint: str, event: str, data: Dict):
        try:
            await self.db.pumpfun_positions.insert_one({
                "at": datetime.now(timezone.utc).isoformat(),
                "mint": mint,
                "event": event,
                **data,
            })
        except Exception:
            pass

    def status(self) -> Dict[str, Any]:
        self._reset_day_if_needed()
        return {
            "enabled": self.cfg.enabled,
            "config": {
                "buy_sol": self.cfg.buy_sol,
                "daily_budget_sol": self.cfg.daily_budget_sol,
                "max_concurrent": self.cfg.max_concurrent,
                "cooldown_sec": self.cfg.cooldown_sec,
                "require_authorities_revoked": self.cfg.require_authorities_revoked,
                "hold_max_seconds": self.cfg.hold_max_seconds,
                "take_profit_mult": self.cfg.take_profit_mult,
                "stop_loss_mult": self.cfg.stop_loss_mult,
                "settle_delay_sec": self.cfg.settle_delay_sec,
                "slippage_pct": self.cfg.slippage_pct,
                "priority_fee_sol": self.cfg.priority_fee_sol,
                "max_dev_hold_pct": self.cfg.max_dev_hold_pct,
                "max_top10_pct": self.cfg.max_top10_pct,
                "max_holder_pct": self.cfg.max_holder_pct,
                "min_curve_sol": self.cfg.min_curve_sol,
                "reject_dangerous_t22": self.cfg.reject_dangerous_t22,
            },
            "day_spent_sol": round(self.day_spent_sol, 6),
            "day_budget_remaining_sol": round(self.cfg.daily_budget_sol - self.day_spent_sol, 6),
            "open_positions": len(self.positions),
            "position_mints": list(self.positions.keys()),
            "counters": {
                "attempts": self.attempts,
                "buys_fired": self.buys_fired,
                "buys_successful": self.buys_successful,
                "sells_fired": self.sells_fired,
                "rejects_safety": self.rejects_safety,
            },
            "last_reason": self.last_reason,
            "live_trader_ready": self.lt.ready,
            "execution_backend": "pumpportal_local_tx + quicknode_rpc",
            "tp_sl_enforced": True,
            "ladder_mode": self.cfg.ladder_mode,
            "exit_policy": (
                f"[{self.cfg.ladder_mode}] "
                + (f"mcap ladder={self.cfg.ladder_mcap_cfg}, rug_stop_mcap_usd=${self.cfg.rug_stop_mcap_usd}, entry_mcap_max=${self.cfg.entry_mcap_max_usd}, min_sell=${self.cfg.min_sell_usd}"
                   if self.cfg.ladder_mode == "mcap"
                   else f"ratio ladder={self.cfg.ladder_cfg}, rug_stop={self.cfg.rug_stop_mult}x")
            ),
            "ladder": [
                {"mult": m.mult, "sell_pct": m.sell_pct_of_remaining, "floor_after": m.floor_after}
                for m in self.cfg.ladder
            ],
            "ladder_mcap": [
                {"mcap_usd": m.mult, "sell_pct": m.sell_pct_of_remaining, "floor_after_usd": m.floor_after}
                for m in self.cfg.ladder_mcap
            ],
            "rug_stop_mult": self.cfg.rug_stop_mult,
            "rug_stop_mcap_usd": self.cfg.rug_stop_mcap_usd,
            "entry_mcap_max_usd": self.cfg.entry_mcap_max_usd,
            "min_sell_usd": self.cfg.min_sell_usd,
        }


_instance: Optional[PumpFunAutoBuyer] = None


def get_pumpfun_autobuyer(db=None) -> PumpFunAutoBuyer:
    global _instance
    if _instance is None:
        if db is None:
            raise RuntimeError("first call must pass db")
        _instance = PumpFunAutoBuyer(db)
    return _instance
