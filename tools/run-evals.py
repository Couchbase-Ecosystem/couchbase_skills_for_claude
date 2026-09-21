#!/usr/bin/env python3
"""Validate and run the skill eval suites under testing/.

Three modes:

    python3 tools/run-evals.py --dry-run
        Schema validation only. Free, deterministic, no API key, no network.
        This is what CI runs on every pull request.

    python3 tools/run-evals.py --self-test
        Exercises the grader against built-in fixtures. Free, no network.
        Run it after changing grading logic.

    python3 tools/run-evals.py --execute
        Runs every case against a model and grades it. Costs money (a full pass
        is roughly 2M input tokens) and needs ANTHROPIC_API_KEY. Deliberately
        NOT wired into CI: run it by hand when you want it.

Execution model: each case is one stateless request. The skill under test is
injected as the system prompt (its SKILL.md body, with any reference file the
body links to appended), and the case's `input` is sent as the user turn. That
approximates a host that has loaded the skill, without needing a plugin host.

Grading is substring matching, case-insensitive, over the model's text output:

    pass  =  at least `threshold` of the `expect` strings appear
             AND none of the `reject` strings appear

`threshold` defaults to the full length of `expect`. Substring grading is blunt
on purpose — it is cheap, deterministic and reviewable. Its limit is that it
cannot tell a correct statement from its negation, which is why a `reject`
string must be one that only a wrong answer produces; see testing/README.md.
--dry-run enforces this mechanically: a `reject` string that appears in the
loaded skill's own corpus is a schema failure, because the skill teaches that
vocabulary and a correct answer would emit it.

Suite layout:

    testing/<skill-name>/evals/evals.json

Schema:

    {
      "skill": "<skill-name>",            # must equal the directory name
      "cases": [
        {
          "name": "kebab-case-name",      # unique within the suite
          "input": "the user prompt",
          "expect": ["..."],              # substrings the answer must contain
          "reject": ["..."],              # substrings the answer must not contain
          "threshold": 2,                 # optional; int, 1 <= threshold <= len(expect)
          "tier": "smoke",                # optional; smoke | standard | deep
          "expect_skill": "<skill-name>"  # optional; the skill that should trigger
        }
      ]
    }

Exit codes: 0 pass, 1 schema or grading failure, 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTING_DIR = REPO_ROOT / "testing"
SKILLS_DIR = REPO_ROOT / "skills"

VALID_TIERS = ("smoke", "standard", "deep")
CASE_KEYS = {
    "name",
    "input",
    "expect",
    "reject",
    "threshold",
    "tier",
    "expect_skill",
}

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 2048

SYSTEM_PREAMBLE = (
    "You are a Couchbase expert assistant. The following skill has been loaded "
    "into your context. Follow it. Answer the user's question directly and "
    "concretely, naming the specific versions, limits, tool names and "
    "identifiers the skill gives you rather than speaking in generalities.\n\n"
)


# --------------------------------------------------------------------------
# Schema validation
# --------------------------------------------------------------------------


def discover_suites() -> list[Path]:
    if not TESTING_DIR.is_dir():
        return []
    return sorted(TESTING_DIR.glob("*/evals/evals.json"))


def known_skills() -> set[str]:
    if not SKILLS_DIR.is_dir():
        return set()
    return {p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md")}


def load_corpus(skill_name: str) -> str | None:
    """The skill's loaded corpus, lowercased, or None if it cannot be read.

    This is exactly what --execute injects as the system prompt, so a string
    found here is a string the model is being handed. Offline: it only reads
    files under skills/.
    """
    if not (SKILLS_DIR / skill_name / "SKILL.md").is_file():
        return None
    try:
        return build_system_prompt(skill_name).lower()
    except OSError:
        return None


def validate_suite(path: Path, skills: set[str]) -> list[str]:
    """Return a list of error strings for one suite. Empty list means valid."""
    errors: list[str] = []
    suite_dir = path.parent.parent.name

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON: {exc}"]
    except OSError as exc:
        return [f"{path}: could not be read: {exc}"]

    if not isinstance(data, dict):
        return [f"{path}: top level must be an object"]

    skill = data.get("skill")
    if not skill:
        errors.append(f"{path}: missing 'skill'")
    elif skill != suite_dir:
        errors.append(f"{path}: skill '{skill}' does not match directory '{suite_dir}'")
    elif skills and skill not in skills:
        errors.append(f"{path}: skill '{skill}' has no matching skills/{skill}/SKILL.md")

    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append(f"{path}: 'cases' must be a non-empty array")
        return errors

    # A `reject` string that appears in the skill's own loaded corpus is
    # self-defeating: the skill teaches that vocabulary, so a *correct* answer
    # is likely to emit it and fail the case. Checked mechanically here so it
    # cannot be reintroduced silently. See testing/README.md.
    corpus = load_corpus(skill) if isinstance(skill, str) and skill else None

    seen: set[str] = set()
    for index, case in enumerate(cases):
        where = f"{path}: case {index}"
        if not isinstance(case, dict):
            errors.append(f"{where}: must be an object")
            continue

        name = case.get("name")
        if not name:
            errors.append(f"{where}: missing 'name'")
        else:
            where = f"{path}: case '{name}'"
            if name in seen:
                errors.append(f"{where}: duplicate case name")
            seen.add(name)

        unknown = set(case) - CASE_KEYS
        if unknown:
            errors.append(f"{where}: unknown key(s): {', '.join(sorted(unknown))}")

        user_input = case.get("input")
        if not user_input:
            errors.append(f"{where}: missing 'input'")
        elif not isinstance(user_input, str):
            errors.append(f"{where}: 'input' must be a string")

        if name and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", str(name)):
            errors.append(f"{where}: name must be kebab-case")

        expect = case.get("expect")
        if not isinstance(expect, list) or not expect:
            errors.append(f"{where}: 'expect' must be a non-empty array")
            expect = []
        elif not all(isinstance(item, str) and item for item in expect):
            errors.append(f"{where}: every 'expect' entry must be a non-empty string")

        reject = case.get("reject")
        if reject is None:
            errors.append(f"{where}: missing 'reject' (use [] if there is nothing to reject)")
        elif not isinstance(reject, list):
            errors.append(f"{where}: 'reject' must be an array")
        elif not all(isinstance(item, str) and item for item in reject):
            # An empty string is a substring of every answer, so it would fail
            # every case in the suite at grading time with no schema warning.
            errors.append(f"{where}: every 'reject' entry must be a non-empty string")
        elif corpus is not None:
            for item in reject:
                if item.lower() in corpus:
                    errors.append(
                        f"{where}: reject string {item!r} appears in the loaded "
                        f"corpus of skill '{skill}' — a correct answer would use it. "
                        f"Assert routing in 'expect' (the sibling skill's name and "
                        f"handoff wording) instead."
                    )

        if "threshold" in case:
            threshold = case["threshold"]
            if not isinstance(threshold, int) or isinstance(threshold, bool):
                errors.append(f"{where}: 'threshold' must be an integer")
            elif threshold < 1:
                errors.append(f"{where}: 'threshold' must be at least 1")
            elif expect and threshold > len(expect):
                errors.append(
                    f"{where}: threshold {threshold} exceeds the {len(expect)} 'expect' entries"
                )

        tier = case.get("tier")
        if tier is not None and tier not in VALID_TIERS:
            errors.append(f"{where}: tier '{tier}' must be one of {list(VALID_TIERS)}")

        target = case.get("expect_skill")
        if target and skills and target not in skills:
            errors.append(f"{where}: expect_skill '{target}' names no skill in skills/")

    return errors


def cmd_dry_run(quiet: bool = False) -> int:
    suites = discover_suites()
    if not suites:
        # Finding nothing is a failure, not a pass: a moved or regrouped tree
        # would otherwise report success while validating nothing.
        print("FAIL no eval suites found under testing/*/evals/evals.json")
        return 1

    skills = known_skills()
    all_errors: list[str] = []
    total_cases = 0

    for suite in suites:
        errors = validate_suite(suite, skills)
        all_errors.extend(errors)
        if not errors:
            total_cases += len(json.loads(suite.read_text(encoding="utf-8"))["cases"])

    for error in all_errors:
        print(f"FAIL {error}")

    covered = {s.parent.parent.name for s in suites}
    missing = sorted(skills - covered)
    for name in missing:
        print(f"WARN skills/{name} has no eval suite at testing/{name}/evals/evals.json")

    if not quiet:
        print(
            f"Validated {len(suites)} suite(s), {total_cases} case(s): "
            f"{len(all_errors)} failure(s), {len(missing)} skill(s) without a suite."
        )
    return 1 if all_errors else 0


# --------------------------------------------------------------------------
# Grading
# --------------------------------------------------------------------------


def grade(answer: str, case: dict) -> tuple[bool, dict]:
    """Grade one answer. Returns (passed, detail)."""
    haystack = answer.lower()
    expect = case.get("expect", [])
    reject = case.get("reject", []) or []
    threshold = case.get("threshold", len(expect))

    matched = [s for s in expect if s.lower() in haystack]
    missed = [s for s in expect if s.lower() not in haystack]
    violated = [s for s in reject if s.lower() in haystack]

    passed = len(matched) >= threshold and not violated
    return passed, {
        "matched": matched,
        "missed": missed,
        "violated": violated,
        "threshold": threshold,
        "expect_count": len(expect),
    }


def build_system_prompt(skill_name: str) -> str:
    """SKILL.md body plus every reference file it links to."""
    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)

    parts = [SYSTEM_PREAMBLE, f"# Skill: {skill_name}\n\n{body}"]
    refs_dir = skill_md.parent / "references"
    if refs_dir.is_dir():
        for ref in sorted(refs_dir.glob("*.md")):
            if f"references/{ref.name}" in body:
                parts.append(
                    f"\n\n---\n# Reference: references/{ref.name}\n\n"
                    + ref.read_text(encoding="utf-8")
                )
    return "".join(parts)


TRANSIENT = ("rate_limit", "overloaded", "timeout", "connection", "api_error", "529", "500", "502", "503")


def is_transient(exc: Exception) -> bool:
    """Retry only what retrying can fix. A 401 or a bad model name never resolves."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    return any(token in f"{type(exc).__name__} {exc}".lower() for token in TRANSIENT)


