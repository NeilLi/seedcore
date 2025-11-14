# ops/pkg/evaluator.py

import time
import logging
from typing import Any, Dict, Optional, List, Protocol, runtime_checkable
from dataclasses import dataclass

# Import snapshot data structure from dao
from .dao import PKGSnapshotData

logger = logging.getLogger(__name__)

# --- Optional WASM Runtime Support ---
_WASMTIME_AVAILABLE = False
try:
    import wasmtime  # type: ignore
    _WASMTIME_AVAILABLE = True
except ImportError:
    logger.warning("wasmtime not available - WASM engine will use fallback mode")


@dataclass
class EvaluationResult:
    """Result object returned by policy engines."""
    subtasks: List[Dict[str, Any]]
    dag: List[Dict[str, Any]]
    provenance: List[Dict[str, Any]]


# --- Engine Protocol Interface ---

@runtime_checkable
class PolicyEngine(Protocol):
    """
    Protocol interface for policy evaluation engines.
    
    All policy engines must implement this interface to ensure
    consistent evaluation behavior across different engine types.
    """
    def evaluate(self, task_facts: Dict[str, Any]) -> EvaluationResult:
        """
        Evaluate policy rules against task facts.
        
        Args:
            task_facts: Input facts dictionary with tags, signals, context
            
        Returns:
            EvaluationResult with subtasks, dag, and provenance
        """
        ...


# --- WASM Cache ---

_WASM_CACHE: Dict[str, Any] = {}  # Cache keyed by checksum


def _get_cached_wasm(checksum: Optional[str], wasm_bytes: bytes) -> Optional[Any]:
    """Get cached WASM engine or None if not cached."""
    if checksum and checksum in _WASM_CACHE:
        logger.debug(f"Using cached WASM engine for checksum {checksum[:8]}...")
        return _WASM_CACHE[checksum]
    return None


def _cache_wasm(checksum: Optional[str], engine: Any) -> None:
    """Cache WASM engine by checksum."""
    if checksum:
        _WASM_CACHE[checksum] = engine
        logger.debug(f"Cached WASM engine for checksum {checksum[:8]}...")
        # Limit cache size (keep last 10)
        if len(_WASM_CACHE) > 10:
            oldest_key = next(iter(_WASM_CACHE))
            del _WASM_CACHE[oldest_key]


