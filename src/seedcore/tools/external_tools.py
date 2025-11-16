from __future__ import annotations
from typing import Dict, Any
import logging
import os
import httpx  # pyright: ignore[reportMissingImports]
import aiofiles  # pyright: ignore[reportMissingModuleSource]

# Import the protocol this class must implement

logger = logging.getLogger(__name__)

# ============================================================
# Internet Tools
# ============================================================

class InternetFetchTool:
    """
    A ToolManager for fetching content from a URL.
    Implements the ToolManager protocol.
    """
    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client

    @property
    def name(self) -> str:
        return "internet.fetch"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Fetches the text content of a given URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch (must be http or https).",
                    }
                },
                "required": ["url"],
            }
        }

    async def execute(self, url: str) -> str:
        """
        Executes the web fetch operation.
        
        Args:
            url: The URL to fetch.
        
        Returns:
            The text content of the page.
        """
        if not url.startswith(("http://", "https://")):
            raise ValueError("Invalid URL. Must start with http:// or https://")
        
        try:
            response = await self.http_client.get(url, follow_redirects=True)
            response.raise_for_status()  # Raise an exception for 4xx/5xx errors
            
            # Limit content size to avoid OOM issues
            # (In a real app, you might stream this)
            content = await response.aread()
            return content.decode("utf-8", errors="ignore")[:20000] # Cap at 20k chars
            
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error fetching {url}: {e}")
            raise Exception(f"HTTP error: {e.response.status_code}") from e
        except Exception as e:
            logger.error(f"Failed to fetch URL {url}: {e}")
            raise Exception(f"Failed to fetch URL: {e}")


# ============================================================
# Filesystem Tools
# ============================================================

class FileReadTool:
    """
    A ToolManager for reading a file from a sandboxed directory.
    Implements the ToolManager protocol.
    """
    def __init__(self, sandbox_dir: str):
        # Resolve to an absolute path for security
        self._sandbox_dir = os.path.realpath(sandbox_dir)
        os.makedirs(self._sandbox_dir, exist_ok=True)
        logger.info(f"FileReadTool initialized. Sandbox: {self._sandbox_dir}")

    @property
    def name(self) -> str:
        return "fs.read"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Reads the content of a file from a sandboxed directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The name of the file to read (e.G., 'data.txt').",
                    }
                },
                "required": ["filename"],
            }
        }

    async def execute(self, filename: str) -> str:
        """
        Executes the sandboxed file read operation.
        
        Args:
            filename: The name of the file to read.
        
        Returns:
            The text content of the file.
        """
        if not filename or ".." in filename or filename.startswith("/"):
            raise ValueError("Invalid filename. Path traversal is not allowed.")
        
        # Create the full, absolute path
        full_path = os.path.realpath(os.path.join(self._sandbox_dir, filename))
        
        # Security Check: Ensure the resolved path is still inside the sandbox
        if not full_path.startswith(self._sandbox_dir):
            logger.error(f"SECURITY: Path traversal attempt blocked: {filename}")
            raise PermissionError("File access denied: path is outside sandbox.")
            
        try:
            async with aiofiles.open(full_path, mode="r", encoding="utf-8") as f:
                content = await f.read(20000) # Cap at 20k chars
            return content
        except FileNotFoundError:
            logger.warning(f"File not found: {full_path}")
            raise FileNotFoundError(f"File '{filename}' not found in sandbox.")
        except Exception as e:
            logger.error(f"Failed to read file {full_path}: {e}")
            raise Exception(f"Failed to read file: {e}")