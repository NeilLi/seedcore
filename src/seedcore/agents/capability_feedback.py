"""
Capability feedback and improvement system for SeedCore agents.

This module provides a feedback-driven mechanism for agents to improve their
capabilities based on cognitive reasoning quality and performance.
"""

import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import statistics

logger = logging.getLogger(__name__)


class FeedbackType(Enum):
    """Types of feedback for agent capabilities."""
    COGNITIVE_QUALITY = "cognitive_quality"
    TASK_SUCCESS = "task_success"
    REASONING_ACCURACY = "reasoning_accuracy"
    DECISION_QUALITY = "decision_quality"
    MEMORY_EFFICIENCY = "memory_efficiency"
    ENERGY_EFFICIENCY = "energy_efficiency"
    COLLABORATION = "collaboration"
    INNOVATION = "innovation"


class CapabilityLevel(Enum):
    """Agent capability levels."""
    NOVICE = "novice"
    APPRENTICE = "apprentice"
    JOURNEYMAN = "journeyman"
    EXPERT = "expert"
    MASTER = "master"


@dataclass
class CapabilityFeedback:
    """Individual feedback entry for agent capabilities."""
    agent_id: str
    feedback_type: FeedbackType
    score: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    context: Dict[str, Any]
    timestamp: float
    evaluator: str  # Who provided the feedback
    reasoning: Optional[str] = None


@dataclass
class CapabilityAssessment:
    """Comprehensive capability assessment for an agent."""
    agent_id: str
    current_level: CapabilityLevel
    target_level: CapabilityLevel
    overall_score: float
    capability_scores: Dict[str, float]
    improvement_areas: List[str]
    strengths: List[str]
    promotion_ready: bool
    last_assessment: float
    assessment_count: int


