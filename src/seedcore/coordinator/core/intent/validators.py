"""
Intent validators: Safety checks and sanity validation for routing intent.

This module provides validation logic that ensures RoutingIntent is:
- Structurally valid (required fields present)
- Semantically consistent (specialization exists, skills are valid)
- Policy-compliant (meets Coordinator safety requirements)

Future enhancements:
- Specialization registry validation
- Skills range validation (0.0 - 1.0)
- Policy constraint checking
"""

from typing import List, Any, Optional

from seedcore.logging_setup import ensure_serve_logger
from seedcore.agents.roles import Specialization
from .model import RoutingIntent

logger = ensure_serve_logger("seedcore.coordinator.core.intent.validators")


class IntentValidator:
    """
    Validate routing intent for safety and consistency.
    
    This class provides validation logic that ensures RoutingIntent
    meets Coordinator requirements before routing decisions are made.
    """
    
    @staticmethod
    def validate(intent: Optional[RoutingIntent], ctx: Any) -> List[str]:
        """
        Validate routing intent and return list of validation errors.
        
        Args:
            intent: RoutingIntent to validate (None if extraction failed)
            ctx: TaskContext for context-aware validation
        
        Returns:
            List of validation error messages (empty if valid)
        """
        errors: List[str] = []
        
        # Check if intent was extracted at all
        if intent is None:
            task_id = getattr(ctx, "task_id", "unknown")
            errors.append(
                f"No routing hints found in proto_plan for task {task_id}. "
                "PKG policy evaluation should always include required_specialization or "
                "specialization in proto_plan.routing or step.task.params.routing."
            )
            return errors
        
        # Check if intent has specialization (required for explicit PKG routing)
        if intent.is_explicit() and not intent.specialization:
            errors.append(
                "PKG routing intent is explicit but missing specialization. "
                "PKG should always provide required_specialization or specialization."
            )
        
        # Validate specialization exists in registry (if provided)
        if intent.specialization:
            try:
                # Check if specialization is a valid Specialization enum value
                valid_specializations = {s.value for s in Specialization}
                if intent.specialization not in valid_specializations:
                    # Allow non-enum values for extensibility, but log warning
                    logger.debug(
                        f"[IntentValidator] Specialization '{intent.specialization}' "
                        "not found in Specialization enum (may be custom)"
                    )
            except Exception as e:
                logger.debug(f"[IntentValidator] Error validating specialization: {e}")
        
        # Validate skills are in valid range (0.0 - 1.0)
        if intent.skills:
            for skill_name, skill_level in intent.skills.items():
                try:
                    level = float(skill_level)
                    if level < 0.0 or level > 1.0:
                        errors.append(
                            f"Skill '{skill_name}' has invalid level {level}. "
                            "Skills must be between 0.0 and 1.0."
                        )
                except (ValueError, TypeError):
                    errors.append(
                        f"Skill '{skill_name}' has non-numeric level: {skill_level}"
                    )
        
        return errors
    
    @staticmethod
    def is_valid(intent: Optional[RoutingIntent], ctx: Any) -> bool:
        """
        Check if routing intent is valid.
        
        Args:
            intent: RoutingIntent to validate
            ctx: TaskContext for context-aware validation
        
        Returns:
            True if valid, False otherwise
        """
        return len(IntentValidator.validate(intent, ctx)) == 0
    
    @staticmethod
    def validate_and_log(intent: Optional[RoutingIntent], ctx: Any) -> bool:
        """
        Validate routing intent and log errors.
        
        Args:
            intent: RoutingIntent to validate
            ctx: TaskContext for context-aware validation
        
        Returns:
            True if valid, False otherwise
        """
        errors = IntentValidator.validate(intent, ctx)
        
        if errors:
            task_id = getattr(ctx, "task_id", "unknown")
            for error in errors:
                logger.warning(f"[IntentValidator] Task {task_id}: {error}")
            return False
        
        return True
