# ops/pkg/evaluator.py

import time
import logging
import uuid
from typing import Any, Dict, Optional, List, Protocol, runtime_checkable
from dataclasses import dataclass
from datetime import datetime

# Import snapshot data structure and client
from .dao import PKGSnapshotData
from .client import PKGClient

logger = logging.getLogger(__name__)

# --- Optional WASM Runtime Support ---
def is_wasmtime_available() -> bool:
    """
    Runtime check for wasmtime availability.
    
    This function is called at runtime rather than module import time,
    ensuring correct detection even if the environment changes after startup.
    
    Returns:
        True if wasmtime can be imported and used, False otherwise
    """
    try:
        import wasmtime  # type: ignore
        # Verify wasmtime is actually usable by checking version
        try:
            # Try to create an engine to verify it works
            test_engine = wasmtime.Engine()
            del test_engine
            return True
        except Exception as e:
            logger.warning(f"wasmtime imported but Engine() creation failed: {type(e).__name__}: {e}")
            return False
    except Exception as e:
        logger.debug(f"wasmtime import failed: {type(e).__name__}: {repr(e)}")
        return False


@dataclass
class EvaluationResult:
    """Result object returned by policy engines."""
    subtasks: List[Dict[str, Any]]
    dag: List[Dict[str, Any]]
    provenance: List[Dict[str, Any]]


# --- Engine Protocol Interface ---

@runtime_checkable
class PolicyEngine(Protocol):
    """
    Protocol interface for policy evaluation engines.
    
    All policy engines must implement this interface to ensure
    consistent evaluation behavior across different engine types.
    """
    def evaluate(self, task_facts: Dict[str, Any]) -> EvaluationResult:
        """
        Evaluate policy rules against task facts.
        
        Args:
            task_facts: Input facts dictionary with tags, signals, context
            
        Returns:
            EvaluationResult with subtasks, dag, and provenance
        """
        ...


# --- WASM Cache ---

_WASM_CACHE: Dict[str, Any] = {}  # Cache keyed by checksum


def _get_cached_wasm(checksum: Optional[str], wasm_bytes: bytes) -> Optional[Any]:
    """Get cached WASM engine or None if not cached."""
    if checksum and checksum in _WASM_CACHE:
        cached = _WASM_CACHE[checksum]
        logger.debug(f"Using cached WASM engine for checksum {checksum[:8]}...")
        # Ensure cached instance has entrypoints resolved (for instances cached before this feature)
        if hasattr(cached, '_entrypoint_name') and cached._entrypoint_name is None:
            if cached._wasmtime_available and cached._instance:
                logger.debug("Cached instance missing entrypoint resolution, resolving now...")
                cached._resolve_entrypoint()
        return cached
    return None


def _cache_wasm(checksum: Optional[str], engine: Any) -> None:
    """
    Cache WASM engine by checksum.
    
    Uses simple FIFO eviction (keeps last 10 entries).
    For systems with many policy snapshots, consider upgrading to LRU cache.
    """
    if checksum:
        _WASM_CACHE[checksum] = engine
        logger.debug(f"Cached WASM engine for checksum {checksum[:8]}...")
        # Limit cache size (keep last 10) - FIFO eviction
        # Note: If you have many personalized policies, consider upgrading to LRU cache
        if len(_WASM_CACHE) > 10:
            oldest_key = next(iter(_WASM_CACHE))
            logger.debug(f"Evicting oldest WASM cache entry: {oldest_key[:8]}... (cache size limit: 10)")
            del _WASM_CACHE[oldest_key]


def _json_safe(obj: Any) -> Any:
    """
    Recursively sanitize objects for JSON serialization.
    
    Converts UUID objects to strings, datetime objects to ISO format strings,
    and handles nested dicts/lists. This prevents JSON serialization errors
    when task_facts contains database objects with UUID or datetime fields.
    
    Args:
        obj: Object to sanitize (can be dict, list, UUID, datetime, or any other type)
        
    Returns:
        JSON-serializable version of the object
    """
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_json_safe(v) for v in obj)
    if isinstance(obj, set):
        return [_json_safe(v) for v in obj]
    return obj


