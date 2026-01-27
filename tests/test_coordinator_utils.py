"""
Unit tests for coordinator.utils module.

Tests utility functions for task normalization, redaction, extraction, and data processing.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import uuid
import pytest
from unittest.mock import Mock, MagicMock
from seedcore.coordinator.utils import (
    sync_task_identity,
    normalize_task_dict,
    convert_task_to_dict,
    canonicalize_identifier,
    redact_sensitive_data,
    extract_from_nested,
    extract_proto_plan,
    extract_decision,
    extract_dependency_token,
    normalize_string,
    normalize_domain,
    normalize_type,
    collect_record_aliases,
    collect_step_aliases,
    resolve_child_task_id,
    iter_dependency_entries,
)
from seedcore.models import TaskPayload


class TestSyncTaskIdentity:
    """Tests for sync_task_identity function."""
    
    def test_sync_dict_with_id(self):
        """Test syncing identity to a dictionary."""
        task = {"type": "test"}
        sync_task_identity(task, "test-id-123")
        assert task["id"] == "test-id-123"
    
    def test_sync_dict_with_existing_id(self):
        """Test syncing identity overwrites existing id."""
        task = {"id": "old-id", "type": "test"}
        sync_task_identity(task, "new-id-123")
        assert task["id"] == "new-id-123"
    
    def test_sync_object_with_id_attr(self):
        """Test syncing identity to an object with id attribute."""
        task = Mock()
        task.id = None
        sync_task_identity(task, "test-id-123")
        assert task.id == "test-id-123"
    
    def test_sync_object_with_task_id_attr(self):
        """Test syncing identity to an object with task_id attribute."""
        task = Mock()
        task.task_id = None
        sync_task_identity(task, "test-id-123")
        assert task.task_id == "test-id-123"


class TestConvertTaskToDict:
    """Tests for convert_task_to_dict function."""
    
    def test_convert_dict(self):
        """Test converting a dictionary (should return copy)."""
        task = {"id": "123", "type": "test"}
        result = convert_task_to_dict(task)
        assert result == task
        assert result is not task  # Should be a copy
    
    def test_convert_pydantic_model(self):
        """Test converting a Pydantic model."""
        task = TaskPayload(
            type="test",
            task_id="123",
            description="test task"
        )
        result = convert_task_to_dict(task)
        assert result["type"] == "test"
        assert result["task_id"] == "123"  # TaskPayload uses task_id, not id
        assert result["description"] == "test task"
    
    def test_convert_object_with_dict(self):
        """Test converting an object with __dict__."""
        class TaskObj:
            def __init__(self):
                self.id = "123"
                self.type = "test"
        
        task = TaskObj()
        result = convert_task_to_dict(task)
        assert result["id"] == "123"
        assert result["type"] == "test"
    
    def test_convert_unknown_type(self):
        """Test converting unknown type returns empty dict."""
        result = convert_task_to_dict("not a task")
        assert result == {}


class TestNormalizeTaskDict:
    """Tests for normalize_task_dict function."""
    
    def test_normalize_dict_with_id(self):
        """Test normalizing a dict with existing id."""
        task = {"id": "123", "type": "test"}
        task_id, task_dict = normalize_task_dict(task)
        assert str(task_id) == "123"
        assert task_dict["id"] == "123"
    
    def test_normalize_dict_with_task_id(self):
        """Test normalizing a dict with task_id."""
        task = {"task_id": "123", "type": "test"}
        task_id, task_dict = normalize_task_dict(task)
        assert str(task_id) == "123"
        assert task_dict["id"] == "123"
    
    def test_normalize_dict_generates_id(self):
        """Test normalizing a dict without id generates UUID."""
        task = {"type": "test"}
        task_id, task_dict = normalize_task_dict(task)
        assert isinstance(task_id, uuid.UUID)
        assert task_dict["id"] == str(task_id)
    
    def test_normalize_pydantic_model(self):
        """Test normalizing a Pydantic model."""
        task = TaskPayload(type="test", task_id="123")
        task_id, task_dict = normalize_task_dict(task)
        assert str(task_id) == "123"
        assert task_dict["id"] == "123"


class TestCanonicalizeIdentifier:
    """Tests for canonicalize_identifier function."""
    
    def test_canonicalize_uuid(self):
        """Test canonicalizing a UUID."""
        test_uuid = uuid.uuid4()
        result = canonicalize_identifier(test_uuid)
        assert result == str(test_uuid)
    
    def test_canonicalize_string(self):
        """Test canonicalizing a string."""
        result = canonicalize_identifier("test-id")
        assert result == "test-id"
    
    def test_canonicalize_int(self):
        """Test canonicalizing an integer."""
        result = canonicalize_identifier(123)
        assert result == "123"
    
    def test_canonicalize_float(self):
        """Test canonicalizing a float."""
        result = canonicalize_identifier(123.0)
        assert result == "123"
    
    def test_canonicalize_bool(self):
        """Test canonicalizing a boolean."""
        assert canonicalize_identifier(True) == "True"
        assert canonicalize_identifier(False) == "False"
    
    def test_canonicalize_none(self):
        """Test canonicalizing None."""
        result = canonicalize_identifier(None)
        assert result == ""


class TestRedactSensitiveData:
    """Tests for redact_sensitive_data function."""
    
    def test_redact_password(self):
        """Test redacting password fields."""
        data = {"username": "user", "password": "secret123"}
        result = redact_sensitive_data(data)
        assert result["username"] == "user"
        assert result["password"] == "[REDACTED]"
    
    def test_redact_token(self):
        """Test redacting token fields."""
        data = {"token": "abc123", "api_key": "xyz789"}
        result = redact_sensitive_data(data)
        assert result["token"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"
    
    def test_redact_nested(self):
        """Test redacting nested structures."""
        data = {
            "user": {
                "name": "John",
                "password": "secret"
            },
            "auth": {
                "token": "abc123"
            }
        }
        result = redact_sensitive_data(data)
        assert result["user"]["name"] == "John"
        assert result["user"]["password"] == "[REDACTED]"
        assert result["auth"]["token"] == "[REDACTED]"
    
    def test_redact_list(self):
        """Test redacting list items."""
        data = [{"password": "secret1"}, {"password": "secret2"}]
        result = redact_sensitive_data(data)
        assert result[0]["password"] == "[REDACTED]"
        assert result[1]["password"] == "[REDACTED]"
    
    def test_redact_non_dict_list(self):
        """Test redacting non-dict/list returns as-is."""
        long_string = "a" * 2000
        result = redact_sensitive_data(long_string)
        assert result == long_string  # Strings are returned as-is


class TestExtractFromNested:
    """Tests for extract_from_nested function."""
    
    def test_extract_simple_path(self):
        """Test extracting from simple path."""
        data = {"payload": {"decision": "fast"}}
        result = extract_from_nested(
            data,
            [("payload", "decision")],
            str
        )
        assert result == "fast"
    
    def test_extract_multiple_paths(self):
        """Test extracting from multiple paths (first match wins)."""
        data = {"payload": {"metadata": {"decision": "planner"}}}
        result = extract_from_nested(
            data,
            [("payload", "metadata", "decision"), ("payload", "decision")],
            str
        )
        assert result == "planner"
    
    def test_extract_with_type_check(self):
        """Test extracting with type constraint."""
        data = {"payload": {"decision": "fast"}}
        result = extract_from_nested(
            data,
            [("payload", "decision")],
            str
        )
        assert result == "fast"
        
        # Should return None if type doesn't match
        result = extract_from_nested(
            data,
            [("payload", "decision")],
            dict
        )
        assert result is None
    
    def test_extract_nonexistent_path(self):
        """Test extracting from nonexistent path."""
        data = {"payload": {}}
        result = extract_from_nested(
            data,
            [("payload", "decision")],
            str
        )
        assert result is None


class TestExtractProtoPlan:
    """Tests for extract_proto_plan function."""
    
    def test_extract_from_metadata(self):
        """Test extracting proto_plan from metadata."""
        data = {"metadata": {"proto_plan": {"steps": 3}}}
        result = extract_proto_plan(data)
        assert result == {"steps": 3}
    
    def test_extract_from_top_level(self):
        """Test extracting proto_plan from top level."""
        data = {"proto_plan": {"steps": 3}}
        result = extract_proto_plan(data)
        assert result == {"steps": 3}
    
    def test_extract_nonexistent(self):
        """Test extracting when proto_plan doesn't exist."""
        data = {"payload": {}}
        result = extract_proto_plan(data)
        assert result is None


