"""
Create optional OpenAI embeddings for Neo4j Entity nodes and store them as e.embedding.

Run from project root:
    python src/04_create_node_embeddings.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase
from openai import OpenAI

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
CACHE_PATH = DATA_DIR / "node_embeddings.json"
load_dotenv(ROOT_DIR / ".env")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password12345")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

GET_NODES_QUERY = """
MATCH (e:Entity)
RETURN e.key AS key, e.name AS name, e.type AS type, coalesce(e.aliases, []) AS aliases
ORDER BY e.name
"""

SET_EMBEDDING_QUERY = """
MATCH (e:Entity {key: $key})
SET e.embedding = $embedding,
    e.embedding_model = $model
"""


def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def main() -> None:
    if not OPENAI_API_KEY:
        raise ValueError("Missing OPENAI_API_KEY in .env")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = OpenAI(api_key=OPENAI_API_KEY)
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        records, _, _ = driver.execute_query(GET_NODES_QUERY, database_=NEO4J_DATABASE)
        nodes = [record.data() for record in records]

        if not nodes:
            print("No Entity nodes found. Run src/03_import_to_neo4j.py first.")
            return

        cache = {}
        if CACHE_PATH.exists():
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

        missing = []
        for node in nodes:
            if node["key"] not in cache:
                aliases = ", ".join(node.get("aliases") or [])
                text = f"Entity name: {node['name']}\nType: {node['type']}\nAliases: {aliases}"
                missing.append((node["key"], text))

        print(f"Total nodes: {len(nodes)}")
        print(f"Missing embeddings: {len(missing)}")

        batch_size = 64
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            texts = [item[1] for item in batch]
            embeddings = embed_texts(client, texts)
            for (key, _), embedding in zip(batch, embeddings):
                cache[key] = embedding
            print(f"Embedded {min(start + batch_size, len(missing))}/{len(missing)}")

        CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")

        for node in nodes:
            embedding = cache.get(node["key"])
            if embedding:
                driver.execute_query(
                    SET_EMBEDDING_QUERY,
                    key=node["key"],
                    embedding=embedding,
                    model=EMBEDDING_MODEL,
                    database_=NEO4J_DATABASE,
                )

        print(f"Stored embeddings in Neo4j and cache: {CACHE_PATH}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
