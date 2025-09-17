#!/usr/bin/env python3
"""
Mock Ray Dependencies for Testing

This module provides mock implementations of Ray and xgboost_ray modules
to allow tests to run without requiring a Ray cluster.
"""

import sys
import os
import logging
from typing import Any, Dict, List, Optional, Union, Tuple
from dataclasses import dataclass
import numpy as np
import pandas as pd

# Mock Ray module
class MockRay:
    """Mock Ray module that provides the expected interface."""
    
    @staticmethod
    def init(*args, **kwargs):
        """Mock ray.init() - always returns True."""
        return True
    
    def is_initialized(self):
        """Mock ray.is_initialized() - always returns True."""
        return True
    
    @staticmethod
    def shutdown():
        """Mock ray.shutdown() - no-op."""
        pass
    
    @staticmethod
    def get_actor(name, namespace=None):
        """Mock ray.get_actor() - returns a mock actor."""
        return MockActor()
    
    def remote(self, *args, **kwargs):
        """Mock ray.remote decorator."""
        # If called with a class (decorator usage), add remote and options methods and return class
        if args and callable(args[0]) and not kwargs:
            cls = args[0]
            def remote_method(*args, **kwargs):
                return MockActor()
            def options_method(**kwargs):
                # Return self to allow chaining: actor.options(...).remote(...)
                return cls
            cls.remote = staticmethod(remote_method)
            cls.options = staticmethod(options_method)
            return cls
        # If called with arguments, return a decorator
        elif args and not callable(args[0]):
            def decorator(cls):
                def remote_method(*args, **kwargs):
                    return MockActor()
                def options_method(**kwargs):
                    # Return self to allow chaining: actor.options(...).remote(...)
                    return cls
                cls.remote = staticmethod(remote_method)
                cls.options = staticmethod(options_method)
                return cls
            return decorator
        # If called without arguments, return a decorator
        else:
            def decorator(cls):
                def remote_method(*args, **kwargs):
                    return MockActor()
                def options_method(**kwargs):
                    # Return self to allow chaining: actor.options(...).remote(...)
                    return cls
                cls.remote = staticmethod(remote_method)
                cls.options = staticmethod(options_method)
                return cls
            return decorator
    
    @staticmethod
    def get(obj, timeout=None):
        """Mock ray.get() - returns the object as-is or the value if it's a MockObjectRef."""
        if isinstance(obj, list):
            # Handle lists of MockObjectRef objects
            return [item.value if hasattr(item, 'value') else item for item in obj]
        elif hasattr(obj, 'value'):
            return obj.value
        return obj
    
    @staticmethod
    def put(obj):
        """Mock ray.put() - returns the object as-is."""
        return obj
    
    @staticmethod
    def kill(actor):
        """Mock ray.kill() - no-op."""
        pass
    
    @staticmethod
    def get_runtime_context():
        """Mock ray.get_runtime_context() - returns mock runtime context."""
        return MockRuntimeContext()
    
    class serve:
        """Mock Ray Serve module."""
        
        @staticmethod
        def deployment(*args, **kwargs):
            """Mock serve.deployment decorator."""
            def decorator(cls):
                return cls
            return decorator
        
        @staticmethod
        def get_deployment_handle(name, app_name=None):
            """Mock serve.get_deployment_handle."""
            return MockDeploymentHandle()
        
        @staticmethod
        def list_deployments():
            """Mock serve.list_deployments."""
            return {}
        
        @staticmethod
        def ingress(app):
            """Mock serve.ingress decorator."""
            def decorator(cls):
                return cls
            return decorator
    
    class air:
        class config:
            @dataclass
            class ScalingConfig:
                num_workers: int = 1
                use_gpu: bool = False
                resources_per_worker: Dict[str, Any] = None
                
                def __post_init__(self):
                    if self.resources_per_worker is None:
                        self.resources_per_worker = {}
    
    class exceptions:
        """Mock Ray exceptions module."""
        
        class RayActorError(Exception):
            """Mock RayActorError exception."""
            pass
        
        class RayTaskError(Exception):
            """Mock RayTaskError exception."""
            pass
        
        class RayTimeoutError(Exception):
            """Mock RayTimeoutError exception."""
            pass

