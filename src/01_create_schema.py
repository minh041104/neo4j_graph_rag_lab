"""
Create Neo4j constraints and indexes.

Run from project root:
    python src/01_create_schema.py
"""
from __future__ import annotations

import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password12345")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

SCHEMA_QUERIES = [
    """
    CREATE CONSTRAINT entity_key_unique IF NOT EXISTS
    FOR (e:Entity)
    REQUIRE e.key IS UNIQUE
    """,
    """
    CREATE INDEX entity_name_index IF NOT EXISTS
    FOR (e:Entity)
    ON (e.name)
    """,
    """
    CREATE INDEX entity_type_index IF NOT EXISTS
    FOR (e:Entity)
    ON (e.type)
    """,
    """
    CREATE INDEX relation_type_index IF NOT EXISTS
    FOR ()-[r:RELATION]-()
    ON (r.type)
    """,
]


def main() -> None:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        for query in SCHEMA_QUERIES:
            driver.execute_query(query, database_=NEO4J_DATABASE)
        print("Neo4j schema created successfully.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
