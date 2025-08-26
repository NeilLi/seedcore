"""
Unit tests for Coordinator async initialization.
Tests that the async __init__ pattern works correctly without event loop conflicts.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from seedcore.agents.queue_dispatcher import Coordinator


class TestCoordinatorAsyncInit:
    """Test cases for Coordinator async initialization."""
    
    @pytest.mark.asyncio
    async def test_coordinator_async_init_success(self):
        """Test that Coordinator async initialization works correctly."""
        # Mock the OrganismManager to avoid actual initialization
        with patch('seedcore.agents.queue_dispatcher.OrganismManager') as mock_om_class:
            mock_om = MagicMock()
            mock_om.initialize_organism = AsyncMock()
            mock_om_class.return_value = mock_om
            
            # Create Coordinator instance (this will call async __init__)
            coord = Coordinator()
            await coord.__init__()
            
            # Verify OrganismManager was created and initialized
            mock_om_class.assert_called_once()
            mock_om.initialize_organism.assert_called_once()
            
            # Verify the instance has the expected attributes
            assert hasattr(coord, 'org')
            assert coord.org == mock_om
    
    @pytest.mark.asyncio
    async def test_coordinator_handle_method(self):
        """Test that the handle method works correctly after async initialization."""
        # Mock the OrganismManager
        with patch('seedcore.agents.queue_dispatcher.OrganismManager') as mock_om_class:
            mock_om = MagicMock()
            mock_om.initialize_organism = AsyncMock()
            mock_om.handle_incoming_task = AsyncMock(return_value={"success": True, "result": "test"})
            mock_om_class.return_value = mock_om
            
            # Create and initialize Coordinator
            coord = Coordinator()
            await coord.__init__()
            
            # Test task handling
            test_task = {"type": "test", "params": {}}
            result = await coord.handle(test_task)
            
            # Verify the result
            assert result == {"success": True, "result": "test"}
            mock_om.handle_incoming_task.assert_called_once_with(test_task, app_state=None)
    
    @pytest.mark.asyncio
    async def test_coordinator_ping_method(self):
        """Test that the ping method returns 'pong'."""
        # Mock the OrganismManager
        with patch('seedcore.agents.queue_dispatcher.OrganismManager') as mock_om_class:
            mock_om = MagicMock()
            mock_om.initialize_organism = AsyncMock()
            mock_om_class.return_value = mock_om
            
            # Create and initialize Coordinator
            coord = Coordinator()
            await coord.__init__()
            
            # Test ping
            result = await coord.ping()
            assert result == "pong"
    
    @pytest.mark.asyncio
    async def test_coordinator_get_status_method(self):
        """Test that the get_status method returns correct status information."""
        # Mock the OrganismManager
        with patch('seedcore.agents.queue_dispatcher.OrganismManager') as mock_om_class:
            mock_om = MagicMock()
            mock_om.initialize_organism = AsyncMock()
            mock_om._initialized = True  # Simulate initialized organism
            mock_om_class.return_value = mock_om
            
            # Create and initialize Coordinator
            coord = Coordinator()
            await coord.__init__()
            
            # Test get_status
            status = await coord.get_status()
            assert status["status"] == "healthy"
            assert status["organism_initialized"] is True
            assert status["coordinator"] == "available"
    
    @pytest.mark.asyncio
    async def test_coordinator_get_status_uninitialized(self):
        """Test get_status when OrganismManager is not properly initialized."""
        # Mock the OrganismManager
        with patch('seedcore.agents.queue_dispatcher.OrganismManager') as mock_om_class:
            mock_om = MagicMock()
            mock_om.initialize_organism = AsyncMock()
            mock_om._initialized = False  # Simulate uninitialized organism
            mock_om_class.return_value = mock_om
            
            # Create and initialize Coordinator
            coord = Coordinator()
            await coord.__init__()
            
            # Test get_status
            status = await coord.get_status()
            assert status["status"] == "initializing"
            assert status["organism_initialized"] is False
            assert status["coordinator"] == "available"
    
    @pytest.mark.asyncio
    async def test_coordinator_init_failure_handling(self):
        """Test that initialization failures are handled gracefully."""
        # Mock the OrganismManager to raise an exception during initialization
        with patch('seedcore.agents.queue_dispatcher.OrganismManager') as mock_om_class:
            mock_om = MagicMock()
            mock_om.initialize_organism = AsyncMock(side_effect=Exception("Initialization failed"))
            mock_om_class.return_value = mock_om
            
            # Create Coordinator instance
            coord = Coordinator()
            
            # Verify that initialization failure raises the exception
            with pytest.raises(Exception, match="Initialization failed"):
                await coord.__init__()
    
    def test_coordinator_ray_decorator(self):
        """Test that the Coordinator class has the correct Ray decorator."""
        # Check that the class has the expected Ray decorator attributes
        assert hasattr(Coordinator, '_remote')
        assert hasattr(Coordinator, '_ray_remote_function')
        
        # Verify the decorator configuration
        remote_options = Coordinator._ray_remote_function.options
        assert remote_options.name == "seedcore_coordinator"
        assert remote_options.lifetime == "detached"
        assert remote_options.num_cpus == 0.1


if __name__ == "__main__":
    pytest.main([__file__])
