"""
Import data/triples.json into Neo4j.

Run from project root:
    python src/03_import_to_neo4j.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
TRIPLES_PATH = DATA_DIR / "triples.json"
load_dotenv(ROOT_DIR / ".env")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password12345")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

ALIAS_MAP = {
    "open ai": "openai",
    "openai inc": "openai",
    "openai inc.": "openai",
    "google llc": "google",
    "google inc": "google",
    "google inc.": "google",
    "alphabet inc": "alphabet",
    "meta": "meta platforms",
    "facebook": "meta platforms",
    "facebook inc": "meta platforms",
    "nvidia corporation": "nvidia",
    "microsoft corporation": "microsoft",
    "amazon web services inc": "amazon web services",
    "aws": "amazon web services",
}

UPSERT_TRIPLE_QUERY = """
MERGE (s:Entity {key: $subject_key})
ON CREATE SET
    s.name = $subject,
    s.type = $subject_type,
    s.aliases = $subject_aliases
ON MATCH SET
    s.type = CASE WHEN s.type IS NULL OR s.type = 'Unknown' THEN $subject_type ELSE s.type END,
    s.aliases = apoc_coll_to_set(coalesce(s.aliases, []) + $subject_aliases)

MERGE (o:Entity {key: $object_key})
ON CREATE SET
    o.name = $object,
    o.type = $object_type,
    o.aliases = $object_aliases
ON MATCH SET
    o.type = CASE WHEN o.type IS NULL OR o.type = 'Unknown' THEN $object_type ELSE o.type END,
    o.aliases = apoc_coll_to_set(coalesce(o.aliases, []) + $object_aliases)

MERGE (s)-[r:RELATION {type: $relation}]->(o)
ON CREATE SET
    r.sources = CASE WHEN $source_text = '' THEN [] ELSE [$source_text] END,
    r.count = 1
ON MATCH SET
    r.sources = CASE
        WHEN $source_text = '' THEN coalesce(r.sources, [])
        WHEN $source_text IN coalesce(r.sources, []) THEN r.sources
        ELSE coalesce(r.sources, []) + $source_text
    END,
    r.count = coalesce(r.count, 1) + 1
"""

# Same query without APOC, because the base Docker image does not include APOC.
UPSERT_TRIPLE_QUERY_NO_APOC = """
MERGE (s:Entity {key: $subject_key})
ON CREATE SET
    s.name = $subject,
    s.type = $subject_type,
    s.aliases = $subject_aliases
ON MATCH SET
    s.type = CASE WHEN s.type IS NULL OR s.type = 'Unknown' THEN $subject_type ELSE s.type END,
    s.aliases = coalesce(s.aliases, [])

MERGE (o:Entity {key: $object_key})
ON CREATE SET
    o.name = $object,
    o.type = $object_type,
    o.aliases = $object_aliases
ON MATCH SET
    o.type = CASE WHEN o.type IS NULL OR o.type = 'Unknown' THEN $object_type ELSE o.type END,
    o.aliases = coalesce(o.aliases, [])

MERGE (s)-[r:RELATION {type: $relation}]->(o)
ON CREATE SET
    r.sources = CASE WHEN $source_text = '' THEN [] ELSE [$source_text] END,
    r.count = 1
ON MATCH SET
    r.sources = CASE
        WHEN $source_text = '' THEN coalesce(r.sources, [])
        WHEN $source_text IN coalesce(r.sources, []) THEN r.sources
        ELSE coalesce(r.sources, []) + $source_text
    END,
    r.count = coalesce(r.count, 1) + 1
"""


def normalize_key(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return ALIAS_MAP.get(value, value)


def aliases_for(text: str, key: str) -> list[str]:
    aliases = {text.strip(), key}
    return sorted(a for a in aliases if a)


def import_triple(driver, triple: dict) -> None:
    subject = triple["subject"].strip()
    obj = triple["object"].strip()
    relation = triple["relation"].strip().upper()
    subject_key = normalize_key(subject)
    object_key = normalize_key(obj)

    params = {
        "subject": subject,
        "subject_key": subject_key,
        "subject_type": triple.get("subject_type", "Unknown"),
        "subject_aliases": aliases_for(subject, subject_key),
        "relation": relation,
        "object": obj,
        "object_key": object_key,
        "object_type": triple.get("object_type", "Unknown"),
        "object_aliases": aliases_for(obj, object_key),
        "source_text": triple.get("source_text", ""),
    }

    driver.execute_query(UPSERT_TRIPLE_QUERY_NO_APOC, **params, database_=NEO4J_DATABASE)


def main() -> None:
    if not TRIPLES_PATH.exists():
        raise FileNotFoundError(f"Missing {TRIPLES_PATH}. Run src/02_extract_triples_llm.py first.")

    triples = json.loads(TRIPLES_PATH.read_text(encoding="utf-8"))
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        for idx, triple in enumerate(triples, start=1):
            import_triple(driver, triple)
            if idx % 100 == 0:
                print(f"Imported {idx}/{len(triples)} triples...")
        print(f"Imported {len(triples)} triples into Neo4j.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
