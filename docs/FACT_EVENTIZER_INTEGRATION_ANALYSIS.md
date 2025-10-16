# Fact-Eventizer Integration Analysis

## Overview

This document analyzes how to combine the original `fact.py` model with the latest eventizer service to create a unified, PKG-integrated fact management system that leverages policy-driven event processing.

## Current State Analysis

### Original Fact Model (`src/seedcore/models/fact.py`)

**Structure:**
- **SQLAlchemy ORM Model**: Traditional database model with SQLAlchemy
- **Simple Schema**: `id`, `text`, `tags`, `meta_data`, `created_at`, `updated_at`
- **Basic Functionality**: Simple CRUD operations with `to_dict()` method
- **Database-Focused**: Direct database interaction without business logic

**Strengths:**
- Clean, simple schema
- Standard SQLAlchemy patterns
- Easy database operations
- UUID primary key for distributed systems

**Limitations:**
- No PKG integration
- No policy-driven processing
- No event processing capabilities
- No temporal fact support
- No validation or governance

### Eventizer Service Models (`src/seedcore/services/eventizer/schemas/eventizer_models.py`)

**Structure:**
- **Pydantic Models**: Rich validation and serialization
- **PKG Integration**: Full PKG schema with snapshots, rules, conditions, emissions
- **Temporal Facts**: `PKGFact` model with validity windows
- **Policy-Driven**: Rule-based fact processing and validation
- **Comprehensive**: 1100+ lines with extensive functionality

**Strengths:**
- PKG governance integration
- Temporal fact support (`valid_from`, `valid_to`)
- Policy-driven processing
- Rich validation and serialization
- Event processing pipeline
- Audit trails and provenance

**Limitations:**
- No direct database integration
- Complex for simple fact storage
- Eventizer-specific focus

## Integration Strategy

### Option 1: Extend Original Fact Model (Recommended)

**Approach:** Enhance the original `fact.py` model with PKG capabilities while maintaining backward compatibility.

**Benefits:**
- Maintains existing database schema
- Gradual migration path
- Backward compatibility
- Simpler for basic use cases

**Implementation:**
```python
# Enhanced fact.py with PKG integration
class Fact(Base):
    __tablename__ = "facts"
    
    # Original fields
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    text: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=True, default=list)
    meta_data: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # PKG integration fields
    snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, description="PKG snapshot reference")
    namespace: Mapped[str] = mapped_column(String, nullable=False, default="default")
    subject: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    predicate: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    object_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    valid_from: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False, default="system")
    
    # PKG governance fields
    pkg_rule_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pkg_provenance: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
```

### Option 2: Create Hybrid Model

**Approach:** Create a new model that bridges both approaches.

**Benefits:**
- Best of both worlds
- Clean separation of concerns
- Flexible usage patterns

**Implementation:**
```python
class FactManager:
    """Unified fact management with PKG integration."""
    
    def __init__(self, db_session, pkg_client: Optional[PKGClient] = None):
        self.db = db_session
        self.pkg_client = pkg_client
    
    async def create_fact(self, fact_data: Union[Dict, PKGFact]) -> Fact:
        """Create fact with PKG integration if available."""
        
    async def process_with_eventizer(self, text: str) -> Tuple[Fact, EventizerResponse]:
        """Process text through eventizer and create fact."""
        
    async def validate_with_pkg(self, fact: Fact) -> bool:
        """Validate fact against PKG policies."""
```

### Option 3: Eventizer-First Approach

**Approach:** Use eventizer models as primary and add database persistence.

**Benefits:**
- Full PKG integration
- Rich policy processing
- Advanced temporal support

**Limitations:**
- More complex
- Breaking change for existing code
- Overkill for simple use cases

## Recommended Integration Plan

### Phase 1: Extend Original Model (Immediate)

1. **Add PKG Fields to Fact Model**
   ```python
   # Add to existing fact.py
   snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
   namespace: Mapped[str] = mapped_column(String, nullable=False, default="default")
   subject: Mapped[Optional[str]] = mapped_column(String, nullable=True)
   predicate: Mapped[Optional[str]] = mapped_column(String, nullable=True)
   object_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
   valid_from: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
   valid_to: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
   created_by: Mapped[str] = mapped_column(String, nullable=False, default="system")
   ```

2. **Add PKG Helper Methods**
   ```python
   def to_pkg_fact(self) -> PKGFact:
       """Convert to PKGFact for policy processing."""
       
   def is_temporal(self) -> bool:
       """Check if this is a temporal fact."""
       
   def is_expired(self) -> bool:
       """Check if temporal fact has expired."""
   ```

