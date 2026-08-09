"""
GRADUATION MONITOR
==================
Watches for pump.fun → PumpSwap AND bonk.fun/LetsBonk → Raydium CPMM graduation events
via QuickNode WSS logsSubscribe. Emits a NORMALIZED event to mongo + calls the
graduation_executor. All detection here; execution decisions are made downstream.

Event shape (mongo `graduation_events` collection + downstream callback):
{
  "source": "pumpswap" | "bonk_cpmm",
  "mint": "<base mint address>",
  "pool_address": "<AMM pool account>",
  "dex": "pumpswap" | "raydium_cpmm",
  "reserves_sol": <float, real SOL in pool>,
  "signature": "<graduation tx signature>",
  "detected_at": ISO,
  "confirmed_at": ISO,
  "latency_ms": <int, detection→confirmation>,
  "slot": <int>
}

Two independent WSS subscriptions:
- PumpSwap program: pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA
  Filter for logs containing "Instruction: CreatePool"
- Raydium LaunchLab program: LanMV9UNbk6iCfu4pVeMxKUKQg3jTsA9F5Ke8V5nJ8t
  (subscribing here instead of CPMM directly to avoid the noisy CPMM swap firehose;
  LaunchLab only emits on bonk.fun activity, migration events pop out cleanly)
  Filter for logs mentioning migration.
"""
import os
import json
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable

import websockets
import aiohttp

logger = logging.getLogger("graduation_monitor")

PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
LAUNCHLAB_PROGRAM_ID = "LanMV9UNbk6iCfu4pVeMxKUKQg3jTsA9F5Ke8V5nJ8t"
RAYDIUM_CPMM_PROGRAM_ID = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
SOL_MINT = "So11111111111111111111111111111111111111112"
WSOL_MINT = SOL_MINT

# Log-line heuristics: both platforms emit consistent instruction names
PUMPSWAP_CREATE_MARKERS = ("Instruction: CreatePool", "Instruction: Initialize")
LAUNCHLAB_MIGRATE_MARKERS = ("Instruction: MigrateToCpmm", "Instruction: Migrate", "Instruction: MigrateToRaydium")


def _fbool(k, d=False):
    return str(os.environ.get(k, str(d))).strip().lower() in ("true", "1", "yes", "on")


class GraduationMonitorConfig:
    def __init__(self):
        self.enabled = _fbool("GRADUATION_ENABLED", False)
        self.pumpswap_enabled = _fbool("GRADUATION_PUMPSWAP_ENABLED", True)
        self.bonk_enabled = _fbool("GRADUATION_BONK_ENABLED", True)
        self.wss_url = (
            os.environ.get("QUICKNODE_WSS_URL")
            or os.environ.get("SOLANA_WSS_URL")
            or ""
        ).strip()
        self.http_url = os.environ.get("SOLANA_RPC_URL", "").strip()


