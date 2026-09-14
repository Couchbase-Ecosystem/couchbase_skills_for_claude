# The Couchbase AI Data Plane

- [What it is](#what-it-is)
- [Naming and history](#naming-and-history)
- [Components](#components)
- [Agent Memory](#agent-memory)
- [Agent Catalog](#agent-catalog)
- [AI Functions](#ai-functions)
- [Model Service and Data Processing Service](#model-service-and-data-processing-service)
- [MCP Server](#mcp-server)
- [When to reach for it](#when-to-reach-for-it)
- [What to verify before you design around it](#what-to-verify-before-you-design-around-it)

## What it is

The Couchbase AI Data Plane is Couchbase's layer of agent-oriented building blocks sitting above the core data platform: managed memory for agents, a governed catalogue of tools and prompts, LLM-backed functions callable from SQL++, model hosting, and a vectorization pipeline. The documentation frames it as "the tools to create, organize, and manage your agentic applications and data in a unified environment."

It is not a separate database. It runs against Couchbase Capella or a self-managed **Couchbase Server Enterprise Edition** deployment, and it stores its state in ordinary buckets, scopes and collections.

## Naming and history

- **November 2025** — launched as **Couchbase AI Services**, alongside Couchbase Server 8.0.
- **June 2026** — relaunched and renamed to the **Couchbase AI Data Plane**.

"Couchbase AI Services" is the retired name. Older blog posts, tutorials and codelabs still use it; when you meet that name in a source, read it as the AI Data Plane's predecessor rather than a separate product.

## Components

| Component | What it does | Availability as documented |
|---|---|---|
| **Agent Catalog** | Governs and versions the tools and prompts an agent uses | GA |
| **AI Functions** | LLM-backed functions (summarize, classify, sentiment, explain) callable from SQL++ | GA |
| **MCP Server** | Model Context Protocol server exposing Couchbase data and admin operations to LLM clients | GA |
| **Agent Memory** | Persistent, unified memory layer for agentic applications | Enterprise support required |
| **Model Service** | Hosts LLMs and embedding models in Capella, or fronts external providers | Enterprise support required |
| **Data Processing Service** | Vectorizes structured and unstructured data for the rest of the platform | Enterprise support required |

"Enterprise support required" is how the current documentation gates several of these — treat it as a licensing question to settle with Couchbase, not a technical one you can work around. The split has moved between releases; check the AI Data Plane release notes for the version you are targeting.

## Agent Memory

Agent Memory gives agents a persistent memory layer so they can recall context across sessions instead of each application inventing its own session tables, summarization job and retrieval path. It stores conversation history, extracted facts, and vector embeddings of both.

Three documented memory types:

- **Conversational memory** — short-term, scoped to the current session, capturing the dialogue as it happens.
- **Profile memory** — long-term, spanning sessions, holding facts and preferences about a user.
- **Semantic memory** — long-term knowledge and facts used to ground responses.

Note these are Couchbase's terms. They do not map one-to-one onto the episodic/semantic/procedural vocabulary common in agent literature — in particular, what other frameworks call episodic memory is closest to Couchbase's conversational memory.

**How it is deployed and accessed.** Agent Memory runs as a stateless container against an existing Couchbase Capella or Couchbase Server Enterprise Edition backend. It exposes a REST API, self-documented at the service's own `/docs` and `/redoc` endpoints once deployed, and a Python client published on PyPI as **`couchbase-agent-memory`**. It requires an embedding model and an LLM to be available to the instance, for vectorization and summarization respectively.

**Do not write Agent Memory method signatures from memory.** Read them from the deployed instance's own API documentation or the current client library — the surface is new and moving. The framework-level story is that Agent Memory is designed to sit under any agent framework; the documentation names LangGraph, CrewAI, LlamaIndex and Strands Agents.

## Agent Catalog

Agent Catalog governs agentic application development by managing the tools and prompts an agent can use — registering them, versioning them, and making them discoverable to the agent at runtime, so the set of capabilities an agent has is a reviewable artifact rather than scattered code. It is documented as GA.

Its tooling is published under the `agentc` name; the implementation lives in a Couchbase Labs repository. Check the current documentation for the CLI and library entry points rather than assuming a package layout.

## AI Functions

AI Functions bring LLM-backed operations into SQL++ itself — summarization, classification, sentiment detection, and explaining patterns in data — so a query can enrich rows without the application round-tripping to a model. Documented as GA.

Separately, Couchbase Server 8.0 added a `USING AI` statement that turns a natural-language prompt into SQL++. That is a Server feature rather than an AI Data Plane component; keep the two straight when scoping what a cluster can do.

## Model Service and Data Processing Service

The **Model Service** deploys and manages LLMs and embedding models, either hosted in Capella or proxied to external providers. The **Data Processing Service** runs the vectorization pipeline: taking structured and unstructured source data and producing the embeddings the rest of the platform searches.

Together these are the managed alternative to the do-it-yourself embedding pipeline described in `data-design.md`. The tradeoff is the usual one: less pipeline code to own, in exchange for a licensing dependency and less control over chunking and model choice.

## MCP Server

The MCP Server exposes Couchbase to MCP-speaking LLM clients. It is documented as GA and is the supported path for agent tooling that needs to read and administer a cluster. The `couchbase-mcp` skill covers operating it.

## When to reach for it

Reach for the AI Data Plane when the agent-shaped concerns — cross-session memory, tool governance, managed vectorization — are the bulk of what you would otherwise build, and you have (or will have) the enterprise licensing.

Build it yourself on plain Couchbase when you need full control over chunking and embedding, when you are on Community Edition, or when your workload is retrieval rather than agency — a RAG pipeline over a document corpus does not need any of this. The patterns in `rag-patterns.md` and `data-design.md` run on an unadorned cluster.

The two are not exclusive. A common shape is Agent Memory for cross-session state, with retrieval built directly on vector indexes.

## What to verify before you design around it

This is the fastest-moving part of the product, and it has already been renamed once. Before committing a design:

1. Read the AI Data Plane release notes for the current release — component names, GA status and licensing gates have all changed between releases.
2. Confirm which components your license actually includes.
3. Pull API details from the deployed service's own generated documentation, not from tutorials, blog posts or this file.
4. Treat anything written under the "Couchbase AI Services" name as potentially superseded.
