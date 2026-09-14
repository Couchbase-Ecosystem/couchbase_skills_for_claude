---
name: couchbase-fts
description: "Design, build, and tune Couchbase Search Service indexes (historically called Full Text Search / FTS) and vector indexes. Use whenever the user asks about Search indexes, the Search Service, text search, full-text search, fuzzy search, phrase search, wildcard search, regex search, geo search, geo-distance, geo-bounding-box, GeoJSON shape search, IP/CIDR range search, facets, scoring, BM25, boosting, analyzers, tokenizers, custom analyzers, language analyzers, type mappings, dynamic mappings, child mappings, Search index design, synonyms (8.0+), vector search, kNN search, Search Vector Index, embedding search, hybrid search (text + vector), run_fts_query, admin_fts_*, Bleve, or 'how do I search text in Couchbase.' Distinct from couchbase-sqlpp-tuning (SQL++ and GSI index design) and couchbase-mcp (operating the tools). Use proactively when the user has a search use case — text relevance, semantic similarity, geo-proximity, or faceted navigation."
license: Apache-2.0
---

# Couchbase Search Service & Vector Search

A skill for *designing and operating* Couchbase Search indexes and vector indexes.

**Naming note.** The current documented product name is **the Search Service**. "Full Text Search" and "FTS" are the older names; they survive in tool names (`run_fts_query`, `admin_fts_*`), in REST paths, and in the `fulltext-index` index type, so both spellings appear below. Prefer "Search Service" in prose.

Distinct from:

- `couchbase-sqlpp-tuning` — SQL++ / GSI index design (not the Search Service)
- `couchbase-data-modeling` — document shape decisions that affect what the Search Service can index
- `couchbase-mcp` — the data-plane server that runs Search queries and reads index definitions: `run_fts_query`, `list_fts_indexes`, `get_fts_index_definition`
- `couchbase-admin-mcp` — the administration server that owns Search index *lifecycle* (`admin_fts_index_*`) and the Index-Service vector index tools (`admin_vector_index_create_hyperscale`, `admin_vector_index_create_composite`). The data-plane server has no cluster-administration tools

If the conversation is "I need to search text / find similar documents / search by location," this is the right skill.

## When this skill applies

- "How do I do full-text search in Couchbase?"
- "How do I build a Search index?"
- "Why isn't my Search query matching what I expect?"
- "How do I add fuzzy / wildcard / phrase search?"
- "How do I search by geo-distance or a GeoJSON shape?"
- "How do I implement vector / semantic / kNN search?"
- "How do I combine text search with vector search (hybrid)?"
- "What analyzer should I use for [language]?"
- "How do I boost certain fields, or switch to BM25 scoring?"
- "What are Search synonyms and when should I use them?"
- "How do I size Search / vector index memory?"

## Pick the right reference

| Question | Read |
|---|---|
| "How do I design a Search index — mappings, analyzers, type fields, partitions, replicas?" | `references/index-design.md` |
| "How do I write Search queries — match, phrase, fuzzy, wildcard, conjunction, geo, CIDR?" | `references/query-types.md` |
| "Analyzers, tokenizers, token filters — how do they work, which to pick?" | `references/analyzers.md` |
| "Vector search — kNN, pre-filtering, hybrid search, index design for embeddings?" | `references/vector-search.md` |
| "Synonyms (8.0+) — what they are, how to create, when to use?" | `references/synonyms.md` |
| "Search is slow / results are wrong / index not updating — how to debug?" | `references/troubleshooting.md` |

## Three core principles

**Principle 1 — The index definition determines everything.**
The Search Service doesn't infer what to index from the document. If a field isn't mapped (or dynamic mapping is off), it is ignored. Get the index definition right before debugging queries. The most common failure mode is "the field isn't indexed."

**Principle 2 — Analyzer choice is irreversible at query time.**
The analyzer applied at index time must be consistent with what you apply at query time. If you index with the `en` (English stemming) analyzer and query with `standard`, "running" and "run" won't match. Pick the analyzer once, document it, use it consistently.

**Principle 3 — The Search Service and GSI solve different problems.**
The Search Service is for relevance-ranked text search, fuzzy matching, linguistic analysis, geo search, and vector kNN. GSI is for exact-match, range, and structured queries with SQL++ syntax. They're complementary — use both. A common pattern: GSI for filtering (`WHERE status = 'active'`), Search for text relevance (`SEARCH(description, "fast delivery")`).

## The five-question Search index design pass

Before building an index:

