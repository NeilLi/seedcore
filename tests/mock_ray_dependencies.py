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

# Mock Ray module
class MockRay:
    """Mock Ray module that provides the expected interface."""
    
    @staticmethod
    def init(*args, **kwargs):
        """Mock ray.init() - always returns True."""
        return True
    
    @staticmethod
    def is_initialized():
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
                # Extract agent_id from args if available
                agent_id = None
                if args and len(args) > 0:
                    agent_id = args[0]
                return MockActor(agent_id=agent_id)
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
                    # Extract agent_id from args if available
                    agent_id = None
                    if args and len(args) > 0:
                        agent_id = args[0]
                    return MockActor(agent_id=agent_id)
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
                    # Extract agent_id from args if available
                    agent_id = None
                    if args and len(args) > 0:
                        agent_id = args[0]
                    return MockActor(agent_id=agent_id)
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
    
    @staticmethod
    def wait(object_refs, timeout=None):
        """Mock ray.wait() - returns ready and not_ready lists."""
        if isinstance(object_refs, list):
            return object_refs, []
        else:
            return [object_refs], []
    
    class serve:
        """Mock Ray Serve module."""
        
        @staticmethod
        def deployment(*args, **kwargs):
            """Mock serve.deployment decorator."""
            def decorator(cls):
                # Add bind method to the class (Ray Serve does this)
                @staticmethod
                def bind():
                    return cls
                cls.bind = bind
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
    
    def __init__(self, agent_id=None):
        self.name = "mock_actor"
        self.agent_id = agent_id or "mock_agent"
        self._task_count = 0  # Track task count for testing
        # Provide RemoteCallable wrappers for methods that tests call with .remote
        class RemoteCallable:
            def __init__(self, func):
                self._func = func
            def __call__(self, *args, **kwargs):
                return self._func(*args, **kwargs)
            def remote(self, *args, **kwargs):
                return self._func(*args, **kwargs)

        self.ping = RemoteCallable(lambda: MockObjectRef("pong"))
        self.get_id = RemoteCallable(lambda: MockObjectRef(self.agent_id))
        self.get_heartbeat = RemoteCallable(lambda: MockObjectRef({
            'role_probs': {'E': 0.5, 'S': 0.3, 'O': 0.2},
            'performance_metrics': {
                'capability_score_c': 0.8,
                'mem_util': 0.3,
                'tasks_processed': self._task_count
            }
        }))
        self.get_summary_stats = RemoteCallable(lambda: MockObjectRef({
            'tasks_processed': self._task_count,
            'capability_score': 0.8,
            'mem_util': 0.3,
            'memory_writes': 10,
            'peer_interactions_count': 5
        }))
        def _exec(task_data):
            self._task_count += 1
            return MockObjectRef({
                'success': True,
                'agent_id': self.agent_id,
                'task_id': task_data.get('task_id', 'mock_task'),
                'execution_time': 0.1,
                'quality': 0.8
            })
        self.execute_task = RemoteCallable(_exec)
        self.update_role_probs = RemoteCallable(lambda new_probs: MockObjectRef(True))
        self.update_local_metrics = RemoteCallable(lambda capability, role_efficiency, mem_hits: MockObjectRef(True))
        self.get_energy_proxy = RemoteCallable(lambda: MockObjectRef({
            'capability': 0.8,
            'entropy_contribution': 0.6,
            'mem_util': 0.3,
            'state_norm': 0.7,
            'memory_utilization': 0.3,
            'energy_score': 0.7,
            'role_efficiency': 0.9
        }))
    
    def remote(self, *args, **kwargs):
        """Mock remote method call."""
        return MockObjectRef()
    
    # After method definitions, attach .remote wrappers for explicit methods
    def __post_init_remote__(self):
        for method_name in [
            'ping', 'get_id', 'get_heartbeat', 'get_summary_stats',
            'execute_task', 'update_role_probs', 'update_local_metrics',
            'get_energy_proxy'
        ]:
            method = getattr(self, method_name, None)
            if callable(method):
                # Already handled by RemoteCallable, no-op
                pass
    
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
                # Return a proper array for state embedding
                return MockObjectRef([0.1] * 128)  # 128-dimensional embedding
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
            mock_method.remote = lambda *args, **kwargs: MockObjectRef([0.1] * 128)
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
    
    def __iter__(self):
        """Make MockObjectRef iterable if value is iterable."""
        if hasattr(self.value, '__iter__') and not isinstance(self.value, str):
            return iter(self.value)
        raise TypeError(f"'{type(self).__name__}' object is not iterable")
    
    def __getitem__(self, key):
        """Make MockObjectRef subscriptable if value is subscriptable."""
        if hasattr(self.value, '__getitem__'):
            return self.value[key]
        raise TypeError(f"'{type(self).__name__}' object is not subscriptable")
    
    def __await__(self):
        """Make MockObjectRef awaitable - returns the value."""
        import asyncio
        if asyncio.iscoroutine(self.value):
            return self.value.__await__()
        # Return a coroutine that yields the value
        async def _await():
            return self.value
        return _await().__await__()

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
            return [0.5] * data.shape[0]
        return [0.5]
    
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
            return [0.5] * data.shape[0]
        return [0.5]

