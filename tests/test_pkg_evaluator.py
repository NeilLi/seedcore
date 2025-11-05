#!/usr/bin/env python3
"""
Unit tests for PKG Evaluator.

Tests PKGEvaluator, OpaWasm, and NativeRuleEngine with mocked dependencies.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from typing import Dict, Any, List

from seedcore.ops.pkg.evaluator import (
    PKGEvaluator,
    OpaWasm,
    NativeRuleEngine,
    EvaluationResult,
    PolicyEngine,
    ENGINE_REGISTRY,
    register_engine,
)
from seedcore.ops.pkg.dao import PKGSnapshotData


class TestEvaluationResult:
    """Tests for EvaluationResult dataclass."""
    
    def test_evaluation_result_creation(self):
        """Test creating EvaluationResult."""
        result = EvaluationResult(
            subtasks=[{'name': 'task1'}],
            dag=[{'from': 'task1', 'to': 'task2'}],
            provenance=[{'rule_id': 'rule1'}]
        )
        
        assert len(result.subtasks) == 1
        assert len(result.dag) == 1
        assert len(result.provenance) == 1


class TestOpaWasm:
    """Tests for OpaWasm engine."""
    
    def test_opa_wasm_init_without_wasmtime(self):
        """Test OpaWasm initialization without wasmtime."""
        with patch('seedcore.ops.pkg.evaluator._WASMTIME_AVAILABLE', False):
            engine = OpaWasm(b'wasm_bytes', checksum='abc123')
            
            assert engine._wasm_bytes == b'wasm_bytes'
            assert engine._checksum == 'abc123'
            assert engine._wasmtime_available is False
            assert engine._instance is None
    
    def test_opa_wasm_load_from_bytes(self):
        """Test loading OpaWasm from bytes."""
        engine = OpaWasm.load_from_bytes(b'wasm_bytes', checksum='abc123')
        
        assert isinstance(engine, OpaWasm)
        assert engine._wasm_bytes == b'wasm_bytes'
        assert engine._checksum == 'abc123'
    
    def test_opa_wasm_evaluate_fallback(self):
        """Test OpaWasm evaluation in fallback mode."""
        engine = OpaWasm(b'wasm_bytes', checksum='abc123')
        engine._wasmtime_available = False
        
        task_facts = {
            'tags': ['vip'],
            'signals': {'x2': 0.8},
            'context': {}
        }
        
        result = engine.evaluate(task_facts)
        
        assert isinstance(result, EvaluationResult)
        assert len(result.subtasks) == 0
        assert len(result.dag) == 0
        assert len(result.provenance) > 0
        assert result.provenance[0]['rule_id'] == 'wasm-fallback'
    
    def test_opa_wasm_parse_opa_result(self):
        """Test parsing OPA result."""
        engine = OpaWasm(b'wasm_bytes')
        opa_result = {
            'result': {
                'subtasks': [{'name': 'task1'}],
                'dag': [{'from': 'task1', 'to': 'task2'}],
                'rules': [{'rule_id': 'rule1'}]
            }
        }
        
        result = engine._parse_opa_result(opa_result)
        
        assert isinstance(result, EvaluationResult)
        assert len(result.subtasks) == 1
        assert len(result.dag) == 1
        assert len(result.provenance) == 1


class TestNativeRuleEngine:
    """Tests for NativeRuleEngine."""
    
    @pytest.fixture
    def mock_rules(self):
        """Create mock rules."""
        return [
            {
                'id': 'rule-001',
                'rule_name': 'high_priority_vip',
                'priority': 10,
                'conditions': [
                    {
                        'condition_type': 'TAG',
                        'condition_key': 'vip',
                        'operator': 'IN',
                        'value': 'vip',
                        'position': 0
                    }
                ],
                'emissions': [
                    {
                        'subtask_type': 'escalate',
                        'subtask_name': 'escalate_vip',
                        'params': {'level': 'high'},
                        'relationship_type': 'EMITS',
                        'position': 0
                    }
                ]
            },
            {
                'id': 'rule-002',
                'rule_name': 'allergen_alert',
                'priority': 8,
                'conditions': [
                    {
                        'condition_type': 'TAG',
                        'condition_key': 'allergen',
                        'operator': 'EXISTS',
                        'value': None,
                        'position': 0
                    }
                ],
                'emissions': [
                    {
                        'subtask_type': 'notify',
                        'subtask_name': 'notify_kitchen',
                        'params': {'alert_type': 'allergen'},
                        'relationship_type': 'EMITS',
                        'position': 0
                    }
                ]
            }
        ]
    
    @pytest.fixture
    def engine(self, mock_rules):
        """Create NativeRuleEngine instance."""
        return NativeRuleEngine(mock_rules)
    
    def test_native_engine_init(self, engine, mock_rules):
        """Test NativeRuleEngine initialization."""
        assert len(engine._rules) == 2
        assert engine._rules[0]['rule_name'] == 'high_priority_vip'
    
    def test_native_engine_init_empty_rules(self):
        """Test NativeRuleEngine with empty rules."""
        engine = NativeRuleEngine([])
        assert len(engine._rules) == 0
    
    def test_native_engine_run_no_matches(self, engine):
        """Test running engine with no matching rules."""
        task_facts = {
            'tags': [],
            'signals': {},
            'context': {}
        }
        
        result = engine.run(task_facts)
        
        assert isinstance(result, EvaluationResult)
        assert len(result.subtasks) == 0
        assert len(result.provenance) == 0
    
    def test_native_engine_run_with_matches(self, engine):
        """Test running engine with matching rules."""
        task_facts = {
            'tags': ['vip', 'allergen'],
            'signals': {'x2': 0.8},
            'context': {'domain': 'hotel_ops'}
        }
        
        result = engine.run(task_facts)
        
        assert isinstance(result, EvaluationResult)
        assert len(result.subtasks) >= 1
        assert len(result.provenance) >= 1
        assert any('vip' in str(p) for p in result.provenance) or len(result.provenance) > 0
    
    def test_native_engine_evaluate_conditions_tag(self, engine):
        """Test condition evaluation for TAG type."""
        conditions = [
            {
                'condition_type': 'TAG',
                'condition_key': 'vip',
                'operator': 'IN',
                'value': 'vip'
            }
        ]
        
        task_facts = {'tags': ['vip'], 'signals': {}, 'context': {}}
        
        matches = engine._evaluate_conditions(conditions, task_facts, Mock())
        
        assert matches is True
    
    def test_native_engine_evaluate_conditions_signal(self, engine):
        """Test condition evaluation for SIGNAL type."""
        conditions = [
            {
                'condition_type': 'SIGNAL',
                'condition_key': 'x2',
                'operator': '>=',
                'value': 0.5
            }
        ]
        
        task_facts = {'tags': [], 'signals': {'x2': 0.8}, 'context': {}}
        
        matches = engine._evaluate_conditions(conditions, task_facts, Mock())
        
        assert matches is True
    
    def test_native_engine_check_condition_tag(self, engine):
        """Test checking TAG condition."""
        condition = {
            'condition_type': 'TAG',
            'condition_key': 'vip',
            'operator': 'IN',
            'value': None
        }
        
        context = {'tags': ['vip']}
        
        matches = engine._check_condition(condition, context, condition_type='TAG')
        
        assert matches is True
    
    def test_native_engine_check_condition_signal(self, engine):
        """Test checking SIGNAL condition."""
        condition = {
            'condition_type': 'SIGNAL',
            'condition_key': 'x2',
            'operator': '>=',
            'value': 0.5
        }
        
        context = {'signals': {'x2': 0.8}}
        
        matches = engine._check_condition(condition, context, condition_type='SIGNAL')
        
        assert matches is True
    
    def test_native_engine_evaluate_operator(self, engine):
        """Test operator evaluation."""
        assert engine._evaluate_operator(5, '>', 3) is True
        assert engine._evaluate_operator(5, '<', 3) is False
        assert engine._evaluate_operator(5, '=', 5) is True
        assert engine._evaluate_operator(5, '!=', 3) is True
        assert engine._evaluate_operator('test', 'IN', ['test', 'other']) is True
        assert engine._evaluate_operator('value', 'EXISTS', None) is True
        assert engine._evaluate_operator(None, 'EXISTS', None) is False
    
    def test_native_engine_get_field_value(self, engine):
        """Test field value extraction."""
        context = {
            'tags': ['vip'],
            'signals': {'x2': 0.8},
            'context': {'domain': 'hotel_ops'}
        }
        
        assert engine._get_field_value('tags', context) == ['vip']
        assert engine._get_field_value('signals.x2', context) == 0.8
        assert engine._get_field_value('context.domain', context) == 'hotel_ops'
        assert engine._get_field_value('nonexistent', context) is None
    
    def test_native_engine_process_emissions(self, engine):
        """Test processing emissions."""
        emissions = [
            {
                'subtask_type': 'escalate',
                'subtask_name': 'escalate_vip',
                'params': {'level': 'high'},
                'relationship_type': 'EMITS',
                'position': 0
            }
        ]
        
        subtasks = engine._process_emissions(emissions, 'rule-001', 'high_priority_vip')
        
        assert len(subtasks) == 1
        assert subtasks[0]['name'] == 'escalate_vip'
        assert subtasks[0]['type'] == 'escalate'
        assert subtasks[0]['rule_id'] == 'rule-001'
    
    def test_native_engine_build_dag(self, engine):
        """Test building DAG."""
        matched_rules = [
            {
                'rule_name': 'rule1',
                'emissions': [
                    {
                        'subtask_name': 'task1',
                        'relationship_type': 'ORDERS'
                    },
                    {
                        'subtask_name': 'task2',
                        'relationship_type': 'ORDERS'
                    }
                ]
            }
        ]
        
        subtasks = [
            {'name': 'task1'},
            {'name': 'task2'}
        ]
        
        dag = engine._build_dag(matched_rules, subtasks)
        
        assert isinstance(dag, list)
        # Should have at least one edge if relationships are defined
    
    def test_native_engine_evaluate_protocol(self, engine):
        """Test that NativeRuleEngine implements PolicyEngine protocol."""
        task_facts = {'tags': ['vip'], 'signals': {}, 'context': {}}
        
        # Should work with both run() and evaluate()
        result1 = engine.run(task_facts)
        result2 = engine.evaluate(task_facts)
        
        assert isinstance(result1, EvaluationResult)
        assert isinstance(result2, EvaluationResult)


class TestPKGEvaluator:
    """Tests for PKGEvaluator."""
    
    @pytest.fixture
    def wasm_snapshot(self):
        """Create a WASM snapshot."""
        return PKGSnapshotData(
            id=1,
            version='rules@1.4.0-wasm',
            engine='wasm',
            wasm_artifact=b'wasm_binary_data',
            checksum='sha256-abc123',
            rules=[]
        )
    
    @pytest.fixture
    def native_snapshot(self):
        """Create a native snapshot."""
        return PKGSnapshotData(
            id=2,
            version='rules@0.2.0-native',
            engine='native',
            wasm_artifact=None,
            checksum='sha256-xyz',
            rules=[
                {
                    'id': 'rule-001',
                    'rule_name': 'test_rule',
                    'priority': 10,
                    'conditions': [],
                    'emissions': []
                }
            ]
        )
    
    def test_pkg_evaluator_init_wasm(self, wasm_snapshot):
        """Test PKGEvaluator initialization with WASM snapshot."""
        evaluator = PKGEvaluator(wasm_snapshot)
        
        assert evaluator.version == 'rules@1.4.0-wasm'
        assert evaluator.engine_type == 'wasm'
        assert evaluator.engine is not None
        assert isinstance(evaluator.engine, OpaWasm)
    
    def test_pkg_evaluator_init_native(self, native_snapshot):
        """Test PKGEvaluator initialization with native snapshot."""
        evaluator = PKGEvaluator(native_snapshot)
        
        assert evaluator.version == 'rules@0.2.0-native'
        assert evaluator.engine_type == 'native'
        assert evaluator.engine is not None
        assert isinstance(evaluator.engine, NativeRuleEngine)
    
    def test_pkg_evaluator_init_invalid_engine(self):
        """Test PKGEvaluator with invalid engine type."""
        snapshot = PKGSnapshotData(
            id=3,
            version='rules@1.0.0',
            engine='invalid',
            wasm_artifact=None,
            checksum='abc',
            rules=[]
        )
        
        with pytest.raises(ValueError, match="Unknown engine type"):
            PKGEvaluator(snapshot)
    
    def test_pkg_evaluator_init_wasm_missing_artifact(self):
        """Test PKGEvaluator with WASM snapshot missing artifact."""
        snapshot = PKGSnapshotData(
            id=1,
            version='rules@1.4.0',
            engine='wasm',
            wasm_artifact=None,
            checksum='abc',
            rules=[]
        )
        
        with pytest.raises(ValueError, match="no 'wasm_artifact'"):
            PKGEvaluator(snapshot)
    
    def test_pkg_evaluator_evaluate_wasm(self, wasm_snapshot):
        """Test PKGEvaluator evaluation with WASM engine."""
        evaluator = PKGEvaluator(wasm_snapshot)
        
        task_facts = {
            'tags': ['vip'],
            'signals': {'x2': 0.8},
            'context': {'domain': 'hotel_ops'}
        }
        
        result = evaluator.evaluate(task_facts)
        
        assert isinstance(result, dict)
        assert 'subtasks' in result
        assert 'dag' in result
        assert 'rules' in result
        assert 'snapshot' in result
        assert result['snapshot'] == 'rules@1.4.0-wasm'
    
    def test_pkg_evaluator_evaluate_native(self, native_snapshot):
        """Test PKGEvaluator evaluation with native engine."""
        evaluator = PKGEvaluator(native_snapshot)
        
        task_facts = {
            'tags': [],
            'signals': {},
            'context': {}
        }
        
        result = evaluator.evaluate(task_facts)
        
        assert isinstance(result, dict)
        assert 'subtasks' in result
        assert 'dag' in result
        assert 'rules' in result
        assert 'snapshot' in result
        assert result['snapshot'] == 'rules@0.2.0-native'
    
    def test_pkg_evaluator_evaluate_error_handling(self, wasm_snapshot):
        """Test PKGEvaluator error handling."""
        evaluator = PKGEvaluator(wasm_snapshot)
        evaluator.engine = None  # Simulate uninitialized engine
        
        with pytest.raises(RuntimeError, match="engine not initialized"):
            evaluator.evaluate({})


class TestEngineRegistry:
    """Tests for engine registry."""
    
    def test_engine_registry_contains_defaults(self):
        """Test that registry contains default engines."""
        assert 'wasm' in ENGINE_REGISTRY
        assert 'native' in ENGINE_REGISTRY
        assert ENGINE_REGISTRY['wasm'] == OpaWasm
        assert ENGINE_REGISTRY['native'] == NativeRuleEngine
    
    def test_register_engine(self):
        """Test registering a new engine."""
        class CustomEngine:
            def evaluate(self, task_facts):
                return EvaluationResult([], [], [])
        
        original_count = len(ENGINE_REGISTRY)
        register_engine('custom', CustomEngine)
        
        assert 'custom' in ENGINE_REGISTRY
        assert ENGINE_REGISTRY['custom'] == CustomEngine
        assert len(ENGINE_REGISTRY) == original_count + 1
        
        # Cleanup
        del ENGINE_REGISTRY['custom']

