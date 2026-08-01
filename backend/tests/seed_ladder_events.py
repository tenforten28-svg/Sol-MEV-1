import asyncio, os, sys
from datetime import datetime, timezone
sys.path.insert(0, "/app/backend")
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

env = dotenv_values("/app/backend/.env")
client = AsyncIOMotorClient(env["MONGO_URL"])
db = client[env["DB_NAME"]]

now = datetime.now(timezone.utc).isoformat()
PF = {
    "at": now, "mint": "TESTPFMINT1111111111111111111111111111111",
    "event": "partial_sell", "reason": "milestone_5x_sell_80pct",
    "ratio": 5.12, "peak_ratio": 5.4, "current_floor": 5.0,
    "sell_pct_of_current": 80.0, "remaining_pct_of_original": 20.0,
    "milestone_index": 0, "milestones_hit": [0],
    "sell_signature": "P" * 64,
    "solscan_sell": "https://solscan.io/tx/" + "P" * 64,
    "_test_seed": True,
}
GD = {
    "at": now, "mint": "TESTGDMINT1111111111111111111111111111111",
    "event": "partial_sell", "reason": "milestone_20x_sell_50pct",
    "ratio": 20.3, "peak_ratio": 21.9, "current_floor": 10.0,
    "sell_pct_of_current": 50.0, "sol_received": 0.0301,
    "milestone_index": 1, "milestones_hit": [0, 1],
    "tokens_remaining": 100000, "source": "pumpswap",
    "sell_signature": "G" * 64,
    "solscan_sell": "https://solscan.io/tx/" + "G" * 64,
    "_test_seed": True,
}


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "seed"
    if mode == "seed":
        await db.pumpfun_positions.insert_one(dict(PF))
        await db.graduation_positions.insert_one(dict(GD))
        print("seeded")
    else:
        r1 = await db.pumpfun_positions.delete_many({"_test_seed": True})
        r2 = await db.graduation_positions.delete_many({"_test_seed": True})
        print("cleaned", r1.deleted_count, r2.deleted_count)

asyncio.run(main())
