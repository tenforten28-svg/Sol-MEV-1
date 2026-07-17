#!/usr/bin/env python3
"""
Update bot configuration to include 8 stablecoin pairs
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

async def update_config():
    """Update monitored pairs in database"""
    # Connect to MongoDB
    mongo_url = os.environ['MONGO_URL']
    client = AsyncIOMotorClient(mongo_url)
    db = client[os.environ['DB_NAME']]
    
    # New pairs list with 8 pairs
    new_pairs = [
        "SOL/USDC", "RAY/USDC", "ORCA/USDC", "JUP/USDC",
        "JTO/USDC", "PYTH/USDC", "SOL/USDT", "USDC/USDT"
    ]
    
    # Update config
    result = await db.config.update_one(
        {},
        {"$set": {"monitored_pairs": new_pairs}},
        upsert=False
    )
    
    if result.modified_count > 0:
        print(f"✅ Updated config with {len(new_pairs)} pairs")
    else:
        print("⚠️  No config found to update, will use default on next startup")
    
    # Verify
    config = await db.config.find_one({}, {"_id": 0})
    if config:
        print(f"\n📊 Current monitored pairs:")
        for i, pair in enumerate(config.get('monitored_pairs', []), 1):
            print(f"   {i}. {pair}")
    
    client.close()
    print("\n✅ Configuration update complete!")

if __name__ == "__main__":
    asyncio.run(update_config())
