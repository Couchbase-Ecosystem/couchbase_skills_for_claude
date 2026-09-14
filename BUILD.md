# Build and verification process

How a change gets from an idea into this repository, and what it has to survive on the way. This process exists because the content here is version-sensitive: a skill that was correct in June is wrong by September, and a wrong skill is worse than a missing one because an agent will state it confidently.

The authoring standard the skills themselves are written to is in [`docs/skill-authoring-standard.md`](docs/skill-authoring-standard.md). This document is about the pipeline around it.

## Contents

- [Prerequisites](#prerequisites)
- [The four gates](#the-four-gates)
- [Adding a skill](#adding-a-skill)
- [Changing a skill](#changing-a-skill)
- [The content verification pass](#the-content-verification-pass)
- [Packaging](#packaging)
- [Release](#release)
- [Review cadence](#review-cadence)

---

## Prerequisites

- `bash` and standard POSIX tools (`awk`, `sed`, `grep`, `find`)
- Python 3.12 or later
- Optional: a recent Claude Code if you want to run `claude plugin eval` instead — check its own docs for the minimum version

No build step produces artifacts. The repository is the deliverable: the skills are markdown, and the manifests point at them in place.

---

## The four gates

Every change runs all four, locally and in CI. They are fast, deterministic, free, and require no network or API key.

```bash
./tools/validate-skills.sh
python3 tools/run-evals.py --dry-run
python3 tools/validate-manifests.py
python3 tools/validate-links.py
```

`python3 tools/run-evals.py --self-test` runs alongside them in CI on every pull request. It exercises the grader against built-in fixtures, so run it locally too whenever you change grading logic.

### Gate 1 — `tools/validate-skills.sh`

Checks each skill against the [Agent Skills specification](https://agentskills.io/specification) and this repository's conventions:

*Specification*
- `SKILL.md` exists and opens with a YAML frontmatter block
- frontmatter contains only the six valid keys: `name`, `description`, `license`, `allowed-tools`, `compatibility`, `metadata`
- `name` is present, kebab-case, 64 characters or fewer, has no leading, trailing or doubled hyphen, avoids the reserved words `claude` and `anthropic`, and matches the containing directory
- `description` is present, 1024 characters or fewer, and free of angle brackets
- `compatibility`, if present, is 500 characters or fewer
- exactly one `SKILL.md` per skill — nested ones are rejected on upload by the Skills API, so they fail here

*House*
- `license` is present and is `Apache-2.0`
- `SKILL.md` warns above 500 lines and fails above 800
- `references/` is one level deep, never empty when present, and every file in it is linked from `SKILL.md`
- no backslash paths in markdown links
- no personal branding or MIT licensing language anywhere in the skill

### Gate 2 — `tools/run-evals.py --dry-run`

Validates the eval suites' schema: `skill` matches its directory and a real skill, case names are unique, `expect` is non-empty, `reject` is present, `threshold` is an integer no larger than the number of `expect` entries, `tier` is one of `smoke` / `standard` / `deep`, and any `expect_skill` names a skill that exists. It also warns about skills with no suite at all — a warning, not a failure, so an uncovered skill still merges unless a reviewer stops it.

This gate spends no money. The executing run (`--execute`) does, which is why it lives in a scheduled and manually-dispatchable workflow rather than the pull-request gate.

### Gate 3 — `tools/validate-manifests.py`

Validates the packaging and the cross-file consistency that nothing else catches:

- every manifest is valid JSON
- the marketplace has a kebab-case name, an owner object, and a non-empty plugins array
- the Claude, Codex and Cursor plugin manifests agree on name, version and license, declare `Apache-2.0`, and point at `./skills/` and `./mcp.json`
- `mcp.json` and `gemini-extension.json` declare a `couchbase` server, and it is read-only by default
- `skills/OWNERS.yaml` has exactly one entry per skill and no orphans
- `README.md` mentions every skill directory, and links no skill directory that does not exist
- `gemini-extension.json` carries the same version as the plugin manifests

### Gate 4 — `tools/validate-links.py`

Checks every markdown link in the repository: relative file links resolve, and in-file anchors match a heading in the target file. Fenced code and YAML frontmatter are excluded.

The anchor half is the one that earns its keep. GitHub's slugifier strips punctuation and turns each remaining space into a hyphen, so a heading containing an em dash, an arrow, a slash or a `+` produces a *double* hyphen where an author naturally writes one — `## Code pattern — Python` becomes `code-pattern--python`. A hand-written table of contents gets this wrong most times it comes up, and the resulting link fails silently.

---

## Running the evals

```bash
python3 tools/run-evals.py --execute                       # every case
python3 tools/run-evals.py --execute --tier smoke          # one tier
python3 tools/run-evals.py --execute --skill couchbase-xdcr  # one skill, repeatable
python3 tools/run-evals.py --execute --json results.json --threshold 0.8
```

Needs `ANTHROPIC_API_KEY` and `pip install anthropic`. Each case is one stateless request: the skill's `SKILL.md` body plus every reference file it links to becomes the system prompt, the case's `input` is the user turn, and the answer is graded by case-insensitive substring match — at least `threshold` of the `expect` strings present, none of the `reject` strings present.

Substring grading is blunt on purpose: cheap, deterministic, and reviewable in a diff. Its one real limit is that it cannot distinguish a claim from its negation, which is why a `reject` string must be one only a wrong answer produces.

`--threshold` sets a pass-rate floor so a scheduled run does not go red over a single flaky case. `--json` writes the full result set, and `--save-answers` includes each model response for inspection.

---

## Adding a skill

1. Pick a name. Lowercase, hyphenated, `couchbase-` prefixed, and specific — `couchbase-xdcr`, not `couchbase-replication-helper`.
2. `mkdir -p skills/<name>` and write `SKILL.md` with the frontmatter and body shape from [`CONTRIBUTING.md`](CONTRIBUTING.md).
3. Add `references/*.md` only once the body would otherwise pass roughly 150 lines of depth. Do not create an empty `references/` directory.
4. Add a `## Related skills` section, and add a reciprocal line to any sibling whose scope now abuts this one.
5. Add the skill to the table in `README.md`.
6. Add an entry to `skills/OWNERS.yaml` with a real reviewer and a cadence.
7. Write `testing/<name>/evals/evals.json` — at least four cases: two that should trigger, one near-miss that belongs to a sibling, and one that pins a specific fact.
8. Run the four gates.

---

## Changing a skill

- Edit the file directly. No amendment documents, no changelog files inside a skill.
- If you add a reference, add its row to the routing table in `SKILL.md`.
- Re-measure the description if you touched it: `python3 -c "import yaml,sys; print(len(yaml.safe_load(open(sys.argv[1]).read().split('---',2)[1])['description']))" skills/<name>/SKILL.md`
- Update `## Related skills` in any sibling the change affects.
- Add a regression case to the eval suite for anything you corrected.
- Update `last_reviewed` in `skills/OWNERS.yaml`.

---

## The content verification pass

This is the part that is easy to skip and expensive to skip. Run it per skill, not per repository.

**1. Inventory the claims.** Read the skill and its references and list every claim that could rot: version numbers, upgrade paths, numeric limits, defaults, edition gates, product names, tool names, SDK symbols, CLI flags, metric names, CRD field names, REST paths.

**2. Verify each against a primary source**, in this order of authority:

- `docs.couchbase.com` for the relevant release, including its release notes
- the official Couchbase GitHub repository for the component
- `couchbase.com/blog` for launch and naming announcements
- the MCP server's own inventory (`cb_mcp_list_tools`, `cb_mcp_get_tool_info`) for tool names

Training data is not a source. Neither is another skill in this repository.

**3. Correct, gate, or cut.** A claim that is wrong gets corrected with a citation. A claim that is right only for some releases gets a version gate. A claim you cannot verify gets removed or explicitly marked unverified — it never stays as a bare assertion.

**4. Watch for these specific failure modes**, all of which have occurred here:

- *Invented numbers.* Latency figures, throughput ranges, cache-hit targets, performance multipliers and alert thresholds that no Couchbase page publishes. If you cannot cite it, it is judgement — label it as judgement or delete it.
- *Invented tool and symbol names.* Plausible-looking MCP tool names and SDK methods that do not exist. Check the server's inventory and the SDK's documentation.
- *Stale product names.* "Capella Columnar" for Capella Analytics; "FTS" where the Search Service is meant.
- *Inverted defaults.* Saying a safety gate defaults off when it defaults on, or that an opt-in feature is automatic.
- *Silently dropped older guidance.* Deleting 7.x content when adding 8.x content, instead of gating both.

**5. Record what you could not verify.** Open questions go in [`FINDINGS.md`](FINDINGS.md) with enough context for a Couchbase engineer to rule on them, not into a skill as a hedge.

**6. Pin the correction.** Every fact you fixed becomes an eval case with the wrong value in `reject`.

---

## Packaging

The repository root is the plugin for every harness. There is nothing to build; the manifests are checked in:

| File | Consumed by |
|---|---|
| `.claude-plugin/marketplace.json` | the marketplace listing |
| `.claude-plugin/plugin.json` | Claude Code and the Claude apps |
| `.codex-plugin/plugin.json` | Codex, including its `interface` block |
| `.cursor-plugin/plugin.json` | Cursor |
| `gemini-extension.json` | Gemini CLI, with the MCP server declared inline |
| `mcp.json` | Claude, Codex and Cursor — shared MCP server wiring |

They all point at `./skills/`, so adding a skill directory is the whole of adding it to the package. Bump `version` in the three `plugin.json` files and `gemini-extension.json` together — gate 3 fails if they drift.

To produce per-skill archives for hosts that take one skill at a time:

```bash
mkdir -p skill-zips
for d in skills/*/; do
  name="$(basename "$d")"
  case "$name" in _*) continue ;; esac
  zip -rq "skill-zips/${name}.zip" "$d"
done
```

---

## Release

1. All four gates pass on `main`.
2. Run the executing eval job (`Actions → evals → Run workflow`) and read the results. A regression pin that starts failing means either the skill drifted or the fact changed — find out which before releasing.
3. Bump the version in the four manifests.
4. Tag the release.

There is no artifact to publish. Plugin hosts install from the repository at the tag or branch.

---

## Review cadence

`skills/OWNERS.yaml` carries a `last_reviewed` date and a `review_cadence_days` for every skill. An overdue skill is a bug: its facts have had a release cycle to drift and nobody has checked.

Reviewing means running the content verification pass above, not skimming for typos. Couchbase Server, Capella, the SDKs, Couchbase Lite and the MCP servers all ship on their own cadences, and a skill that names versions is only as good as its last verification date.
