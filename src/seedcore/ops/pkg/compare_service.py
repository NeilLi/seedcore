#!/usr/bin/env python3
"""
Snapshot comparison service for the PKG simulator.
"""

from __future__ import annotations

import copy
import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .client import PKGClient
from .evaluator import PKGEvaluator
from .manager import ALLOWED_TASK_FACTS_KEYS, PKGMode
from .result_utils import normalize_policy_result

logger = logging.getLogger(__name__)


class PKGSnapshotCompareService:
    """Orchestrates snapshot-vs-snapshot PKG comparisons."""

    def __init__(self, pkg_client: PKGClient):
        self.pkg_client = pkg_client

    async def compare_snapshots(
        self,
        *,
        baseline_snapshot_id: int,
        candidate_snapshot_id: int,
        task_facts: Optional[Dict[str, Any]] = None,
        fixture_id: Optional[int] = None,
        embedding: Optional[List[float]] = None,
        mode: PKGMode = PKGMode.ADVISORY,
    ) -> Dict[str, Any]:
        self._validate_input_source(task_facts=task_facts, fixture_id=fixture_id)

        run_id = await self.pkg_client.create_validation_run(candidate_snapshot_id)
        report: Dict[str, Any] = {
            "report_type": "snapshot_compare",
            "run_id": run_id,
            "baseline_snapshot_id": baseline_snapshot_id,
            "candidate_snapshot_id": candidate_snapshot_id,
            "errors": [],
        }
        success = False

        try:
            baseline_snapshot = await self.pkg_client.get_snapshot_by_id(baseline_snapshot_id)
            candidate_snapshot = await self.pkg_client.get_snapshot_by_id(candidate_snapshot_id)

            if baseline_snapshot is None:
                raise LookupError(f"Baseline snapshot {baseline_snapshot_id} not found")
            if candidate_snapshot is None:
                raise LookupError(f"Candidate snapshot {candidate_snapshot_id} not found")

            report["baseline_snapshot"] = self._snapshot_metadata(baseline_snapshot)
            report["candidate_snapshot"] = self._snapshot_metadata(candidate_snapshot)

            resolved_input = await self._resolve_compare_input(
                baseline_snapshot_id=baseline_snapshot_id,
                task_facts=task_facts,
                fixture_id=fixture_id,
            )
            base_task_facts = resolved_input["task_facts"]
            input_source = resolved_input["input_source"]
            report["input_source"] = input_source

            baseline_evaluator = PKGEvaluator(baseline_snapshot, pkg_client=self.pkg_client)
            candidate_evaluator = PKGEvaluator(candidate_snapshot, pkg_client=self.pkg_client)

            shared_semantic = await self._hydrate_shared_semantic_context(
                evaluator=baseline_evaluator,
                task_facts=base_task_facts,
                embedding=embedding,
                mode=mode,
            )

            baseline_result = await self._execute_snapshot(
                evaluator=baseline_evaluator,
                base_task_facts=base_task_facts,
                shared_semantic=shared_semantic,
                mode=mode,
                embedding=embedding,
            )
            report["baseline_result"] = baseline_result["normalized"]

            candidate_result = await self._execute_snapshot(
                evaluator=candidate_evaluator,
                base_task_facts=base_task_facts,
                shared_semantic=shared_semantic,
                mode=mode,
                embedding=embedding,
            )
            report["candidate_result"] = candidate_result["normalized"]

            diff = self._diff_results(
                baseline=baseline_result["normalized"],
                candidate=candidate_result["normalized"],
            )
            hydration = {
                "shared_semantic_context_count": len(
                    shared_semantic.get("semantic_context", []) or []
                ),
                "baseline_governed_facts_count": baseline_result["hydration"][
                    "governed_facts_count"
                ],
                "candidate_governed_facts_count": candidate_result["hydration"][
                    "governed_facts_count"
                ],
                "hydration_blocked": (
                    mode == PKGMode.CONTROL and embedding is not None
                ),
            }

            response = {
                "run_id": run_id,
                "baseline_snapshot": self._snapshot_metadata(baseline_snapshot),
                "candidate_snapshot": self._snapshot_metadata(candidate_snapshot),
                "summary": diff["summary"],
                "comparison": {
                    "baseline": baseline_result["normalized"],
                    "candidate": candidate_result["normalized"],
                    "diff": diff["diff"],
                },
            }

            report["summary"] = diff["summary"]
            report["comparison"] = response["comparison"]
            report["hydration"] = hydration
            success = True
            return response
        except Exception as exc:
            report["errors"].append(
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            raise
        finally:
            await self.pkg_client.finish_validation_run(run_id, success, report)

    def _validate_input_source(
        self,
        *,
        task_facts: Optional[Dict[str, Any]],
        fixture_id: Optional[int],
    ) -> None:
        has_task_facts = task_facts is not None
        has_fixture = fixture_id is not None
        if has_task_facts == has_fixture:
            raise ValueError("Exactly one of task_facts or fixture_id must be provided")

    async def _resolve_compare_input(
        self,
        *,
        baseline_snapshot_id: int,
        task_facts: Optional[Dict[str, Any]],
        fixture_id: Optional[int],
    ) -> Dict[str, Any]:
        if task_facts is not None:
            canonical_task_facts = copy.deepcopy(task_facts)
            self._validate_task_facts(canonical_task_facts)
            return {
                "task_facts": canonical_task_facts,
                "input_source": {
                    "type": "raw_task_facts",
                },
            }

        fixture = await self.pkg_client.get_validation_fixture_by_id(fixture_id)
        if fixture is None:
            raise LookupError(f"Validation fixture {fixture_id} not found")
        if fixture.get("snapshot_id") != baseline_snapshot_id:
            raise ValueError(
                f"Fixture {fixture_id} belongs to snapshot {fixture.get('snapshot_id')}, "
                f"expected baseline snapshot {baseline_snapshot_id}"
            )

        canonical_task_facts = copy.deepcopy(fixture.get("input") or {})
        self._validate_task_facts(canonical_task_facts)
        return {
            "task_facts": canonical_task_facts,
            "input_source": {
                "type": "fixture",
                "fixture_id": fixture.get("id"),
                "fixture_name": fixture.get("name"),
                "fixture_snapshot_id": fixture.get("snapshot_id"),
            },
        }

    def _validate_task_facts(self, task_facts: Dict[str, Any]) -> None:
        if not isinstance(task_facts, dict):
            raise ValueError("task_facts must be a dictionary")

        extra_keys = sorted(set(task_facts.keys()) - ALLOWED_TASK_FACTS_KEYS)
        if extra_keys:
            raise ValueError(
                "task_facts contains unsupported keys: " + ", ".join(extra_keys)
            )

    async def _hydrate_shared_semantic_context(
        self,
        *,
        evaluator: PKGEvaluator,
        task_facts: Dict[str, Any],
        embedding: Optional[List[float]],
        mode: PKGMode,
    ) -> Dict[str, Any]:
        if mode == PKGMode.CONTROL or embedding is None:
            return {}

        hydrated = await evaluator.hydrate_semantic_context(
            copy.deepcopy(task_facts),
            embedding=embedding,
        )
        shared: Dict[str, Any] = {}
        if "semantic_context" in hydrated:
            shared["semantic_context"] = copy.deepcopy(hydrated.get("semantic_context"))
        if "memory_hits" in hydrated:
            shared["memory_hits"] = copy.deepcopy(hydrated.get("memory_hits"))
        return shared

    async def _execute_snapshot(
        self,
        *,
        evaluator: PKGEvaluator,
        base_task_facts: Dict[str, Any],
        shared_semantic: Dict[str, Any],
        mode: PKGMode,
        embedding: Optional[List[float]],
    ) -> Dict[str, Any]:
        hydrated_input = copy.deepcopy(base_task_facts)
        for key, value in shared_semantic.items():
            hydrated_input[key] = copy.deepcopy(value)

        hydrated_input = await evaluator.hydrate_governed_facts(
            hydrated_input,
            snapshot_id=evaluator.snapshot_id,
        )

        raw_result = evaluator.evaluate(hydrated_input)
        raw_result["_hydrated"] = {
            "governed_facts": hydrated_input.get("governed_facts"),
            "semantic_context": hydrated_input.get("semantic_context"),
        }
        raw_result["meta"] = {
            "mode": mode.value,
            "version": raw_result.get("snapshot"),
            "hydration_blocked": mode == PKGMode.CONTROL and embedding is not None,
            "has_subtasks": len(raw_result.get("subtasks", []) or []) > 0,
            "subtasks_count": len(raw_result.get("subtasks", []) or []),
            "rules_matched": len(raw_result.get("rules", []) or []),
        }

        normalized = normalize_policy_result(
            raw_result,
            raise_on_gate_block=False,
        )

        return {
            "normalized": normalized,
            "hydration": {
                "governed_facts_count": len(
                    hydrated_input.get("governed_facts", []) or []
                ),
            },
        }

    def _diff_results(
        self,
        *,
        baseline: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> Dict[str, Any]:
        emission_diff = self._diff_emissions(baseline, candidate)
        dag_diff = self._diff_dag(baseline, candidate)
        rule_diff = self._summarize_rule_changes(emission_diff)

        decision_changed = baseline.get("decision") != candidate.get("decision")
        behavior_changed = bool(
            decision_changed
            or emission_diff
            or dag_diff
        )

        summary = {
            "behavior_changed": behavior_changed,
            "decision_changed": decision_changed,
            "emissions": {
                "baseline": len(baseline.get("emissions", {}).get("subtasks", []) or []),
                "candidate": len(candidate.get("emissions", {}).get("subtasks", []) or []),
                "added": sum(1 for item in emission_diff if item["status"] == "added"),
                "removed": sum(1 for item in emission_diff if item["status"] == "removed"),
                "changed": sum(1 for item in emission_diff if item["status"] == "changed"),
            },
            "dag": {
                "baseline": len(baseline.get("emissions", {}).get("dag", []) or []),
                "candidate": len(candidate.get("emissions", {}).get("dag", []) or []),
                "added": sum(1 for item in dag_diff if item["status"] == "added"),
                "removed": sum(1 for item in dag_diff if item["status"] == "removed"),
            },
            "changed_rule_count": len(rule_diff),
        }

        return {
            "summary": summary,
            "diff": {
                "emissions": emission_diff,
                "dag": dag_diff,
                "rules": rule_diff,
            },
        }

    def _diff_emissions(
        self,
        baseline: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        baseline_index = self._index_emissions(
            baseline.get("emissions", {}).get("subtasks", []) or []
        )
        candidate_index = self._index_emissions(
            candidate.get("emissions", {}).get("subtasks", []) or []
        )

        diffs: List[Dict[str, Any]] = []
        all_keys = sorted(set(baseline_index.keys()) | set(candidate_index.keys()))

        for key in all_keys:
            baseline_records = baseline_index.get(key, [])
            candidate_records = candidate_index.get(key, [])
            max_len = max(len(baseline_records), len(candidate_records))

            for idx in range(max_len):
                baseline_record = baseline_records[idx] if idx < len(baseline_records) else None
                candidate_record = candidate_records[idx] if idx < len(candidate_records) else None

                if baseline_record and not candidate_record:
                    diffs.append(
                        {
                            "status": "removed",
                            "rule_id": baseline_record.get("rule_id"),
                            "rule_name": baseline_record.get("rule_name"),
                            "emission_key": baseline_record.get("emission_key"),
                            "baseline": baseline_record,
                            "candidate": None,
                        }
                    )
                    continue

                if candidate_record and not baseline_record:
                    diffs.append(
                        {
                            "status": "added",
                            "rule_id": candidate_record.get("rule_id"),
                            "rule_name": candidate_record.get("rule_name"),
                            "emission_key": candidate_record.get("emission_key"),
                            "baseline": None,
                            "candidate": candidate_record,
                        }
                    )
                    continue

                if baseline_record and candidate_record:
                    baseline_payload = self._canonical_json(
                        {
                            "subtask_name": baseline_record.get("subtask_name"),
                            "subtask_type": baseline_record.get("subtask_type"),
                            "params": baseline_record.get("params"),
                        }
                    )
                    candidate_payload = self._canonical_json(
                        {
                            "subtask_name": candidate_record.get("subtask_name"),
                            "subtask_type": candidate_record.get("subtask_type"),
                            "params": candidate_record.get("params"),
                        }
                    )
                    if baseline_payload != candidate_payload:
                        diffs.append(
                            {
                                "status": "changed",
                                "rule_id": candidate_record.get("rule_id")
                                or baseline_record.get("rule_id"),
                                "rule_name": candidate_record.get("rule_name")
                                or baseline_record.get("rule_name"),
                                "emission_key": candidate_record.get("emission_key")
                                or baseline_record.get("emission_key"),
                                "baseline": baseline_record,
                                "candidate": candidate_record,
                            }
                        )

        return diffs

    def _diff_dag(
        self,
        baseline: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        baseline_edges = {
            self._dag_key(edge): edge
            for edge in baseline.get("emissions", {}).get("dag", []) or []
        }
        candidate_edges = {
            self._dag_key(edge): edge
            for edge in candidate.get("emissions", {}).get("dag", []) or []
        }

        diffs: List[Dict[str, Any]] = []
        all_keys = sorted(set(baseline_edges.keys()) | set(candidate_edges.keys()))
        for key in all_keys:
            baseline_edge = baseline_edges.get(key)
            candidate_edge = candidate_edges.get(key)
            if baseline_edge and not candidate_edge:
                diffs.append(
                    {
                        "status": "removed",
                        "edge_key": key,
                        "baseline": baseline_edge,
                        "candidate": None,
                    }
                )
            elif candidate_edge and not baseline_edge:
                diffs.append(
                    {
                        "status": "added",
                        "edge_key": key,
                        "baseline": None,
                        "candidate": candidate_edge,
                    }
                )

        return diffs

    def _summarize_rule_changes(
        self,
        emission_diff: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        summaries: Dict[Tuple[Optional[str], Optional[str]], Dict[str, Any]] = {}
        for item in emission_diff:
            source = item.get("candidate") or item.get("baseline") or {}
            rule_key = (
                source.get("rule_id"),
                source.get("rule_name"),
            )
            if rule_key not in summaries:
                summaries[rule_key] = {
                    "rule_id": source.get("rule_id"),
                    "rule_name": source.get("rule_name"),
                    "added": 0,
                    "removed": 0,
                    "changed": 0,
                    "total_changed": 0,
                }

            status = item["status"]
            summaries[rule_key][status] += 1
            summaries[rule_key]["total_changed"] += 1

        return sorted(
            summaries.values(),
            key=lambda item: (-item["total_changed"], item.get("rule_name") or ""),
        )

    def _index_emissions(
        self,
        subtasks: List[Dict[str, Any]],
    ) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)

        for subtask in subtasks:
            rule_compare_key = str(
                subtask.get("rule_name")
                or subtask.get("rule_id")
                or "unknown_rule"
            )
            emission_name = str(
                subtask.get("name")
                or subtask.get("type")
                or "unknown_subtask"
            )
            grouped[(rule_compare_key, emission_name)].append(
                {
                    "rule_id": subtask.get("rule_id"),
                    "rule_name": subtask.get("rule_name"),
                    "subtask_name": subtask.get("name"),
                    "subtask_type": subtask.get("type"),
                    "params": copy.deepcopy(subtask.get("params") or {}),
                    "emission_key": f"{rule_compare_key}:{emission_name}",
                }
            )

        for records in grouped.values():
            records.sort(key=lambda item: self._canonical_json(item.get("params")))

        return grouped

    def _dag_key(self, edge: Dict[str, Any]) -> str:
        return self._canonical_json(
            {
                "from": edge.get("from"),
                "to": edge.get("to"),
                "type": edge.get("type"),
                "rule": edge.get("rule"),
            }
        )

    def _snapshot_metadata(self, snapshot: Any) -> Dict[str, Any]:
        return {
            "id": snapshot.id,
            "version": snapshot.version,
            "engine": snapshot.engine,
            "checksum": snapshot.checksum,
        }

    def _canonical_json(self, value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
