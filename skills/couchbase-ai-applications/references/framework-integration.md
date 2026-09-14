# Framework integration

- [The official integrations](#the-official-integrations)
- [LangChain](#langchain)
- [LlamaIndex](#llamaindex)
- [Haystack](#haystack)
- [Semantic Kernel](#semantic-kernel)
- [LangGraph](#langgraph)
- [Direct SDK integration](#direct-sdk-integration-no-framework)
- [Choosing between framework and direct SDK](#choosing-between-framework-and-direct-sdk)
- [Environment-specific notes](#environment-specific-notes)

## The official integrations

Couchbase maintains first-party integrations for the major LLM application frameworks. Most live in the **Couchbase-Ecosystem** GitHub organization:

| Framework | Package | Repository |
|---|---|---|
| LangChain (Python) | `langchain-couchbase` | `Couchbase-Ecosystem/langchain-couchbase` |
| LangGraph (Python) | `langgraph-checkpointer-couchbase` | `Couchbase-Ecosystem/langgraph-checkpointer-couchbase` |
| LlamaIndex (Python) | `llama-index-vector-stores-couchbase` | maintained in the LlamaIndex integrations tree |
| Haystack (Python) | `couchbase-haystack` | `Couchbase-Ecosystem/couchbase-haystack` |
| Semantic Kernel (.NET) | Couchbase vector store connector for Microsoft Semantic Kernel | `Couchbase-Ecosystem/couchbase-semantic-kernel` |

Install from the language's package manager and let your dependency tooling resolve versions — do not pin a version from a document, including this one. Check the repository's own README for the currently supported framework versions.

## LangChain

`langchain-couchbase` exposes **two** vector store classes, matching the two ways Couchbase does vector search:

- **`CouchbaseSearchVectorStore`** — backed by a Search Vector Index in the Search Service. Supports hybrid search. Works on Couchbase Server 7.6+.
- **`CouchbaseQueryVectorStore`** — backed by the Index Service, i.e. Hyperscale or Composite vector indexes, queried through SQL++. Requires Couchbase Server 8.0+ and Enterprise Edition or Capella.

The older **`CouchbaseVectorStore`** class is **deprecated**; new code should use `CouchbaseSearchVectorStore`. If you find `CouchbaseVectorStore` in an existing codebase or in an older tutorial, that is the class to replace.

```python
from langchain_couchbase.vectorstores import CouchbaseSearchVectorStore
from couchbase.cluster import Cluster
from couchbase.auth import PasswordAuthenticator
from couchbase.options import ClusterOptions

cluster = Cluster(
    "couchbases://your-cluster.example.com",
    ClusterOptions(PasswordAuthenticator(username, password)),
)

vector_store = CouchbaseSearchVectorStore(
    cluster=cluster,
    bucket_name="my-bucket",
    scope_name="my-scope",
    collection_name="chunks",
    embedding=embeddings,          # any LangChain Embeddings implementation
    index_name="chunks-search-idx",  # the Search index carrying the vector field
)

vector_store.add_texts(
    texts=["chunk text 1", "chunk text 2"],
    metadatas=[{"source": "doc1", "section": "intro"},
               {"source": "doc1", "section": "body"}],
)

results = vector_store.similarity_search("how to configure XDCR", k=5)
retriever = vector_store.as_retriever(search_kwargs={"k": 5})
```

`CouchbaseQueryVectorStore` takes the same cluster/bucket/scope/collection/embedding arguments but a `distance_metric` instead of an `index_name`, because the index it uses is a GSI selected by the query planner rather than one named in the request. Confirm the current constructor signature against the package's API documentation before writing code against it.

### RAG chain

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

prompt = ChatPromptTemplate.from_messages([
    ("system", "Answer using only the provided context. Context:\n\n{context}"),
    ("human", "{question}"),
])

def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | prompt
    | llm            # any LangChain chat model
    | StrOutputParser()
)

answer = rag_chain.invoke("How do I configure XDCR filtering?")
```

### Caching and chat history

The package also ships `CouchbaseCache` (exact-match LLM response cache), `CouchbaseSemanticCache` (cache keyed by embedding similarity, so paraphrases hit), and `CouchbaseChatMessageHistory` (conversation persistence). All take cluster, bucket, scope and collection, and accept an optional TTL.

```python
from langchain_couchbase.cache import CouchbaseCache, CouchbaseSemanticCache
```

A semantic cache needs a similarity threshold. There is no universally right value — it depends on the embedding model and on how much paraphrase you are willing to treat as identical. Set it from measurement on your own query log, and log cache hits so you can see when it is wrong.

## LlamaIndex

```bash
pip install llama-index-vector-stores-couchbase
```

The package mirrors the LangChain split:

- **`CouchbaseSearchVectorStore`** — Search Vector Index (Search Service).
- **`CouchbaseQueryVectorStore`** — Hyperscale / Composite vector indexes via the Query and Index services.
- **`CouchbaseVectorStore`** — **deprecated**; use `CouchbaseSearchVectorStore`.

```python
from llama_index.vector_stores.couchbase import CouchbaseSearchVectorStore
from llama_index.core import VectorStoreIndex, StorageContext

vector_store = CouchbaseSearchVectorStore(
    cluster=cluster,
    bucket_name="my-bucket",
    scope_name="my-scope",
    collection_name="chunks",
    index_name="chunks-search-idx",
)

storage_context = StorageContext.from_defaults(vector_store=vector_store)
index = VectorStoreIndex.from_documents(
    documents,
    storage_context=storage_context,
    embed_model=embed_model,
)

response = index.as_query_engine(similarity_top_k=5).query(
    "How do I configure XDCR filtering?"
)
```

## Haystack

`couchbase-haystack` provides a Couchbase document store for Haystack pipelines, with the retriever components Haystack expects. Use it when the rest of the application is already a Haystack pipeline; the Couchbase-side design decisions (index type, chunking, metadata fields) are identical to the other frameworks.

## Semantic Kernel

`couchbase-semantic-kernel` is the official Couchbase **.NET** vector store connector for Microsoft Semantic Kernel. It is the path for .NET applications that want Couchbase as the vector store behind Semantic Kernel's memory abstractions. Couchbase publishes tutorials covering both Search and Index-Service vector indexes behind it.

## LangGraph

`langgraph-checkpointer-couchbase` implements LangGraph's checkpoint saver on Couchbase, so graph state persists between steps and runs. This is graph execution state, and is a different concern from Agent Memory's conversational/profile/semantic memory — see `ai-data-plane.md` if what you actually want is cross-session agent memory.

## Direct SDK integration (no framework)

For full control, or when framework overhead is not worth paying:

```python
from couchbase.cluster import Cluster
from couchbase.options import SearchOptions
from couchbase.search import SearchRequest
from couchbase.vector_search import VectorSearch, VectorQuery

def retrieve(query_vector, cluster: Cluster, bucket: str, scope: str,
             index: str, top_k: int = 5) -> list[dict]:
    scope_obj = cluster.bucket(bucket).scope(scope)
    results = scope_obj.search(
        index,
        SearchRequest.create(
            VectorSearch.from_vector_query(
                VectorQuery("embedding", query_vector, num_candidates=top_k * 4)
            )
        ),
        SearchOptions(
            limit=top_k,
            fields=["chunk_text", "parent_title", "section", "parent_id"],
        ),
    )
    return [
        {
            "text": r.fields.get("chunk_text", ""),
            "title": r.fields.get("parent_title", ""),
            "section": r.fields.get("section", ""),
            "score": r.score,
        }
        for r in results.rows()
    ]
```

SDK class and method names differ across language SDKs and have changed across SDK major versions — check the SDK documentation for your language and version rather than transcribing this.

For a Hyperscale or Composite index there is no search API involved at all: issue a SQL++ query with `ORDER BY APPROX_VECTOR_DISTANCE(...) LIMIT n` through the ordinary query API.

## Choosing between framework and direct SDK

| Situation | Recommendation |
|---|---|
| Prototyping, or a standard RAG pipeline | LangChain / LlamaIndex / Haystack — faster to build |
| Complex filtering, multi-step retrieval, custom scoring | Direct SDK — full control |
| Latency-critical hot path | Direct SDK — one less layer between you and the cluster |
| Team already invested in a framework | Stay with it |
| Want the semantic cache or chat history helpers | LangChain — they are built |
| Retrieval through a Hyperscale or Composite index | SQL++ directly, or `CouchbaseQueryVectorStore` |

## Environment-specific notes

**Capella:** use a `couchbases://` (TLS) connection string. Application access uses database credentials, which are distinct from the Capella control-plane account. Allowed CIDRs must include your application's egress addresses before a connection will succeed.

**Self-managed with TLS:** supply the cluster's CA certificate in production. Disabling certificate verification is a development-only shortcut and should never reach a deployed environment.

**Both:** vector payloads make documents large and requests heavy. Fetch only the fields you need back from a search — retrieving the embedding array itself in query results is a common and avoidable waste of bandwidth.
