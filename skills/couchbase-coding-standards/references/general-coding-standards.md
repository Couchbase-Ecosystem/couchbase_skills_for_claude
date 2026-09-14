# General coding standards

Language-agnostic engineering discipline. These are not Couchbase-specific; they apply to any code in the project and set the baseline the Couchbase-specific references build on. Where a rule has a Couchbase wrinkle, it points to the relevant reference.

## Contents

- [Naming](#naming)
- [Functions and structure](#functions-and-structure)
- [Comments and docstrings](#comments-and-docstrings)
- [Error handling](#error-handling)
- [Testing](#testing)
- [Version control](#version-control)
- [Code review](#code-review)
- [Secrets and configuration](#secrets-and-configuration)
- [Formatting and linting](#formatting-and-linting)
- [Checklist](#checklist)

## Naming

- **Names carry intent.** A name should say what the thing is or does without needing a comment. `retryCount` over `n`; `activeConnections` over `list2`.
- **Match the language's convention, don't invent one.** `snake_case` for Python functions/variables, `PascalCase` for classes; `camelCase` for Java/JS methods and variables, `PascalCase` for types; `PascalCase`/`camelCase` per Go's exported/unexported rule. Don't carry one language's casing into another.
- **Booleans read as predicates.** `is_active`, `has_replica`, `should_retry` — not `active`, `replica`, `retry`.
- **Avoid abbreviations that aren't universal.** `cluster`, not `clstr`. `configuration` or `config` (config is universal); `cfg` is not.
- **Reserve single letters for tight scopes** — a loop index or a lambda parameter, never a field or a function argument that outlives three lines.
- **Don't encode type in the name** (`strName`, `listItems`) — the type system already does that. Encode *role*.

## Functions and structure

- **One function, one responsibility.** If you need "and" to describe what it does, it's two functions.
- **Keep functions short enough to see whole.** No hard line count, but a function you must scroll to read is a refactor candidate.
- **Limit parameters.** More than ~4 positional parameters is a signal to pass an options object / struct / dataclass. This also future-proofs the signature.
- **Return early.** Guard clauses over deep nesting: validate and bail at the top, keep the happy path un-indented.
- **No hidden side effects.** A function named `get_user` must not also write. If it must do both, name it for the write (`fetch_and_cache_user`).
- **Depth of nesting is a complexity smell.** More than 2–3 levels of nesting usually means an extracted function is waiting to be born.

## Comments and docstrings

- **Comment the "why", never the "what".** The code says what. `# skip drafts — they aren't synced to mobile` earns its place; `# increment i` does not.
- **Every public function/class gets a docstring** stating purpose, parameters, return, and the errors it can raise. Follow the language's doc convention (Python docstrings, Javadoc, JSDoc, Go doc comments).
- **Document non-obvious constants inline.** No magic numbers: `timeout=2500  # ms; p99 KV latency is <5ms, this is 500x headroom` beats a bare `2500`.
- **Keep comments truthful.** A stale comment is worse than none. If you change the code, change the comment.

## Error handling

- **Never swallow silently.** A bare `except: pass` (or `catch (e) {}`) hides the failure that will page you at 3am. Catch specifically, handle or re-raise, log with context.
- **Catch the narrowest exception that fits.** Broad catches mask bugs. See `error-handling-and-resilience.md` for the Couchbase-specific exception taxonomy.
- **Fail fast on programmer errors, retry on transient ones.** A malformed key is a bug (fail loudly); a timeout is transient (retry with backoff). Don't retry bugs.
- **Preserve the cause.** Wrap-and-raise with the original exception chained (`raise X from e`, `throw new X(cause)`), so the stack trace survives.
- **Errors are values at the boundary.** Decide deliberately where an error becomes a user-facing result vs. a propagated exception; don't let that happen by accident three layers deep.

## Testing

- **Every non-trivial unit gets a test.** Especially the error paths — the happy path usually works; the failure paths are where regressions hide.
- **Tests are code: name them for what they assert.** `test_upsert_retries_on_timeout`, not `test_upsert_2`.
- **Isolate the unit under test.** Mock or stub the Couchbase collection/cluster for pure unit tests; keep integration tests (real cluster or testcontainers) in a separate, clearly-marked suite. Don't make unit tests depend on a live cluster.
- **Test the edges:** empty result, missing document, concurrent write / CAS mismatch, timeout, oversize input. See `error-handling-and-resilience.md` for the Couchbase-specific ones.
- **A bug fix starts with a failing test** that reproduces it, then the fix makes it pass.

## Version control

- **Small, focused commits.** One logical change per commit; a commit that touches migration, styling, and a bug fix is three commits.
- **Write the message for the reader six months out.** Imperative subject ("Add retry to profile upsert"), body explaining *why* when it isn't obvious. Consider Conventional Commits (`feat:`, `fix:`, `refactor:`) if the project uses them.
- **Never commit secrets, credentials, or connection strings.** See Secrets below. If one lands in history, rotate it — history is forever.
- **Branch names describe the work**, not the person: `fix/profile-cas-retry`, not `chris-branch`.

## Code review

Review against a consistent bar. A reusable checklist:

- [ ] **Correct:** does it do what it claims, including the error paths?
- [ ] **Couchbase-safe:** reads handle missing docs; writes handle ambiguity/CAS; SQL++ is parameterized (see `sqlpp-in-code.md`)
- [ ] **Idiomatic:** follows the SDK/language grain (see `couchbase-sdk-idioms.md`)
- [ ] **Named well:** intent-revealing names, self-describing keys (see `key-and-document-conventions.md`)
- [ ] **Tested:** unit tests including failure paths; integration tests where behavior depends on the cluster
- [ ] **No secrets** in code or commits
- [ ] **Readable:** a reviewer understands it without asking the author
- [ ] **Version-verified:** SDK symbols match the pinned SDK version, not assumed

Give feedback direct over diplomatic, but on the code, not the person. Separate blocking defects (correctness, security) from preferences (style opinions) — label which is which.

## Secrets and configuration

- **Credentials come from the environment or a secrets manager, never source.** Connection strings, usernames, passwords, API keys: env vars, vault, or a secrets service — not literals, not committed config files.
- **Config is layered and explicit.** Sensible defaults in code, overridable by environment, documented. No surprise behavior from an unset variable.
- **Redact secrets from logs.** Never log a password or a full connection string. Log the host, not the credential.
- **Fail loudly on missing required config** at startup, not lazily at first use in production.

## Formatting and linting

- **Automate formatting; don't argue about it.** Adopt the language's standard formatter (Python `black`/`ruff format`, JS/TS `prettier`, Go `gofmt`, Java a shared formatter config) and run it in CI. Formatting should never be a review comment.
- **Lint in CI, pin the linter version.** Ruff/flake8, ESLint, `go vet`/`golangci-lint`, etc. Pin the version so the same code doesn't pass locally and fail in CI. (Repo rule: verify against the *pinned* linter version, not whatever is installed locally.)
- **Treat warnings as signal.** A warning you always ignore should be either fixed or explicitly disabled with a reason, not left to train the team to ignore warnings.

## Checklist

- [ ] Names reveal intent; casing matches the language
- [ ] Functions do one thing; parameters bounded; early returns
- [ ] Comments explain why; public APIs have docstrings; no magic numbers
- [ ] Errors caught narrowly, handled or re-raised with cause, never swallowed
- [ ] Unit tests cover failure paths; integration tests separated
- [ ] Commits small and message-clear; no secrets in history
- [ ] Secrets from env/vault; redacted in logs
- [ ] Formatter + linter run in CI at pinned versions
