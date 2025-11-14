"""
Unit tests for coordinator.models module.

Tests Pydantic models for coordinator API requests and responses.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import pytest
from seedcore.coordinator.models import (
    AnomalyTriageRequest,
    AnomalyTriageResponse,
    TuneCallbackRequest,
)


class TestAnomalyTriageRequest:
    """Tests for AnomalyTriageRequest model."""
    
    def test_create_minimal_request(self):
        """Test creating minimal request with required fields."""
        request = AnomalyTriageRequest(agent_id="agent-123")
        assert request.agent_id == "agent-123"
        assert request.series == []
        assert request.context == {}
    
    def test_create_with_series(self):
        """Test creating request with series data."""
        request = AnomalyTriageRequest(
            agent_id="agent-123",
            series=[1.0, 2.0, 3.0, 4.0, 5.0]
        )
        assert request.agent_id == "agent-123"
        assert len(request.series) == 5
        assert request.series == [1.0, 2.0, 3.0, 4.0, 5.0]
    
    def test_create_with_context(self):
        """Test creating request with context."""
        context = {"timestamp": 1234567890, "source": "test"}
        request = AnomalyTriageRequest(
            agent_id="agent-123",
            context=context
        )
        assert request.context == context
    
    def test_missing_agent_id_raises_error(self):
        """Test that missing agent_id raises validation error."""
        with pytest.raises(Exception):  # Pydantic validation error
            AnomalyTriageRequest()


class TestAnomalyTriageResponse:
    """Tests for AnomalyTriageResponse model."""
    
    def test_create_minimal_response(self):
        """Test creating minimal response."""
        response = AnomalyTriageResponse(
            agent_id="agent-123",
            anomalies={},
            reason={},
            decision={},
            correlation_id="cid-123",
            p_fast=0.5,
            escalated=False
        )
        assert response.agent_id == "agent-123"
        assert response.correlation_id == "cid-123"
        assert response.p_fast == 0.5
        assert response.escalated is False
        assert response.tuning_job is None
    
    def test_create_with_tuning_job(self):
        """Test creating response with tuning job."""
        tuning_job = {"job_id": "job-123", "status": "started"}
        response = AnomalyTriageResponse(
            agent_id="agent-123",
            anomalies={},
            reason={},
            decision={},
            correlation_id="cid-123",
            p_fast=0.5,
            escalated=True,
            tuning_job=tuning_job
        )
        assert response.tuning_job == tuning_job
    
    def test_create_with_anomalies(self):
        """Test creating response with anomalies."""
        anomalies = {
            "anomalies": [
                {"timestamp": 1, "value": 10.0},
                {"timestamp": 2, "value": 20.0}
            ]
        }
        response = AnomalyTriageResponse(
            agent_id="agent-123",
            anomalies=anomalies,
            reason={},
            decision={},
            correlation_id="cid-123",
            p_fast=0.3,
            escalated=True
        )
        assert len(response.anomalies["anomalies"]) == 2
    
    def test_create_with_decision(self):
        """Test creating response with decision."""
        decision = {"result": {"action": "escalate", "reason": "high_drift"}}
        response = AnomalyTriageResponse(
            agent_id="agent-123",
            anomalies={},
            reason={},
            decision=decision,
            correlation_id="cid-123",
            p_fast=0.2,
            escalated=True
        )
        assert response.decision == decision


class TestTuneCallbackRequest:
    """Tests for TuneCallbackRequest model."""
    
    def test_create_minimal_callback(self):
        """Test creating minimal callback."""
        callback = TuneCallbackRequest(job_id="job-123")
        assert callback.job_id == "job-123"
        assert callback.status == "completed"
        assert callback.E_before is None
        assert callback.E_after is None
        assert callback.gpu_seconds is None
        assert callback.error is None
    
    def test_create_completed_callback(self):
        """Test creating completed callback with energy values."""
        callback = TuneCallbackRequest(
            job_id="job-123",
            status="completed",
            E_before=100.0,
            E_after=95.0,
            gpu_seconds=120.5
        )
        assert callback.job_id == "job-123"
        assert callback.status == "completed"
        assert callback.E_before == 100.0
        assert callback.E_after == 95.0
        assert callback.gpu_seconds == 120.5
    
    def test_create_failed_callback(self):
        """Test creating failed callback with error."""
        callback = TuneCallbackRequest(
            job_id="job-123",
            status="failed",
            error="Out of memory"
        )
        assert callback.job_id == "job-123"
        assert callback.status == "failed"
        assert callback.error == "Out of memory"
    
    def test_missing_job_id_raises_error(self):
        """Test that missing job_id raises validation error."""
        with pytest.raises(Exception):  # Pydantic validation error
            TuneCallbackRequest()
    
    def test_callback_with_delta_e(self):
        """Test callback allows computing delta E."""
        callback = TuneCallbackRequest(
            job_id="job-123",
            E_before=100.0,
            E_after=95.0
        )
        # Delta E should be negative (energy decreased)
        delta_e = callback.E_after - callback.E_before
        assert delta_e == -5.0

