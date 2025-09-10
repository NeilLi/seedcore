"""
Pydantic schema for predicate YAML configuration.

This module defines the structure and validation rules for predicate configuration
files, ensuring type safety and proper validation of routing rules.
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Literal, Optional, Dict, Any
import re

class Rule(BaseModel):
    """A single routing or mutation rule."""
    when: str = Field(..., description="Boolean expression over canonical signals & task fields")
    do: str = Field(..., description="Action directive")
    priority: int = Field(default=0, description="Rule priority (higher = more important)")
    description: Optional[str] = Field(default=None, description="Human-readable description")
    
    @field_validator("when")
    @classmethod
    def validate_when_expression(cls, v):
        """Basic validation of the when expression."""
        if not v or not v.strip():
            raise ValueError("When expression cannot be empty")
        return v.strip()
    
    @field_validator("do")
    @classmethod
    def validate_do_action(cls, v):
        """Basic validation of the do action."""
        if not v or not v.strip():
            raise ValueError("Do action cannot be empty")
        return v.strip()

class GpuGuard(BaseModel):
    """GPU guard configuration."""
    max_concurrent: int = Field(..., description="Maximum concurrent GPU jobs", ge=1)
    daily_budget_hours: float = Field(..., description="Daily GPU budget in hours", gt=0.0)
    cooldown_minutes: int = Field(..., description="Cooldown period between jobs in minutes", ge=0)
    queue_timeout_minutes: int = Field(default=30, description="Queue timeout in minutes", ge=1)
    
    @field_validator("daily_budget_hours")
    @classmethod
    def validate_daily_budget(cls, v):
        if v > 24:
            raise ValueError("Daily budget cannot exceed 24 hours")
        return v

class Metadata(BaseModel):
    """Configuration metadata."""
    version: str = Field(..., description="Configuration version")
    commit: str = Field(..., description="Git commit hash")
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")
    description: Optional[str] = Field(default=None, description="Configuration description")

class PredicatesConfig(BaseModel):
    """Complete predicate configuration."""
    routing: List[Rule] = Field(..., description="Routing rules for task path selection")
    mutations: List[Rule] = Field(..., description="Mutation rules for tuning/retraining")
    gpu_guard: GpuGuard = Field(..., description="GPU guard configuration")
    metadata: Metadata = Field(..., description="Configuration metadata")
    
    # Feature flags for emergency control
    routing_enabled: bool = Field(default=True, description="Enable routing rules")
    mutations_enabled: bool = Field(default=True, description="Enable mutation rules")
    gpu_guard_enabled: bool = Field(default=True, description="Enable GPU guard system")
    
    # Optional configuration sections
    alerts: Optional[Dict[str, Any]] = Field(default=None, description="Alert configuration")
    fallback: Optional[Dict[str, str]] = Field(default=None, description="Fallback actions")
    
    @field_validator("routing", "mutations")
    @classmethod
    def validate_rules_not_empty(cls, v):
        """Ensure rules sections are not empty."""
        if not v:
            raise ValueError("Rules section cannot be empty")
        return v
    
    @field_validator("routing")
    @classmethod
    def validate_routing_rules(cls, v):
        """Validate routing rules have valid actions."""
        valid_actions = {"escalate", "fast_path", "hold", "retry"}
        for rule in v:
            action = rule.do.split(":")[0] if ":" in rule.do else rule.do
            if action not in valid_actions:
                raise ValueError(f"Invalid routing action: {action}")
        return v
    
    @field_validator("mutations")
    @classmethod
    def validate_mutation_rules(cls, v):
        """Validate mutation rules have valid actions."""
        valid_actions = {"submit_tuning", "submit_retrain", "hold", "skip"}
        for rule in v:
            action = rule.do.split(":")[0] if ":" in rule.do else rule.do
            if action not in valid_actions:
                raise ValueError(f"Invalid mutation action: {action}")
        return v

class TaskContext(BaseModel):
    """Context for task evaluation."""
    type: str = Field(..., description="Task type")
    domain: Optional[str] = Field(default=None, description="Task domain")
    priority: int = Field(default=5, description="Task priority", ge=1, le=10)
    complexity: float = Field(default=0.5, description="Task complexity", ge=0.0, le=1.0)
    features: Dict[str, Any] = Field(default_factory=dict, description="Task features")

class DecisionContext(BaseModel):
    """Context for decision evaluation."""
    action: str = Field(..., description="Decision action")
    confidence: float = Field(default=0.5, description="Decision confidence", ge=0.0, le=1.0)
    reasoning: Optional[str] = Field(default=None, description="Decision reasoning")

class EvaluationContext(BaseModel):
    """Complete evaluation context."""
    task: TaskContext = Field(..., description="Task context")
    decision: DecisionContext = Field(..., description="Decision context")
    signals: Dict[str, Any] = Field(default_factory=dict, description="Signal values")
    gpu: Dict[str, Any] = Field(default_factory=dict, description="GPU guard state")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for evaluation."""
        return {
            "task": self.task.model_dump(),
            "decision": self.decision.model_dump(),
            **self.signals,
            "gpu": self.gpu
        }

# Allowed symbols for expression validation
ALLOWED_TASK_FIELDS = {"type", "domain", "priority", "complexity"}
ALLOWED_DECISION_FIELDS = {"action", "confidence", "reasoning"}
ALLOWED_OPERATORS = {"and", "or", "not", "in", "True", "False", "None", "true", "false"}

def validate_expression_symbols(expr: str) -> List[str]:
    """Extract and validate symbols used in an expression."""
    # Remove string literals first to avoid matching them as symbols
    # This regex matches single or double quoted strings
    string_literal_re = re.compile(r'["\'][^"\']*["\']')
    expr_without_strings = string_literal_re.sub('""', expr)
    
    # Simple regex to find identifiers (but not inside string literals)
    symbol_re = re.compile(r'\b([A-Za-z_Δ][A-Za-z0-9_Δ\.]*)\b')
    symbols = symbol_re.findall(expr_without_strings)
    
    # Filter out operators and literals
    valid_symbols = []
    for symbol in symbols:
        if "." in symbol:
            # Handle dotted access like task.type
            base, field = symbol.split(".", 1)
            if base == "task" and field in ALLOWED_TASK_FIELDS:
                valid_symbols.append(symbol)
            elif base == "decision" and field in ALLOWED_DECISION_FIELDS:
                valid_symbols.append(symbol)
            elif base == "gpu":
                valid_symbols.append(symbol)
        elif symbol in ALLOWED_OPERATORS:
            continue  # Skip operators
        elif symbol.replace(".", "").isnumeric():
            continue  # Skip numbers
        else:
            # Check if it's a known signal
            from .signals import SIGNALS
            if symbol in SIGNALS:
                valid_symbols.append(symbol)
            else:
                raise ValueError(f"Unknown or disallowed symbol in expression: {symbol}")
    
    return valid_symbols