class TestExtractDecision:
    """Tests for extract_decision function."""
    
    def test_extract_from_metadata(self):
        """Test extracting decision from metadata."""
        data = {"payload": {"metadata": {"decision": "fast"}}}
        result = extract_decision(data)
        assert result == "fast"
    
    def test_extract_from_payload(self):
        """Test extracting decision from payload."""
        data = {"payload": {"decision": "planner"}}
        result = extract_decision(data)
        assert result == "planner"
    
    def test_extract_from_top_level(self):
        """Test extracting decision from top level."""
        data = {"decision": "hgnn"}
        result = extract_decision(data)
        assert result == "hgnn"
    
    def test_extract_nonexistent(self):
        """Test extracting when decision doesn't exist."""
        data = {"payload": {}}
        result = extract_decision(data)
        assert result is None


class TestNormalizeString:
    """Tests for normalize_string function."""
    
    def test_normalize_lowercase(self):
        """Test normalizing string to lowercase."""
        assert normalize_string("TEST") == "test"
        assert normalize_string("Test String") == "test string"
    
    def test_normalize_strip_whitespace(self):
        """Test normalizing string strips whitespace."""
        assert normalize_string("  test  ") == "test"
    
    def test_normalize_none(self):
        """Test normalizing None."""
        assert normalize_string(None) is None


