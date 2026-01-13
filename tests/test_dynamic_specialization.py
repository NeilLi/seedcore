#!/usr/bin/env python3
"""
Comprehensive pytest tests for the Dynamic Specialization System.

Tests cover:
- Thread-safety of SpecializationManager
- YAML persistence (load/save)
- Backward compatibility with static Specialization enum
- Dynamic registration and lookup
- RoleProfile integration
- E/S/O mapping for dynamic specializations
"""

import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from seedcore.agents.roles import specialization as spec_module
from seedcore.agents.roles.specialization import (
    Specialization,
    DynamicSpecialization,
    SpecializationManager,
    RoleProfile,
    RoleRegistry,
    get_specialization,
    register_specialization,
    ROLE_KEYS,
)

# Check if YAML is available
HAS_YAML = getattr(spec_module, 'HAS_YAML', False)


class TestDynamicSpecialization:
    """Test DynamicSpecialization class behavior."""
    
    def test_creation(self):
        """Test creating a DynamicSpecialization."""
        spec = DynamicSpecialization("custom_agent_v2", "Custom Agent V2")
        assert spec.value == "custom_agent_v2"
        assert spec.name == "Custom Agent V2"
        assert spec.metadata == {}
    
    def test_creation_with_metadata(self):
        """Test creating with metadata."""
        metadata = {"category": "custom", "version": "2.0"}
        spec = DynamicSpecialization("test_spec", metadata=metadata)
        assert spec.metadata == metadata
    
    def test_value_normalization(self):
        """Test that values are normalized to lowercase."""
        spec = DynamicSpecialization("UPPERCASE_SPEC")
        assert spec.value == "uppercase_spec"
    
    def test_equality_with_enum(self):
        """Test equality comparison with Specialization enum."""
        spec = DynamicSpecialization("generalist")
        assert spec == Specialization.GENERALIST
        assert Specialization.GENERALIST == spec
    
    def test_equality_with_string(self):
        """Test equality comparison with strings."""
        spec = DynamicSpecialization("custom_agent")
        assert spec == "custom_agent"
        assert spec == "CUSTOM_AGENT"  # Case-insensitive
        assert spec == "Custom_Agent"
    
    def test_equality_between_dynamic(self):
        """Test equality between two DynamicSpecialization instances."""
        spec1 = DynamicSpecialization("test_spec")
        spec2 = DynamicSpecialization("TEST_SPEC")
        assert spec1 == spec2
    
    def test_hash(self):
        """Test hashing for use in sets/dicts."""
        spec1 = DynamicSpecialization("test_spec")
        spec2 = DynamicSpecialization("TEST_SPEC")
        assert hash(spec1) == hash(spec2)
        
        # Can be used in sets
        spec_set = {spec1, spec2}
        assert len(spec_set) == 1
    
    def test_ordering(self):
        """Test ordering for sorting."""
        spec1 = DynamicSpecialization("a_spec")
        spec2 = DynamicSpecialization("b_spec")
        assert spec1 < spec2
        assert sorted([spec2, spec1]) == [spec1, spec2]
    
    def test_repr(self):
        """Test string representation."""
        spec = DynamicSpecialization("test_spec", "Test Spec")
        repr_str = repr(spec)
        assert "DynamicSpecialization" in repr_str
        assert "test_spec" in repr_str
        assert "Test Spec" in repr_str


