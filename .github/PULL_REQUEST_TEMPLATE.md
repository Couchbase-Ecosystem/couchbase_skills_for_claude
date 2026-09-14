<!--
Thank you for contributing to Couchbase Skills for Claude.
Please read CONTRIBUTING.md before submitting. Keep pull requests small and
focused — one skill, one fix, or one refactor per pull request.
-->

## Related issue

<!-- GitHub issue for external contributors, JIRA ticket for Couchbase internal contributors. -->
Resolves:

## What does this change do?

## Why is this change needed?

## Evidence

<!-- For any version-sensitive, numeric, or product-naming claim you added or changed,
     link the docs.couchbase.com page that supports it. Claims without a source will
     be asked for one. -->

| Claim | Source |
|---|---|
|  |  |

## Checklist

- [ ] `./tools/validate-skills.sh` passes
- [ ] `python3 tools/run-evals.py --dry-run` passes
- [ ] `python3 tools/validate-manifests.py` passes
- [ ] `python3 tools/validate-links.py` passes
- [ ] Every version-sensitive claim is cited above, or is version-gated and marked unverified
- [ ] Older-version guidance was gated, not deleted (7.x and 8.x are both in production)
- [ ] Couchbase-native terminology (Bucket → Scope → Collection, SQL++, GSI, the Search Service, Capella)
- [ ] Read-only by default; writes and DDL require explicit user approval
- [ ] `references/` used for depth; `SKILL.md` stays focused and under 500 lines
- [ ] Eval suite added or updated under `testing/`
- [ ] `skills/OWNERS.yaml` updated if adding a skill
