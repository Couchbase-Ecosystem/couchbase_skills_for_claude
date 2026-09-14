# Eval suites

Every skill in `skills/` has a matching eval suite at
`testing/<skill-name>/evals/evals.json`. The suites are behavioural regression
tests: each case is a prompt a real user might type, plus the things the answer
must and must not contain.

## Layout

```
testing/
  <skill-name>/
    evals/
      evals.json
```

`<skill-name>` must be exactly the directory name under `skills/`.

## Schema

```json
{
  "skill": "couchbase-magma",
  "cases": [
    {
      "name": "magma-is-enterprise-only",
      "input": "Can we switch our Community Edition buckets to Magma to save memory?",
      "expect": ["Enterprise Edition only", "Couchstore", "no"],
      "reject": ["yes, Magma is available in Community Edition"],
      "threshold": 2,
      "tier": "deep"
    }
  ]
}
```

| Field | Type | Rules |
|---|---|---|
| `skill` | string | Must equal the parent directory name. |
| `cases` | array | At least 4 cases per skill. |
| `name` | string | Short, kebab-case, unique within the suite. |
| `input` | string | The user prompt, written the way a user would actually type it. |
| `expect` | array of strings | Substrings or concepts the answer should contain. |
| `reject` | array of strings | Substrings the answer must **not** contain. May be empty, but the key is required. |
| `threshold` | integer | How many `expect` entries must match. Must be `<= len(expect)`. |
| `tier` | string | One of `smoke`, `standard`, `deep`. |
| `expect_skill` | string | Optional. On a near-miss case, the sibling skill that should actually handle the prompt. |

A case passes when at least `threshold` of its `expect` entries are present and
none of its `reject` entries are.

## Tiers

- **`smoke`** — the skill's most obvious trigger. If this fails, the skill is
  broken. Run on every commit.
- **`standard`** — realistic day-to-day prompts, including near-miss routing
  between sibling skills. Run on pull requests.
- **`deep`** — accuracy and safety regressions: version gates, edition gates,
  corrected tool and resource names, corrected defaults. These are the cases
  that pin specific documented facts, and they are the most expensive to run.
  Run before a release.

## What every suite contains

1. **At least two should-trigger cases** taken from the skill's own
   "When this skill applies" list — not invented triggers.
2. **At least one near-miss case**: a prompt that sounds like this skill but
   belongs to a named sibling. It carries `expect_skill` naming that sibling.
3. **At least one accuracy or safety case** pinning a real fact from the skill
   body — a version gate, an Enterprise-only restriction, a corrected tool or
   resource name, a corrected default — with the known-wrong prior value in
   `reject` where one exists.

A `reject` entry must be a string that **only a wrong answer produces**. Never
reject a value the skill deliberately names in order to warn against it: if the
skill says "never use `cluster_admin` for a scrape account" or "the resource is
`CouchbaseReplication`, not `CouchbaseReplicationRepresentation`", then a
correct answer repeats that wrong value while warning about it, and a case that
rejects the bare string can never pass. Reject a phrasing that only the mistake
yields, or move the discrimination into `expect` instead — pin the correct value
there and leave `reject` empty.

**This is now enforced mechanically, not merely advised.** `--dry-run` builds
the skill's loaded corpus (the same `SKILL.md` body plus linked references that
`--execute` injects as the system prompt) and **fails** if any `reject` string
appears in it, case-insensitively:

```
FAIL testing/couchbase-magma/evals/evals.json: case 'near-miss-cluster-capacity-math':
     reject string 'numVBuckets' appears in the loaded corpus of skill 'couchbase-magma'
     — a correct answer would use it. Assert routing in 'expect' (the sibling skill's
     name and handoff wording) instead.
```

The check is offline and costs no API calls; CI therefore blocks the merge. It
matters most for near-miss cases: a near-miss must assert **routing** — the
sibling skill's name, the handoff wording the skill's `## Related skills` and
scope sections actually contain, plus `expect_skill` as the machine-readable
claim — not the absence of a vocabulary word the loaded skill teaches.

## Running

Schema check only — parses every suite, validates the fields above, and reports
skills with no suite. No model calls, no network:

```bash
python3 tools/run-evals.py --dry-run
```

Executing run — sends each `input` to the model with the skill loaded and scores
the response against `expect` / `reject` / `threshold`:

```bash
python3 tools/run-evals.py --execute
```

`--execute` needs `ANTHROPIC_API_KEY` and `pip install anthropic`. It validates
the schema first and refuses to spend API calls if that fails. Narrow a run with
`--skill <name>` (repeatable) or `--tier smoke`; `--json results.json` writes the
full result set, `--save-answers` includes each model response, and
`--threshold 0.8` sets a pass-rate floor so one flaky case does not fail the job.

Each case is one stateless request. The skill's `SKILL.md` body plus every
reference file it links to becomes the system prompt, and the case's `input` is
the user turn. Grading is case-insensitive substring matching: at least
`threshold` of the `expect` strings present, and none of the `reject` strings.

`python3 tools/run-evals.py --self-test` exercises the grader against built-in
fixtures. Run it if you change grading logic.

CI runs the schema check on every push; a suite that fails schema validation
blocks the merge.

## Adding a case

1. **Read the skill first.** Never put a fact in `expect` that the SKILL.md or
   its references do not actually state. If you cannot point at the line, it
   does not go in the suite.
2. Write the `input` as a specific, concrete prompt. "Help me with Couchbase"
   tests nothing; "Why is my query doing a PrimaryScan when I have an index on
   the field?" is a test.
3. Put the correct value in `expect`. If a wrong value was previously in
   circulation — an old product name, a wrong byte limit, a tool name that never
   existed — put that wrong value in `reject`. That is what turns the case into
   a regression test. The wrong value must not appear anywhere in the skill's
   own corpus; `--dry-run` fails the suite if it does.
4. Keep `threshold` at or below `len(expect)`, and set it so that a good answer
   passes without having to use your exact wording. Two or three of four is
   usually right.
5. Pick a tier. Anything pinning a corrected fact is `deep`.
6. Run `python3 tools/run-evals.py --dry-run` before committing.

## Adding a skill

A new skill needs a new `testing/<skill-name>/evals/evals.json` in the same
commit. The schema check *warns* about a skill with no suite and still exits 0,
so nothing mechanical stops an uncovered skill from merging — treat the warning
as a blocker in review.