class OpaWasm:
    """
    OPA WASM runtime wrapper.
    
    Supports both wasmtime-based execution (if available) and fallback mode.
    Implements PolicyEngine protocol for consistent evaluation interface.
    [cite: 68, 91]
    """
    def __init__(self, wasm_bytes: bytes, checksum: Optional[str] = None):
        """
        Initialize OPA WASM engine.
        
        Args:
            wasm_bytes: Compiled WASM binary bytes
            checksum: Optional checksum for caching
        """
        self._wasm_bytes = wasm_bytes
        self._checksum = checksum
        self._engine = None
        self._instance = None
        self._wasmtime_available = False
        
        if _WASMTIME_AVAILABLE:
            try:
                # Initialize wasmtime engine
                import wasmtime  # type: ignore
                engine = wasmtime.Engine()
                module = wasmtime.Module(engine, wasm_bytes)
                store = wasmtime.Store(engine)
                self._instance = wasmtime.Instance(store, module, [])
                self._store = store
                self._wasmtime_available = True
                logger.info(f"OPA WASM engine loaded with wasmtime ({len(wasm_bytes)} bytes, checksum={checksum[:8] if checksum else 'N/A'}...)")
            except Exception as e:
                logger.warning(f"Failed to load WASM with wasmtime: {e}. Using fallback mode.")
                self._wasmtime_available = False
        else:
            logger.warning(f"OPA WASM engine loaded in fallback mode ({len(wasm_bytes)} bytes)")
            self._wasmtime_available = False

    @staticmethod
    def load_from_bytes(wasm_bytes: bytes, checksum: Optional[str] = None) -> "OpaWasm":
        """
        Loads the compiled .wasm policy artifact.
        
        Args:
            wasm_bytes: Compiled WASM binary bytes
            checksum: Optional checksum for caching
            
        Returns:
            OpaWasm instance (cached if checksum provided and available)
        """
        # Check cache first
        if checksum:
            cached = _get_cached_wasm(checksum, wasm_bytes)
            if cached:
                return cached
        
        # Create new instance
        engine = OpaWasm(wasm_bytes, checksum)
        
        # Cache if checksum provided
        if checksum and _WASMTIME_AVAILABLE:
            _cache_wasm(checksum, engine)
        
        return engine

    def evaluate(self, task_facts: Dict[str, Any]) -> EvaluationResult:
        """
        Runs the WASM policy evaluation.
        
        Args:
            task_facts: Input facts dictionary with tags, signals, context
            
        Returns:
            EvaluationResult with subtasks, dag, and provenance
        """
        start_time = time.perf_counter()
        
        # Log evaluation start
        logger.debug({
            "event": "wasm_evaluation_start",
            "checksum": self._checksum[:8] if self._checksum else None,
            "facts_keys": list(task_facts.keys()),
            "wasmtime_available": self._wasmtime_available
        })
        
        if self._wasmtime_available and self._instance:
            try:
                # Call OPA WASM entrypoint with task_facts
                # OPA WASM expects input as JSON string
                import json
                input_json = json.dumps(task_facts)
                
                # Get the evaluate function from WASM instance
                # Note: Actual function name depends on OPA WASM compilation
                # This is a placeholder - adjust based on your OPA WASM interface
                # Real OPA WASM uses: opa_eval(ctx, data_addr, data_len, input_addr, input_len, ...)
                exports = self._instance.exports(self._store)
                evaluate_func = exports.get("evaluate") or exports.get("opa_eval")
                
                if evaluate_func:
                    result_json = evaluate_func(self._store, input_json)
                    result = json.loads(result_json) if isinstance(result_json, str) else result_json
                else:
                    # Fallback: try default entrypoint pattern
                    result = self._call_opa_entrypoint(task_facts)
                
                parsed_result = self._parse_opa_result(result)
                
                elapsed = time.perf_counter() - start_time
                logger.info(f"WASM evaluation completed in {elapsed:.3f}s (checksum={self._checksum[:8] if self._checksum else 'N/A'}...)")
                
                return parsed_result
            except Exception as e:
                logger.error(f"WASM evaluation failed: {e}. Falling back to default behavior.", exc_info=True)
                return self._fallback_evaluate(task_facts)
        else:
            # Fallback mode: return basic structure
            logger.debug("WASM evaluation in fallback mode (wasmtime not available)")
            return self._fallback_evaluate(task_facts)
    
    def _call_opa_entrypoint(self, task_facts: Dict[str, Any]) -> Dict[str, Any]:
        """Call OPA entrypoint function (placeholder - implement based on your WASM interface)."""
        # This would call the actual OPA WASM entrypoint
        # For now, return a structured default
        return {
            "result": {
                "subtasks": [],
                "dag": [],
                "rules": []
            }
        }
    
    def _parse_opa_result(self, opa_result: Dict[str, Any]) -> EvaluationResult:
        """Parse OPA result into EvaluationResult format."""
        result_data = opa_result.get("result", {})
        return EvaluationResult(
            subtasks=result_data.get("subtasks", []),
            dag=result_data.get("dag", []),
            provenance=result_data.get("rules", result_data.get("provenance", []))
        )
    
    def _fallback_evaluate(self, task_facts: Dict[str, Any]) -> EvaluationResult:
        """Fallback evaluation when WASM runtime is unavailable."""
        logger.debug(f"WASM fallback evaluation for facts: {list(task_facts.keys())}")
        # Return empty result structure - policy should handle this gracefully
        return EvaluationResult(
            subtasks=[],
            dag=[],
            provenance=[{"rule_id": "wasm-fallback", "note": "WASM runtime unavailable"}]
        )


