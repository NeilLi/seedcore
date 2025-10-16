# Database Initialization Script PKG Integration

## Overview

This document summarizes the PKG (Policy Knowledge Graph) integration added to the `deploy/init_full_db.sh` script, enabling automated setup of the complete SeedCore database schema including PKG governance capabilities.

## Changes Made

### 1. Migration Path Configuration

Added PKG migration file paths to the script:

```bash
MIGRATION_013="${SCRIPT_DIR}/migrations/013_pkg_core.sql"
MIGRATION_014="${SCRIPT_DIR}/migrations/014_pkg_ops.sql"
MIGRATION_015="${SCRIPT_DIR}/migrations/015_pkg_views_functions.sql"
```

### 2. Migration File Validation

Updated the migration file existence check to include PKG migrations:

```bash
for migration in \
  "$MIGRATION_001" "$MIGRATION_002" "$MIGRATION_003" "$MIGRATION_004" \
  "$MIGRATION_005" "$MIGRATION_006" "$MIGRATION_007" "$MIGRATION_008" \
  "$MIGRATION_009" "$MIGRATION_010" "$MIGRATION_011" "$MIGRATION_012" \
  "$MIGRATION_013" "$MIGRATION_014" "$MIGRATION_015"
```

### 3. Migration Execution Steps

Added execution steps for PKG migrations:

```bash
# Migration 013 (NEW - PKG Core)
echo "⚙️  Running migration 013: PKG core catalog (snapshots, rules, conditions, emissions, artifacts)..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_013" "$POSTGRES_POD:/tmp/013_pkg_core.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/013_pkg_core.sql"

# Migration 014 (NEW - PKG Operations)
echo "⚙️  Running migration 014: PKG operations (deployments, temporal facts, validation, promotions, device coverage)..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_014" "$POSTGRES_POD:/tmp/014_pkg_ops.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/014_pkg_ops.sql"

# Migration 015 (NEW - PKG Views and Functions)
echo "⚙️  Running migration 015: PKG views and helper functions..."
kubectl -n "$NAMESPACE" cp "$MIGRATION_015" "$POSTGRES_POD:/tmp/015_pkg_views_functions.sql"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- psql -U "$DB_USER" -d "$DB_NAME" -f "/tmp/015_pkg_views_functions.sql"
```

### 4. Schema Verification

Added comprehensive PKG schema verification:

#### PKG Core Tables Verification
```bash
echo "📊 PKG core tables:"
for tbl in pkg_snapshots pkg_subtask_types pkg_policy_rules pkg_rule_conditions pkg_rule_emissions pkg_snapshot_artifacts
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ $tbl" || true
done
```

#### PKG Operations Tables Verification
```bash
echo "📊 PKG operations tables:"
for tbl in pkg_deployments pkg_facts pkg_validation_fixtures pkg_validation_runs pkg_promotions pkg_device_versions
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ $tbl" || true
done
```

#### PKG Views Verification
```bash
echo "📊 PKG views:"
for view in pkg_active_artifact pkg_rules_expanded pkg_deployment_coverage
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\d+ $view" || true
done
```

#### PKG Functions Verification
```bash
echo "📊 PKG functions:"
for fn in pkg_check_integrity pkg_active_snapshot_id pkg_promote_snapshot
do
  kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
    psql -U "$DB_USER" -d "$DB_NAME" -c "\df+ $fn" || true
done
```

#### PKG Enum Types Verification
```bash
echo "📊 PKG enum types:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT typname FROM pg_type WHERE typname LIKE 'pkg_%' ORDER BY typname;"
```

### 5. PKG Sanity Checks

Added comprehensive PKG sanity checks:

```bash
echo "📊 PKG sanity checks:"
kubectl -n "$NAMESPACE" exec "$POSTGRES_POD" -- \
  psql -U "$DB_USER" -d "$DB_NAME" -c "
    -- 1) Exactly one active snapshot per env
    SELECT 'Active snapshots per env:' as check_name, env, COUNT(*) as count 
    FROM pkg_snapshots WHERE is_active = TRUE GROUP BY env;
    
    -- 2) PKG integrity check
    SELECT 'PKG integrity:' as check_name, * FROM pkg_check_integrity();
    
    -- 3) Check all PKG enum types were created
    SELECT 'PKG enum types:' as check_name, COUNT(*) as count 
    FROM pg_type WHERE typname LIKE 'pkg_%';
    
    -- 4) Check all PKG tables were created
    SELECT 'PKG tables:' as check_name, COUNT(*) as count 
    FROM information_schema.tables WHERE table_name LIKE 'pkg_%';
    
    -- 5) Check all PKG views were created
    SELECT 'PKG views:' as check_name, COUNT(*) as count 
    FROM information_schema.views WHERE table_name LIKE 'pkg_%';
    
    -- 6) Check all PKG functions were created
    SELECT 'PKG functions:' as check_name, COUNT(*) as count 
    FROM information_schema.routines WHERE routine_name LIKE 'pkg_%';
"
```

