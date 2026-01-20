#!/usr/bin/env python3
"""
Unit tests for PKG Data Access Objects (DAOs).

Tests all DAO classes with mocked database connections.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from types import SimpleNamespace
from datetime import datetime
from typing import Dict, Any, List

from seedcore.ops.pkg.dao import (
    PKGSnapshotsDAO,
    PKGDeploymentsDAO,
    PKGValidationDAO,
    PKGPromotionsDAO,
    PKGDevicesDAO,
    PKGCortexDAO,
    PKGSnapshotData,
    check_pkg_integrity,
)


class TestPKGSnapshotsDAO:
    """Tests for PKGSnapshotsDAO."""
    
    @pytest.fixture
    def mock_session_factory(self):
        """Create a mock session factory."""
        def _create_session():
            session = AsyncMock()
            session.__aenter__.return_value = session
            session.__aexit__.return_value = None
            return session
        return _create_session
    
    @pytest.fixture
    def mock_snapshot_row(self):
        """Create a mock snapshot row."""
        row = Mock()
        row._mapping = {
            'id': 1,
            'version': 'rules@1.4.0',
            'checksum': 'abc123def456',
            'notes': 'Test snapshot'
        }
        return row
    
    @pytest.fixture
    def mock_wasm_artifact_row(self):
        """Create a mock WASM artifact row."""
        row = Mock()
        row._mapping = {
            'artifact_bytes': b'wasm_binary_data',
            'artifact_type': 'wasm_pack'
        }
        return row
    
    @pytest.fixture
    def mock_native_rules_rows(self):
        """Create mock native rule rows with conditions and emissions."""
        rows = []
        
        # Rule 1 with conditions and emissions
        row1 = Mock()
        row1._mapping = {
            'rule_id': 'rule-001',
            'rule_name': 'high_priority_vip',
            'priority': 10,
            'rule_source': 'yaml',
            'compiled_rule': None,
            'engine': 'native',
            'rule_hash': 'hash1',
            'metadata': {},
            'disabled': False,
            'condition_type': 'TAG',
            'condition_key': 'vip',
            'operator': 'IN',
            'condition_value': 'vip',
            'condition_position': 0,
            'relationship_type': 'EMITS',
            'emission_params': {'level': 'high'},
            'emission_position': 0,
            'subtask_type_id': 'subtask-001',
            'subtask_name': 'escalate_vip',
            'subtask_default_params': {}
        }
        rows.append(row1)
        
        # Rule 2
        row2 = Mock()
        row2._mapping = {
            'rule_id': 'rule-002',
            'rule_name': 'allergen_alert',
            'priority': 8,
            'rule_source': 'yaml',
            'compiled_rule': None,
            'engine': 'native',
            'rule_hash': 'hash2',
            'metadata': {},
            'disabled': False,
            'condition_type': 'TAG',
            'condition_key': 'allergen',
            'operator': 'EXISTS',
            'condition_value': None,
            'condition_position': 0,
            'relationship_type': 'EMITS',
            'emission_params': {'alert_type': 'allergen'},
            'emission_position': 0,
            'subtask_type_id': 'subtask-002',
            'subtask_name': 'notify_kitchen',
            'subtask_default_params': {}
        }
        rows.append(row2)
        
        return rows
    
    @pytest.fixture
    def dao(self, mock_session_factory):
        """Create a PKGSnapshotsDAO instance."""
        return PKGSnapshotsDAO(session_factory=mock_session_factory)
    
    @pytest.mark.asyncio
    async def test_get_active_snapshot_wasm(self, dao, mock_session_factory, mock_snapshot_row, mock_wasm_artifact_row):
        """Test getting active WASM snapshot."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        # Mock snapshot query
        snapshot_result = AsyncMock()
        snapshot_result.first.return_value = mock_snapshot_row

        artifact_result = AsyncMock()
        artifact_result.first.return_value = mock_wasm_artifact_row

        session.execute.side_effect = [snapshot_result, artifact_result]

        snapshot = await dao.get_active_snapshot()
        
        assert snapshot is not None
        assert snapshot.id == 1
        assert snapshot.version == 'rules@1.4.0'
        assert snapshot.engine == 'wasm'
        assert snapshot.wasm_artifact == b'wasm_binary_data'
        assert snapshot.checksum == 'abc123def456'
        assert snapshot.rules == []
    
    @pytest.mark.asyncio
    async def test_get_active_snapshot_native(self, dao, mock_session_factory, mock_snapshot_row, mock_native_rules_rows):
        """Test getting active native snapshot with rules."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        # Mock snapshot query
        snapshot_result = AsyncMock()
        snapshot_result.first.return_value = mock_snapshot_row

        artifact_result = AsyncMock()
        artifact_result.first.return_value = None

        rules_result = AsyncMock()
        rules_result.__iter__ = Mock(return_value=iter(mock_native_rules_rows))

        session.execute.side_effect = [snapshot_result, artifact_result, rules_result]

        snapshot = await dao.get_active_snapshot()
        
        assert snapshot is not None
        assert snapshot.engine == 'native'
        assert snapshot.wasm_artifact is None
        assert len(snapshot.rules) == 2
        assert snapshot.rules[0]['rule_name'] == 'high_priority_vip'
        assert len(snapshot.rules[0]['conditions']) > 0
        assert len(snapshot.rules[0]['emissions']) > 0
    
    @pytest.mark.asyncio
    async def test_get_active_snapshot_not_found(self, dao, mock_session_factory):
        """Test getting active snapshot when none exists."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        snapshot_result = AsyncMock()
        snapshot_result.first.return_value = None
        session.execute.side_effect = [snapshot_result]

        snapshot = await dao.get_active_snapshot()
        
        assert snapshot is None
    
    @pytest.mark.asyncio
    async def test_get_snapshot_by_version(self, dao, mock_session_factory, mock_snapshot_row, mock_wasm_artifact_row):
        """Test getting snapshot by version."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        snapshot_result = AsyncMock()
        snapshot_result.first.return_value = mock_snapshot_row

        artifact_result = AsyncMock()
        artifact_result.first.return_value = mock_wasm_artifact_row

        session.execute.side_effect = [snapshot_result, artifact_result]

        snapshot = await dao.get_snapshot_by_version('rules@1.4.0')
        
        assert snapshot is not None
        assert snapshot.version == 'rules@1.4.0'
    
    @pytest.mark.asyncio
    async def test_get_active_artifact(self, dao, mock_session_factory):
        """Test getting active artifact."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        result = AsyncMock()
        row = Mock()
        row._mapping = {
            'env': 'prod',
            'snapshot_id': 1,
            'version': 'rules@1.4.0',
            'artifact_type': 'wasm_pack',
            'size_bytes': 1024,
            'sha256': 'abc123'
        }
        result.first.return_value = row
        session.execute.side_effect = [result]

        artifact = await dao.get_active_artifact('prod')
        
        assert artifact is not None
        assert artifact['version'] == 'rules@1.4.0'
        assert artifact['artifact_type'] == 'wasm_pack'


