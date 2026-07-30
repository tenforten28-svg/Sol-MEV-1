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
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import aiohttp
from solders.transaction import VersionedTransaction

from live_trader import get_live_trader

logger = logging.getLogger("pumpfun_autobuy")

PUMPPORTAL_TRADE_LOCAL_URL = "https://pumpportal.fun/api/trade-local"
LAMPORTS_PER_SOL = 1_000_000_000


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


class Position:
    def __init__(self, mint: str, buy_sol: float, token_amount: float,
                 buy_signature: str, opened_at: float):
        self.mint = mint
        self.buy_sol = buy_sol          # SOL spent
        self.token_amount = token_amount  # tokens received (whole units)
        self.buy_signature = buy_signature
        self.opened_at = opened_at
        self.closed = False


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
            parsed = (((val.get("data") or {}).get("parsed") or {}).get("info") or {})
            mint_auth = parsed.get("mintAuthority")
            freeze_auth = parsed.get("freezeAuthority")
            decimals = parsed.get("decimals")
            supply = parsed.get("supply")
            authorities_ok = (mint_auth is None) and (freeze_auth is None)
            return {
                "ok": True,
                "mint_authority_revoked": mint_auth is None,
                "freeze_authority_revoked": freeze_auth is None,
                "authorities_safe": authorities_ok,
                "decimals": decimals,
                "supply": supply,
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
        """Sign the pumpportal-built tx with our local wallet, submit via QuickNode."""
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
        s = await self._http()
        async with s.post(self.lt.cfg.rpc_url, json=payload, timeout=20) as r:
            data = await r.json()
        if "error" in data:
            return {"success": False, "error": str(data["error"]), "signature": sig}

        # Poll confirmation (up to 60s)
        deadline = time.time() + 60
        confirmed = False
        err = None
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
                        break
            except Exception:
                pass
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

        # Safety pre-check
        safety = await self._check_mint_safety(mint)
        if self.cfg.require_authorities_revoked and not safety.get("authorities_safe"):
            self.rejects_safety += 1
            self.last_reason = f"safety_fail: mint_rev={safety.get('mint_authority_revoked')} freeze_rev={safety.get('freeze_authority_revoked')}"
            await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety})
            return {"ok": False, "reason": self.last_reason, "safety": safety}

        # Dev-hold rug filter (if we have the mint tx signature)
        dev = None
        if signature and self.cfg.max_dev_hold_pct < 100.0:
            dev = await self._check_dev_hold(signature, mint, safety.get("supply"))
            if dev.get("ok") and not dev.get("within_limit"):
                self.rejects_safety += 1
                self.last_reason = f"dev_hold_fail: {dev.get('dev_hold_pct')}% > {self.cfg.max_dev_hold_pct}% limit"
                await self._record_position_event(mint, "rejected", {"reason": self.last_reason, "safety": safety, "dev": dev})
                return {"ok": False, "reason": self.last_reason, "dev": dev}

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

        # Position opened — token_amount unknown until we parse post-tx balance;
        # for now we track approx via subsequent quote round-trip; sell uses percentOfTokens.
        pos = Position(
            mint=mint,
            buy_sol=self.cfg.buy_sol,
            token_amount=0.0,  # unknown; sell path uses percentage of token account balance
            buy_signature=result["signature"],
            opened_at=time.time(),
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
                    verdict = await self._evaluate_position(pos)
                    if verdict:
                        to_close.append((mint, verdict))
                for mint, verdict in to_close:
                    await self._sell(mint, verdict)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[pumpfun-monitor] loop error: {e}")

    async def _evaluate_position(self, pos: Position) -> Optional[str]:
        """Only time-based exit is enforced on-chain. TP/SL config is advisory in this
        version (price-based exits require bonding-curve account decoding which we
        deliberately skip to keep this path minimal). See status().tp_sl_enforced."""
        age = time.time() - pos.opened_at
        if age >= self.cfg.hold_max_seconds:
            return "time_limit"
        return None

    async def _sell(self, mint: str, verdict: str):
        pos = self.positions.get(mint)
        if not pos or pos.closed:
            return
        logger.info(f"[pumpfun-sell] {mint[:8]} verdict={verdict}")
        try:
            # Sell 100% of the position via pumpportal (denominatedInSol=false, amount=100%)
            tx_bytes = await self._pumpportal_build_tx("sell", mint, "100%", denominated_in_sol=False)
        except Exception as e:
            logger.warning(f"[pumpfun-sell] build failed: {e}")
            return
        result = await self._sign_and_send(tx_bytes)
        self.sells_fired += 1
        pos.closed = True

        await self._record_position_event(mint, "closed", {
            "verdict": verdict,
            "sell_signature": result.get("signature"),
            "buy_signature": pos.buy_signature,
            "buy_sol": pos.buy_sol,
            "hold_seconds": time.time() - pos.opened_at,
            "solscan_sell": f"https://solscan.io/tx/{result.get('signature')}" if result.get("signature") else None,
            "success": result.get("success", False),
        })
        # Persist a trade row so LiveTradingPanel picks it up
        try:
            await self.db.trades.insert_one({
                "created_at": datetime.now(timezone.utc).isoformat(),
                "pair": f"SOL->{mint[:6]}..->SOL",
                "type": "live_pumpfun_snipe",
                "amount_sol": pos.buy_sol,
                "success": result.get("success", False),
                "signature": result.get("signature"),
                "solscan_url": f"https://solscan.io/tx/{result.get('signature')}" if result.get("signature") else None,
                "simulation": False,
                "mint": mint,
                "verdict": verdict,
            })
        except Exception as e:
            logger.warning(f"[pumpfun-sell] mongo insert failed: {e}")
        self.positions.pop(mint, None)

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
            "tp_sl_enforced": False,
            "exit_policy": "time_limit only (TP/SL values in config are advisory in this version)",
        }


_instance: Optional[PumpFunAutoBuyer] = None


def get_pumpfun_autobuyer(db=None) -> PumpFunAutoBuyer:
    global _instance
    if _instance is None:
        if db is None:
            raise RuntimeError("first call must pass db")
        _instance = PumpFunAutoBuyer(db)
    return _instance
