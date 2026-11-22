#!/usr/bin/env python3
"""Validate the packaging manifests and cross-file consistency.

Checks:
  - every manifest is valid JSON
  - .claude-plugin/marketplace.json has name, owner.name, and a plugins array
  - each plugin manifest has name, version, license, and points at ./skills/
  - the Claude, Codex and Cursor plugin manifests agree on name, version and license
  - mcp.json and gemini-extension.json declare a couchbase MCP server
  - the MCP server is configured read-only by default
  - skills/OWNERS.yaml has exactly one entry per skill, no duplicates and no
    orphans, and every entry has one or two DRI handles, an ISO last_reviewed
    date that is not in the future, and a positive review_cadence_days
  - README.md lists every skill directory, and lists no skill that does not exist

Run with --self-test to exercise the OWNERS.yaml checks on fixtures.

Exit codes: 0 pass, 1 one or more failures.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)


def load_json(relative: str) -> dict | None:
    path = REPO_ROOT / relative
    if not path.is_file():
        fail(f"{relative}: missing")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{relative}: invalid JSON: {exc}")
        return None


def skill_dirs() -> set[str]:
    return {p.parent.name for p in (REPO_ROOT / "skills").glob("*/SKILL.md")}


def check_marketplace() -> None:
    data = load_json(".claude-plugin/marketplace.json")
    if data is None:
        return
    if not data.get("name"):
        fail(".claude-plugin/marketplace.json: missing 'name'")
    elif not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", data["name"]):
        fail(f".claude-plugin/marketplace.json: name '{data['name']}' is not kebab-case")
    owner = data.get("owner")
    if not isinstance(owner, dict) or not owner.get("name"):
        fail(".claude-plugin/marketplace.json: 'owner' must be an object with a 'name'")
    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        fail(".claude-plugin/marketplace.json: 'plugins' must be a non-empty array")
        return
    for entry in plugins:
        if not entry.get("name") or not entry.get("source"):
            fail(".claude-plugin/marketplace.json: every plugin needs 'name' and 'source'")


def check_plugins() -> None:
    manifests = {
        harness: load_json(f".{harness}-plugin/plugin.json")
        for harness in ("claude", "codex", "cursor")
    }
    identities = {}
    for harness, data in manifests.items():
        if data is None:
            continue
        path = f".{harness}-plugin/plugin.json"
        for field in ("name", "version", "license", "description"):
            if not data.get(field):
                fail(f"{path}: missing '{field}'")
        if data.get("license") != "Apache-2.0":
            fail(f"{path}: license is '{data.get('license')}'; this repository is Apache-2.0")
        if data.get("skills") != "./skills/":
            fail(f"{path}: 'skills' must be './skills/'")
        if data.get("mcpServers") != "./mcp.json":
            fail(f"{path}: 'mcpServers' must be './mcp.json'")
        identities[harness] = (data.get("name"), data.get("version"), data.get("license"))

    if len(set(identities.values())) > 1:
        fail(f"plugin manifests disagree on name/version/license: {identities}")

    gemini = load_json("gemini-extension.json")
    if gemini is not None and identities:
        expected = next(iter(identities.values()))[1]
        if gemini.get("version") != expected:
            fail(
                f"gemini-extension.json: version {gemini.get('version')!r} does not match "
                f"the plugin manifests ({expected!r})"
            )


def check_mcp_config() -> None:
    for relative in ("mcp.json", "gemini-extension.json"):
        data = load_json(relative)
        if data is None:
            continue
        servers = data.get("mcpServers")
        if not isinstance(servers, dict) or "couchbase" not in servers:
            fail(f"{relative}: must declare an 'mcpServers.couchbase' entry")
            continue
        env = servers["couchbase"].get("env", {})
        read_only = str(env.get("CB_MCP_READ_ONLY_MODE", ""))
        if "true" not in read_only:
            fail(
                f"{relative}: CB_MCP_READ_ONLY_MODE must default to true "
                f"(found {read_only!r})"
            )


OWNER_HANDLE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")


def parse_owners(text: str) -> list[dict[str, str]]:
    """Parse the flat entry list in skills/OWNERS.yaml without PyYAML.

    Each entry opens with ``- name: <skill>`` and is followed by indented
    ``key: value`` lines. Values are returned as raw strings, with trailing
    ``# comments`` and surrounding quotes removed.
    """
    entries: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        match = re.match(r"^\s*(-\s+)?([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not match or not line.startswith(" "):
            continue  # comments, blank lines and the top-level "skills:" key
        is_new, key, value = match.groups()
        if is_new:
            entries.append({})
        if entries:
            entries[-1][key] = value.strip().strip('"\'')
    return entries


def owners_problems(text: str, present: set[str], today: date) -> list[str]:
    """Return every way OWNERS.yaml breaks its documented contract.

    One entry per skill directory, no duplicates or orphans, one or two DRI
    handles, an ISO last_reviewed date that is not in the future, and a
    positive integer review_cadence_days.
    """
    problems: list[str] = []
    entries = parse_owners(text)
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        name = entry.get("name", "")
        label = f"entry '{name}'" if name else f"entry #{index}"
        if not name:
            problems.append(f"{label} has no 'name'")
        elif name in seen:
            problems.append(f"{label} is listed more than once")
        seen.add(name)

        dris_raw = entry.get("dris", "")
        dris = [d.strip().strip("\"'") for d in dris_raw.strip("[]").split(",") if d.strip()]
        if not dris_raw.startswith("[") or not 1 <= len(dris) <= 2:
            problems.append(f"{label}: 'dris' must be a list of one or two GitHub usernames")
        for handle in dris:
            if not OWNER_HANDLE.fullmatch(handle):
                problems.append(f"{label}: DRI '{handle}' is not a GitHub username (no leading @)")

        reviewed = entry.get("last_reviewed", "")
        try:
            reviewed_on = date.fromisoformat(reviewed)
        except ValueError:
            problems.append(f"{label}: 'last_reviewed' {reviewed!r} is not a YYYY-MM-DD date")
        else:
            if reviewed_on > today:
                problems.append(f"{label}: 'last_reviewed' {reviewed} is in the future")

        cadence = entry.get("review_cadence_days", "")
        if not cadence.isdigit() or int(cadence) == 0:
            problems.append(f"{label}: 'review_cadence_days' {cadence!r} must be a positive integer")

    for name in sorted(present - seen):
        problems.append(f"no entry for skills/{name}")
    for name in sorted(seen - present - {""}):
        problems.append(f"entry '{name}' has no matching skill directory")
    return problems


def check_owners() -> None:
    path = REPO_ROOT / "skills" / "OWNERS.yaml"
    if not path.is_file():
        fail("skills/OWNERS.yaml: missing")
        return
    text = path.read_text(encoding="utf-8")
    for problem in owners_problems(text, skill_dirs(), date.today()):
        fail(f"skills/OWNERS.yaml: {problem}")


def check_readme() -> None:
    path = REPO_ROOT / "README.md"
    if not path.is_file():
        fail("README.md: missing")
        return
    text = path.read_text(encoding="utf-8")
    present = skill_dirs()
    for name in sorted(present):
        if name not in text:
            fail(f"README.md: does not mention skills/{name}")
    # Reverse direction: a README row for a skill nobody can install is worse
    # than a missing row, because it advertises something that does not exist.
    #
    # Only real markdown links count. Fenced blocks and inline code are
    # excluded, because the migration note deliberately shows the old
    # pre-flattening paths as illustrations of what to change.
    prose = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    prose = re.sub(r"`[^`]*`", "", prose)
    linked = set(re.findall(r"\]\(skills/([a-z0-9][a-z0-9-]*)/", prose))
    for name in sorted(linked - present):
        fail(f"README.md: links skills/{name}, which does not exist")


OWNERS_GOOD = """skills:
  - name: alpha
    dris: [someone, other-one]  # interim
    last_reviewed: "2026-01-02"
    review_cadence_days: 90
  - name: beta
    dris: [someone]
    last_reviewed: "2026-01-02"
    review_cadence_days: 30