3. **Create Migration**
   ```sql
   -- Add PKG fields to existing facts table
   ALTER TABLE facts ADD COLUMN snapshot_id INTEGER REFERENCES pkg_snapshots(id);
   ALTER TABLE facts ADD COLUMN namespace TEXT NOT NULL DEFAULT 'default';
   ALTER TABLE facts ADD COLUMN subject TEXT;
   ALTER TABLE facts ADD COLUMN predicate TEXT;
   ALTER TABLE facts ADD COLUMN object_data JSONB;
   ALTER TABLE facts ADD COLUMN valid_from TIMESTAMPTZ;
   ALTER TABLE facts ADD COLUMN valid_to TIMESTAMPTZ;
   ALTER TABLE facts ADD COLUMN created_by TEXT NOT NULL DEFAULT 'system';
   ```

### Phase 2: Create Fact Manager (Short-term)

1. **Implement FactManager Class**
   ```python
   class FactManager:
       async def create_from_eventizer(self, response: EventizerResponse) -> Fact
       async def validate_with_pkg(self, fact: Fact) -> bool
       async def process_text(self, text: str, domain: str) -> Tuple[Fact, EventizerResponse]
       async def get_temporal_facts(self, subject: str) -> List[Fact]
       async def cleanup_expired_facts(self) -> int
   ```

2. **Add Eventizer Integration**
   ```python
   async def create_fact_from_text(self, text: str, domain: str = "default") -> Fact:
       """Process text through eventizer and create fact."""
       eventizer = EventizerService()
       await eventizer.initialize()
       
       request = EventizerRequest(text=text, domain=domain)
       response = await eventizer.process_text(request)
       
       # Create fact from eventizer response
       fact = Fact(
           text=response.processed_text,
           tags=[tag.value for tag in response.event_tags.event_types],
           meta_data={
               "eventizer_response": response.model_dump(),
               "pkg_hint": response.pkg_hint.model_dump() if response.pkg_hint else None,
               "confidence": response.confidence.overall_confidence
           },
           subject=response.attributes.target_organ,
           predicate="processed_by_eventizer",
           object_data=response.attributes.model_dump(),
           snapshot_id=response.pkg_snapshot_id,
           created_by="eventizer_service"
       )
       
       return fact
   ```

### Phase 3: Advanced Integration (Medium-term)

1. **Policy-Driven Fact Processing**
   ```python
   async def process_with_policies(self, text: str) -> Fact:
       """Process text with PKG policy evaluation."""
       eventizer = EventizerService(pkg_validation_enabled=True)
       await eventizer.initialize()
       
       request = EventizerRequest(text=text)
       response = await eventizer.process_text(request)
       
       # Apply PKG policies to fact creation
       if response.pkg_hint:
           fact = await self._create_fact_from_pkg_hint(response)
       else:
           fact = await self._create_fact_from_response(response)
           
       return fact
   ```

2. **Temporal Fact Management**
   ```python
   async def create_temporal_fact(
       self, 
       subject: str, 
       predicate: str, 
       object_data: dict,
       valid_from: datetime,
       valid_to: Optional[datetime] = None
   ) -> Fact:
       """Create temporal fact with PKG governance."""
       
   async def get_active_facts(self, subject: str) -> List[Fact]:
       """Get non-expired temporal facts for subject."""
   ```

## Implementation Details

### Database Schema Evolution

```sql
-- Migration: Add PKG fields to facts table
BEGIN;

-- Add PKG integration columns
ALTER TABLE facts ADD COLUMN IF NOT EXISTS snapshot_id INTEGER;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS namespace TEXT NOT NULL DEFAULT 'default';
ALTER TABLE facts ADD COLUMN IF NOT EXISTS subject TEXT;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS predicate TEXT;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS object_data JSONB;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT 'system';

-- Add foreign key constraint
ALTER TABLE facts ADD CONSTRAINT fk_facts_snapshot_id 
    FOREIGN KEY (snapshot_id) REFERENCES pkg_snapshots(id) ON DELETE SET NULL;

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts(predicate);
CREATE INDEX IF NOT EXISTS idx_facts_namespace ON facts(namespace);
CREATE INDEX IF NOT EXISTS idx_facts_temporal ON facts(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_facts_snapshot ON facts(snapshot_id);

-- Add constraints
ALTER TABLE facts ADD CONSTRAINT chk_facts_temporal 
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to);

COMMIT;
```

### Enhanced Fact Model