def ask_model(client, model: str, system: str, prompt: str) -> str:
    """One stateless request. Retries transient failures with a backoff."""
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=DEFAULT_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(
                block.text for block in response.content if block.type == "text"
            )
        except Exception as exc:  # noqa: BLE001 - the SDK raises several types
            last_error = exc
            if attempt == 3 or not is_transient(exc):
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"model call failed: {last_error}")


def cmd_execute(args: argparse.Namespace) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; --execute cannot run.", file=sys.stderr)
        return 2

    try:
        import anthropic
    except ImportError:
        print(
            "The anthropic package is not installed. Install it with:\n"
            "    pip install anthropic",
            file=sys.stderr,
        )
        return 2

    if cmd_dry_run(quiet=True) != 0:
        print("Schema validation failed; refusing to spend API calls.", file=sys.stderr)
        return 1

    client = anthropic.Anthropic()
    suites = discover_suites()
    if args.skill:
        suites = [s for s in suites if s.parent.parent.name in args.skill]
        if not suites:
            print(f"No suite matches {args.skill}", file=sys.stderr)
            return 2

    results: list[dict] = []
    failures = 0
    ran = 0

    for suite in suites:
        data = json.loads(suite.read_text(encoding="utf-8"))
        skill = data["skill"]
        system = build_system_prompt(skill)

        for case in data["cases"]:
            if args.tier and case.get("tier") != args.tier:
                continue
            ran += 1
            try:
                answer = ask_model(client, args.model, system, case["input"])
            except RuntimeError as exc:
                print(f"ERROR {skill}/{case['name']}: {exc}", file=sys.stderr)
                failures += 1
                results.append(
                    {"skill": skill, "case": case["name"], "passed": False, "error": str(exc)}
                )
                continue

            passed, detail = grade(answer, case)
            if not passed:
                failures += 1
            status = "PASS" if passed else "FAIL"
            print(f"{status} {skill}/{case['name']}")
            if not passed:
                if detail["violated"]:
                    print(f"       rejected string(s) present: {detail['violated']}")
                if len(detail["matched"]) < detail["threshold"]:
                    print(
                        f"       matched {len(detail['matched'])}/{detail['threshold']} "
                        f"required; missing: {detail['missed']}"
                    )
            results.append(
                {
                    "skill": skill,
                    "case": case["name"],
                    "tier": case.get("tier"),
                    "passed": passed,
                    **detail,
                    "answer": answer if args.save_answers else None,
                }
            )

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {"model": args.model, "ran": ran, "failed": failures, "results": results},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {args.json}")

    rate = (ran - failures) / ran * 100 if ran else 0.0
    print(f"\nRan {ran} case(s): {ran - failures} passed, {failures} failed ({rate:.0f}%).")

    if args.threshold is not None and ran:
        if rate / 100 < args.threshold:
            print(f"Pass rate {rate:.0f}% is below the --threshold of {args.threshold:.0%}.")
            return 1
        return 0
    return 1 if failures else 0


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------


