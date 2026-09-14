# Open findings

Questions raised during the content verification pass of 2026-09-14 that need a ruling from Couchbase engineering, product or legal.

Three kinds of entry: **decisions** that need an owner; **unverifiable claims**, where the documentation is silent or self-contradictory and the skills therefore say nothing; and **uncorroborated claims**, where a skill does state something but the statement rests on inference rather than a citable page. The third kind is called out explicitly rather than hidden, because a reader who trusts this file needs to know which is which.

---

## Decisions

### D1 — Homing of the Analytics MCP skills

The eight `cb-analytics-*` skills document an Analytics MCP server that has not yet been migrated into a Couchbase-owned repository. At the time of the donation that migration was understood to be pending, so the skills were left pointing where they point rather than being retargeted at a server that does not yet exist under a Couchbase namespace.

Consequence while that stands: a Couchbase-owned repository ships eight skills whose tool names, environment variables, rate-limit categories and response envelope belong to a third-party server and cannot be verified against any Couchbase source, yet will read to a user as Couchbase-supported. No GitHub URL appears inside any of the eight `SKILL.md` files, so the coupling is implicit rather than advertised.

**Needs:** a decision on whether to migrate that server, retarget the skills at a Couchbase-owned Analytics MCP server, or withdraw the eight skills until one exists.

### D2 — Relationship between the three Analytics offerings

Three things carry the name: the in-cluster **Analytics Service** (`cbas`, still shipping in Couchbase Server 8.0 and still valid in the Kubernetes Operator), **Capella Analytics** (managed, renamed from Capella Columnar in August 2025), and **Couchbase Enterprise Analytics** (self-managed, 2.0 GA August 2025, 2.2 current). The skills now state which is which and refuse to conflate them, but the *relationship* — whether the in-cluster service has a deprecation path toward the other two — is a product answer nobody has published.

### D3 — `couchbase-columnar` directory name

The skill directory is still `couchbase-columnar`, because `name` must match the directory and renaming breaks anyone who installed it. Its content now uses current naming throughout. Rename at a major version, or leave it.

### D3a — `couchbase-fts` directory name

Same situation as D3 and it should be decided at the same time. "FTS" is the older name for what the documentation now calls the Search Service; the skill's content uses the current name and flags the legacy one, but the directory — and therefore the `name` frontmatter — is still `couchbase-fts`. Renaming breaks existing installs, so it waits for a major version alongside `couchbase-columnar`.

### D4 — Skill ownership (interim assignment in place)

`skills/OWNERS.yaml` names an interim DRI on all 31 skills, carried over from the donation, with a 90-day review cadence. That makes the cadence enforceable from day one, but it is a placeholder for a real ownership split: each skill should move to the team that owns the surface it documents — mobile to the mobile team, the Operator skill to the Kubernetes team, the MCP skills to whoever maintains those servers.

**Needs:** a pass assigning real DRIs, ideally before the collection is advertised.

### D5 — SECURITY.md and CODE_OF_CONDUCT.md need ratifying

Both files now exist, but neither is an org-ratified template — no Couchbase standard for either was found across the `couchbase`, `couchbaselabs` and `Couchbase-Ecosystem` organizations.

`CODE_OF_CONDUCT.md` is Contributor Covenant 2.1, taken from Couchbase's own copy in `Couchbase-Ecosystem/cbl-reactnative`, with the enforcement contact filled in as `agent-plugins@couchbase.com` — the owner address `Couchbase-Ecosystem/agent-skills` publishes in its marketplace manifest. Note that the copy it was taken from still ships with `[INSERT CONTACT METHOD]` unfilled, which is worth fixing at the source.

`SECURITY.md` is written specifically for a documentation repository: it scopes a security issue to guidance that would weaken a cluster, credentials committed into examples, unsafe packaging defaults, and defects in the validators, and it routes reports to GitHub private advisories with that same address as the fallback.

**Needs:** Legal or the org owners to confirm both the enforcement contact and the vulnerability-reporting route, and to swap in official text if one exists.

### D6 — Contributor licence agreement

Couchbase's Gerrit-based CLA applies to SDK and server repositories. Newer GitHub-native repositories, including `couchbase/mcp-server-couchbase`, use plain pull requests with no CLA mention. `CONTRIBUTING.md` here assumes the GitHub-native model. Confirm with Legal before the repository takes outside contributions.

---

## Unverifiable claims

### Server and storage

- **Default database fragmentation threshold.** Three documentation pages disagree or are silent: the CLI gives a range only, a REST example shows 50%, the Operator says "cluster level value". The previously asserted 30% could not be substantiated.
- **Default Magma fragmentation percentage.** Web Console shows 50%; the Operator gives a 10–100 range with no default; REST does not document the parameter.
- **Metadata purge interval default.** The REST auto-compaction page says 3.0; the `couchbase-cli setting-compaction` page says 7 days. Worth an upstream documentation fix.
- **8.0.2 / 8.0.3 upgrade path tables.** The documentation enumerates paths to 8.0.1 only.

### Data model

- **Whether the maximum document key length is collection-dependent.** `docs.couchbase.com/server/current/learn/clusters-and-availability/size-limitations.html` states `Max key length | 250 bytes` with no distinction between `_default` and named collections and no note about collection-identifier overhead. Earlier material in this repository asserted 246 bytes for named collections; that could not be sourced and has been removed in favour of the documented 250. If a collection identifier does consume part of the key budget in practice, the documentation does not say so and should.

### Query and indexing

- **Maximum vector dimension for Hyperscale and Composite vector indexes.** 4096 is documented for the Search Service only. The skills decline to extend it to the Index Service indexes.
- **Hyperscale vector index algorithm.** The documentation describes IVF with quantization; the launch blog describes a Vamana/IVF hybrid. Both are recorded; neither is asserted.
- **Is query monitoring and profiling strictly Enterprise Edition?** The editions page lists it as EE/Capella; the monitoring documentation carries no edition label. This decides whether the whole query-diagnostics workflow exists on Community Edition.

