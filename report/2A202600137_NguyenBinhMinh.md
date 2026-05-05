# Báo cáo Lab: Xây dựng hệ thống GraphRAG với Neo4j cho Tech Company Corpus

## 1. Mục tiêu

Mục tiêu của bài lab là xây dựng một hệ thống GraphRAG sử dụng Neo4j để biểu diễn tri thức về các công ty công nghệ/AI dưới dạng đồ thị. Hệ thống thực hiện các bước chính: thu thập corpus, trích xuất thực thể và quan hệ, xây dựng knowledge graph trong Neo4j, truy vấn graph theo hướng 1-hop/2-hop, sinh câu trả lời bằng LLM, và so sánh kết quả với một hệ thống Flat RAG baseline.

Project tập trung vào việc đánh giá sự khác biệt giữa Flat RAG và GraphRAG trong hai nhóm câu hỏi:

- **Single-hop questions**: câu hỏi có thể trả lời bằng một thực thể hoặc một quan hệ trực tiếp.
- **Multi-hop / broad questions**: câu hỏi cần kết nối nhiều thực thể, nhiều quan hệ, hoặc tổng hợp trên toàn corpus.

---

## 2. Dataset

Corpus được xây dựng từ các Wikipedia pages liên quan đến các công ty/tổ chức AI và công nghệ sau:

1. OpenAI
2. Anthropic
3. DeepMind
4. Google Brain
5. Mistral AI
6. Scale AI
7. Perplexity AI
8. Stability AI
9. Nvidia
10. Microsoft
11. Meta Platforms
12. Amazon Web Services

Các trang này được tải về và lưu thành corpus text. Sau đó, hệ thống sử dụng LLM để trích xuất các triples dạng:

```text
(subject, relation, object)
```

Ví dụ:

```text
(OpenAI, DEVELOPS, ChatGPT)
(Microsoft, INVESTED_IN, OpenAI)
(Anthropic, DEVELOPS, Claude)
(Meta Platforms, DEVELOPS, Llama models)
(Nvidia, PRODUCES, GPUs)
```

---

## 3. Kiến trúc hệ thống

Pipeline tổng thể của hệ thống:

```text
Wikipedia corpus
    ↓
Chunk text
    ↓
LLM entity/relation extraction
    ↓
Triples JSON
    ↓
Neo4j knowledge graph
    ↓
GraphRAG retrieval
    ↓
Subgraph-to-text
    ↓
LLM answer generation
    ↓
Benchmark against Flat RAG
```

Hệ thống gồm hai nhánh chính:

### 3.1. Flat RAG baseline

Flat RAG hoạt động theo pipeline truyền thống:

```text
Question
    ↓
Embedding search over text chunks
    ↓
Top-k retrieved chunks
    ↓
LLM answer
```

Flat RAG phù hợp với các câu hỏi mà câu trả lời nằm trực tiếp trong một đoạn văn bản.

### 3.2. GraphRAG với Neo4j

GraphRAG hoạt động theo pipeline:

```text
Question
    ↓
Seed node retrieval
    ↓
1-hop / 2-hop graph traversal
    ↓
Retrieve triples from Neo4j
    ↓
Convert triples into text context
    ↓
LLM answer
```

GraphRAG phù hợp hơn với các câu hỏi cần đi qua các quan hệ rõ ràng giữa các thực thể, ví dụ:

```text
Microsoft --INVESTED_IN--> OpenAI --DEVELOPS--> ChatGPT
```

---

## 4. Neo4j graph schema

Project sử dụng schema đơn giản và linh hoạt:

### 4.1. Node schema

```cypher
(:Entity {
  key: string,
  name: string,
  type: string,
  aliases: list<string>,
  embedding: list<float>
})
```

Trong đó:

- `key`: tên thực thể đã được normalize, dùng để chống trùng node.
- `name`: tên hiển thị của thực thể.
- `type`: loại thực thể, ví dụ `Company`, `Person`, `Product`, `Platform`, `Technology`.
- `aliases`: các tên thay thế nếu có.
- `embedding`: vector embedding của node, phục vụ seed node retrieval.

### 4.2. Relationship schema

```cypher
(:Entity)-[:RELATION {
  type: string,
  sources: list<string>,
  count: integer
}]->(:Entity)
```

Thay vì tạo relationship type động như `:FOUNDED_BY`, `:DEVELOPS`, `:OWNS`, project dùng một relationship type chung là `:RELATION`, còn loại quan hệ thật được lưu ở property `type`.

Ví dụ:

