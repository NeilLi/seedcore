#!/usr/bin/env python3
"""Launch the bounded simulation rehearsal on localhost. No device connections."""

import argparse
from pathlib import Path

from seedcore.robotics.fast_spine.studio import create_app

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--state-dir", type=Path, default=Path("artifacts/session-lab"))
    args = parser.parse_args()
    uvicorn.run(create_app(args.state_dir), host="127.0.0.1", port=args.port)
