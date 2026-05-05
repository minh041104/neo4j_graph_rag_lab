# Lab 19 — GraphRAG với Neo4j cho AI Company Corpus

Project này triển khai pipeline GraphRAG đầy đủ:

```text
Wikipedia corpus
  -> LLM entity/relation extraction
  -> triples.json
  -> Neo4j knowledge graph
  -> seed node retrieval
  -> BFS / 2-hop traversal
  -> subgraph-to-text
  -> LLM answer
  -> benchmark Flat RAG vs GraphRAG
```

## 1. Cấu trúc project

```text
graphrag-neo4j-lab/
  README.md
  requirements.txt
  docker-compose.yml
  .env.example

  data/
    wiki_pages.txt
    benchmark_questions.json

  src/
    00_download_wikipedia_corpus.py
    01_create_schema.py
    02_extract_triples_llm.py
    03_import_to_neo4j.py
    04_create_node_embeddings.py
    05_graphrag_retrieval.py
    06_flat_rag_baseline.py
    07_run_benchmark.py
    08_visualization_queries.cypher

  report/
    final_report_template.md
    screenshots/
```

## 2. Setup môi trường

### 2.1. Tạo virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2.2. Tạo file `.env`

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Sau đó mở `.env` và điền:

```env
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

## 3. Chạy Neo4j

```bash
docker compose up -d
```

Mở Neo4j Browser:

```text
http://localhost:7474
```

Đăng nhập:

```text
Username: neo4j
Password: password12345
```

## 4. Chạy pipeline GraphRAG

Chạy từ root project.

### Bước 1: Tải Wikipedia corpus

```bash
python src/00_download_wikipedia_corpus.py
```

Output:

```text
data/wiki_corpus.txt
```

### Bước 2: Tạo schema Neo4j

```bash
python src/01_create_schema.py
```

### Bước 3: Extract triples bằng LLM

```bash
python src/02_extract_triples_llm.py
```

Output:

```text
data/triples.json
data/extraction_stats.json
```

Nếu muốn test nhanh ít chunk trước, sửa trong `.env`:

```env
MAX_CHUNKS=3
```

Khi chạy đầy đủ thì để:

```env
MAX_CHUNKS=0
```

### Bước 4: Import triples vào Neo4j

```bash
python src/03_import_to_neo4j.py
```

### Bước 5: Tạo node embeddings, optional nhưng nên làm

```bash
python src/04_create_node_embeddings.py
```

### Bước 6: Test GraphRAG

```bash
python src/05_graphrag_retrieval.py
```

Thử hỏi:

```text
What is OpenAI?
```

hoặc:

```text
Which AI companies were founded by people formerly associated with OpenAI?
```

### Bước 7: Test Flat RAG baseline

```bash
python src/06_flat_rag_baseline.py
```

### Bước 8: Chạy benchmark 20 câu hỏi

```bash
python src/07_run_benchmark.py
```

Output:

```text
data/benchmark_results.csv
```

## 5. Neo4j visualization

Mở file:

```text
src/08_visualization_queries.cypher
```

Copy từng query vào Neo4j Browser.

Query xem full graph sample:

```cypher
MATCH (a)-[r:RELATION]->(b)
RETURN a, r, b
LIMIT 100;
```

Query xem 2-hop quanh OpenAI:

```cypher
MATCH p = (:Entity {key: 'openai'})-[*1..2]-(n)
RETURN p
LIMIT 100;
```

Query multi-hop ví dụ:

```cypher
MATCH p = (company:Entity)-[r1:RELATION]-(person:Entity)-[r2:RELATION]-(google:Entity)
WHERE r1.type IN ['FOUNDED_BY', 'CO_FOUNDED_BY']
  AND r2.type IN ['WORKED_AT', 'FORMER_EMPLOYEE_OF']
  AND toLower(google.name) CONTAINS 'google'
RETURN p
LIMIT 100;
```

## 6. Graph schema

Node:

```text
(:Entity {
  key,
  name,
  type,
  aliases,
  embedding,
  embedding_model
})
```

Relationship:

```text
(:Entity)-[:RELATION {
  type,
  sources,
  count
}]->(:Entity)
```

Ví dụ:

```text
(OpenAI)-[:RELATION {type: "FOUNDED_BY"}]->(Sam Altman)
(Microsoft)-[:RELATION {type: "INVESTED_IN"}]->(OpenAI)
(Anthropic)-[:RELATION {type: "FOUNDED_BY"}]->(Dario Amodei)
```

## 7. Flat RAG vs GraphRAG

Flat RAG:

```text
question -> chunk retrieval -> LLM answer
```

GraphRAG:

```text
question -> seed nodes -> graph traversal -> subgraph-to-text -> LLM answer
```

GraphRAG có lợi thế với câu hỏi multi-hop vì quan hệ được biểu diễn trực tiếp trong graph.

## 8. Deliverables

- GitHub repo chứa code.
- Screenshot Neo4j graph.
- `data/benchmark_results.csv`.
- Báo cáo dựa trên `report/final_report_template.md`.
- Phân tích failure modes và chi phí/token/time.

## 9. Lỗi thường gặp

### Không thấy graph trong Neo4j

Chạy:

```bash
python src/01_create_schema.py
python src/03_import_to_neo4j.py
```

Sau đó vào Neo4j Browser:

```cypher
MATCH (a)-[r:RELATION]->(b)
RETURN a, r, b
LIMIT 100;
```

### `src/02_extract_triples_llm.py` lỗi API

Kiểm tra:

```bash
pip install --upgrade openai pydantic python-dotenv
```

Kiểm tra `.env`:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

### Query multi-hop không ra kết quả

Kiểm tra relation types:

```cypher
MATCH ()-[r:RELATION]->()
RETURN r.type AS relation_type, count(*) AS count
ORDER BY count DESC;
```

Nếu thiếu `WORKED_AT`, `FORMER_EMPLOYEE_OF`, `FOUNDED_BY`, cần cải thiện prompt extraction hoặc bổ sung triples thủ công.