# Mock Actor class
class MockActor:
    """Mock Ray actor."""
    
    def __init__(self):
        self.name = "mock_actor"
    
    def remote(self, *args, **kwargs):
        """Mock remote method call."""
        return MockObjectRef()
    
    def __getattr__(self, name):
        """Mock attribute access - returns a mock method."""
        def mock_method(*args, **kwargs):
            # Return a MockObjectRef with a meaningful value
            if name == 'test_pg_query':
                return MockObjectRef(1)  # Expected result for test
            elif name == 'test_mysql_query':
                return MockObjectRef(1)  # Expected result for test
            elif name == 'get_heartbeat':
                # Return a proper heartbeat dictionary
                return MockObjectRef({
                    'role_probs': {'E': 0.5, 'S': 0.3, 'O': 0.2},
                    'performance_metrics': {'capability_score_c': 0.8, 'mem_util': 0.3}
                })
            elif name == 'update_role_probs':
                return MockObjectRef(True)  # Success response
            elif name == 'get_state_embedding':
                # Return a proper numpy array for state embedding
                import numpy as np
                return MockObjectRef(np.random.randn(128))  # 128-dimensional embedding
            elif name == 'get_energy_proxy':
                # Return a proper energy proxy dictionary
                return MockObjectRef({
                    'capability': 0.8,
                    'entropy_contribution': 0.6,
                    'mem_util': 0.3,
                    'state_norm': 0.7,
                    'memory_utilization': 0.3,
                    'energy_score': 0.7,
                    'role_efficiency': 0.9
                })
            elif name == 'update_local_metrics':
                return MockObjectRef(True)  # Success response
            elif name == 'topn' or name == 'top_n':
                # Return a list of tuples for hot items
                return MockObjectRef([("test_item_123", 5), ("other_item", 3), ("another_item", 2)])
            elif name == 'incr':
                return MockObjectRef(True)  # Success response
            elif name == 'execute_task_on_best_agent':
                # Return a proper task execution result
                return MockObjectRef({
                    'success': True,
                    'agent_id': 'mock_agent',
                    'task_id': 'mock_task',
                    'execution_time': 0.1,
                    'energy_consumed': 0.05
                })
            elif name == 'execute_task':
                # Return a proper task execution result
                return MockObjectRef({
                    'success': True,
                    'agent_id': 'mock_agent',
                    'task_id': 'mock_task',
                    'execution_time': 0.1,
                    'quality': 0.8
                })
            elif name == 'get_id':
                # Return agent ID
                return MockObjectRef('mock_agent')
            else:
                return MockObjectRef(f"Mock result for {name}")
        # Add a remote method to the mock method
        if name == 'test_pg_query' or name == 'test_mysql_query':
            mock_method.remote = lambda *args, **kwargs: MockObjectRef(1)
        elif name == 'get_heartbeat':
            mock_method.remote = lambda *args, **kwargs: MockObjectRef({
                'role_probs': {'E': 0.5, 'S': 0.3, 'O': 0.2},
                'performance_metrics': {'capability_score_c': 0.8, 'mem_util': 0.3}
            })
        elif name == 'update_role_probs':
            mock_method.remote = lambda *args, **kwargs: MockObjectRef(True)
        elif name == 'get_state_embedding':
            import numpy as np
            mock_method.remote = lambda *args, **kwargs: MockObjectRef(np.random.randn(128))
        elif name == 'get_energy_proxy':
            mock_method.remote = lambda *args, **kwargs: MockObjectRef({
                'capability': 0.8,
                'entropy_contribution': 0.6,
                'mem_util': 0.3,
                'state_norm': 0.7,
                'memory_utilization': 0.3,
                'energy_score': 0.7,
                'role_efficiency': 0.9
            })
        elif name == 'update_local_metrics':
            mock_method.remote = lambda *args, **kwargs: MockObjectRef(True)
        elif name == 'topn' or name == 'top_n':
            mock_method.remote = lambda *args, **kwargs: MockObjectRef([("test_item_123", 5), ("other_item", 3), ("another_item", 2)])
        elif name == 'incr':
            mock_method.remote = lambda *args, **kwargs: MockObjectRef(True)
        elif name == 'execute_task_on_best_agent':
            mock_method.remote = lambda *args, **kwargs: MockObjectRef({
                'success': True,
                'agent_id': 'mock_agent',
                'task_id': 'mock_task',
                'execution_time': 0.1,
                'energy_consumed': 0.05
            })
        elif name == 'execute_task':
            mock_method.remote = lambda *args, **kwargs: MockObjectRef({
                'success': True,
                'agent_id': 'mock_agent',
                'task_id': 'mock_task',
                'execution_time': 0.1,
                'quality': 0.8
            })
        elif name == 'get_id':
            mock_method.remote = lambda *args, **kwargs: MockObjectRef('mock_agent')
        else:
            mock_method.remote = lambda *args, **kwargs: MockObjectRef(f"Mock result for {name}")
        return mock_method

