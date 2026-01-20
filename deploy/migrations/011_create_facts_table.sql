-- 011_create_facts_table.sql
-- Purpose: Create the core facts table for hybrid (text + structured triple) facts
--          with temporal validity, governance hooks (PKG), and query-friendly indexes.

BEGIN;

-- ---------------------------------------------------------------------------
-- Prereqs
-- ---------------------------------------------------------------------------
-- gen_random_uuid() lives in pgcrypto
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- Table: public.facts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.facts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Human-readable / searchable representation of the fact
    text              TEXT NOT NULL,

    -- Lightweight classification & metadata
    tags              TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    meta_data         JSONB  NOT NULL DEFAULT '{}'::JSONB,

    -- Audit timestamps
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Governance / grouping
    snapshot_id       INTEGER,
    namespace         TEXT NOT NULL DEFAULT 'default',
    created_by        TEXT NOT NULL DEFAULT 'system',

    -- Structured fact (triple)
    subject           TEXT,
    predicate         TEXT,
    object_data       JSONB,

    -- Temporal validity window for the fact (optional)
    valid_from        TIMESTAMPTZ,
    valid_to          TIMESTAMPTZ,

    -- Policy / rule governance (PKG)
    pkg_rule_id       TEXT,
    pkg_provenance    JSONB,
    validation_status TEXT
);

-- ---------------------------------------------------------------------------
-- Constraints (added idempotently)
-- ---------------------------------------------------------------------------

-- Temporal sanity: valid_from <= valid_to when both present
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'chk_facts_temporal'
          AND c.conrelid = 'public.facts'::regclass
    ) THEN
        ALTER TABLE public.facts
        ADD CONSTRAINT chk_facts_temporal
        CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to);
    END IF;
END$$;

-- namespace not empty
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'chk_facts_namespace_not_empty'
          AND c.conrelid = 'public.facts'::regclass
    ) THEN
        ALTER TABLE public.facts
        ADD CONSTRAINT chk_facts_namespace_not_empty
        CHECK (length(btrim(namespace)) > 0);
    END IF;
END$$;

-- created_by not empty
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'chk_facts_created_by_not_empty'
          AND c.conrelid = 'public.facts'::regclass
    ) THEN
        ALTER TABLE public.facts
        ADD CONSTRAINT chk_facts_created_by_not_empty
        CHECK (length(btrim(created_by)) > 0);
    END IF;
END$$;

-- No partial triples:
-- Either (subject,predicate,object_data) are all NULL, or all NOT NULL.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'chk_facts_no_partial_triple'
          AND c.conrelid = 'public.facts'::regclass
    ) THEN
        ALTER TABLE public.facts
        ADD CONSTRAINT chk_facts_no_partial_triple
        CHECK (
            (subject IS NULL AND predicate IS NULL AND object_data IS NULL)
            OR
            (subject IS NOT NULL AND predicate IS NOT NULL AND object_data IS NOT NULL)
        );
    END IF;
END$$;

-- PKG governed facts must be structured triples
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conname = 'chk_facts_pkg_requires_triple'
          AND c.conrelid = 'public.facts'::regclass
    ) THEN
        ALTER TABLE public.facts
        ADD CONSTRAINT chk_facts_pkg_requires_triple
        CHECK (
            pkg_rule_id IS NULL
            OR (subject IS NOT NULL AND predicate IS NOT NULL AND object_data IS NOT NULL)
        );
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- updated_at trigger
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger t
        WHERE t.tgname = 'trg_facts_set_updated_at'
          AND t.tgrelid = 'public.facts'::regclass
    ) THEN
        CREATE TRIGGER trg_facts_set_updated_at
        BEFORE UPDATE ON public.facts
        FOR EACH ROW
        EXECUTE FUNCTION public.set_updated_at();
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

-- Common time-based / namespace queries
CREATE INDEX IF NOT EXISTS idx_facts_created_at
    ON public.facts(created_at);

CREATE INDEX IF NOT EXISTS idx_facts_namespace
    ON public.facts(namespace);

