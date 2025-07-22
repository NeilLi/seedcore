// Initialize Neo4j schema for Holon Fabric
// Run this in Neo4j Browser or cypher-shell

// Create constraint for Holon nodes
CREATE CONSTRAINT holon_uuid IF NOT EXISTS 
ON (h:Holon) ASSERT h.uuid IS UNIQUE;

// Create indexes for better performance
CREATE INDEX holon_created_at IF NOT EXISTS FOR (h:Holon) ON (h.created_at);
CREATE INDEX holon_type IF NOT EXISTS FOR (h:Holon) ON (h.type);

// Create some sample Holon nodes
CREATE (h1:Holon {
    uuid: apoc.create.uuid(),
    type: 'sample',
    description: 'Test holon 1',
    created_at: datetime(),
    meta: {compression_tau: 0.5, source: 'test'}
});

CREATE (h2:Holon {
    uuid: apoc.create.uuid(),
    type: 'sample', 
    description: 'Test holon 2',
    created_at: datetime(),
    meta: {compression_tau: 0.3, source: 'test'}
});

CREATE (h3:Holon {
    uuid: apoc.create.uuid(),
    type: 'sample',
    description: 'Test holon 3', 
    created_at: datetime(),
    meta: {compression_tau: 0.7, source: 'test'}
});

// Create relationships between sample nodes
MATCH (h1:Holon {description: 'Test holon 1'})
MATCH (h2:Holon {description: 'Test holon 2'})
MATCH (h3:Holon {description: 'Test holon 3'})
CREATE (h1)-[:DERIVED_FROM]->(h2)
CREATE (h2)-[:RELATED_TO]->(h3)
CREATE (h1)-[:SIMILAR_TO]->(h3); 