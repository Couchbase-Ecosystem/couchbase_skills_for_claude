# Data design for AI applications

- [Document structure patterns](#document-structure-patterns)
- [Embedding field naming conventions](#embedding-field-naming-conventions)
- [Metadata fields for filtered vector search](#metadata-fields-for-filtered-vector-search)
- [Embedding pipeline architecture](#embedding-pipeline-architecture)
- [Stale embedding detection](#stale-embedding-detection)

## Document structure patterns

### Pattern 1: Embedded embedding (most common)

Store the embedding vector directly in the source document:

```json
{
  "id": "product::p-001",
  "type": "product",
  "title": "Wireless Noise-Cancelling Headphones",
  "description": "Premium over-ear headphones with 30-hour battery life...",
  "category": "electronics",
  "brand": "SoundPro",
  "price": 249.99,
  "status": "active",
  "embedding": [0.023, -0.147, 0.891],
  "embedding_model": "<model identifier>",
  "embedding_dimension": 1536,
  "embedding_updated_at": "2026-01-15T10:30:00Z"
}
```

Good for: product search, document retrieval, entity search where documents are self-contained.

### Pattern 2: Chunked documents (RAG)

For long documents (articles, PDFs, knowledge base entries), split into chunks. Store the parent document and child chunks separately:

```json
// Parent document
{
  "id": "doc::kb-001",
  "type": "knowledge_article",
  "title": "Configuring Couchbase XDCR",
  "source_url": "https://docs.example.com/xdcr",
  "last_updated": "2026-03-10"
}

// Child chunk documents
{
  "id": "chunk::kb-001::001",
  "type": "chunk",
  "parent_id": "doc::kb-001",
  "parent_title": "Configuring Couchbase XDCR",
  "chunk_index": 1,
  "chunk_text": "XDCR (Cross-Datacenter Replication) enables...",
  "embedding": [0.012, 0.847, -0.233],
  "embedding_model": "<model identifier>",
  "section": "Introduction"
}
```

**Chunk design decisions:**
- **Chunk size:** smaller chunks give more precise retrieval; larger chunks give more context per result. There is no universally correct size — it depends on the content and the questions. Start in the few-hundred-token range and tune against a retrieval evaluation set.
- **Overlap:** a modest overlap between adjacent chunks avoids splitting a fact across a boundary. Tune it alongside chunk size; too much overlap inflates the index and returns near-duplicate results.
- **Parent reference:** always store `parent_id` and key parent metadata (title, URL, date) in the chunk. At query time you'll display these to the user without a separate lookup.
- **Section/heading:** store the document section heading in each chunk. It helps the LLM understand context and improves retrieval quality for structured content.

### Pattern 3: Multi-vector documents

Store multiple embeddings per document for different fields or modalities:

```json
{
  "id": "product::p-001",
  "title": "Wireless Headphones",
  "description": "...",
  "title_embedding": [0.023],
  "desc_embedding": [0.891],
  "combined_embedding": [0.456],
  "image_embedding": [0.334]
}
```

Use multi-vector when different query types need different context (title search vs description search). Each embedding field needs its own vector index definition. Note that a Hyperscale or Composite index carries exactly **one** vector column, so N embedding fields means N indexes; a Search index can map several vector fields, but each `knn` clause targets one field.

## Embedding field naming conventions

Be consistent. Recommended convention:

- Single embedding: `embedding`
- Multiple embeddings: `<field>_embedding` (e.g. `title_embedding`, `body_embedding`)
- Always store `embedding_model` (a string identifying the model that produced the vector) alongside the vector, and the dimension
- Store `embedding_updated_at` (ISO timestamp) to track staleness

When you update your embedding model, `embedding_model` lets you identify which documents need re-embedding without scanning all documents.

## Metadata fields for filtered vector search

All three vector index types can narrow a search by metadata, but by different mechanisms — design the fields deliberately either way:

- **Composite Vector Index** (8.0+, EE/Capella): the filtered fields are index keys in the index definition, and the predicate narrows the candidate set before vector distances are computed. Strongest filtering.
- **Hyperscale Vector Index** (8.0+, EE/Capella): scalars are attached with the `INCLUDE` clause. They are stored with the vectors but not indexed themselves, so they cut down vector comparisons without accelerating the predicate.
- **Search Vector Index** (7.6+, all editions): a `filter` inside the `knn` clause, expressed as an ordinary Search query over fields mapped in the same index.

In every case the fields must be reachable and declared in the index definition. A predicate on a field the index does not carry cannot narrow the scan.

```json
{
  "embedding": [...],
  "category": "electronics",          // filter: WHERE category = "electronics"
  "region": "us-east",               // filter: WHERE region = $region
  "status": "active",                // filter: WHERE status = "active"
  "created_at": "2026-01-15",        // filter: WHERE created_at > "2026-01-01"
  "tenant_id": "acme-corp"           // filter: WHERE tenant_id = $tenant_id
}
```

Low-cardinality fields (status, category, region) are the natural pre-filters. Very high-cardinality fields (document_id) are usually better as post-filters. Tenant identifiers are the exception worth calling out: cardinality is high, but a tenant predicate typically eliminates almost the entire corpus, which is exactly the case a Composite Vector Index is built for.

## Embedding pipeline architecture

```
Documents → [Chunking] → [Embedding Model] → [Write to Couchbase]
                                ↑
                         (same model used at query time)
```

**At write time:**
1. Create or update the document in Couchbase (without embedding first)
2. Generate the embedding from the relevant text fields
3. Update the document with the embedding via subdoc `mutate_in` (avoids rewriting the full document)

```python
# Efficient: update only the embedding fields
coll.mutate_in(doc_id, [
    SD.upsert("embedding", embedding_vector),
    SD.upsert("embedding_model", model_id),
    SD.upsert("embedding_updated_at", now_iso()),
])
```

**Batch embedding pipeline:**
For bulk indexing, batch requests to your embedding provider up to whatever its current batch limit is — read that from the provider's own documentation, since it varies by provider and changes. Write batches to Couchbase in parallel and track progress with an `embedding_status` field (`pending`, `complete`, `failed`) so a failed run is resumable.

**Managed alternative:** on licensed AI Data Plane deployments, the Data Processing Service performs vectorization of structured and unstructured data, and the Model Service hosts the embedding model. That removes the pipeline code above at the cost of a licensing dependency and less control over chunking. Everything else on this page still applies.

**At query time:**
1. Embed the user's query with the same model
2. Run the vector search
3. Pass retrieved chunks + user query to the LLM

## Stale embedding detection

Embeddings become stale when the source text changes. Track this with a content hash or update timestamp:

```json
{
  "description": "...",
  "description_hash": "sha256:abc123",
  "embedding": [0.023, -0.147, 0.891],
  "embedding_model": "<model identifier>"
}
```

When `description` changes, compare the new hash to `description_hash`. If different, re-embed. Use an Eventing function or CDC pipeline to trigger re-embedding automatically.

The same field is what makes a model migration tractable. When you change embedding models, every document must be re-embedded and every vector index rebuilt — there is no in-place dimension change. Having `embedding_model` on each document lets you migrate incrementally and see exactly how far the backfill has got.