"""

# (label, OWNERS.yaml text, substring the problem list must contain or None)
OWNERS_FIXTURES = [
    ("valid file", OWNERS_GOOD, None),
    ("duplicate entry", OWNERS_GOOD + OWNERS_GOOD.split("\n", 1)[1], "listed more than once"),
    ("missing skill", OWNERS_GOOD.split("  - name: beta")[0], "no entry for skills/beta"),
    ("orphan entry", OWNERS_GOOD.replace("name: beta", "name: gamma"), "no matching skill directory"),
    ("no DRI", OWNERS_GOOD.replace("[someone]", "[]"), "one or two GitHub usernames"),
    ("three DRIs", OWNERS_GOOD.replace("[someone]", "[a, b, c]"), "one or two GitHub usernames"),
    ("@-prefixed DRI", OWNERS_GOOD.replace("[someone]", "[@someone]"), "is not a GitHub username"),
    ("bad date", OWNERS_GOOD.replace('"2026-01-02"\n    review_cadence_days: 30', '"14/09/2026"\n    review_cadence_days: 30'), "not a YYYY-MM-DD date"),
    ("future date", OWNERS_GOOD.replace("2026-01-02", "2027-01-01", 1), "is in the future"),
    ("zero cadence", OWNERS_GOOD.replace("review_cadence_days: 30", "review_cadence_days: 0"), "positive integer"),
    ("missing cadence", OWNERS_GOOD.replace("    review_cadence_days: 30\n", ""), "positive integer"),
]


def self_test() -> int:
    failures_seen = 0
    today = date(2026, 6, 1)
    for label, text, want in OWNERS_FIXTURES:
        problems = owners_problems(text, {"alpha", "beta"}, today)
        if want is None:
            ok = not problems
        else:
            ok = any(want in problem for problem in problems)
        failures_seen += not ok
        print(f"{'ok  ' if ok else 'FAIL'} owners: {label}" + ("" if ok else f" -> {problems}"))
    print(f"\nSelf-test: {len(OWNERS_FIXTURES)} check(s), {failures_seen} failure(s).")
    return 1 if failures_seen else 0


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    check_marketplace()
    check_plugins()
    check_mcp_config()
    check_owners()
    check_readme()

    for message in failures:
        print(f"FAIL {message}")
    print(f"Manifest validation: {len(failures)} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