- **Which release added `knn.filter`.** Documented for current releases with no "since" statement.
- **Vector index sizing.** Only a raw-payload floor survives; no published overhead factor exists. This is the most-asked sizing question and the largest remaining gap in `couchbase-sizing`.
- **GSI, Search, Eventing and Analytics sizing formulas.** The skills now say "measure on a sample" because nothing is published. Internal guidance would materially improve `references/indexes.md`.

### XDCR and mobile

- **Does the ten-user-xattr silent skip apply to plain active-active XDCR without Sync Gateway?** The documentation makes the claim only for `mobile=Active` (XDCR with Sync Gateway 4.0+, Server 7.6.6+). The skill refuses both to generalize it and to declare plain active-active safe above ten. Highest-priority item on this list.
- **Is there a documented absolute maximum xattr count per document?** None found. The "15 per query" figure is a query limit, not a document limit.
- **Whether Couchbase Support can revert a Capella App Services version out of band.** No downgrade, rollback or version-revert path is documented, and the Management API v4 has no `version` field on update. The skill says the upgrade is one-way; whether Support has an out-of-band route is a question for Support, not a documentation question.
- **What a Couchbase Lite 3.x client actually does when repointed at a different cluster.** The documentation states 4.0 clients can switch and that 3.x cannot do so safely, but never describes the 3.x failure mode.
- **Are Capella App Services covered by bucket or cluster backups?** Unmentioned on either page.

### Operations and security


- **Current REST paths for certificate upload and reload.** The prior paths could not be confirmed for 8.0 and were replaced with a procedural pointer.
- **Whether Rancher/SUSE is still a certified Kubernetes Operator platform.** Present in the previous content, absent from the current supported list.
- **Whether Operator 2.7 and 2.8 support rows should still be documented** for customers still running them.
- **`cbbackupmgr` RBAC.** The documentation contradicts itself: "Full Admin or Data Backup and Restore" on one page, "Only Full Administrators" on another.
- **Are distributed transactions Enterprise, Community, or both?** The transactions pages carry no edition banner, unlike XDCR and Eventing.
- **Recommended AWS DMS to Couchbase path**, so `couchbase-migration-execution` can be prescriptive rather than descriptive.
- **Whether `cbdatarecovery` warrants its own coverage** now that `cbtransfer` is deprecated in its favour.

### MCP servers

- **RBAC role needed by the `get_queries_*` performance tools.** Not named in the server's source, so the skill says "typically a cluster-level monitoring role" rather than naming one.
- **`mutate_subdocument` inner spec keys** (`path`, `value`, `delta`) were inferred from docstring prose rather than a schema. Worth a spot-check against a live server.
- **Admin MCP server: `CB_ADMIN_LOG_*` variable names and defaults**, and the defaults for `CB_ADMIN_DRY_RUN`, `CAPELLA_MAX_ENVIRONMENTS`, `CAPELLA_MAX_ITEMS` and `CB_EVENTING_PORT`. Documented behaviour without documented defaults; the reference marks each as "not stated".
- **Admin MCP server: `docs/tools.json` is stale** relative to its own source. The repository ships a generator for it; regenerating it would let this skill's family table be checked mechanically rather than by reading handlers.

---

### Tooling

- **Eval grading is substring matching.** `tools/run-evals.py --execute` is implemented against the Messages API: each case is one stateless request with the skill's `SKILL.md` and its linked references as the system prompt, graded by case-insensitive substring match. That is cheap, deterministic and reviewable, and it cannot distinguish a claim from its negation — which is why a `reject` string must be one only a wrong answer produces. If the org wants semantic grading, `claude plugin eval` offers an `llm` grader, but its case format differs from the one here and the suites would need restructuring.
- **The scheduled eval run has never executed.** It is wired to `ANTHROPIC_API_KEY` as a repository secret and runs weekly. Nobody has run it against a real key yet, so its pass rate and its cost are both unmeasured. Run it once manually before trusting the `--threshold 0.8` floor in the workflow.
- **An uncovered skill can merge.** The schema gate warns, rather than fails, when a skill has no eval suite. Making it a failure is a one-line change; it was left as a warning so the gate does not block a legitimate work-in-progress branch. Decide which behaviour the org wants.

---

## Uncorroborated claims

These the skills **do** state. Each is more likely right than wrong, but rests on inference or on a page that does not quite say it. Someone with access to internal sources should confirm or correct each, and the skill should be amended either way.

- **`INCLUDE MISSING` is gated at 7.1+ and optimizer hints at 7.6+** in `couchbase-sqlpp-tuning/SKILL.md` and two of its references. Neither release is stated as the introducing version on any page found; 7.6 for hints was inferred from their absence in earlier documentation.
- **The `ep_*` KV stat names** behind the alert rules in `couchbase-observability/references/alert-thresholds.md` were carried forward rather than re-derived from the 8.0 metrics reference. Couchbase 8.0 renamed at least two KV metrics, so a sweep of that file against the current reference is worth doing before the alert rules are used verbatim.
- **Sub-document requests are capped at 16 operations** in `couchbase-coding-standards/references/couchbase-sdk-idioms.md`. The Size Limits page it cites documents path length and nesting depth but not an operation count, so the citation does not support the number even though the number appears elsewhere in the repository.

---

## How to close an item

Correct the skill, cite the source in the pull request, add a regression case to the skill's eval suite with the wrong value in `reject`, and delete the entry from this file. An item that is genuinely undocumented rather than merely unfound should say so here and stay.