CREATE INDEX IF NOT EXISTS idx_facts_created_at_namespace
    ON public.facts(created_at, namespace);

CREATE INDEX IF NOT EXISTS idx_facts_created_by
    ON public.facts(created_by);

-- Structured fact lookups
CREATE INDEX IF NOT EXISTS idx_facts_subject
    ON public.facts(subject);

CREATE INDEX IF NOT EXISTS idx_facts_predicate
    ON public.facts(predicate);

CREATE INDEX IF NOT EXISTS idx_facts_subject_namespace
    ON public.facts(subject, namespace);

CREATE INDEX IF NOT EXISTS idx_facts_spo_namespace
    ON public.facts(subject, predicate, namespace)
    WHERE subject IS NOT NULL AND predicate IS NOT NULL;

-- Snapshot / PKG
CREATE INDEX IF NOT EXISTS idx_facts_snapshot
    ON public.facts(snapshot_id);

CREATE INDEX IF NOT EXISTS idx_facts_pkg_rule
    ON public.facts(pkg_rule_id);

CREATE INDEX IF NOT EXISTS idx_facts_validation_status
    ON public.facts(validation_status);

-- Temporal filtering
CREATE INDEX IF NOT EXISTS idx_facts_temporal
    ON public.facts(valid_from, valid_to);

CREATE INDEX IF NOT EXISTS idx_facts_temporal_namespace
    ON public.facts(valid_from, valid_to, namespace);

-- JSONB + tags
CREATE INDEX IF NOT EXISTS idx_facts_meta_data
    ON public.facts USING GIN (meta_data);

CREATE INDEX IF NOT EXISTS idx_facts_tags
    ON public.facts USING GIN (tags);

-- Full-text search on text
CREATE INDEX IF NOT EXISTS idx_facts_text_search
    ON public.facts USING GIN (to_tsvector('english', text));

-- Optional: object_data helpers (capabilities / type)
CREATE INDEX IF NOT EXISTS idx_facts_object_capabilities
    ON public.facts USING GIN ((object_data->'capabilities'))
    WHERE object_data ? 'capabilities';

CREATE INDEX IF NOT EXISTS idx_facts_object_type
    ON public.facts ((object_data->>'type'))
    WHERE object_data ? 'type';

-- ---------------------------------------------------------------------------
-- Comments
-- ---------------------------------------------------------------------------
COMMENT ON TABLE public.facts IS 'Hybrid facts store: text + optional (subject,predicate,object_data) triple with temporal validity and governance fields.';

COMMENT ON COLUMN public.facts.text IS 'Human-readable statement for search/debug; may mirror structured triple.';
COMMENT ON COLUMN public.facts.tags IS 'Tags for faceting and quick filtering.';
COMMENT ON COLUMN public.facts.meta_data IS 'Additional metadata for retrieval, attribution, and analytics.';
COMMENT ON COLUMN public.facts.snapshot_id IS 'Optional governance snapshot identifier (e.g., PKG snapshot).';
COMMENT ON COLUMN public.facts.namespace IS 'Logical namespace/tenant/domain for fact partitioning and access control.';
COMMENT ON COLUMN public.facts.subject IS 'Triple subject (e.g., room:1208, service:digital_concierge).';
COMMENT ON COLUMN public.facts.predicate IS 'Triple predicate (e.g., hasType, hasCapabilities).';
COMMENT ON COLUMN public.facts.object_data IS 'Triple object as JSONB payload (typed data).';
COMMENT ON COLUMN public.facts.valid_from IS 'Fact validity start time. NULL means unspecified/immediate.';
COMMENT ON COLUMN public.facts.valid_to IS 'Fact validity end time. NULL means indefinite.';
COMMENT ON COLUMN public.facts.created_by IS 'Creator identifier (user/service) for audit.';
COMMENT ON COLUMN public.facts.pkg_rule_id IS 'Policy/rule identifier that produced or governs this fact.';
COMMENT ON COLUMN public.facts.pkg_provenance IS 'Provenance payload (inputs/trace/rule outputs) for governed facts.';
COMMENT ON COLUMN public.facts.validation_status IS 'Validation status for governed facts (e.g., validated, failed).';