class QualityEvaluator:
    """Evaluates the quality of cognitive reasoning outputs."""
    
    def __init__(self):
        self.evaluation_criteria = {
            FeedbackType.COGNITIVE_QUALITY: {
                "clarity": 0.3,
                "completeness": 0.3,
                "accuracy": 0.4
            },
            FeedbackType.REASONING_ACCURACY: {
                "logical_consistency": 0.4,
                "evidence_quality": 0.3,
                "conclusion_validity": 0.3
            },
            FeedbackType.DECISION_QUALITY: {
                "option_analysis": 0.3,
                "risk_assessment": 0.3,
                "outcome_prediction": 0.4
            }
        }
    
    def evaluate_cognitive_output(self, output: Dict[str, Any], task_type: str) -> Dict[str, float]:
        """
        Evaluate the quality of a cognitive reasoning output.
        
        Args:
            output: The cognitive reasoning output
            task_type: Type of cognitive task
            
        Returns:
            Dictionary of quality scores
        """
        scores = {}
        
        # Basic quality metrics
        scores["clarity"] = self._evaluate_clarity(output)
        scores["completeness"] = self._evaluate_completeness(output)
        scores["relevance"] = self._evaluate_relevance(output, task_type)
        scores["confidence_alignment"] = self._evaluate_confidence_alignment(output)
        
        # Task-specific evaluations
        if task_type == "failure_analysis":
            scores["root_cause_analysis"] = self._evaluate_root_cause_analysis(output)
            scores["solution_feasibility"] = self._evaluate_solution_feasibility(output)
        elif task_type == "task_planning":
            scores["plan_structure"] = self._evaluate_plan_structure(output)
            scores["resource_consideration"] = self._evaluate_resource_consideration(output)
        elif task_type == "decision_making":
            scores["option_analysis"] = self._evaluate_option_analysis(output)
            scores["risk_assessment"] = self._evaluate_risk_assessment(output)
        
        return scores
    
    def _evaluate_clarity(self, output: Dict[str, Any]) -> float:
        """Evaluate the clarity of the output."""
        text_fields = []
        for key, value in output.items():
            if isinstance(value, str) and key not in ["error", "success"]:
                text_fields.append(value)
        
        if not text_fields:
            return 0.5
        
        # Simple heuristics for clarity
        total_length = sum(len(text) for text in text_fields)
        avg_length = total_length / len(text_fields)
        
        # Prefer medium-length responses (not too short, not too long)
        if 50 <= avg_length <= 500:
            return 0.9
        elif 20 <= avg_length <= 1000:
            return 0.7
        else:
            return 0.4
    
    def _evaluate_completeness(self, output: Dict[str, Any]) -> float:
        """Evaluate the completeness of the output."""
        required_fields = {
            "failure_analysis": ["thought", "proposed_solution"],
            "task_planning": ["step_by_step_plan", "estimated_complexity"],
            "decision_making": ["reasoning", "decision", "confidence"],
            "problem_solving": ["solution_approach", "solution_steps"],
            "memory_synthesis": ["synthesized_insight", "confidence_level"],
            "capability_assessment": ["capability_gaps", "improvement_plan"]
        }
        
        # Default completeness score
        completeness = 0.5
        
        # Check if output has required fields
        if "task_type" in output:
            task_type = output["task_type"]
            if task_type in required_fields:
                present_fields = sum(1 for field in required_fields[task_type] if field in output)
                completeness = present_fields / len(required_fields[task_type])
        
        return completeness
    
    def _evaluate_relevance(self, output: Dict[str, Any], task_type: str) -> float:
        """Evaluate the relevance of the output to the task."""
        # Simple keyword-based relevance check
        relevance_keywords = {
            "failure_analysis": ["error", "problem", "issue", "solution", "fix"],
            "task_planning": ["plan", "step", "task", "resource", "timeline"],
            "decision_making": ["decision", "option", "choice", "reasoning"],
            "problem_solving": ["solution", "approach", "method", "strategy"],
            "memory_synthesis": ["pattern", "insight", "synthesis", "connection"],
            "capability_assessment": ["capability", "skill", "improvement", "gap"]
        }
        
        if task_type not in relevance_keywords:
            return 0.5
        
        keywords = relevance_keywords[task_type]
        text_content = " ".join(str(v) for v in output.values() if isinstance(v, str))
        text_lower = text_content.lower()
        
        keyword_matches = sum(1 for keyword in keywords if keyword in text_lower)
        relevance = min(1.0, keyword_matches / len(keywords))
        
        return relevance
    
    def _evaluate_confidence_alignment(self, output: Dict[str, Any]) -> float:
        """Evaluate if confidence scores align with output quality."""
        if "confidence_score" not in output:
            return 0.5
        
        confidence = output["confidence_score"]
        if not isinstance(confidence, (int, float)):
            return 0.5
        
        # Simple heuristic: confidence should be reasonable (not too high for poor outputs)
        quality_indicators = [
            self._evaluate_clarity(output),
            self._evaluate_completeness(output)
        ]
        avg_quality = statistics.mean(quality_indicators)
        
        # Penalize overconfidence or underconfidence
        confidence_diff = abs(confidence - avg_quality)
        alignment = max(0.0, 1.0 - confidence_diff)
        
        return alignment
    
    def _evaluate_root_cause_analysis(self, output: Dict[str, Any]) -> float:
        """Evaluate root cause analysis quality."""
        thought = output.get("thought", "")
        if not thought:
            return 0.0
        
        # Look for root cause indicators
        root_cause_indicators = ["root cause", "underlying", "fundamental", "core issue", "primary reason"]
        indicators_found = sum(1 for indicator in root_cause_indicators if indicator in thought.lower())
        
        return min(1.0, indicators_found / len(root_cause_indicators))
    
    def _evaluate_solution_feasibility(self, output: Dict[str, Any]) -> float:
        """Evaluate solution feasibility."""
        solution = output.get("proposed_solution", "")
        if not solution:
            return 0.0
        
        # Look for actionable solution indicators
        action_indicators = ["implement", "deploy", "configure", "update", "modify", "add", "remove"]
        indicators_found = sum(1 for indicator in action_indicators if indicator in solution.lower())
        
        return min(1.0, indicators_found / len(action_indicators))
    
    def _evaluate_plan_structure(self, output: Dict[str, Any]) -> float:
        """Evaluate plan structure quality."""
        plan = output.get("step_by_step_plan", "")
        if not plan:
            return 0.0
        
        # Look for structured planning indicators
        structure_indicators = ["step", "phase", "stage", "first", "second", "then", "finally"]
        indicators_found = sum(1 for indicator in structure_indicators if indicator in plan.lower())
        
        return min(1.0, indicators_found / len(structure_indicators))
    
    def _evaluate_resource_consideration(self, output: Dict[str, Any]) -> float:
        """Evaluate resource consideration in planning."""
        plan = output.get("step_by_step_plan", "")
        if not plan:
            return 0.0
        
        # Look for resource consideration indicators
        resource_indicators = ["resource", "time", "budget", "personnel", "equipment", "cost"]
        indicators_found = sum(1 for indicator in resource_indicators if indicator in plan.lower())
        
        return min(1.0, indicators_found / len(resource_indicators))
    
    def _evaluate_option_analysis(self, output: Dict[str, Any]) -> float:
        """Evaluate option analysis quality."""
        reasoning = output.get("reasoning", "")
        if not reasoning:
            return 0.0
        
        # Look for option analysis indicators
        analysis_indicators = ["option", "alternative", "compare", "pros", "cons", "benefit", "risk"]
        indicators_found = sum(1 for indicator in analysis_indicators if indicator in reasoning.lower())
        
        return min(1.0, indicators_found / len(analysis_indicators))
    
    def _evaluate_risk_assessment(self, output: Dict[str, Any]) -> float:
        """Evaluate risk assessment quality."""
        reasoning = output.get("reasoning", "")
        if not reasoning:
            return 0.0
        
        # Look for risk assessment indicators
        risk_indicators = ["risk", "threat", "vulnerability", "mitigation", "contingency", "fallback"]
        indicators_found = sum(1 for indicator in risk_indicators if indicator in reasoning.lower())
        
        return min(1.0, indicators_found / len(risk_indicators))


