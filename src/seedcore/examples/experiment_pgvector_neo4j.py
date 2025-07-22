import psycopg2
from psycopg2.extras import execute_values
from neo4j import GraphDatabase
import numpy as np
import time
from datetime import datetime, timezone

# --- CONFIG ---
PG_HOST = 'localhost'
PG_PORT = 5432
PG_USER = 'postgres'
PG_PASSWORD = 'password'
PG_DB = 'postgres'

NEO4J_URI = 'bolt://localhost:7687'
NEO4J_USER = 'neo4j'
NEO4J_PASSWORD = 'password'

VECTOR_DIM = 384
N_TASKS = 100
COMPRESSION_KS = [0.1, 0.3, 0.5, 0.7, 0.9]

# --- PGVector Setup ---
def setup_pgvector():
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DB
    )
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS memory_items (
      id SERIAL PRIMARY KEY,
      vector VECTOR(%s),
      bytes_used INT,
      compression_k FLOAT,
      recon_loss FLOAT,
      staleness FLOAT,
      last_access TIMESTAMP,
      writer_agent TEXT,
      hit_count INT DEFAULT 0
    );
    ''' % VECTOR_DIM)
    conn.commit()
    cur.close()
    conn.close()

# --- Neo4j Setup ---
def setup_neo4j():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (a:Agent) REQUIRE a.id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (o:Organ) REQUIRE o.id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (m:MemoryObject) REQUIRE m.id IS UNIQUE")
    driver.close()

# --- Main Experiment Function ---
def run_memory_loop_experiment():
    setup_pgvector()
    setup_neo4j()
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=PG_DB
    )
    cur = conn.cursor()
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    agent_id = "a1"
    organ_id = "cognitive"
    # Ensure agent and organ exist
    with driver.session() as session:
        session.run("MERGE (a:Agent {id: $aid, capability: 0.8, role: 'writer'})", aid=agent_id)
        session.run("MERGE (o:Organ {id: $oid})", oid=organ_id)
        session.run("MATCH (a:Agent {id: $aid}), (o:Organ {id: $oid}) MERGE (a)-[:MEMBER_OF]->(o)", aid=agent_id, oid=organ_id)
    summary = {"compression_sweeps": []}
    for k in COMPRESSION_KS:
        sweep_stats = {"compression_k": k, "tasks": []}
        for task in range(N_TASKS):
            vec = np.random.randn(VECTOR_DIM).astype(np.float32)
            bytes_used = int((1 - k) * VECTOR_DIM * 4)
            recon_loss = float(np.abs(np.random.randn()) * k)
            staleness = 1.0
            now = datetime.now(timezone.utc)
            cur.execute('''
                INSERT INTO memory_items (vector, bytes_used, compression_k, recon_loss, staleness, last_access, writer_agent)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            ''', (vec.tolist(), bytes_used, k, recon_loss, staleness, now, agent_id))
            mem_id = cur.fetchone()[0]
            conn.commit()
            with driver.session() as session:
                session.run("MERGE (m:MemoryObject {id: $mid, compression_k: $k})", mid=mem_id, k=k)
                session.run("MATCH (a:Agent {id: $aid}), (m:MemoryObject {id: $mid}) MERGE (a)-[:WROTE]->(m)", aid=agent_id, mid=mem_id)
            vec_str = '[' + ','.join(str(x) for x in vec.tolist()) + ']'
            cur.execute('''
                SELECT id, vector <#> %s::vector as dist FROM memory_items ORDER BY dist ASC LIMIT 1
            ''', (vec_str,))
            hit_id, dist = cur.fetchone()
            cur.execute('''
                UPDATE memory_items SET hit_count = hit_count + 1, staleness = 1.0/(1+hit_count), last_access = %s WHERE id = %s
            ''', (now, hit_id))
            conn.commit()
            sweep_stats["tasks"].append({
                "task": task,
                "bytes_used": bytes_used,
                "recon_loss": recon_loss,
                "hit_id": hit_id,
                "dist": dist,
            })
        summary["compression_sweeps"].append(sweep_stats)
    cur.close()
    conn.close()
    driver.close()
    summary["message"] = "Comprehensive memory loop completed successfully!"
    return summary

if __name__ == "__main__":
    print("Setting up PGVector and Neo4j schema...")
    print("Running synthetic experiment loop...")
    result = run_memory_loop_experiment()
    print(result) 