# Couchbase Skills — agent context

- Skills live in `skills/<skill-name>/SKILL.md`. Each skill is a focused playbook the agent loads on demand. Depth lives in `skills/<skill-name>/references/*.md`, one level deep, linked directly from `SKILL.md`.
- Ground answers in the real cluster through the Couchbase MCP server — schema, indexes, `EXPLAIN`, live statistics — rather than guessing. `mcp.json` wires the data-plane server, which covers documents, SQL++ and query diagnostics. A second server, the Couchbase Admin MCP server, covers cluster and Capella administration; it is documented by the `couchbase-admin-mcp` skill and configured separately rather than bundled here.
- Treat the cluster as **read-only** unless the user explicitly approves a write or DDL statement. Both MCP servers ship read-only by default; do not ask a user to disable that gate in order to complete a task.
- Use Couchbase terminology: Bucket → Scope → Collection, SQL++, GSI, the Search Service, Capella. "Capella Columnar" is retired — the current names are Capella Analytics (managed) and Couchbase Enterprise Analytics (self-managed).
- Version-gate anything version-specific. Couchbase Server 7.x and 8.x are both in production use, and Enterprise-only features must say so.
- Never assert a version-sensitive fact, SDK symbol or tool name from memory. Verify against docs.couchbase.com for the pinned release, or against the server's own inventory.