class TestSpecializationManager:
    """Test SpecializationManager singleton and functionality."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        # Clear singleton instance
        SpecializationManager._instance = None
    
    def test_singleton_pattern(self):
        """Test that get_instance returns the same instance."""
        manager1 = SpecializationManager.get_instance()
        manager2 = SpecializationManager.get_instance()
        assert manager1 is manager2
    
    def test_register_dynamic(self):
        """Test registering a dynamic specialization."""
        manager = SpecializationManager.get_instance()
        spec = manager.register_dynamic("custom_agent_v2", "Custom Agent V2")
        
        assert isinstance(spec, DynamicSpecialization)
        assert spec.value == "custom_agent_v2"
        assert spec.name == "Custom Agent V2"
        assert manager.is_registered("custom_agent_v2")
        assert manager.is_dynamic("custom_agent_v2")
    
    def test_register_with_role_profile(self):
        """Test registering with a RoleProfile."""
        manager = SpecializationManager.get_instance()
        profile = RoleProfile(
            name=DynamicSpecialization("test_spec"),  # Temporary for profile
            default_skills={"skill1": 0.8},
            allowed_tools={"tool1", "tool2"},
        )
        
        spec = manager.register_dynamic(
            "test_spec",
            role_profile=profile
        )
        
        retrieved_profile = manager.get_role_profile(spec)
        assert retrieved_profile is not None
        assert retrieved_profile.default_skills == {"skill1": 0.8}
        assert retrieved_profile.allowed_tools == {"tool1", "tool2"}
    
    def test_register_conflicts_with_static(self):
        """Test that registering conflicts with static enum raises error."""
        manager = SpecializationManager.get_instance()
        
        with pytest.raises(ValueError, match="conflicts with static"):
            manager.register_dynamic("generalist")  # Conflicts with Specialization.GENERALIST
    
    def test_get_static_specialization(self):
        """Test getting static specializations."""
        manager = SpecializationManager.get_instance()
        spec = manager.get("generalist")
        assert isinstance(spec, Specialization)
        assert spec == Specialization.GENERALIST
    
    def test_get_dynamic_specialization(self):
        """Test getting dynamic specializations."""
        manager = SpecializationManager.get_instance()
        manager.register_dynamic("custom_spec")
        
        spec = manager.get("custom_spec")
        assert isinstance(spec, DynamicSpecialization)
        assert spec.value == "custom_spec"
    
    def test_get_case_insensitive(self):
        """Test that get() is case-insensitive."""
        manager = SpecializationManager.get_instance()
        manager.register_dynamic("CustomSpec")
        
        # All these should work
        assert manager.get("customspec") is not None
        assert manager.get("CUSTOMSPEC") is not None
        assert manager.get("CustomSpec") is not None
    
    def test_get_not_found(self):
        """Test that get() raises KeyError for unknown specializations."""
        manager = SpecializationManager.get_instance()
        
        with pytest.raises(KeyError):
            manager.get("nonexistent_spec")
    
    def test_get_safe(self):
        """Test get_safe() returns None for unknown specializations."""
        manager = SpecializationManager.get_instance()
        
        assert manager.get_safe("nonexistent_spec") is None
        assert manager.get_safe("generalist") == Specialization.GENERALIST
    
    def test_is_registered(self):
        """Test is_registered() for both static and dynamic."""
        manager = SpecializationManager.get_instance()
        
        assert manager.is_registered("generalist")  # Static
        assert not manager.is_registered("custom_spec")
        
        manager.register_dynamic("custom_spec")
        assert manager.is_registered("custom_spec")  # Now dynamic
    
    def test_list_all(self):
        """Test listing all specializations."""
        manager = SpecializationManager.get_instance()
        all_specs = manager.list_all()
        
        # Should include all static specializations
        assert Specialization.GENERALIST in all_specs
        
        # Register dynamic and verify it's included
        dynamic_spec = manager.register_dynamic("custom_spec")
        all_specs_after = manager.list_all()
        assert dynamic_spec in all_specs_after
    
    def test_list_dynamic(self):
        """Test listing only dynamic specializations."""
        manager = SpecializationManager.get_instance()
        
        assert len(manager.list_dynamic()) == 0
        
        manager.register_dynamic("spec1")
        manager.register_dynamic("spec2")
        
        dynamic_specs = manager.list_dynamic()
        assert len(dynamic_specs) == 2
        assert all(isinstance(s, DynamicSpecialization) for s in dynamic_specs)
    
    def test_update_existing_dynamic(self):
        """Test updating an existing dynamic specialization."""
        manager = SpecializationManager.get_instance()
        
        spec1 = manager.register_dynamic("test_spec", name="Original Name")
        assert spec1.name == "Original Name"
        
        spec2 = manager.register_dynamic(
            "test_spec",
            name="Updated Name",
            metadata={"version": "2.0"}
        )
        
        # Should be the same instance (updated)
        assert spec1 is spec2
        assert spec2.name == "Updated Name"
        assert spec2.metadata == {"version": "2.0"}


class TestThreadSafety:
    """Test thread-safety of SpecializationManager."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        SpecializationManager._instance = None
    
    def test_concurrent_registration(self):
        """Test that concurrent registration is thread-safe."""
        manager = SpecializationManager.get_instance()
        results: List[Exception] = []
        
        def register_specs(start_idx: int, count: int):
            try:
                for i in range(count):
                    manager.register_dynamic(f"spec_{start_idx + i}")
            except Exception as e:
                results.append(e)
        
        # Create multiple threads registering different specializations
        threads = []
        num_threads = 10
        specs_per_thread = 5
        
        for i in range(num_threads):
            t = threading.Thread(
                target=register_specs,
                args=(i * specs_per_thread, specs_per_thread)
            )
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Should have no errors
        assert len(results) == 0
        
        # Verify all specializations were registered
        all_specs = manager.list_dynamic()
        assert len(all_specs) == num_threads * specs_per_thread
    
    def test_concurrent_get(self):
        """Test that concurrent get() operations are thread-safe."""
        manager = SpecializationManager.get_instance()
        
        # Register some specializations
        for i in range(10):
            manager.register_dynamic(f"spec_{i}")
        
        results: List[Exception] = []
        
        def get_specs():
            try:
                for i in range(10):
                    spec = manager.get(f"spec_{i}")
                    assert spec is not None
            except Exception as e:
                results.append(e)
        
        # Create multiple threads reading
        threads = []
        for _ in range(20):
            t = threading.Thread(target=get_specs)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(results) == 0