# Mock ObjectRef class
class MockObjectRef:
    """Mock Ray ObjectRef."""
    
    def __init__(self, value=None):
        self.value = value
    
    def __call__(self):
        """Mock call - returns the value."""
        return self.value

# Mock DeploymentHandle class
class MockDeploymentHandle:
    """Mock Ray Serve deployment handle."""
    
    def __init__(self):
        self.name = "mock_deployment"
    
    def remote(self, *args, **kwargs):
        """Mock remote method call."""
        return MockObjectRef({"success": True, "result": "mock_result"})
    
    def __getattr__(self, name):
        """Mock attribute access - returns a mock method."""
        return lambda *args, **kwargs: MockObjectRef({"success": True, "result": "mock_result"})

# Mock RuntimeContext class
class MockRuntimeContext:
    """Mock Ray runtime context."""
    
    def __init__(self):
        self.namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        self.job_id = "mock_job_id"
        self.node_id = "mock_node_id"
        self.worker_id = "mock_worker_id"
    
    def get(self, key, default=None):
        """Mock get method for runtime context attributes."""
        return getattr(self, key, default)

# Mock xgboost_ray module
class MockRayDMatrix:
    """Mock RayDMatrix class."""
    
    def __init__(self, data, label=None, **kwargs):
        self.data = data
        self.label = label
        self.kwargs = kwargs
    
    def get_data(self):
        """Mock get_data method."""
        return self.data
    
    def get_label(self):
        """Mock get_label method."""
        return self.label

def mock_train(*args, **kwargs):
    """Mock xgboost_ray.train function."""
    # Return a mock model
    return MockXGBoostModel()

class MockXGBoostModel:
    """Mock XGBoost model."""
    
    def __init__(self):
        self.booster = MockBooster()
    
    def predict(self, data):
        """Mock predict method."""
        if hasattr(data, 'shape'):
            # Return random predictions
            return np.random.random(data.shape[0])
        return np.random.random(1)
    
    def save_model(self, path):
        """Mock save_model method."""
        with open(path, 'w') as f:
            f.write("mock_model")
    
    def load_model(self, path):
        """Mock load_model method."""
        return self

class MockBooster:
    """Mock XGBoost booster."""
    
    def __init__(self):
        pass
    
    def predict(self, data):
        """Mock predict method."""
        if hasattr(data, 'shape'):
            return np.random.random(data.shape[0])
        return np.random.random(1)

# Mock Ray logger
class MockLogger:
    """Mock Ray logger."""
    
    def __init__(self):
        self.logger = logging.getLogger("mock_ray")
    
    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)
    
    def debug(self, msg, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

# Create mock modules
mock_ray = MockRay()
# Ensure serve is accessible as an attribute
mock_ray.serve = MockRay.serve
mock_xgboost_ray = type('MockXGBoostRay', (), {
    'RayDMatrix': MockRayDMatrix,
    'train': mock_train,
    'RayParams': type('RayParams', (), {}),
    'predict': lambda *args, **kwargs: np.random.random(1)
})()

# Mock the modules in sys.modules before they're imported
sys.modules['ray'] = mock_ray
sys.modules['ray.logger'] = MockLogger()
sys.modules['ray.serve'] = mock_ray.serve
sys.modules['ray.exceptions'] = mock_ray.exceptions
sys.modules['ray.core'] = type('MockRayCore', (), {})()
sys.modules['ray.core.generated'] = type('MockRayCoreGenerated', (), {})()
sys.modules['ray.core.generated.ray_client_pb2'] = type('MockRayClientPb2', (), {})()
sys.modules['ray.util'] = type('MockRayUtil', (), {})()
sys.modules['ray.util.client'] = type('MockRayUtilClient', (), {})()
sys.modules['ray.util.client.server'] = type('MockRayUtilClientServer', (), {})()
sys.modules['ray.util.client.server.server'] = type('MockRayUtilClientServerServer', (), {})()
sys.modules['ray.air'] = mock_ray.air
sys.modules['ray.air.config'] = mock_ray.air.config
sys.modules['xgboost_ray'] = mock_xgboost_ray
sys.modules['xgboost_ray.main'] = mock_xgboost_ray
sys.modules['xgboost_ray.matrix'] = mock_xgboost_ray

# Mock logging_setup module
mock_logging_setup = type('MockLoggingSetup', (), {
    'ensure_serve_logger': lambda *args, **kwargs: MockLogger(),
    'setup_logging': lambda *args, **kwargs: None
})()
sys.modules['seedcore.logging_setup'] = mock_logging_setup

# Mock the logger import that xgboost_ray tries to do
sys.modules['ray'].logger = MockLogger()

print("✅ Mock Ray dependencies loaded successfully")
