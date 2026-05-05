// Neo4j Browser visualization queries for Lab 19 GraphRAG.
// Open http://localhost:7474 and paste these queries.

// 1. Show a sample of the graph
MATCH (a)-[r:RELATION]->(b)
RETURN a, r, b
LIMIT 100;

// 2. Show all relation types and counts
MATCH ()-[r:RELATION]->()
RETURN r.type AS relation_type, count(*) AS count
ORDER BY count DESC;

// 3. Show all company-like entities
MATCH (e:Entity)
WHERE e.type IN ['Company', 'Organization', 'ResearchLab']
RETURN e.name AS name, e.type AS type
ORDER BY name;

// 4. Show the 2-hop subgraph around OpenAI
MATCH p = (:Entity {key: 'openai'})-[*1..2]-(n)
RETURN p
LIMIT 100;

// 5. Show the 2-hop subgraph around Anthropic
MATCH p = (:Entity {key: 'anthropic'})-[*1..2]-(n)
RETURN p
LIMIT 100;

// 6. Query: AI companies founded/co-founded by former Google employees.
// This works only if extraction captured WORKED_AT / FORMER_EMPLOYEE_OF edges.
MATCH p = (company:Entity)-[r1:RELATION]-(person:Entity)-[r2:RELATION]-(google:Entity)
WHERE r1.type IN ['FOUNDED_BY', 'CO_FOUNDED_BY']
  AND r2.type IN ['WORKED_AT', 'FORMER_EMPLOYEE_OF']
  AND toLower(google.name) CONTAINS 'google'
RETURN p
LIMIT 100;

// 7. Query: companies connected to Google / Alphabet by organizational relation
MATCH p = (company:Entity)-[r:RELATION]-(google:Entity)
WHERE r.type IN ['ACQUIRED_BY', 'OWNED_BY', 'PART_OF', 'SUBSIDIARY_OF', 'PARENT_COMPANY']
  AND (toLower(google.name) CONTAINS 'google' OR toLower(google.name) CONTAINS 'alphabet')
RETURN p
LIMIT 100;

// 8. Clear previous highlight labels
MATCH (n:AnswerNode)
REMOVE n:AnswerNode;

// 9. Highlight selected answer nodes manually. Edit the names after you run your benchmark.
MATCH (n:Entity)
WHERE n.name IN ['OpenAI', 'Anthropic', 'DeepMind', 'Google Brain', 'Google', 'Microsoft']
SET n:AnswerNode
RETURN n;

// 10. Show highlighted answer subgraph
MATCH p = (:AnswerNode)-[*1..2]-(:AnswerNode)
RETURN p
LIMIT 100;