# Mock Ray logger
class MockLogger:
    """Mock Ray logger."""
    
    def __init__(self):
        self.logger = logging.getLogger("mock_ray")
        self.handlers = []
        self.propagate = True
    
    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)
    
    def debug(self, msg, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)
    
    def addHandler(self, handler):
        """Mock addHandler method."""
        self.handlers.append(handler)
    
    def exception(self, msg, *args, **kwargs):
        """Mock exception method."""
        self.logger.error(msg, *args, **kwargs)

# Create mock modules
mock_xgboost_ray = type('MockXGBoostRay', (), {
    'RayDMatrix': MockRayDMatrix,
    'train': mock_train,
    'RayParams': type('RayParams', (), {}),
    'predict': lambda *args, **kwargs: [0.5]
})()

import types

# Build a proper module-type mock for ray
ray_mod = types.ModuleType('ray')

def _ray_init(*args, **kwargs):
    return True

def _ray_is_initialized():
    return True

# Make it callable
_ray_is_initialized.__name__ = 'is_initialized'

def _ray_shutdown():
    return None

def _ray_get_actor(name, namespace=None):
    return MockActor(agent_id=name)

def _ray_get(obj, timeout=None):
    if isinstance(obj, list):
        return [item.value if hasattr(item, 'value') else item for item in obj]
    return obj.value if hasattr(obj, 'value') else obj

def _ray_put(obj):
    return obj

def _ray_kill(actor):
    return None

def _ray_get_runtime_context():
    return MockRuntimeContext()

def _ray_wait(object_refs, timeout=None):
    if isinstance(object_refs, list):
        return object_refs, []
    return [object_refs], []

def _ray_remote(*r_args, **r_kwargs):
    def decorator(obj):
        def remote_method(*args, **kwargs):
            agent_id = args[0] if args else None
            return MockActor(agent_id=agent_id)
        def options_method(**kwargs):
            return obj
        setattr(obj, 'remote', staticmethod(remote_method))
        setattr(obj, 'options', staticmethod(options_method))
        return obj
    if r_args and callable(r_args[0]) and not r_kwargs:
        return decorator(r_args[0])
    return decorator

# Assign functions to module
ray_mod.init = _ray_init
# Ensure is_initialized is callable and accessible
ray_mod.is_initialized = _ray_is_initialized
# Also set it as a property that can be called
if not callable(ray_mod.is_initialized):
    ray_mod.is_initialized = _ray_is_initialized
ray_mod.shutdown = _ray_shutdown
ray_mod.remote = _ray_remote
ray_mod.get_actor = _ray_get_actor
ray_mod.get = _ray_get
ray_mod.put = _ray_put
ray_mod.kill = _ray_kill
ray_mod.get_runtime_context = _ray_get_runtime_context
ray_mod.wait = _ray_wait