class GraduationMonitor:
    def __init__(self, db, on_event: Optional[Callable] = None):
        self.db = db
        self.cfg = GraduationMonitorConfig()
        self.on_event = on_event    # async callback(event_dict)
        self.pumpswap_task: Optional[asyncio.Task] = None
        self.bonk_task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        # Metrics
        self.pumpswap_events_received = 0
        self.pumpswap_graduations_detected = 0
        self.bonk_events_received = 0
        self.bonk_graduations_detected = 0
        self.last_pumpswap_at: Optional[str] = None
        self.last_bonk_at: Optional[str] = None
        self.last_error: Optional[str] = None
        # Dedup for reconnect resiliency
        self._seen_sigs: set = set()

    def running(self) -> bool:
        return bool(
            (self.pumpswap_task and not self.pumpswap_task.done())
            or (self.bonk_task and not self.bonk_task.done())
        )

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def start(self):
        if not self.cfg.enabled:
            logger.info("[graduation] disabled (GRADUATION_ENABLED=false)")
            return
        if not self.cfg.wss_url:
            self.last_error = "no QUICKNODE_WSS_URL configured"
            logger.warning(f"[graduation] {self.last_error}")
            return
        # Ensure dedup index
        try:
            await self.db.graduation_events.create_index(
                [("signature", 1), ("source", 1)], unique=True
            )
        except Exception as e:
            logger.debug(f"[graduation] index create: {e}")

        if self.cfg.pumpswap_enabled:
            self.pumpswap_task = asyncio.create_task(
                self._subscription_loop("pumpswap", PUMPSWAP_PROGRAM_ID, PUMPSWAP_CREATE_MARKERS)
            )
        if self.cfg.bonk_enabled:
            self.bonk_task = asyncio.create_task(
                self._subscription_loop("bonk_cpmm", LAUNCHLAB_PROGRAM_ID, LAUNCHLAB_MIGRATE_MARKERS)
            )

    async def stop(self):
        for t in (self.pumpswap_task, self.bonk_task):
            if t and not t.done():
                t.cancel()
        if self._session and not self._session.closed:
            await self._session.close()

    async def _subscription_loop(self, source: str, program_id: str, markers: tuple):
        """Robust WSS loop with reconnect + backoff.
        Starts at 10s (not 1s) because QuickNode returns 429 on rapid reconnects,
        and further increases when 429 is detected."""
        backoff = 10
        while True:
            try:
                async with websockets.connect(
                    self.cfg.wss_url,
                    ping_interval=20,
                    ping_timeout=40,   # tolerate slow pongs on Helius free tier
                    close_timeout=5,
                    max_size=8_000_000,
                ) as ws:
                    sub = {
                        "jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                        "params": [
                            {"mentions": [program_id]},
                            {"commitment": "confirmed"},
                        ],
                    }
                    await ws.send(json.dumps(sub))
                    logger.info(f"[graduation:{source}] subscribed to {program_id}")
                    backoff = 10
                    async for raw in ws:
                        await self._handle_notification(source, markers, raw)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.last_error = f"{source} wss: {e}"
                # 429 = QuickNode plan / concurrent WSS limit. Back off HARD to give
                # the rate-limit window (typically 60s) time to expire.
                is_429 = "429" in str(e)
                if is_429:
                    backoff = max(backoff, 60)
                logger.warning(f"[graduation:{source}] wss error: {e}; reconnect in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

    async def _handle_notification(self, source: str, markers: tuple, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        params = msg.get("params") or {}
        result = (params.get("result") or {})
        value = result.get("value") or {}
        logs = value.get("logs") or []
        sig = value.get("signature")
        slot = (result.get("context") or {}).get("slot")
        err = value.get("err")

        # Counters
        if source == "pumpswap":
            self.pumpswap_events_received += 1
        else:
            self.bonk_events_received += 1

        if err or not sig or sig in self._seen_sigs:
            return
        # Marker match
        matched = any(any(m in ln for m in markers) for ln in logs)
        if not matched:
            return
        self._seen_sigs.add(sig)
        # cap dedup set memory
        if len(self._seen_sigs) > 10000:
            self._seen_sigs = set(list(self._seen_sigs)[-5000:])

        # Extract details from the actual tx
        detected_at = datetime.now(timezone.utc)
        detail = await self._extract_pool_details(sig, source)
        if not detail:
            return

        event = {
            "source": source,
            "mint": detail["mint"],
            "pool_address": detail["pool_address"],
            "dex": "pumpswap" if source == "pumpswap" else "raydium_cpmm",
            "reserves_sol": detail["reserves_sol"],
            "signature": sig,
            "slot": slot,
            "detected_at": detected_at.isoformat(),
            "confirmed_at": detail.get("block_time_iso"),
            "latency_ms": detail.get("latency_ms"),
            "solscan_url": f"https://solscan.io/tx/{sig}",
        }

        # Counters + last-seen
        if source == "pumpswap":
            self.pumpswap_graduations_detected += 1
            self.last_pumpswap_at = detected_at.isoformat()
        else:
            self.bonk_graduations_detected += 1
            self.last_bonk_at = detected_at.isoformat()

        # Persist (idempotent via unique index)
        try:
            await self.db.graduation_events.insert_one(dict(event))
        except Exception:
            return  # duplicate — already saw it

        logger.info(
            f"[graduation:{source}] mint={detail['mint'][:8]} pool={detail['pool_address'][:8]} "
            f"reserves={detail['reserves_sol']} SOL latency={detail.get('latency_ms')}ms"
        )

        # Downstream callback (executor)
        if self.on_event:
            try:
                asyncio.create_task(self.on_event(event))
            except Exception as e:
                logger.warning(f"[graduation:{source}] callback dispatch: {e}")

    async def _extract_pool_details(self, sig: str, source: str) -> Optional[Dict[str, Any]]:
        """Fetch the graduation tx and extract mint + pool + SOL reserves from
        postTokenBalances / native balance deltas."""
        if not self.cfg.http_url:
            return None
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
            "params": [sig, {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0,
            }],
        }
        # Retry a few times — freshly confirmed tx sometimes returns null
        result = None
        for _ in range(5):
            try:
                s = await self._http()
                async with s.post(self.cfg.http_url, json=payload, timeout=10) as r:
                    data = await r.json()
                result = data.get("result")
                if result:
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        if not result:
            return None
        meta = result.get("meta") or {}
        tx = result.get("transaction") or {}
        message = tx.get("message") or {}
        account_keys = message.get("accountKeys") or []
        block_time = result.get("blockTime")
        latency_ms = None
        block_time_iso = None
        if block_time:
            block_time_iso = datetime.fromtimestamp(block_time, tz=timezone.utc).isoformat()
            latency_ms = int((time.time() - block_time) * 1000)

        # Find the base mint = the non-SOL token touched in the tx
        post_balances = meta.get("postTokenBalances") or []
        base_mint = None
        pool_owner = None       # the pool account (SPL token account owner for both sides)
        base_pool_balance = 0
        for b in post_balances:
            m = b.get("mint")
            if not m:
                continue
            if m != WSOL_MINT and base_mint is None:
                base_mint = m
                pool_owner = b.get("owner")
                try:
                    base_pool_balance = int((b.get("uiTokenAmount") or {}).get("amount") or 0)
                except Exception:
                    base_pool_balance = 0
                break
        if not base_mint or not pool_owner:
            return None

        # SOL reserves — take the WSOL side of the pool if present, else the largest
        # native SOL delta on a non-signer account.
        reserves_sol = 0.0
        for b in post_balances:
            if b.get("mint") == WSOL_MINT and b.get("owner") == pool_owner:
                try:
                    amt = int((b.get("uiTokenAmount") or {}).get("amount") or 0)
                    reserves_sol = amt / 1_000_000_000
                    break
                except Exception:
                    pass
        if reserves_sol == 0.0:
            # Fallback: largest positive lamport delta on any non-signer account
            pre_lamports = meta.get("preBalances") or []
            post_lamports = meta.get("postBalances") or []
            best = 0
            for i, (pre, post) in enumerate(zip(pre_lamports, post_lamports)):
                if i == 0:  # skip fee payer
                    continue
                delta = post - pre
                if delta > best:
                    best = delta
            reserves_sol = best / 1_000_000_000

        return {
            "mint": base_mint,
            "pool_address": pool_owner,
            "reserves_sol": round(reserves_sol, 4),
            "block_time_iso": block_time_iso,
            "latency_ms": latency_ms,
            "base_pool_balance": base_pool_balance,
        }

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.cfg.enabled,
            "running": self.running(),
            "wss_configured": bool(self.cfg.wss_url),
            "http_configured": bool(self.cfg.http_url),
            "pumpswap": {
                "enabled": self.cfg.pumpswap_enabled,
                "events_received": self.pumpswap_events_received,
                "graduations_detected": self.pumpswap_graduations_detected,
                "last_at": self.last_pumpswap_at,
            },
            "bonk_cpmm": {
                "enabled": self.cfg.bonk_enabled,
                "events_received": self.bonk_events_received,
                "graduations_detected": self.bonk_graduations_detected,
                "last_at": self.last_bonk_at,
            },
            "last_error": self.last_error,
        }


_instance: Optional[GraduationMonitor] = None


def get_graduation_monitor(db=None, on_event=None) -> GraduationMonitor:
    global _instance
    if _instance is None:
        if db is None:
            raise RuntimeError("first call must pass db")
        _instance = GraduationMonitor(db, on_event=on_event)
    return _instance
