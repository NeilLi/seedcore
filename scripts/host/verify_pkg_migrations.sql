-- verify_pkg_migrations.sql
-- Purpose: Sanity checklist for PKG migrations (post-apply verification)

-- 1) Exactly one active snapshot per env
SELECT env, COUNT(*) FROM pkg_snapshots WHERE is_active = TRUE GROUP BY env;

-- 2) Artifacts wired to the active snapshot
SELECT * FROM pkg_active_artifact;

-- 3) Rule→Subtask integrity
SELECT * FROM pkg_check_integrity();

-- 4) Any non-expired temporary facts?
SELECT * FROM pkg_facts
WHERE (valid_to IS NULL OR valid_to > now())
ORDER BY valid_to NULLS LAST;

-- 5) Deployment coverage (devices on-target)
SELECT * FROM pkg_deployment_coverage ORDER BY target, region;

-- 6) Check all enum types were created
SELECT typname FROM pg_type WHERE typname LIKE 'pkg_%' ORDER BY typname;

-- 7) Check all tables were created
SELECT tablename FROM pg_tables WHERE tablename LIKE 'pkg_%' ORDER BY tablename;

-- 8) Check all views were created
SELECT viewname FROM pg_views WHERE viewname LIKE 'pkg_%' ORDER BY viewname;

-- 9) Check all functions were created
SELECT proname FROM pg_proc WHERE proname LIKE 'pkg_%' ORDER BY proname;