class CapabilityManager:
    """
    Manages agent capability assessment and improvement.
    
    This class provides:
    - Quality evaluation of cognitive outputs
    - Capability scoring and tracking
    - Feedback aggregation and analysis
    - Promotion recommendations
    - Improvement planning
    """
    
    def __init__(self):
        self.quality_evaluator = QualityEvaluator()
        self.feedback_history: List[CapabilityFeedback] = []
        self.agent_assessments: Dict[str, CapabilityAssessment] = {}
        self.capability_thresholds = {
            CapabilityLevel.NOVICE: 0.0,
            CapabilityLevel.APPRENTICE: 0.3,
            CapabilityLevel.JOURNEYMAN: 0.5,
            CapabilityLevel.EXPERT: 0.7,
            CapabilityLevel.MASTER: 0.9
        }
        
        logger.info("✅ Capability manager initialized")
    
    def evaluate_cognitive_task(
        self,
        agent_id: str,
        task_type: str,
        output: Dict[str, Any],
        context: Dict[str, Any]
    ) -> CapabilityFeedback:
        """
        Evaluate a cognitive task output and generate feedback.
        
        Args:
            agent_id: ID of the agent
            task_type: Type of cognitive task
            output: Task output to evaluate
            context: Additional context for evaluation
            
        Returns:
            Capability feedback
        """
        # Evaluate output quality
        quality_scores = self.quality_evaluator.evaluate_cognitive_output(output, task_type)
        overall_score = statistics.mean(quality_scores.values())
        
        # Determine feedback type
        feedback_type = self._map_task_type_to_feedback(task_type)
        
        # Generate feedback
        feedback = CapabilityFeedback(
            agent_id=agent_id,
            feedback_type=feedback_type,
            score=overall_score,
            confidence=output.get("confidence_score", 0.5),
            context={
                "task_type": task_type,
                "quality_scores": quality_scores,
                "output_keys": list(output.keys()),
                **context
            },
            timestamp=time.time(),
            evaluator="quality_evaluator",
            reasoning=self._generate_feedback_reasoning(quality_scores, task_type)
        )
        
        # Store feedback
        self.feedback_history.append(feedback)
        
        # Update agent assessment
        self._update_agent_assessment(agent_id, feedback)
        
        logger.info(f"✅ Evaluated cognitive task for agent {agent_id}: {overall_score:.3f}")
        return feedback
    
    def add_manual_feedback(
        self,
        agent_id: str,
        feedback_type: FeedbackType,
        score: float,
        confidence: float,
        context: Dict[str, Any],
        evaluator: str,
        reasoning: Optional[str] = None
    ) -> CapabilityFeedback:
        """
        Add manual feedback for an agent.
        
        Args:
            agent_id: ID of the agent
            feedback_type: Type of feedback
            score: Quality score (0.0 to 1.0)
            confidence: Confidence in the feedback (0.0 to 1.0)
            context: Additional context
            evaluator: Who provided the feedback
            reasoning: Optional reasoning for the feedback
            
        Returns:
            Capability feedback
        """
        feedback = CapabilityFeedback(
            agent_id=agent_id,
            feedback_type=feedback_type,
            score=score,
            confidence=confidence,
            context=context,
            timestamp=time.time(),
            evaluator=evaluator,
            reasoning=reasoning
        )
        
        self.feedback_history.append(feedback)
        self._update_agent_assessment(agent_id, feedback)
        
        logger.info(f"✅ Added manual feedback for agent {agent_id}: {score:.3f}")
        return feedback
    
    def get_agent_assessment(self, agent_id: str) -> Optional[CapabilityAssessment]:
        """Get current capability assessment for an agent."""
        return self.agent_assessments.get(agent_id)
    
    def get_agent_feedback_history(self, agent_id: str, limit: int = 100) -> List[CapabilityFeedback]:
        """Get feedback history for an agent."""
        agent_feedback = [f for f in self.feedback_history if f.agent_id == agent_id]
        return sorted(agent_feedback, key=lambda x: x.timestamp, reverse=True)[:limit]
    
    def get_promotion_recommendations(self, min_score: float = 0.7) -> List[Tuple[str, CapabilityLevel]]:
        """Get agents recommended for promotion."""
        recommendations = []
        
        for agent_id, assessment in self.agent_assessments.items():
            if assessment.overall_score >= min_score and assessment.promotion_ready:
                next_level = self._get_next_level(assessment.current_level)
                if next_level:
                    recommendations.append((agent_id, next_level))
        
        return sorted(recommendations, key=lambda x: self.agent_assessments[x[0]].overall_score, reverse=True)
    
    def get_improvement_plan(self, agent_id: str) -> Dict[str, Any]:
        """Generate improvement plan for an agent."""
        assessment = self.get_agent_assessment(agent_id)
        if not assessment:
            return {"error": "No assessment available for agent"}
        
        # Analyze feedback history
        recent_feedback = self.get_agent_feedback_history(agent_id, limit=50)
        
        # Identify improvement areas
        improvement_areas = []
        for area in assessment.improvement_areas:
            improvement_areas.append({
                "area": area,
                "current_score": assessment.capability_scores.get(area, 0.0),
                "target_score": 0.8,
                "suggestions": self._generate_improvement_suggestions(area, recent_feedback)
            })
        
        return {
            "agent_id": agent_id,
            "current_level": assessment.current_level.value,
            "target_level": assessment.target_level.value,
            "overall_score": assessment.overall_score,
            "improvement_areas": improvement_areas,
            "estimated_time_to_promotion": self._estimate_promotion_time(assessment),
            "recommended_activities": self._recommend_activities(assessment, recent_feedback)
        }
    
    def _map_task_type_to_feedback(self, task_type: str) -> FeedbackType:
        """Map task type to feedback type."""
        mapping = {
            "failure_analysis": FeedbackType.COGNITIVE_QUALITY,
            "task_planning": FeedbackType.COGNITIVE_QUALITY,
            "decision_making": FeedbackType.DECISION_QUALITY,
            "problem_solving": FeedbackType.REASONING_ACCURACY,
            "memory_synthesis": FeedbackType.MEMORY_EFFICIENCY,
            "capability_assessment": FeedbackType.COGNITIVE_QUALITY
        }
        return mapping.get(task_type, FeedbackType.COGNITIVE_QUALITY)
    
    def _generate_feedback_reasoning(self, quality_scores: Dict[str, float], task_type: str) -> str:
        """Generate reasoning for feedback."""
        strengths = [k for k, v in quality_scores.items() if v >= 0.7]
        weaknesses = [k for k, v in quality_scores.items() if v < 0.5]
        
        reasoning = f"Task type: {task_type}. "
        
        if strengths:
            reasoning += f"Strengths: {', '.join(strengths)}. "
        
        if weaknesses:
            reasoning += f"Areas for improvement: {', '.join(weaknesses)}. "
        
        return reasoning
    
    def _update_agent_assessment(self, agent_id: str, feedback: CapabilityFeedback):
        """Update agent capability assessment with new feedback."""
        # Get or create assessment
        if agent_id not in self.agent_assessments:
            self.agent_assessments[agent_id] = CapabilityAssessment(
                agent_id=agent_id,
                current_level=CapabilityLevel.NOVICE,
                target_level=CapabilityLevel.APPRENTICE,
                overall_score=0.0,
                capability_scores={},
                improvement_areas=[],
                strengths=[],
                promotion_ready=False,
                last_assessment=time.time(),
                assessment_count=0
            )
        
        assessment = self.agent_assessments[agent_id]
        
        # Update capability scores
        feedback_type = feedback.feedback_type.value
        if feedback_type not in assessment.capability_scores:
            assessment.capability_scores[feedback_type] = []
        
        assessment.capability_scores[feedback_type].append(feedback.score)
        
        # Keep only recent scores (last 20)
        assessment.capability_scores[feedback_type] = assessment.capability_scores[feedback_type][-20:]
        
        # Calculate overall score
        all_scores = []
        for scores in assessment.capability_scores.values():
            all_scores.extend(scores)
        
        if all_scores:
            assessment.overall_score = statistics.mean(all_scores)
        
        # Update level
        assessment.current_level = self._calculate_level(assessment.overall_score)
        assessment.target_level = self._get_next_level(assessment.current_level) or assessment.current_level
        
        # Update strengths and improvement areas
        assessment.strengths = [
            capability for capability, scores in assessment.capability_scores.items()
            if statistics.mean(scores) >= 0.7
        ]
        
        assessment.improvement_areas = [
            capability for capability, scores in assessment.capability_scores.items()
            if statistics.mean(scores) < 0.5
        ]
        
        # Check promotion readiness
        assessment.promotion_ready = (
            assessment.overall_score >= 0.7 and
            len(assessment.strengths) >= 2 and
            len(assessment.improvement_areas) <= 1
        )
        
        assessment.last_assessment = time.time()
        assessment.assessment_count += 1
    
    def _calculate_level(self, score: float) -> CapabilityLevel:
        """Calculate capability level from score."""
        for level, threshold in sorted(self.capability_thresholds.items(), key=lambda x: x[1], reverse=True):
            if score >= threshold:
                return level
        return CapabilityLevel.NOVICE
    
    def _get_next_level(self, current_level: CapabilityLevel) -> Optional[CapabilityLevel]:
        """Get the next capability level."""
        levels = list(CapabilityLevel)
        try:
            current_index = levels.index(current_level)
            if current_index < len(levels) - 1:
                return levels[current_index + 1]
        except ValueError:
            pass
        return None
    
    def _generate_improvement_suggestions(self, area: str, feedback_history: List[CapabilityFeedback]) -> List[str]:
        """Generate improvement suggestions for a capability area."""
        suggestions = {
            "cognitive_quality": [
                "Practice more complex reasoning tasks",
                "Focus on clarity and completeness in responses",
                "Review and refine reasoning processes"
            ],
            "reasoning_accuracy": [
                "Improve logical consistency in analysis",
                "Enhance evidence evaluation skills",
                "Practice structured problem-solving approaches"
            ],
            "decision_quality": [
                "Expand option analysis capabilities",
                "Improve risk assessment methodologies",
                "Enhance outcome prediction accuracy"
            ],
            "memory_efficiency": [
                "Optimize memory synthesis processes",
                "Improve pattern recognition abilities",
                "Enhance information integration skills"
            ]
        }
        
        return suggestions.get(area, ["Focus on general improvement in this area"])
    
    def _estimate_promotion_time(self, assessment: CapabilityAssessment) -> str:
        """Estimate time to promotion."""
        if assessment.promotion_ready:
            return "Ready for promotion"
        
        score_gap = max(0.0, 0.7 - assessment.overall_score)
        if score_gap < 0.1:
            return "1-2 weeks"
        elif score_gap < 0.2:
            return "1-2 months"
        else:
            return "3-6 months"
    
    def _recommend_activities(self, assessment: CapabilityAssessment, feedback_history: List[CapabilityFeedback]) -> List[str]:
        """Recommend activities for improvement."""
        activities = []
        
        if assessment.improvement_areas:
            activities.append(f"Focus on improving {', '.join(assessment.improvement_areas)}")
        
        if assessment.overall_score < 0.5:
            activities.append("Practice basic cognitive tasks to build foundational skills")
        
        if len(assessment.strengths) < 2:
            activities.append("Develop expertise in specific capability areas")
        
        activities.append("Seek feedback from more experienced agents")
        activities.append("Review successful task executions for learning")
        
        return activities


# Global capability manager instance
_capability_manager: Optional[CapabilityManager] = None


def get_capability_manager() -> CapabilityManager:
    """Get the global capability manager instance."""
    global _capability_manager
    if _capability_manager is None:
        _capability_manager = CapabilityManager()
    return _capability_manager


def evaluate_cognitive_task(
    agent_id: str,
    task_type: str,
    output: Dict[str, Any],
    context: Dict[str, Any]
) -> CapabilityFeedback:
    """Evaluate a cognitive task output."""
    manager = get_capability_manager()
    return manager.evaluate_cognitive_task(agent_id, task_type, output, context)


def get_agent_assessment(agent_id: str) -> Optional[CapabilityAssessment]:
    """Get agent capability assessment."""
    manager = get_capability_manager()
    return manager.get_agent_assessment(agent_id)


def get_promotion_recommendations(min_score: float = 0.7) -> List[Tuple[str, CapabilityLevel]]:
    """Get promotion recommendations."""
    manager = get_capability_manager()
    return manager.get_promotion_recommendations(min_score)


def get_improvement_plan(agent_id: str) -> Dict[str, Any]:
    """Get improvement plan for an agent."""
    manager = get_capability_manager()
    return manager.get_improvement_plan(agent_id) 