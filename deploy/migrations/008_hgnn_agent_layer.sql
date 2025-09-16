-- 008_hgnn_agent_layer.sql
-- Extend HGNN schema with agent/organ layer relations
-- Author: SeedCore Team
-- Depends on: 007_hgnn_graph_schema.sql

BEGIN;

-- ============================================================
-- 1. New supporting tables (skills, services, models, policies)
-- ============================================================

CREATE TABLE IF NOT EXISTS skill (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    meta        JSONB,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS service (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    meta        JSONB,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    meta        JSONB,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS policy (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    rules       JSONB,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- 2. Relationship tables for agent/organ layer
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_member_of_organ (
    agent_id    UUID NOT NULL REFERENCES agent_registry(id) ON DELETE CASCADE,
    organ_id    UUID NOT NULL REFERENCES organ_registry(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (agent_id, organ_id)
);

CREATE TABLE IF NOT EXISTS organ_provides_skill (
    organ_id    UUID NOT NULL REFERENCES organ_registry(id) ON DELETE CASCADE,
    skill_id    UUID NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (organ_id, skill_id)
);

CREATE TABLE IF NOT EXISTS agent_collab_agent (
    agent_id    UUID NOT NULL REFERENCES agent_registry(id) ON DELETE CASCADE,
    peer_id     UUID NOT NULL REFERENCES agent_registry(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (agent_id, peer_id)
);

CREATE TABLE IF NOT EXISTS organ_uses_service (
    organ_id    UUID NOT NULL REFERENCES organ_registry(id) ON DELETE CASCADE,
    service_id  UUID NOT NULL REFERENCES service(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (organ_id, service_id)
);

CREATE TABLE IF NOT EXISTS agent_uses_model (
    agent_id    UUID NOT NULL REFERENCES agent_registry(id) ON DELETE CASCADE,
    model_id    UUID NOT NULL REFERENCES model(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (agent_id, model_id)
);

CREATE TABLE IF NOT EXISTS organ_governed_by_policy (
    organ_id    UUID NOT NULL REFERENCES organ_registry(id) ON DELETE CASCADE,
    policy_id   UUID NOT NULL REFERENCES policy(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (organ_id, policy_id)
);

-- ============================================================
-- 3. Ensure node functions for new entity types
-- ============================================================

CREATE OR REPLACE FUNCTION ensure_skill_node(skill_name TEXT)
RETURNS BIGINT AS $$
DECLARE
    node BIGINT;
    new_id UUID;
BEGIN
    SELECT node_id INTO node FROM graph_node_map
    WHERE node_type = 'skill' AND ext_table = 'skill' AND ext_uuid = (
        SELECT id FROM skill WHERE name = skill_name LIMIT 1
    );
    IF node IS NULL THEN
        INSERT INTO skill (name) VALUES (skill_name) RETURNING id INTO new_id;
        INSERT INTO graph_node_map(node_type, ext_table, ext_uuid)
        VALUES ('skill', 'skill', new_id)
        RETURNING node_id INTO node;
    END IF;
    RETURN node;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ensure_service_node(service_name TEXT)
RETURNS BIGINT AS $$
DECLARE
    node BIGINT;
    new_id UUID;
BEGIN
    SELECT node_id INTO node FROM graph_node_map
    WHERE node_type = 'service' AND ext_table = 'service' AND ext_uuid = (
        SELECT id FROM service WHERE name = service_name LIMIT 1
    );
    IF node IS NULL THEN
        INSERT INTO service (name) VALUES (service_name) RETURNING id INTO new_id;
        INSERT INTO graph_node_map(node_type, ext_table, ext_uuid)
        VALUES ('service', 'service', new_id)
        RETURNING node_id INTO node;
    END IF;
    RETURN node;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ensure_model_node(model_name TEXT)
RETURNS BIGINT AS $$
DECLARE
    node BIGINT;
    new_id UUID;
BEGIN
    SELECT node_id INTO node FROM graph_node_map
    WHERE node_type = 'model' AND ext_table = 'model' AND ext_uuid = (
        SELECT id FROM model WHERE name = model_name LIMIT 1
    );
    IF node IS NULL THEN
        INSERT INTO model (name) VALUES (model_name) RETURNING id INTO new_id;
        INSERT INTO graph_node_map(node_type, ext_table, ext_uuid)
        VALUES ('model', 'model', new_id)
        RETURNING node_id INTO node;
    END IF;
    RETURN node;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ensure_policy_node(policy_name TEXT)
RETURNS BIGINT AS $$
DECLARE
    node BIGINT;
    new_id UUID;
BEGIN
    SELECT node_id INTO node FROM graph_node_map
    WHERE node_type = 'policy' AND ext_table = 'policy' AND ext_uuid = (
        SELECT id FROM policy WHERE name = policy_name LIMIT 1
    );
    IF node IS NULL THEN
        INSERT INTO policy (name) VALUES (policy_name) RETURNING id INTO new_id;
        INSERT INTO graph_node_map(node_type, ext_table, ext_uuid)
        VALUES ('policy', 'policy', new_id)
        RETURNING node_id INTO node;
    END IF;
    RETURN node;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 4. Extend hgnn_edges view with new agent/organ edges
-- ============================================================

CREATE OR REPLACE VIEW hgnn_edges AS
SELECT * FROM (
    -- existing unions from 007...
    SELECT * FROM (
        SELECT ensure_task_node(d.src_task_id) AS src_node_id,
               ensure_task_node(d.dst_task_id) AS dst_node_id,
               'task__depends_on__task'::text AS edge_type
          FROM task_depends_on_task d
        UNION ALL
        -- (other existing unions stay intact) ...
        SELECT ensure_task_node(u.task_id) AS src_node_id,
               m.node_id AS dst_node_id,
               'task__uses__capability'::text AS edge_type
          FROM task_uses_capability u
            JOIN graph_node_map m ON m.node_type='capability'
                                 AND m.ext_table='capability'
                                 AND m.ext_uuid=u.capability_id
    ) t
    UNION ALL
    -- New agent layer unions
    SELECT ensure_agent_node(a.agent_id),
           ensure_organ_node(a.organ_id),
           'agent__member_of__organ'
      FROM agent_member_of_organ a
    UNION ALL
    SELECT ensure_organ_node(o.organ_id),
           ensure_skill_node(s.name),
           'organ__provides__skill'
      FROM organ_provides_skill o
        JOIN skill s ON s.id = o.skill_id
    UNION ALL
    SELECT ensure_agent_node(c.agent_id),
           ensure_agent_node(c.peer_id),
           'agent__collab__agent'
      FROM agent_collab_agent c
    UNION ALL
    SELECT ensure_organ_node(o.organ_id),
           ensure_service_node(s.name),
           'organ__uses__service'
      FROM organ_uses_service o
        JOIN service s ON s.id = o.service_id
    UNION ALL
    SELECT ensure_agent_node(a.agent_id),
           ensure_model_node(m.name),
           'agent__uses__model'
      FROM agent_uses_model a
        JOIN model m ON m.id = a.model_id
    UNION ALL
    SELECT ensure_organ_node(o.organ_id),
           ensure_policy_node(p.name),
           'organ__governed_by__policy'
      FROM organ_governed_by_policy o
        JOIN policy p ON p.id = o.policy_id
) all_edges;

COMMIT;