```cypher
(OpenAI)-[:RELATION {type: "DEVELOPS"}]->(ChatGPT)
(Microsoft)-[:RELATION {type: "INVESTED_IN"}]->(OpenAI)
```

Cách thiết kế này giúp tránh lỗi khi relation được sinh tự động bởi LLM và giúp query dễ chuẩn hóa hơn.

---

## 5. Deduplication và normalization

Để hạn chế node trùng lặp, project sử dụng các cơ chế sau:

1. **Normalize entity name thành key**
   - Chuyển chữ thường.
   - Xóa khoảng trắng thừa.
   - Xóa ký tự đặc biệt không cần thiết.

2. **Alias mapping thủ công**
   - Ví dụ:

```text
Open AI → OpenAI
OpenAI Inc. → OpenAI
AWS → Amazon Web Services
Meta → Meta Platforms
Facebook → Meta Platforms
Nvidia Corporation → Nvidia
Microsoft Corporation → Microsoft
```

3. **Neo4j unique constraint**

```cypher
CREATE CONSTRAINT entity_key_unique IF NOT EXISTS
FOR (e:Entity)
REQUIRE e.key IS UNIQUE;
```

4. **MERGE-based upsert**

Khi import triples, hệ thống dùng `MERGE` thay vì `CREATE`, do đó nếu node đã tồn tại thì dùng lại node cũ thay vì tạo node mới.

Hạn chế: project hiện mới dùng rule-based deduplication. Các trường hợp semantic entity resolution phức tạp như `Sam Altman` và `Samuel Altman`, hoặc `DeepMind` và `Google DeepMind`, vẫn cần cải thiện thêm bằng fuzzy matching, embedding similarity hoặc LLM-based entity resolution.

---

## 6. Benchmark setup

Benchmark gồm 20 câu hỏi, chia thành hai nhóm:

- `single-hop`
- `multi-hop`

Mỗi hệ thống được chấm theo `score` từ 0 đến 1. Sau khi chỉnh lại rule chấm điểm, câu trả lời chỉ được tính là đúng nếu:

```text
score >= 0.8
```

Điều này giúp phân biệt giữa câu trả lời đúng hoàn toàn và câu trả lời chỉ đúng một phần. Ví dụ `score = 0.5` được xem là partial answer, không được tính là correct.

---

## 7. Kết quả benchmark

### 7.1. Kết quả từng câu hỏi

| # | Question | Flat Score | Flat Correct | Flat Latency | Graph Score | Graph Correct | Graph Latency |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | What is OpenAI? | 1.00 | 1 | 4.95s | 1.00 | 1 | 2.07s |
| 2 | Which company developed ChatGPT? | 1.00 | 1 | 2.74s | 1.00 | 1 | 1.36s |
| 3 | Which company developed Claude? | 1.00 | 1 | 1.40s | 1.00 | 1 | 1.77s |
| 4 | What is DeepMind related to? | 0.50 | 0 | 1.60s | 1.00 | 1 | 2.48s |
| 5 | Which company is associated with Mistral models? | 1.00 | 1 | 1.43s | 1.00 | 1 | 1.72s |
| 6 | Which company is associated with Llama models? | 0.50 | 0 | 1.77s | 1.00 | 1 | 2.48s |
| 7 | Which company provides Amazon Web Services? | 1.00 | 1 | 1.55s | 1.00 | 1 | 1.79s |
| 8 | Which company produces GPUs used in AI? | 1.00 | 1 | 1.55s | 0.50 | 0 | 1.43s |
| 9 | Which company owns or is related to Instagram and WhatsApp? | 1.00 | 1 | 1.72s | 1.00 | 1 | 1.69s |
| 10 | Which company is associated with Windows and Azure? | 1.00 | 1 | 2.21s | 1.00 | 1 | 1.33s |
| 11 | Which AI companies were founded by people formerly associated with OpenAI? | 0.50 | 0 | 2.29s | 0.50 | 0 | 2.32s |
| 12 | Which AI companies are connected to Google through acquisition, organization, or former employment relationships? | 1.00 | 1 | 2.60s | 1.00 | 1 | 2.54s |
| 13 | Which companies in the corpus are connected to cloud computing and AI infrastructure? | 0.67 | 0 | 2.48s | 0.00 | 0 | 1.69s |
| 14 | Which companies in the corpus are connected to large language models? | 0.50 | 0 | 2.36s | 0.25 | 0 | 2.06s |
| 15 | Which AI company is linked to both ChatGPT and Microsoft? | 1.00 | 1 | 1.46s | 1.00 | 1 | 1.26s |
| 16 | Which companies in the corpus are connected to Google or Alphabet? | 1.00 | 1 | 2.37s | 1.00 | 1 | 2.03s |
| 17 | Which company is connected to GPUs and AI training? | 1.00 | 1 | 1.66s | 0.67 | 0 | 4.07s |
| 18 | Which companies in the corpus are AI startups rather than large platform companies? | 0.83 | 1 | 1.86s | 0.00 | 0 | 2.60s |
| 19 | Which company is connected to search or answer engines in AI? | 1.00 | 1 | 2.11s | 0.00 | 0 | 1.45s |
| 20 | Which companies are connected through AI model development and cloud/platform infrastructure? | 0.80 | 1 | 2.44s | 0.20 | 0 | 3.08s |

