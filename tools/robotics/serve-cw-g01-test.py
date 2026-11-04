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
    parser.add_argument('--evidence',action='store_true',help='Explicit test-only receipt signer and verification trust')
    parser.add_argument('--trust-out',type=Path,help='Retain public fixture trust for independent browser artifact checks')
    args=parser.parse_args()
    with TemporaryDirectory(prefix='seedcore-cw-g01-browser-') as directory:
        signer = None
        if args.evidence:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from seedcore.robotics.cw_evidence import CwReceiptSigner
            signer = CwReceiptSigner(Ed25519PrivateKey.generate(),'cw-browser-explicit-receipt')
        service,store,_=make_test_service(args.source.read_bytes(),directory,threaded=True,receipt_signer=signer,evidence_enabled=args.evidence)
        if args.trust_out:
            if not args.evidence: raise ValueError('--trust-out requires --evidence')
            from seedcore.robotics.cw_evidence import json_bytes
            args.trust_out.parent.mkdir(parents=True,exist_ok=True)
            args.trust_out.write_bytes(json_bytes(service._evidence_verifier._trust))
        try: uvicorn.run(create_app(admission_service=service),host='127.0.0.1',port=args.port)
        finally: service.close();store.close()
