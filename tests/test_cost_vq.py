#!/usr/bin/env python3
"""
Unit tests for cost_vq calculation.

Tests are independent of Ray and Kubernetes cluster dependencies.
"""

import sys
import os

# Add tests directory to path for mock imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import mocks BEFORE other imports
import mock_database_dependencies
import mock_ray_dependencies

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
import numpy as np

from src.seedcore.memory.cost_vq import calculate_cost_vq, _compute_cost_math, DEFAULT_WEIGHTS


class TestComputeCostMath:
    """Tests for low-level cost computation function."""
    
    def test_compute_cost_math_basic(self):
        """Test basic cost computation."""
        bytes_cost = 1.5  # 1.5 GB
        recon_loss = 0.3
        staleness = 0.2
        w_b = 1.0
        w_r = 1.0
        w_s = 0.5
        
        cost = _compute_cost_math(bytes_cost, recon_loss, staleness, w_b, w_r, w_s)
        
        expected = (1.0 * 1.5) + (1.0 * 0.3) + (0.5 * 0.2)
        assert cost == pytest.approx(expected)
    
    def test_compute_cost_math_zero_staleness(self):
        """Test cost computation with zero staleness."""
        cost = _compute_cost_math(1.0, 0.5, 0.0, 1.0, 1.0, 0.5)
        expected = (1.0 * 1.0) + (1.0 * 0.5) + (0.5 * 0.0)
        assert cost == pytest.approx(expected)
    
    def test_compute_cost_math_custom_weights(self):
        """Test cost computation with custom weights."""
        cost = _compute_cost_math(2.0, 0.4, 0.6, 2.0, 0.5, 0.3)
        expected = (2.0 * 2.0) + (0.5 * 0.4) + (0.3 * 0.6)
        assert cost == pytest.approx(expected)


