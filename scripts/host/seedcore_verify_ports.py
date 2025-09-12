#!/usr/bin/env python3
# Copyright 2024 SeedCore Contributors
# Licensed under the Apache License, Version 2.0

import argparse, socket, sys

def check_port(host, port, timeout=1.5):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ports", nargs="+", type=int, required=True)
    args = ap.parse_args()

    failures = []
    for p in args.ports:
        ok = check_port(args.host, p)
        print(f"{'✅' if ok else '❌'} {args.host}:{p}")
        if not ok:
            failures.append(p)

    if failures:
        print(f"❌ Unreachable ports: {failures}")
        sys.exit(2)
    print("✅ All ports reachable.")

if __name__ == "__main__":
    main()

