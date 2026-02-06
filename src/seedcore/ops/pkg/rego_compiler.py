#!/usr/bin/env python3
"""
Rego Compiler for PKG Rules

Translates PKG rule definitions (rule_source, conditions, emissions) into
OPA-compatible Rego policy format.

This module implements the rule_source → Rego translation stage, generating
deterministic Rego modules that output the exact JSON structure expected by
SeedCore's PKG evaluator.
"""

import logging
import json
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class RegoCompiler:
    """
    Compiles PKG rules into OPA-compatible Rego format.
    
    Generates Rego policies that:
    1. Evaluate conditions (TAG, SIGNAL, FACT, SEMANTIC)
    2. Emit subtasks when conditions match
    3. Build DAG edges from relationship types
    4. Return structured result matching SeedCore's expected format
    """
    
    def __init__(self):
        """Initialize the Rego compiler."""
        pass
    
    def compile_snapshot_to_rego(
        self,
        snapshot_id: int,
        snapshot_version: str,
        rules: List[Dict[str, Any]],
        entrypoint: str = "data.pkg.allow"
    ) -> str:
        """
        Compile a complete snapshot's rules into a Rego policy module.
        
        Args:
            snapshot_id: Snapshot ID for provenance
            snapshot_version: Snapshot version string
            rules: List of rule dictionaries with conditions and emissions
            entrypoint: OPA entrypoint path (default: "data.pkg.allow")
            
        Returns:
            Complete Rego policy module as string
        """
        # Build package declaration
        # Entrypoint format: "data.pkg.result" -> package is "pkg" (second segment)
        parts = entrypoint.split(".")
        if len(parts) >= 2 and parts[0] == "data":
            package_name = parts[1]
        else:
            package_name = parts[0] if len(parts) > 0 else "pkg"
        
        rego_lines = [
            f"package {package_name}",
            "",
            "import future.keywords.if",
            "import future.keywords.contains",
            "import future.keywords.in",
            "",
            "# Generated Rego policy for PKG snapshot",
            f"# Snapshot ID: {snapshot_id}",
            f"# Version: {snapshot_version}",
            "",
        ]
        
        # Compile each rule into matched_rules pattern
        for rule in rules:
            rule_rego = self._compile_rule(rule)
            if rule_rego:
                rego_lines.extend(rule_rego)
                rego_lines.append("")
        
        # Add policy decision + aggregate result rule
        # Direct iteration of matched_rules set (no intermediate helper sets needed)
        rego_lines.extend([
            "# Decision rule for WASM entrypoint compatibility",
            "default allow := false",
            "allow if {",
            "    true",
            "}",
            "",
            "# Default result ensures the entrypoint always exists",
            "default result := {",
            '    "subtasks": [],',
            '    "dag": [],',
            '    "rules": []',
            "}",
            "",
            "# Aggregate result from all matched rules",
            "# Function-style decision rule - OPA recognizes this as a valid entrypoint",
            "# Use multi-line comprehensions to avoid ambiguity in Rego v1 parsing",
            "result := out if {",
            "    out := {",
            '        "subtasks": [s |',
            "            some mr",
            "            matched_rules[mr]",
            "            s := mr.subtasks[_]",
            "        ],",
            '        "dag": [e |',
            "            some mr",
            "            matched_rules[mr]",
            "            e := mr.dag[_]",
            "        ],",
            '        "rules": [p |',
            "            some mr",
            "            matched_rules[mr]",
            "            p := mr.provenance",
            "        ]",
            "    }",
            "}",
        ])
        
        return "\n".join(rego_lines)
    
    def _compile_rule(self, rule: Dict[str, Any]) -> List[str]:
        """
        Compile a single rule into Rego.
        
        Args:
            rule: Rule dictionary with conditions and emissions
            
        Returns:
            List of Rego code lines for this rule
        """
        rule_id = rule.get("id")
        rule_name = rule.get("rule_name", "unknown")
        priority = rule.get("priority", 100)
        conditions = rule.get("conditions", [])
        emissions = rule.get("emissions", [])
        
        if not conditions and not emissions:
            logger.warning(f"Rule {rule_name} has no conditions or emissions, skipping")
            return []
        
        # Build condition expressions (now returns list of lines)
        # Use enumerate to generate unique variable names for each condition
        condition_lines = []
        sorted_conditions = sorted(conditions, key=lambda c: (
            c.get("position", 0),
            c.get("condition_type", ""),
            c.get("condition_key", ""),
            c.get("operator", ""),
            str(c.get("value", ""))
        ))
        for idx, cond in enumerate(sorted_conditions):
            cond_lines = self._compile_condition(cond, idx)
            if cond_lines:
                condition_lines.extend(cond_lines)
        
        # If no conditions, rule always matches
        if not condition_lines:
            condition_lines.append("true")
        
        # Build emissions output
        subtasks = []
        dag_edges = []
        rule_provenance = {
            "rule_id": str(rule_id) if rule_id else rule_name,
            "rule_name": rule_name,
            "rule_priority": priority,
            "weight": rule.get("weight", 1.0),
            "matched_conditions": len(conditions),
            "emissions_count": len(emissions)
        }
        
        # Process emissions - sort once and use consistently
        sorted_emissions = sorted(emissions, key=lambda e: e.get("position", 0))
        for i, emission in enumerate(sorted_emissions):
            subtask_name = emission.get("subtask_name") or emission.get("subtask_type", f"{rule_name}_subtask_{i}")
            subtask_type = emission.get("subtask_type") or subtask_name
            params = emission.get("params", {})
            relationship_type = emission.get("relationship_type", "EMITS")
            
            # Build subtask
            subtask = {
                "name": subtask_name,
                "type": subtask_type,
                "params": params,
                "rule_id": str(rule_id) if rule_id else rule_name,
                "rule_name": rule_name
            }
            subtasks.append(subtask)
            
            # Build DAG edges based on relationship type
            if relationship_type == "ORDERS" and i > 0:
                # Sequential dependency: depends on previous emission (use sorted_emissions)
                prev_emission = sorted_emissions[i - 1]
                prev_subtask_name = prev_emission.get("subtask_name") or prev_emission.get("subtask_type", f"{rule_name}_subtask_{i-1}")
                dag_edges.append({
                    "from": prev_subtask_name,
                    "to": subtask_name,
                    "type": "sequential",
                    "rule": rule_name
                })
            elif relationship_type == "GATE":
                # Gate dependency (conditional)
                gate_source = (rule.get("metadata") or {}).get("gate_source")
                if gate_source:
                    dag_edges.append({
                        "from": gate_source,
                        "to": subtask_name,
                        "type": "gate",
                        "rule": rule_name
                    })
            # EMITS: No dependencies (independent subtask)
        
        # Generate Rego rule using matched_rules pattern:
        # matched_rules contains mr if {
        #     conditions
        #     mr := { "subtasks": [...], "dag": [...], "provenance": {...} }
        # }
        rego_lines = [
            f"# Rule: {rule_name} (priority: {priority})",
            "matched_rules contains mr if {",
        ]
        
        # Add conditions first (indented)
        for cond_line in condition_lines:
            rego_lines.append(f"    {cond_line}")
        
        # Define helper variables (subtasks, dag, provenance)
        rego_lines.append("    ")
        rego_lines.append("    # Define subtasks")
        if subtasks:
            rego_lines.append("    subtasks := [")
            for i, subtask in enumerate(subtasks):
                rego_lines.append("        {")
                name = subtask["name"].replace('"', '\\"')
                stype = subtask["type"].replace('"', '\\"')
                rule_id_str = str(subtask.get("rule_id", "")).replace('"', '\\"')
                rule_name_str = subtask.get("rule_name", "").replace('"', '\\"')
                
                rego_lines.append(f'            "name": "{name}",')
                rego_lines.append(f'            "type": "{stype}",')
                
                # Build params object
                params = subtask.get("params", {})
                if params:
                    params_parts = []
                    for k, v in params.items():
                        k_escaped = str(k).replace('"', '\\"')
                        # Use _format_value for all values to ensure proper Rego formatting
                        v_formatted = self._format_value(v)
                        params_parts.append(f'"{k_escaped}": {v_formatted}')
                    params_str = ", ".join(params_parts)
                    rego_lines.append(f'            "params": {{{params_str}}},')
                else:
                    rego_lines.append('            "params": {},')
                
                rego_lines.append(f'            "rule_id": "{rule_id_str}",')
                rego_lines.append(f'            "rule_name": "{rule_name_str}"')
                if i < len(subtasks) - 1:
                    rego_lines.append("        },")
                else:
                    rego_lines.append("        }")
            rego_lines.append("    ]")
        else:
            rego_lines.append("    subtasks := []")
        
        # Define DAG edges
        rego_lines.append("    ")
        rego_lines.append("    # Define DAG edges")
        if dag_edges:
            rego_lines.append("    dag := [")
            for i, edge in enumerate(dag_edges):
                rego_lines.append("        {")
                from_val = edge["from"].replace('"', '\\"')
                to_val = edge["to"].replace('"', '\\"')
                etype = edge["type"].replace('"', '\\"')
                rule = edge["rule"].replace('"', '\\"')
                
                rego_lines.append(f'            "from": "{from_val}",')
                rego_lines.append(f'            "to": "{to_val}",')
                rego_lines.append(f'            "type": "{etype}",')
                rego_lines.append(f'            "rule": "{rule}"')
                if i < len(dag_edges) - 1:
                    rego_lines.append("        },")
                else:
                    rego_lines.append("        }")
            rego_lines.append("    ]")
        else:
            rego_lines.append("    dag := []")
        
        # Define provenance
        rego_lines.append("    ")
        rego_lines.append("    # Define provenance")
        rego_lines.append("    provenance := {")
        # Use _format_value for all fields to prevent Python stringification (e.g., False -> false)
        rule_id_val = self._format_value(rule_provenance["rule_id"])
        rule_name_val = self._format_value(rule_provenance["rule_name"])
        priority_val = self._format_value(rule_provenance["rule_priority"])
        weight_val = self._format_value(rule_provenance["weight"])
        cond_count = self._format_value(rule_provenance["matched_conditions"])
        emissions_count = self._format_value(rule_provenance["emissions_count"])
        rego_lines.append(f'        "rule_id": {rule_id_val},')
        rego_lines.append(f'        "rule_name": {rule_name_val},')
        rego_lines.append(f'        "rule_priority": {priority_val},')
        rego_lines.append(f'        "weight": {weight_val},')
        rego_lines.append(f'        "matched_conditions": {cond_count},')
        rego_lines.append(f'        "emissions_count": {emissions_count}')
        rego_lines.append("    }")
        
        # Define the rule value
        rego_lines.append("    ")
        rego_lines.append("    # Define rule value")
        rego_lines.append("    mr := {")
        rego_lines.append('        "subtasks": subtasks,')
        rego_lines.append('        "dag": dag,')
        rego_lines.append('        "provenance": provenance')
        rego_lines.append("    }")
        
        rego_lines.append("}")
        
        return rego_lines
    
    def _compile_condition(self, condition: Dict[str, Any], idx: int = 0) -> List[str]:
        """
        Compile a single condition into Rego expression lines.
        
        Args:
            condition: Condition dictionary
            idx: Index of this condition within the rule (for unique variable naming)
            
        Returns:
            List of Rego expression lines (can be multiple lines for SIGNAL with object.get)
        """
        condition_type = condition.get("condition_type", "TAG")
        condition_key = condition.get("condition_key", "")
        operator = condition.get("operator", "EXISTS")
        value = condition.get("value")
        
        if condition_type == "TAG":
            # TAG condition: check tags array in input.tags
            # For MATCHES: condition_key is "tags" (the array name), value is the regex pattern
            # For other operators: condition_key may be the tag value to match
            # Use unique variable name per condition to avoid redeclaration errors
            tag_var = f"tag_idx_{idx}"
            
            if operator == "MATCHES":
                # Regex match: check if any tag matches the pattern
                # Pattern is stored in value, condition_key is typically "tags"
                pattern = str(value) if value is not None else ""
                # Escape quotes in pattern for Rego string literal
                pattern_escaped = pattern.replace('"', '\\"')
                # Use regex.match() for Rego v1 compatibility (re_match() is deprecated)
                return [f"some {tag_var}; regex.match(\"{pattern_escaped}\", input.tags[{tag_var}])"]
            elif operator in ("IN", "EXISTS", "="):
                # Exact match: check if tag exists with exact value
                # condition_key is the tag value to match
                tag_value_escaped = str(condition_key).replace('"', '\\"')
                return [f'some {tag_var}; input.tags[{tag_var}] == "{tag_value_escaped}"']
            elif operator == "!=":
                # Check if tag does NOT exist (with parentheses for clarity)
                # Use unique variable name inside negation to avoid unsafe variable errors
                tag_value_escaped = str(condition_key).replace('"', '\\"')
                neg_var = f"tag_neg_{idx}"
                return [f'not (some {neg_var}; input.tags[{neg_var}] == "{tag_value_escaped}")']
            else:
                logger.warning(f"Unsupported TAG operator: {operator}")
                return []
        
        elif condition_type == "SIGNAL":
            # SIGNAL condition: compare signal value using object.get for missing keys
            signal_key = condition_key
            var_name = f"signal_val_{signal_key.replace('.', '_').replace('-', '_')}"
            
            if operator == "EXISTS":
                # Check if signal exists (not null)
                return [
                    f'{var_name} := object.get(input.signals, "{signal_key}", null)',
                    f'{var_name} != null'
                ]
            elif operator == "=":
                return [
                    f'{var_name} := object.get(input.signals, "{signal_key}", null)',
                    f'{var_name} != null',
                    f'{var_name} == {self._format_value(value)}'
                ]
            elif operator == "!=":
                return [
                    f'{var_name} := object.get(input.signals, "{signal_key}", null)',
                    f'{var_name} != {self._format_value(value)}'
                ]
            elif operator == ">=":
                # Use to_number() for numeric comparisons to avoid string comparison issues
                # Convert value to number if it's a string representation of a number
                numeric_value = self._format_numeric_value(value)
                return [
                    f'{var_name} := object.get(input.signals, "{signal_key}", null)',
                    f'{var_name} != null',
                    f'to_number({var_name}) >= {numeric_value}'
                ]
            elif operator == "<=":
                # Use to_number() for numeric comparisons to avoid string comparison issues
                numeric_value = self._format_numeric_value(value)
                return [
                    f'{var_name} := object.get(input.signals, "{signal_key}", null)',
                    f'{var_name} != null',
                    f'to_number({var_name}) <= {numeric_value}'
                ]
            elif operator == ">":
                # Use to_number() for numeric comparisons to avoid string comparison issues
                numeric_value = self._format_numeric_value(value)
                return [
                    f'{var_name} := object.get(input.signals, "{signal_key}", null)',
                    f'{var_name} != null',
                    f'to_number({var_name}) > {numeric_value}'
                ]
            elif operator == "<":
                # Use to_number() for numeric comparisons to avoid string comparison issues
                numeric_value = self._format_numeric_value(value)
                return [
                    f'{var_name} := object.get(input.signals, "{signal_key}", null)',
                    f'{var_name} != null',
                    f'to_number({var_name}) < {numeric_value}'
                ]
            else:
                logger.warning(f"Unsupported SIGNAL operator: {operator}")
                return []
        
        elif condition_type == "FACT":
            # FACT condition: check governed_facts array
            subject = condition_key  # condition_key is the subject
            predicate = condition.get("predicate") or condition.get("field_path", "")
            
            if operator in ("EXISTS", "="):
                # Check if fact exists
                return [f'some fact_idx; fact := input.governed_facts[fact_idx]; fact.subject == "{subject}"; fact.predicate == "{predicate}"']
            elif operator == "!=":
                # Check if fact does NOT exist
                return [f'not (some fact_idx; fact := input.governed_facts[fact_idx]; fact.subject == "{subject}"; fact.predicate == "{predicate}")']
            else:
                # For other operators, check object_data value
                if value:
                    return [f'some fact_idx; fact := input.governed_facts[fact_idx]; fact.subject == "{subject}"; fact.predicate == "{predicate}"; fact.object_data == {self._format_value(value)}']
                else:
                    return [f'some fact_idx; fact := input.governed_facts[fact_idx]; fact.subject == "{subject}"; fact.predicate == "{predicate}"']
        
        elif condition_type == "SEMANTIC":
            # SEMANTIC condition: check semantic_context for category/similarity
            target_category = condition_key
            min_similarity = float(value) if value is not None else 0.85
            
            if operator in ("EXISTS", "=", ">="):
                return [f'some mem_idx; mem := input.semantic_context[mem_idx]; mem.category == "{target_category}"; mem.similarity >= {min_similarity}']
            elif operator == ">":
                return [f'some mem_idx; mem := input.semantic_context[mem_idx]; mem.category == "{target_category}"; mem.similarity > {min_similarity}']
            else:
                logger.warning(f"Unsupported SEMANTIC operator: {operator}")
                return []
        
        else:
            # Default: field_path-based evaluation
            field_path = condition.get("field_path", condition_key)
            
            if operator == "EXISTS":
                # Use object.get for resilient field access
                field_access = self._build_field_access_resilient(field_path)
                return [f'{field_access} != null']
            elif operator == "IN":
                field_access = self._build_field_access(field_path)
                if isinstance(value, list):
                    value_list = ", ".join(self._format_value(v) for v in value)
                    return [f'{field_access} in [{value_list}]']
                else:
                    return [f'{field_access} == {self._format_value(value)}']
            else:
                # For comparisons, use direct field access (undefined if missing is acceptable)
                field_access = self._build_field_access(field_path)
                if operator == "=":
                    return [f'{field_access} == {self._format_value(value)}']
                elif operator == "!=":
                    return [f'{field_access} != {self._format_value(value)}']
                elif operator == ">=":
                    return [f'{field_access} >= {self._format_value(value)}']
                elif operator == "<=":
                    return [f'{field_access} <= {self._format_value(value)}']
                elif operator == ">":
                    return [f'{field_access} > {self._format_value(value)}']
                elif operator == "<":
                    return [f'{field_access} < {self._format_value(value)}']
                else:
                    logger.warning(f"Unsupported operator: {operator} for condition type: {condition_type}")
                    return []
    
    def _build_field_access(self, field_path: str) -> str:
        """Build Rego field access expression from dot-notation path."""
        parts = field_path.split(".")
        access = "input"
        for part in parts:
            if part.isdigit():
                access = f"{access}[{part}]"
            else:
                access = f'{access}["{part}"]'
        return access
    
    def _build_field_access_resilient(self, field_path: str) -> str:
        """
        Build resilient Rego field access using object.get for EXISTS checks.
        
        For paths like "context.domain", generates:
        object.get(object.get(input, "context", {}), "domain", null)
        """
        parts = field_path.split(".")
        if not parts:
            return "input"
        
        # Build nested object.get calls
        access = "input"
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # Last part: return null if missing
                access = f'object.get({access}, "{part}", null)'
            else:
                # Intermediate parts: return empty object if missing
                access = f'object.get({access}, "{part}", {{}})'
        return access
    
    def _format_numeric_value(self, value: Any) -> str:
        """
        Format a value as a numeric literal for Rego numeric comparisons.
        
        Converts string representations of numbers to unquoted numeric literals.
        """
        if isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Try to parse as number - if successful, return unquoted numeric literal
            try:
                # Try float first (handles both int and float strings)
                num_val = float(value)
                # If it's a whole number, return as int string, otherwise float
                if num_val.is_integer():
                    return str(int(num_val))
                return str(num_val)
            except (ValueError, TypeError):
                # If not a number, return as-is (will be quoted by _format_value)
                return self._format_value(value)
        else:
            # For non-string, non-numeric values, try to convert
            try:
                return str(float(value))
            except (ValueError, TypeError):
                return self._format_value(value)
    
    def _format_value(self, value: Any) -> str:
        """Format a value for Rego (JSON-like)."""
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Escape quotes and wrap in quotes
            escaped = value.replace('"', '\\"')
            return f'"{escaped}"'
        elif isinstance(value, (list, dict)):
            return json.dumps(value)
        else:
            return json.dumps(value)
