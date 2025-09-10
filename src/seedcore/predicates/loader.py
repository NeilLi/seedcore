"""
Predicate configuration loader with validation and hot-reload support.

This module handles loading, validating, and managing predicate YAML configurations
with support for hot-reloading and comprehensive validation.
"""

import yaml
import os
import hashlib
import asyncio
from typing import Dict, Any, Optional, Callable
from pathlib import Path
import logging

from .schema import PredicatesConfig, validate_expression_symbols
from .signals import SIGNALS

logger = logging.getLogger(__name__)

class PredicateLoader:
    """Handles loading and validation of predicate configurations."""
    
    def __init__(self, config_path: str, watch_for_changes: bool = True):
        self.config_path = Path(config_path)
        self.watch_for_changes = watch_for_changes
        self._config: Optional[PredicatesConfig] = None
        self._last_good_config: Optional[PredicatesConfig] = None
        self._config_hash: Optional[str] = None
        self._last_good_hash: Optional[str] = None
        self._reload_callbacks: list = []
        self._file_watcher_task: Optional[asyncio.Task] = None
        self._load_failures = 0
        
    async def load(self) -> PredicatesConfig:
        """Load and validate the predicate configuration."""
        try:
            with open(self.config_path, 'r') as f:
                doc = yaml.safe_load(f)
            
            # Validate YAML structure
            config = PredicatesConfig(**doc)
            
            # Validate expressions
            self._validate_expressions(config)
            
            # Calculate config hash for change detection
            config_str = yaml.dump(doc, default_flow_style=False)
            self._config_hash = hashlib.sha256(config_str.encode()).hexdigest()
            
            # Update last good config
            self._last_good_config = config
            self._last_good_hash = self._config_hash
            self._load_failures = 0
            
            self._config = config
            logger.info(f"✅ Loaded predicate config from {self.config_path} (version: {config.metadata.version})")
            
            return config
            
        except Exception as e:
            self._load_failures += 1
            logger.error(f"❌ Failed to load predicate config from {self.config_path}: {e}")
            
            # Return last good config if available
            if self._last_good_config:
                logger.warning(f"⚠️ Using last good config (failures: {self._load_failures})")
                self._config = self._last_good_config
                self._config_hash = self._last_good_hash
                return self._last_good_config
            
            # If no last good config, create a minimal fallback
            logger.warning("⚠️ No last good config available, creating minimal fallback")
            fallback_config = self._create_minimal_fallback()
            self._config = fallback_config
            self._config_hash = "fallback"
            return fallback_config
    
    def _validate_expressions(self, config: PredicatesConfig):
        """Validate all expressions in the configuration."""
        all_rules = config.routing + config.mutations
        
        for rule in all_rules:
            try:
                # Extract and validate symbols
                symbols = validate_expression_symbols(rule.when)
                logger.debug(f"Rule '{rule.description or rule.do}' uses symbols: {symbols}")
                
                # Strict validation: ensure all symbols exist in signal registry
                from .signals import SIGNALS
                from .schema import ALLOWED_TASK_FIELDS, ALLOWED_DECISION_FIELDS
                
                allowed_symbols = set(SIGNALS.keys()) | {f"task.{f}" for f in ALLOWED_TASK_FIELDS} | {f"decision.{f}" for f in ALLOWED_DECISION_FIELDS} | {"gpu.guard_ok", "gpu.budget_remaining_s", "gpu.queue_depth", "gpu.concurrent_jobs"}
                
                for symbol in symbols:
                    if symbol not in allowed_symbols:
                        raise ValueError(f"Unknown signal '{symbol}' in rule '{rule.description or rule.do}'. Allowed signals: {sorted(allowed_symbols)}")
                
            except Exception as e:
                raise ValueError(f"Invalid expression in rule '{rule.description or rule.do}': {e}")
    
    def _create_minimal_fallback(self) -> PredicatesConfig:
        """Create a minimal fallback configuration."""
        from .schema import Rule, GpuGuard, Metadata
        
        return PredicatesConfig(
            routing=[
                Rule(
                    when="true",
                    do="fast_path:utility_organ_1",
                    priority=-1,
                    description="Emergency fallback rule"
                )
            ],
            mutations=[
                Rule(
                    when="false",  # Disabled fallback mutation rule
                    do="hold",
                    priority=-1,
                    description="Disabled fallback mutation"
                )
            ],
            gpu_guard=GpuGuard(
                max_concurrent=2,
                daily_budget_hours=4.0,
                cooldown_minutes=30,
                queue_timeout_minutes=30
            ),
            metadata=Metadata(
                version="fallback",
                commit="emergency",
                description="Emergency fallback configuration"
            ),
            routing_enabled=True,
            mutations_enabled=False,  # Disable mutations in fallback
            gpu_guard_enabled=True
        )
    
    def get_config(self) -> Optional[PredicatesConfig]:
        """Get the current configuration."""
        return self._config
    
    def get_config_hash(self) -> Optional[str]:
        """Get the current configuration hash."""
        return self._config_hash
    
    def add_reload_callback(self, callback: Callable[[PredicatesConfig], None]):
        """Add a callback to be called when configuration reloads."""
        self._reload_callbacks.append(callback)
    
    async def start_watching(self):
        """Start watching for configuration file changes."""
        if not self.watch_for_changes:
            return
            
        self._file_watcher_task = asyncio.create_task(self._watch_file())
        logger.info(f"🔍 Started watching {self.config_path} for changes")
    
    async def stop_watching(self):
        """Stop watching for configuration file changes."""
        if self._file_watcher_task:
            self._file_watcher_task.cancel()
            try:
                await self._file_watcher_task
            except asyncio.CancelledError:
                pass
            self._file_watcher_task = None
        logger.info("🛑 Stopped watching configuration file")
    
    async def _watch_file(self):
        """Watch for file changes and reload configuration."""
        last_mtime = 0
        
        while True:
            try:
                if self.config_path.exists():
                    current_mtime = self.config_path.stat().st_mtime
                    
                    if current_mtime > last_mtime:
                        logger.info(f"📝 Configuration file changed, reloading...")
                        try:
                            new_config = await self.load()
                            
                            # Notify callbacks
                            for callback in self._reload_callbacks:
                                try:
                                    callback(new_config)
                                except Exception as e:
                                    logger.error(f"Error in reload callback: {e}")
                            
                            last_mtime = current_mtime
                            
                        except Exception as e:
                            logger.error(f"Failed to reload configuration: {e}")
                
                await asyncio.sleep(1)  # Check every second
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error watching configuration file: {e}")
                await asyncio.sleep(5)  # Wait before retrying

