---
name: couchbase-ai-applications
description: "Design and build AI-powered applications on Couchbase, including RAG pipelines, vector search architecture, embedding strategies, and AI agent data patterns. Use whenever the user asks about RAG, retrieval-augmented generation, vector search for AI, Hyperscale Vector Index (HVI), Composite Vector Index (CVI), Search Vector Index (SVI), APPROX_VECTOR_DISTANCE, embedding pipelines, semantic search, AI agent memory, Agent Memory, Agent Catalog, the Couchbase AI Data Plane, grounding LLMs with Couchbase, agentic data patterns, billion-scale or multi-vector search, or LangChain, LlamaIndex, Haystack and Semantic Kernel integration. Distinct from couchbase-fts (Search index mechanics and query syntax) — this skill covers end-to-end AI application design: data model, embedding pipeline, index type selection, retrieval strategy, and LLM framework integration. Use proactively when the user is building AI features involving language models, embeddings, or semantic retrieval."
license: Apache-2.0
---

# Couchbase AI Applications

A skill for *designing AI-powered applications* on Couchbase — RAG pipelines, vector search architecture, embedding strategies, and agent memory patterns. Covers the full stack from document design through embedding generation, index selection, retrieval, and LLM integration.

Distinct from:

- `couchbase-fts` — Search Service index mechanics and query syntax (the lower-level how); this skill is about the application-level what and why
- `couchbase-data-modeling` — general document design; this skill covers AI-specific document patterns
- `couchbase-app-integration` — SDK patterns; this skill covers AI framework integration

If the conversation is "I'm building an AI feature / RAG pipeline / agent," this is the right skill.

## When this skill applies

- "How do I build a RAG pipeline with Couchbase?"
- "Which vector index type should I use — Hyperscale, Composite, or Search?"
- "How do I store and search embeddings at scale?"
- "How do I combine vector search with keyword or metadata filters?"
- "How do I use Couchbase as memory for an AI agent?"
- "What's the difference between a Hyperscale and a Composite vector index?"
- "How do I integrate Couchbase with LangChain / LlamaIndex / Haystack / Semantic Kernel?"
- "How do I build billion-scale vector search?"
- "What is the AI Data Plane, Agent Memory, or Agent Catalog?"
- "How do I evaluate retrieval quality in my RAG pipeline?"

## Pick the right reference

| Question | Read |
|---|---|
| "Which of the three vector index types should I use?" | `references/vector-index-types.md` |
| "How do I design my documents and data pipeline for AI?" | `references/data-design.md` |
| "How do I build a RAG pipeline end to end?" | `references/rag-patterns.md` |
| "LangChain / LlamaIndex / Haystack / Semantic Kernel integration" | `references/framework-integration.md` |
| "What is the AI Data Plane — Agent Memory, Agent Catalog, AI Functions?" | `references/ai-data-plane.md` |

## Three core principles

**Principle 1 — Choose the index type before writing any code.**
From Couchbase Server 8.0 there are three vector index types owned by two different services, with different query languages and different filtering behaviour. Choosing wrong means an index rebuild and often an application rewrite, because the query interface differs. Read `references/vector-index-types.md` before picking.

**Principle 2 — Embedding generation is a pipeline concern, not a storage concern.**
Couchbase stores and searches vectors. Generating them is either your application's job or, on licensed AI Data Plane deployments, the Data Processing Service's job. Either way the embedding model must be identical at index time and at query time — a model or dimension mismatch produces silently wrong results, not errors. Record the model name on every document so you can find stale vectors later.

**Principle 3 — RAG quality is a retrieval problem, not a generation problem.**
Most RAG failures are retrieval failures: wrong chunks returned, too few chunks, no metadata filtering, stale chunks. Invest in retrieval quality (chunk strategy, hybrid search, metadata filters, reranking) before tuning the LLM prompt.

## The three vector index types at a glance

