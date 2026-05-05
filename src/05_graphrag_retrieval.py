"""
GraphRAG retrieval over Neo4j:
    query -> seed nodes -> BFS-style graph traversal -> subgraph-to-text -> LLM answer

Run interactively from project root:
    python src/05_graphrag_retrieval.py
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from neo4j import GraphDatabase
from openai import OpenAI

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
EMBEDDING_CACHE_PATH = DATA_DIR / "node_embeddings.json"
load_dotenv(ROOT_DIR / ".env")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password12345")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

ALLOWED_RELATIONS = {
    "FOUNDED_BY",
    "CO_FOUNDED_BY",
    "FOUNDED_IN",
    "WORKED_AT",
    "FORMER_EMPLOYEE_OF",
    "ACQUIRED_BY",
    "ACQUIRED",
    "INVESTED_IN",
    "PARTNERED_WITH",
    "DEVELOPS",
    "OWNS",
    "OWNED_BY",
    "PART_OF",
    "SUBSIDIARY_OF",
    "PARENT_COMPANY",
    "PRODUCES",
    "CREATED",
    "LOCATED_IN",
    "RENAMED_TO",
    "MERGED_INTO",
}

GET_ENTITIES_QUERY = """
MATCH (e:Entity)
RETURN e.key AS key, e.name AS name, e.type AS type, coalesce(e.aliases, []) AS aliases
ORDER BY e.name
"""


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def cosine(a: list[float], b: list[float]) -> float:
    av = np.array(a, dtype=np.float32)
    bv = np.array(b, dtype=np.float32)
    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denom == 0:
        return 0.0
    return float(np.dot(av, bv) / denom)


class GraphRAG:
    def __init__(self) -> None:
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

    def close(self) -> None:
        self.driver.close()

    def get_entities(self) -> list[dict[str, Any]]:
        records, _, _ = self.driver.execute_query(GET_ENTITIES_QUERY, database_=NEO4J_DATABASE)
        return [record.data() for record in records]

    def find_seed_nodes(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Hybrid seed retrieval: exact/alias match first, embedding fallback second."""
        entities = self.get_entities()
        q_norm = normalize_text(question)
        matches: list[dict[str, Any]] = []

        for entity in entities:
            names = [entity.get("name", "")] + list(entity.get("aliases") or [])
            for name in names:
                name_norm = normalize_text(name)
                if name_norm and name_norm in q_norm:
                    entity_with_score = dict(entity)
                    entity_with_score["seed_score"] = 1.0
                    entity_with_score["seed_method"] = "exact_or_alias_match"
                    matches.append(entity_with_score)
                    break

        # Deduplicate while preserving order.
        deduped = []
        seen = set()
        for item in matches:
            if item["key"] not in seen:
                deduped.append(item)
                seen.add(item["key"])

        if deduped:
            return deduped[:top_k]

        # Embedding fallback if cache and API are available.
        if self.client and EMBEDDING_CACHE_PATH.exists():
            cache = json.loads(EMBEDDING_CACHE_PATH.read_text(encoding="utf-8"))
            response = self.client.embeddings.create(model=EMBEDDING_MODEL, input=question)
            q_embedding = response.data[0].embedding

            scored = []
            for entity in entities:
                emb = cache.get(entity["key"])
                if emb:
                    scored.append((cosine(q_embedding, emb), entity))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = []
            for score, entity in scored[:top_k]:
                entity_with_score = dict(entity)
                entity_with_score["seed_score"] = score
                entity_with_score["seed_method"] = "embedding_fallback"
                results.append(entity_with_score)
            return results

        return []

    def get_subgraph_triples(
        self,
        seed_keys: list[str],
        depth: int = 2,
        max_triples: int = 150,
        relation_filter: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        depth = max(1, min(int(depth), 3))
        relation_filter = relation_filter or ALLOWED_RELATIONS

        query = f"""
        MATCH path = (seed:Entity)-[*1..{depth}]-(neighbor:Entity)
        WHERE seed.key IN $seed_keys
        UNWIND relationships(path) AS r
        WITH DISTINCT startNode(r) AS s, r, endNode(r) AS o
        WHERE r.type IN $relation_filter
        RETURN
            s.key AS subject_key,
            s.name AS subject,
            s.type AS subject_type,
            r.type AS relation,
            o.key AS object_key,
            o.name AS object,
            o.type AS object_type,
            coalesce(r.sources, []) AS sources,
            coalesce(r.count, 1) AS count
        ORDER BY subject, relation, object
        LIMIT $max_triples
        """
        records, _, _ = self.driver.execute_query(
            query,
            seed_keys=seed_keys,
            relation_filter=sorted(relation_filter),
            max_triples=max_triples,
            database_=NEO4J_DATABASE,
        )
        return [record.data() for record in records]

    @staticmethod
    def textualize_triples(triples: list[dict[str, Any]]) -> str:
        lines = []
        for t in triples:
            evidence = ""
            sources = t.get("sources") or []
            if sources:
                evidence = f" Evidence: {sources[0][:300]}"
            lines.append(f"- {t['subject']} --{t['relation']}--> {t['object']}.{evidence}")
        return "\n".join(lines)

    def answer_with_llm(self, question: str, graph_context: str) -> str:
        if not self.client:
            return (
                "OPENAI_API_KEY is missing. Returning graph context only.\n\n"
                f"Graph context:\n{graph_context}"
            )

        instructions = (
            "You are a GraphRAG assistant. Answer using ONLY the graph context. "
            "If the answer is not present in the graph context, say the graph does not contain enough information. "
            "Be concise and cite the relevant entity-relation facts in plain language."
        )
        user_input = f"Question:\n{question}\n\nGraph context:\n{graph_context}"

        try:
            response = self.client.responses.create(
                model=OPENAI_MODEL,
                instructions=instructions,
                input=user_input,
            )
            return response.output_text
        except Exception:
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": user_input},
                ],
            )
            return response.choices[0].message.content or ""

    def answer(self, question: str, depth: int = 2) -> dict[str, Any]:
        seeds = self.find_seed_nodes(question)
        if not seeds:
            return {
                "question": question,
                "answer": "No seed nodes found for the question.",
                "seeds": [],
                "graph_context": "",
                "triples": [],
            }

        triples = self.get_subgraph_triples([seed["key"] for seed in seeds], depth=depth)
        context = self.textualize_triples(triples)
        answer = self.answer_with_llm(question, context)

        return {
            "question": question,
            "answer": answer,
            "seeds": seeds,
            "graph_context": context,
            "triples": triples,
        }


def main() -> None:
    rag = GraphRAG()
    try:
        question = input("Question: ").strip()
        result = rag.answer(question, depth=2)
        print("\nSeed nodes:")
        for seed in result["seeds"]:
            print(f"- {seed['name']} ({seed['type']}) [{seed.get('seed_method')}, score={seed.get('seed_score')}] ")

        print("\nGraph context:")
        print(result["graph_context"])

        print("\nAnswer:")
        print(result["answer"])
    finally:
        rag.close()


if __name__ == "__main__":
    main()
