"""
Enhanced Fact database model for SeedCore with PKG integration.

This model extends the original fact model with PKG (Policy Knowledge Graph) capabilities,
including temporal facts, policy validation, and eventizer integration.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy import String, DateTime, JSON, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func

class Base(DeclarativeBase):
    pass

class Fact(Base):
    """
    Enhanced Fact model with PKG integration.
    
    This model supports both traditional fact storage and PKG-governed temporal facts
    with policy validation and eventizer integration.
    """
    __tablename__ = "facts"

    # Original fields (backward compatible)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    text: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=True, default=list)
    meta_data: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    
    # PKG integration fields
    snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, description="PKG snapshot reference")
    namespace: Mapped[str] = mapped_column(String, nullable=False, default="default", description="Fact namespace")
    subject: Mapped[Optional[str]] = mapped_column(String, nullable=True, description="Fact subject (e.g., 'guest:Ben')")
    predicate: Mapped[Optional[str]] = mapped_column(String, nullable=True, description="Fact predicate (e.g., 'hasTemporaryAccess')")
    object_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, description="Fact object data")
    valid_from: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True, description="Fact validity start time")
    valid_to: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True, description="Fact validity end time (NULL = indefinite)")
    created_by: Mapped[str] = mapped_column(String, nullable=False, default="system", description="Creator identifier")
    
    # PKG governance fields
    pkg_rule_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, description="PKG rule that created this fact")
    pkg_provenance: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, description="PKG rule provenance data")
    validation_status: Mapped[Optional[str]] = mapped_column(String, nullable=True, description="PKG validation status")

    def to_dict(self):
        """Convert the fact to a dictionary representation."""
        result = {}
        # Use SQLAlchemy's state directly to avoid lazy loading
        state = self.__dict__
        for c in self.__table__.columns:
            if c.name in state:
                value = state[c.name]
                # Handle special cases like enums
                if hasattr(value, 'value'):
                    result[c.name] = value.value
                else:
                    result[c.name] = value
            else:
                # For unloaded attributes, set to None to avoid lazy loading
                result[c.name] = None
        return result
    
    def to_pkg_fact(self) -> Dict[str, Any]:
        """
        Convert to PKGFact-compatible dictionary for policy processing.
        
        Returns a dictionary that can be used to create a PKGFact instance
        for policy evaluation and validation.
        """
        return {
            "id": None,  # Will be set by database
            "snapshot_id": self.snapshot_id,
            "namespace": self.namespace,
            "subject": self.subject or "unknown",
            "predicate": self.predicate or "has_fact",
            "object": self.object_data or {"text": self.text},
            "valid_from": self.valid_from or self.created_at,
            "valid_to": self.valid_to,
            "created_at": self.created_at,
            "created_by": self.created_by
        }
    
    def is_temporal(self) -> bool:
        """Check if this is a temporal fact."""
        return self.valid_from is not None or self.valid_to is not None
    
    def is_expired(self) -> bool:
        """Check if temporal fact has expired."""
        if not self.is_temporal() or self.valid_to is None:
            return False
        return datetime.now(timezone.utc) > self.valid_to
    
    def is_valid(self) -> bool:
        """Check if temporal fact is currently valid."""
        if not self.is_temporal():
            return True
        now = datetime.now(timezone.utc)
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_to and now > self.valid_to:
            return False
        return True
    
    def get_validity_status(self) -> str:
        """Get human-readable validity status."""
        if not self.is_temporal():
            return "permanent"
        if self.is_expired():
            return "expired"
        if not self.is_valid():
            return "not_yet_valid"
        return "valid"
    
    @classmethod
    def from_pkg_fact(cls, pkg_fact_data: Dict[str, Any], text: str = None) -> "Fact":
        """
        Create Fact from PKGFact data.
        
        Args:
            pkg_fact_data: Dictionary containing PKGFact fields
            text: Optional text override (defaults to string representation of object)
        
        Returns:
            New Fact instance
        """
        return cls(
            text=text or str(pkg_fact_data.get("object", "")),
            tags=[pkg_fact_data.get("predicate", "fact")],
            meta_data={"pkg_fact_id": pkg_fact_data.get("id")},
            snapshot_id=pkg_fact_data.get("snapshot_id"),
            namespace=pkg_fact_data.get("namespace", "default"),
            subject=pkg_fact_data.get("subject"),
            predicate=pkg_fact_data.get("predicate"),
            object_data=pkg_fact_data.get("object"),
            valid_from=pkg_fact_data.get("valid_from"),
            valid_to=pkg_fact_data.get("valid_to"),
            created_by=pkg_fact_data.get("created_by", "system")
        )
    
    @classmethod
    def create_temporal(
        cls,
        subject: str,
        predicate: str,
        object_data: dict,
        text: str = None,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
        namespace: str = "default",
        created_by: str = "system"
    ) -> "Fact":
        """
        Create a temporal fact with explicit validity window.
        
        Args:
            subject: Fact subject (e.g., 'guest:john_doe')
            predicate: Fact predicate (e.g., 'hasTemporaryAccess')
            object_data: Fact object data
            text: Optional text description
            valid_from: Validity start time (defaults to now)
            valid_to: Validity end time (None = indefinite)
            namespace: Fact namespace
            created_by: Creator identifier
        
        Returns:
            New temporal Fact instance
        """
        if text is None:
            text = f"{subject} {predicate} {object_data}"
        
        return cls(
            text=text,
            tags=[predicate, "temporal"],
            meta_data={"temporal_fact": True},
            namespace=namespace,
            subject=subject,
            predicate=predicate,
            object_data=object_data,
            valid_from=valid_from or datetime.now(timezone.utc),
            valid_to=valid_to,
            created_by=created_by
        )
    
    @classmethod
    def create_from_eventizer(
        cls,
        processed_text: str,
        event_types: List[str],
        attributes: Dict[str, Any],
        pkg_hint: Optional[Dict[str, Any]] = None,
        snapshot_id: Optional[int] = None,
        domain: str = "default"
    ) -> "Fact":
        """
        Create Fact from eventizer processing results.
        
        Args:
            processed_text: Text after eventizer processing
            event_types: List of detected event types
            attributes: Eventizer attributes
            pkg_hint: Optional PKG hint data
            snapshot_id: Optional PKG snapshot ID
            domain: Processing domain
        
        Returns:
            New Fact instance from eventizer results
        """
        meta_data = {
            "eventizer_processed": True,
            "event_types": event_types,
            "attributes": attributes
        }
        
        if pkg_hint:
            meta_data["pkg_hint"] = pkg_hint
        
        return cls(
            text=processed_text,
            tags=event_types,
            meta_data=meta_data,
            namespace=domain,
            subject=attributes.get("target_organ"),
            predicate="processed_by_eventizer",
            object_data=attributes,
            snapshot_id=snapshot_id,
            created_by="eventizer_service"
        )
    
    def add_pkg_governance(
        self,
        rule_id: str,
        provenance: Dict[str, Any],
        validation_status: str = "pkg_validated"
    ) -> None:
        """
        Add PKG governance information to the fact.
        
        Args:
            rule_id: PKG rule identifier
            provenance: Rule provenance data
            validation_status: Validation status
        """
        self.pkg_rule_id = rule_id
        self.pkg_provenance = provenance
        self.validation_status = validation_status
    
    def __repr__(self) -> str:
        """String representation of the fact."""
        validity = self.get_validity_status()
        return f"<Fact(id={self.id}, subject={self.subject}, predicate={self.predicate}, validity={validity})>"