FIXTURES = [
    (
        "all expect present, no reject",
        "The documented maximum is 250 bytes and it is a hard limit.",
        {"expect": ["250 bytes", "hard limit"], "reject": ["246 bytes"]},
        True,
    ),
    (
        "a rejected string appears",
        "The maximum key length is 246 bytes for a named collection.",
        {"expect": ["246 bytes"], "reject": ["246 bytes"]},
        False,
    ),
    (
        "threshold met by a subset",
        "Use ALL ARRAY for an UNNEST query.",
        {"expect": ["ALL ARRAY", "DISTINCT ARRAY", "UNNEST"], "reject": [], "threshold": 2},
        True,
    ),
    (
        "threshold not met",
        "Use an array index.",
        {"expect": ["ALL ARRAY", "DISTINCT ARRAY"], "reject": [], "threshold": 2},
        False,
    ),
    (
        "matching is case-insensitive",
        "the search service owns the svi.",
        {"expect": ["Search Service", "SVI"], "reject": []},
        True,
    ),
    (
        "empty reject list is legal",
        "Replicas do not serve ordinary reads.",
        {"expect": ["do not serve"], "reject": []},
        True,
    ),
    (
        "threshold defaults to the full expect list",
        "Only one of the two facts is here: external_stats_reader.",
        {"expect": ["external_stats_reader", "cluster_admin"], "reject": []},
        False,
    ),
]


