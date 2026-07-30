"""Seed a fake live_manual_swap trade, verify bot_diagnostic counts it, then clean up.
Also checks whether the 'auto-execution NOT wired' reason survives when a live trade exists
(spec says it must ALWAYS be present)."""
import asyncio
import os
import json
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone
from dotenv import dotenv_values

env = dotenv_values("/app/backend/.env")
fe = dotenv_values("/app/frontend/.env")
BASE = fe["REACT_APP_BACKEND_URL"].rstrip("/")


async def main():
    client = AsyncIOMotorClient(env["MONGO_URL"])
    db = client[env["DB_NAME"]]
    doc = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pair": "TEST_SOL/USDC",
        "type": "live_manual_swap",
        "amount_usd": 0.3,
        "signature": "TEST_SIG",
        "success": True,
        "_test_marker": "TEST_iteration4",
    }
    res = await db.trades.insert_one(doc)
    try:
        d = requests.get(f"{BASE}/api/bot_diagnostic", timeout=30).json()
        print("live_manual_swap_trades =", d["trades_last_24h"]["live_manual_swap_trades"])
        print("live_manual_swap_successful =", d["trades_last_24h"]["live_manual_swap_successful"])
        reasons = d["reasons_no_live_trades"]
        print("reasons count =", len(reasons))
        print(json.dumps(reasons, indent=1))
        has_wired = any("not wired" in r.lower() for r in reasons)
        print("AUTO_EXEC_REASON_PRESENT_WITH_LIVE_TRADE =", has_wired)
        print("verdict:", d["verdict_short"])
    finally:
        await db.trades.delete_one({"_id": res.inserted_id})
        left = await db.trades.count_documents({"_test_marker": "TEST_iteration4"})
        print("cleanup remaining test docs =", left)

asyncio.run(main())
