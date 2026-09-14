# Search synonyms (8.0+)

- [What they are](#what-they-are)
- [How the pieces fit together](#how-the-pieces-fit-together)
- [Synonym documents](#synonym-documents)
- [Wiring a synonym source into an index](#wiring-a-synonym-source-into-an-index)
- [Tools](#tools)
- [When to use synonyms](#when-to-use-synonyms)
- [Maintenance](#maintenance)
- [Limitations](#limitations)

## What they are

Synonyms let a Search query match words that mean the same thing as the term the user typed, instead of only exact matches. They were added to the Search Service in **Couchbase Server 8.0**. On 7.x there is no synonym feature — the workarounds are a custom analyzer with a token map, or expanding the query in the application.

Two forms:

**Bidirectional (equivalent) synonyms** — every term in the list is interchangeable with every other. A search for any one of them can return documents containing any of the others.

```
laptop, notebook, portable computer
```

**Unidirectional synonyms** — terms in an `input` list expand to the terms in a `synonyms` list, but not the other way round.

```
iphone  =>  apple smartphone, ios device
```

## How the pieces fit together

Unlike some search engines, Couchbase does not keep synonyms in a cluster-global registry. There are three pieces:

1. A **synonym collection** — an ordinary Couchbase collection, in a bucket and scope, holding one JSON document per synonym group.
2. A **synonym source** — a named entry in the Search index definition that points at that collection and names an analyzer.
3. A **field mapping** that selects the synonym source, so queries against that field expand.

The analyzer named on the synonym source must match the analyzer on the field. If they don't match, synonym expansion does not apply to that field.

## Synonym documents

Each document in the synonym collection describes one group. Bidirectional:

```json
{
  "synonyms": ["cheap", "inexpensive", "affordable", "budget-friendly"]
}
```

Unidirectional:

```json
{
  "input": ["iphone"],
  "synonyms": ["apple smartphone", "ios device"]
}
```

Keep the synonym collection separate from your data collections. It is regular document data, so it is backed up, replicated by XDCR, and subject to the same RBAC as anything else in that scope.

## Wiring a synonym source into an index

In the index definition, the `params.mapping` object gains a `synonym_sources` entry naming the collection and the analyzer; the field mapping then selects that source. The exact property names have changed during the 8.0 cycle — build the definition in the Search UI's Quick Editor once, export the JSON, and use that as your template rather than hand-writing it from memory.

Workflow in the Web Console Quick Editor:

1. Create the synonym collection and load the synonym documents.
2. Open the Search index, select the text field mapping.
3. Add a synonym source: give it a name, choose the collection, choose the language/analyzer.
4. Select that synonym source on the field mapping.
5. Update the index.

## Tools

**Neither MCP server has a synonym tool.** Manage synonym sets through the Search REST API (the index's synonym-source settings and the synonym collection), `couchbase-cli`, or the Web Console.

Over MCP, the equivalent is to write the synonym documents into the synonym collection with ordinary KV or SQL++ operations (`upsert_document_by_id`, `run_sql_plus_plus_query` on the data-plane server) and then apply the updated index definition with `admin_fts_index_create`, which is create-*or-update*.

## When to use synonyms

**Good use cases:**

- Product search: "TV" should match "television", "flat screen"
- Domain vocabulary: "myocardial infarction" and "heart attack"
- Abbreviations: "US" and "United States", "FAQ" and "frequently asked questions"
- Spelling variants not handled by a language analyzer
- Brand and generic equivalences

**Not the right tool for:**

- Typo correction — use `fuzziness` in match queries
- Stemming ("run" and "running") — handled by language analyzers
- Stop-word removal — handled by analyzers

## Maintenance

Because synonym groups are documents, ordinary data tooling works: upsert a document to change a group, delete it to remove one, and query the collection with SQL++ to review what's defined. Put the synonym documents in source control and apply them from your deployment pipeline — a synonym change silently alters search behaviour for every query against that field.

## Limitations

- **8.0+ only.** No synonym support on 7.x.
- **Analyzer coupling.** A field only uses a synonym source whose analyzer matches the field's analyzer.
- **Query-time expansion.** Documents indexed before a synonym was added are still findable — the query expands, not the stored index — so adding synonyms does not require a reindex. Confirm this behaviour for your version before relying on it operationally.
- **Scope.** Synonym collections live in a bucket and scope, so an index can only use sources it has been pointed at. Name them clearly if several teams share a bucket.
- **Cost.** Very large synonym groups expand a single query term into many, which costs query time. Measure before putting a large synonym set on a hot-path query.