class TestPKGDeploymentsDAO:
    """Tests for PKGDeploymentsDAO."""
    
    @pytest.fixture
    def mock_session_factory(self):
        """Create a mock session factory."""
        def _create_session():
            session = AsyncMock()
            session.__aenter__.return_value = session
            session.__aexit__.return_value = None
            return session
        return _create_session
    
    @pytest.fixture
    def dao(self, mock_session_factory):
        """Create a PKGDeploymentsDAO instance."""
        return PKGDeploymentsDAO(session_factory=mock_session_factory)
    
    @pytest.mark.asyncio
    async def test_get_deployments(self, dao, mock_session_factory):
        """Test getting deployments."""
        session = mock_session_factory()
        dao._sf = lambda: session

        result = AsyncMock()
        row1 = Mock()
        row1._mapping = {
            'id': 1,
            'snapshot_id': 1,
            'target': 'router',
            'region': 'global',
            'percent': 100,
            'is_active': True,
            'snapshot_version': 'rules@1.4.0'
        }
        row2 = Mock()
        row2._mapping = {
            'id': 2,
            'snapshot_id': 1,
            'target': 'edge:door',
            'region': 'us-west',
            'percent': 50,
            'is_active': True,
            'snapshot_version': 'rules@1.4.0'
        }
        result.__iter__ = Mock(return_value=iter([row1, row2]))
        session.execute.side_effect = [result]
        
        deployments = await dao.get_deployments()
        
        assert len(deployments) == 2
        assert deployments[0]['target'] == 'router'
        assert deployments[1]['target'] == 'edge:door'
    
    @pytest.mark.asyncio
    async def test_get_deployments_filtered(self, dao, mock_session_factory):
        """Test getting deployments with filters."""
        session = mock_session_factory()
        dao._sf = lambda: session

        result = AsyncMock()
        row = Mock()
        row._mapping = {
            'id': 1,
            'snapshot_id': 1,
            'target': 'router',
            'region': 'global',
            'percent': 100,
            'is_active': True,
            'snapshot_version': 'rules@1.4.0'
        }
        result.__iter__ = Mock(return_value=iter([row]))
        session.execute.side_effect = [result]
        
        deployments = await dao.get_deployments(target='router', region='global')
        
        assert len(deployments) == 1
        assert deployments[0]['target'] == 'router'
    
    @pytest.mark.asyncio
    async def test_get_deployment_coverage(self, dao, mock_session_factory):
        """Test getting deployment coverage."""
        session = mock_session_factory()
        dao._sf = lambda: session

        result = AsyncMock()
        row = Mock()
        row._mapping = {
            'target': 'router',
            'region': 'global',
            'snapshot_id': 1,
            'version': 'rules@1.4.0',
            'devices_on_snapshot': 45,
            'devices_total': 50
        }
        result.__iter__ = Mock(return_value=iter([row]))
        session.execute.side_effect = [result]
        
        coverage = await dao.get_deployment_coverage()
        
        assert len(coverage) == 1
        assert coverage[0]['devices_on_snapshot'] == 45
        assert coverage[0]['devices_total'] == 50


