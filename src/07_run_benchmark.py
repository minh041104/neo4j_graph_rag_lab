"""
Run benchmark comparing Flat RAG vs GraphRAG.

Input:
    data/benchmark_questions.json

Output:
    data/benchmark_results.csv

Run from project root:
    python src/07_run_benchmark.py
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
QUESTIONS_PATH = DATA_DIR / "benchmark_questions.json"
RESULTS_PATH = DATA_DIR / "benchmark_results.csv"


def load_class(file_path: Path, class_name: str):
    spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


FlatRAG = load_class(ROOT_DIR / "src" / "06_flat_rag_baseline.py", "FlatRAG")
GraphRAG = load_class(ROOT_DIR / "src" / "05_graphrag_retrieval.py", "GraphRAG")


def entity_recall_score(text: str, expected_entities: list[str]) -> tuple[float, list[str]]:
    text_lower = text.lower()
    found = []
    for entity in expected_entities:
        if entity.lower() in text_lower:
            found.append(entity)
    score = len(found) / max(1, len(expected_entities))
    return score, found


def correctness_label(score: float) -> int:
    # For a simple report: correct if at least half of expected key entities appear.
    # You can replace this with an LLM judge if required.
    return 1 if score >= 0.75 else 0


def main() -> None:
    if not QUESTIONS_PATH.exists():
        raise FileNotFoundError(f"Missing {QUESTIONS_PATH}")

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))

    flat_rag = FlatRAG()
    graph_rag = GraphRAG()

    rows: list[dict[str, Any]] = []

    try:
        for item in questions:
            qid = item["id"]
            question = item["question"]
            expected = item.get("expected_entities", [])

            print(f"\n[{qid}/{len(questions)}] {question}")

            flat_start = time.perf_counter()
            flat_result = flat_rag.answer(question)
            flat_latency = time.perf_counter() - flat_start
            flat_score, flat_found = entity_recall_score(flat_result["answer"], expected)

            graph_start = time.perf_counter()
            graph_result = graph_rag.answer(question, depth=2)
            graph_latency = time.perf_counter() - graph_start
            graph_score, graph_found = entity_recall_score(graph_result["answer"], expected)

            flat_correct = correctness_label(flat_score)
            graph_correct = correctness_label(graph_score)

            print(f"  Flat RAG: score={flat_score:.2f}, correct={flat_correct}, latency={flat_latency:.2f}s")
            print(f"  GraphRAG: score={graph_score:.2f}, correct={graph_correct}, latency={graph_latency:.2f}s")

            rows.append(
                {
                    "id": qid,
                    "type": item.get("type", "unknown"),
                    "question": question,
                    "expected_entities": "; ".join(expected),
                    "gold_answer_hint": item.get("gold_answer_hint", ""),
                    "flat_answer": flat_result["answer"],
                    "graph_answer": graph_result["answer"],
                    "flat_found_entities": "; ".join(flat_found),
                    "graph_found_entities": "; ".join(graph_found),
                    "flat_entity_recall": flat_score,
                    "graph_entity_recall": graph_score,
                    "flat_correct": flat_correct,
                    "graph_correct": graph_correct,
                    "flat_latency_seconds": flat_latency,
                    "graph_latency_seconds": graph_latency,
                    "flat_retrieved_pages": "; ".join(
                        sorted({chunk.get("page_title", "") for chunk in flat_result.get("chunks", [])})
                    ),
                    "graph_seed_nodes": "; ".join(
                        [seed.get("name", "") for seed in graph_result.get("seeds", [])]
                    ),
                    "graph_triples_count": len(graph_result.get("triples", [])),
                    "failure_note": "",
                }
            )

    finally:
        graph_rag.close()

    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_PATH, index=False, encoding="utf-8")

    print(f"\nSaved benchmark results: {RESULTS_PATH}")
    print("\nSummary:")
    print(
        df.groupby("type")[["flat_correct", "graph_correct", "flat_latency_seconds", "graph_latency_seconds"]]
        .mean(numeric_only=True)
        .round(3)
    )


if __name__ == "__main__":
    main()
