from enum import Enum
from typing import Any, Dict, List
from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]
from datetime import datetime
import uuid

class HolonType(str, Enum):
    FACT = "fact"           # Immutable truth ("Room 101 is Single")
    EPISODE = "episode"     # Event log ("User complained about AC")
    CONCEPT = "concept"     # Abstract idea ("HVAC Failure")
    POLICY = "policy"       # Rule ("Refund if AC fails > 2hrs")

class HolonScope(str, Enum):
    GLOBAL = "global"       # Everyone can see
    ORGAN = "organ"         # Only agents in this Organ can see
    ENTITY = "entity"       # Attached to specific Guest/Device ID
    EPHEMERAL = "ephemeral" # Agent-local, forgotten after task

class Holon(BaseModel):
    """
    The fundamental unit of Semantic Memory.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: HolonType
    scope: HolonScope
    
    # The Content (Symbolic)
    content: Dict[str, Any] = Field(..., description="Structured JSON data")
    summary: str = Field(..., description="Natural language summary for LLM embedding")
    
    # The Index (Neural)
    embedding: List[float] = Field(default_factory=list, description="1024-dim vector")
    
    # The Web (Graph)
    # Adjacency list: [{'rel': 'CAUSED_BY', 'target_id': '...'}]
    links: List[Dict[str, str]] = Field(default_factory=list)
    
    # Governance
    created_at: datetime = Field(default_factory=datetime.utcnow)
    decay_rate: float = Field(0.1, description="Forgetting curve factor")
    confidence: float = 1.0
    access_policy: List[str] = Field(default_factory=list) # e.g. ["security_organ"]