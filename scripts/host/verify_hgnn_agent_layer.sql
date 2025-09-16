-- verify_hgnn_agent_layer.sql
-- Purpose: Verify presence and integrity of objects introduced by 008_hgnn_agent_layer.sql
-- Safe to run multiple times. Read-only checks only.

-- Show server and current database/user
SELECT version() AS postgres_version;
SELECT current_database() AS db, current_user AS usr;

-- Section 1: New entity tables
SELECT 'skill'  AS object, CASE WHEN to_regclass('public.skill')  IS NOT NULL THEN 'OK' ELSE 'MISSING' END AS status
UNION ALL SELECT 'service', CASE WHEN to_regclass('public.service') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'model',   CASE WHEN to_regclass('public.model')   IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'policy',  CASE WHEN to_regclass('public.policy')  IS NOT NULL THEN 'OK' ELSE 'MISSING' END
ORDER BY object;

-- Section 2: Relationship tables
SELECT 'agent_member_of_organ'      AS object, CASE WHEN to_regclass('public.agent_member_of_organ')    IS NOT NULL THEN 'OK' ELSE 'MISSING' END AS status
UNION ALL SELECT 'organ_provides_skill',       CASE WHEN to_regclass('public.organ_provides_skill')     IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'agent_collab_agent',         CASE WHEN to_regclass('public.agent_collab_agent')       IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'organ_uses_service',         CASE WHEN to_regclass('public.organ_uses_service')       IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'agent_uses_model',           CASE WHEN to_regclass('public.agent_uses_model')         IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'organ_governed_by_policy',   CASE WHEN to_regclass('public.organ_governed_by_policy') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
ORDER BY object;

-- Section 3: Functions (presence via to_regprocedure)
SELECT 'ensure_skill_node(text)'    AS function, CASE WHEN to_regprocedure('ensure_skill_node(text)')    IS NOT NULL THEN 'OK' ELSE 'MISSING' END AS status
UNION ALL SELECT 'ensure_service_node(text)',   CASE WHEN to_regprocedure('ensure_service_node(text)')  IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'ensure_model_node(text)',     CASE WHEN to_regprocedure('ensure_model_node(text)')    IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL SELECT 'ensure_policy_node(text)',    CASE WHEN to_regprocedure('ensure_policy_node(text)')   IS NOT NULL THEN 'OK' ELSE 'MISSING' END
ORDER BY function;

-- Section 4: View presence
SELECT 'hgnn_edges' AS view, CASE WHEN to_regclass('public.hgnn_edges') IS NOT NULL THEN 'OK' ELSE 'MISSING' END AS status
ORDER BY view;

-- Section 5: View definition contains new edge unions (string presence)
WITH def AS (
  SELECT pg_get_viewdef('public.hgnn_edges'::regclass, true) AS vdef
)
SELECT 'agent__member_of__organ'    AS edge_union, CASE WHEN position('agent__member_of__organ'    IN vdef) > 0 THEN 'OK' ELSE 'MISSING' END AS status FROM def
UNION ALL SELECT 'organ__provides__skill',       CASE WHEN position('organ__provides__skill'       IN vdef) > 0 THEN 'OK' ELSE 'MISSING' END FROM def
UNION ALL SELECT 'agent__collab__agent',         CASE WHEN position('agent__collab__agent'         IN vdef) > 0 THEN 'OK' ELSE 'MISSING' END FROM def
UNION ALL SELECT 'organ__uses__service',         CASE WHEN position('organ__uses__service'         IN vdef) > 0 THEN 'OK' ELSE 'MISSING' END FROM def
UNION ALL SELECT 'agent__uses__model',           CASE WHEN position('agent__uses__model'           IN vdef) > 0 THEN 'OK' ELSE 'MISSING' END FROM def
UNION ALL SELECT 'organ__governed_by__policy',   CASE WHEN position('organ__governed_by__policy'   IN vdef) > 0 THEN 'OK' ELSE 'MISSING' END FROM def
ORDER BY edge_union;

-- Section 6: View shape smoke test
SELECT * FROM hgnn_edges LIMIT 0;


