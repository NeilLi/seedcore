-- Requires: CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS graph_embeddings (
    node_id BIGINT PRIMARY KEY,
    label TEXT NULL,
    props JSONB NULL,
    emb VECTOR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ANN index (adjust lists per data size)
CREATE INDEX IF NOT EXISTS idx_graph_embeddings_emb
ON graph_embeddings
USING ivfflat (emb vector_l2_ops)
WITH (lists = 100);

CREATE OR REPLACE FUNCTION update_graph_embeddings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_graph_embeddings_updated_at ON graph_embeddings;
CREATE TRIGGER trg_graph_embeddings_updated_at
BEFORE UPDATE ON graph_embeddings
FOR EACH ROW EXECUTE FUNCTION update_graph_embeddings_updated_at();
