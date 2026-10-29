#!/usr/bin/env python3
"""Serve the offline authoring shell on localhost; no hardware endpoints."""
import argparse
import uvicorn
from seedcore.robotics.mini_studio_api import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--admission-config", type=str, help="Explicit private service configuration for one reviewed synthetic endpoint")
    args = parser.parse_args()
    service = None
    if args.admission_config:
        from pathlib import Path
        from seedcore.robotics.cw_simulation_api import load_cw_simulation_service
        service = load_cw_simulation_service(Path(args.admission_config))
    try:
        uvicorn.run(create_app(admission_service=service), host="127.0.0.1", port=args.port)
    finally:
        if service:
            service.close()
            service._store.close()
