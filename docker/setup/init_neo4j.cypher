// Initialize Neo4j schema for Holon Fabric
// This script is idempotent and safe to re-run.

// Create constraint for Holon nodes
CREATE CONSTRAINT holon_uuid IF NOT EXISTS
FOR (h:Holon) REQUIRE h.uuid IS UNIQUE;

// Create indexes for better performance
CREATE INDEX holon_created_at IF NOT EXISTS FOR (h:Holon) ON (h.created_at);
CREATE INDEX holon_type IF NOT EXISTS FOR (h:Holon) ON (h.type);

// Seed sample Holon nodes
MERGE (h1:Holon {description: 'Test holon 1'})
  ON CREATE SET
    h1.uuid = randomUUID(),
    h1.type = 'sample',
    h1.created_at = datetime(),
    h1.meta_compression_tau = 0.5,
    h1.meta_source = 'test';

MERGE (h2:Holon {description: 'Test holon 2'})
  ON CREATE SET
    h2.uuid = randomUUID(),
    h2.type = 'sample',
    h2.created_at = datetime(),
    h2.meta_compression_tau = 0.3,
    h2.meta_source = 'test';

MERGE (h3:Holon {description: 'Test holon 3'})
  ON CREATE SET
    h3.uuid = randomUUID(),
    h3.type = 'sample',
    h3.created_at = datetime(),
    h3.meta_compression_tau = 0.7,
    h3.meta_source = 'test';

// Seed relationships between the nodes
MATCH (h1:Holon {description: 'Test holon 1'})
MATCH (h2:Holon {description: 'Test holon 2'})
MATCH (h3:Holon {description: 'Test holon 3'})
MERGE (h1)-[:DERIVED_FROM]->(h2)
MERGE (h2)-[:RELATED_TO]->(h3)
MERGE (h1)-[:SIMILAR_TO]->(h3);
