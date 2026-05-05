"""
Flat RAG baseline over data/wiki_corpus.txt:
    corpus chunks -> embedding/keyword retrieval -> LLM answer

Run interactively from project root:
    python src/06_flat_rag_baseline.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
CORPUS_PATH = DATA_DIR / "wiki_corpus.txt"
CHUNK_CACHE_PATH = DATA_DIR / "flat_rag_chunks.json"
load_dotenv(ROOT_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


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


def chunk_text(text: str, max_chars: int = 1800, overlap: int = 250) -> list[dict[str, Any]]:
    """Simple character chunking with overlap and page-title preservation."""
    page_blocks = re.split(r"(?=^=== PAGE: .+ ===$)", text, flags=re.MULTILINE)
    chunks: list[dict[str, Any]] = []
    chunk_id = 0

    for page in page_blocks:
        page = page.strip()
        if not page:
            continue

        title_match = re.search(r"^=== PAGE: (.+?) ===$", page, flags=re.MULTILINE)
        page_title = title_match.group(1).strip() if title_match else "Unknown"

        start = 0
        while start < len(page):
            end = min(start + max_chars, len(page))
            chunk = page[start:end].strip()
            if chunk:
                chunk_id += 1
                chunks.append({"chunk_id": chunk_id, "page_title": page_title, "text": chunk})
            if end == len(page):
                break
            start = max(0, end - overlap)

    return chunks


class FlatRAG:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
        self.chunks = self.load_or_create_chunks()

    def load_or_create_chunks(self) -> list[dict[str, Any]]:
        if CHUNK_CACHE_PATH.exists():
            return json.loads(CHUNK_CACHE_PATH.read_text(encoding="utf-8"))

        if not CORPUS_PATH.exists():
            raise FileNotFoundError(f"Missing {CORPUS_PATH}. Run src/00_download_wikipedia_corpus.py first.")

        corpus = CORPUS_PATH.read_text(encoding="utf-8")
        chunks = chunk_text(corpus)
        CHUNK_CACHE_PATH.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
        return chunks

    def ensure_embeddings(self) -> None:
        if not self.client:
            return

        missing = [chunk for chunk in self.chunks if "embedding" not in chunk]
        if not missing:
            return

        print(f"Creating embeddings for {len(missing)} flat RAG chunks...")
        batch_size = 64
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            texts = [chunk["text"] for chunk in batch]
            response = self.client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            for chunk, item in zip(batch, response.data):
                chunk["embedding"] = item.embedding
            print(f"Embedded {min(start + batch_size, len(missing))}/{len(missing)}")

        CHUNK_CACHE_PATH.write_text(json.dumps(self.chunks, ensure_ascii=False), encoding="utf-8")

    def keyword_retrieve(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        q_terms = set(normalize_text(question).split())
        scored = []
        for chunk in self.chunks:
            text_terms = set(normalize_text(chunk["text"]).split())
            score = len(q_terms & text_terms) / max(1, len(q_terms))
            scored.append((score, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{**chunk, "score": score, "retrieval_method": "keyword"} for score, chunk in scored[:top_k]]

    def embedding_retrieve(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        if not self.client:
            return self.keyword_retrieve(question, top_k=top_k)

        self.ensure_embeddings()
        response = self.client.embeddings.create(model=EMBEDDING_MODEL, input=question)
        q_embedding = response.data[0].embedding

        scored = []
        for chunk in self.chunks:
            emb = chunk.get("embedding")
            if emb:
                scored.append((cosine(q_embedding, emb), chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{**chunk, "score": score, "retrieval_method": "embedding"} for score, chunk in scored[:top_k]]

    @staticmethod
    def format_context(chunks: list[dict[str, Any]]) -> str:
        lines = []
        for chunk in chunks:
            lines.append(
                f"[Chunk {chunk['chunk_id']} | {chunk['page_title']} | score={chunk.get('score', 0):.3f}]\n{chunk['text']}"
            )
        return "\n\n---\n\n".join(lines)

    def answer_with_llm(self, question: str, context: str) -> str:
        if not self.client:
            return (
                "OPENAI_API_KEY is missing. Returning retrieved context only.\n\n"
                f"Flat RAG context:\n{context}"
            )

        instructions = (
            "You are a Flat RAG assistant. Answer using ONLY the retrieved text context. "
            "If the context does not contain enough information, say so."
        )
        user_input = f"Question:\n{question}\n\nRetrieved context:\n{context}"

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

    def answer(self, question: str, top_k: int = 5) -> dict[str, Any]:
        chunks = self.embedding_retrieve(question, top_k=top_k)
        context = self.format_context(chunks)
        answer = self.answer_with_llm(question, context)
        return {
            "question": question,
            "answer": answer,
            "chunks": chunks,
            "context": context,
        }


def main() -> None:
    rag = FlatRAG()
    question = input("Question: ").strip()
    result = rag.answer(question)

    print("\nRetrieved chunks:")
    for chunk in result["chunks"]:
        print(f"- {chunk['page_title']} | chunk={chunk['chunk_id']} | score={chunk.get('score', 0):.3f}")

    print("\nAnswer:")
    print(result["answer"])


if __name__ == "__main__":
    main()
