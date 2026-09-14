# RAG patterns

- [RAG pipeline overview](#rag-pipeline-overview)
- [Retrieval strategies](#retrieval-strategies)
- [Chunking strategies](#chunking-strategies)
- [Prompt construction](#prompt-construction)
- [Reranking](#reranking)
- [Retrieval evaluation](#retrieval-evaluation)
- [AI agent memory patterns](#ai-agent-memory-patterns)

## RAG pipeline overview

Retrieval-Augmented Generation (RAG) grounds LLM responses in your data by retrieving relevant documents at query time and including them in the prompt.

```
User Query
    ↓
[Embed query]
    ↓
[Vector search in Couchbase] ──→ Top-K chunks
    ↓
[Optional: rerank / filter]
    ↓
[Build prompt: system + chunks + user query]
    ↓
[LLM generates response]
    ↓
Response to user
```

## Retrieval strategies

### Pure vector search

Embed the query, search by vector similarity only. Good for semantic questions where keywords may not match the answer.

```python
query_embedding = embed("How do I configure XDCR filtering?")

# Against a Search Vector Index (7.6+)
results = scope.search(
    "chunks-search-idx",
    SearchRequest.create(
        VectorSearch.from_vector_query(
            VectorQuery("embedding", query_embedding, num_candidates=20)
        )
    ),
    SearchOptions(limit=5, fields=["chunk_text", "parent_title", "section"]),
)
```

Against a Hyperscale or Composite index (8.0+, Enterprise Edition / Capella), the same retrieval is a SQL++ query with `ORDER BY APPROX_VECTOR_DISTANCE(...) LIMIT n` — no search API involved.

### Hybrid search (vector + keyword)

Combines vector similarity with keyword relevance. Usually better recall than either alone, because it catches both semantic and lexical matches — use it when queries may contain exact terms the embedding model does not represent well: product names, error codes, identifiers, jargon.

**Only the Search Vector Index can do this**, and only when one Search index maps both the text fields and the vector field. The Hyperscale and Composite indexes do not combine with full-text queries.

```python
# Search Service: knn + query in one request
run_fts_query(
    index_name="chunks-hybrid-idx",
    query={
        "knn": [{"field": "embedding", "vector": query_vec, "k": 40, "boost": 1.0}],
        "query": {"match": user_query, "field": "chunk_text", "boost": 0.5},
    },
    limit=10,
)
```

The Search Service unions the two result sets and ranks documents matching both higher; it is not a documented weighted-sum formula, so tune the `boost` values against your evaluation set rather than reasoning about the arithmetic. On Couchbase Server 8.0+, set the index's `scoring_model` to `bm25` — the documentation recommends BM25 over the default tf-idf specifically for hybrid search, and it ranks more consistently across index partitions.

### Pre-filtered vector search (Search Vector Index)

A `knn` clause can carry a `filter` — an ordinary Search query restricting which documents the nearest-neighbour search considers:

```python
run_fts_query(
    index_name="chunks-search-idx",
    query={
        "knn": [{
            "field": "embedding",
            "vector": query_vec,
            "k": 20,
            "filter": {"field": "tenant_id", "match": tenant_id},
        }]
    },
    limit=5,
)
```

Confirm `filter` support on your server version; it is documented for current releases but was not in the original 7.6.0 feature set.

### Filtered vector search (Composite Vector Index)

Scalar predicates narrow the candidate set before vector distances are computed. This is the right shape when a filter removes most of the corpus on every query — multi-tenant data, region-partitioned catalogues, status-gated content. Requires Couchbase Server 8.0+, Enterprise Edition or Capella, and the filtered fields must be index keys in the index definition.

```sql
-- Only search within the user's tenant and the relevant product area
SELECT c.chunk_text, c.parent_title, c.section,
       APPROX_VECTOR_DISTANCE(c.embedding, $query_vec, "COSINE") AS score
FROM `kb`.`default`.chunks AS c
WHERE c.tenant_id = $tenant_id
  AND c.product_area = $product_area
  AND c.status = "published"
ORDER BY APPROX_VECTOR_DISTANCE(c.embedding, $query_vec, "COSINE")
LIMIT 10
```

## Chunking strategies

**Fixed-size chunking.** Split every N tokens with an M-token overlap. Simple and predictable; fine for unstructured prose. Chunk size is a retrieval-quality parameter, not a constant — start somewhere in the few-hundred-token range with a modest overlap and tune it against your evaluation set.

**Semantic chunking.** Split at sentence or paragraph boundaries rather than token count. Better coherence; variable chunk sizes. Use a sentence splitter library.

**Document-structure chunking.** Split at section headings for structured documents (documentation, reports). Each chunk = one section. Include the heading in the chunk text and as a metadata field.

**Hierarchical chunking.** Index both the full document and its chunks. At query time, retrieve chunks; at generation time, optionally fetch the parent document for broader context. Useful for long documents where the LLM needs surrounding context.

## Prompt construction

```python
def build_rag_prompt(user_query: str, retrieved_chunks: list[dict]) -> list[dict]:
    context_parts = []
    for i, chunk in enumerate(retrieved_chunks, 1):
        context_parts.append(
            f"[Source {i}: {chunk['parent_title']} — {chunk['section']}]\n"
            f"{chunk['chunk_text']}"
        )

    context = "\n\n".join(context_parts)

    return [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. Answer the user's question using only "
                "the provided sources. If the sources don't contain the answer, say so. "
                "Cite sources by their [Source N] label.\n\n"
                f"Sources:\n{context}"
            )
        },
        {
            "role": "user",
            "content": user_query
        }
    ]
```

Key prompt principles:
- Tell the LLM to use only the provided sources (reduces hallucination)
- Include the source title and section so the LLM can cite them
- Instruct the LLM to say "I don't know" when sources are insufficient
- Cap the number of chunks; too many dilutes focus and pushes the useful ones away from the prompt's most-attended positions. Tune the cap rather than assuming one.

## Reranking

After vector retrieval, reranking re-scores the results with a more expensive but more accurate cross-encoder model. Improves precision when initial retrieval quality is insufficient.

```python
# Retrieve more candidates than you need, then re-score them
initial_results = vector_search(query, k=40)
reranked = reranker.rerank(
    query=user_query,
    documents=[r["chunk_text"] for r in initial_results],
    top_n=5,
)
```

Several vendors and open-source models provide cross-encoder rerankers; pick one and measure it, rather than assuming it helps.

There is also a Couchbase-side reranking mechanism that is a different thing: a Hyperscale Vector Index (8.0) can re-score its candidates against full-precision vectors instead of quantized ones, enabled per-query. That recovers recall lost to quantization inside the index; it does not model query–document relevance the way a cross-encoder does. The two are complementary.

Add application-level reranking when:

- Retrieval precision is the measured bottleneck on your evaluation set
- Queries are complex or ambiguous
- The cost of a wrong answer is high

## Retrieval evaluation

Before going to production, evaluate retrieval quality:

1. Build a test set of question + expected-source pairs — enough to be stable, and drawn from real queries where possible.
2. Run your retrieval pipeline on each question.
3. Measure recall@K: what fraction of questions have the correct source in the top K results?
4. Set the target from what the application needs, and re-measure on every change to chunking, model, index type or filters. Track the number over time; a single absolute threshold matters less than knowing which direction a change moved it.

If recall is low:
- First check: is the correct chunk actually in the index? (examine the chunk text)
- Try hybrid search if you're using pure vector
- Try smaller chunk size if chunks are too broad
- Try a better embedding model
- Add reranking as a last resort (expensive)

## AI agent memory patterns

Couchbase works well as persistent memory for AI agents. Two routes:

- **Build it yourself** on ordinary collections and vector indexes, as below. Works on any edition; you own the schema, the retention policy and the summarization.
- **Use Agent Memory**, the AI Data Plane's managed memory layer, which provides conversational, profile and semantic memory with a REST API and a Python client. It requires Capella or Couchbase Server Enterprise Edition and enterprise support. See `ai-data-plane.md`.

The hand-rolled patterns below are worth understanding either way, because they are what Agent Memory is doing on your behalf.

**Conversation history** (Agent Memory calls this conversational memory; much of the agent literature calls it episodic):
```json
{
  "id": "memory::user-123::session-456::001",
  "type": "episode",
  "user_id": "user-123",
  "session_id": "session-456",
  "role": "user",
  "content": "How do I configure XDCR?",
  "timestamp": "2026-05-28T10:00:00Z",
  "embedding": [...]   // embed for semantic recall
}
```

**Extracted facts about the user** (Agent Memory calls this profile memory) **and durable knowledge** (semantic memory):
```json
{
  "id": "memory::user-123::fact::001",
  "type": "semantic_memory",
  "user_id": "user-123",
  "content": "User is a DBA managing a 3-node Couchbase 8.0 cluster on AWS.",
  "extracted_at": "2026-05-28T10:05:00Z",
  "embedding": [...]
}
```

At the start of each agent turn, retrieve relevant memories via vector search and include them in the system prompt alongside RAG context.

Whichever route you take, decide three things explicitly: what gets written to long-term memory and by what rule, how it expires, and how much of it is injected per turn. Unbounded memory growth degrades both retrieval quality and cost, and it is the most common failure in hand-rolled agent memory.
