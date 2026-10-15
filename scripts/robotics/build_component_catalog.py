#!/usr/bin/env python3
"""Check the draft component registry, or explicitly rebuild original proxy assets."""

from __future__ import annotations

import argparse
from collections import Counter
import json

from jsonschema import Draft202012Validator

from seedcore.robotics.component_registry import (
    REGISTRY,
    load_catalog,
    parse_json,
    part_schema,
    proxy_glb,
    read_local,
    sha256,
)


def encoded(value):
    return (
        json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("ascii")


def rebuild():
    schema = part_schema()
    entries = []
    for path in sorted((REGISTRY / "parts").glob("*.sc-part.json")):
        part = parse_json(read_local(REGISTRY, path.relative_to(REGISTRY).as_posix()))
        Draft202012Validator(schema).validate(part)
        mesh = part["mechanical"]["visual_mesh"]
        if mesh["origin"] == "seedcore_box_proxy":
            data = proxy_glb(part["mechanical"]["collision"]["size_m"])
            target = REGISTRY / mesh["uri"]
            if target.is_symlink() or target.parent.is_symlink():
                raise ValueError("refuse to write symlinked proxy asset")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            mesh["sha256"] = sha256(data)
        path.write_bytes(encoded(part))
        entries.append(
            {
                "part_id": part["identity"]["part_id"],
                "version": part["identity"]["version"],
                "path": path.relative_to(REGISTRY).as_posix(),
                "sha256": sha256(path.read_bytes()),
            }
        )
    references = [
        {"path": p.relative_to(REGISTRY).as_posix(), "sha256": sha256(p.read_bytes())}
        for p in sorted((REGISTRY / "references").glob("*.json"))
    ]
    index = {
        "schema_version": "seedcore.component-catalog.v1",
        "status": "draft_only",
        "schema_sha256": sha256(read_local(REGISTRY, "schema/v1.sc-part.schema.json")),
        "parts": entries,
        "references": references,
    }
    (REGISTRY / "catalog.json").write_bytes(encoded(index))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-assets",
        action="store_true",
        help="rebuild proxy GLBs, part hashes and catalog index after review",
    )
    args = parser.parse_args()
    if args.write_assets:
        rebuild()
    parts = load_catalog()
    unindexed = {
        p.relative_to(REGISTRY).as_posix()
        for p in (REGISTRY / "parts").glob("*.sc-part.json")
    } - {p["path"] for p in parse_json(read_local(REGISTRY, "catalog.json"))["parts"]}
    if unindexed:
        raise SystemExit("Unindexed parts: " + ", ".join(sorted(unindexed)))
    print(
        json.dumps(
            {
                "valid_parts": len(parts),
                "categories": dict(Counter(p["identity"]["category"] for p in parts)),
                "hardware_qualified": 0,
                "unknown_costs": sum(
                    p["identity"]["bom_cost_usd"] is None for p in parts
                ),
                "scope": "authoring_only",
            },
            indent=2,
        )
    )
