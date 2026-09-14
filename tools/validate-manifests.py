#!/usr/bin/env python3
"""Validate the packaging manifests and cross-file consistency.

Checks:
  - every manifest is valid JSON
  - .claude-plugin/marketplace.json has name, owner.name, and a plugins array
  - each plugin manifest has name, version, license, and points at ./skills/
  - the Claude, Codex and Cursor plugin manifests agree on name, version and license
  - mcp.json and gemini-extension.json declare a couchbase MCP server
  - the MCP server is configured read-only by default
  - skills/OWNERS.yaml has exactly one entry per skill, and no orphans
  - README.md lists every skill directory, and lists no skill that does not exist

Exit codes: 0 pass, 1 one or more failures.
"""

from __future__ import annotations

import json
import re
import sys
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


def check_owners() -> None:
    path = REPO_ROOT / "skills" / "OWNERS.yaml"
    if not path.is_file():
        fail("skills/OWNERS.yaml: missing")
        return
    text = path.read_text(encoding="utf-8")
    listed = set(re.findall(r"^\s*-\s*name:\s*(\S+)", text, re.MULTILINE))
    present = skill_dirs()
    for name in sorted(present - listed):
        fail(f"skills/OWNERS.yaml: no entry for skills/{name}")
    for name in sorted(listed - present):
        fail(f"skills/OWNERS.yaml: entry '{name}' has no matching skill directory")


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
    for name in sorted(set(re.findall(r"skills/([a-z0-9][a-z0-9-]*)/", text)) - present):
        fail(f"README.md: links skills/{name}, which does not exist")


def main() -> int:
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
