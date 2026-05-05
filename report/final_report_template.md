# Lab 19 — GraphRAG với AI Company Corpus

## 1. Mục tiêu

Xây dựng pipeline GraphRAG sử dụng Wikipedia corpus về các công ty AI, trích xuất entity/relation thành triples, load vào Neo4j, truy vấn multi-hop, và so sánh với Flat RAG.

## 2. Dataset

Corpus gồm các Wikipedia pages trong `data/wiki_pages.txt`:

- OpenAI
- Anthropic
- DeepMind
- Google Brain
- Mistral AI
- Scale AI
- Perplexity AI
- Stability AI
- Nvidia
- Microsoft
- Meta Platforms
- Amazon Web Services

## 3. Graph schema

Node:

```text
(:Entity {key, name, type, aliases, embedding})
```

Relationship:

```text
(:Entity)-[:RELATION {type, sources, count}]->(:Entity)
```

## 4. Pipeline

```text
Wikipedia pages
  -> wiki_corpus.txt
  -> LLM triple extraction
  -> triples.json
  -> Neo4j graph
  -> seed node retrieval
  -> 2-hop traversal
  -> subgraph-to-text
  -> LLM answer
```

## 5. Benchmark setup

- Flat RAG: chunk corpus, retrieve top-k text chunks, LLM answer.
- GraphRAG: retrieve seed nodes, traverse Neo4j graph up to depth 2, textualize triples, LLM answer.
- Questions: `data/benchmark_questions.json`.
- Results: `data/benchmark_results.csv`.

## 6. Results

Paste summary from `python src/07_run_benchmark.py` here.

| Type | Flat RAG Accuracy | GraphRAG Accuracy | Flat Latency | Graph Latency |
|---|---:|---:|---:|---:|
| single-hop |  |  |  |  |
| multi-hop |  |  |  |  |

## 7. Failure modes

### Flat RAG failures

- Missing one of the required chunks for multi-hop reasoning.
- Retrieved company page but missed founder/employment page.
- LLM hallucinated when retrieved context was incomplete.

### GraphRAG failures

- LLM extraction missed important relation.
- Entity duplication, for example `Google`, `Google LLC`, `Alphabet's Google`.
- Relation normalization failed, for example `FOUNDER` vs `FOUNDED_BY`.
- Direction of relation was inconsistent.
- BFS returned noisy subgraph.

## 8. Visualization

Include screenshots from Neo4j Browser:

- Full graph sample.
- 2-hop graph around OpenAI.
- Multi-hop answer subgraph.
- Highlighted answer nodes.

## 9. Cost and latency analysis

Use `data/extraction_stats.json` and `data/benchmark_results.csv` to report:

- number of chunks extracted
- total triples before/after deduplication
- extraction time
- benchmark latency
- approximate token usage when available

## 10. Conclusion

Flat RAG is adequate for simple single-hop questions. GraphRAG is better for multi-hop questions because relations are explicitly represented as paths in a knowledge graph.