def load_predicates(config_path: str) -> PredicatesConfig:
    """Load predicate configuration from file (sync version)."""
    loader = PredicateLoader(config_path, watch_for_changes=False)
    try:
        # Try to get the current event loop
        loop = asyncio.get_running_loop()
        # If we're in an event loop, we can't use asyncio.run()
        # Instead, we need to use a different approach - run in a new thread
        import concurrent.futures
        import threading
        
        def run_in_thread():
            # Create a new event loop in the thread
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(loader.load())
            finally:
                new_loop.close()
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(run_in_thread)
            return future.result()
    except RuntimeError:
        # No event loop running, safe to use asyncio.run()
        return asyncio.run(loader.load())

async def load_predicates_async(config_path: str) -> PredicatesConfig:
    """Load predicate configuration from file (async version)."""
    loader = PredicateLoader(config_path, watch_for_changes=False)
    return await loader.load()

def validate_predicates(config: PredicatesConfig) -> bool:
    """Validate a predicate configuration."""
    try:
        # Re-validate expressions
        all_rules = config.routing + config.mutations
        for rule in all_rules:
            validate_expression_symbols(rule.when)
        
        # Validate signal references
        from .evaluator import PredicateEvaluator
        evaluator = PredicateEvaluator()
        
        # Test with dummy context
        dummy_context = {
            "task": {"type": "test", "domain": "test", "priority": 5, "complexity": 0.5},
            "decision": {"action": "test", "confidence": 0.5},
            "p_fast": 0.8,
            "s_drift": 0.3,
            "gpu": {"guard_ok": True}
        }
        
        # Try to evaluate each rule
        for rule in all_rules:
            try:
                evaluator.eval_predicate(rule.when, dummy_context)
            except Exception as e:
                logger.warning(f"Rule validation failed for '{rule.description or rule.do}': {e}")
                return False
        
        return True
        
    except Exception as e:
        logger.error(f"Predicate validation failed: {e}")
        return False

def create_default_config() -> PredicatesConfig:
    """Create a default predicate configuration."""
    from .schema import Rule, GpuGuard, Metadata
    
    return PredicatesConfig(
        routing=[
            Rule(
                when="task.type == 'anomaly_triage' and s_drift > 0.7",
                do="escalate",
                priority=10,
                description="Escalate high-drift anomaly triage tasks"
            ),
            Rule(
                when="task.type == 'anomaly_triage' and s_drift <= 0.7",
                do="fast_path:utility_organ_1",
                priority=5,
                description="Fast path for low-drift anomaly triage"
            ),
            Rule(
                when="task.type == 'general_query'",
                do="fast_path:utility_organ_1",
                priority=1,
                description="Default fast path for general queries"
            ),
            Rule(
                when="task.type == 'health_check'",
                do="fast_path:utility_organ_1",
                priority=1,
                description="Health checks always go fast path"
            ),
            # Catch-all fallback rule
            Rule(
                when="true",
                do="fast_path:utility_organ_1",
                priority=-1,
                description="Default fallback rule"
            )
        ],
        mutations=[
            Rule(
                when="decision.action in ['tune', 'retrain'] and ΔE_est > 0.02 and gpu.guard_ok",
                do="submit_tuning",
                priority=10,
                description="Submit tuning for high-value mutations"
            ),
            Rule(
                when="decision.action == 'tune' and ΔE_est <= 0.02",
                do="hold",
                priority=5,
                description="Hold low-value tuning requests"
            )
        ],
        gpu_guard=GpuGuard(
            max_concurrent=2,
            daily_budget_hours=4.0,
            cooldown_minutes=30,
            queue_timeout_minutes=30
        ),
        metadata=Metadata(
            version="1.0.0",
            commit="initial",
            description="Default predicate configuration"
        ),
        routing_enabled=True,
        mutations_enabled=True,
        gpu_guard_enabled=True
    )

def save_default_config(config_path: str):
    """Save a default configuration to file."""
    config = create_default_config()
    
    # Convert to dict for YAML serialization
    config_dict = config.model_dump()
    
    with open(config_path, 'w') as f:
        yaml.dump(config_dict, f, default_flow_style=False, indent=2)
    
    logger.info(f"💾 Saved default configuration to {config_path}")