### 7.2. Summary

| Type | Flat Correct | Graph Correct | Flat Latency | Graph Latency |
|---|---:|---:|---:|---:|
| single-hop | 0.8 | 0.9 | 2.091s | 1.812s |
| multi-hop | 0.7 | 0.3 | 2.163s | 2.311s |

---

## 8. Phân tích kết quả

### 8.1. Single-hop questions

Ở nhóm single-hop, GraphRAG đạt kết quả tốt hơn Flat RAG:

```text
Flat RAG correct: 0.8
GraphRAG correct: 0.9
```

GraphRAG cũng có latency thấp hơn:

```text
Flat RAG latency: 2.091s
GraphRAG latency: 1.812s
```

Điều này cho thấy khi câu hỏi có entity rõ ràng và graph đã chứa đúng relation cần thiết, GraphRAG có thể trả lời nhanh và chính xác hơn nhờ việc truy vấn context nhỏ gọn từ Neo4j.

Ví dụ các câu GraphRAG trả lời tốt:

```text
Which company developed ChatGPT?
Which company developed Claude?
Which company is associated with Llama models?
Which company is associated with Windows and Azure?
```

Các câu này đều có quan hệ trực tiếp hoặc gần trực tiếp trong graph.

---

### 8.2. Multi-hop questions

Ở nhóm multi-hop, Flat RAG hiện tốt hơn GraphRAG:

```text
Flat RAG correct: 0.7
GraphRAG correct: 0.3
```

Đây là kết quả quan trọng vì nó cho thấy prototype GraphRAG hiện tại chưa đủ mạnh cho mọi loại câu hỏi nhiều bước.

Các câu GraphRAG fail nặng gồm:

```text
[13] Which companies in the corpus are connected to cloud computing and AI infrastructure?
[14] Which companies in the corpus are connected to large language models?
[18] Which companies in the corpus are AI startups rather than large platform companies?
[19] Which company is connected to search or answer engines in AI?
[20] Which companies are connected through AI model development and cloud/platform infrastructure?
```

Các câu này không chỉ là multi-hop path query đơn giản. Chúng là các câu hỏi dạng broad/global/category query, tức là cần quét nhiều công ty trong corpus và tổng hợp theo chủ đề.

Ví dụ câu:

```text
Which companies in the corpus are AI startups rather than large platform companies?
```

Muốn GraphRAG trả lời tốt, graph cần có thông tin phân loại như:

```text
OpenAI --HAS_CATEGORY--> AI Startup
Anthropic --HAS_CATEGORY--> AI Startup
Microsoft --HAS_CATEGORY--> Large Platform Company
Meta Platforms --HAS_CATEGORY--> Large Platform Company
Amazon Web Services --HAS_CATEGORY--> Cloud Platform
```

Hiện tại graph chủ yếu chứa triples thực thể-quan hệ được trích xuất từ Wikipedia, chưa có lớp category/classification rõ ràng. Vì vậy GraphRAG khó trả lời loại câu này.

---

## 9. Failure analysis

### 9.1. Nguyên nhân GraphRAG trả lời sai ở multi-hop/broad queries

Có bốn nguyên nhân chính:

#### 1. Seed node retrieval quá hẹp

GraphRAG hiện tại bắt đầu bằng cách tìm seed node từ câu hỏi, sau đó duyệt graph 1-hop hoặc 2-hop. Cách này tốt khi câu hỏi có entity rõ, ví dụ:

```text
ChatGPT
OpenAI
Microsoft
Claude
```

Nhưng với câu hỏi dạng:

```text
Which companies in the corpus are connected to large language models?
```

không có một seed node duy nhất rõ ràng. Hệ thống cần global graph retrieval, tức là tìm trên toàn graph các công ty liên quan đến model development.

#### 2. Graph thiếu category triples