# Submodules
ray_mod.logger = MockLogger()
ray_mod.exceptions = MockRay.exceptions
# serve submodule
ray_mod.serve = MockRay.serve

# actor submodule with ActorHandle
ray_actor_mod = types.ModuleType('ray.actor')
class ActorHandle:
    """Mock Ray ActorHandle type."""
    pass
ray_actor_mod.ActorHandle = ActorHandle

# data submodule
ray_data_mod = types.ModuleType('ray.data')
class Dataset:
    """Mock Ray Dataset class."""
    def __init__(self, data=None):
        self._data = data
    
    def map(self, *args, **kwargs):
        """Mock map method."""
        return self
    
    def __iter__(self):
        """Mock iterator."""
        return iter([]) if self._data is None else iter(self._data)

def _data_from_pandas(df, **kwargs):
    """Mock from_pandas function."""
    return Dataset(data=df)

def _data_read_csv(path, **kwargs):
    """Mock read_csv function."""
    return Dataset()

def _data_read_parquet(path, **kwargs):
    """Mock read_parquet function."""
    return Dataset()

ray_data_mod.Dataset = Dataset
ray_data_mod.from_pandas = _data_from_pandas
ray_data_mod.read_csv = _data_read_csv
ray_data_mod.read_parquet = _data_read_parquet

# air submodule
ray_air = types.ModuleType('ray.air')
ray_air.config = MockRay.air.config

# util submodule with log_once
ray_util = types.ModuleType('ray.util')
def _log_once(*args, **kwargs):
    """Mock log_once function."""
    pass
ray_util.log_once = _log_once

# Assign submodules to ray_mod
ray_mod.actor = ray_actor_mod
ray_mod.data = ray_data_mod
ray_mod.air = ray_air
ray_mod.util = ray_util

# Register in sys.modules
# Ensure ray module is always properly mocked, even if it was already imported
# We need to handle the case where ray might have been imported as a real module
# Force replace the module completely to avoid any issues with already-imported modules
sys.modules['ray'] = ray_mod  # Always ensure our mock is registered first

# Also update any already-imported references if they exist
if 'ray' in sys.modules:
    existing_ray = sys.modules['ray']
    # If it's not our mock module, update its attributes
    if existing_ray is not ray_mod:
        # Try to update attributes on the existing module object
        for attr_name in ['is_initialized', 'init', 'shutdown', 'get_actor', 'get', 'put', 'remote']:
            if hasattr(ray_mod, attr_name):
                try:
                    setattr(existing_ray, attr_name, getattr(ray_mod, attr_name))
                except (TypeError, AttributeError):
                    pass  # Skip attributes that can't be set
sys.modules['ray.logger'] = ray_mod.logger
sys.modules['ray.serve'] = ray_mod.serve
sys.modules['ray.exceptions'] = ray_mod.exceptions
sys.modules['ray.actor'] = ray_actor_mod
sys.modules['ray.data'] = ray_data_mod
sys.modules['ray.core'] = type('MockRayCore', (), {})()
sys.modules['ray.core.generated'] = type('MockRayCoreGenerated', (), {})()
sys.modules['ray.core.generated.ray_client_pb2'] = type('MockRayClientPb2', (), {})()
sys.modules['ray.util'] = ray_util
sys.modules['ray.util.client'] = type('MockRayUtilClient', (), {})()
sys.modules['ray.util.client.server'] = type('MockRayUtilClientServer', (), {})()
sys.modules['ray.util.client.server.server'] = type('MockRayUtilClientServerServer', (), {})()
sys.modules['ray.air'] = ray_air
sys.modules['ray.air.config'] = ray_air.config
sys.modules['xgboost_ray'] = mock_xgboost_ray
sys.modules['xgboost_ray.main'] = mock_xgboost_ray
sys.modules['xgboost_ray.matrix'] = mock_xgboost_ray

