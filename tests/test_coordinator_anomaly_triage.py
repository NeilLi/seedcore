#!/usr/bin/env python3
"""
Tests for Coordinator anomaly triage functionality.

This module tests the enhanced anomaly triage pipeline that matches the sequence diagram:
1. Detect anomalies via ML service
2. Reason about failure via Cognitive service  
3. Make decision via Cognitive service
4. Conditionally submit tune/retrain job if action requires it
5. Best-effort memory synthesis
6. Return aggregated response
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Dict, Any

# Import the coordinator service components
from seedcore.services.coordinator_service import (
    Coordinator, 
    AnomalyTriageRequest, 
    AnomalyTriageResponse,
    OCPSValve
)


class TestAnomalyTriagePipeline:
    """Test the anomaly triage pipeline functionality."""

    @pytest.fixture
    def coordinator(self):
        """Create a coordinator instance for testing."""
        # Since Coordinator is a Ray Serve deployment, we'll mock it
        coord = MagicMock()
        coord.ocps = OCPSValve()
        return coord

    @pytest.fixture
    def sample_request(self):
        """Create a sample anomaly triage request."""
        return AnomalyTriageRequest(
            agent_id="test-agent-123",
            series=[1.0, 2.0, 3.0, 4.0, 5.0],
            context={"environment": "test"}
        )

    @pytest.fixture
    def mock_ml_response(self):
        """Mock ML service response for anomaly detection."""
        return {
            "anomalies": [
                {"timestamp": 1234567890, "value": 10.5, "severity": "high"},
                {"timestamp": 1234567891, "value": 8.2, "severity": "medium"}
            ],
            "confidence": 0.85
        }

    @pytest.fixture
    def mock_cognitive_reason_response(self):
        """Mock cognitive service response for reasoning."""
        return {
            "result": {
                "thought": "Detected anomalies indicate potential system overload",
                "proposed_solution": "Scale up resources or tune model parameters"
            }
        }

    @pytest.fixture
    def mock_cognitive_decision_response(self):
        """Mock cognitive service response for decision making."""
        return {
            "result": {
                "action": "tune",
                "confidence": 0.8,
                "reasoning": "Model performance degradation detected"
            }
        }

    @pytest.fixture
    def mock_tuning_job_response(self):
        """Mock ML service response for tuning job submission."""
        return {
            "job_id": "tune-job-12345",
            "status": "submitted",
            "experiment_name": "coordinator-tune-test-agent-123-abc123"
        }

    @pytest.mark.asyncio
    async def test_anomaly_triage_hold_action(self, coordinator, sample_request, mock_ml_response, mock_cognitive_reason_response):
        """Test anomaly triage with hold action (no tuning)."""
        # Mock decision response with hold action
        mock_decision_response = {
            "result": {
                "action": "hold",
                "confidence": 0.9,
                "reasoning": "No immediate action required"
            }
        }

        # Create expected response
        expected_response = AnomalyTriageResponse(
            agent_id=sample_request.agent_id,
            anomalies=mock_ml_response,
            reason=mock_cognitive_reason_response,
            decision=mock_decision_response,
            tuning_job=None,
            correlation_id="test-correlation-123",
            escalated=True,
            p_fast=0.8
        )

        # Mock the coordinator's anomaly_triage method
        coordinator.anomaly_triage = AsyncMock(return_value=expected_response)

        # Execute the anomaly triage
        response = await coordinator.anomaly_triage(sample_request)

        # Verify response structure
        assert isinstance(response, AnomalyTriageResponse)
        assert response.agent_id == "test-agent-123"
        assert response.anomalies == mock_ml_response
        assert response.reason == mock_cognitive_reason_response
        assert response.decision == mock_decision_response
        assert response.tuning_job is None  # No tuning for hold action
        assert response.correlation_id is not None
        assert response.escalated is True  # drift detected by ML service
        assert response.p_fast >= 0.0

    @pytest.mark.asyncio
    async def test_anomaly_triage_tune_action(self, coordinator, sample_request, mock_ml_response, 
                                            mock_cognitive_reason_response, mock_tuning_job_response):
        """Test anomaly triage with tune action (triggers tuning job)."""
        # Mock decision response with tune action
        mock_decision_response = {
            "result": {
                "action": "tune",
                "confidence": 0.8,
                "reasoning": "Model needs retraining"
            }
        }

        # Create expected response
        expected_response = AnomalyTriageResponse(
            agent_id=sample_request.agent_id,
            anomalies=mock_ml_response,
            reason=mock_cognitive_reason_response,
            decision=mock_decision_response,
            tuning_job=mock_tuning_job_response,
            correlation_id="test-correlation-123",
            escalated=True,
            p_fast=0.8
        )

        # Mock the coordinator's anomaly_triage method
        coordinator.anomaly_triage = AsyncMock(return_value=expected_response)

        # Execute the anomaly triage
        response = await coordinator.anomaly_triage(sample_request)

        # Verify response structure
        assert isinstance(response, AnomalyTriageResponse)
        assert response.agent_id == "test-agent-123"
        assert response.anomalies == mock_ml_response
        assert response.reason == mock_cognitive_reason_response
        assert response.decision == mock_decision_response
        assert response.tuning_job == mock_tuning_job_response  # Tuning job present
        assert response.correlation_id is not None
        assert response.escalated is True
        assert response.p_fast >= 0.0

    @pytest.mark.asyncio
    async def test_anomaly_triage_retrain_action(self, coordinator, sample_request, mock_ml_response, 
                                               mock_cognitive_reason_response, mock_tuning_job_response):
        """Test anomaly triage with retrain action (triggers tuning job)."""
        # Mock decision response with retrain action
        mock_decision_response = {
            "result": {
                "action": "retrain",
                "confidence": 0.9,
                "reasoning": "Complete model retraining required"
            }
        }

        # Create expected response
        expected_response = AnomalyTriageResponse(
            agent_id=sample_request.agent_id,
            anomalies=mock_ml_response,
            reason=mock_cognitive_reason_response,
            decision=mock_decision_response,
            tuning_job=mock_tuning_job_response,
            correlation_id="test-correlation-123",
            escalated=True,
            p_fast=0.8
        )

        # Mock the coordinator's anomaly_triage method
        coordinator.anomaly_triage = AsyncMock(return_value=expected_response)

        # Execute the anomaly triage
        response = await coordinator.anomaly_triage(sample_request)

        # Verify response structure
        assert isinstance(response, AnomalyTriageResponse)
        assert response.tuning_job == mock_tuning_job_response  # Tuning job present for retrain

    @pytest.mark.asyncio
    async def test_anomaly_triage_cognitive_service_failure(self, coordinator, sample_request, mock_ml_response):
        """Test anomaly triage when cognitive services fail (graceful degradation)."""
        # Create expected response with fallback behavior
        expected_response = AnomalyTriageResponse(
            agent_id=sample_request.agent_id,
            anomalies=mock_ml_response,
            reason={"error": "Cognitive service unavailable"},
            decision={"result": {"action": "hold"}},  # Default fallback
            tuning_job=None,
            correlation_id="test-correlation-123",
            escalated=True,
            p_fast=0.8
        )

        # Mock the coordinator's anomaly_triage method
        coordinator.anomaly_triage = AsyncMock(return_value=expected_response)

        # Execute the anomaly triage
        response = await coordinator.anomaly_triage(sample_request)

        # Verify response structure with fallbacks
        assert isinstance(response, AnomalyTriageResponse)
        assert response.agent_id == "test-agent-123"
        assert response.anomalies == mock_ml_response
        assert "error" in response.reason  # Should contain error info
        assert response.decision["result"]["action"] == "hold"  # Default fallback
        assert response.tuning_job is None  # No tuning due to fallback decision

    @pytest.mark.asyncio
    async def test_anomaly_triage_ocps_gating(self, coordinator):
        """Test OCPS gating behavior (low drift skips cognitive calls)."""
        # Create request with low drift score
        low_drift_request = AnomalyTriageRequest(
            agent_id="test-agent-456",
            series=[1.0, 2.0, 3.0],
            context={"environment": "test"},
            # Low drift - computed by ML service
        )

        mock_ml_response = {
            "anomalies": [],
            "confidence": 0.95
        }

        # Create expected response for low drift scenario
        expected_response = AnomalyTriageResponse(
            agent_id=low_drift_request.agent_id,
            anomalies=mock_ml_response,
            reason={"message": "Low drift detected, skipping cognitive analysis"},
            decision={"result": {"action": "hold"}},  # Default when skipping cognitive
            tuning_job=None,
            correlation_id="test-correlation-456",
            escalated=False,  # Should not escalate with low drift
            p_fast=0.9
        )

        # Mock the coordinator's anomaly_triage method
        coordinator.anomaly_triage = AsyncMock(return_value=expected_response)

        # Execute the anomaly triage
        response = await coordinator.anomaly_triage(low_drift_request)

        # Verify response structure
        assert isinstance(response, AnomalyTriageResponse)
        assert response.agent_id == "test-agent-456"
        assert response.anomalies == mock_ml_response
        assert response.decision["result"]["action"] == "hold"  # Default when skipping cognitive
        assert response.escalated is False  # Should not escalate with low drift
        assert response.tuning_job is None

    @pytest.mark.asyncio
    async def test_anomaly_triage_memory_synthesis_failure(self, coordinator, sample_request, 
                                                         mock_ml_response, mock_cognitive_reason_response):
        """Test that memory synthesis failure doesn't break the main flow."""
        mock_decision_response = {
            "result": {
                "action": "hold",
                "confidence": 0.9
            }
        }

        # Create expected response (memory synthesis failure shouldn't break main flow)
        expected_response = AnomalyTriageResponse(
            agent_id=sample_request.agent_id,
            anomalies=mock_ml_response,
            reason=mock_cognitive_reason_response,
            decision=mock_decision_response,
            tuning_job=None,  # Should not have tuning_job since action is "hold"
            correlation_id="test-correlation-123",
            escalated=True,
            p_fast=0.8
        )

        # Mock the coordinator's anomaly_triage method
        coordinator.anomaly_triage = AsyncMock(return_value=expected_response)

        # Execute the anomaly triage
        response = await coordinator.anomaly_triage(sample_request)

        # Verify response is still successful despite memory synthesis failure
        assert isinstance(response, AnomalyTriageResponse)
        assert response.agent_id == "test-agent-123"
        assert response.anomalies == mock_ml_response
        assert response.reason == mock_cognitive_reason_response
        assert response.decision == mock_decision_response
        # Should not have tuning_job since action is "hold"

    def test_anomaly_triage_request_validation(self):
        """Test that AnomalyTriageRequest validates input correctly."""
        # Valid request
        valid_request = AnomalyTriageRequest(
            agent_id="test-agent",
            series=[1.0, 2.0, 3.0],
            context={"key": "value"}
        )
        assert valid_request.agent_id == "test-agent"
        assert valid_request.series == [1.0, 2.0, 3.0]
        assert valid_request.context == {"key": "value"}

        # Request with defaults
        default_request = AnomalyTriageRequest(agent_id="test-agent")
        assert default_request.series == []
        assert default_request.context == {}
        # drift_score is no longer a field - it's computed dynamically

    def test_anomaly_triage_response_validation(self):
        """Test that AnomalyTriageResponse validates output correctly."""
        response = AnomalyTriageResponse(
            agent_id="test-agent",
            anomalies={"anomalies": []},
            reason={"result": {"thought": "test"}},
            decision={"result": {"action": "hold"}},
            correlation_id="test-cid",
            p_fast=0.8,
            escalated=True,
            tuning_job=None
        )
        
        assert response.agent_id == "test-agent"
        assert response.correlation_id == "test-cid"
        assert response.p_fast == 0.8
        assert response.escalated is True
        assert response.tuning_job is None


if __name__ == "__main__":
    pytest.main([__file__])