class NativeRuleEngine:
    """
    Native Python rule engine that evaluates rules from the database.
    
    Processes rules with conditions and emissions to generate subtasks and DAG.
    Implements PolicyEngine protocol for consistent evaluation interface.
    [cite: 62, 93]
    """
    def __init__(self, rules: Optional[List[Dict[str, Any]]]):
        """
        Initialize native rule engine.
        
        Args:
            rules: List of rule dictionaries from pkg_policy_rules table
        """
        self._rules = rules or []
        logger.info(f"NativeRuleEngine loaded with {len(self._rules)} rules")
        
        # Validate rules structure
        if self._rules:
            for rule in self._rules:
                if not isinstance(rule.get("conditions"), list):
                    logger.warning(f"Rule {rule.get('rule_name', 'unknown')} has invalid conditions structure")
                if not isinstance(rule.get("emissions"), list):
                    logger.warning(f"Rule {rule.get('rule_name', 'unknown')} has invalid emissions structure")
    
    def run(self, task_facts: Dict[str, Any]) -> EvaluationResult:
        """
        Runs the native rule evaluation chain.
        
        Args:
            task_facts: Input facts dictionary with tags, signals, context
            
        Returns:
            EvaluationResult with subtasks, dag, and provenance
        """
        start_time = time.perf_counter()
        
        # Log evaluation start
        logger.debug({
            "event": "native_evaluation_start",
            "rule_count": len(self._rules),
            "facts_keys": list(task_facts.keys())
        })
        
        from ...predicates.evaluator import PredicateEvaluator
        
        evaluator = PredicateEvaluator()
        matched_rules = []
        subtasks = []
        provenance = []
        
        # Validate task_facts structure
        if not isinstance(task_facts, dict):
            logger.warning(f"Invalid task_facts type: {type(task_facts)}, expected dict")
            return EvaluationResult(subtasks=[], dag=[], provenance=[])
        
        # Evaluate rules in priority order
        for rule in sorted(self._rules, key=lambda r: r.get("priority", 0), reverse=True):
            rule_name = rule.get("rule_name", "unknown")
            rule_id = rule.get("id")
            
            # Check rule conditions
            conditions = rule.get("conditions", [])
            
            if self._evaluate_conditions(conditions, task_facts, evaluator):
                # Rule matched - process emissions
                emissions = rule.get("emissions", [])
                rule_subtasks = self._process_emissions(emissions, rule_id, rule_name)
                subtasks.extend(rule_subtasks)
                
                # Add provenance
                provenance.append({
                    "rule_id": str(rule_id) if rule_id else rule_name,
                    "rule_name": rule_name,
                    "rule_priority": rule.get("priority", 0),
                    "weight": rule.get("weight", 1.0),
                    "matched_conditions": len(conditions),
                    "emissions_count": len(emissions)
                })
                
                matched_rules.append(rule)
        
        # Build DAG from rule relationships and emissions
        dag = self._build_dag(matched_rules, subtasks)
        
        elapsed = time.perf_counter() - start_time
        logger.info(f"NativeRuleEngine evaluated {len(matched_rules)}/{len(self._rules)} matching rules in {elapsed:.3f}s")
        
        return EvaluationResult(
            subtasks=subtasks,
            dag=dag,
            provenance=provenance
        )
    
    # Alias for Protocol compatibility
    def evaluate(self, task_facts: Dict[str, Any]) -> EvaluationResult:
        """Alias for run() to match PolicyEngine protocol."""
        return self.run(task_facts)
    
    def _evaluate_conditions(
        self, 
        conditions: List[Dict[str, Any]], 
        task_facts: Dict[str, Any],
        evaluator: Any
    ) -> bool:
        """
        Evaluate rule conditions against task facts.
        
        Uses PredicateEvaluator for declarative condition evaluation.
        
        Args:
            conditions: List of condition dictionaries
            task_facts: Input facts
            evaluator: PredicateEvaluator instance
            
        Returns:
            True if all conditions match
        """
        if not conditions:
            # No conditions means rule always matches
            return True
        
        # Build evaluation context from task_facts
        context = {
            "tags": task_facts.get("tags", []),
            "signals": task_facts.get("signals", {}),
            "context": task_facts.get("context", {})
        }
        
        # Flatten context for easier access
        for key, value in task_facts.items():
            if key not in context:
                context[key] = value
        
        # Evaluate each condition
        for condition in conditions:
            condition_type = condition.get("condition_type")
            operator = condition.get("operator")
            condition_key = condition.get("condition_key") or condition.get("field_path", "")
            value = condition.get("value")
            
            # Use condition_type to determine evaluation strategy
            if condition_type == "TAG":
                # Check if tag exists in tags list
                if not self._check_condition(condition, context, condition_type="TAG"):
                    logger.debug(f"Condition failed: TAG {condition_key} not in {context.get('tags', [])}")
                    return False
            elif condition_type == "SIGNAL":
                # Check signal value using operator
                if not self._check_condition(condition, context, condition_type="SIGNAL"):
                    logger.debug(f"Condition failed: SIGNAL {condition_key} {operator} {value}")
                    return False
            elif condition_type == "FACT":
                # Check fact predicate using PredicateEvaluator
                if not self._check_condition(condition, context, condition_type="FACT"):
                    logger.debug(f"Condition failed: FACT {condition_key} {operator} {value}")
                    return False
            else:
                # Default: use field_path-based evaluation
                if not self._check_condition(condition, context):
                    logger.debug(f"Condition failed: {condition_key} {operator} {value}")
                    return False
        
        return True
    
    def _check_condition(
        self, 
        condition: Dict[str, Any], 
        context: Dict[str, Any],
        condition_type: Optional[str] = None
    ) -> bool:
        """
        Check a single condition against context.
        
        Args:
            condition: Condition dictionary
            context: Evaluation context
            condition_type: Optional condition type override
            
        Returns:
            True if condition matches
        """
        condition_type = condition_type or condition.get("condition_type")
        condition_key = condition.get("condition_key") or condition.get("field_path", "")
        operator = condition.get("operator", "EXISTS")
        value = condition.get("value")
        
        # Handle condition type-specific logic
        if condition_type == "TAG":
            tags = context.get("tags", [])
            if operator == "IN" or operator == "EXISTS":
                return condition_key in tags
            elif operator == "=":
                return condition_key in tags
            else:
                return False
        
        elif condition_type == "SIGNAL":
            signals = context.get("signals", {})
            field_value = signals.get(condition_key)
            return self._evaluate_operator(field_value, operator, value)
        
        elif condition_type == "FACT":
            # For FACT conditions, use PredicateEvaluator if available
            # For now, use field path resolution
            field_path = condition.get("field_path", condition_key)
            field_value = self._get_field_value(field_path, context)
            return self._evaluate_operator(field_value, operator, value)
        
        else:
            # Default: use field_path-based evaluation
            field_path = condition.get("field_path", condition_key)
            field_value = self._get_field_value(field_path, context)
            return self._evaluate_operator(field_value, operator, value)
    
    def _evaluate_operator(self, field_value: Any, operator: str, expected_value: Any) -> bool:
        """
        Evaluate operator-based comparison.
        
        Args:
            field_value: Actual value from context
            operator: Comparison operator (=, !=, >=, <=, >, <, IN, EXISTS, MATCHES)
            expected_value: Expected value to compare against
            
        Returns:
            True if comparison matches
        """
        if operator == "=":
            return field_value == expected_value
        elif operator == "!=":
            return field_value != expected_value
        elif operator == ">=":
            try:
                return field_value >= expected_value
            except TypeError:
                logger.warning(f"Cannot compare {type(field_value)} >= {type(expected_value)}")
                return False
        elif operator == "<=":
            try:
                return field_value <= expected_value
            except TypeError:
                logger.warning(f"Cannot compare {type(field_value)} <= {type(expected_value)}")
                return False
        elif operator == ">":
            try:
                return field_value > expected_value
            except TypeError:
                logger.warning(f"Cannot compare {type(field_value)} > {type(expected_value)}")
                return False
        elif operator == "<":
            try:
                return field_value < expected_value
            except TypeError:
                logger.warning(f"Cannot compare {type(field_value)} < {type(expected_value)}")
                return False
        elif operator == "IN":
            if isinstance(expected_value, list):
                return field_value in expected_value
            else:
                return field_value == expected_value
        elif operator == "EXISTS":
            return field_value is not None
        elif operator == "MATCHES":
            # Regex pattern matching
            import re
            if isinstance(expected_value, str):
                try:
                    return bool(re.match(expected_value, str(field_value)))
                except re.error:
                    logger.warning(f"Invalid regex pattern: {expected_value}")
                    return False
            return False
        else:
            logger.warning(f"Unsupported operator: {operator}")
            return False
    
    def _get_field_value(self, field_path: str, context: Dict[str, Any]) -> Any:
        """Get value from context using dot-notation path."""
        parts = field_path.split(".")
        value = context
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit():
                value = value[int(part)] if int(part) < len(value) else None
            else:
                return None
        return value
    
    def _process_emissions(
        self, 
        emissions: List[Dict[str, Any]], 
        rule_id: Any,
        rule_name: str
    ) -> List[Dict[str, Any]]:
        """Process rule emissions into subtasks."""
        subtasks = []
        
        for emission in emissions:
            subtask_type = emission.get("subtask_type")
            subtask_name = emission.get("subtask_name", f"{rule_name}_subtask")
            params = emission.get("params", {})
            
            subtask = {
                "name": subtask_name,
                "type": subtask_type,
                "params": params,
                "rule_id": rule_id,
                "rule_name": rule_name
            }
            subtasks.append(subtask)
        
        return subtasks
    
    def _build_dag(
        self, 
        matched_rules: List[Dict[str, Any]], 
        subtasks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Build DAG edges from rule relationships and emissions.
        
        Uses relationship_type from emissions to determine proper DAG topology:
        - EMITS: Independent subtask (no dependencies)
        - ORDERS: Sequential dependency (depends on previous)
        - GATE: Conditional dependency (waits for condition)
        
        Args:
            matched_rules: List of matched rules
            subtasks: List of generated subtasks
            
        Returns:
            List of DAG edge dictionaries
        """
        dag = []
        
        if not subtasks:
            return dag
        
        # Build subtask index by name for quick lookup
        subtask_map = {st["name"]: st for st in subtasks}
        
        # Process emissions to build proper DAG
        for rule in matched_rules:
            emissions = rule.get("emissions", [])
            rule_name = rule.get("rule_name", "unknown")
            
            for i, emission in enumerate(emissions):
                relationship_type = emission.get("relationship_type", "EMITS")
                subtask_name = emission.get("subtask_name")
                
                if not subtask_name or subtask_name not in subtask_map:
                    continue
                
                # Handle different relationship types
                if relationship_type == "ORDERS":
                    # Sequential dependency: depends on previous emission from same rule
                    if i > 0:
                        prev_emission = emissions[i - 1]
                        prev_subtask = prev_emission.get("subtask_name")
                        if prev_subtask and prev_subtask in subtask_map:
                            dag.append({
                                "from": prev_subtask,
                                "to": subtask_name,
                                "type": "sequential",
                                "rule": rule_name
                            })
                elif relationship_type == "GATE":
                    # Conditional dependency: wait for condition
                    # For now, we'll use rule priority to determine gates
                    # In full implementation, you'd check pkg_rule_conditions for gate conditions
                    gate_source = rule.get("metadata", {}).get("gate_source")
                    if gate_source and gate_source in subtask_map:
                        dag.append({
                            "from": gate_source,
                            "to": subtask_name,
                            "type": "gate",
                            "rule": rule_name
                        })
                # EMITS: No dependencies (independent subtask)
        
        # Fallback: if no relationships defined, create sequential chain
        if not dag and len(subtasks) > 1:
            logger.debug("No explicit relationships found, creating sequential DAG")
            for i in range(1, len(subtasks)):
                dag.append({
                    "from": subtasks[i-1]["name"],
                    "to": subtasks[i]["name"],
                    "type": "sequential",
                    "rule": "auto-generated"
                })
        
        return dag

# --- Engine Registry ---

ENGINE_REGISTRY: Dict[str, type] = {
    "wasm": OpaWasm,
    "native": NativeRuleEngine,
}


def register_engine(engine_type: str, engine_class: type) -> None:
    """
    Register a new engine type in the registry.
    
    Args:
        engine_type: Engine type identifier (e.g., 'llm', 'graph')
        engine_class: Engine class implementing PolicyEngine protocol
    """
    if not issubclass(engine_class, PolicyEngine) if hasattr(PolicyEngine, '__subclasshook__') else True:
        logger.warning(f"Engine class {engine_class} may not implement PolicyEngine protocol")
    ENGINE_REGISTRY[engine_type] = engine_class
    logger.info(f"Registered engine type '{engine_type}': {engine_class.__name__}")


# --- Main Implementation ---

class PKGEvaluator:
    """
    Implements the PKGEvaluator class as defined in the architecture document.
    [cite: 85]
    
    This class holds a specific, loaded policy snapshot (either WASM or 
    native) and provides a unified 'evaluate' interface.
    
    Uses dynamic engine registration for extensibility.
    """
    
    def __init__(self, snapshot: PKGSnapshotData):
        """
        Initializes the evaluator by loading the specified snapshot's engine.
        [cite: 86]
        
        Uses ENGINE_REGISTRY for dynamic engine selection, enabling
        easy extension to new engine types (e.g., LLM, graph-based).
        
        Args:
            snapshot: PKGSnapshotData instance from PKGClient
        """
        self.version: str = snapshot.version  # [cite: 87]
        self.engine_type: str = snapshot.engine  # [cite: 88]
        self.loaded_at: float = time.time()  # [cite: 89]
        self.engine: Optional[PolicyEngine] = None

        # Use engine registry for dynamic engine selection
        engine_class = ENGINE_REGISTRY.get(self.engine_type)
        
        if not engine_class:
            raise ValueError(
                f"Unknown engine type '{self.engine_type}' for snapshot {self.version}. "
                f"Available engines: {list(ENGINE_REGISTRY.keys())}"
            )
        
        if self.engine_type == 'wasm':
            if not snapshot.wasm_artifact:
                raise ValueError(f"Snapshot {self.version} has engine 'wasm' but no 'wasm_artifact'.")
            # Load the OPA WASM binary bytes into the runtime [cite: 90]
            # Use checksum for caching
            self.engine = OpaWasm.load_from_bytes(
                snapshot.wasm_artifact, 
                checksum=snapshot.checksum
            )  # [cite: 91]
            logger.info(f"PKGEvaluator initialized with WASM engine (version: {self.version}, checksum={snapshot.checksum[:8] if snapshot.checksum else 'N/A'}...)")
        else:
            # Load the native rule definitions [cite: 92]
            self.engine = NativeRuleEngine(snapshot.rules)  # [cite: 93]
            logger.info(f"PKGEvaluator initialized with native engine (version: {self.version}, {len(snapshot.rules) if snapshot.rules else 0} rules)")

    def evaluate(self, task_facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs the loaded policy engine against a set of input facts.
        [cite: 94]
        
        Args:
            task_facts: A dictionary of input facts for the policy. 
                        e.g., {"tags": [...], "signals": {...}, "context": {...}} [cite: 55-59]

        Returns:
            A dictionary containing the policy output (subtasks, dag, provenance)
            and the snapshot version that was used. [cite: 99-104]
        """
        if self.engine is None:
            raise RuntimeError(f"PKGEvaluator engine not initialized for version {self.version}")

        start_time = time.perf_counter()
        
        # Log evaluation start with structured context
        logger.debug({
            "event": "pkg_evaluation_start",
            "snapshot": self.version,
            "engine": self.engine_type,
            "facts_keys": list(task_facts.keys()) if isinstance(task_facts, dict) else []
        })

        try:
            # Unified engine interface - both engines implement evaluate()
            if isinstance(self.engine, OpaWasm):
                # Invoke the OPA runtime [cite: 95]
                result = self.engine.evaluate(task_facts)  # [cite: 96]
            elif isinstance(self.engine, NativeRuleEngine):
                # Run the native predicate chain [cite: 97]
                result = self.engine.evaluate(task_facts)  # [cite: 98]
            else:
                # Generic engine interface (for future extensions)
                result = self.engine.evaluate(task_facts)
            
            elapsed = time.perf_counter() - start_time
            
            # Assemble the final, standardized output dictionary [cite: 99]
            output = {
                "subtasks": result.subtasks,      # [cite: 100]
                "dag": result.dag,                # [cite: 101]
                "rules": result.provenance,       # [cite: 102]
                "snapshot": self.version          # [cite: 103]
            }
            
            # Log successful evaluation
            logger.info({
                "event": "pkg_evaluation_complete",
                "snapshot": self.version,
                "engine": self.engine_type,
                "duration_ms": elapsed * 1000,
                "subtasks_count": len(result.subtasks),
                "rules_matched": len(result.provenance)
            })
            
            return output
            
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            logger.error({
                "event": "pkg_evaluation_error",
                "snapshot": self.version,
                "engine": self.engine_type,
                "duration_ms": elapsed * 1000,
                "error": str(e)
            }, exc_info=True)
            
            # Return empty result on error
            return {
                "subtasks": [],
                "dag": [],
                "rules": [{"rule_id": "error", "error": str(e), "error_type": type(e).__name__}],
                "snapshot": self.version
            }

if __name__ == '__main__':
    # --- Example Usage ---
    print("--- Testing PKG Evaluator ---")
    
    # Note: In real usage, snapshots come from PKGClient.get_active_snapshot()
    # This is just for demonstration
    
    # Example input facts
    input_data = {
        "tags": ["vip", "privacy", "allergen"],
        "signals": {"x2": 0.8, "x6": 0.95},
        "context": {"domain": "hotel_ops", "task_type": "guest_request"}
    }
    
    print("Input facts:", input_data)
    print("\nNote: To test with real snapshots, use PKGClient and PKGManager")