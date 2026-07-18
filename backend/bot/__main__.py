"""
HFT Bot - Main Entry Point
Run with: python -m bot
"""

import asyncio
import sys
import os

# Add bot directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from .trading_engine_v2 import main

if __name__ == "__main__":
    asyncio.run(main())