def cmd_self_test() -> int:
    failures = 0
    for label, answer, case, want in FIXTURES:
        got, detail = grade(answer, case)
        ok = got == want
        if not ok:
            failures += 1
        print(f"{'ok  ' if ok else 'FAIL'} {label} (expected {want}, got {got}) {detail if not ok else ''}")

    # The in-corpus reject check must fire on a planted violation.
    checks = len(FIXTURES) + 1
    skills = sorted(known_skills())
    if skills:
        checks += 1
        victim = skills[0]
        corpus_words = re.findall(r"[A-Za-z_]{6,}", build_system_prompt(victim))
        planted = corpus_words[0] if corpus_words else victim
        suite = {
            "skill": victim,
            "cases": [
                {
                    "name": "planted-violation",
                    "input": "anything",
                    "expect": ["something"],
                    "reject": [planted],
                }
            ],
        }
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / victim / "evals" / "evals.json"
            fake.parent.mkdir(parents=True)
            fake.write_text(json.dumps(suite), encoding="utf-8")
            found = [e for e in validate_suite(fake, set(skills)) if "loaded corpus" in e]
        if found:
            print(f"ok   in-corpus reject check fires on planted {planted!r} in {victim}")
        else:
            print(f"FAIL in-corpus reject check did not fire on planted {planted!r}")
            failures += 1

    # The system-prompt builder must produce real content for a real skill.
    if skills:
        prompt = build_system_prompt(skills[0])
        if len(prompt) < 500 or "---\nname:" in prompt:
            print(f"FAIL build_system_prompt({skills[0]}) looks wrong ({len(prompt)} chars)")
            failures += 1
        else:
            print(f"ok   build_system_prompt({skills[0]}) -> {len(prompt)} chars, frontmatter stripped")

    print(f"\nSelf-test: {checks} check(s), {failures} failure(s).")
    return 1 if failures else 0


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="schema validation only")
    group.add_argument("--execute", action="store_true", help="run cases against a model")
    group.add_argument("--self-test", action="store_true", help="test the grader on fixtures")

    parser.add_argument("--skill", action="append", help="limit to this skill (repeatable)")
    parser.add_argument("--tier", choices=VALID_TIERS, help="limit to one tier")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"default: {DEFAULT_MODEL}")
    parser.add_argument("--json", help="write full results to this path")
    parser.add_argument(
        "--save-answers",
        action="store_true",
        help="include the model's full text in the --json output",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        help="pass-rate floor between 0 and 1; exit 0 if met even with some failures",
    )
    args = parser.parse_args()

    if args.dry_run:
        return cmd_dry_run()
    if args.self_test:
        return cmd_self_test()
    return cmd_execute(args)


if __name__ == "__main__":
    sys.exit(main())