# Mock logging_setup module
mock_logging_setup = type('MockLoggingSetup', (), {
    'ensure_serve_logger': lambda *args, **kwargs: MockLogger(),
    'setup_logging': lambda *args, **kwargs: None
})()
sys.modules['seedcore.logging_setup'] = mock_logging_setup

# Mock registry module
mock_registry = type('MockRegistry', (), {
    'RegistryClient': type('MockRegistryClient', (), {
        '__init__': lambda self, *args, **kwargs: None,
        'register': lambda self: None,
        'set_status': lambda self, status: None,
        'beat': lambda self: None
    }),
    'list_active_instances': lambda: []
})()
sys.modules['seedcore.registry'] = mock_registry

# Mock specs module
mock_specs = type('MockSpecs', (), {
    'AgentSpec': type('MockAgentSpec', (), {
        '__init__': lambda self, *args, **kwargs: None
    }),
    'OrganSpec': type('MockOrganSpec', (), {
        '__init__': lambda self, *args, **kwargs: None
    }),
    'GraphClient': type('MockGraphClient', (), {
        'list_agent_specs': lambda self: [],
        'list_organ_specs': lambda self: []
    })
})()
sys.modules['seedcore.organs.tier0.specs'] = mock_specs

# Mock database module (only if not already provided by mock_database_dependencies)
mock_database = type('MockDatabase', (), {
    'get_async_pg_session_factory': lambda: lambda: type('MockSession', (), {
        '__enter__': lambda self: self,
        '__exit__': lambda self, *args: None,
        'execute': lambda self, query, params=None: type('MockResult', (), {
            'first': lambda: type('MockRow', (), {'__getitem__': lambda self, i: 'test_epoch' if i == 0 else None})()
        })(),
        'commit': lambda self: None
    })(),
    'get_async_pg_engine': lambda: type('MockEngine', (), {})(),
    'get_sync_pg_engine': lambda: type('MockEngine', (), {})(),
    'get_async_mysql_engine': lambda: type('MockEngine', (), {})(),
    'get_sync_mysql_engine': lambda: type('MockEngine', (), {})(),
    'get_neo4j_driver': lambda: type('MockDriver', (), {})(),
    'get_db_session': lambda: iter([type('MockSession', (), {'close': lambda: None})()]),
    'get_mysql_session': lambda: iter([type('MockSession', (), {'close': lambda: None})()]),
    'check_pg_health': lambda: True,
    'check_mysql_health': lambda: True,
    'check_neo4j_health': lambda: True,
    'PG_DSN': 'postgresql://test:test@localhost/test',
    'MYSQL_DSN': 'mysql://test:test@localhost/test',
    'NEO4J_URI': 'bolt://localhost:7687',
    'NEO4J_USER': 'neo4j',
    'NEO4J_PASSWORD': 'password',
    'NEO4J_DATABASE': 'neo4j',
    'NEO4J_POOL_SIZE': 10,
    'NEO4J_CONNECTION_ACQUISITION_TIMEOUT': 30,
    'NEO4J_MAX_CONNECTION_LIFETIME': 3600,
    'NEO4J_MAX_TX_RETRY_TIME': 30,
    'NEO4J_ENCRYPTED': True,
    'NEO4J_KEEP_ALIVE': True,
    'PG_POOL_SIZE': 10,
    'PG_MAX_OVERFLOW': 20,
    'PG_POOL_TIMEOUT': 30,
    'PG_POOL_RECYCLE': 3600,
    'PG_POOL_PRE_PING': True,
    'MYSQL_POOL_SIZE': 10,
    'MYSQL_MAX_OVERFLOW': 20,
    'MYSQL_POOL_TIMEOUT': 30,
    'MYSQL_POOL_RECYCLE': 3600,
    'MYSQL_POOL_PRE_PING': True
})()
if 'seedcore.database' not in sys.modules:
    sys.modules['seedcore.database'] = mock_database

# Mock the logger import that xgboost_ray tries to do
sys.modules['ray'].logger = MockLogger()

print("✅ Mock Ray dependencies loaded successfully")