class TestYAMLPersistence:
    """Test YAML config file loading and saving."""
    
    def setup_method(self):
        """Reset singleton and create temp directory."""
        SpecializationManager._instance = None
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_save_to_config(self):
        """Test saving dynamic specializations to YAML."""
        manager = SpecializationManager.get_instance()
        
        # Register some dynamic specializations
        manager.register_dynamic(
            "custom_agent_v2",
            name="Custom Agent V2",
            metadata={"category": "custom", "version": "2.0"}
        )
        
        profile = RoleProfile(
            name=DynamicSpecialization("test_spec"),
            default_skills={"skill1": 0.8},
            allowed_tools={"tool1"},
        )
        manager.register_dynamic("test_spec", role_profile=profile)
        
        # Save to file
        config_path = Path(self.temp_dir) / "specializations.yaml"
        manager.save_to_config(config_path)
        
        # Verify file exists and has content
        assert config_path.exists()
        with open(config_path) as f:
            content = f.read()
            assert "custom_agent_v2" in content
            assert "Custom Agent V2" in content
            assert "test_spec" in content
    
    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_load_from_config(self):
        """Test loading dynamic specializations from YAML."""
        # Create a test config file
        config_path = Path(self.temp_dir) / "specializations.yaml"
        config_content = """
dynamic_specializations:
  custom_agent_v2:
    name: "Custom Agent V2"
    metadata:
      category: "custom"
      version: "2.0"
    role_profile:
      default_skills:
        skill1: 0.8
        skill2: 0.6
      allowed_tools:
        - tool1
        - tool2
      routing_tags:
        - tag1
  simple_spec:
    name: "Simple Spec"
    metadata:
      description: "A simple specialization"
"""
        with open(config_path, 'w') as f:
            f.write(config_content)
        
        # Load from file
        manager = SpecializationManager.get_instance()
        loaded_count = manager.load_from_config(config_path)
        
        assert loaded_count == 2
        assert manager.is_registered("custom_agent_v2")
        assert manager.is_registered("simple_spec")
        
        # Verify metadata
        spec = manager.get("custom_agent_v2")
        assert spec.metadata["category"] == "custom"
        assert spec.metadata["version"] == "2.0"
        
        # Verify role profile
        profile = manager.get_role_profile("custom_agent_v2")
        assert profile is not None
        assert profile.default_skills["skill1"] == 0.8
        assert "tool1" in profile.allowed_tools
    
    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_load_invalid_config(self):
        """Test loading invalid config handles errors gracefully."""
        # Create invalid config
        config_path = Path(self.temp_dir) / "invalid.yaml"
        with open(config_path, 'w') as f:
            f.write("invalid: yaml: content: [")
        
        manager = SpecializationManager.get_instance()
        
        # Should raise an exception
        with pytest.raises(Exception):
            manager.load_from_config(config_path)


