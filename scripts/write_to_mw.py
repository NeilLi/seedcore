#!/usr/bin/env python3
"""
Write to Mw (Working Memory) script
This script writes data to the working memory system.
"""

import os
import sys
import time
import uuid

# Add the src directory to the Python path so we can import seedcore modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from seedcore.telemetry.server import app
    
    # Check if the app state has been initialized
    if hasattr(app.state, 'stats') and hasattr(app.state.stats, 'mw'):
        mw = app.state.stats.mw
        mw[str(uuid.uuid4())] = {"blob": b"hello world", "ts": time.time()}
        print("✅ Wrote one item to Mw via FastAPI app state.")
    else:
        # Fallback: Create a simple in-memory Mw if the app state isn't ready
        print("⚠️  FastAPI app state not initialized, creating fallback Mw...")
        
        # Import the StatsCollector directly
        from seedcore.telemetry.stats import StatsCollector
        
        # Create a simple in-memory working memory
        mw_cache = {}
        stats = StatsCollector(
            pg_dsn=os.getenv("PG_DSN", ""),
            neo_uri=os.getenv("NEO4J_URI", ""),
            neo_auth=(os.getenv("NEO4J_USER", ""), os.getenv("NEO4J_PASSWORD", "")),
            mw_ref=mw_cache,
        )
        
        mw = stats.mw
        mw[str(uuid.uuid4())] = {"blob": b"hello world", "ts": time.time()}
        print("✅ Wrote one item to fallback Mw.")
        print(f"   - Item count: {len(mw)}")
        print(f"   - Latest item: {list(mw.keys())[-1]}")

except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the correct directory and the seedcore package is available.")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error: {e}")
    print(f"Error type: {type(e).__name__}")
    import traceback
    print(f"Traceback: {traceback.format_exc()}")
    sys.exit(1) 