class TestPKGValidationDAO:
    """Tests for PKGValidationDAO."""
    
    @pytest.fixture
    def mock_session_factory(self):
        """Create a mock session factory."""
        def _create_session():
            session = AsyncMock()
            session.__aenter__.return_value = session
            session.__aexit__.return_value = None
            tx = AsyncMock()
            tx.__aenter__.return_value = session
            tx.__aexit__.return_value = None
            session.begin = Mock(return_value=tx)
            return session
        return _create_session
    
    @pytest.fixture
    def dao(self, mock_session_factory):
        """Create a PKGValidationDAO instance."""
        return PKGValidationDAO(session_factory=mock_session_factory)
    
    @pytest.mark.asyncio
    async def test_get_validation_fixtures(self, dao, mock_session_factory):
        """Test getting validation fixtures."""
        session = mock_session_factory()
        dao._sf = lambda: session

        result = AsyncMock()
        row = Mock()
        row._mapping = {
            'id': 1,
            'name': 'test_fixture',
            'input': {'tags': ['vip']},
            'expect': {'subtasks': []},
            'created_at': datetime.now()
        }
        result.__iter__ = Mock(return_value=iter([row]))
        session.execute.side_effect = [result]
        
        fixtures = await dao.get_validation_fixtures(snapshot_id=1)
        
        assert len(fixtures) == 1
        assert fixtures[0]['name'] == 'test_fixture'
    
    @pytest.mark.asyncio
    async def test_create_validation_run(self, dao, mock_session_factory):
        """Test creating validation run."""
        session = mock_session_factory()
        dao._sf = lambda: session

        result = AsyncMock()
        result.scalar.return_value = 123
        session.execute.side_effect = [result]
        
        run_id = await dao.create_validation_run(snapshot_id=1)
        
        assert run_id == 123
        session.begin.assert_called()
    
    @pytest.mark.asyncio
    async def test_finish_validation_run(self, dao, mock_session_factory):
        """Test finishing validation run."""
        session = mock_session_factory()
        dao._sf = lambda: session

        session.execute = AsyncMock()
        tx = AsyncMock()
        tx.__aenter__ = AsyncMock(return_value=session)
        tx.__aexit__ = AsyncMock(return_value=None)
        session.begin = Mock(return_value=tx)
        
        await dao.finish_validation_run(
            run_id=123,
            success=True,
            report={'passed': 10, 'failed': 0}
        )
        
        session.begin.assert_called()
        session.execute.assert_called()
    
    @pytest.mark.asyncio
    async def test_get_validation_runs(self, dao, mock_session_factory):
        """Test getting validation runs."""
        session = mock_session_factory()
        dao._sf = lambda: session

        result = AsyncMock()
        row = Mock()
        row._mapping = {
            'id': 123,
            'snapshot_id': 1,
            'started_at': datetime.now(),
            'finished_at': datetime.now(),
            'success': True,
            'report': {}
        }
        result.__iter__ = Mock(return_value=iter([row]))
        session.execute.side_effect = [result]
        
        runs = await dao.get_validation_runs(snapshot_id=1)
        
        assert len(runs) == 1
        assert runs[0]['id'] == 123
        assert runs[0]['success'] is True


