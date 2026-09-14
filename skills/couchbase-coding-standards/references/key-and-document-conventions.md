# Document key & field conventions

Naming standards for the two things Couchbase code produces constantly: document keys and the JSON field names inside them. Consistency here pays off in readability, debuggability, and the ability to reason about a key without opening the document.

This reference is about the *coding convention* — how the code spells keys and fields. For *what documents to model in the first place* (embed vs reference, boundaries, TTL), see the `couchbase-data-modeling` skill.

## Contents

- [Key naming](#key-naming)
- [Type discriminators](#type-discriminators)
- [Field naming](#field-naming)
- [Metadata fields](#metadata-fields)
- [Constants, not string literals](#constants-not-string-literals)
- [Checklist](#checklist)

## Key naming

A document key should be **deterministic, self-describing, and collision-free.**

- **Use a typed, delimited prefix:** `type::identifier`. `user::a1b2c3`, `order::2026-0007`, `session::<uuid>`. A reader (or a log line, or a `cbq` output) can tell what a key refers to without fetching the document.
- **Pick one delimiter and never vary it.** `::` is the common house choice. Don't mix `::`, `:`, `-`, and `/` across the codebase — grep-ability and parsing both suffer.
- **Keys are deterministic where possible.** If the identity is known (a user ID, an order number), derive the key from it so the same entity always maps to the same key — enables direct KV `get` without a lookup. Reserve random UUIDs for entities with no natural identity.
- **Composite keys encode the hierarchy left-to-right**, most significant first: `sensor::42::2026-05-21T14:00`. This makes prefix scans meaningful and keeps related keys adjacent.
- **Keep keys within limits and ASCII-safe.** The documented maximum key length is **250 bytes**; stay well under it. Avoid whitespace and characters that need escaping in SQL++ or URLs. ([Size Limits](https://docs.couchbase.com/server/current/learn/clusters-and-availability/size-limitations.html))
- **Never put mutable data in the key.** A key derived from a value that changes (email, status) breaks the moment the value changes. Key on stable identity.

Generate keys through one function, not ad-hoc string concatenation scattered across the codebase:

```python
def user_key(user_id: str) -> str:
    """Canonical document key for a user."""
    return f"user::{user_id}"
```

This gives one place to change the scheme, one place to test it, and no drift between modules.

## Type discriminators

Every document carries a field naming its type — conventionally `type` (some codebases use `docType` or `_type`; pick one and hold it). This is what SQL++ `WHERE type = "user"` and FTS type mappings key on.

- **The discriminator value matches the key prefix.** `user::…` documents have `"type": "user"`. Divergence between key prefix and type field is a bug waiting to confuse a query.
- **Set it once, centrally.** The same factory that builds the document sets its `type`; don't rely on every call site to remember.

## Field naming

- **One casing convention for JSON fields, project-wide.** `snake_case` and `camelCase` are both defensible; mixing them is not. Decide once. (Note the field casing is independent of the *language's* variable casing — your Python code may use `snake_case` variables serializing to `camelCase` JSON, or vice versa; the serialization layer bridges them consistently.)
- **Names are stable contracts.** Once documents are written with a field name, renaming it is a migration, not an edit. Choose deliberately.
- **Booleans read as predicates:** `is_active`, `has_shipped`. Timestamps say their unit/format: `created_at` (ISO-8601 string, since JSON — and therefore Couchbase — has no native date type. Store sortable ISO-8601 strings and use SQL++'s date functions, such as `STR_TO_MILLIS` / `MILLIS_TO_STR`, for arithmetic; confirm the exact function names against the [SQL++ date functions reference](https://docs.couchbase.com/server/current/n1ql/n1ql-language-reference/datefun.html) for your server version).
- **Don't abbreviate into obscurity.** `qty` is fine (universal); `usr_ac_bal` is not.

## Metadata fields

Namespace bookkeeping fields so they never collide with domain fields. A leading-underscore or dotted-namespace convention works:

```json
{
  "type": "user",
  "id": "a1b2c3",
  "name": "Alice",
  "_meta": {
    "schema_version": 3,
    "created_at": "2026-05-21T14:00:00Z",
    "updated_at": "2026-05-21T14:32:00Z",
    "source": "signup-api"
  }
}
```

- **Carry a `schema_version`** so code can migrate documents forward and reason about shape drift. This is cheap to add up front and painful to retrofit.
- **Preserve provenance where it matters** (migration source id, originating system) for traceability — invaluable when debugging bad data.

## Constants, not string literals

Type names, field names, key prefixes, and scope/collection names appear in many places. Define them once as constants; don't scatter string literals.

```python
# GOOD — one source of truth
DOC_TYPE_USER = "user"
FIELD_UPDATED_AT = "_meta.updated_at"
SCOPE_PROFILES, COLLECTION_USERS = "profiles", "users"
```

A typo'd `"usre"` in one of twelve inline literals is a silent bug; a typo in one constant fails everywhere at once and is caught immediately.

## Documented limits to design within

| Limit | Value |
|---|---|
| Maximum document key (ID) | 250 bytes |
| Maximum document value | 20 MB |
| Maximum UI-editable document | 10 MB |
| Maximum document size for indexing | 20 MB |
| Maximum buckets per cluster | 30 |
| Sub-document path length / nesting | 1024 bytes / 32 levels |

Source: [Size Limits](https://docs.couchbase.com/server/current/learn/clusters-and-availability/size-limitations.html). The 30-bucket ceiling is the practical reason to organize with **scopes and collections** (Couchbase Server 7.0+) rather than by creating more buckets — buckets are a heavyweight, quota-bearing resource; collections are not.

## Checklist

- [ ] Keys are `type::identifier` with one consistent delimiter
- [ ] Keys under 250 bytes; documents under 20 MB
- [ ] New logical partitions created as scopes/collections, not extra buckets
- [ ] Keys deterministic from stable identity where possible; no mutable data in keys
- [ ] Keys generated through a single function, not scattered concatenation
- [ ] Every document has a type discriminator; its value matches the key prefix
- [ ] One JSON field-casing convention project-wide
- [ ] Timestamps stored as sortable ISO-8601 strings
- [ ] Metadata namespaced (`_meta`); `schema_version` present
- [ ] Type names, field paths, scope/collection names defined as constants