1. **What fields need to be searchable?** List them explicitly. Enabling dynamic mapping on large documents indexes everything, including fields you'll never search — wastes RAM and slows indexing.
2. **What languages?** Use language-specific analyzers (`en`, `de`, `fr`, etc.) for stemming and stop-word handling. Multi-language content needs multiple type mappings or a custom analyzer.
3. **Do you need relevance ranking?** If you just need "does this doc contain X" (filter), a simple match query is fine. If you need "most relevant first," think about field weighting, boost values, and whether to use the `bm25` scoring model (8.0+) instead of the default `tf-idf`.
4. **Geo, facets, or highlighting?** These require specific field types (`geopoint` or `geoshape` for geo, `include_term_vectors: true` for highlighting, `docvalues: true` for facets and sorting). Plan for them in the index definition, not after the fact.
5. **Vector search?** Decide between a Search Vector Index (vector field inside a Search index — the only option that does hybrid text + vector in one query) and the Index-Service vector indexes (Hyperscale / Composite, 8.0+, Enterprise Edition and Capella only). See `references/vector-search.md` and `couchbase-ai-applications`.

## Quick tool map

Search runs across **two** MCP servers: querying lives on the data-plane server (`couchbase-mcp/references/tool-index.md`) and index administration on the admin server (`couchbase-admin-mcp/references/tool-families.md`). Verify against your deployed servers before scripting.

| Task | Tool | Server |
|---|---|---|
| Run a search query (text, geo, kNN, hybrid) | `run_fts_query` | `couchbase-mcp` |
| List Search indexes | `list_fts_indexes` | `couchbase-mcp` |
| Get a Search index definition | `get_fts_index_definition` | `couchbase-mcp` |
| List / get an index from the admin side | `admin_fts_index_list`, `admin_fts_index_get` | `couchbase-admin-mcp` |
| Create or update a Search index | `admin_fts_index_create` (create-*or-update*: applied to an existing name it replaces the definition and the index rebuilds) | `couchbase-admin-mcp` |
| Delete a Search index | `admin_fts_index_delete` | `couchbase-admin-mcp` |
| Index health (doc count, ingest backlog) | `admin_fts_index_doc_count`, `admin_fts_index_stats` | `couchbase-admin-mcp` |
| Pause / resume index ingestion | `admin_fts_index_ingest_pause`, `admin_fts_index_ingest_resume` | `couchbase-admin-mcp` |
| Search Service settings | `admin_fts_settings_get` | `couchbase-admin-mcp` |
| Create Index-Service vector indexes (8.0+) | `admin_vector_index_create_hyperscale`, `admin_vector_index_create_composite` | `couchbase-admin-mcp` |
| List / drop Index-Service vector indexes | `admin_index_list`, `admin_index_drop` (they are GSI indexes) | `couchbase-admin-mcp` |
| Search Service metrics | `admin_stats_single` / `admin_stats_multi` with Search metric names | `couchbase-admin-mcp` |

**Not on either MCP server.** Search index **aliases** and **synonym sets** have no tool on either server — manage them through the Search REST API (`/api/index/...`), `couchbase-cli`, or the Web Console.

## Version notes

Gate any advice you give on the cluster version. Do not assume 8.0.

- **7.0+:** scoped (bucket/scope/collection) Search indexes and the `scope.collection.type_field` doc_config mode.
- **7.6+:** Search Vector Index — a `vector` field type inside a Search index, enabling kNN and hybrid text + vector search. Supported on Linux from 7.6.0 and macOS from 7.6.2; **not supported on Windows**.
- **7.6.2+:** vector fields accept up to **4096** dimensions.
- **7.6.4+:** `cosine` similarity and the `memory-efficient` value for `vector_index_optimized_for` are added (before that: `dot_product` and `l2_norm`; `recall` and `latency`).
- **8.0+:** synonym sources and synonym collections; the `bm25` scoring model alongside the default `tf-idf`; custom document filters for choosing which documents get indexed; and two Index-Service vector index types — **Hyperscale Vector Index** and **Composite Vector Index** — created with SQL++ and queried with `APPROX_VECTOR_DISTANCE()`, not through the Search Service.
- **Edition gating:** the Search Service and the Search Vector Index are available in Community Edition. **Search index replicas, Hyperscale Vector Indexes, and Composite Vector Indexes are Enterprise Edition / Capella only.**
- **Capella:** the Search Service is available on Capella clusters; Hyperscale and Composite vector indexes require the Index Service and an appropriately sized cluster. Check current Capella documentation for service and sizing limits before committing to a design.

## Related skills

- `couchbase-ai-applications` — choosing between Search, Hyperscale, and Composite vector indexes for AI workloads
- `couchbase-data-modeling` — document field types and structure that the Search Service will index
- `couchbase-sizing` — Search and vector index memory budgeting
- `couchbase-mcp` — the data-plane tools for running Search queries and reading index definitions
- `couchbase-admin-mcp` — the `admin_fts_*` index lifecycle, stats and ingest-control tools
- `couchbase-sqlpp-tuning` — complementary GSI index design for the SQL++ side of hybrid queries