class TestPKGPromotionsDAO:
    """Tests for PKGPromotionsDAO."""
    
    @pytest.fixture
    def mock_session_factory(self):
        """Create a mock session factory."""
        def _create_session():
            session = AsyncMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            tx = AsyncMock()
            tx.__aenter__ = AsyncMock(return_value=session)
            tx.__aexit__ = AsyncMock(return_value=None)
            session.begin = Mock(return_value=tx)
            return session
        return _create_session
    
    @pytest.fixture
    def dao(self, mock_session_factory):
        """Create a PKGPromotionsDAO instance."""
        return PKGPromotionsDAO(session_factory=mock_session_factory)
    
    @pytest.mark.asyncio
    async def test_get_promotions(self, dao, mock_session_factory):
        """Test getting promotions."""
        session = mock_session_factory()
        dao._sf = lambda: session

        result = AsyncMock()
        row = Mock()
        row._mapping = {
            'id': 1,
            'snapshot_id': 1,
            'from_version': 'rules@1.3.0',
            'to_version': 'rules@1.4.0',
            'actor': 'admin',
            'action': 'promote',
            'reason': 'Production ready',
            'metrics': {'p95': 50},
            'success': True,
            'snapshot_version': 'rules@1.4.0'
        }
        result.__iter__ = Mock(return_value=iter([row]))
        session.execute.side_effect = [result]
        
        promotions = await dao.get_promotions()
        
        assert len(promotions) == 1
        assert promotions[0]['action'] == 'promote'
        assert promotions[0]['from_version'] == 'rules@1.3.0'
    
    @pytest.mark.asyncio
    async def test_create_promotion(self, dao, mock_session_factory):
        """Test creating promotion."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        current_result = AsyncMock()
        current_row = Mock()
        current_row._mapping = {'version': 'rules@1.3.0'}
        current_result.first.return_value = current_row

        to_result = AsyncMock()
        to_row = Mock()
        to_row._mapping = {'version': 'rules@1.4.0'}
        to_result.first.return_value = to_row

        insert_result = AsyncMock()
        insert_result.scalar.return_value = 456

        session.execute.side_effect = [current_result, to_result, insert_result]
        
        promo_id = await dao.create_promotion(
            snapshot_id=1,
            actor='admin',
            action='promote',
            reason='Ready for production'
        )
        
        assert promo_id == 456
        session.begin.assert_called()


class TestPKGDevicesDAO:
    """Tests for PKGDevicesDAO."""
    
    @pytest.fixture
    def mock_session_factory(self):
        """Create a mock session factory."""
        def _create_session():
            session = AsyncMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            tx = AsyncMock()
            tx.__aenter__ = AsyncMock(return_value=session)
            tx.__aexit__ = AsyncMock(return_value=None)
            session.begin = Mock(return_value=tx)
            return session
        return _create_session
    
    @pytest.fixture
    def dao(self, mock_session_factory):
        """Create a PKGDevicesDAO instance."""
        return PKGDevicesDAO(session_factory=mock_session_factory)
    
    @pytest.mark.asyncio
    async def test_get_device_versions(self, dao, mock_session_factory):
        """Test getting device versions."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        result = AsyncMock()
        row = Mock()
        row._mapping = {
            'device_id': 'door:D-1510',
            'device_type': 'door',
            'region': 'us-west',
            'snapshot_id': 1,
            'version': 'rules@1.4.0',
            'last_seen': datetime.now(),
            'snapshot_version': 'rules@1.4.0'
        }
        result.__iter__ = Mock(return_value=iter([row]))
        session.execute = AsyncMock(return_value=result)
        
        devices = await dao.get_device_versions(device_type='door')
        
        assert len(devices) == 1
        assert devices[0]['device_id'] == 'door:D-1510'
    
    @pytest.mark.asyncio
    async def test_update_device_heartbeat(self, dao, mock_session_factory):
        """Test updating device heartbeat."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        session.execute = AsyncMock()
        
        await dao.update_device_heartbeat(
            device_id='door:D-1510',
            device_type='door',
            snapshot_id=1,
            version='rules@1.4.0',
            region='us-west'
        )
        
        session.begin.assert_called()
        session.execute.assert_called()


class TestPKGIntegrity:
    """Tests for PKG integrity checks."""
    
    @pytest.fixture
    def mock_session_factory(self):
        """Create a mock session factory."""
        def _create_session():
            session = AsyncMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            return session
        return _create_session
    
    @pytest.mark.asyncio
    async def test_check_pkg_integrity_ok(self, mock_session_factory):
        """Test integrity check passing."""
        session = mock_session_factory()
        
        result = AsyncMock()
        row = SimpleNamespace(_mapping={'ok': True, 'msg': 'OK'})
        result.first = AsyncMock(return_value=row)
        session.execute = AsyncMock(return_value=result)
        
        integrity = await check_pkg_integrity(lambda: session)
        
        assert integrity['ok'] is True
        assert integrity['msg'] == 'OK'
    
    @pytest.mark.asyncio
    async def test_check_pkg_integrity_failed(self, mock_session_factory):
        """Test integrity check failing."""
        session = mock_session_factory()
        
        result = AsyncMock()
        row = SimpleNamespace(_mapping={'ok': False, 'msg': 'Cross-snapshot emission mismatch found'})
        result.first = AsyncMock(return_value=row)
        session.execute = AsyncMock(return_value=result)
        
        integrity = await check_pkg_integrity(lambda: session)
        
        assert integrity['ok'] is False
        assert 'mismatch' in integrity['msg']


class TestPKGCortexDAO:
    """Tests for PKGCortexDAO."""
    
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
    def dao(self, mock_session_factory):
        """Create a PKGCortexDAO instance."""
        return PKGCortexDAO(session_factory=mock_session_factory)
    
    @pytest.mark.asyncio
    async def test_get_semantic_context(self, dao, mock_session_factory):
        """Test getting semantic context from Unified Memory."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        result = AsyncMock()
        row1 = Mock()
        row1._mapping = {
            'id': 'task-123',
            'category': 'guest_request',
            'content': 'Guest wants room service',
            'memory_tier': 'TIER_1',
            'metadata': {},
            'similarity': 0.95
        }
        row2 = Mock()
        row2._mapping = {
            'id': 'task-456',
            'category': 'room_service',
            'content': 'Previous room service order',
            'memory_tier': 'TIER_2',
            'metadata': {},
            'similarity': 0.88
        }
        result.__iter__ = Mock(return_value=iter([row1, row2]))
        session.execute = AsyncMock(return_value=result)
        
        embedding = [0.1] * 1024  # 1024d embedding
        context = await dao.get_semantic_context(
            embedding=embedding,
            limit=5,
            min_similarity=0.8,
            exclude_task_id='task-999'
        )
        
        assert len(context) == 2
        assert context[0]['id'] == 'task-123'
        assert context[0]['similarity'] == 0.95
        session.execute.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_active_governed_facts(self, dao, mock_session_factory):
        """Test getting active PKG-governed facts."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        result = AsyncMock()
        row1 = Mock()
        row1._mapping = {
            'id': 'fact-uuid-1',
            'namespace': 'default',
            'subject': 'guest:Ben',
            'predicate': 'hasTemporaryAccess',
            'object_data': {'service': 'lounge'},
            'valid_from': datetime.now(),
            'valid_to': None,
            'pkg_rule_id': 'rule-001',
            'snapshot_id': 1,
            'created_at': datetime.now(),
            'created_by': 'system',
            'validation_status': 'validated'
        }
        row2 = Mock()
        row2._mapping = {
            'id': 'fact-uuid-2',
            'namespace': 'default',
            'subject': 'guest:Ben',
            'predicate': 'hasAllergen',
            'object_data': {'allergen': 'peanuts'},
            'valid_from': datetime.now(),
            'valid_to': None,
            'pkg_rule_id': 'rule-002',
            'snapshot_id': 1,
            'created_at': datetime.now(),
            'created_by': 'system',
            'validation_status': 'validated'
        }
        result.__iter__ = Mock(return_value=iter([row1, row2]))
        session.execute = AsyncMock(return_value=result)
        
        facts = await dao.get_active_governed_facts(
            snapshot_id=1,
            namespace='default',
            subject='guest:Ben',
            limit=100
        )
        
        assert len(facts) == 2
        assert facts[0]['subject'] == 'guest:Ben'
        assert facts[0]['predicate'] == 'hasTemporaryAccess'
        assert facts[0]['pkg_rule_id'] == 'rule-001'
        assert facts[0]['snapshot_id'] == 1
        session.execute.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_active_governed_facts_with_predicate_filter(self, dao, mock_session_factory):
        """Test getting active governed facts with predicate filter."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        result = AsyncMock()
        row = Mock()
        row._mapping = {
            'id': 'fact-uuid-1',
            'namespace': 'default',
            'subject': 'guest:Ben',
            'predicate': 'hasTemporaryAccess',
            'object_data': {'service': 'lounge'},
            'valid_from': datetime.now(),
            'valid_to': None,
            'pkg_rule_id': 'rule-001',
            'snapshot_id': 1,
            'created_at': datetime.now(),
            'created_by': 'system',
            'validation_status': 'validated'
        }
        result.__iter__ = Mock(return_value=iter([row]))
        session.execute = AsyncMock(return_value=result)
        
        facts = await dao.get_active_governed_facts(
            snapshot_id=1,
            namespace='default',
            subject='guest:Ben',
            predicate='hasTemporaryAccess',
            limit=100
        )
        
        assert len(facts) == 1
        assert facts[0]['predicate'] == 'hasTemporaryAccess'
        session.execute.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_active_governed_facts_empty(self, dao, mock_session_factory):
        """Test getting active governed facts when none exist."""
        session = mock_session_factory()
        dao._sf = lambda: session
        
        result = AsyncMock()
        result.__iter__ = Mock(return_value=iter([]))
        session.execute = AsyncMock(return_value=result)
        
        facts = await dao.get_active_governed_facts(
            snapshot_id=1,
            namespace='default'
        )
        
        assert len(facts) == 0
        session.execute.assert_called_once()