| | Search Vector Index | Composite Vector Index | Hyperscale Vector Index |
|---|---|---|---|
| Service | Search Service | Index Service (GSI) | Index Service (GSI) |
| Introduced | 7.6 | 8.0 | 8.0 |
| Edition | CE, EE, Capella | **EE / Capella only** | **EE / Capella only** |
| Created with | Search index definition (`vector` field) | `CREATE INDEX ... (v VECTOR, scalars)` | `CREATE VECTOR INDEX` |
| Queried with | Search request with `knn` | SQL++ `APPROX_VECTOR_DISTANCE()` | SQL++ `APPROX_VECTOR_DISTANCE()` |
| Hybrid with full-text / geo | **Yes — the only one** | No | No |
| Documented scale | tens of millions, to roughly 100M docs | tens of millions to a billion | tens of millions to billions |

Full decision guidance, including filtering behaviour and quantization, is in `references/vector-index-types.md`.

## Quick tool map

These tools live on **two** servers: index creation is administration (`couchbase-admin-mcp/references/tool-families.md`) and retrieval is data plane (`couchbase-mcp/references/tool-index.md`). Verify against your deployed servers before scripting.

| Task | Tool |
|---|---|
| Create a Composite Vector Index (8.0+, EE/Capella) | `admin_vector_index_create_composite` — admin server |
| Create a Hyperscale Vector Index (8.0+, EE/Capella) | `admin_vector_index_create_hyperscale` — admin server |
| List / drop those indexes (they are GSI indexes) | `admin_index_list`, `admin_index_drop` — admin server |
| Create a Search index with a `vector` field (7.6+) | `admin_fts_index_create` — admin server |
| Run a kNN or hybrid text + vector search | `run_fts_query` with `knn` (and optionally `query`) — data-plane server |
| Run SQL++ vector retrieval | `run_sql_plus_plus_query` with `APPROX_VECTOR_DISTANCE()` — data-plane server |

## Version notes

Gate every recommendation on the target version and edition.

- **Pre-7.6:** no server-side vector search. Semantic retrieval has to happen outside Couchbase.
- **7.6+:** Search Vector Index — a `vector` field inside a Search index, supporting kNN, pre-filtered kNN, and hybrid text + vector in a single query. Linux from 7.6.0, macOS from 7.6.2, **not supported on Windows**. Up to **4096** dimensions from 7.6.2. `cosine` similarity and the `memory-efficient` optimization mode arrive in **7.6.4**. Available in Community Edition.
- **8.0 (GA October 2025):** adds the **Hyperscale Vector Index** and **Composite Vector Index** in the Index Service, both **Enterprise Edition / Capella only**, both queried through SQL++ `APPROX_VECTOR_DISTANCE()`. The Search Service adds synonyms and the `bm25` scoring model, which the documentation recommends for hybrid search.
- **AI Data Plane:** Couchbase's agent-focused layer, launched November 2025 as Couchbase AI Services and **relaunched as the Couchbase AI Data Plane in June 2026**. It runs against Capella or self-managed Couchbase Server Enterprise Edition. Components include **Agent Catalog**, **AI Functions**, the **MCP Server**, **Agent Memory**, the **Model Service**, and the **Data Processing Service**; several of these are gated behind enterprise support. See `references/ai-data-plane.md` for what each one does and how it is accessed — and check the AI Data Plane release notes before committing, because this is the fastest-moving part of the product.
- **Capella:** all three index types are available on Capella. Hyperscale and Composite require the Index Service; check current Capella documentation for service availability and sizing limits.

## Related skills

- `couchbase-fts` — Search index mechanics, analyzers, query syntax, Search Vector Index configuration
- `couchbase-data-modeling` — document shape decisions that affect chunking and embedding storage
- `couchbase-sizing` — vector index memory budgeting
- `couchbase-sqlpp-tuning` — SQL++ queries using `APPROX_VECTOR_DISTANCE()` with Hyperscale and Composite indexes
- `couchbase-mcp` — the data-plane tools for querying these indexes (`run_fts_query`, `run_sql_plus_plus_query`)
- `couchbase-admin-mcp` — the administration tools that create them (`admin_vector_index_*`, `admin_fts_index_*`)
- `couchbase-upgrade` — reaching 8.0, which is what makes the Hyperscale and Composite vector indexes available
