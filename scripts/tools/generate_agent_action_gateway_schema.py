#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from seedcore.models.agent_action_gateway import (
        AgentActionClosureRequest,
        AgentActionClosureResponse,
        AgentActionEvaluateRequest,
        AgentActionEvaluateResponse,
    )

    output_path = repo_root / "docs" / "references" / "contracts" / "seedcore.agent_action_gateway.v1.schema.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://seedcore.ai/schemas/seedcore.agent_action_gateway.v1.schema.json",
        "title": "seedcore.agent_action_gateway.v1",
        "type": "object",
        "definitions": {
            "AgentActionEvaluateRequest": AgentActionEvaluateRequest.model_json_schema(),
            "AgentActionEvaluateResponse": AgentActionEvaluateResponse.model_json_schema(),
            "AgentActionClosureRequest": AgentActionClosureRequest.model_json_schema(),
            "AgentActionClosureResponse": AgentActionClosureResponse.model_json_schema(),
        },
    }
    output_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
