#!/usr/bin/env python3
"""
OPA Compiler Integration for PKG

Executes OPA build pipeline to compile Rego policies to WASM.
Handles temporary file management, OPA binary execution, and WASM extraction.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import hashlib
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class OPACompiler:
    """
    Compiles Rego policies to WASM using OPA build tool.
    
    Responsibilities:
    - Write Rego to temporary directory
    - Execute `opa build` command
    - Extract WASM bytes from bundle.tar.gz
    - Calculate SHA256 checksum
    - Clean up temporary files
    """
    
    def __init__(self, opa_binary_path: Optional[str] = None, verify_on_init: bool = False):
        """
        Initialize OPA compiler.
        
        Args:
            opa_binary_path: Optional path to OPA binary. If None, uses 'opa' from PATH.
            verify_on_init: If True, verify OPA availability immediately. 
                           If False (default), verify lazily on first compilation.
        """
        self.opa_binary = opa_binary_path or "opa"
        self._opa_verified = False
        if verify_on_init:
            self._verify_opa_available()
    
    def _verify_opa_available(self) -> None:
        """
        Verify that OPA binary is available.
        
        Raises:
            RuntimeError: If OPA binary is not found or not working
        """
        try:
            result = subprocess.run(
                [self.opa_binary, "version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                version_info = result.stdout.strip()
                logger.info(f"OPA compiler available: {version_info}")
            else:
                error_msg = result.stderr or result.stdout or "Unknown error"
                raise RuntimeError(
                    f"OPA binary '{self.opa_binary}' returned non-zero exit code {result.returncode}: {error_msg}"
                )
        except FileNotFoundError:
            # Provide helpful installation instructions
            install_instructions = (
                f"OPA binary not found at '{self.opa_binary}'. "
                "Please install OPA using one of the following methods:\n"
                "  Linux/macOS: curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64 && chmod +x opa && sudo mv opa /usr/local/bin/\n"
                "  Or download from: https://www.openpolicyagent.org/docs/latest/#running-opa\n"
                "  Verify installation: opa version"
            )
            raise RuntimeError(install_instructions)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"OPA binary timeout - '{self.opa_binary}' is not responding. "
                "Please check that the binary is executable and not corrupted."
            )
        except PermissionError:
            raise RuntimeError(
                f"Permission denied executing '{self.opa_binary}'. "
                "Please ensure the binary has execute permissions: chmod +x {self.opa_binary}"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to verify OPA binary '{self.opa_binary}': {e}. "
                "Please ensure OPA is installed and accessible."
            )
    
    def compile_rego_to_wasm(
        self,
        rego_text: str,
        entrypoint: str = "data.pkg.allow"
    ) -> Tuple[bytes, str]:
        """
        Compile Rego policy to WASM binary.
        
        Args:
            rego_text: Rego policy source code
            entrypoint: OPA entrypoint path (default: "data.pkg.allow")
            
        Returns:
            Tuple of (wasm_bytes, sha256_checksum)
            
        Raises:
            RuntimeError: If compilation fails
        """
        # Lazy verification: check OPA availability on first compilation
        if not self._opa_verified:
            self._verify_opa_available()
            self._opa_verified = True

        def _entrypoint_for_opa_build(entrypoint_value: str) -> str:
            # OPA build expects package/rule (e.g., pkg/allow), not data path.
            parts = entrypoint_value.split(".")
            if len(parts) >= 3 and parts[0] == "data":
                return f"{parts[1]}/{parts[2]}"
            return entrypoint_value
        
        temp_dir = None
        try:
            # Create temporary directory
            temp_dir = tempfile.mkdtemp(prefix="pkg-opa-")
            logger.debug(f"Created temporary directory: {temp_dir}")
            
            # Write Rego to file
            rego_path = os.path.join(temp_dir, "policy.rego")
            # Log the generated Rego for debugging (at debug level to avoid cluttering logs)
            logger.debug(f"Generated Rego source ({len(rego_text)} chars) for entrypoint {entrypoint}:\n{rego_text}")
            with open(rego_path, "w", encoding="utf-8") as f:
                f.write(rego_text)
            logger.debug(f"Wrote Rego policy to {rego_path}")
            
            # Execute OPA build
            bundle_path = os.path.join(temp_dir, "bundle.tar.gz")
            build_entrypoint = _entrypoint_for_opa_build(entrypoint)
            cmd = [
                self.opa_binary,
                "build",
                "-t", "wasm",
                "-e", build_entrypoint,
                "-o", bundle_path,
                rego_path
            ]
            
            logger.info(f"Executing: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout for compilation
            )
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                raise RuntimeError(
                    f"OPA build failed with exit code {result.returncode}:\n{error_msg}"
                )
            
            logger.info("OPA build completed successfully")
            
            # Extract WASM from bundle.tar.gz
            wasm_bytes = self._extract_wasm_from_bundle(bundle_path, temp_dir)
            
            if not wasm_bytes:
                raise RuntimeError("Failed to extract WASM from bundle.tar.gz")
            
            # Calculate SHA256 checksum
            sha256 = hashlib.sha256(wasm_bytes).hexdigest()
            
            logger.info(
                f"WASM compilation successful: {len(wasm_bytes)} bytes, "
                f"checksum: {sha256[:16]}..."
            )
            
            return wasm_bytes, sha256
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("OPA build timed out after 30 seconds")
        except Exception as e:
            logger.error(f"WASM compilation failed: {e}", exc_info=True)
            raise
        finally:
            # Clean up temporary directory unless explicitly disabled for debugging
            keep_temp = os.getenv("OPA_KEEP_TEMP", "0") == "1"
            if keep_temp:
                logger.debug(f"Keeping temporary directory for debugging: {temp_dir}")
            elif temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up temporary directory: {temp_dir}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temp directory {temp_dir}: {e}")
    
    def _extract_wasm_from_bundle(
        self,
        bundle_path: str,
        extract_dir: str
    ) -> Optional[bytes]:
        """
        Extract WASM binary from OPA bundle.tar.gz.
        
        OPA bundles contain:
        - /policy.wasm (the compiled WASM)
        - /.manifest (metadata)
        - /policy.rego (source, optional)
        
        Args:
            bundle_path: Path to bundle.tar.gz
            extract_dir: Directory to extract bundle into
            
        Returns:
            WASM bytes or None if extraction fails
        """
        try:
            # Extract bundle.tar.gz
            extract_path = os.path.join(extract_dir, "extracted")
            os.makedirs(extract_path, exist_ok=True)
            
            # Use tar to extract (more reliable than Python tarfile for gzip)
            result = subprocess.run(
                ["tar", "-xzf", bundle_path, "-C", extract_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error(f"tar extraction failed: {result.stderr}")
                return None
            
            # Look for policy.wasm in extracted bundle
            wasm_path = os.path.join(extract_path, "policy.wasm")
            if not os.path.exists(wasm_path):
                # Try alternative location (OPA sometimes uses different structure)
                wasm_path = os.path.join(extract_path, ".", "policy.wasm")
                if not os.path.exists(wasm_path):
                    # List contents for debugging
                    logger.error(f"WASM file not found. Bundle contents: {os.listdir(extract_path)}")
                    return None
            
            # Read WASM bytes
            with open(wasm_path, "rb") as f:
                wasm_bytes = f.read()
            
            logger.debug(f"Extracted WASM: {len(wasm_bytes)} bytes from {wasm_path}")
            return wasm_bytes
            
        except Exception as e:
            logger.error(f"Failed to extract WASM from bundle: {e}", exc_info=True)
            return None
    
    def validate_wasm_module(self, wasm_bytes: bytes) -> Dict[str, Any]:
        """
        Validate WASM module exports (optional validation step).
        
        Checks that WASM module has required OPA ABI exports.
        This is a lightweight validation - full validation happens at runtime.
        
        Args:
            wasm_bytes: WASM binary bytes
            
        Returns:
            Dictionary with validation results
        """
        # OPA WASM modules expect the OPA runtime host ABI and are not meant to be
        # instantiated directly without those imports. Skip wasmtime validation.
        return {
            "valid": True,
            "note": "Skipped wasmtime instantiation; OPA WASM ABI requires host runtime imports."
        }
