# Skill authoring standard

The conventions every skill in this repository follows, and where each rule comes from. Verified 2026-09-14 against:

- Agent Skills specification — https://agentskills.io/specification
- Optimizing skill descriptions — https://agentskills.io/skill-creation/optimizing-descriptions
- Agent Skills best practices — https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Claude Code skills documentation — https://code.claude.com/docs/en/skills
- Plugin and marketplace reference — https://code.claude.com/docs/en/plugins-reference

Rules that come from the specification or Anthropic's documentation are marked **[spec]**. Rules that are this repository's own choice are marked **[house]**. Keep the house rules, but do not present them as the standard when sharing skills elsewhere.

## Contents

- [Two layers, different rules](#two-layers-different-rules)
- [Frontmatter](#frontmatter)
- [Writing the description](#writing-the-description)
- [Progressive disclosure](#progressive-disclosure)
- [Directory layout](#directory-layout)
- [Workflows and instruction design](#workflows-and-instruction-design)
- [Paths](#paths)
- [Evaluation](#evaluation)
- [Packaging](#packaging)
- [Pre-flight checklist](#pre-flight-checklist)

---

## Two layers, different rules

There are two standards in play and they do not agree on the field list.

| Layer | Authority | Scope |
|---|---|---|
| **The Agent Skills specification** | agentskills.io, stewarded by Anthropic as an open standard | six frontmatter fields; portable across Claude, Codex, Cursor, Gemini CLI and anything else implementing it |
| **Claude Code extensions** | code.claude.com | roughly twenty additional frontmatter fields; work only in Claude Code, and are a hard error when a skill is packaged or uploaded elsewhere |

**This repository targets the specification.** Skills here must install anywhere, so Claude Code-only fields — `when_to_use`, `model`, `effort`, `context`, `paths`, `agent`, `argument-hint` and the rest — are not used. `tools/validate-skills.sh` rejects them.

---

## Frontmatter

**[spec]** Six fields are valid. Anything else fails validation and is rejected on upload:

| Field | Required | Constraint |
|---|---|---|
| `name` | yes | 64 characters maximum. Lowercase letters, digits and hyphens only. No leading, trailing or consecutive hyphen. Must match the parent directory name. No XML tags. Cannot contain `anthropic` or `claude`. |
| `description` | yes | 1024 characters maximum, non-empty, no angle brackets. Says what the skill does *and* when to use it. |
| `license` | no | A license name or a reference to a bundled license file. |
| `compatibility` | no | 500 characters maximum. Environment requirements — product, system packages, network access. |
| `metadata` | no | A map of string keys to string values. A skill's own version number belongs here, never as a top-level `version` key. |
| `allowed-tools` | no | A space-separated **string** of pre-approved tools, not a YAML list. Marked experimental in the specification. |

**[house]** `license: Apache-2.0` on every skill, matching the repository.

**[house]** Naming: `couchbase-<topic>`. Anthropic recommends gerund forms (`processing-pdfs`) as a general convention; a product-scoped corpus reads better with a consistent product prefix, and the prefix also keeps names distinct when several skill collections are installed side by side.

---

## Writing the description

The description is the only part of a skill that is always in context. It is what decides whether the skill triggers at all, so it is worth more attention than any other line in the file.

**[spec]** Third person. "Diagnoses and tunes slow SQL++ queries", never "I can help you tune queries" or "You can use this to tune queries" — first and second person measurably degrade skill discovery.

**[spec]** Frame it as an instruction to the agent — "Use this skill when…" — rather than a description of the artifact — "This skill does…".

**[spec]** Lead with the key use case. Hosts truncate long skill listings under a context budget, and the first sentence is what survives.

**[spec]** Focus on user intent, not implementation. List the terms a user would actually type, including the cases where they never name the product.

**[spec]** Err toward being pushy about scope. Enumerate the contexts where the skill applies rather than hoping the agent infers them.

**[house]** State what the skill is distinct *from*, naming the sibling that handles the near miss. In a corpus of thirty-one overlapping skills this does more to prevent wrong triggers than anything else.

**[house]** Measure it. A description between 1024 and 1536 characters is legal in Claude Code and rejected by the specification validator — so it will work on the author's machine and fail on upload.

```bash
python3 -c "import yaml,sys; print(len(yaml.safe_load(open(sys.argv[1]).read().split('---',2)[1])['description']))" skills/<name>/SKILL.md
```

---

## Progressive disclosure

**[spec]** Three levels, each loaded at a different moment:

| Level | What | Loaded |
|---|---|---|
| 1 | `name` + `description` (~100 tokens) | always, at startup, for every installed skill |
| 2 | the `SKILL.md` body (under ~5000 tokens recommended) | when the skill triggers |
| 3 | `references/`, `scripts/`, `assets/` | only when the body routes the agent to them |

**[spec]** Keep `SKILL.md` under 500 lines. Split into reference files as you approach it.

**[spec]** Concision is not stylistic. Once loaded, the body stays in context across turns and every line is a recurring cost. Assume the agent is already competent: cut any explanation of what a JSON document is or how an index works in general. Challenge each line — does it justify its tokens?

**[spec]** Keep references one level deep. Do not chain `SKILL.md → advanced.md → details.md`; a file reached transitively may be read only in part, which produces confidently incomplete answers. Every reference links directly from `SKILL.md`.

**[spec]** Give any reference over 100 lines a table of contents, so a partial read still shows the full scope.

**[spec]** Large bundled files cost nothing until they are read, so depth in `references/` is encouraged. The constraint is on the body, not the bundle.

**[house]** Reference files target 80–400 lines — the tighter band inside the specification's limit — and each must be self-contained. A reference may point at a sibling; it must never be reachable only through one.

**[house]** No empty `references/` directory. A single-file skill with no routing table is correct when the topic does not need splitting.

---

## Directory layout

**[spec]**

```
skills/<skill-name>/
  SKILL.md          # required, exactly one per skill
  references/       # optional, documentation loaded on demand
  scripts/          # optional, executable code
  assets/           # optional, templates and resources used in output
```

**[spec]** `references/`, plural. Exactly one `SKILL.md` per skill — nested ones load in Claude Code's filesystem but are rejected by the Skills API and the Claude apps on upload. Supporting prose becomes `references/<topic>.md`, never a second `SKILL.md`.

**[house]** `evals/` sits outside the skill, at `testing/<skill-name>/evals/`, because eval material is excluded from a packaged skill anyway and keeping it out of the skill directory makes that boundary obvious.

---

## Workflows and instruction design

**[spec]** Break complex operations into explicit sequential steps, and give genuinely complex workflows a checklist the agent can copy and tick off. This is what stops validation steps being skipped.

**[spec]** Build validate → fix → repeat loops for quality-critical work, and gate progress explicitly: only proceed when validation passes. The validator can be a script or a document the agent reads and checks against.

**[spec]** Match specificity to fragility. Prose instructions where several approaches are valid and context decides; parameterized templates where a preferred pattern exists; exact, do-not-modify scripts where the operation is fragile and consistency is critical.

**[spec]** For high-stakes batch operations, plan → validate → execute: have the agent write a structured plan, validate the plan, then run it.

**[spec]** Use consistent terminology throughout. Pick one term and never drift to a synonym — inconsistency degrades instruction-following.

**[spec]** Avoid time-sensitive phrasing. Not "before August 2025, use the old API"; put superseded guidance in its own clearly-labelled section instead.

**[spec]** Do not offer a menu. Give one default with an escape hatch, not five options.

**[spec]** Use fully-qualified MCP tool names where a host namespaces them, so the agent can still locate a tool when several servers are connected.

**[house]** Every skill that touches a cluster opens with a pre-flight step that confirms the connection and the server's posture before proposing anything.

**[house]** Read-only is the resting state. No skill instructs a user to disable a safety gate in order to finish a task.

---

## Paths

**[spec]** Every path written inside a skill uses forward slashes — `references/guide.md`, `scripts/helper.py` — regardless of the author's operating system. Backslash paths break on the Unix runtimes where skills execute, and Anthropic names this explicitly as an anti-pattern.

This is the one place a Windows-first house preference does not apply. Shell commands *given to a user for their own machine* can be Windows syntax; paths *written into a skill file* are always Unix-style. `tools/validate-skills.sh` enforces this.

---

## Evaluation

**[spec]** Seeing a skill trigger tells you the agent found it, not that it worked.

**[spec]** Build evaluations before writing extensive documentation. Run the agent on representative tasks *without* the skill, record the specific failures, write the minimum instruction that fixes exactly those, and iterate. This solves observed gaps rather than imagined ones.

**[spec]** At least three scenarios per skill, each with a query, any input files, and expected-behaviour assertions. Measure a baseline with the skill disabled. Use a fresh session each time — leftover authoring context hides gaps in the written instructions.

**[spec]** Test on every model the skill will run on. What is sufficient for a large model may under-specify for a small one.

**[spec]** Tune the description by measurement, not intuition: a set of should-trigger and near-miss should-not-trigger queries, several runs each, selected on validation pass rate.

**[house]** At least four cases per skill: two should-trigger, one near-miss naming the correct sibling, and one that pins a specific corrected fact. Every correction to a skill adds a regression case with the old wrong value in `reject`. See [`../testing/README.md`](../testing/README.md).

---

## Packaging

**[spec]** A repository of many skills is distributed as a plugin with a marketplace manifest, not as a loose directory. `.claude-plugin/marketplace.json` needs a kebab-case `name`, an `owner` object with a `name`, and a `plugins` array. `.claude-plugin/plugin.json` needs at minimum a `name`; a multi-skill plugin points at `skills/` and its skills are namespaced `plugin-name:skill-name`.

**[spec]** `claude plugin validate <path> --strict` checks manifest syntax, component paths and unrecognized fields. `claude plugin eval` runs behavioural tests against a plugin, repeating each case without the plugin to produce a baseline delta — it bills real model calls, so it belongs in a scheduled job rather than a per-push gate.

**[house]** Per-harness manifests for Claude, Codex and Cursor, plus a Gemini extension manifest, all pointing at the same `./skills/` and the same MCP configuration. `tools/validate-manifests.py` fails if they drift apart.

---

## Pre-flight checklist

Specification:

- [ ] Frontmatter contains only `name`, `description`, `license`, `allowed-tools`, `compatibility`, `metadata`
- [ ] `name` is kebab-case, 64 characters or fewer, matches the directory, avoids `claude` and `anthropic`
- [ ] `description` is third person, leads with the key use case, lists trigger terms, names the sibling it is distinct from, and is 1024 characters or fewer with no angle brackets
- [ ] `SKILL.md` is under 500 lines
- [ ] Exactly one `SKILL.md`; `references/` is one level deep; any **reference file** over 100 lines has a table of contents
- [ ] All paths use forward slashes
- [ ] Progressive disclosure applied — depth is in `references/`, not the body
- [ ] Consistent terminology; no time-sensitive phrasing; one default rather than a menu

House:

- [ ] `license: Apache-2.0`
- [ ] `## Pick the right reference` routing table on any multi-file skill, and every reference linked from it
- [ ] `## Related skills` section, reciprocated in the siblings it names
- [ ] No empty `references/` directory
- [ ] Pre-flight step before any cluster interaction; read-only by default
- [ ] Version- and edition-gated wherever it matters; older-release guidance gated rather than deleted
- [ ] Every version-sensitive claim verified against a primary source, or explicitly marked unverified
- [ ] At least four eval cases, including a regression pin for anything corrected
- [ ] Entry in `skills/OWNERS.yaml`