Một số câu hỏi yêu cầu phân loại công ty:

```text
AI startup
large platform company
cloud infrastructure company
answer engine company
```

Nhưng các category này chưa được biểu diễn rõ trong graph. Do đó Neo4j không có đủ evidence để trả lời.

#### 3. Relation extraction chưa đầy đủ

Một số relation quan trọng có thể chưa được LLM extract đủ hoặc chưa được normalize tốt:

```text
DEVELOPS
PRODUCES
PROVIDES
OWNS
PART_OF
ACQUIRED_BY
ASSOCIATED_WITH
WORKED_AT
FORMER_EMPLOYEE_OF
```

Nếu graph thiếu relation như `PRODUCES` giữa `Nvidia` và `GPUs`, câu hỏi về GPU hoặc AI infrastructure sẽ trả lời sai.

#### 4. Broad questions cần retrieval strategy khác

Flat RAG có lợi thế ở các câu hỏi broad vì nó lấy nhiều text chunks liên quan và LLM có thể tổng hợp trực tiếp từ văn bản. Trong khi đó GraphRAG chỉ lấy subgraph quanh seed nodes, nên dễ thiếu context khi câu hỏi yêu cầu tổng hợp toàn corpus.

---

## 10. Trường hợp GraphRAG tốt hơn Flat RAG

Dù GraphRAG chưa thắng ở multi-hop tổng thể, nó vẫn có một số case tốt hơn rõ ràng:

### Case 1: DeepMind

```text
Question: What is DeepMind related to?
Flat RAG: score = 0.50, correct = 0
GraphRAG: score = 1.00, correct = 1
```

GraphRAG tốt hơn vì graph có thể biểu diễn các quan hệ liên quan đến DeepMind một cách trực tiếp, ví dụ quan hệ với Google hoặc Alphabet.

### Case 2: Llama models

```text
Question: Which company is associated with Llama models?
Flat RAG: score = 0.50, correct = 0
GraphRAG: score = 1.00, correct = 1
```

GraphRAG tốt hơn vì relation giữa `Meta Platforms` và `Llama models` được biểu diễn rõ trong graph.

### Case 3: ChatGPT và Microsoft

```text
Question: Which AI company is linked to both ChatGPT and Microsoft?
Flat RAG: score = 1.00, correct = 1
GraphRAG: score = 1.00, correct = 1
```

Cả hai hệ thống đều đúng, nhưng đây là ví dụ tốt để minh họa đường đi multi-hop trong graph:

```text
Microsoft --INVESTED_IN--> OpenAI --DEVELOPS--> ChatGPT
```

---

## 11. Latency analysis

Kết quả latency trung bình:

```text
Single-hop:
Flat RAG: 2.091s
GraphRAG: 1.812s

Multi-hop:
Flat RAG: 2.163s
GraphRAG: 2.311s
```

Nhận xét:

- Với single-hop, GraphRAG nhanh hơn vì context lấy từ graph nhỏ gọn hơn text chunks.
- Với multi-hop, GraphRAG chậm hơn một chút vì cần seed retrieval, graph traversal, subgraph textualization và generation.
- Latency của GraphRAG vẫn ở mức chấp nhận được, nhưng độ chính xác multi-hop cần cải thiện.

---

## 12. Cost analysis

Project có hai loại chi phí:

### 12.1. Upfront cost

GraphRAG cần chi phí ban đầu để xây graph:

```text
Wikipedia corpus
→ LLM triple extraction
→ Neo4j import
→ node embedding generation
```

Chi phí này cao hơn Flat RAG ở giai đoạn indexing vì phải gọi LLM để extract triples và gọi embedding model cho node embeddings.

### 12.2. Query-time cost

Ở query-time, GraphRAG có thể tiết kiệm token hơn vì context đưa vào LLM thường là các triples ngắn gọn:

```text
OpenAI --DEVELOPS--> ChatGPT
Microsoft --INVESTED_IN--> OpenAI
```

Trong khi Flat RAG thường đưa vào nhiều đoạn text dài hơn.

Tuy nhiên, với các câu hỏi broad/global, GraphRAG hiện tại chưa lấy đủ context nên dù chi phí có thể thấp hơn, chất lượng trả lời lại kém hơn.

---

## 13. Đề xuất cải thiện

### 13.1. Thêm global graph retrieval

Với các câu hỏi có cụm:

```text
which companies in the corpus
which companies are connected to
```

hệ thống không nên chỉ chọn một seed node. Thay vào đó, cần query toàn graph theo relation hoặc topic.