class TestNormalizeDomain:
    """Tests for normalize_domain function."""
    
    def test_normalize_standard_domain(self):
        """Test normalizing standard domain."""
        assert normalize_domain("hospitality") == "hospitality"
    
    def test_normalize_domain_alias(self):
        """Test normalizing domain alias."""
        assert normalize_domain("hotel") == "hospitality"
        assert normalize_domain("admin") == "management"  # "admin" maps to "management"
        assert normalize_domain("ops") == "operations"
        assert normalize_domain("mgmt") == "mgmt"  # Not in aliases, returns as-is
    
    def test_normalize_domain_none(self):
        """Test normalizing None domain."""
        assert normalize_domain(None) is None
    
    def test_normalize_domain_case_insensitive(self):
        """Test normalizing domain is case insensitive."""
        assert normalize_domain("HOTEL") == "hospitality"
        assert normalize_domain("  hotel  ") == "hospitality"


class TestNormalizeType:
    """Tests for normalize_type function."""
    
    def test_normalize_standard_type(self):
        """Test normalizing standard type."""
        # TaskType enum values
        assert normalize_type("query") == "query"
        assert normalize_type("action") == "action"
    
    def test_normalize_type_alias(self):
        """Test normalizing type alias."""
        assert normalize_type("anomaly_triage") == "query"  # Maps to TaskType.QUERY.value
        assert normalize_type("execute") == "action"  # Maps to TaskType.ACTION.value
        assert normalize_type("embed") == "graph"  # Maps to TaskType.GRAPH.value
        assert normalize_type("anomaly") == "anomaly"  # Not in type_map, returns as-is
        assert normalize_type("exec") == "exec"  # Not in type_map, returns as-is
    
    def test_normalize_type_none(self):
        """Test normalizing None type."""
        assert normalize_type(None) == "unknown"
    
    def test_normalize_type_case_insensitive(self):
        """Test normalizing type is case insensitive."""
        assert normalize_type("ANOMALY_TRIAGE") == "query"  # Maps to TaskType.QUERY.value
        assert normalize_type("EXECUTE") == "action"  # Maps to TaskType.ACTION.value


class TestExtractDependencyToken:
    """Tests for extract_dependency_token function."""
    
    def test_extract_from_dict(self):
        """Test extracting token from dictionary."""
        # The function requires string IDs with len > 5, so use a longer ID
        ref = {"task_id": "123456"}
        result = extract_dependency_token(ref)
        assert result == "123456"
    
    def test_extract_from_list(self):
        """Test extracting token from list."""
        # The function requires string IDs with len > 5
        ref = [{"task_id": "123456"}]
        result = extract_dependency_token(ref)
        assert result == "123456"
    
    def test_extract_from_object(self):
        """Test extracting token from object."""
        # The function requires string IDs with len > 5
        obj = Mock()
        obj.task_id = "123456"
        result = extract_dependency_token(obj)
        assert result == "123456"
    
    def test_extract_none(self):
        """Test extracting from None."""
        result = extract_dependency_token(None)
        assert result is None
    
    def test_extract_circular_reference(self):
        """Test extracting handles circular references."""
        # The function requires string IDs with len > 5
        ref = {"task_id": "123456"}
        ref["self"] = ref  # Create circular reference
        result = extract_dependency_token(ref)
        assert result == "123456"  # Should still extract the task_id


class TestCollectAliases:
    """Tests for alias collection functions."""
    
    def test_collect_record_aliases(self):
        """Test collecting aliases from record."""
        record = {"task_id": "123", "metadata": {"id": "456"}}
        aliases = collect_record_aliases(record)
        assert "123" in aliases
        assert "456" in aliases
    
    def test_collect_step_aliases(self):
        """Test collecting aliases from step."""
        step = {"step_id": "789", "task": {"task_id": "123"}}
        aliases = collect_step_aliases(step)
        assert "789" in aliases
        assert "123" in aliases


class TestResolveChildTaskId:
    """Tests for resolve_child_task_id function."""
    
    def test_resolve_from_record(self):
        """Test resolving child task id from record."""
        # extract_dependency_token requires string IDs with len > 5
        record = {"task_id": "123456"}
        result = resolve_child_task_id(record, None)
        assert result == "123456"
    
    def test_resolve_from_fallback(self):
        """Test resolving child task id from fallback."""
        # extract_dependency_token requires string IDs with len > 5
        # It only searches for: task_id, id, parent_task_id, child_task_id
        result = resolve_child_task_id(None, {"task_id": "789012"})
        assert result == "789012"
    
    def test_resolve_none(self):
        """Test resolving when neither record nor fallback has id."""
        result = resolve_child_task_id(None, {})
        assert result is None


class TestIterDependencyEntries:
    """Tests for iter_dependency_entries function."""
    
    def test_iter_list(self):
        """Test iterating over list."""
        deps = [{"task_id": "1"}, {"task_id": "2"}]
        entries = list(iter_dependency_entries(deps))
        assert len(entries) == 2
    
    def test_iter_nested_list(self):
        """Test iterating over nested list."""
        deps = [[{"task_id": "1"}], [{"task_id": "2"}]]
        entries = list(iter_dependency_entries(deps))
        assert len(entries) == 2
    
    def test_iter_none(self):
        """Test iterating over None."""
        entries = list(iter_dependency_entries(None))
        assert len(entries) == 0

