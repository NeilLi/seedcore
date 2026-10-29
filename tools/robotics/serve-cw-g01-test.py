#!/usr/bin/env python3
"""Temporary browser-test service with explicit synthetic registration/delegation.

No normal application imports this fixture. Keys and claims live in a temporary
directory and this endpoint cannot address any hardware or external executor.
"""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
import uvicorn

from cw_g01_test_fixture import make_test_service
from seedcore.robotics.mini_studio_api import create_app

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args()
    with TemporaryDirectory(prefix='seedcore-cw-g01-browser-') as directory:
        service,store,_=make_test_service(args.source.read_bytes(),directory,threaded=True)
        try: uvicorn.run(create_app(admission_service=service),host='127.0.0.1',port=args.port)
        finally: service.close();store.close()