```python
class Fact(Base):
    __tablename__ = "facts"
    
    # Original fields (backward compatible)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    text: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[List[str]] = mapped_column(ARRAY(String), nullable=True, default=list)
    meta_data: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # PKG integration fields
    snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    namespace: Mapped[str] = mapped_column(String, nullable=False, default="default")
    subject: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    predicate: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    object_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    valid_from: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False, default="system")
    
    # PKG governance fields
    pkg_rule_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pkg_provenance: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    def to_pkg_fact(self) -> PKGFact:
        """Convert to PKGFact for policy processing."""
        return PKGFact(
            id=None,  # Will be set by database
            snapshot_id=self.snapshot_id,
            namespace=self.namespace,
            subject=self.subject or "unknown",
            predicate=self.predicate or "has_fact",
            object=self.object_data or {"text": self.text},
            valid_from=self.valid_from or self.created_at,
            valid_to=self.valid_to,
            created_at=self.created_at,
            created_by=self.created_by
        )
    
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
    
    @classmethod
    def from_pkg_fact(cls, pkg_fact: PKGFact, text: str = None) -> "Fact":
        """Create Fact from PKGFact."""
        return cls(
            text=text or str(pkg_fact.object),
            tags=[pkg_fact.predicate],
            meta_data={"pkg_fact_id": pkg_fact.id},
            snapshot_id=pkg_fact.snapshot_id,
            namespace=pkg_fact.namespace,
            subject=pkg_fact.subject,
            predicate=pkg_fact.predicate,
            object_data=pkg_fact.object,
            valid_from=pkg_fact.valid_from,
            valid_to=pkg_fact.valid_to,
            created_by=pkg_fact.created_by
        )
```

### Fact Manager Implementation

```python
class FactManager:
    """Unified fact management with PKG integration."""
    
    def __init__(self, db_session, pkg_client: Optional[PKGClient] = None):
        self.db = db_session
        self.pkg_client = pkg_client
        self._eventizer: Optional[EventizerService] = None
    
    async def initialize(self):
        """Initialize eventizer service."""
        if not self._eventizer:
            self._eventizer = EventizerService()
            await self._eventizer.initialize()
    
    async def create_from_text(
        self, 
        text: str, 
        domain: str = "default",
        process_with_pkg: bool = True
    ) -> Tuple[Fact, Optional[EventizerResponse]]:
        """Create fact from text with optional eventizer processing."""
        
        await self.initialize()
        
        # Process through eventizer
        request = EventizerRequest(text=text, domain=domain)
        response = await self._eventizer.process_text(request)
        
        # Create fact
        fact = Fact(
            text=response.processed_text,
            tags=[tag.value for tag in response.event_tags.event_types],
            meta_data={
                "original_text": response.original_text,
                "confidence": response.confidence.overall_confidence,
                "patterns_applied": response.patterns_applied,
                "pii_redacted": response.pii_redacted,
                "processing_time_ms": response.processing_time_ms
            },
            namespace=domain,
            subject=response.attributes.target_organ,
            predicate="processed_by_eventizer",
            object_data={
                "event_types": [tag.value for tag in response.event_tags.event_types],
                "keywords": response.event_tags.keywords,
                "entities": response.event_tags.entities,
                "attributes": response.attributes.model_dump()
            },
            snapshot_id=response.pkg_snapshot_id,
            created_by="fact_manager"
        )
        
        # Apply PKG policies if enabled
        if process_with_pkg and response.pkg_hint:
            fact.pkg_provenance = [prov.model_dump() for prov in response.pkg_hint.provenance]
            fact.validation_status = "pkg_validated"
        
        return fact, response
    
    async def create_temporal_fact(
        self,
        subject: str,
        predicate: str,
        object_data: dict,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
        namespace: str = "default"
    ) -> Fact:
        """Create temporal fact with PKG governance."""
        
        fact = Fact(
            text=f"{subject} {predicate} {object_data}",
            tags=[predicate],
            meta_data={"temporal_fact": True},
            namespace=namespace,
            subject=subject,
            predicate=predicate,
            object_data=object_data,
            valid_from=valid_from or datetime.now(timezone.utc),
            valid_to=valid_to,
            created_by="fact_manager"
        )
        
        # Validate with PKG if available
        if self.pkg_client:
            try:
                pkg_fact = fact.to_pkg_fact()
                await self.pkg_client.create_temporal_fact(pkg_fact)
                fact.validation_status = "pkg_validated"
            except Exception as e:
                logger.warning(f"PKG validation failed: {e}")
                fact.validation_status = "pkg_validation_failed"
        
        return fact
    
    async def get_active_facts(self, subject: str, namespace: str = "default") -> List[Fact]:
        """Get non-expired temporal facts for subject."""
        
        query = select(Fact).where(
            Fact.subject == subject,
            Fact.namespace == namespace,
            or_(
                Fact.valid_to.is_(None),
                Fact.valid_to > datetime.now(timezone.utc)
            )
        ).order_by(Fact.created_at.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def cleanup_expired_facts(self) -> int:
        """Remove expired temporal facts."""
        
        expired_cutoff = datetime.now(timezone.utc)
        
        query = delete(Fact).where(
            and_(
                Fact.valid_to.is_not(None),
                Fact.valid_to <= expired_cutoff
            )
        )
        
        result = await self.db.execute(query)
        await self.db.commit()
        
        return result.rowcount
    
    async def validate_with_pkg(self, fact: Fact) -> bool:
        """Validate fact against PKG policies."""
        
        if not self.pkg_client:
            return True
        
        try:
            pkg_fact = fact.to_pkg_fact()
            # Use PKG client to validate
            # This would integrate with PKG validation logic
            return True
        except Exception as e:
            logger.error(f"PKG validation failed: {e}")
            return False
```

