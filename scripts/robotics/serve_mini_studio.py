#!/usr/bin/env python3
"""Serve the offline authoring shell on localhost; no hardware endpoints."""
import argparse
import uvicorn
from seedcore.robotics.mini_studio_api import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
