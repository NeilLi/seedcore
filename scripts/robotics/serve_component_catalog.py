#!/usr/bin/env python3
"""Serve the read-only part viewer on localhost. No hardware or external services."""

import argparse

from seedcore.robotics.component_catalog_api import create_app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
