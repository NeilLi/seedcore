#!/usr/bin/env python3
"""Prepare an unpublished review packet from an existing ESP-IDF ESP32-S3 build."""

import argparse
import json
from pathlib import Path

from seedcore.robotics.fast_spine.release import prepare_release


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--merged-image", required=True, help="path relative to build-dir"
    )
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--version", required=True)
    args = vars(parser.parse_args())
    print(json.dumps(prepare_release(**args), indent=2))
