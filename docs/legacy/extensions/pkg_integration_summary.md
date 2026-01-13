# PKG Integration Summary

## Overview

This document summarizes the comprehensive PKG (Policy Knowledge Graph) integration added to the SeedCore eventizer service, following the existing codebase patterns and database architecture.

## Changes Made

### 1. Database Migrations (013-015)

Created three focused migration files in `deploy/migrations/`:

- **`013_pkg_core.sql`** - Core PKG catalog (snapshots, rules, conditions, emissions, artifacts)
- **`014_pkg_ops.sql`** - Operations (deployments, temporal facts, validation, promotions, device coverage)
- **`015_pkg_views_functions.sql`** - Views and helper functions

### 2. Enhanced Eventizer Models

Updated `src/seedcore/services/eventizer/schemas/eventizer_models.py` with:

#### New PKG Enums
- `PKGEnv` - Environment types (prod, staging, dev)
- `PKGEngine` - Execution engines (wasm, native)
- `PKGConditionType` - Condition types (TAG, SIGNAL, VALUE, FACT)
- `PKGOperator` - Operators (=, !=, >=, <=, >, <, EXISTS, IN, MATCHES)
- `PKGRelation` - Relationship types (EMITS, ORDERS, GATE)
- `PKGArtifactType` - Artifact types (rego_bundle, wasm_pack)

#### New PKG Core Models
- `PKGSnapshot` - Versioned policy snapshots with validation
- `PKGSubtaskType` - Subtask type definitions
- `PKGPolicyRule` - Policy rule definitions
- `PKGRuleCondition` - Rule conditions for policy evaluation
- `PKGRuleEmission` - Rule emissions linking rules to subtasks
- `PKGSnapshotArtifact` - Compiled WASM/Rego artifacts

#### New PKG Operations Models
- `PKGDeployment` - Targeted deployment configurations
- `PKGFact` - Temporal policy facts with expiration
- `PKGValidationFixture` - Validation fixtures for testing
- `PKGValidationRun` - Validation run results
- `PKGPromotion` - Promotion/rollback audit records
- `PKGDeviceVersion` - Device version heartbeat tracking

#### Enhanced Existing Models
- **`RuleProvenance`** - Enhanced with PKG integration fields
- **`PKGHint`** - Enhanced with full snapshot integration
- **`EventizerResponse`** - Added PKG integration metadata
- **`EventizerConfig`** - Added PKG governance settings

#### Helper Classes
- **`PKGHelper`** - Static helper methods for common operations
- **`PKGValidationResult`** - Validation operation results
- **`PKGDeploymentStatus`** - Deployment status with coverage metrics

### 3. PKG Client Implementation

Created `src/seedcore/services/eventizer/clients/pkg_client.py` following the `RegistryClient` pattern:

#### Key Features
- Async database operations using SQLAlchemy
- Proper error handling and logging
- Database session management following existing patterns
- Integration with PostgreSQL-based PKG data layer

#### Main Methods
- `get_active_snapshot()` - Get active snapshot for environment
- `get_snapshot_by_version()` - Get snapshot by version string
- `validate_snapshot()` - Validate snapshot using fixtures
- `promote_snapshot()` - Promote snapshot to active
- `get_deployments()` - Get deployment configurations
- `get_device_coverage()` - Get device coverage information
- `get_temporal_facts()` - Get temporal policy facts
- `create_temporal_fact()` - Create new temporal fact
- `check_integrity()` - Check PKG integrity

### 4. Database Integration Patterns

#### Consistent with Existing Codebase
- Uses `get_async_pg_session_factory()` from `database.py`
- Follows the same async context manager patterns as `RegistryClient`
- Proper SQL query construction with parameter binding
- Error handling and logging patterns consistent with existing code

#### Model Factory Methods
Added `from_db_row()` class methods to key models for clean database integration:
- `PKGSnapshot.from_db_row()`
- `PKGDeployment.from_db_row()`
- `PKGFact.from_db_row()`

### 5. Verification Script

Created `scripts/host/verify_pkg_migrations.sql` with comprehensive sanity checks:
- Active snapshot validation
- Artifact verification
- Rule-subtask integrity checks
- Temporal facts validation
- Deployment coverage analysis
- Database object verification

## Architecture Benefits

### 1. Consistency
- Follows existing database and client patterns
- Uses established session management
- Consistent error handling and logging

### 2. Performance
- Async operations throughout
- Proper connection pooling
- Efficient query patterns

### 3. Maintainability
- Clear separation of concerns
- Well-documented models and methods
- Follows existing code organization

### 4. Extensibility
- Modular design allows easy extension
- Helper classes provide convenient operations
- Database views and functions support complex queries

## Usage Examples

### Basic PKG Operations

```python
from seedcore.services.eventizer.clients import PKGClient, get_active_snapshot

# Get active snapshot
client = PKGClient(PKGEnv.PROD)
snapshot = await client.get_active_snapshot()

# Validate snapshot
result = await client.validate_snapshot(snapshot.id)

# Get deployments
deployments = await client.get_deployments("router")

# Create temporal fact
fact = PKGHelper.create_temporal_fact(
    subject="guest:Ben",
    predicate="hasTemporaryAccess",
    object={"service": "lounge"},
    valid_to=datetime.now(timezone.utc) + timedelta(hours=2)
)
await client.create_temporal_fact(fact)
```

### Eventizer Integration

```python
# In eventizer service
response = EventizerResponse(
    # ... existing fields ...
    pkg_snapshot_version=snapshot.version,
    pkg_snapshot_id=snapshot.id,
    pkg_validation_status=validation_result.success,
    pkg_deployment_info={
        "target": "router",
        "region": "us-west-2",
        "percent": 100
    }
)
```

## Migration Application

To apply the PKG migrations:

```bash
# From project root
cd deploy/migrations

# Apply migrations in order
psql -h localhost -U seedcore -d seedcore_db -f 013_pkg_core.sql
psql -h localhost -U seedcore -d seedcore_db -f 014_pkg_ops.sql
psql -h localhost -U seedcore -d seedcore_db -f 015_pkg_views_functions.sql

# Verify installation
psql -h localhost -U seedcore -d seedcore_db -f ../../scripts/host/verify_pkg_migrations.sql
```

## Future Enhancements

1. **Real-time Validation** - Implement actual policy validation logic
2. **Hot-swap Support** - Add Redis pub/sub for live snapshot updates
3. **Metrics Integration** - Add Prometheus metrics for PKG operations
4. **Audit Logging** - Enhanced audit trails for policy changes
5. **Multi-tenant Support** - Namespace isolation for different tenants

## Conclusion

The PKG integration provides a robust foundation for policy-driven event processing while maintaining consistency with the existing SeedCore architecture. The implementation follows established patterns and provides comprehensive functionality for governance, validation, and deployment tracking.