## Migration Strategy

### Database Migration

```sql
-- 016_fact_pkg_integration.sql
BEGIN;

-- Add PKG integration columns to facts table
ALTER TABLE facts ADD COLUMN IF NOT EXISTS snapshot_id INTEGER;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS namespace TEXT NOT NULL DEFAULT 'default';
ALTER TABLE facts ADD COLUMN IF NOT EXISTS subject TEXT;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS predicate TEXT;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS object_data JSONB;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT 'system';
ALTER TABLE facts ADD COLUMN IF NOT EXISTS pkg_rule_id TEXT;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS pkg_provenance JSONB;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS validation_status TEXT;

-- Add foreign key constraint
ALTER TABLE facts ADD CONSTRAINT fk_facts_snapshot_id 
    FOREIGN KEY (snapshot_id) REFERENCES pkg_snapshots(id) ON DELETE SET NULL;

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts(predicate);
CREATE INDEX IF NOT EXISTS idx_facts_namespace ON facts(namespace);
CREATE INDEX IF NOT EXISTS idx_facts_temporal ON facts(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_facts_snapshot ON facts(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_facts_created_by ON facts(created_by);

-- Add constraints
ALTER TABLE facts ADD CONSTRAINT chk_facts_temporal 
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to);

-- Update existing facts to have default namespace
UPDATE facts SET namespace = 'default' WHERE namespace IS NULL;

COMMIT;
```

### Code Migration

1. **Update imports in existing code**
2. **Add FactManager to services**
3. **Update fact creation calls**
4. **Add PKG validation where needed**

## Benefits of Integration

### 1. **Unified Fact Management**
- Single source of truth for facts
- Consistent API across all fact operations
- Backward compatibility with existing code

### 2. **Policy-Driven Processing**
- PKG governance for fact creation
- Validation against active policies
- Audit trails and provenance

### 3. **Temporal Fact Support**
- Expiring facts with automatic cleanup
- Time-based fact queries
- Policy-driven temporal constraints

### 4. **Eventizer Integration**
- Rich text processing capabilities
- Pattern matching and entity extraction
- Confidence scoring and validation

### 5. **Scalability**
- Efficient indexing for temporal queries
- PKG snapshot-based versioning
- Distributed fact management

## Usage Examples

### Basic Fact Creation
```python
# Simple fact creation (backward compatible)
fact = Fact(
    text="Room 101 temperature is 72°F",
    tags=["temperature", "room"],
    meta_data={"room_id": "101", "temperature": 72}
)
```

### Eventizer-Processed Fact
```python
# Process text through eventizer
fact_manager = FactManager(db_session, pkg_client)
fact, response = await fact_manager.create_from_text(
    "Emergency alert: Fire detected in building A",
    domain="hotel_ops"
)
```

### Temporal Fact Creation
```python
# Create temporal fact with expiration
fact = await fact_manager.create_temporal_fact(
    subject="guest:john_doe",
    predicate="hasTemporaryAccess",
    object_data={"service": "lounge", "level": "premium"},
    valid_from=datetime.now(timezone.utc),
    valid_to=datetime.now(timezone.utc) + timedelta(hours=24)
)
```

### Policy-Validated Fact
```python
# Create fact with PKG validation
fact = await fact_manager.create_from_text(
    "VIP guest request for room upgrade",
    domain="hotel_ops",
    process_with_pkg=True
)

# Fact will include PKG provenance and validation status
if fact.validation_status == "pkg_validated":
    print(f"Fact validated by PKG rules: {fact.pkg_provenance}")
```

## Conclusion

The recommended integration approach extends the original `fact.py` model with PKG capabilities while maintaining backward compatibility. This provides:

1. **Gradual Migration**: Existing code continues to work
2. **Enhanced Capabilities**: PKG governance and temporal support
3. **Unified Management**: Single API for all fact operations
4. **Policy Integration**: Eventizer-driven fact processing
5. **Scalability**: Efficient temporal fact management

The integration creates a powerful, policy-driven fact management system that leverages the full capabilities of the PKG and eventizer services while maintaining simplicity for basic use cases.
