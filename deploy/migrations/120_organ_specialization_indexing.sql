-- 120_agent_specialization_indexing.sql
-- Add specialization column and unique constraint to agent_member_of_organ
-- This enables efficient queries by specialization and prevents duplicate agents
-- with the same specialization in the same organ.
--
-- Key Benefits:
-- 1. Efficient queries: Index on (organ_id, specialization) enables fast lookups
-- 2. Database-level deduplication: Unique constraint prevents duplicate agents
-- 3. Supports unique agent IDs: Works with agent_{organ_id}_{specialization}_{unique12} format
-- 4. Backward compatible: Handles legacy agents without specialization gracefully

BEGIN;

-- Add specialization column to agent_member_of_organ table
ALTER TABLE agent_member_of_organ
  ADD COLUMN IF NOT EXISTS specialization TEXT;

-- Extract specialization from agent_id pattern for existing agents
-- Pattern: agent_{organ_id}_{specialization}_{unique12}
-- This helps migrate existing data, but new registrations will set it explicitly
DO $$
DECLARE
  rec RECORD;
  extracted_spec TEXT;
BEGIN
  FOR rec IN 
    SELECT agent_id, organ_id 
    FROM agent_member_of_organ 
    WHERE specialization IS NULL
  LOOP
    -- Try to extract specialization from agent_id pattern
    -- Pattern: agent_{organ_id}_{specialization}_{unique12}
    IF rec.agent_id LIKE 'agent_' || rec.organ_id || '_%' THEN
      -- Extract the part between organ_id and the last underscore (which is unique12)
      extracted_spec := substring(
        rec.agent_id 
        FROM ('agent_' || rec.organ_id || '_(.+)_[a-f0-9]{12}$')
      );
      IF extracted_spec IS NOT NULL THEN
        UPDATE agent_member_of_organ
        SET specialization = lower(extracted_spec)
        WHERE agent_id = rec.agent_id AND organ_id = rec.organ_id;
      END IF;
    END IF;
  END LOOP;
END $$;

-- Create index on (organ_id, specialization) for efficient queries
-- Partial index (WHERE specialization IS NOT NULL) is smaller and faster
CREATE INDEX IF NOT EXISTS idx_agent_member_of_organ_organ_spec 
  ON agent_member_of_organ(organ_id, specialization)
  WHERE specialization IS NOT NULL;

-- Create unique constraint to prevent duplicate agents with same specialization in same organ
-- This ensures database-level deduplication for agents with unique IDs
-- The constraint allows multiple agents per organ, but only one per (organ_id, specialization) pair
-- This works with the agent_{organ_id}_{specialization}_{unique12} naming format
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_member_of_organ_organ_spec_unique
  ON agent_member_of_organ(organ_id, specialization)
  WHERE specialization IS NOT NULL;

-- Create index on specialization alone for cross-organ queries
-- Useful for finding all agents with a specific specialization across all organs
CREATE INDEX IF NOT EXISTS idx_agent_member_of_organ_spec
  ON agent_member_of_organ(specialization)
  WHERE specialization IS NOT NULL;

COMMENT ON COLUMN agent_member_of_organ.specialization IS 
  'Agent specialization (normalized lowercase). Used for efficient queries and deduplication. '
  'Enables database-level prevention of duplicate agents with the same specialization in the same organ, '
  'even when agents have unique IDs like agent_{organ_id}_{specialization}_{unique12}.';

-- === Organ Registry Indexing Improvements ===
-- Add index on organ kind for efficient queries by organ type
-- This enables fast lookups when filtering organs by their kind/type
-- (e.g., finding all 'utility' organs or all 'actuator' organs)
CREATE INDEX IF NOT EXISTS idx_organ_registry_kind
  ON organ_registry(kind)
  WHERE kind IS NOT NULL;

-- Add GIN index on props JSONB for efficient property-based queries
-- This enables fast queries on organ properties stored in JSONB
-- (e.g., finding organs with specific capabilities or metadata)
CREATE INDEX IF NOT EXISTS idx_organ_registry_props_gin
  ON organ_registry USING gin(props)
  WHERE props IS NOT NULL;

COMMENT ON INDEX idx_organ_registry_kind IS 
  'Index on organ kind/type for efficient filtering by organ category.';

COMMENT ON INDEX idx_organ_registry_props_gin IS 
  'GIN index on organ props JSONB for efficient property-based queries and filtering.';

COMMIT;