-- ---------------------------------------------------------------------------
-- Helpful Views (optional, but typically useful)
-- ---------------------------------------------------------------------------

-- Structured facts with extracted semantic fields
CREATE OR REPLACE VIEW public.facts_structured AS
SELECT
    id,
    namespace,
    subject,
    predicate,
    object_data,
    object_data->>'type'        AS extracted_type,
    object_data->'capabilities' AS extracted_capabilities,
    object_data->>'contact'     AS extracted_contact,
    object_data->>'description' AS extracted_description,
    valid_from,
    valid_to,
    snapshot_id,
    pkg_rule_id,
    validation_status,
    created_by,
    created_at,
    updated_at
FROM public.facts
WHERE subject IS NOT NULL
  AND predicate IS NOT NULL
  AND object_data IS NOT NULL;

COMMENT ON VIEW public.facts_structured IS 'Structured triple facts with convenience extracted columns for common JSON patterns.';

-- Text-only facts (notes)
CREATE OR REPLACE VIEW public.facts_text_only AS
SELECT
    id,
    namespace,
    text,
    tags,
    meta_data,
    created_by,
    created_at,
    updated_at
FROM public.facts
WHERE subject IS NULL
  AND predicate IS NULL
  AND object_data IS NULL;

COMMENT ON VIEW public.facts_text_only IS 'Text-only facts (notes). Prefer converting important ones into structured triples.';

-- Facts with capabilities
CREATE OR REPLACE VIEW public.facts_with_capabilities AS
SELECT
    id,
    namespace,
    subject,
    predicate,
    object_data->'capabilities' AS capabilities,
    object_data->>'type'        AS type,
    object_data->>'contact'     AS contact,
    valid_from,
    valid_to,
    created_at
FROM public.facts
WHERE object_data ? 'capabilities'
ORDER BY created_at DESC;

COMMENT ON VIEW public.facts_with_capabilities IS 'Facts that carry capabilities; good for routing/execution planning queries.';

-- Active temporal facts (not expired and not future-dated)
CREATE OR REPLACE VIEW public.active_temporal_facts AS
SELECT
    id,
    namespace,
    subject,
    predicate,
    object_data,
    text,
    tags,
    meta_data,
    valid_from,
    valid_to,
    created_by,
    snapshot_id,
    pkg_rule_id,
    validation_status,
    created_at,
    updated_at,
    CASE
        WHEN valid_from IS NOT NULL AND valid_from > now() THEN 'future'
        WHEN valid_to   IS NULL THEN 'indefinite'
        WHEN valid_to   > now() THEN 'active'
        ELSE 'expired'
    END AS status
FROM public.facts
WHERE
    (valid_from IS NOT NULL OR valid_to IS NOT NULL)
    AND (valid_from IS NULL OR valid_from <= now())
    AND (valid_to   IS NULL OR valid_to   >  now());

COMMENT ON VIEW public.active_temporal_facts IS 'Temporal facts currently in effect (not expired, not future).';

-- Current truth: latest active fact per (namespace, subject, predicate)
CREATE OR REPLACE VIEW public.facts_current_truth AS
SELECT DISTINCT ON (namespace, subject, predicate)
    id,
    namespace,
    subject,
    predicate,
    object_data,
    valid_from,
    valid_to,
    created_by,
    snapshot_id,
    pkg_rule_id,
    validation_status,
    created_at,
    updated_at
FROM public.facts
WHERE subject IS NOT NULL
  AND predicate IS NOT NULL
  AND (valid_to IS NULL OR valid_to > now())
  AND (valid_from IS NULL OR valid_from <= now())
ORDER BY
  namespace, subject, predicate,
  COALESCE(valid_from, created_at) DESC,
  created_at DESC;

COMMENT ON VIEW public.facts_current_truth IS 'Latest in-effect fact per (namespace, subject, predicate).';

COMMIT;