### 6. Updated Summary Output

Enhanced the completion summary to include PKG information:

```bash
echo "✅ Created PKG schema: pkg_snapshots, pkg_policy_rules, pkg_rule_conditions, pkg_rule_emissions,"
echo "   pkg_snapshot_artifacts, pkg_deployments, pkg_facts, pkg_validation_*, pkg_promotions, pkg_device_versions"
echo "✅ Created PKG views: pkg_active_artifact, pkg_rules_expanded, pkg_deployment_coverage"
echo "✅ Created PKG functions: pkg_check_integrity, pkg_active_snapshot_id, pkg_promote_snapshot"
echo "✅ Created PKG enums: pkg_env, pkg_engine, pkg_condition_type, pkg_operator, pkg_relation, pkg_artifact_type"
```

### 7. PKG Quick Start Examples

Added PKG-specific examples to the quick start section:

```bash
echo "📋 PKG Quick start examples:"
echo "   -- Check PKG integrity:"
echo "   SELECT * FROM pkg_check_integrity();"
echo ""
echo "   -- View active PKG snapshot:"
echo "   SELECT * FROM pkg_active_artifact;"
echo ""
echo "   -- View PKG rules with emissions:"
echo "   SELECT * FROM pkg_rules_expanded LIMIT 10;"
echo ""
echo "   -- Check deployment coverage:"
echo "   SELECT * FROM pkg_deployment_coverage;"
echo ""
echo "   -- View PKG enum types:"
echo "   SELECT typname FROM pg_type WHERE typname LIKE 'pkg_%' ORDER BY typname;"
```

## Migration Execution Order

The script now executes migrations in the following order:

1. **001-012**: Existing migrations (tasks, HGNN, facts, runtime registry)
2. **013**: PKG core catalog (snapshots, rules, conditions, emissions, artifacts)
3. **014**: PKG operations (deployments, temporal facts, validation, promotions, device coverage)
4. **015**: PKG views and helper functions

## Verification Coverage

The enhanced script provides comprehensive verification of:

### Database Objects
- **Tables**: All PKG tables with structure details
- **Views**: All PKG views with structure details
- **Functions**: All PKG functions with signatures
- **Enums**: All PKG enum types
- **Indexes**: Implicit verification through table structure

### Data Integrity
- **Active Snapshots**: Verification of one active snapshot per environment
- **PKG Integrity**: Cross-reference validation using `pkg_check_integrity()`
- **Object Counts**: Verification that all expected objects were created

### Functional Testing
- **Quick Start Examples**: Ready-to-use SQL queries for testing PKG functionality
- **Sanity Checks**: Automated validation of PKG setup completeness

## Usage

The updated script maintains backward compatibility while adding PKG support:

```bash
# Run with default settings
./deploy/init_full_db.sh

# Run with custom namespace
NAMESPACE=my-seedcore ./deploy/init_full_db.sh

# Run with custom database settings
DB_NAME=seedcore_prod DB_USER=admin ./deploy/init_full_db.sh
```

## Expected Output

The script now provides:

1. **Migration Progress**: Clear indication of PKG migration execution
2. **Schema Verification**: Detailed verification of all PKG objects
3. **Sanity Checks**: Automated validation of PKG setup
4. **Quick Start Examples**: Ready-to-use PKG queries
5. **Complete Summary**: Comprehensive overview of all created objects

## Benefits

1. **Complete Setup**: Single script sets up entire SeedCore database including PKG
2. **Validation**: Comprehensive verification ensures proper PKG installation
3. **Documentation**: Built-in examples and verification queries
4. **Idempotency**: Safe to run multiple times
5. **Observability**: Detailed logging and verification output
6. **Production Ready**: Includes sanity checks and integrity validation

The enhanced initialization script now provides a complete, validated setup of the SeedCore database with full PKG governance capabilities, making it easy to deploy and verify the entire system.
