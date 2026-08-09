"""
PUMP.FUN NEW-LISTING DETECTOR
==============================
Subscribes to pump.fun program logs via QuickNode WebSocket.
Detects every new token creation in real-time and records to MongoDB.

This module is DETECTION-ONLY in this version:
  * Watches pump.fun program for `create` instructions (new mint events)
  * Extracts mint address, creator wallet, timestamp
  * Records to db.pumpfun_detections
  * NO automatic buying yet — that requires a separate safety review

Toggle with env var PUMPFUN_SNIPER_ENABLED=true.
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import aiohttp

logger = logging.getLogger("pumpfun_sniper")

# Pump.fun program ID (mainnet)
PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


def _env_bool(k, d=False):
    return str(os.environ.get(k, str(d))).strip().lower() in ("true", "1", "yes", "on")


class PumpFunSniper:
    def __init__(self, db):
        self.db = db
        self.enabled = _env_bool("PUMPFUN_SNIPER_ENABLED", False)
        # QuickNode wss URL. Reuses the same endpoint as the main RPC.
        self.wss_url = os.environ.get("QUICKNODE_WSS_URL", "") or \
            os.environ.get("SOLANA_RPC_URL", "").replace("https://", "wss://")
        # HTTP RPC URL for tx lookups (mint extraction requires getTransaction)
        self.http_url = os.environ.get("SOLANA_RPC_URL", "").strip()
        self.task: Optional[asyncio.Task] = None
        self.running = False
        # Counters
        self.total_events = 0
        self.detections = 0
        self.last_detection_at: Optional[str] = None
        self.last_error: Optional[str] = None
        self.connection_count = 0

    def start(self):
        if not self.enabled:
            logger.info("[pumpfun] disabled via PUMPFUN_SNIPER_ENABLED")
            return
        if not self.wss_url or not self.wss_url.startswith("wss://"):
            logger.warning(f"[pumpfun] no valid WSS URL — set QUICKNODE_WSS_URL")
            return
        self.task = asyncio.create_task(self._loop())
        self.running = True
        logger.info(f"[pumpfun] sniper started (wss={self.wss_url.split('/')[2]})")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass

    async def _loop(self):
        """Reconnecting WebSocket loop. Auto-retry on disconnect."""
        base_backoff = 10
        current_backoff = base_backoff
        while self.running:
            try:
                await self._connect_and_listen()
                current_backoff = base_backoff  # reset on successful cycle
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.last_error = str(e)
                # 429 = QuickNode WSS rate limit. Back off HARD (60s+) so the
                # rate-limit window can expire instead of hammering reconnects.
                if "429" in str(e):
                    current_backoff = max(current_backoff, 60)
                logger.warning(f"[pumpfun] loop error, reconnecting in {current_backoff}s: {e}")
                await asyncio.sleep(current_backoff)
                current_backoff = min(current_backoff * 2, 300)

    async def _connect_and_listen(self):
        self.connection_count += 1
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.wss_url, timeout=aiohttp.ClientTimeout(total=30)) as ws:
                # Subscribe to pump.fun program logs
                sub_req = {
                    "jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                    "params": [
                        {"mentions": [PUMPFUN_PROGRAM]},
                        {"commitment": "processed"},
                    ],
                }
                await ws.send_str(json.dumps(sub_req))
                logger.info("[pumpfun] subscribed to program logs")

                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        data = json.loads(msg.data)
                    except Exception:
                        continue
                    if data.get("method") != "logsNotification":
                        continue
                    await self._handle_log_notification(data)

    async def _handle_log_notification(self, data: Dict[str, Any]):
        self.total_events += 1
        try:
            value = data["params"]["result"]["value"]
            logs = value.get("logs", [])
            sig = value.get("signature")
            slot = data["params"]["result"]["context"]["slot"]

            # Detect a new mint creation. Pump.fun emits "Instruction: Create" for new tokens.
            is_new_mint = any("Instruction: Create" in ln for ln in logs)
            if not is_new_mint:
                return

            # Extract mint address by fetching the tx and finding the pump.fun-suffix account.
            # Pump.fun mints are vanity addresses ending in "pump".
            candidate_mint = None
            if sig and self.http_url:
                try:
                    import aiohttp
                    payload = {
                        "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                        "params": [sig, {
                            "encoding": "jsonParsed", "commitment": "confirmed",
                            "maxSupportedTransactionVersion": 0,
                        }],
                    }
                    async with aiohttp.ClientSession() as s:
                        # Retry 3x — tx may not be indexed yet
                        for _ in range(3):
                            async with s.post(self.http_url, json=payload, timeout=6) as r:
                                data = await r.json()
                            if data.get("result"):
                                break
                            await asyncio.sleep(0.8)
                        result = data.get("result") or {}
                    keys = ((result.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
                    for k in keys:
                        addr = k.get("pubkey") if isinstance(k, dict) else k
                        if isinstance(addr, str) and addr.endswith("pump") and len(addr) >= 40:
                            candidate_mint = addr
                            break
                    # NO accountKeys[1] fallback — heuristic can mis-select creator/PDA/fee
                    # accounts, which then get dispatched as a fake mint and produce failed
                    # buys (or worse, unintended buys against the wrong token account).
                    # Prefer to skip detection than fire on a wrong address.
                except Exception as e:
                    logger.debug(f"[pumpfun-sniper] mint extract failed: {e}")

            # Counters for visibility — BUG 1 (silent 0-buys) was invisible from status
            if candidate_mint:
                self.mints_resolved = getattr(self, "mints_resolved", 0) + 1
            else:
                self.mints_unresolved = getattr(self, "mints_unresolved", 0) + 1

            self.detections += 1
            self.last_detection_at = datetime.now(timezone.utc).isoformat()

            doc = {
                "detected_at": self.last_detection_at,
                "signature": sig,
                "solscan_url": f"https://solscan.io/tx/{sig}" if sig else None,
                "pumpfun_url": f"https://pump.fun/coin/{candidate_mint}" if candidate_mint else None,
                "slot": slot,
                "candidate_mint": candidate_mint,
                "raw_log_count": len(logs),
            }
            await self.db.pumpfun_detections.insert_one(doc)

            # Cap collection at ~1000 rows
            try:
                total = await self.db.pumpfun_detections.count_documents({})
                if total > 1000:
                    oldest = await self.db.pumpfun_detections.find().sort("detected_at", 1).limit(total - 1000).to_list(None)
                    ids = [d["_id"] for d in oldest]
                    if ids:
                        await self.db.pumpfun_detections.delete_many({"_id": {"$in": ids}})
            except Exception:
                pass

            logger.info(f"[pumpfun] NEW MINT #{self.detections} → {candidate_mint or 'unknown'} (sig={sig[:8] if sig else '?'})")

            # If auto-buy is enabled, fire the buy in a background task so we don't block the WSS loop
            if candidate_mint:
                try:
                    from pumpfun_autobuy import get_pumpfun_autobuyer
                    ab = get_pumpfun_autobuyer(self.db)
                    self.buys_dispatched = getattr(self, "buys_dispatched", 0) + 1
                    asyncio.create_task(ab.maybe_buy(candidate_mint, signature=sig))
                except Exception as e:
                    logger.debug(f"[pumpfun] autobuy trigger failed: {e}")

        except Exception as e:
            logger.debug(f"[pumpfun] parse error: {e}")

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self.running and self.task is not None and not self.task.done(),
            "wss_host": self.wss_url.split("/")[2] if self.wss_url.startswith("wss://") else None,
            "total_events_received": self.total_events,
            "mints_resolved": getattr(self, "mints_resolved", 0),
            "mints_unresolved": getattr(self, "mints_unresolved", 0),
            "buys_dispatched": getattr(self, "buys_dispatched", 0),
            "new_mint_detections": self.detections,
            "last_detection_at": self.last_detection_at,
            "connection_count": self.connection_count,
            "last_error": self.last_error,
            "note": (
                "New-mint detector. If PUMPFUN_AUTO_BUY_ENABLED=true AND "
                "live_trader is ready, each detection is routed to the auto-buyer "
                "(direct bonding-curve buy via PumpPortal Local API + QuickNode)."
            ),
        }


# Singleton
_instance: Optional[PumpFunSniper] = None

def get_pumpfun_sniper(db=None) -> PumpFunSniper:
    global _instance
    if _instance is None:
        if db is None:
            raise RuntimeError("first call must pass db")
        _instance = PumpFunSniper(db)
    return _instance