class TestBackwardCompatibility:
    """Test backward compatibility with existing Specialization enum."""
    
    def test_role_registry_with_dynamic(self):
        """Test RoleRegistry works with dynamic specializations."""
        manager = SpecializationManager.get_instance()
        dynamic_spec = manager.register_dynamic("custom_spec")
        
        profile = RoleProfile(
            name=dynamic_spec,
            default_skills={"skill1": 0.5},
            allowed_tools={"tool1"},
        )
        
        registry = RoleRegistry([profile])
        retrieved = registry.get(dynamic_spec)
        assert retrieved == profile
    
    def test_role_registry_e_s_o_mapping(self):
        """Test E/S/O mapping works for dynamic specializations."""
        manager = SpecializationManager.get_instance()
        
        # Test execution-heavy specialization
        exec_spec = manager.register_dynamic("execution_robot_v2")
        p_dict = RoleRegistry.specialization_to_p_dict_static(exec_spec)
        assert "E" in p_dict
        assert "S" in p_dict
        assert "O" in p_dict
        assert p_dict["E"] > p_dict["S"]  # Should favor execution
        
        # Test synthesis-heavy specialization
        synth_spec = manager.register_dynamic("planner_agent")
        p_dict = RoleRegistry.specialization_to_p_dict_static(synth_spec)
        assert p_dict["S"] > p_dict["E"]  # Should favor synthesis
    
    def test_get_specialization_convenience(self):
        """Test get_specialization() convenience function."""
        manager = SpecializationManager.get_instance()
        manager.register_dynamic("convenience_spec")
        
        # Should work for both static and dynamic
        static_spec = get_specialization("generalist")
        assert isinstance(static_spec, Specialization)
        
        dynamic_spec = get_specialization("convenience_spec")
        assert isinstance(dynamic_spec, DynamicSpecialization)
    
    def test_register_specialization_convenience(self):
        """Test register_specialization() convenience function."""
        spec = register_specialization(
            "convenience_test",
            name="Convenience Test",
            metadata={"test": True}
        )
        
        assert isinstance(spec, DynamicSpecialization)
        assert spec.value == "convenience_test"
        assert spec.metadata["test"] is True
        
        # Verify it's registered
        manager = SpecializationManager.get_instance()
        assert manager.is_registered("convenience_test")


class TestIntegration:
    """Integration tests combining multiple features."""
    
    def setup_method(self):
        """Reset singleton."""
        SpecializationManager._instance = None
    
    def test_full_workflow(self):
        """Test a complete workflow: register -> use in profile -> use in registry."""
        # Register dynamic specialization
        spec = register_specialization(
            "workflow_spec",
            name="Workflow Spec",
            metadata={"workflow": True}
        )
        
        # Create role profile
        profile = RoleProfile(
            name=spec,
            default_skills={"workflow_skill": 0.9},
            allowed_tools={"workflow_tool"},
        )
        
        # Use in registry
        registry = RoleRegistry([profile])
        retrieved_profile = registry.get(spec)
        
        assert retrieved_profile.default_skills["workflow_skill"] == 0.9
        assert "workflow_tool" in retrieved_profile.allowed_tools
        
        # Test E/S/O mapping
        p_dict = registry.specialization_to_p_dict(spec)
        assert all(k in p_dict for k in ROLE_KEYS)
        assert sum(p_dict.values()) == pytest.approx(1.0)
    
    def test_mixed_static_and_dynamic(self):
        """Test using both static and dynamic specializations together."""
        manager = SpecializationManager.get_instance()
        dynamic_spec = manager.register_dynamic("dynamic_spec")
        
        # Create profiles for both
        static_profile = RoleProfile(
            name=Specialization.GENERALIST,
            default_skills={"general": 0.5},
        )
        dynamic_profile = RoleProfile(
            name=dynamic_spec,
            default_skills={"dynamic": 0.8},
        )
        
        # Use both in registry
        registry = RoleRegistry([static_profile, dynamic_profile])
        
        assert registry.get(Specialization.GENERALIST) == static_profile
        assert registry.get(dynamic_spec) == dynamic_profile
