#!/usr/bin/env python3
"""
PKG Compiler Service

Orchestrates the compilation pipeline:
1. Fetch rules from database
2. Compile rules to Rego
3. Compile Rego to WASM using OPA
4. Store WASM artifact in database
"""

import logging
from typing import Dict, Any, Optional

from .rego_compiler import RegoCompiler
from .opa_compiler import OPACompiler
from .dao import PKGSnapshotsDAO

logger = logging.getLogger(__name__)


class PKGCompilerService:
    """
    Service for compiling PKG snapshots to WASM.
    
    Coordinates Rego compilation and OPA build pipeline.
    """
    
    def __init__(
        self,
        session_factory=None,
        opa_binary_path: Optional[str] = None,
        verify_opa_on_init: bool = False
    ):
        """
        Initialize compiler service.
        
        Args:
            session_factory: Database session factory
            opa_binary_path: Optional path to OPA binary
            verify_opa_on_init: If True, verify OPA availability immediately.
                              If False (default), verify lazily on first compilation.
        """
        self.dao = PKGSnapshotsDAO(session_factory)
        self.rego_compiler = RegoCompiler()
        self.opa_compiler = OPACompiler(opa_binary_path, verify_on_init=verify_opa_on_init)
    
    async def compile_snapshot_to_wasm(
        self,
        snapshot_id: int,
        entrypoint: str = "data.pkg.allow"
    ) -> Dict[str, Any]:
        """
        Compile a snapshot's rules to WASM.
        
        Args:
            snapshot_id: Snapshot ID to compile
            entrypoint: OPA entrypoint path (default: "data.pkg.allow")
            
        Returns:
            Dictionary with:
            - success: bool
            - wasm_bytes: bytes (if success)
            - sha256: str (if success)
            - error: str (if failure)
            - rego_source: str (for debugging)
        """
        try:
            # Fetch snapshot metadata (we just need version, not full snapshot)
            from sqlalchemy import text
            from ...database import get_async_pg_session_factory
            
            session_factory = get_async_pg_session_factory()
            async with session_factory() as session:
                snapshot_sql = text("""
                    SELECT id, version, checksum, notes
                    FROM pkg_snapshots
                    WHERE id = :snapshot_id
                    LIMIT 1
                """)
                res = await session.execute(snapshot_sql, {"snapshot_id": snapshot_id})
                snapshot_row = res.first()
                
                if not snapshot_row:
                    return {
                        "success": False,
                        "error": f"Snapshot {snapshot_id} not found"
                    }
                
                snapshot_dict = dict(snapshot_row._mapping)
                snapshot_version = snapshot_dict["version"]
            
            # Fetch rules for this snapshot
            rules = await self._fetch_rules_for_snapshot(snapshot_id)
            if not rules:
                return {
                    "success": False,
                    "error": f"Snapshot {snapshot_id} has no rules to compile"
                }
            
            logger.info(
                f"Compiling snapshot {snapshot_id} ({snapshot_version}) "
                f"with {len(rules)} rules to WASM"
            )
            
            # Step 1: Compile rules to Rego
            rego_source = self.rego_compiler.compile_snapshot_to_rego(
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
                rules=rules,
                entrypoint=entrypoint
            )
            
            logger.debug(f"Generated Rego policy ({len(rego_source)} chars)")
            
            # Step 2: Compile Rego to WASM
            wasm_bytes, sha256 = self.opa_compiler.compile_rego_to_wasm(
                rego_text=rego_source,
                entrypoint=entrypoint
            )
            
            # Step 3: Validate WASM (optional)
            validation = self.opa_compiler.validate_wasm_module(wasm_bytes)
            if not validation.get("valid", True):
                logger.warning(f"WASM validation warnings: {validation}")
            
            logger.info(
                f"Successfully compiled snapshot {snapshot_id} to WASM: "
                f"{len(wasm_bytes)} bytes, checksum: {sha256[:16]}..."
            )
            
            return {
                "success": True,
                "wasm_bytes": wasm_bytes,
                "sha256": sha256,
                "size_bytes": len(wasm_bytes),
                "rego_source": rego_source,
                "validation": validation
            }
            
        except Exception as e:
            logger.error(f"Compilation failed for snapshot {snapshot_id}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    async def _fetch_rules_for_snapshot(self, snapshot_id: int) -> list:
        """
        Fetch rules with conditions and emissions for a snapshot.
        
        This replicates the logic from PKGSnapshotsDAO._build_snapshot_data
        but returns just the rules structure.
        """
        from sqlalchemy import text
        from ...database import get_async_pg_session_factory
        
        session_factory = get_async_pg_session_factory()
        
        async with session_factory() as session:
            # Use the same query as _build_snapshot_data
            rules_sql = text("""
                SELECT 
                    r.id AS rule_id,
                    r.rule_name,
                    r.priority,
                    r.rule_source,
                    r.compiled_rule,
                    r.engine,
                    r.rule_hash,
                    r.metadata,
                    r.disabled,
                    c.condition_type,
                    c.condition_key,
                    c.operator,
                    c.value AS condition_value,
                    c.position AS condition_position,
                    e.relationship_type,
                    e.params AS emission_params,
                    e.position AS emission_position,
                    st.id AS subtask_type_id,
                    st.name AS subtask_name,
                    st.default_params AS subtask_default_params
                FROM pkg_policy_rules r
                LEFT JOIN pkg_rule_conditions c ON c.rule_id = r.id
                LEFT JOIN pkg_rule_emissions e ON e.rule_id = r.id
                LEFT JOIN pkg_subtask_types st ON st.id = e.subtask_type_id
                WHERE r.snapshot_id = :snapshot_id AND r.disabled = FALSE
                ORDER BY r.priority DESC, r.rule_name, c.position, e.position
            """)
            
            rules_res = await session.execute(rules_sql, {"snapshot_id": snapshot_id})
            
            # Post-process: group conditions and emissions by rule
            rules_dict = {}
            
            for row in rules_res:
                row_dict = dict(row._mapping)
                rule_id = str(row_dict["rule_id"])
                
                # Initialize rule if not seen
                if rule_id not in rules_dict:
                    rules_dict[rule_id] = {
                        "id": row_dict["rule_id"],
                        "rule_name": row_dict["rule_name"],
                        "priority": row_dict["priority"],
                        "rule_source": row_dict["rule_source"],
                        "compiled_rule": row_dict["compiled_rule"],
                        "engine": row_dict["engine"],
                        "rule_hash": row_dict["rule_hash"],
                        "metadata": row_dict["metadata"],
                        "conditions": [],
                        "emissions": [],
                    }
                
                # Add condition if present
                if row_dict.get("condition_type"):
                    rules_dict[rule_id]["conditions"].append({
                        "condition_type": row_dict["condition_type"],
                        "condition_key": row_dict["condition_key"],
                        "operator": row_dict["operator"],
                        "value": row_dict["condition_value"],
                        "position": row_dict["condition_position"] or 0,
                    })
                
                # Add emission if present
                if row_dict.get("subtask_name"):
                    rules_dict[rule_id]["emissions"].append({
                        "subtask_type": row_dict["subtask_name"],
                        "subtask_type_id": str(row_dict["subtask_type_id"]),
                        "subtask_name": row_dict["subtask_name"],
                        "params": row_dict["emission_params"]
                        or row_dict["subtask_default_params"]
                        or {},
                        "relationship_type": row_dict["relationship_type"],
                        "position": row_dict["emission_position"] or 0,
                    })
            
            # Deduplicate conditions and emissions
            for rule_dict in rules_dict.values():
                # Remove duplicate conditions
                seen_conditions = set()
                unique_conditions = []
                for cond in rule_dict["conditions"]:
                    cond_key = (
                        cond["condition_key"],
                        cond["operator"],
                        cond.get("value"),
                    )
                    if cond_key not in seen_conditions:
                        seen_conditions.add(cond_key)
                        unique_conditions.append(cond)
                rule_dict["conditions"] = unique_conditions
                
                # Remove duplicate emissions
                seen_emissions = set()
                unique_emissions = []
                for em in rule_dict["emissions"]:
                    em_key = (em["subtask_type_id"], em["position"])
                    if em_key not in seen_emissions:
                        seen_emissions.add(em_key)
                        unique_emissions.append(em)
                rule_dict["emissions"] = unique_emissions
            
            return list(rules_dict.values())