class TestCalculateCostVq:
    """Tests for high-level async calculate_cost_vq function."""
    
    @pytest.fixture
    def mock_mw_manager(self):
        """Create a mock MwManager."""
        manager = Mock()
        manager.get_cluster_stats = AsyncMock(return_value={
            "bytes_used": 1024 * 1024 * 500,  # 500 MB
            "hit_count": 100,
            "total_items": 200
        })
        return manager
    
    @pytest.fixture
    def mock_fabric(self):
        """Create a mock HolonFabric."""
        fabric = Mock()
        fabric.get_stats = AsyncMock(return_value={
            "total_holons": 1000,
            "total_relationships": 500,
            "bytes_used": 1024 * 1024 * 1024,  # 1 GB
            "vector_dimensions": 768,
            "status": "healthy"
        })
        return fabric
    
    @pytest.mark.asyncio
    async def test_calculate_cost_vq_basic(self, mock_mw_manager, mock_fabric):
        """Test basic cost_vq calculation."""
        compression_knob = 0.5
        
        result = await calculate_cost_vq(
            mock_mw_manager,
            mock_fabric,
            compression_knob
        )
        
        assert "cost_vq" in result
        assert "components" in result
        assert "raw_metrics" in result
        assert "weights" in result
        assert isinstance(result["cost_vq"], float)
        assert result["cost_vq"] != float('inf')
    
    @pytest.mark.asyncio
    async def test_calculate_cost_vq_components(self, mock_mw_manager, mock_fabric):
        """Test that all cost components are calculated correctly."""
        compression_knob = 0.5
        
        result = await calculate_cost_vq(
            mock_mw_manager,
            mock_fabric,
            compression_knob
        )
        
        components = result["components"]
        assert "bytes_cost" in components
        assert "recon_loss" in components
        assert "staleness" in components
        
        # Check recon_loss calculation (1.0 - compression_knob)
        assert components["recon_loss"] == 0.5
        
        # Check bytes_cost is normalized to GB
        raw_metrics = result["raw_metrics"]
        total_bytes = raw_metrics["total_bytes"]
        assert components["bytes_cost"] == pytest.approx(total_bytes / (1024**3))
    
    @pytest.mark.asyncio
    async def test_calculate_cost_vq_recon_loss(self, mock_mw_manager, mock_fabric):
        """Test reconstruction loss calculation."""
        # Test with different compression knobs
        for knob in [0.0, 0.25, 0.5, 0.75, 1.0]:
            result = await calculate_cost_vq(
                mock_mw_manager,
                mock_fabric,
                knob
            )
            
            expected_recon_loss = 1.0 - knob
            assert result["components"]["recon_loss"] == pytest.approx(expected_recon_loss)
    
    @pytest.mark.asyncio
    async def test_calculate_cost_vq_staleness(self, mock_mw_manager, mock_fabric):
        """Test staleness calculation based on hit rate."""
        # With 100 hits out of 1200 total items (200 mw + 1000 mlt)
        # hit_rate = 100 / 1200 = 0.0833
        # staleness = 1.0 - 0.0833 = 0.9167
        result = await calculate_cost_vq(
            mock_mw_manager,
            mock_fabric,
            0.5
        )
        
        raw_metrics = result["raw_metrics"]
        assert raw_metrics["total_hits"] == 100
        assert raw_metrics["total_items"] == 1200
        hit_rate = 100 / 1200
        assert raw_metrics["hit_rate"] == pytest.approx(hit_rate)
        assert result["components"]["staleness"] == pytest.approx(1.0 - hit_rate)
    
    @pytest.mark.asyncio
    async def test_calculate_cost_vq_zero_data_points(self, mock_mw_manager, mock_fabric):
        """Test cost_vq with zero data points."""
        mock_mw_manager.get_cluster_stats = AsyncMock(return_value={
            "bytes_used": 0,
            "hit_count": 0,
            "total_items": 0
        })
        mock_fabric.get_stats = AsyncMock(return_value={
            "total_holons": 0,
            "total_relationships": 0,
            "bytes_used": 0,
            "status": "healthy"
        })
        
        result = await calculate_cost_vq(
            mock_mw_manager,
            mock_fabric,
            0.5
        )
        
        # With no data, hit_rate should be 1.0 (100% "hits"), staleness should be 0.0
        assert result["components"]["staleness"] == 0.0
        assert result["raw_metrics"]["hit_rate"] == 1.0
    
    @pytest.mark.asyncio
    async def test_calculate_cost_vq_custom_weights(self, mock_mw_manager, mock_fabric):
        """Test cost_vq with custom weights."""
        custom_weights = {
            "w_b": 2.0,
            "w_r": 0.5,
            "w_s": 1.0
        }
        
        result = await calculate_cost_vq(
            mock_mw_manager,
            mock_fabric,
            0.5,
            weights=custom_weights
        )
        
        assert result["weights"]["w_b"] == 2.0
        assert result["weights"]["w_r"] == 0.5
        assert result["weights"]["w_s"] == 1.0
    
    @pytest.mark.asyncio
    async def test_calculate_cost_vq_error_handling(self, mock_mw_manager, mock_fabric):
        """Test cost_vq handles errors gracefully."""
        mock_mw_manager.get_cluster_stats = AsyncMock(side_effect=Exception("Connection error"))
        
        result = await calculate_cost_vq(
            mock_mw_manager,
            mock_fabric,
            0.5
        )
        
        assert result["cost_vq"] == float('inf')
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_calculate_cost_vq_missing_keys(self, mock_mw_manager, mock_fabric):
        """Test cost_vq handles missing keys in stats gracefully."""
        mock_mw_manager.get_cluster_stats = AsyncMock(return_value={})
        mock_fabric.get_stats = AsyncMock(return_value={})
        
        result = await calculate_cost_vq(
            mock_mw_manager,
            mock_fabric,
            0.5
        )
        
        # Should use defaults (0) for missing keys
        assert result["raw_metrics"]["total_bytes"] == 0
        assert result["components"]["staleness"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
