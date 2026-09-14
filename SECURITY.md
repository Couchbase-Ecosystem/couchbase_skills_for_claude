# Security policy

## What lives in this repository

This repository contains documentation and the tooling that validates it — skill playbooks, reference material, eval cases, and shell and Python scripts. It ships no application code and no service, and nothing here runs against a cluster on its own. It does declare dependencies other software will fetch: the MCP server pinned in `mcp.json` and `gemini-extension.json`, and the Anthropic SDK and PyYAML used by the tooling.

That shapes what a security issue looks like here. The realistic risks are:

- **Guidance that weakens a cluster.** A skill that tells an agent to disable a safety gate, grant an over-broad role, expose a port, or hand credentials to the wrong place. A skill that reads as authoritative and is wrong in a dangerous direction is a security defect in this repository, not merely a documentation bug.
- **Credential exposure in examples.** A real connection string, key, certificate or password committed into a skill, a reference file or an eval case.
- **Unsafe defaults in the packaging.** The bundled MCP configuration (`mcp.json`, `gemini-extension.json`) declares the Couchbase MCP server read-only by default. A change that silently flips that, or that makes a write path reachable without explicit user approval, is a security defect.
- **A defect in the validation scripts** under `tools/` that lets one of the above through while reporting success.

Vulnerabilities in the MCP servers themselves, in Couchbase Server, or in Capella are **not** in scope here — report those to the relevant project, listed below.

## Reporting

**Do not open a public issue for a security report.**

Use GitHub's private vulnerability reporting on this repository: **Security → Report a vulnerability**. That creates a private advisory visible only to the maintainers.

If private reporting is unavailable to you, email **agent-plugins@couchbase.com** and put `SECURITY` in the subject line.

Please include:

- which file or files are affected, with paths
- what an agent or user would do as a result of following the guidance
- why that is unsafe, with a link to the Couchbase documentation that supports the correct behaviour if you have one
- any suggested wording for the fix

## What to expect

Maintainers aim to acknowledge a report within five business days and to agree a remediation plan with the reporter before anything is made public. Fixes to guidance land as an ordinary pull request once the advisory is resolved, with a regression case added to the skill's eval suite so the unsafe wording cannot silently return.

This project is community-maintained and is not covered by Couchbase's support team, so response is best-effort rather than contractual.

## Related projects

Report issues in those projects to them, not here:

| Project | Where |
|---|---|
| Couchbase MCP server | https://github.com/couchbase/mcp-server-couchbase |
| Couchbase Admin MCP server | https://github.com/Couchbase-Ecosystem/couchbase_admin_mcp_server |
| Couchbase Server, Capella, SDKs, Couchbase Lite | https://www.couchbase.com/security/ |

## Credentials in this repository

Every connection string, username, password, key and certificate path in this repository is a placeholder. If you believe a real credential has been committed, treat it as a live incident: report it privately using the process above and assume it is compromised, rather than opening a pull request that removes it — the value stays in the git history either way and needs rotating.
