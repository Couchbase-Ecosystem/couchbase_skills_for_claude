# Contributing

Open an issue before writing code for any new skill or significant change — a GitHub issue for external contributors, or a JIRA ticket for Couchbase internal contributors. Then branch, change, validate, and open a pull request.

```bash
git checkout -b feature/your-change
# ... make your change ...
./tools/validate-skills.sh
python3 tools/run-evals.py --dry-run
python3 tools/validate-manifests.py
python3 tools/validate-links.py
```

All four must pass. CI runs the same four checks on every pull request, plus a self-test of the eval grader.

---

## Skill layout

```
skills/<skill-name>/
  SKILL.md                 # required — the playbook
  references/*.md          # optional — deep dives, loaded on demand
```

Every skill needs an entry in `skills/OWNERS.yaml` and an eval suite at `testing/<skill-name>/evals/evals.json`.

---

## Frontmatter

```yaml
---
name: couchbase-<skill-name>   # must match the directory name exactly
description: >-                 # what it does AND when to invoke it
  One paragraph. Leads with the key use case, lists the trigger terms a user
  would actually say, and states which sibling skill handles the near misses.
license: Apache-2.0
---
```

Only six keys are valid, and the validator rejects anything else: `name`, `description`, `license`, `allowed-tools`, `compatibility`, `metadata`. A `version` belongs under `metadata`, not at the top level.

**`name`** — lowercase, digits and single hyphens; 64 characters maximum; no leading, trailing or doubled hyphen; cannot contain `claude` or `anthropic`; must match the containing directory.

**`description`** — 1024 characters maximum, no angle brackets, third person. Put the key use case in the first sentence so it survives truncation in hosts that shorten skill listings. Be explicit about scope in both directions: what triggers this skill, and which sibling takes the requests that look similar but are not this. Err toward being pushy about the contexts where the skill applies, including ones where the user does not name the product.

**`license`** — always `Apache-2.0` in this repository.

---

## Body

Aim for a playbook, not an essay:

```markdown
# <Skill Title>

One-paragraph orientation.

## When this skill applies
- "A trigger phrase a user would type"

## Step 0 — Confirm the connection (pre-flight)

## Pick the right reference
| Question | Read |
|---|---|
| "..." | `references/topic.md` |

## Workflow / Core principles

## Scope
What this skill does not cover, and which sibling to hand off to.

## Related skills

## References
```

`SKILL.md` stays under 500 lines — the validator warns above 500 and fails above 800. Push depth into `references/`.

---

## Reference files

- **Self-contained.** Each must be readable without `SKILL.md` or any sibling.
- **One level deep.** Every reference links directly from `SKILL.md` and appears in its routing table. A reference may point at a sibling reference, but never be reachable only through one — agents may read a transitively-reached file only in part.
- **80–400 lines**, with a table of contents at the top of anything over 100 lines. Use a bullet list of links — `- [Heading](#heading)` — rather than an inline run of links, so the two styles currently in the repository converge on one.
- **No frontmatter.** Reference files start at their `# H1`.
- **Forward slashes** in every path, always, regardless of the author's operating system.

Do not create an empty `references/` directory. A single-file skill is valid when the topic does not need splitting.

---

## Conventions

**MCP-grounded.** Skills operate a live cluster through the Couchbase MCP servers. Prefer real evidence — `get_schema_for_collection`, `list_indexes`, `explain_sql_plus_plus_query`, live statistics — over generic advice.

**Read-only by default.** Both MCP servers ship read-only. Treat the cluster as read-only and require explicit user approval before any write or DDL. Never write a skill that instructs a user to disable a safety gate in order to finish a task.

**Language-agnostic where possible.** Rely on SQL++ and MCP tools rather than per-SDK code. Where SDK code is genuinely needed, see the SDK rule below.

**Couchbase-native terminology.** Bucket → Scope → Collection. SQL++, not N1QL (the legacy alias may appear once, where it aids recognition). GSI. The Search Service. Capella. "Capella Columnar" is retired: the managed service is **Capella Analytics** and the self-managed product is **Couchbase Enterprise Analytics**, and they are different deployments, not synonyms.

**Version-gate, do not delete.** Couchbase Server 7.x and 8.x are both in production use. Mark version- and edition-specific content explicitly — "Available in 7.6+", "8.0+ only", "EE only — not available in Community Edition" — rather than removing the older guidance.

---

## The evidence rule

This is the rule that matters most, because these skills are read as authoritative.

**Never assert a version-sensitive fact, a numeric limit, an SDK symbol, or an MCP tool name from memory.** Verify it against docs.couchbase.com for the relevant release, the official Couchbase repository, or the MCP server's own inventory. Cite the page in your pull request.

If you cannot verify something:

- Replace the specific with a qualitative statement, or
- Remove it, or
- Keep it and mark it explicitly as unverified.

Never invent a number to fill a gap. Fabricated thresholds, latency figures, throughput numbers and performance multipliers are the failure mode this repository has had to correct most often, and they are worse than silence because they read as authoritative.

**SDK symbols** get the same treatment: check the method, class and exception names against that SDK's current documentation before writing them, and keep the "verify against your pinned SDK version" caveat in place.

---

## What not to put in a skill

- Pricing of any kind — it changes, and it is Finance-owned
- Version pins for third-party tools (Prometheus, Grafana, Filebeat) — they age badly; describe the integration instead
- Cloud provider recommendations
- Exact API response payloads that shift between patch releases
- Benchmark figures without a dated, named source
- Personal or third-party branding — this repository is Apache-2.0, Couchbase, Inc.

---

## Eval cases

Every skill has a suite at `testing/<skill-name>/evals/evals.json`. When you change a skill, add a case. When you **correct** a skill, add a regression case: put the right answer in `expect` and the wrong one you just removed in `reject`. Those pins are how a correction survives the next contributor.

One trap to avoid: a `reject` string must be one that only a *wrong* answer produces. If the skill deliberately names the wrong value in order to warn against it — "do not grant `cluster_admin`" — then a correct answer contains that substring and the case can never pass. Negating it does not help, for the same reason. Put the discrimination in `expect` instead.

This rule is mechanically enforced: `python3 tools/run-evals.py --dry-run` builds each skill's loaded corpus and **fails** when a `reject` string appears in it, naming the case and the offending string. The check is offline and runs in CI, so a self-defeating `reject` cannot be reintroduced silently. For near-miss cases, assert routing in `expect` — the sibling skill's name and the handoff wording from the skill's `## Related skills` section — and keep `expect_skill` as the machine-readable routing claim.

See [`testing/README.md`](testing/README.md) for the schema.

---

## Commit style

```
Add couchbase-admin-mcp skill: cluster and Capella administration, risk tiers, runbooks
Fix couchbase-upgrade: remove non-existent direct 7.0/7.1 to 8.0 upgrade paths
Update couchbase-fts: correct vector index taxonomy and gate SVI at 7.6+
```
