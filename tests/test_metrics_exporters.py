#!/usr/bin/env python3
"""
Unit tests for metrics exporters.

Tests all exporter implementations including health checks.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from seedcore.ops.metrics.exporters import (
    MetricsExporter,
    NoOpExporter,
    LoggingExporter,
    PrometheusExporter,
    OpenTelemetryExporter,
    RedisExporter,
)


class TestNoOpExporter:
    """Tests for NoOpExporter."""
    
    def test_export(self):
        """Test NoOpExporter export (no-op)."""
        exporter = NoOpExporter()
        result = exporter.export({"test": "metrics"})
        assert result is True
    
    def test_flush(self):
        """Test NoOpExporter flush (no-op)."""
        exporter = NoOpExporter()
        result = exporter.flush()
        assert result is True
    
    def test_get_health(self):
        """Test NoOpExporter health status."""
        exporter = NoOpExporter()
        health = exporter.get_health()
        
        assert health["type"] == "NoOpExporter"
        assert health["available"] is True
        assert health["healthy"] is True


class TestLoggingExporter:
    """Tests for LoggingExporter."""
    
    def test_export(self):
        """Test LoggingExporter export."""
        exporter = LoggingExporter()
        metrics = {"total_tasks": 100, "success_rate": 0.95}
        
        with patch('seedcore.ops.metrics.exporters.logger') as mock_logger:
            result = exporter.export(metrics)
            assert result is True
            mock_logger.log.assert_called_once()
    
    def test_export_with_exception(self):
        """Test LoggingExporter handles exceptions."""
        exporter = LoggingExporter()
        
        with patch('seedcore.ops.metrics.exporters.logger.log', side_effect=Exception("Test error")):
            result = exporter.export({"test": "metrics"})
            assert result is False
    
    def test_flush(self):
        """Test LoggingExporter flush."""
        exporter = LoggingExporter()
        result = exporter.flush()
        assert result is True
    
    def test_get_health(self):
        """Test LoggingExporter health status."""
        exporter = LoggingExporter()
        health = exporter.get_health()
        
        assert health["type"] == "LoggingExporter"
        assert health["available"] is True
        assert health["healthy"] is True


class TestPrometheusExporter:
    """Tests for PrometheusExporter."""
    
    def test_init_without_prometheus(self):
        """Test PrometheusExporter initialization without prometheus_client."""
        exporter = PrometheusExporter()
        assert exporter._prometheus_available is False
    
    @patch('seedcore.ops.metrics.exporters.logger')
    def test_init_without_prometheus_logs_warning(self, mock_logger):
        """Test that missing prometheus_client logs a warning."""
        PrometheusExporter()
        mock_logger.warning.assert_called()
    
    @patch('builtins.__import__', side_effect=ImportError("No module named 'prometheus_client'"))
    def test_init_import_error(self, mock_import):
        """Test initialization handles import error."""
        exporter = PrometheusExporter()
        assert exporter._prometheus_available is False
    
    def test_export_without_prometheus(self):
        """Test export when prometheus_client is not available."""
        exporter = PrometheusExporter()
        result = exporter.export({"test": "metrics"})
        assert result is False
    
    def test_export_with_prometheus(self):
        """Test export when prometheus_client is available."""
        exporter = PrometheusExporter()
        exporter._prometheus_available = True
        
        with patch('seedcore.ops.metrics.exporters.logger') as mock_logger:
            result = exporter.export({"test": "metrics"})
            assert result is True
            mock_logger.debug.assert_called()
    
    def test_export_with_exception(self):
        """Test export handles exceptions."""
        exporter = PrometheusExporter()
        exporter._prometheus_available = True
        
        with patch('seedcore.ops.metrics.exporters.logger.debug', side_effect=Exception("Test error")):
            result = exporter.export({"test": "metrics"})
            assert result is False
    
    def test_flush(self):
        """Test PrometheusExporter flush."""
        exporter = PrometheusExporter()
        result = exporter.flush()
        assert result is True
    
    def test_get_health_unavailable(self):
        """Test health status when prometheus_client is unavailable."""
        exporter = PrometheusExporter()
        health = exporter.get_health()
        
        assert health["type"] == "PrometheusExporter"
        assert health["available"] is False
        assert health["healthy"] is False
    
    def test_get_health_available(self):
        """Test health status when prometheus_client is available."""
        exporter = PrometheusExporter()
        exporter._prometheus_available = True
        health = exporter.get_health()
        
        assert health["type"] == "PrometheusExporter"
        assert health["available"] is True
        assert health["healthy"] is True


class TestOpenTelemetryExporter:
    """Tests for OpenTelemetryExporter."""
    
    def test_init_without_otel(self):
        """Test OpenTelemetryExporter initialization without opentelemetry."""
        exporter = OpenTelemetryExporter()
        assert exporter._otel_available is False
    
    @patch('seedcore.ops.metrics.exporters.logger')
    def test_init_without_otel_logs_warning(self, mock_logger):
        """Test that missing opentelemetry logs a warning."""
        OpenTelemetryExporter()
        mock_logger.warning.assert_called()
    
    def test_export_without_otel(self):
        """Test export when opentelemetry is not available."""
        exporter = OpenTelemetryExporter()
        result = exporter.export({"test": "metrics"})
        assert result is False
    
    def test_export_with_otel(self):
        """Test export when opentelemetry is available."""
        exporter = OpenTelemetryExporter()
        exporter._otel_available = True
        
        with patch('seedcore.ops.metrics.exporters.logger') as mock_logger:
            result = exporter.export({"test": "metrics"})
            assert result is True
            mock_logger.debug.assert_called()
    
    def test_flush(self):
        """Test OpenTelemetryExporter flush."""
        exporter = OpenTelemetryExporter()
        result = exporter.flush()
        assert result is True
    
    def test_get_health_unavailable(self):
        """Test health status when opentelemetry is unavailable."""
        exporter = OpenTelemetryExporter()
        health = exporter.get_health()
        
        assert health["type"] == "OpenTelemetryExporter"
        assert health["available"] is False
        assert health["healthy"] is False
    
    def test_get_health_available(self):
        """Test health status when opentelemetry is available."""
        exporter = OpenTelemetryExporter()
        exporter._otel_available = True
        health = exporter.get_health()
        
        assert health["type"] == "OpenTelemetryExporter"
        assert health["available"] is True
        assert health["healthy"] is True


class TestRedisExporter:
    """Tests for RedisExporter."""
    
    def test_init_without_redis(self):
        """Test RedisExporter initialization without redis client."""
        exporter = RedisExporter()
        assert exporter._redis_available is False
    
    def test_init_with_redis(self):
        """Test RedisExporter initialization with redis client."""
        mock_redis = Mock()
        exporter = RedisExporter(redis_client=mock_redis)
        assert exporter._redis_available is True
        assert exporter.redis_client is mock_redis
    
    def test_init_with_custom_stream_key(self):
        """Test RedisExporter with custom stream key."""
        exporter = RedisExporter(stream_key="custom:metrics")
        assert exporter.stream_key == "custom:metrics"
    
    def test_export_without_redis(self):
        """Test export when redis is not available."""
        exporter = RedisExporter()
        result = exporter.export({"test": "metrics"})
        assert result is False
    
    def test_export_with_redis(self):
        """Test export when redis is available."""
        mock_redis = Mock()
        exporter = RedisExporter(redis_client=mock_redis)
        
        with patch('seedcore.ops.metrics.exporters.logger') as mock_logger:
            result = exporter.export({"test": "metrics"})
            assert result is True
            mock_logger.debug.assert_called()
    
    def test_export_with_exception(self):
        """Test export handles exceptions."""
        mock_redis = Mock()
        exporter = RedisExporter(redis_client=mock_redis)
        
        with patch('seedcore.ops.metrics.exporters.logger.debug', side_effect=Exception("Test error")):
            result = exporter.export({"test": "metrics"})
            assert result is False
    
    def test_flush(self):
        """Test RedisExporter flush."""
        exporter = RedisExporter()
        result = exporter.flush()
        assert result is True
    
    def test_get_health_unavailable(self):
        """Test health status when redis is unavailable."""
        exporter = RedisExporter()
        health = exporter.get_health()
        
        assert health["type"] == "RedisExporter"
        assert health["available"] is False
        assert health["healthy"] is False
    
    def test_get_health_available(self):
        """Test health status when redis is available."""
        mock_redis = Mock()
        exporter = RedisExporter(redis_client=mock_redis)
        health = exporter.get_health()
        
        assert health["type"] == "RedisExporter"
        assert health["available"] is True
        assert health["healthy"] is True

