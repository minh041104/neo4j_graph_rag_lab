"""
Extract knowledge graph triples from data/wiki_corpus.txt using an LLM.

Output:
    data/triples.json
    data/extraction_stats.json

Run from project root:
    python src/02_extract_triples_llm.py
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
CORPUS_PATH = DATA_DIR / "wiki_corpus.txt"
OUTPUT_PATH = DATA_DIR / "triples.json"
STATS_PATH = DATA_DIR / "extraction_stats.json"

load_dotenv(ROOT_DIR / ".env")

ENTITY_TYPES = Literal[
    "Company",
    "Person",
    "Product",
    "Platform",
    "ResearchLab",
    "Technology",
    "Model",
    "Year",
    "Location",
    "Organization",
    "Unknown",
]


class Triple(BaseModel):
    subject: str = Field(description="Source entity name")
    subject_type: ENTITY_TYPES
    relation: str = Field(description="UPPERCASE_RELATION_NAME")
    object: str = Field(description="Target entity name")
    object_type: ENTITY_TYPES
    source_text: str = Field(description="Original sentence or phrase proving the triple")


class TripleExtraction(BaseModel):
    triples: list[Triple]


RELATION_MAP = {
    "FOUNDER": "FOUNDED_BY",
    "FOUNDERS": "FOUNDED_BY",
    "WAS_FOUNDED_BY": "FOUNDED_BY",
    "CREATED_BY": "FOUNDED_BY",
    "COFOUNDED_BY": "CO_FOUNDED_BY",
    "COFOUNDER": "CO_FOUNDED_BY",
    "CO_FOUNDERS": "CO_FOUNDED_BY",
    "CO_FOUNDER": "CO_FOUNDED_BY",
    "FORMERLY_WORKED_AT": "FORMER_EMPLOYEE_OF",
    "PREVIOUSLY_WORKED_AT": "FORMER_EMPLOYEE_OF",
    "FORMERLY_EMPLOYED_BY": "FORMER_EMPLOYEE_OF",
    "WAS_EMPLOYEE_OF": "FORMER_EMPLOYEE_OF",
    "EMPLOYED_BY": "WORKED_AT",
    "EMPLOYEE_OF": "WORKED_AT",
    "DEVELOPED": "DEVELOPS",
    "CREATED": "DEVELOPS",
    "CREATES": "DEVELOPS",
    "BUILT": "DEVELOPS",
    "BUILDS": "DEVELOPS",
    "OWNER_OF": "OWNS",
    "OWNED_BY": "OWNED_BY",
    "SUBSIDIARY": "SUBSIDIARY_OF",
    "PART_OF": "PART_OF",
    "IS_PART_OF": "PART_OF",
}


SYSTEM_INSTRUCTIONS = """
You extract factual knowledge graph triples from Wikipedia-style text.

Extract facts useful for GraphRAG over AI companies:
- company founders and co-founders
- previous employers and employment history of founders/executives/researchers
- acquisitions, parent companies, subsidiaries, divisions, and organizational relationships
- products, AI models, platforms, APIs, cloud services, GPUs, research labs
- investments and partnerships
- company locations and founding years

Rules:
- Extract only facts explicitly stated in the text.
- Do not invent facts.
- Use concise canonical entity names.
- Relations must be uppercase with underscores.
- Prefer these relation names when possible:
  FOUNDED_BY, CO_FOUNDED_BY, FOUNDED_IN, WORKED_AT, FORMER_EMPLOYEE_OF,
  ACQUIRED_BY, ACQUIRED, INVESTED_IN, PARTNERED_WITH, DEVELOPS, OWNS,
  OWNED_BY, PART_OF, SUBSIDIARY_OF, PARENT_COMPANY, PRODUCES, CREATED,
  LOCATED_IN, RENAMED_TO, MERGED_INTO.
