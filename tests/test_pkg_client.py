#!/usr/bin/env python3
"""
Unit tests for PKG Client (facade).

Tests the PKGClient facade that composes multiple DAOs.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from seedcore.ops.pkg.client import PKGClient
from seedcore.ops.pkg.dao import PKGSnapshotData


class TestPKGClient:
    """Tests for PKGClient facade."""
    
    @pytest.fixture
    def mock_session_factory(self):
        """Create a mock session factory."""
        def _create_session():
            session = AsyncMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            return session
        return _create_session
    
    @pytest.fixture
    def client(self, mock_session_factory):
        """Create a PKGClient instance."""
        return PKGClient(session_factory=mock_session_factory)
    
    @pytest.mark.asyncio
    async def test_get_active_snapshot(self, client):
        """Test getting active snapshot through facade."""
        mock_snapshot = PKGSnapshotData(
            id=1,
            version='rules@1.4.0',
            engine='wasm',
            wasm_artifact=b'wasm_data',
            checksum='abc123',
            rules=[]
        )
        
        client.snapshots.get_active_snapshot = AsyncMock(return_value=mock_snapshot)
        
        snapshot = await client.get_active_snapshot()
        
        assert snapshot == mock_snapshot
        client.snapshots.get_active_snapshot.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_snapshot_by_version(self, client):
        """Test getting snapshot by version."""
        mock_snapshot = PKGSnapshotData(
            id=1,
            version='rules@1.4.0',
            engine='native',
            wasm_artifact=None,
            checksum='abc123',
            rules=[{'rule_name': 'test'}]
        )
        
        client.snapshots.get_snapshot_by_version = AsyncMock(return_value=mock_snapshot)
        
        snapshot = await client.get_snapshot_by_version('rules@1.4.0')
        
        assert snapshot == mock_snapshot
        client.snapshots.get_snapshot_by_version.assert_called_once_with('rules@1.4.0')
    
    @pytest.mark.asyncio
    async def test_get_deployments(self, client):
        """Test getting deployments."""
        mock_deployments = [
            {'id': 1, 'target': 'router', 'snapshot_version': 'rules@1.4.0'},
            {'id': 2, 'target': 'edge:door', 'snapshot_version': 'rules@1.4.0'}
        ]
        
        client.deployments.get_deployments = AsyncMock(return_value=mock_deployments)
        
        deployments = await client.get_deployments(target='router')
        
        assert deployments == mock_deployments
        client.deployments.get_deployments.assert_called_once_with(
            snapshot_id=None,
            target='router',
            region=None,
            active_only=True
        )
    
    @pytest.mark.asyncio
    async def test_get_deployment_coverage(self, client):
        """Test getting deployment coverage."""
        mock_coverage = [
            {
                'target': 'router',
                'devices_on_snapshot': 45,
                'devices_total': 50
            }
        ]
        
        client.deployments.get_deployment_coverage = AsyncMock(return_value=mock_coverage)
        
        coverage = await client.get_deployment_coverage()
        
        assert coverage == mock_coverage
        client.deployments.get_deployment_coverage.assert_called_once_with(
            target=None,
            region=None
        )
    
    @pytest.mark.asyncio
    async def test_get_validation_fixtures(self, client):
        """Test getting validation fixtures."""
        mock_fixtures = [
            {'id': 1, 'name': 'test_fixture', 'input': {}, 'expect': {}}
        ]
        
        client.validation.get_validation_fixtures = AsyncMock(return_value=mock_fixtures)
        
        fixtures = await client.get_validation_fixtures(snapshot_id=1)
        
        assert fixtures == mock_fixtures
        client.validation.get_validation_fixtures.assert_called_once_with(1)
    
    @pytest.mark.asyncio
    async def test_create_validation_run(self, client):
        """Test creating validation run."""
        client.validation.create_validation_run = AsyncMock(return_value=123)
        
        run_id = await client.create_validation_run(snapshot_id=1)
        
        assert run_id == 123
        client.validation.create_validation_run.assert_called_once_with(1, None)
    
    @pytest.mark.asyncio
    async def test_finish_validation_run(self, client):
        """Test finishing validation run."""
        client.validation.finish_validation_run = AsyncMock()
        
        await client.finish_validation_run(
            run_id=123,
            success=True,
            report={'passed': 10}
        )
        
        client.validation.finish_validation_run.assert_called_once_with(
            123, True, {'passed': 10}
        )
    
    @pytest.mark.asyncio
    async def test_get_promotions(self, client):
        """Test getting promotions."""
        mock_promotions = [
            {
                'id': 1,
                'from_version': 'rules@1.3.0',
                'to_version': 'rules@1.4.0',
                'action': 'promote'
            }
        ]
        
        client.promotions.get_promotions = AsyncMock(return_value=mock_promotions)
        
        promotions = await client.get_promotions()
        
        assert promotions == mock_promotions
        client.promotions.get_promotions.assert_called_once_with(
            snapshot_id=None,
            limit=100
        )
    
    @pytest.mark.asyncio
    async def test_create_promotion(self, client):
        """Test creating promotion."""
        client.promotions.create_promotion = AsyncMock(return_value=456)
        
        promo_id = await client.create_promotion(
            snapshot_id=1,
            actor='admin',
            action='promote',
            reason='Production ready'
        )
        
        assert promo_id == 456
        client.promotions.create_promotion.assert_called_once_with(
            snapshot_id=1,
            actor='admin',
            action='promote',
            reason='Production ready',
            metrics=None,
            success=True
        )
    
    @pytest.mark.asyncio
    async def test_get_device_versions(self, client):
        """Test getting device versions."""
        mock_devices = [
            {
                'device_id': 'door:D-1510',
                'device_type': 'door',
                'snapshot_version': 'rules@1.4.0'
            }
        ]
        
        client.devices.get_device_versions = AsyncMock(return_value=mock_devices)
        
        devices = await client.get_device_versions(device_type='door')
        
        assert devices == mock_devices
        client.devices.get_device_versions.assert_called_once_with(
            device_type='door',
            region=None,
            snapshot_id=None
        )
    
    @pytest.mark.asyncio
    async def test_update_device_heartbeat(self, client):
        """Test updating device heartbeat."""
        client.devices.update_device_heartbeat = AsyncMock()
        
        await client.update_device_heartbeat(
            device_id='door:D-1510',
            device_type='door',
            snapshot_id=1
        )
        
        client.devices.update_device_heartbeat.assert_called_once_with(
            device_id='door:D-1510',
            device_type='door',
            snapshot_id=1,
            version=None,
            region='global'
        )
    
    @pytest.mark.asyncio
    async def test_get_semantic_context(self, client):
        """Test getting semantic context through facade."""
        mock_context = [
            {
                'id': 'task-123',
                'category': 'guest_request',
                'content': 'Guest wants room service',
                'memory_tier': 'TIER_1',
                'similarity': 0.95
            }
        ]
        
        client.cortex.get_semantic_context = AsyncMock(return_value=mock_context)
        
        embedding = [0.1] * 1024
        context = await client.get_semantic_context(
            embedding=embedding,
            limit=5,
            min_similarity=0.8,
            exclude_task_id='task-999'
        )
        
        assert context == mock_context
        client.cortex.get_semantic_context.assert_called_once_with(
            embedding=embedding,
            limit=5,
            min_similarity=0.8,
            exclude_task_id='task-999'
        )
    
    @pytest.mark.asyncio
    async def test_get_active_governed_facts(self, client):
        """Test getting active governed facts through facade."""
        mock_facts = [
            {
                'id': 'fact-uuid-1',
                'namespace': 'default',
                'subject': 'guest:Ben',
                'predicate': 'hasTemporaryAccess',
                'object_data': {'service': 'lounge'},
                'pkg_rule_id': 'rule-001',
                'snapshot_id': 1,
                'valid_from': None,
                'valid_to': None
            }
        ]
        
        client.cortex.get_active_governed_facts = AsyncMock(return_value=mock_facts)
        
        facts = await client.get_active_governed_facts(
            snapshot_id=1,
            namespace='default',
            subject='guest:Ben',
            limit=100
        )
        
        assert facts == mock_facts
        client.cortex.get_active_governed_facts.assert_called_once_with(
            snapshot_id=1,
            namespace='default',
            subject='guest:Ben',
            predicate=None,
            limit=100
        )
    
    @pytest.mark.asyncio
    async def test_get_active_governed_facts_with_predicate(self, client):
        """Test getting active governed facts with predicate filter."""
        mock_facts = [
            {
                'id': 'fact-uuid-1',
                'subject': 'guest:Ben',
                'predicate': 'hasTemporaryAccess',
                'object_data': {'service': 'lounge'}
            }
        ]
        
        client.cortex.get_active_governed_facts = AsyncMock(return_value=mock_facts)
        
        facts = await client.get_active_governed_facts(
            snapshot_id=1,
            namespace='default',
            subject='guest:Ben',
            predicate='hasTemporaryAccess',
            limit=100
        )
        
        assert facts == mock_facts
        client.cortex.get_active_governed_facts.assert_called_once_with(
            snapshot_id=1,
            namespace='default',
            subject='guest:Ben',
            predicate='hasTemporaryAccess',
            limit=100
        )
    
    @pytest.mark.asyncio
    async def test_promote_task_to_knowledge_graph(self, client):
        """Test promoting task to knowledge graph through facade."""
        mock_result = {
            'ok': True,
            'msg': 'Task promoted successfully',
            'new_node_id': 12345,
            'task_id': 'task-uuid-123'
        }
        
        client.cortex.promote_task_to_knowledge_graph = AsyncMock(return_value=mock_result)
        
        result = await client.promote_task_to_knowledge_graph(
            task_id='task-uuid-123',
            actor='admin',
            preserve_multimodal=True
        )
        
        assert result == mock_result
        client.cortex.promote_task_to_knowledge_graph.assert_called_once_with(
            task_id='task-uuid-123',
            actor='admin',
            preserve_multimodal=True
        )
    
    @pytest.mark.asyncio
    async def test_check_integrity(self, client):
        """Test checking integrity."""
        from seedcore.ops.pkg.dao import check_pkg_integrity
        
        with patch('seedcore.ops.pkg.client.check_pkg_integrity') as mock_check:
            mock_check.return_value = {'ok': True, 'msg': 'OK'}
            
            result = await client.check_integrity()
            
            assert result['ok'] is True
            mock_check.assert_called_once()

