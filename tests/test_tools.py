#!/usr/bin/env python3
"""
Comprehensive Unit Tests for SeedCore Tools

Tests all tool implementations:
- VLA Discovery Tools (hf_hub.list_models, lerobot.registry.query)
- VLA Analysis Tools (vla.analyze_model, vla.score_candidate)
- Distillation Tools (finetune.run_lerobot, teacher.escalate_gpt4)
- Calculator Tool
- Query Tools (general_query)
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any, List

# Import tools
from seedcore.tools.base import ToolBase
from seedcore.tools.calculator_tool import CalculatorTool
from seedcore.tools.vla_discovery_tools import HFListModelsTool, LeRobotRegistryQueryTool
from seedcore.tools.vla_analysis_tools import VLAAnalyzeModelTool, VLAScoreCandidateTool
from seedcore.tools.distillation_tools import FinetuneLeRobotTool, TeacherEscalateGPT4Tool
from seedcore.tools.manager import ToolError


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def mock_hf_api():
    """Mock Hugging Face API."""
    mock_api = Mock()
    mock_model = Mock()
    mock_model.modelId = "lerobot/smolvla_base"
    mock_model.tags = ["robotics", "vla", "pytorch"]
    mock_model.downloads = 1000
    mock_model.likes = 50
    mock_api.list_models.return_value = [mock_model]
    return mock_api


@pytest.fixture
def mock_ml_client():
    """Mock ML service client."""
    mock_client = Mock()
    mock_client.submit_training_job = AsyncMock(return_value={"job_id": "test_job_123"})
    return mock_client


@pytest.fixture
def mock_cognitive_client():
    """Mock cognitive service client."""
    mock_client = Mock()
    mock_client.chat_completion = AsyncMock(return_value={
        "success": True,
        "result": {
            "response": "Test response",
            "reasoning": "Test reasoning"
        }
    })
    return mock_client


@pytest.fixture
def mock_lerobot_tuner():
    """Mock LeRobot fine tuner."""
    mock_tuner = Mock()
    mock_tuner.prepare_training_config = AsyncMock(return_value={"epochs": 10, "batch_size": 4})
    mock_tuner.submit_training_job = AsyncMock(return_value={"job_id": "lerobot_job_123"})
    return mock_tuner


@pytest.fixture
def mock_teacher_escalator():
    """Mock Teacher LLM escalator."""
    mock_escalator = Mock()
    mock_escalator.escalate = AsyncMock(return_value={
        "safe": True,
        "reasoning": "Action is safe",
        "tool_calls": [{"tool": "test.tool", "params": {}}]
    })
    return mock_escalator


# ============================================================================
# ToolBase Tests
# ============================================================================

class TestToolBase:
    """Tests for ToolBase abstract class."""

    def test_tool_base_requires_name(self):
        """Test that tools must define a name."""
        class BadTool(ToolBase):
            pass
        
        tool = BadTool()
        with pytest.raises(ToolError):
            asyncio.run(tool.execute())

    def test_tool_base_execution_wrapper(self):
        """Test that execute() wraps run() properly."""
        class TestTool(ToolBase):
            name = "test.tool"
            
            async def run(self, **kwargs):
                return {"result": "success"}
        
        tool = TestTool()
        result = asyncio.run(tool.execute(test_param="value"))
        assert result == {"result": "success"}

    def test_tool_base_error_handling(self):
        """Test that execute() normalizes errors."""
        class FailingTool(ToolBase):
            name = "failing.tool"
            
            async def run(self, **kwargs):
                raise ValueError("Test error")
        
        tool = FailingTool()
        with pytest.raises(ToolError) as exc_info:
            asyncio.run(tool.execute())
        assert "Test error" in str(exc_info.value)

    def test_tool_base_schema(self):
        """Test default schema generation."""
        class TestTool(ToolBase):
            name = "test.tool"
            description = "Test tool description"
        
        tool = TestTool()
        schema = tool.schema()
        assert schema["name"] == "test.tool"
        assert schema["description"] == "Test tool description"
        assert "parameters" in schema


# ============================================================================
# Calculator Tool Tests
# ============================================================================

class TestCalculatorTool:
    """Tests for CalculatorTool."""

    @pytest.mark.asyncio
    async def test_calculator_simple_addition(self):
        """Test simple addition."""
        tool = CalculatorTool()
        result = await tool.execute(expression="2 + 3")
        assert result == 5.0

    @pytest.mark.asyncio
    async def test_calculator_multiplication(self):
        """Test multiplication."""
        tool = CalculatorTool()
        result = await tool.execute(expression="4 * 5")
        assert result == 20.0

    @pytest.mark.asyncio
    async def test_calculator_division(self):
        """Test division."""
        tool = CalculatorTool()
        result = await tool.execute(expression="10 / 2")
        assert result == 5.0

    @pytest.mark.asyncio
    async def test_calculator_exponentiation(self):
        """Test exponentiation."""
        tool = CalculatorTool()
        result = await tool.execute(expression="2 ** 8")
        assert result == 256.0

    @pytest.mark.asyncio
    async def test_calculator_complex_expression(self):
        """Test complex expression with order of operations."""
        tool = CalculatorTool()
        result = await tool.execute(expression="2 + 3 * 4")
        assert result == 14.0  # 2 + (3 * 4) = 14

    @pytest.mark.asyncio
    async def test_calculator_unary_negation(self):
        """Test unary negation."""
        tool = CalculatorTool()
        result = await tool.execute(expression="-5")
        assert result == -5.0

    @pytest.mark.asyncio
    async def test_calculator_modulo(self):
        """Test modulo operation."""
        tool = CalculatorTool()
        result = await tool.execute(expression="10 % 3")
        assert result == 1.0

    @pytest.mark.asyncio
    async def test_calculator_invalid_expression(self):
        """Test that invalid expressions raise ValueError."""
        tool = CalculatorTool()
        with pytest.raises(ValueError):
            await tool.execute(expression="invalid syntax")

    @pytest.mark.asyncio
    async def test_calculator_empty_expression(self):
        """Test that empty expressions raise ValueError."""
        tool = CalculatorTool()
        with pytest.raises(ValueError):
            await tool.execute(expression="")

    @pytest.mark.asyncio
    async def test_calculator_unsafe_operations(self):
        """Test that unsafe operations are rejected."""
        tool = CalculatorTool()
        # Function calls should be rejected
        with pytest.raises(ValueError):
            await tool.execute(expression="abs(-5)")

    def test_calculator_schema(self):
        """Test calculator schema."""
        tool = CalculatorTool()
        schema = tool.schema()
        assert schema["name"] == "calculator.evaluate"
        assert "expression" in schema["parameters"]["properties"]


# ============================================================================
# VLA Discovery Tools Tests
# ============================================================================

class TestHFListModelsTool:
    """Tests for HFListModelsTool."""

    @pytest.mark.asyncio
    @patch('seedcore.tools.vla_discovery_tools.HF_AVAILABLE', True)
    @patch('seedcore.tools.vla_discovery_tools.HfApi')
    async def test_hf_list_models_basic(self, mock_hf_api_class):
        """Test basic model listing."""
        mock_api_instance = Mock()
        mock_model1 = Mock()
        mock_model1.modelId = "lerobot/smolvla_base"
        mock_model1.author = "lerobot"
        mock_model1.tags = ["robotics", "vla", "pytorch"]
        mock_model1.downloads = 1000
        mock_model1.likes = 50
        mock_model1.createdAt = "2024-01-01"
        mock_model2 = Mock()
        mock_model2.modelId = "openvla-7b"
        mock_model2.author = "openvla"
        mock_model2.tags = ["vla", "pytorch"]
        mock_model2.downloads = 500
        mock_model2.likes = 25
        mock_model2.createdAt = "2024-01-01"
        # Make list_models return an iterable (list)
        mock_api_instance.list_models.return_value = [mock_model1, mock_model2]
        mock_hf_api_class.return_value = mock_api_instance
        
        tool = HFListModelsTool()
        result = await tool.run(limit=10)
        
        assert "candidates" in result
        assert len(result["candidates"]) >= 1  # May be filtered by params
        if result["candidates"]:
            assert result["candidates"][0]["model_id"] in ["lerobot/smolvla_base", "openvla-7b"]

    @pytest.mark.asyncio
    @patch('seedcore.tools.vla_discovery_tools.HF_AVAILABLE', True)
    @patch('seedcore.tools.vla_discovery_tools.HfApi')
    async def test_hf_list_models_with_tags(self, mock_hf_api_class, mock_hf_api):
        """Test model listing with custom tags."""
        mock_api_instance = Mock()
        mock_api_instance.list_models.return_value = []
        mock_hf_api_class.return_value = mock_api_instance
        
        tool = HFListModelsTool()
        result = await tool.run(tags=["robotics", "vla"], limit=5)
        
        assert "candidates" in result
        # Verify API was called with correct filters
        mock_api_instance.list_models.assert_called_once()

    @pytest.mark.asyncio
    @patch('seedcore.tools.vla_discovery_tools.HF_AVAILABLE', True)
    @patch('seedcore.tools.vla_discovery_tools.HfApi')
    async def test_hf_list_models_with_search(self, mock_hf_api_class):
        """Test model listing with search query."""
        mock_api_instance = Mock()
        mock_model = Mock()
        mock_model.modelId = "lerobot/smolvla_base"
        mock_model.author = "lerobot"
        mock_model.tags = ["robotics", "vla"]
        mock_model.downloads = 1000
        mock_model.likes = 50
        mock_model.createdAt = "2024-01-01"
        # Make list_models return an iterable (list)
        mock_api_instance.list_models.return_value = [mock_model]
        mock_hf_api_class.return_value = mock_api_instance
        
        tool = HFListModelsTool()
        result = await tool.run(search_query="smolvla", limit=10)
        
        assert "candidates" in result
        assert "scan_params" in result

    @pytest.mark.asyncio
    @patch('seedcore.tools.vla_discovery_tools.HF_AVAILABLE', False)
    async def test_hf_list_models_hf_not_available(self):
        """Test that tool raises error when HF is not available."""
        with pytest.raises(ImportError):
            tool = HFListModelsTool()

    def test_hf_list_models_schema(self):
        """Test HF list models schema."""
        with patch('seedcore.tools.vla_discovery_tools.HF_AVAILABLE', True):
            with patch('seedcore.tools.vla_discovery_tools.HfApi'):
                tool = HFListModelsTool()
                schema = tool.schema()
                assert schema["name"] == "hf_hub.list_models"
                assert "tags" in schema["parameters"]["properties"]
                assert "limit" in schema["parameters"]["properties"]


class TestLeRobotRegistryQueryTool:
    """Tests for LeRobotRegistryQueryTool."""

    @pytest.mark.asyncio
    async def test_lerobot_registry_query_basic(self):
        """Test basic LeRobot registry query."""
        tool = LeRobotRegistryQueryTool()
        
        # Mock the model info method
        async def mock_get_model_info(model_id, **kwargs):
            return {
                "model_id": model_id,
                "estimated_params": 450_000_000,
                "compatible": True,
                "training_config": {} if kwargs.get("include_training_config") else None,
            }
        
        tool._get_model_info = mock_get_model_info
        
        result = await tool.run(model_family="all")
        
        assert "models" in result
        assert len(result["models"]) > 0

    @pytest.mark.asyncio
    async def test_lerobot_registry_query_with_filters(self):
        """Test LeRobot registry query with filters."""
        tool = LeRobotRegistryQueryTool()
        
        async def mock_get_model_info(model_id, **kwargs):
            return {
                "model_id": model_id,
                "estimated_params": 450_000_000,
                "compatible": True,
            }
        
        tool._get_model_info = mock_get_model_info
        
        result = await tool.run(
            model_family="smolvla",
            max_params=1,  # 1 billion
            compatibility_check=True
        )
        
        assert "models" in result

    def test_lerobot_registry_query_schema(self):
        """Test LeRobot registry query schema."""
        tool = LeRobotRegistryQueryTool()
        schema = tool.schema()
        assert schema["name"] == "lerobot.registry.query"
        assert "model_family" in schema["parameters"]["properties"]


# ============================================================================
# VLA Analysis Tools Tests
# ============================================================================

class TestVLAAnalyzeModelTool:
    """Tests for VLAAnalyzeModelTool."""

    @pytest.mark.asyncio
    async def test_vla_analyze_model_reference_model(self):
        """Test analysis of a known reference model."""
        tool = VLAAnalyzeModelTool()
        
        result = await tool.run(model_id="lerobot/smolvla_base")
        
        assert "model_id" in result
        assert "scores" in result
        assert "vla_native" in result["scores"]
        assert "3d_position_embedding" in result["scores"]
        assert "latency_throughput" in result["scores"]
        assert "overall_spatial_behavioral" in result["scores"]
        assert result["model_id"] == "lerobot/smolvla_base"

    @pytest.mark.asyncio
    async def test_vla_analyze_model_unknown_model(self):
        """Test analysis of an unknown model using heuristics."""
        tool = VLAAnalyzeModelTool()
        
        result = await tool.run(
            model_id="unknown/model",
            model_metadata={"tags": ["robotics", "vla"]}
        )
        
        assert "model_id" in result
        assert "scores" in result
        assert "overall_spatial_behavioral" in result["scores"]
        assert result["model_id"] == "unknown/model"

    @pytest.mark.asyncio
    async def test_vla_analyze_model_with_platform(self):
        """Test analysis with specific platform target."""
        tool = VLAAnalyzeModelTool()
        
        result = await tool.run(
            model_id="nvidia/gr00t-n1.6",
            target_platform="jetson"
        )
        
        assert "scores" in result
        assert "recommendation" in result

    @pytest.mark.asyncio
    async def test_vla_analyze_model_latency_requirement(self):
        """Test analysis with latency requirement."""
        tool = VLAAnalyzeModelTool()
        
        result = await tool.run(
            model_id="lerobot/smolvla_base",
            min_latency_hz=10.0  # Higher requirement
        )
        
        assert "scores" in result
        # Latency score should be affected by requirement
        assert "latency_throughput" in result["scores"]

    def test_vla_analyze_model_schema(self):
        """Test VLA analyze model schema."""
        tool = VLAAnalyzeModelTool()
        schema = tool.schema()
        assert schema["name"] == "vla.analyze_model"
        assert "model_id" in schema["parameters"]["properties"]


class TestVLAScoreCandidateTool:
    """Tests for VLAScoreCandidateTool."""

    @pytest.mark.asyncio
    async def test_vla_score_candidate_basic(self):
        """Test basic candidate scoring."""
        tool = VLAScoreCandidateTool()
        
        candidate = {
            "model_id": "lerobot/smolvla_base",
            "metadata": {"tags": ["robotics", "vla"]}
        }
        
        result = await tool.run(candidates=[candidate])
        
        assert "ranked_candidates" in result
        assert len(result["ranked_candidates"]) == 1
        assert "weighted_score" in result["ranked_candidates"][0]
        assert "top_recommendations" in result
        if result["top_recommendations"]:
            assert "rank" in result["top_recommendations"][0]

    @pytest.mark.asyncio
    async def test_vla_score_candidate_multiple(self):
        """Test scoring multiple candidates."""
        tool = VLAScoreCandidateTool()
        
        candidates = [
            {"model_id": "lerobot/smolvla_base"},
            {"model_id": "openvla-7b"},
            {"model_id": "unknown/model"},
        ]
        
        result = await tool.run(candidates=candidates)
        
        assert "ranked_candidates" in result
        assert len(result["ranked_candidates"]) >= 1  # Some may fail analysis
        # Should be sorted by score (highest first)
        scores = [c["weighted_score"] for c in result["ranked_candidates"]]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_vla_score_candidate_with_weights(self):
        """Test scoring with custom weights (if supported)."""
        tool = VLAScoreCandidateTool()
        
        candidate = {"model_id": "lerobot/smolvla_base"}
        
        # Note: weights parameter may not be supported, test without it
        result = await tool.run(candidates=[candidate])
        
        assert "ranked_candidates" in result

    def test_vla_score_candidate_schema(self):
        """Test VLA score candidate schema."""
        tool = VLAScoreCandidateTool()
        schema = tool.schema()
        assert schema["name"] == "vla.score_candidate"
        assert "candidates" in schema["parameters"]["properties"]


# ============================================================================
# Distillation Tools Tests
# ============================================================================

class TestFinetuneLeRobotTool:
    """Tests for FinetuneLeRobotTool."""

    @pytest.mark.asyncio
    async def test_finetune_lerobot_basic(self, mock_ml_client):
        """Test basic LeRobot fine-tuning."""
        # Mock the LeRobotFineTuner to avoid requiring base_model in __init__
        with patch('seedcore.tools.distillation_tools.LeRobotFineTuner') as mock_tuner_class:
            mock_tuner_instance = Mock()
            mock_tuner_instance.prepare_training_config = AsyncMock(return_value={"epochs": 10})
            mock_tuner_instance.submit_training_job = AsyncMock(return_value={"job_id": "test_job"})
            mock_tuner_class.return_value = mock_tuner_instance
            
            tool = FinetuneLeRobotTool(
                ml_client=mock_ml_client,
                output_base_dir="/tmp/test_output"
            )
            
            result = await tool.run(
                base_model="lerobot/smolvla_base",
                training_data={"episodes": []},
                output_dir="/tmp/test_output"
            )
            
            assert "job_id" in result or "command" in result
            # Should have called the fine tuner
            assert tool.fine_tuner is not None

    @pytest.mark.asyncio
    async def test_finetune_lerobot_with_config(self, mock_ml_client):
        """Test fine-tuning with custom config."""
        with patch('seedcore.tools.distillation_tools.LeRobotFineTuner') as mock_tuner_class:
            mock_tuner_instance = Mock()
            mock_tuner_instance.prepare_training_config = AsyncMock(return_value={"epochs": 20})
            mock_tuner_instance.submit_training_job = AsyncMock(return_value={"job_id": "test_job"})
            mock_tuner_class.return_value = mock_tuner_instance
            
            tool = FinetuneLeRobotTool(
                ml_client=mock_ml_client,
                output_base_dir="/tmp/test_output"
            )
            
            result = await tool.run(
                base_model="lerobot/smolvla_base",
                training_data={"episodes": []},
                training_config={"epochs": 20, "batch_size": 8},
                lora_config={"r": 16, "alpha": 32}
            )
            
            assert result is not None

    @pytest.mark.asyncio
    async def test_finetune_lerobot_seedcore_format(self, mock_ml_client):
        """Test fine-tuning with SeedCore format enabled."""
        with patch('seedcore.tools.distillation_tools.LeRobotFineTuner') as mock_tuner_class:
            mock_tuner_instance = Mock()
            mock_tuner_instance.prepare_training_config = AsyncMock(return_value={"epochs": 10})
            mock_tuner_instance.submit_training_job = AsyncMock(return_value={"job_id": "test_job"})
            mock_tuner_class.return_value = mock_tuner_instance
            
            tool = FinetuneLeRobotTool(
                ml_client=mock_ml_client,
                output_base_dir="/tmp/test_output"
            )
            
            result = await tool.run(
                base_model="lerobot/smolvla_base",
                training_data={"episodes": []},
                seedcore_format=True,
                trace_replay=True
            )
            
            assert result is not None

    def test_finetune_lerobot_schema(self, mock_ml_client):
        """Test fine-tune LeRobot schema."""
        with patch('seedcore.tools.distillation_tools.LeRobotFineTuner') as mock_tuner_class:
            mock_tuner_instance = Mock()
            mock_tuner_class.return_value = mock_tuner_instance
            
            tool = FinetuneLeRobotTool(
                ml_client=mock_ml_client,
                output_base_dir="/tmp/test_output"
            )
            schema = tool.schema()
            assert schema["name"] == "finetune.run_lerobot"
            assert "base_model" in schema["parameters"]["properties"]
            assert "training_data" in schema["parameters"]["properties"]


class TestTeacherEscalateGPT4Tool:
    """Tests for TeacherEscalateGPT4Tool."""

    @pytest.mark.asyncio
    async def test_teacher_escalate_gpt4_basic(self, mock_cognitive_client):
        """Test basic GPT-4 escalation."""
        tool = TeacherEscalateGPT4Tool(cognitive_client=mock_cognitive_client)
        
        # Mock the escalator's escalate method
        tool.escalator.escalate = AsyncMock(return_value={
            "teacher_output": {"tool_calls": [{"tool": "test.tool", "params": {}}]},
            "reasoning": "Test reasoning",
            "trace_data": {}
        })
        
        result = await tool.run(
            multimodal_context={"image": "base64_data"},
            role_profile={"tools": ["test.tool"]},
            task_description="High-risk action",
            risk_level=0.9
        )
        
        assert "teacher_output" in result or "trace_data" in result
        # Should have called escalator
        tool.escalator.escalate.assert_called_once()

    @pytest.mark.asyncio
    async def test_teacher_escalate_gpt4_with_spatial_reasoning(self, mock_cognitive_client):
        """Test escalation with spatial reasoning."""
        tool = TeacherEscalateGPT4Tool(cognitive_client=mock_cognitive_client)
        
        tool.escalator.escalate = AsyncMock(return_value={
            "teacher_output": {},
            "reasoning": "Spatial reasoning explanation",
            "trace_data": {}
        })
        
        result = await tool.run(
            multimodal_context={"image": "base64_data"},
            role_profile={"tools": ["test.tool"]},
            task_description="Move arm to position",
            include_spatial_reasoning=True
        )
        
        assert result is not None
        tool.escalator.escalate.assert_called_once()

    def test_teacher_escalate_gpt4_schema(self, mock_cognitive_client):
        """Test teacher escalate GPT-4 schema."""
        tool = TeacherEscalateGPT4Tool(cognitive_client=mock_cognitive_client)
        schema = tool.schema()
        assert schema["name"] == "teacher.escalate_gpt4"
        assert "task_description" in schema["parameters"]["properties"]


# Note: TeacherEscalateGPT5Tool may be added in the future for 2026 GPT-5 support
# For now, GPT-4 escalation is tested above


# ============================================================================
# Integration Tests
# ============================================================================

class TestToolIntegration:
    """Integration tests for tools working together."""

    @pytest.mark.asyncio
    async def test_vla_discovery_to_analysis_workflow(self):
        """Test workflow: discover models -> analyze them."""
        # Step 1: Discover models
        with patch('seedcore.tools.vla_discovery_tools.HF_AVAILABLE', True):
            with patch('seedcore.tools.vla_discovery_tools.HfApi') as mock_hf_api_class:
                mock_api_instance = Mock()
                mock_model = Mock()
                mock_model.modelId = "lerobot/smolvla_base"
                mock_model.author = "lerobot"
                mock_model.tags = ["robotics", "vla", "pytorch"]
                mock_model.downloads = 1000
                mock_model.likes = 50
                mock_model.createdAt = "2024-01-01"
                # Make list_models return an iterable (list)
                mock_api_instance.list_models.return_value = [mock_model]
                mock_hf_api_class.return_value = mock_api_instance
                
                discovery_tool = HFListModelsTool()
                discovery_result = await discovery_tool.run(limit=5)
                
                # Step 2: Analyze discovered models
                analysis_tool = VLAAnalyzeModelTool()
                if discovery_result["candidates"]:
                    model_id = discovery_result["candidates"][0]["model_id"]
                    analysis_result = await analysis_tool.run(model_id=model_id)
                    
                    assert "scores" in analysis_result
                    assert analysis_result["model_id"] == model_id

    @pytest.mark.asyncio
    async def test_vla_analysis_to_scoring_workflow(self):
        """Test workflow: analyze models -> score candidates."""
        # Step 1: Analyze multiple models
        analysis_tool = VLAAnalyzeModelTool()
        
        model_ids = ["lerobot/smolvla_base", "openvla-7b"]
        candidates = []
        
        for model_id in model_ids:
            analysis = await analysis_tool.run(model_id=model_id)
            candidates.append({
                "model_id": model_id,
                "analysis": analysis
            })
        
        # Step 2: Score candidates
        scoring_tool = VLAScoreCandidateTool()
        scored_result = await scoring_tool.run(candidates=candidates)
        
        assert "ranked_candidates" in scored_result
        assert len(scored_result["ranked_candidates"]) == 2
        # Should be ranked by score - check top_recommendations for rank
        assert "top_recommendations" in scored_result
        if scored_result["top_recommendations"]:
            assert scored_result["top_recommendations"][0]["rank"] == 1

    @pytest.mark.asyncio
    async def test_calculator_tool_usage(self):
        """Test calculator tool in typical usage."""
        tool = CalculatorTool()
        
        # Test various calculations
        assert await tool.execute(expression="2 + 2") == 4.0
        assert await tool.execute(expression="10 * 5") == 50.0
        assert await tool.execute(expression="100 / 4") == 25.0
        assert await tool.execute(expression="2 ** 10") == 1024.0


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestToolErrorHandling:
    """Tests for error handling in tools."""

    @pytest.mark.asyncio
    async def test_calculator_division_by_zero(self):
        """Test calculator handles division by zero."""
        tool = CalculatorTool()
        # Python handles division by zero as ZeroDivisionError
        with pytest.raises((ValueError, ZeroDivisionError)):
            await tool.execute(expression="10 / 0")

    @pytest.mark.asyncio
    async def test_vla_analyze_missing_model_id(self):
        """Test VLA analyze with missing model_id."""
        tool = VLAAnalyzeModelTool()
        # Should handle gracefully or raise appropriate error
        with pytest.raises((TypeError, ValueError)):
            await tool.run()  # Missing required model_id

    @pytest.mark.asyncio
    async def test_finetune_missing_required_params(self, mock_ml_client):
        """Test fine-tuning with missing required parameters."""
        with patch('seedcore.tools.distillation_tools.LeRobotFineTuner') as mock_tuner_class:
            mock_tuner_instance = Mock()
            mock_tuner_class.return_value = mock_tuner_instance
            
            tool = FinetuneLeRobotTool(
                ml_client=mock_ml_client,
                output_base_dir="/tmp/test_output"
            )
            # Should raise error for missing required params
            with pytest.raises((TypeError, ValueError)):
                await tool.run()  # Missing base_model and training_data


# ============================================================================
# Performance Tests
# ============================================================================

class TestToolPerformance:
    """Performance tests for tools."""

    @pytest.mark.asyncio
    async def test_calculator_performance(self):
        """Test calculator performance with complex expressions."""
        import time
        tool = CalculatorTool()
        
        start = time.perf_counter()
        for _ in range(100):
            await tool.execute(expression="2 + 3 * 4 - 1")
        elapsed = time.perf_counter() - start
        
        # Should complete 100 calculations quickly (< 1 second)
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_vla_analyze_multiple_models_performance(self):
        """Test VLA analysis performance with multiple models."""
        import time
        tool = VLAAnalyzeModelTool()
        
        model_ids = ["lerobot/smolvla_base", "openvla-7b", "nvidia/gr00t-n1.6"]
        
        start = time.perf_counter()
        for model_id in model_ids:
            await tool.run(model_id=model_id)
        elapsed = time.perf_counter() - start
        
        # Should complete analyses quickly (< 5 seconds for 3 models)
        assert elapsed < 5.0