- Include source_text for evidence.
""".strip()


def split_corpus(text: str, max_chars: int) -> list[str]:
    """Split corpus into chunks while preserving Wikipedia page boundaries when possible."""
    page_blocks = re.split(r"(?=^=== PAGE: .+ ===$)", text, flags=re.MULTILINE)
    chunks: list[str] = []

    for page in page_blocks:
        page = page.strip()
        if not page:
            continue

        paragraphs = [p.strip() for p in page.split("\n\n") if p.strip()]
        current = ""

        for paragraph in paragraphs:
            if len(current) + len(paragraph) + 2 > max_chars:
                if current:
                    chunks.append(current.strip())
                current = paragraph
            else:
                current = f"{current}\n\n{paragraph}" if current else paragraph

        if current:
            chunks.append(current.strip())

    return chunks


def normalize_relation(relation: str) -> str:
    relation = relation.strip().upper()
    relation = re.sub(r"[^A-Z0-9]+", "_", relation)
    relation = re.sub(r"_+", "_", relation).strip("_")
    return RELATION_MAP.get(relation, relation)


def clean_triples(triples: list[Triple]) -> list[dict]:
    cleaned: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for triple in triples:
        subject = triple.subject.strip()
        obj = triple.object.strip()
        relation = normalize_relation(triple.relation)
        source_text = triple.source_text.strip()

        if not subject or not obj or not relation:
            continue

        if subject.lower() == obj.lower():
            continue

        key = (subject.lower(), relation, obj.lower())
        if key in seen:
            continue
        seen.add(key)

        cleaned.append(
            {
                "subject": subject,
                "subject_type": triple.subject_type,
                "relation": relation,
                "object": obj,
                "object_type": triple.object_type,
                "source_text": source_text,
            }
        )

    return cleaned


def parse_with_responses_api(client: OpenAI, model: str, chunk: str) -> tuple[list[dict], dict]:
    response = client.responses.parse(
        model=model,
        instructions=SYSTEM_INSTRUCTIONS,
        input=f"Extract knowledge graph triples from this text:\n\n{chunk}",
        text_format=TripleExtraction,
    )

    parsed: TripleExtraction = response.output_parsed
    usage = getattr(response, "usage", None)
    usage_dict = usage.model_dump() if hasattr(usage, "model_dump") else {}
    return clean_triples(parsed.triples), usage_dict


def parse_with_chat_json_fallback(client: OpenAI, model: str, chunk: str) -> tuple[list[dict], dict]:
    schema_hint = TripleExtraction.model_json_schema()
    prompt = f"""
Extract knowledge graph triples from this text.
Return valid JSON only that matches this JSON Schema:
{json.dumps(schema_hint, ensure_ascii=False)}

Text:
{chunk}
""".strip()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    parsed = TripleExtraction.model_validate(data)
    usage = getattr(response, "usage", None)
    usage_dict = usage.model_dump() if hasattr(usage, "model_dump") else {}
    return clean_triples(parsed.triples), usage_dict


def extract_triples_from_chunk(client: OpenAI, model: str, chunk: str) -> tuple[list[dict], dict, str]:
    try:
        triples, usage = parse_with_responses_api(client, model, chunk)
        return triples, usage, "responses.parse"
    except Exception as first_error:
        print(f"  Responses API parse failed, falling back to Chat Completions JSON. Reason: {first_error}")
        try:
            triples, usage = parse_with_chat_json_fallback(client, model, chunk)
            return triples, usage, "chat.completions.json"
        except (json.JSONDecodeError, ValidationError) as second_error:
            raise RuntimeError(
                "Both structured extraction methods failed. "
                f"Responses error: {first_error}. Fallback error: {second_error}"
            ) from second_error


def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    max_chars = int(os.getenv("MAX_CHARS_PER_CHUNK", "3500"))
    max_chunks = int(os.getenv("MAX_CHUNKS", "0"))

    if not api_key:
        raise ValueError("Missing OPENAI_API_KEY. Copy .env.example to .env and add your key.")

    if not CORPUS_PATH.exists():
        raise FileNotFoundError(
            f"Missing corpus file: {CORPUS_PATH}. Run src/00_download_wikipedia_corpus.py first."
        )

    corpus = CORPUS_PATH.read_text(encoding="utf-8")
    chunks = split_corpus(corpus, max_chars=max_chars)
    if max_chunks > 0:
        chunks = chunks[:max_chunks]

    if not chunks:
        raise ValueError("Corpus is empty after splitting.")

    client = OpenAI(api_key=api_key)
    all_triples: list[dict] = []
    stats: list[dict] = []

    started = time.perf_counter()
    for idx, chunk in enumerate(chunks, start=1):
        chunk_started = time.perf_counter()
        print(f"Extracting chunk {idx}/{len(chunks)} ({len(chunk)} chars)...")
        triples, usage, method = extract_triples_from_chunk(client, model, chunk)
        elapsed = time.perf_counter() - chunk_started
        print(f"  -> extracted {len(triples)} triples in {elapsed:.2f}s via {method}")

        all_triples.extend(triples)
        stats.append(
            {
                "chunk_id": idx,
                "chars": len(chunk),
                "triples": len(triples),
                "seconds": elapsed,
                "method": method,
                "usage": usage,
            }
        )

    # Global deduplication.
    deduped: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for triple in all_triples:
        key = (triple["subject"].lower(), triple["relation"], triple["object"].lower())
        if key not in seen:
            deduped.append(triple)
            seen.add(key)

    OUTPUT_PATH.write_text(json.dumps(deduped, indent=2, ensure_ascii=False), encoding="utf-8")
    STATS_PATH.write_text(
        json.dumps(
            {
                "model": model,
                "chunks": len(chunks),
                "total_triples_before_dedup": len(all_triples),
                "total_triples_after_dedup": len(deduped),
                "total_seconds": time.perf_counter() - started,
                "chunk_stats": stats,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"\nSaved triples: {OUTPUT_PATH}")
    print(f"Saved stats: {STATS_PATH}")
    print(f"Triples before dedup: {len(all_triples)}")
    print(f"Triples after dedup: {len(deduped)}")


if __name__ == "__main__":
    main()
