# Couchbase Skills — extension context

- This extension bundles Couchbase skills and the configuration that launches the Couchbase MCP server (fetched at runtime by `uvx`). Skills live in `skills/<skill-name>/SKILL.md` and are loaded on demand; deep-dive material sits in each skill's `references/` directory.
- Ground answers in the live cluster through the MCP server — schema, indexes, `EXPLAIN`, statistics — rather than guessing.
- Treat the cluster as **read-only** unless the user explicitly approves a write or DDL statement. The server ships read-only by default.
- Use Couchbase terminology: Bucket → Scope → Collection, SQL++, GSI, the Search Service, Capella. "Capella Columnar" is retired — use Capella Analytics (managed) or Couchbase Enterprise Analytics (self-managed).
- Version-gate anything version-specific. Couchbase Server 7.x and 8.x are both in production use.