Ví dụ với câu hỏi về LLM:

```cypher
MATCH (company:Entity)-[r:RELATION]->(target:Entity)
WHERE company.type = "Company"
  AND (
    toLower(target.name) CONTAINS "chatgpt"
    OR toLower(target.name) CONTAINS "claude"
    OR toLower(target.name) CONTAINS "llama"
    OR toLower(target.name) CONTAINS "mistral"
    OR toLower(target.name) CONTAINS "large language"
  )
RETURN company.name, r.type, target.name;
```

### 13.2. Thêm category triples

Cần bổ sung các triples phân loại:

```text
OpenAI --HAS_CATEGORY--> AI Startup
Anthropic --HAS_CATEGORY--> AI Startup
Mistral AI --HAS_CATEGORY--> AI Startup
Perplexity AI --HAS_CATEGORY--> AI Search Engine
Microsoft --HAS_CATEGORY--> Large Platform Company
Meta Platforms --HAS_CATEGORY--> Large Platform Company
Amazon Web Services --HAS_CATEGORY--> Cloud Platform
Nvidia --HAS_CATEGORY--> AI Infrastructure Company
```

Những triples này giúp GraphRAG trả lời tốt hơn các câu hỏi phân loại.

### 13.3. Cải thiện relation normalization

Cần map các relation tương đương về cùng một loại:

```text
CREATES → DEVELOPS
BUILDS → DEVELOPS
RELEASED → DEVELOPS
PROVIDES → OFFERS
EMPLOYED_BY → WORKED_AT
FORMERLY_WORKED_AT → FORMER_EMPLOYEE_OF
```

### 13.4. Chấm retrieval riêng với answer generation

Benchmark hiện tại chấm kết quả cuối. Để debug tốt hơn, nên tách:

```text
Retrieval metrics:
- entity recall
- relation recall
- evidence coverage
- path coverage

Answer metrics:
- answer correctness
- faithfulness
```

Điều này giúp biết GraphRAG sai vì không retrieve được đúng subgraph hay vì LLM sinh câu trả lời sai.

---

## 14. Kết luận

Project đã xây dựng được một pipeline GraphRAG hoàn chỉnh với Neo4j, bao gồm thu thập Wikipedia corpus, trích xuất triples bằng LLM, import vào Neo4j, tạo node embeddings, truy vấn graph, và benchmark với Flat RAG.

Kết quả cho thấy GraphRAG hoạt động tốt với các câu hỏi single-hop và các câu hỏi có đường đi thực thể-quan hệ rõ ràng. Ở nhóm single-hop, GraphRAG đạt correct rate 0.9, cao hơn Flat RAG là 0.8, đồng thời có latency thấp hơn.

Tuy nhiên, ở nhóm multi-hop/broad questions, GraphRAG hiện tại chỉ đạt correct rate 0.3, thấp hơn Flat RAG là 0.7. Nguyên nhân chính là do retrieval strategy hiện tại còn dựa nhiều vào seed-node traversal, trong khi nhiều câu hỏi benchmark yêu cầu global graph retrieval hoặc category-level reasoning.

Do đó, kết luận thực tế là GraphRAG không tự động tốt hơn Flat RAG trong mọi trường hợp. GraphRAG mạnh khi graph có đủ entity, relation và path cần thiết. Ngược lại, nếu graph thiếu relation, thiếu category triples, hoặc retrieval không quét đúng vùng graph, Flat RAG vẫn có thể cho kết quả tốt hơn nhờ khả năng tổng hợp từ text chunks.

Các hướng cải thiện chính gồm: thêm global graph retrieval, bổ sung category triples, cải thiện relation extraction/normalization, và chấm benchmark ở mức fact/path-level thay vì chỉ chấm text answer cuối cùng.

---

## 15. Appendix: Các file chính trong project

```text
src/00_download_wikipedia_corpus.py
src/01_create_schema.py
src/02_extract_triples_llm.py
src/03_import_to_neo4j.py
src/04_create_node_embeddings.py
src/05_graphrag_retrieval.py
src/06_flat_rag_baseline.py
src/07_run_benchmark.py
src/08_visualization_queries.cypher

data/wiki_pages.txt
data/wiki_corpus.txt
data/triples.json
data/benchmark_questions.json
data/benchmark_results.csv
```

---

## 16. Appendix: Các ảnh cần nộp kèm

Cần chụp và lưu vào thư mục `report/screenshots/`:

```text
neo4j_full_graph.png
neo4j_openai_subgraph.png
neo4j_multihop_query.png
benchmark_terminal_output.png
```