class OpaWasm:
    """
    OPA WASM runtime wrapper.
    
    Supports both wasmtime-based execution (if available) and fallback mode.
    Implements PolicyEngine protocol for consistent evaluation interface.
    [cite: 68, 91]
    """
    def __init__(self, wasm_bytes: bytes, checksum: Optional[str] = None):
        """
        Initialize OPA WASM engine.
        
        Args:
            wasm_bytes: Compiled WASM binary bytes
            checksum: Optional checksum for caching
        """
        self._wasm_bytes = wasm_bytes
        self._checksum = checksum
        self._engine = None
        self._instance = None
        self._memory = None  # Store reference to imported memory
        self._wasmtime_available = False
        self._entrypoint_id = 0  # Default fallback entrypoint ID
        self._entrypoint_name = None  # Resolved entrypoint name (e.g., 'pkg/result', 'authz/allow')
        
        # Runtime check for wasmtime availability (not frozen at import time)
        if is_wasmtime_available():
            try:
                # Initialize wasmtime engine
                import wasmtime  # type: ignore
                logger.debug("wasmtime import successful, creating Engine...")
                engine = wasmtime.Engine()
                logger.debug("wasmtime Engine created, creating Module...")
                module = wasmtime.Module(engine, wasm_bytes)
                logger.debug("wasmtime Module created, creating Store...")
                store = wasmtime.Store(engine)
                
                # OPA WASM modules require host function imports
                # Check what imports the module expects
                imports = module.imports  # imports is a property, not a method
                
                # Build import info list (module, name, type are properties, not methods)
                import_info = []
                for imp in imports:
                    module_name = imp.module
                    func_name = imp.name
                    ty = imp.type
                    import_info.append((module_name, func_name, ty))
                
                logger.debug(f"WASM module requires {len(import_info)} imports: {[(m, n) for m, n, _ in import_info]}")
                
                # Create linker and provide stub implementations for OPA host functions
                linker = wasmtime.Linker(engine)
                
                # Helper functions for version-safe type detection
                def _ft_results(ft: "wasmtime.FuncType"):
                    r = ft.results
                    return list(r() if callable(r) else r)
                
                def _is_i32(v) -> bool:
                    return str(v) in ("i32", "ValType.i32")
                
                def _is_i64(v) -> bool:
                    return str(v) in ("i64", "ValType.i64")
                
                def make_stub(func_name: str, ty: "wasmtime.FuncType"):
                    results = _ft_results(ty)
                    if results and (_is_i32(results[0]) or _is_i64(results[0])):
                        return lambda *args: 0
                    return lambda *args: None
                
                # 1) Define memory exactly as declared by the module
                mem_import_ty = None
                for mod_name, name, ty in import_info:
                    if mod_name == "env" and name == "memory":
                        if not isinstance(ty, wasmtime.MemoryType):
                            raise RuntimeError(f"env::memory import is not MemoryType: {ty}")
                        mem_import_ty = ty
                        break
                
                if mem_import_ty is None:
                    raise RuntimeError("OPA WASM expects env::memory import but it was not found")
                
                memory = wasmtime.Memory(store, mem_import_ty)
                self._memory = memory  # Keep reference for evaluation
                linker.define(store, "env", "memory", memory)
                logger.debug(f"Defined env::memory import using module-declared type: {mem_import_ty}")
                
                # 2) Define function imports
                for mod_name, name, ty in import_info:
                    if mod_name == "env" and name == "memory":
                        continue
                    
                    if isinstance(ty, wasmtime.FuncType):
                        stub = make_stub(name, ty)
                        func = wasmtime.Func(store, ty, stub)
                        linker.define(store, mod_name, name, func)
                    else:
                        logger.warning(f"Unsupported import type {mod_name}::{name}: {ty}")
                
                logger.debug("wasmtime Linker configured with host functions, creating Instance...")
                self._instance = linker.instantiate(store, module)
                self._store = store
                self._wasmtime_available = True
                
                # Resolve entrypoint by name during initialization (package-agnostic)
                self._resolve_entrypoint()
                
                logger.info(f"OPA WASM engine loaded with wasmtime ({len(wasm_bytes)} bytes, checksum={checksum[:8] if checksum else 'N/A'}..., entrypoint={self._entrypoint_name or 'default'})")
            except Exception as e:
                logger.warning(f"Failed to load WASM with wasmtime: {type(e).__name__}: {e}. Using fallback mode.", exc_info=True)
                self._wasmtime_available = False
        else:
            logger.warning(f"wasmtime import check failed - OPA WASM engine loaded in fallback mode ({len(wasm_bytes)} bytes)")
            self._wasmtime_available = False

    @staticmethod
    def load_from_bytes(wasm_bytes: bytes, checksum: Optional[str] = None) -> "OpaWasm":
        """
        Loads the compiled .wasm policy artifact.
        
        Args:
            wasm_bytes: Compiled WASM binary bytes
            checksum: Optional checksum for caching
            
        Returns:
            OpaWasm instance (cached if checksum provided and available)
        """
        # Check cache first
        if checksum:
            cached = _get_cached_wasm(checksum, wasm_bytes)
            if cached:
                return cached
        
        # Create new instance
        engine = OpaWasm(wasm_bytes, checksum)
        
        # Cache if checksum provided
        # Only cache if engine actually has wasmtime loaded (not fallback mode)
        if checksum and engine._wasmtime_available:
            _cache_wasm(checksum, engine)
        
        return engine

    def _wasm_write(self, memory: Any, store: Any, addr: int, data: bytes) -> None:
        """
        Version-safe WASM memory write helper.
        
        Args:
            memory: wasmtime.Memory instance
            store: wasmtime.Store instance
            addr: Memory address offset
            data: Bytes to write
        """
        if hasattr(memory, 'write'):
            # Most common API: write(store, data, offset)
            memory.write(store, data, addr)
        elif hasattr(memory, 'data'):
            # Newer API: data() returns a memoryview/buffer
            memory_data = memory.data(store)
            memory_data[addr:addr + len(data)] = data
        elif hasattr(memory, 'data_ptr'):
            # Older API: data_ptr() returns a pointer, need ctypes
            import ctypes
            ptr = memory.data_ptr(store)
            size = memory.data_len(store)
            memory_data = (ctypes.c_uint8 * size).from_address(ptr)
            memory_data[addr:addr + len(data)] = data
        else:
            raise RuntimeError("Unsupported wasmtime Memory API - no write/data/data_ptr methods found")
    
    def _wasm_read(self, memory: Any, store: Any, addr: int, length: int) -> bytes:
        """
        Version-safe WASM memory read helper.
        
        Args:
            memory: wasmtime.Memory instance
            store: wasmtime.Store instance
            addr: Memory address offset
            length: Number of bytes to read
            
        Returns:
            Bytes read from memory
        """
        if hasattr(memory, 'read'):
            # Most common API: read(store, offset, length) returns bytes
            return bytes(memory.read(store, addr, length))
        elif hasattr(memory, 'data'):
            # Newer API: data() returns a memoryview/buffer
            memory_data = memory.data(store)
            return bytes(memory_data[addr:addr + length])
        elif hasattr(memory, 'data_ptr'):
            # Older API: data_ptr() returns a pointer, need ctypes
            import ctypes
            ptr = memory.data_ptr(store)
            size = memory.data_len(store)
            memory_data = (ctypes.c_uint8 * size).from_address(ptr)
            return bytes(memory_data[addr:addr + length])
        else:
            raise RuntimeError("Unsupported wasmtime Memory API - no read/data/data_ptr methods found")
    
    def _wasm_get_memory_size(self, memory: Any, store: Any) -> int:
        """
        Get the size of WASM memory in bytes.
        
        Args:
            memory: wasmtime.Memory instance
            store: wasmtime.Store instance
            
        Returns:
            Memory size in bytes
        """
        if hasattr(memory, 'data_len'):
            # Most common API: data_len(store) returns size
            return memory.data_len(store)
        elif hasattr(memory, 'data'):
            # Newer API: data() returns a memoryview/buffer with len()
            memory_data = memory.data(store)
            return len(memory_data)
        elif hasattr(memory, 'data_ptr'):
            # Older API: data_len() method exists
            return memory.data_len(store)
        else:
            # Fallback: try to read a byte to see if memory is accessible
            try:
                self._wasm_read(memory, store, 0, 1)
                # If we can read, estimate size (conservative)
                return 1024 * 1024  # 1MB default
            except Exception:
                return 1024 * 1024  # 1MB default
    
    def _prepare_task_facts_for_wasm(self, task_facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare task_facts for WASM evaluation by sanitizing non-serializable types
        and stripping DB-only fields from governed_facts.
        
        This ensures:
        1. UUID objects are converted to strings
        2. datetime objects are converted to ISO format strings
        3. DB metadata fields (id, created_at, etc.) are removed from governed_facts
           to reduce payload size and keep ABI clean
        
        Args:
            task_facts: Original task_facts dictionary
            
        Returns:
            Sanitized task_facts dictionary safe for JSON serialization
        """
        # Create a copy to avoid mutating the original
        prepared = task_facts.copy()
        
        # Strip DB-only fields from governed_facts if present
        if "governed_facts" in prepared and isinstance(prepared["governed_facts"], list):
            prepared["governed_facts"] = [
                {
                    "subject": f.get("subject"),
                    "predicate": f.get("predicate"),
                    "object_data": f.get("object_data"),
                    "pkg_rule_id": f.get("pkg_rule_id"),
                    # Note: We keep pkg_rule_id as it may be needed by policy rules
                    # but strip: id, fact_id, created_at, valid_from, valid_to, snapshot_id, etc.
                }
                for f in prepared["governed_facts"]
            ]
        
        # Strip DB-only fields from governed_facts_by_subject if present
        if "governed_facts_by_subject" in prepared and isinstance(prepared["governed_facts_by_subject"], dict):
            prepared["governed_facts_by_subject"] = {
                subject: [
                    {
                        "subject": f.get("subject"),
                        "predicate": f.get("predicate"),
                        "object_data": f.get("object_data"),
                        "pkg_rule_id": f.get("pkg_rule_id"),
                    }
                    for f in facts_list
                ]
                for subject, facts_list in prepared["governed_facts_by_subject"].items()
            }
        
        # Recursively sanitize all remaining fields (UUID, datetime, etc.)
        return _json_safe(prepared)
    
    def _wasm_read_null_terminated(self, memory: Any, store: Any, addr: int, max_size: int = 1024 * 1024) -> bytes:
        """
        Read a null-terminated string from WASM memory using chunked reading.
        
        This is safer than scanning byte-by-byte, especially with read() API
        which doesn't allow unbounded scanning.
        
        Args:
            memory: wasmtime.Memory instance
            store: wasmtime.Store instance
            addr: Memory address offset where string starts
            max_size: Maximum size to read (safety limit)
            
        Returns:
            Bytes read until null terminator (excluding null)
        """
        buf = bytearray()
        offset = addr
        chunk_size = 4096  # Read in 4KB chunks
        
        # Read first chunk to check if string starts with null terminator (empty string)
        first_chunk = self._wasm_read(memory, store, offset, min(chunk_size, 1024))
        if not first_chunk:
            # Empty read - return empty bytes
            return b""
        
        # Check if first byte is null terminator (empty string)
        if first_chunk[0] == 0:
            return b""
        
        # Look for null terminator in first chunk
        null_pos = first_chunk.find(b"\x00")
        if null_pos != -1:
            # Found null terminator in first chunk
            buf.extend(first_chunk[:null_pos])
            return bytes(buf)
        
        # No null terminator in first chunk - append it and continue
        buf.extend(first_chunk)
        offset += len(first_chunk)
        
        while len(buf) < max_size:
            # Read next chunk
            remaining = max_size - len(buf)
            read_len = min(chunk_size, remaining)
            chunk = self._wasm_read(memory, store, offset, read_len)
            
            if not chunk:
                break
            
            # Look for null terminator in chunk
            null_pos = chunk.find(b"\x00")
            if null_pos != -1:
                # Found null terminator - append up to it and stop
                buf.extend(chunk[:null_pos])
                break
            
            # No null terminator - append whole chunk and continue
            buf.extend(chunk)
            offset += len(chunk)
            
            if len(buf) >= max_size:
                raise ValueError(f"Result JSON string exceeds {max_size} byte limit")
        
        return bytes(buf)
    
    def _resolve_entrypoint(self) -> None:
        """
        Resolve entrypoint by name at runtime instead of assuming Index 0.
        
        This makes the evaluator package-agnostic. It queries the WASM module's
        entrypoints export to get the mapping (e.g., {'pkg/result': 0, 'authz/allow': 1}),
        then selects the appropriate entrypoint based on priority:
        1. 'authz/allow' (preferred for authorization policies)
        2. 'pkg/result' (common for PKG policies)
        3. First available entrypoint
        4. Index 0 (fallback)
        
        Stores the resolved entrypoint_id and entrypoint_name as instance variables
        for use during evaluation.
        """
        if not self._wasmtime_available or not self._instance or not self._memory:
            logger.debug("Cannot resolve entrypoints: wasmtime not available or instance not initialized")
            self._entrypoint_id = 0
            self._entrypoint_name = None
            return
        
        try:
            import json
            logger.debug("Resolving OPA entrypoints by name...")
            exports = self._instance.exports(self._store)
            entrypoints_func = exports.get("entrypoints")
            opa_json_dump = exports.get("opa_json_dump")
            
            if not entrypoints_func:
                logger.warning("entrypoints function not available in WASM exports, using default entrypoint 0")
                self._entrypoint_id = 0
                self._entrypoint_name = None
                return
            
            if not opa_json_dump:
                logger.warning("opa_json_dump function not available in WASM exports, using default entrypoint 0")
                self._entrypoint_id = 0
                self._entrypoint_name = None
                return
            
            # Call entrypoints() to get object pointer
            entrypoints_obj_ptr = entrypoints_func(self._store)
            logger.debug(f"entrypoints() returned object pointer: {entrypoints_obj_ptr}")
            
            if entrypoints_obj_ptr == 0:
                logger.warning("entrypoints() returned null pointer, using default entrypoint 0")
                self._entrypoint_id = 0
                self._entrypoint_name = None
                return
            
            # Dump the entrypoints object to JSON string
            # Try opa_json_dump first, fallback to opa_value_dump if available
            opa_value_dump = exports.get("opa_value_dump")
            entrypoints_json_ptr = opa_json_dump(self._store, entrypoints_obj_ptr)
            logger.debug(f"opa_json_dump returned JSON pointer: {entrypoints_json_ptr}")
            
            # If opa_json_dump fails or returns 0, try opa_value_dump
            if entrypoints_json_ptr == 0 and opa_value_dump:
                logger.debug("opa_json_dump returned 0, trying opa_value_dump...")
                try:
                    entrypoints_json_ptr = opa_value_dump(self._store, entrypoints_obj_ptr)
                    logger.debug(f"opa_value_dump returned JSON pointer: {entrypoints_json_ptr}")
                except Exception as e:
                    logger.debug(f"opa_value_dump failed: {e}")
            
            if entrypoints_json_ptr == 0:
                logger.warning("Both opa_json_dump and opa_value_dump returned null pointer for entrypoints, using default entrypoint 0")
                self._entrypoint_id = 0
                self._entrypoint_name = None
                return
            
            # Read the JSON string from memory using tmp.py approach:
            # Read ENTIRE memory buffer first, then slice from json_ptr (handles imported memory correctly)
            try:
                # Get memory size using helper method
                memory_size = self._wasm_get_memory_size(self._memory, self._store)
                
                logger.debug(f"Reading entire memory buffer (size: {memory_size}) to find entrypoints JSON at {entrypoints_json_ptr}")
                
                # Read entire memory buffer (like tmp.py does)
                # This ensures we're reading from the same buffer OPA wrote to
                raw_mem = self._wasm_read(self._memory, self._store, 0, memory_size)
                logger.debug(f"Read {len(raw_mem)} bytes from memory buffer")
                
                if entrypoints_json_ptr >= len(raw_mem):
                    logger.warning(f"Entrypoints JSON pointer {entrypoints_json_ptr} is beyond memory size {len(raw_mem)}")
                    self._entrypoint_id = 0
                    self._entrypoint_name = None
                    return
                
                # Slice from json_ptr and split on null terminator (exactly like tmp.py)
                # raw_mem[json_ptr:] gets everything from json_ptr to end
                # .split(b'\0')[0] gets everything up to first null terminator
                data_slice = raw_mem[entrypoints_json_ptr:]
                entrypoints_json_bytes = data_slice.split(b'\0')[0]
                
                logger.debug(f"Extracted {len(entrypoints_json_bytes)} bytes from memory at offset {entrypoints_json_ptr}")
                
                # Log first few bytes for debugging
                if entrypoints_json_bytes:
                    logger.debug(f"First 100 bytes (hex): {entrypoints_json_bytes[:100].hex()}")
                    logger.debug(f"First 100 bytes (ascii): {repr(entrypoints_json_bytes[:100])}")
                else:
                    # Check what's actually at that address
                    logger.debug(f"Memory at {entrypoints_json_ptr}: first 50 bytes (hex): {data_slice[:50].hex()}")
                    logger.debug(f"Memory at {entrypoints_json_ptr}: first 50 bytes (ascii): {repr(data_slice[:50])}")
                    
                    # Also check heap pointer (like tmp.py does)
                    heap_ptr_get = exports.get("opa_heap_ptr_get")
                    if heap_ptr_get:
                        heap_ptr = heap_ptr_get(self._store)
                        logger.debug(f"OPA heap pointer: {heap_ptr}")
                        if heap_ptr > 0 and heap_ptr < len(raw_mem):
                            # Try reading from heap area
                            heap_slice = raw_mem[max(0, heap_ptr - 100):heap_ptr + 200]
                            logger.debug(f"Memory around heap pointer (hex): {heap_slice.hex()[:200]}")
                
            except Exception as e:
                logger.error(f"Error reading entrypoints JSON from memory using tmp.py approach: {e}", exc_info=True)
                entrypoints_json_bytes = b""
            
            if not entrypoints_json_bytes:
                logger.warning(f"Could not read entrypoints JSON from memory at address {entrypoints_json_ptr}, using default entrypoint 0")
                self._entrypoint_id = 0
                self._entrypoint_name = None
                return
            
            # Parse the entrypoint mapping
            entrypoints_json_str = entrypoints_json_bytes.decode('utf-8').strip()
            logger.debug(f"Entrypoints JSON string: {entrypoints_json_str}")
            entrypoint_map = json.loads(entrypoints_json_str)
            
            logger.info(f"OPA entrypoints mapping resolved: {entrypoint_map}")
            
            # Priority Resolution: Look for 'authz/allow', then fallback to 'pkg/result'
            if "authz/allow" in entrypoint_map:
                self._entrypoint_id = entrypoint_map["authz/allow"]
                self._entrypoint_name = "authz/allow"
                logger.info(f"Resolved entrypoint: 'authz/allow' -> index {self._entrypoint_id}")
            elif "pkg/result" in entrypoint_map:
                self._entrypoint_id = entrypoint_map["pkg/result"]
                self._entrypoint_name = "pkg/result"
                logger.info(f"Resolved entrypoint: 'pkg/result' -> index {self._entrypoint_id}")
            elif entrypoint_map:
                # Use first available entrypoint if neither preferred one exists
                self._entrypoint_name = list(entrypoint_map.keys())[0]
                self._entrypoint_id = entrypoint_map[self._entrypoint_name]
                logger.info(
                    f"Resolved entrypoint: '{self._entrypoint_name}' -> index {self._entrypoint_id} "
                    f"(first available from {list(entrypoint_map.keys())})"
                )
            else:
                # Fallback to 0 if nothing matches, but log a warning
                self._entrypoint_id = 0
                self._entrypoint_name = None
                logger.warning("No known entrypoints found in mapping, falling back to index 0")
                
        except Exception as e:
            logger.error(f"Could not resolve entrypoints by name: {e}, falling back to entrypoint 0", exc_info=True)
            self._entrypoint_id = 0
            self._entrypoint_name = None
    
    def evaluate(self, task_facts: Dict[str, Any]) -> EvaluationResult:
        """
        Runs the WASM policy evaluation.
        
        Args:
            task_facts: Input facts dictionary with tags, signals, context
            
        Returns:
            EvaluationResult with subtasks, dag, and provenance
        """
        start_time = time.perf_counter()
        
        # Log evaluation start
        logger.debug({
            "event": "wasm_evaluation_start",
            "checksum": self._checksum[:8] if self._checksum else None,
            "facts_keys": list(task_facts.keys()),
            "wasmtime_available": self._wasmtime_available
        })
        
        if self._wasmtime_available and self._instance:
            try:
                # OPA WASM ABI calling convention
                # See: https://www.openpolicyagent.org/docs/wasm/
                import json
                
                # Access exports - wasmtime API uses .get() method
                exports = self._instance.exports(self._store)
                
                # Use the memory we created in __init__ (imported memory, not exported)
                memory = getattr(self, "_memory", None)
                if memory is None:
                    logger.warning("No memory attached to instance; cannot evaluate")
                    return self._fallback_evaluate(task_facts)
                
                # Log available exports for debugging
                available_exports = list(exports.keys())
                logger.debug(f"Available WASM exports: {available_exports}")
                
                # Get OPA ABI functions from exports
                # IMPORTANT: Use opa_eval (not eval) - opa_eval is the correct OPA ABI function
                opa_eval_ctx_new = exports.get("opa_eval_ctx_new")
                opa_eval_ctx_set_input = exports.get("opa_eval_ctx_set_input")
                opa_eval_ctx_set_entrypoint = exports.get("opa_eval_ctx_set_entrypoint")
                opa_eval_ctx_set_data = exports.get("opa_eval_ctx_set_data")
                
                # Use eval (standard OPA ABI function with signature: eval(ctx_addr) -> i32)
                # opa_eval may have a different signature (e.g., 7 parameters) and should NOT be used
                eval_func = exports.get("eval")
                opa_eval_func = exports.get("opa_eval")  # Keep for reference but don't use
                
                # CRITICAL: Use eval, not opa_eval (opa_eval expects 7 params, eval expects 1)
                opa_eval = eval_func
                if not opa_eval:
                    logger.warning("'eval' export not found - this may cause evaluation failures")
                    # Fallback to opa_eval only if eval doesn't exist (will likely fail)
                    opa_eval = opa_eval_func
                
                opa_eval_ctx_get_result = exports.get("opa_eval_ctx_get_result")
                opa_json_parse = exports.get("opa_json_parse")
                opa_json_dump = exports.get("opa_json_dump")
                opa_malloc = exports.get("opa_malloc")
                
                # Heap pointer functions (may be needed for some OPA ABI versions)
                opa_heap_ptr_get = exports.get("opa_heap_ptr_get")
                opa_heap_ptr_set = exports.get("opa_heap_ptr_set")
                
                # Prefer "opa_free" over "opa_value_free" (both may exist)
                opa_free = exports.get("opa_free") or exports.get("opa_value_free")
                
                # Use cached entrypoint resolved during initialization (package-agnostic)
                # This was resolved by _resolve_entrypoint() during __init__
                # If not resolved yet (e.g., cached instance), resolve now
                if self._entrypoint_name is None and self._wasmtime_available:
                    logger.debug("Entrypoint not resolved yet, resolving now...")
                    self._resolve_entrypoint()
                
                target_entrypoint_id = self._entrypoint_id
                target_rule_name = self._entrypoint_name
                
                if target_rule_name:
                    logger.info(f"Using entrypoint: '{target_rule_name}' -> index {target_entrypoint_id}")
                else:
                    logger.warning(f"Using default entrypoint index {target_entrypoint_id} (entrypoint name not resolved - policy may not match input structure)")
                
                # Check if we have the required functions
                required_funcs = {
                    "opa_eval_ctx_new": opa_eval_ctx_new,
                    "opa_eval_ctx_set_input": opa_eval_ctx_set_input,
                    "eval": opa_eval,  # Must use eval, not opa_eval
                    "opa_eval_ctx_get_result": opa_eval_ctx_get_result,
                    "opa_json_parse": opa_json_parse,
                    "opa_json_dump": opa_json_dump,
                    "opa_malloc": opa_malloc,
                }
                
                missing_funcs = [name for name, func in required_funcs.items() if func is None]
                if missing_funcs:
                    logger.warning(f"WASM module missing required OPA ABI functions: {missing_funcs} - using fallback")
                    return self._fallback_evaluate(task_facts)
                
                if opa_eval == eval_func:
                    logger.debug("Using 'eval' export (standard OPA ABI signature)")
                elif opa_eval == opa_eval_func:
                    logger.warning("Using 'opa_eval' export (may have incorrect signature - expect failures)")
                
                # Sanitize task_facts for JSON serialization (UUID, datetime, etc.)
                # Also strip DB-only fields from governed_facts to reduce payload size
                safe_task_facts = self._prepare_task_facts_for_wasm(task_facts)
                
                # Serialize input to JSON (now safe from UUID/datetime serialization errors)
                input_json = json.dumps(safe_task_facts).encode('utf-8')
                input_len = len(input_json)
                
                # Debug: Log input JSON structure (truncated for readability)
                input_json_str = input_json.decode('utf-8')
                logger.debug(f"Input JSON length: {input_len} bytes")
                logger.debug(f"Input JSON (first 500 chars): {input_json_str[:500]}")
                if "governed_facts" in safe_task_facts:
                    logger.debug(f"Input contains {len(safe_task_facts.get('governed_facts', []))} governed_facts")
                    if safe_task_facts.get("governed_facts"):
                        logger.debug(f"First governed_fact: {safe_task_facts['governed_facts'][0]}")
                
                # Allocate memory for input JSON using opa_malloc
                # opa_malloc returns an integer address
                input_addr = opa_malloc(self._store, input_len)
                
                # Write input JSON to WASM memory using version-safe helper
                self._wasm_write(memory, self._store, input_addr, input_json)
                
                # Parse JSON to get value address
                input_value_addr = opa_json_parse(self._store, input_addr, input_len)
                
                # Parse empty data JSON (some policies may require data to be set)
                # Set data to empty object {} if policy expects it
                data_json = b"{}"
                data_addr = opa_malloc(self._store, len(data_json))
                self._wasm_write(memory, self._store, data_addr, data_json)
                data_value_addr = opa_json_parse(self._store, data_addr, len(data_json))
                
                # Use the resolved entrypoint ID (by name) instead of iterating
                # OPA WASM entrypoints map to package/rule paths:
                # - Entrypoint 0 = first entrypoint (usually data.pkg.result or data.pkg.allow)
                # - Entrypoint 1+ = additional rules/packages
                # If wrong entrypoint is used, result may be empty even if rules match
                result_bytes = None
                result_json_str = None
                successful_entrypoint = None
                result = None
                
                # Create evaluation context (takes no parameters)
                ctx_addr = opa_eval_ctx_new(self._store)
                
                # Set data if function is available (some policies require data)
                if opa_eval_ctx_set_data:
                    opa_eval_ctx_set_data(self._store, ctx_addr, data_value_addr)
                
                # Set entrypoint using the resolved ID
                if opa_eval_ctx_set_entrypoint:
                    logger.debug(f"Using OPA entrypoint {target_entrypoint_id} ({target_rule_name or 'unnamed'})")
                    opa_eval_ctx_set_entrypoint(self._store, ctx_addr, target_entrypoint_id)
                else:
                    logger.debug("opa_eval_ctx_set_entrypoint not available - using default entrypoint")
                
                # Set input
                opa_eval_ctx_set_input(self._store, ctx_addr, input_value_addr)
                
                # Initialize heap pointer if needed (some OPA ABI versions require this)
                if opa_heap_ptr_set and opa_heap_ptr_get:
                    try:
                        # Get current heap pointer and set it (ensures heap is initialized)
                        current_heap = opa_heap_ptr_get(self._store)
                        if current_heap == 0:
                            # Initialize heap pointer to a safe value
                            opa_heap_ptr_set(self._store, 1024)  # Start heap at 1KB offset
                            logger.debug("Initialized OPA heap pointer to 1024")
                        else:
                            logger.debug(f"OPA heap pointer already set: {current_heap}")
                    except Exception as e:
                        logger.debug(f"Could not initialize heap pointer (may not be needed): {e}")
                
                # Evaluate using eval (standard OPA ABI: eval(ctx_addr) -> i32)
                # In wasmtime, we pass store as first parameter: eval(store, ctx_addr)
                try:
                    eval_result = opa_eval(self._store, ctx_addr)
                    logger.debug(f"OPA eval returned status {eval_result} for entrypoint {target_entrypoint_id} ({target_rule_name or 'unnamed'})")
                except Exception as e:
                    error_msg = str(e)
                    if "too few parameters" in error_msg or "too many parameters" in error_msg:
                        logger.error(f"eval function signature mismatch: {e}. This indicates the WASM module may not be compatible.")
                        # Return empty result on signature mismatch
                        if opa_free:
                            opa_free(self._store, input_addr)
                        return self._fallback_evaluate(task_facts)
                    else:
                        # Re-raise non-signature errors
                        raise
                
                if eval_result != 0:
                    logger.debug(f"OPA evaluation returned non-zero status {eval_result} for entrypoint {target_entrypoint_id} (non-zero usually means error)")
                    # Return empty result on evaluation error
                    if opa_free:
                        opa_free(self._store, input_addr)
                    return EvaluationResult(subtasks=[], dag=[], provenance=[])
                
                # Get result value address
                result_value_addr = opa_eval_ctx_get_result(self._store, ctx_addr)
                
                logger.debug(
                    f"OPA result addresses for entrypoint {target_entrypoint_id} ({target_rule_name or 'unnamed'}): "
                    f"eval_result={eval_result}, result_value_addr={result_value_addr} "
                    f"(0=undefined/null, non-zero=valid OPA value)"
                )
                
                if result_value_addr == 0:
                    logger.debug(f"OPA evaluation returned undefined/null (result_value_addr=0) for entrypoint {target_entrypoint_id} - policy rule did not match or returned undefined")
                    # Return empty result when rule doesn't match
                    if opa_free:
                        opa_free(self._store, input_addr)
                    return EvaluationResult(subtasks=[], dag=[], provenance=[])
                
                # Check if result_value_addr looks suspicious (very small or constant)
                if result_value_addr < 1024:
                    logger.warning(f"OPA result_value_addr={result_value_addr} is suspiciously small (may be invalid)")
                
                # Dump result to JSON string in memory
                result_str_addr = opa_json_dump(self._store, result_value_addr)
                
                logger.debug(
                    f"OPA json_dump for entrypoint {target_entrypoint_id}: "
                    f"result_value_addr={result_value_addr} -> result_str_addr={result_str_addr}"
                )
                
                if result_str_addr == 0:
                    logger.debug(f"OPA json_dump returned null address (result_str_addr=0) for entrypoint {target_entrypoint_id} - value may not be JSON-serializable")
                    # Return empty result when JSON dump fails
                    if opa_free:
                        opa_free(self._store, input_addr)
                    return EvaluationResult(subtasks=[], dag=[], provenance=[])
                
                # Check if result_str_addr looks suspicious
                if result_str_addr < 1024:
                    logger.warning(f"OPA result_str_addr={result_str_addr} is suspiciously small (may be invalid)")
                
                # Read result JSON string from memory using same approach as entrypoints
                # (read entire memory buffer, then slice - handles imported memory correctly)
                try:
                    memory_size = self._wasm_get_memory_size(memory, self._store)
                    logger.debug(f"Reading result JSON from memory at address {result_str_addr} (memory size: {memory_size})")
                    
                    if result_str_addr >= memory_size:
                        logger.warning(f"Result JSON pointer {result_str_addr} is beyond memory size {memory_size}")
                        result_bytes = b""
                    else:
                        # Read entire memory buffer (like we do for entrypoints)
                        raw_mem = self._wasm_read(memory, self._store, 0, memory_size)
                        
                        # Slice from result_str_addr and split on null terminator
                        result_slice = raw_mem[result_str_addr:]
                        result_bytes = result_slice.split(b'\0')[0]
                        
                        logger.debug(
                            f"OPA result read for entrypoint {target_entrypoint_id} ({target_rule_name or 'unnamed'}): "
                            f"result_str_addr={result_str_addr}, bytes_read={len(result_bytes) if result_bytes else 0}"
                        )
                        
                        # Log first bytes for debugging if empty
                        if not result_bytes:
                            logger.debug(f"Result memory at {result_str_addr}: first 50 bytes (hex): {result_slice[:50].hex()}")
                            logger.debug(f"Result memory at {result_str_addr}: first 50 bytes (ascii): {repr(result_slice[:50])}")
                            
                            # Check heap pointer for diagnostics
                            heap_ptr_get = exports.get("opa_heap_ptr_get")
                            if heap_ptr_get:
                                heap_ptr = heap_ptr_get(self._store)
                                logger.debug(f"OPA heap pointer: {heap_ptr}")
                except Exception as e:
                    logger.warning(f"Error reading result JSON using full-memory approach: {e}, falling back to null-terminated read", exc_info=True)
                    # Fallback to original method
                    result_bytes = self._wasm_read_null_terminated(memory, self._store, result_str_addr)
                
                if result_bytes:
                    # Check first byte to see if it's null-terminated immediately
                    if len(result_bytes) == 0:
                        logger.debug(f"Entrypoint {target_entrypoint_id} returned empty string (first byte was null terminator)")
                    else:
                        result_json_str = result_bytes.decode('utf-8').strip()
                        logger.debug(f"Entrypoint {target_entrypoint_id} result (first 100 chars): {result_json_str[:100]}")
                        
                        if result_json_str and result_json_str != "null":
                            successful_entrypoint = target_entrypoint_id
                            logger.info(f"Found non-empty result at entrypoint {target_entrypoint_id} ({target_rule_name or 'unnamed'}): {len(result_bytes)} bytes, content: {result_json_str[:200]}")
                        elif result_json_str == "null":
                            logger.debug(f"Entrypoint {target_entrypoint_id} returned JSON null (policy returned null/undefined)")
                        else:
                            logger.debug(f"Entrypoint {target_entrypoint_id} returned empty string after decode/strip")
                else:
                    logger.debug(f"Entrypoint {target_entrypoint_id} returned empty bytes (null-terminated string starts with \\0)")
                
                # Free data memory
                if opa_free:
                    opa_free(self._store, data_addr)
                
                if not result_bytes or not result_json_str or result_json_str == "null":
                    if successful_entrypoint is None:
                        logger.debug(f"Entrypoint {target_entrypoint_id} ({target_rule_name or 'unnamed'}) returned empty/null results - policy may have no matches")
                        if opa_free:
                            opa_free(self._store, input_addr)
                        return EvaluationResult(subtasks=[], dag=[], provenance=[])
                
                # Parse result JSON (result_json_str already decoded and stripped above)
                try:
                    logger.debug(f"OPA result JSON (first 200 chars): {result_json_str[:200]}")
                    result = json.loads(result_json_str)
                except UnicodeDecodeError as e:
                    logger.error(f"Failed to decode OPA result as UTF-8: {e}. Raw bytes (hex, first 100): {result_bytes[:100].hex() if result_bytes else 'N/A'}")
                    return self._fallback_evaluate(task_facts)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse OPA result JSON: {e}. Result string (first 500 chars): {result_json_str[:500] if result_json_str else 'N/A'}")
                    # Log raw bytes for debugging
                    if result_bytes:
                        logger.debug(f"Raw bytes (hex, first 200): {result_bytes[:200].hex()}")
                    return self._fallback_evaluate(task_facts)
                
                # Free allocated memory
                if opa_free:
                    opa_free(self._store, input_addr)
                    # Note: OPA manages its own memory for value_addr and result_str_addr
                
                parsed_result = self._parse_opa_result(result)
                
                elapsed = time.perf_counter() - start_time
                logger.info(f"WASM evaluation completed in {elapsed:.3f}s (checksum={self._checksum[:8] if self._checksum else 'N/A'}...)")
                
                return parsed_result
            except Exception as e:
                logger.error(f"WASM evaluation failed: {e}. Falling back to default behavior.", exc_info=True)
                return self._fallback_evaluate(task_facts)
        else:
            # Fallback mode: return basic structure
            logger.debug("WASM evaluation in fallback mode (wasmtime not available)")
            return self._fallback_evaluate(task_facts)
    
    def _call_opa_entrypoint(self, task_facts: Dict[str, Any]) -> Dict[str, Any]:
        """Call OPA entrypoint function (placeholder - implement based on your WASM interface)."""
        # This would call the actual OPA WASM entrypoint
        # For now, return a structured default
        return {
            "result": {
                "subtasks": [],
                "dag": [],
                "rules": []
            }
        }
    
    def _parse_opa_result(self, opa_result: Any) -> EvaluationResult:
        """
        Parse OPA result into EvaluationResult format.
        
        Handles multiple OPA result formats:
        1. Dict with "result" key: {"result": {"subtasks": [...], ...}}
        2. List of dicts with "result" keys: [{"result": {"subtasks": [...], ...}}, ...]
        3. List directly: [{"subtasks": [...], ...}]
        
        Args:
            opa_result: Parsed JSON result from OPA (can be dict or list)
            
        Returns:
            EvaluationResult with subtasks, dag, and provenance
        """
        # Handle list format (OPA sometimes returns list of results)
        if isinstance(opa_result, list):
            if not opa_result:
                return EvaluationResult(subtasks=[], dag=[], provenance=[])
            
            # If list contains dicts with "result" keys, extract and merge them
            all_subtasks = []
            all_dag = []
            all_provenance = []
            
            for item in opa_result:
                if isinstance(item, dict):
                    # Check if item has "result" key
                    if "result" in item:
                        result_data = item["result"]
                    else:
                        # Item itself is the result
                        result_data = item
                    
                    # Extract fields
                    if isinstance(result_data, dict):
                        all_subtasks.extend(result_data.get("subtasks", []))
                        all_dag.extend(result_data.get("dag", []))
                        all_provenance.extend(result_data.get("rules", result_data.get("provenance", [])))
            
            return EvaluationResult(
                subtasks=all_subtasks,
                dag=all_dag,
                provenance=all_provenance
            )
        
        # Handle dict format
        elif isinstance(opa_result, dict):
            result_data = opa_result.get("result", opa_result)  # Fallback to opa_result itself if no "result" key
            if not isinstance(result_data, dict):
                result_data = {}
            
            return EvaluationResult(
                subtasks=result_data.get("subtasks", []),
                dag=result_data.get("dag", []),
                provenance=result_data.get("rules", result_data.get("provenance", []))
            )
        
        # Unknown format - return empty result
        else:
            logger.warning(f"Unexpected OPA result format: {type(opa_result)}, expected dict or list")
            return EvaluationResult(subtasks=[], dag=[], provenance=[])
    
    def _fallback_evaluate(self, task_facts: Dict[str, Any]) -> EvaluationResult:
        """Fallback evaluation when WASM runtime is unavailable."""
        logger.debug(f"WASM fallback evaluation for facts: {list(task_facts.keys())}")
        # Return empty result structure - policy should handle this gracefully
        return EvaluationResult(
            subtasks=[],
            dag=[],
            provenance=[{"rule_id": "wasm-fallback", "note": "WASM runtime unavailable"}]
        )


class NativeRuleEngine:
    """
    Native Python rule engine that evaluates rules from the database.
    
    Processes rules with conditions and emissions to generate subtasks and DAG.
    Implements PolicyEngine protocol for consistent evaluation interface.
    [cite: 62, 93]
    """
    def __init__(self, rules: Optional[List[Dict[str, Any]]]):
        """
        Initialize native rule engine.
        
        Args:
            rules: List of rule dictionaries from pkg_policy_rules table
        """
        self._rules = rules or []
        logger.info(f"NativeRuleEngine loaded with {len(self._rules)} rules")
        
        # Validate rules structure
        if self._rules:
            for rule in self._rules:
                if not isinstance(rule.get("conditions"), list):
                    logger.warning(f"Rule {rule.get('rule_name', 'unknown')} has invalid conditions structure")
                if not isinstance(rule.get("emissions"), list):
                    logger.warning(f"Rule {rule.get('rule_name', 'unknown')} has invalid emissions structure")
    
    def run(self, task_facts: Dict[str, Any]) -> EvaluationResult:
        """
        Runs the native rule evaluation chain.
        
        Args:
            task_facts: Input facts dictionary with tags, signals, context
            
        Returns:
            EvaluationResult with subtasks, dag, and provenance
        """
        start_time = time.perf_counter()
        
        # Log evaluation start
        logger.debug({
            "event": "native_evaluation_start",
            "rule_count": len(self._rules),
            "facts_keys": list(task_facts.keys())
        })
        
        from ...predicates.evaluator import PredicateEvaluator
        
        evaluator = PredicateEvaluator()
        matched_rules = []
        subtasks = []
        provenance = []
        
        # Validate task_facts structure
        if not isinstance(task_facts, dict):
            logger.warning(f"Invalid task_facts type: {type(task_facts)}, expected dict")
            return EvaluationResult(subtasks=[], dag=[], provenance=[])
        
        # Evaluate rules in priority order
        for rule in sorted(self._rules, key=lambda r: r.get("priority", 0), reverse=True):
            rule_name = rule.get("rule_name", "unknown")
            rule_id = rule.get("id")
            
            # Check rule conditions
            conditions = rule.get("conditions", [])
            
            if self._evaluate_conditions(conditions, task_facts, evaluator):
                # Rule matched - process emissions
                emissions = rule.get("emissions", [])
                rule_subtasks = self._process_emissions(emissions, rule_id, rule_name)
                subtasks.extend(rule_subtasks)
                
                # Add provenance
                provenance.append({
                    "rule_id": str(rule_id) if rule_id else rule_name,
                    "rule_name": rule_name,
                    "rule_priority": rule.get("priority", 0),
                    "weight": rule.get("weight", 1.0),
                    "matched_conditions": len(conditions),
                    "emissions_count": len(emissions)
                })
                
                matched_rules.append(rule)
        
        # Build DAG from rule relationships and emissions
        dag = self._build_dag(matched_rules, subtasks)
        
        elapsed = time.perf_counter() - start_time
        logger.info(f"NativeRuleEngine evaluated {len(matched_rules)}/{len(self._rules)} matching rules in {elapsed:.3f}s")
        
        return EvaluationResult(
            subtasks=subtasks,
            dag=dag,
            provenance=provenance
        )
    
    # Alias for Protocol compatibility
    def evaluate(self, task_facts: Dict[str, Any]) -> EvaluationResult:
        """Alias for run() to match PolicyEngine protocol."""
        return self.run(task_facts)
    
    def _evaluate_conditions(
        self, 
        conditions: List[Dict[str, Any]], 
        task_facts: Dict[str, Any],
        evaluator: Any
    ) -> bool:
        """
        Evaluate rule conditions against task facts.
        
        Uses PredicateEvaluator for declarative condition evaluation.
        
        Args:
            conditions: List of condition dictionaries
            task_facts: Input facts
            evaluator: PredicateEvaluator instance
            
        Returns:
            True if all conditions match
        """
        if not conditions:
            # No conditions means rule always matches
            return True
        
        # Build evaluation context from task_facts
        context = {
            "tags": task_facts.get("tags", []),
            "signals": task_facts.get("signals", {}),
            "context": task_facts.get("context", {})
        }
        
        # Flatten context for easier access
        for key, value in task_facts.items():
            if key not in context:
                context[key] = value
        
        # Evaluate each condition
        for condition in conditions:
            condition_type = condition.get("condition_type")
            operator = condition.get("operator")
            condition_key = condition.get("condition_key") or condition.get("field_path", "")
            value = condition.get("value")
            
            # Use condition_type to determine evaluation strategy
            if condition_type == "TAG":
                # Check if tag exists in tags list
                if not self._check_condition(condition, context, condition_type="TAG"):
                    logger.debug(f"Condition failed: TAG {condition_key} not in {context.get('tags', [])}")
                    return False
            elif condition_type == "SIGNAL":
                # Check signal value using operator
                if not self._check_condition(condition, context, condition_type="SIGNAL"):
                    logger.debug(f"Condition failed: SIGNAL {condition_key} {operator} {value}")
                    return False
            elif condition_type == "FACT":
                # Check fact predicate using PredicateEvaluator
                if not self._check_condition(condition, context, condition_type="FACT"):
                    logger.debug(f"Condition failed: FACT {condition_key} {operator} {value}")
                    return False
            elif condition_type == "SEMANTIC":
                # Check if a specific category exists in semantic context with sufficient similarity
                # e.g., condition_key="hvac_fault", operator="EXISTS", value=0.9 (min similarity)
                if not self._check_condition(condition, context, condition_type="SEMANTIC"):
                    logger.debug(f"Condition failed: SEMANTIC {condition_key} not found in semantic_context")
                    return False
            else:
                # Default: use field_path-based evaluation
                if not self._check_condition(condition, context):
                    logger.debug(f"Condition failed: {condition_key} {operator} {value}")
                    return False
        
        return True
    
    def _check_condition(
        self, 
        condition: Dict[str, Any], 
        context: Dict[str, Any],
        condition_type: Optional[str] = None
    ) -> bool:
        """
        Check a single condition against context.
        
        Args:
            condition: Condition dictionary
            context: Evaluation context
            condition_type: Optional condition type override
            
        Returns:
            True if condition matches
        """
        condition_type = condition_type or condition.get("condition_type")
        condition_key = condition.get("condition_key") or condition.get("field_path", "")
        operator = condition.get("operator", "EXISTS")
        value = condition.get("value")
        
        # Handle condition type-specific logic
        if condition_type == "TAG":
            tags = context.get("tags", [])
            if operator == "IN" or operator == "EXISTS":
                return condition_key in tags
            elif operator == "=":
                return condition_key in tags
            else:
                return False
        
        elif condition_type == "SIGNAL":
            signals = context.get("signals", {})
            field_value = signals.get(condition_key)
            return self._evaluate_operator(field_value, operator, value)
        
        elif condition_type == "FACT":
            # For FACT conditions, query governed_facts injected by hydrate_governed_facts()
            # condition_key is the subject, predicate comes from condition, operator checks existence/value
            governed_facts = context.get("governed_facts", [])
            subject = condition_key  # e.g., "guest:Ben"
            predicate = condition.get("predicate") or condition.get("field_path", "")
            expected_value = value
            
            # Filter facts matching subject and predicate
            matching_facts = [
                f for f in governed_facts
                if f.get("subject") == subject and f.get("predicate") == predicate
            ]
            
            if operator == "EXISTS" or operator == "=":
                # Check if fact exists
                return len(matching_facts) > 0
            elif operator == "!=":
                # Check if fact does NOT exist
                return len(matching_facts) == 0
            elif matching_facts:
                # For other operators, check object_data value
                # Use the latest fact (first in list, already sorted by created_at DESC)
                fact_object = matching_facts[0].get("object_data", {})
                if isinstance(fact_object, dict):
                    # Check if expected_value matches any value in object_data
                    if expected_value in fact_object.values():
                        return True
                    # Or check if expected_value matches object_data itself
                    return self._evaluate_operator(fact_object, operator, expected_value)
                else:
                    # If object_data is not a dict, compare directly
                    return self._evaluate_operator(fact_object, operator, expected_value)
            
            return False
        
        elif condition_type == "SEMANTIC":
            # Check if a specific category exists in our recent semantic context
            # e.g., condition_key="hvac_fault", operator="EXISTS", value=0.9 (min similarity threshold)
            context_memories = context.get("semantic_context", [])
            target_category = condition_key
            
            # Default minimum similarity threshold
            min_similarity = value if value is not None else 0.85
            
            for memory in context_memories:
                memory_category = memory.get("category")
                memory_similarity = memory.get("similarity", 0.0)
                
                if memory_category == target_category:
                    if operator == "EXISTS" or operator == "=":
                        # Check if similarity meets threshold
                        if memory_similarity >= min_similarity:
                            return True
                    elif operator == ">=":
                        # Check if similarity is greater than or equal to threshold
                        if memory_similarity >= min_similarity:
                            return True
                    elif operator == ">":
                        # Check if similarity is greater than threshold
                        if memory_similarity > min_similarity:
                            return True
                    else:
                        # For other operators, use similarity comparison
                        return self._evaluate_operator(memory_similarity, operator, min_similarity)
            
            return False
        
        else:
            # Default: use field_path-based evaluation
            field_path = condition.get("field_path", condition_key)
            field_value = self._get_field_value(field_path, context)
            return self._evaluate_operator(field_value, operator, value)
    
    def _evaluate_operator(self, field_value: Any, operator: str, expected_value: Any) -> bool:
        """
        Evaluate operator-based comparison.
        
        Args:
            field_value: Actual value from context
            operator: Comparison operator (=, !=, >=, <=, >, <, IN, EXISTS, MATCHES)
            expected_value: Expected value to compare against
            
        Returns:
            True if comparison matches
        """
        if operator == "=":
            return field_value == expected_value
        elif operator == "!=":
            return field_value != expected_value
        elif operator == ">=":
            try:
                return field_value >= expected_value
            except TypeError:
                logger.warning(f"Cannot compare {type(field_value)} >= {type(expected_value)}")
                return False
        elif operator == "<=":
            try:
                return field_value <= expected_value
            except TypeError:
                logger.warning(f"Cannot compare {type(field_value)} <= {type(expected_value)}")
                return False
        elif operator == ">":
            try:
                return field_value > expected_value
            except TypeError:
                logger.warning(f"Cannot compare {type(field_value)} > {type(expected_value)}")
                return False
        elif operator == "<":
            try:
                return field_value < expected_value
            except TypeError:
                logger.warning(f"Cannot compare {type(field_value)} < {type(expected_value)}")
                return False
        elif operator == "IN":
            if isinstance(expected_value, list):
                return field_value in expected_value
            else:
                return field_value == expected_value
        elif operator == "EXISTS":
            return field_value is not None
        elif operator == "MATCHES":
            # Regex pattern matching
            import re
            if isinstance(expected_value, str):
                try:
                    return bool(re.match(expected_value, str(field_value)))
                except re.error:
                    logger.warning(f"Invalid regex pattern: {expected_value}")
                    return False
            return False
        else:
            logger.warning(f"Unsupported operator: {operator}")
            return False
    
    def _get_field_value(self, field_path: str, context: Dict[str, Any]) -> Any:
        """Get value from context using dot-notation path."""
        parts = field_path.split(".")
        value = context
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit():
                value = value[int(part)] if int(part) < len(value) else None
            else:
                return None
        return value
    
    def _process_emissions(
        self, 
        emissions: List[Dict[str, Any]], 
        rule_id: Any,
        rule_name: str
    ) -> List[Dict[str, Any]]:
        """Process rule emissions into subtasks."""
        subtasks = []
        
        for emission in emissions:
            subtask_type = emission.get("subtask_type")
            subtask_name = emission.get("subtask_name", f"{rule_name}_subtask")
            params = emission.get("params", {})
            
            subtask = {
                "name": subtask_name,
                "type": subtask_type,
                "params": params,
                "rule_id": rule_id,
                "rule_name": rule_name
            }
            subtasks.append(subtask)
        
        return subtasks
    
    def _build_dag(
        self, 
        matched_rules: List[Dict[str, Any]], 
        subtasks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Build DAG edges from rule relationships and emissions.
        
        Uses relationship_type from emissions to determine proper DAG topology:
        - EMITS: Independent subtask (no dependencies)
        - ORDERS: Sequential dependency (depends on previous)
        - GATE: Conditional dependency (waits for condition)
        
        Args:
            matched_rules: List of matched rules
            subtasks: List of generated subtasks
            
        Returns:
            List of DAG edge dictionaries
        """
        dag = []
        
        if not subtasks:
            return dag
        
        # Build subtask index by name for quick lookup
        subtask_map = {st["name"]: st for st in subtasks}
        
        # Process emissions to build proper DAG
        for rule in matched_rules:
            emissions = rule.get("emissions", [])
            rule_name = rule.get("rule_name", "unknown")
            
            for i, emission in enumerate(emissions):
                relationship_type = emission.get("relationship_type", "EMITS")
                subtask_name = emission.get("subtask_name")
                
                if not subtask_name or subtask_name not in subtask_map:
                    continue
                
                # Handle different relationship types
                if relationship_type == "ORDERS":
                    # Sequential dependency: depends on previous emission from same rule
                    if i > 0:
                        prev_emission = emissions[i - 1]
                        prev_subtask = prev_emission.get("subtask_name")
                        if prev_subtask and prev_subtask in subtask_map:
                            dag.append({
                                "from": prev_subtask,
                                "to": subtask_name,
                                "type": "sequential",
                                "rule": rule_name
                            })
                elif relationship_type == "GATE":
                    # Conditional dependency: wait for condition
                    # For now, we'll use rule priority to determine gates
                    # In full implementation, you'd check pkg_rule_conditions for gate conditions
                    gate_source = rule.get("metadata", {}).get("gate_source")
                    if gate_source and gate_source in subtask_map:
                        dag.append({
                            "from": gate_source,
                            "to": subtask_name,
                            "type": "gate",
                            "rule": rule_name
                        })
                # EMITS: No dependencies (independent subtask)
        
        # Fallback: if no relationships defined, create sequential chain
        if not dag and len(subtasks) > 1:
            logger.debug("No explicit relationships found, creating sequential DAG")
            for i in range(1, len(subtasks)):
                dag.append({
                    "from": subtasks[i-1]["name"],
                    "to": subtasks[i]["name"],
                    "type": "sequential",
                    "rule": "auto-generated"
                })
        
        return dag

# --- Engine Registry ---

ENGINE_REGISTRY: Dict[str, type] = {
    "wasm": OpaWasm,
    "native": NativeRuleEngine,
}


def register_engine(engine_type: str, engine_class: type) -> None:
    """
    Register a new engine type in the registry.
    
    Args:
        engine_type: Engine type identifier (e.g., 'llm', 'graph')
        engine_class: Engine class implementing PolicyEngine protocol
    """
    if not issubclass(engine_class, PolicyEngine) if hasattr(PolicyEngine, '__subclasshook__') else True:
        logger.warning(f"Engine class {engine_class} may not implement PolicyEngine protocol")
    ENGINE_REGISTRY[engine_type] = engine_class
    logger.info(f"Registered engine type '{engine_type}': {engine_class.__name__}")


# --- Main Implementation ---

class PKGEvaluator:
    """
    Implements the PKGEvaluator with Cortex Memory Integration.
    
    This class handles the transition from raw perception to grounded policy.
    It uses a PKGClient to 'hydrate' facts from Unified Memory before evaluation.
    
    Architecture: PKGEvaluator evolves from a stateless rule-checker into a
    Contextually Hydrated Reasoning Engine that bridges 'Now' (Current Task)
    with 'Always' (Historical context/KG).
    """
    
    def __init__(self, snapshot: PKGSnapshotData, pkg_client: Optional[PKGClient] = None):
        """
        Initializes the evaluator by loading the specified snapshot's engine.
        [cite: 86]
        
        Uses ENGINE_REGISTRY for dynamic engine selection, enabling
        easy extension to new engine types (e.g., LLM, graph-based).
        
        Args:
            snapshot: PKGSnapshotData instance from PKGClient
            pkg_client: Optional PKGClient facade for Cortex memory access.
                       If provided, enables semantic context hydration.
        """
        self.version: str = snapshot.version  # [cite: 87]
        self.engine_type: str = snapshot.engine  # [cite: 88]
        # Expose snapshot identity for downstream orchestration (capability discovery, audit)
        self.snapshot_id: int = snapshot.id
        self.snapshot = snapshot
        self.loaded_at: float = time.time()  # [cite: 89]
        self.pkg_client = pkg_client
        self.engine: Optional[PolicyEngine] = None

        # Use engine registry for dynamic engine selection
        engine_class = ENGINE_REGISTRY.get(self.engine_type)
        
        if not engine_class:
            raise ValueError(
                f"Unknown engine type '{self.engine_type}' for snapshot {self.version}. "
                f"Available engines: {list(ENGINE_REGISTRY.keys())}"
            )
        
        if self.engine_type == 'wasm':
            if not snapshot.wasm_artifact:
                raise ValueError(f"Snapshot {self.version} has engine 'wasm' but no 'wasm_artifact'.")
            # Load the OPA WASM binary bytes into the runtime [cite: 90]
            # Use checksum for caching
            self.engine = OpaWasm.load_from_bytes(
                snapshot.wasm_artifact, 
                checksum=snapshot.checksum
            )  # [cite: 91]
            logger.info(f"PKGEvaluator initialized with WASM engine (version: {self.version}, checksum={snapshot.checksum[:8] if snapshot.checksum else 'N/A'}..., cortex={'enabled' if pkg_client else 'disabled'})")
        else:
            # Load the native rule definitions [cite: 92]
            self.engine = NativeRuleEngine(snapshot.rules)  # [cite: 93]
            logger.info(f"PKGEvaluator initialized with native engine (version: {self.version}, {len(snapshot.rules) if snapshot.rules else 0} rules, cortex={'enabled' if pkg_client else 'disabled'})")

    async def hydrate_semantic_context(
        self, 
        task_facts: Dict[str, Any], 
        embedding: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Hydrates task_facts with semantic context from Unified Memory.
        
        This bridges 'Now' (Current Task) with 'Always' (Historical context/KG).
        The semantic memory retrieved from v_unified_cortex_memory becomes a
        First-Class Fact that rules can query to understand history and world-state.
        
        Args:
            task_facts: Input facts dictionary (will be modified in-place)
            embedding: Optional 1024d embedding vector for semantic similarity search.
                      If None, hydration is skipped.
        
        Returns:
            Hydrated task_facts dictionary with semantic_context injected.
        
        Note:
            This method automatically excludes the current task_id from semantic search
            to prevent the "Identity Match" problem where the current task returns itself
            as the #1 match. The task_id is extracted from task_facts (either top-level
            or nested in context.task_id).
        """
        if not self.pkg_client or not embedding:
            return task_facts

        try:
            # Extract task_id from task_facts to exclude from semantic search
            # Check both top-level and nested in context (for compatibility)
            current_task_id = (
                task_facts.get("task_id") 
                or task_facts.get("context", {}).get("task_id")
            )

            # Query the Unified Memory View (v_unified_cortex_memory)
            # Exclude current task to prevent self-retrieval
            memory_bundle = await self.pkg_client.get_semantic_context(
                embedding=embedding,
                limit=5,
                min_similarity=0.85,
                exclude_task_id=current_task_id
            )
            
            # Inject memory bundle into facts as First-Class Fact
            task_facts["semantic_context"] = memory_bundle
            
            # Extract grounded metadata for easier rule access
            task_facts["memory_hits"] = [m.get("category") for m in memory_bundle if m.get("category")]
            
            logger.debug(
                f"[PKG] Hydrated task {current_task_id or 'unknown'} with {len(memory_bundle)} memory nodes"
                + (" (excluded self)" if current_task_id else "")
            )
            return task_facts
        except Exception as e:
            logger.error(f"[PKG] Semantic hydration failed: {e}", exc_info=True)
            return task_facts

    async def hydrate_governed_facts(
        self,
        task_facts: Dict[str, Any],
        snapshot_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Hydrates task_facts with active facts from the facts table.
        
        This enables policy feedback loops where facts emitted by previous rule evaluations
        become available for subsequent evaluations. The system transforms from a "stateless
        rule-checker" into a "stateful, cognitive operating system" that remembers the
        consequences of its own prior decisions.
        
        Queries facts table for:
        - Active facts (valid_from <= now() AND (valid_to IS NULL OR valid_to > now()))
        - All facts (not filtered to PKG-governed only) - includes system facts, initialization facts, etc.
        - Snapshot-scoped (snapshot_id matches current snapshot)
        
        Uses subject-specific hydration to keep payload small - only hydrates facts where
        subject matches the current task's subject (if available).
        
        Args:
            task_facts: Input facts dictionary (will be modified in-place)
            snapshot_id: Optional snapshot ID (defaults to current snapshot if not provided)
        
        Returns:
            Hydrated task_facts dictionary with governed_facts injected.
        
        Note:
            Facts are injected as structured SPO triples, maintaining abstraction.
            Rules can query them using the FACT condition type in NativeRuleEngine.
            
            Future enhancement: Consider caching active facts in Redis, keyed by
            (snapshot_id, subject), and invalidating on fact emission.
        """
        if not self.pkg_client:
            return task_facts

        try:
            # If caller didn't pass snapshot_id explicitly, allow passing it via task_facts.
            # This enables snapshot-scoped governed-facts hydration from API payloads while
            # keeping the PKGManager input contract (snapshot_id can live under context).
            if snapshot_id is None and isinstance(task_facts, dict):
                ctx = task_facts.get("context") if isinstance(task_facts.get("context"), dict) else {}
                maybe_snapshot_id = (
                    task_facts.get("snapshot_id")
                    if isinstance(task_facts.get("snapshot_id"), int)
                    else ctx.get("snapshot_id")
                )
                if isinstance(maybe_snapshot_id, int):
                    snapshot_id = maybe_snapshot_id

            # Use current snapshot if not provided
            if snapshot_id is None:
                snapshot = await self.pkg_client.get_active_snapshot()
                if not snapshot:
                    logger.debug("[PKG] No active snapshot found - skipping governed facts hydration")
                    return task_facts
                snapshot_id = snapshot.id
            
            # Extract subject from task_facts for subject-specific hydration
            # Check multiple possible locations for subject
            task_subject = (
                task_facts.get("subject")
                or task_facts.get("context", {}).get("subject")
                or task_facts.get("context", {}).get("entity_id")
            )
            
            # Extract namespace (default to 'default')
            namespace = (
                task_facts.get("namespace")
                or task_facts.get("context", {}).get("namespace")
                or "default"
            )
            
            # Query active facts (subject-specific if subject available)
            # Use governed_only=False to hydrate with all active facts, not just PKG-governed ones
            # This allows policies to query all facts relevant to the snapshot
            facts = await self.pkg_client.get_active_governed_facts(
                snapshot_id=snapshot_id,
                namespace=namespace,
                subject=task_subject,  # Subject-specific hydration
                limit=100,
                governed_only=False  # Include all facts, not just PKG-governed
            )
            
            # Inject facts into task_facts as structured triples
            task_facts["governed_facts"] = facts
            
            # Group facts by subject for easier rule access
            facts_by_subject = {}
            for fact in facts:
                subj = fact.get("subject")
                if subj:
                    if subj not in facts_by_subject:
                        facts_by_subject[subj] = []
                    facts_by_subject[subj].append(fact)
            
            task_facts["governed_facts_by_subject"] = facts_by_subject
            
            # Extract predicates for easier rule access
            task_facts["governed_predicates"] = list(set(
                f.get("predicate") for f in facts if f.get("predicate")
            ))
            
            logger.debug(
                f"[PKG] Hydrated {len(facts)} active facts "
                f"(snapshot={snapshot_id}, namespace={namespace}"
                + (f", subject={task_subject}" if task_subject else "")
                + ")"
            )
            
            return task_facts
        except Exception as e:
            logger.error(f"[PKG] Governed facts hydration failed: {e}", exc_info=True)
            return task_facts

    async def evaluate_async(
        self, 
        task_facts: Dict[str, Any], 
        embedding: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Asynchronous evaluation wrapper that performs full hydration before execution.
        
        This is the recommended entry point when semantic context is available.
        It follows the three-step dance:
        1. Semantic Hydration: Fetching the "Semantic Memory Bundle" based on task embedding
        2. Governed Facts Hydration: Fetching active PKG-governed facts (policy feedback loop)
        3. Execution: Running the WASM or Native rules against enriched context
        
        This integration transforms SeedCore from a "stateless rule-checker" into a
        "stateful, cognitive operating system" that remembers consequences of prior decisions.
        
        Args:
            task_facts: Input facts dictionary with tags, signals, context
            embedding: Optional 1024d embedding vector for semantic similarity search
        
        Returns:
            A dictionary containing the policy output (subtasks, dag, provenance)
            and the snapshot version that was used.
        """
        # 1. HYDRATION: Fetch semantic context from Cortex (historical tasks)
        hydrated_facts = await self.hydrate_semantic_context(task_facts.copy(), embedding)
        
        # 2. HYDRATION: Fetch active PKG-governed facts (policy feedback loop)
        hydrated_facts = await self.hydrate_governed_facts(hydrated_facts)
        
        # 3. EVALUATION: Run the actual engine (synchronous)
        output = self.evaluate(hydrated_facts)
        # Preserve key hydrated bundles for audit/provenance consumers (API, logs).
        # Backward compatible: adds optional keys without changing the core shape.
        output["_hydrated"] = {
            "governed_facts": hydrated_facts.get("governed_facts"),
            "semantic_context": hydrated_facts.get("semantic_context"),
        }
        return output

    def evaluate(self, task_facts: Dict[str, Any]) -> Dict[str, Any]:
        """
        Runs the loaded policy engine against a set of input facts.
        [cite: 94]
        
        Note: For semantic context hydration, use evaluate_async() instead.
        This method assumes task_facts is already hydrated if needed.
        
        Args:
            task_facts: A dictionary of input facts for the policy. 
                        e.g., {"tags": [...], "signals": {...}, "context": {...}, 
                               "semantic_context": [...]} [cite: 55-59]

        Returns:
            A dictionary containing the policy output (subtasks, dag, provenance)
            and the snapshot version that was used. [cite: 99-104]
        """
        if self.engine is None:
            raise RuntimeError(f"PKGEvaluator engine not initialized for version {self.version}")

        start_time = time.perf_counter()
        
        # Log evaluation start with structured context
        logger.debug({
            "event": "pkg_evaluation_start",
            "snapshot": self.version,
            "engine": self.engine_type,
            "facts_keys": list(task_facts.keys()) if isinstance(task_facts, dict) else [],
            "has_semantic_context": "semantic_context" in task_facts if isinstance(task_facts, dict) else False
        })

        try:
            # Unified engine interface - both engines implement evaluate()
            if isinstance(self.engine, OpaWasm):
                # Invoke the OPA runtime [cite: 95]
                result = self.engine.evaluate(task_facts)  # [cite: 96]
            elif isinstance(self.engine, NativeRuleEngine):
                # Run the native predicate chain [cite: 97]
                result = self.engine.evaluate(task_facts)  # [cite: 98]
            else:
                # Generic engine interface (for future extensions)
                result = self.engine.evaluate(task_facts)
            
            elapsed = time.perf_counter() - start_time
            
            # Assemble the final, standardized output dictionary [cite: 99]
            output = {
                "subtasks": result.subtasks,      # [cite: 100]
                "dag": result.dag,                # [cite: 101]
                "rules": result.provenance,       # [cite: 102]
                "snapshot": self.version          # [cite: 103]
            }
            
            # Log successful evaluation
            logger.info({
                "event": "pkg_evaluation_complete",
                "snapshot": self.version,
                "engine": self.engine_type,
                "duration_ms": elapsed * 1000,
                "subtasks_count": len(result.subtasks),
                "rules_matched": len(result.provenance),
                "had_semantic_context": "semantic_context" in task_facts if isinstance(task_facts, dict) else False
            })
            
            return output
            
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            logger.error({
                "event": "pkg_evaluation_error",
                "snapshot": self.version,
                "engine": self.engine_type,
                "duration_ms": elapsed * 1000,
                "error": str(e)
            }, exc_info=True)
            
            # Return empty result on error
            return {
                "subtasks": [],
                "dag": [],
                "rules": [{"rule_id": "error", "error": str(e), "error_type": type(e).__name__}],
                "snapshot": self.version
            }

if __name__ == '__main__':
    # --- Example Usage ---
    print("--- Testing PKG Evaluator ---")
    
    # Note: In real usage, snapshots come from PKGClient.get_active_snapshot()
    # This is just for demonstration
    
    # Example input facts
    input_data = {
        "tags": ["vip", "privacy", "allergen"],
        "signals": {"x2": 0.8, "x6": 0.95},
        "context": {"domain": "hotel_ops", "task_type": "guest_request"}
    }
    
    print("Input facts:", input_data)
    print("\nNote: To test with real snapshots, use PKGClient and PKGManager")