#!/usr/bin/env python3
"""Validate every markdown link in the repository.

Two classes of link break silently and are easy to reintroduce:

  - a relative file link to a path that does not exist
  - an in-file anchor (#something) that matches no heading in that file

The second is the common one. GitHub's slugifier strips punctuation and turns
each remaining space into a hyphen, so a heading containing an em dash, an
arrow, a slash or a "+" produces a DOUBLE hyphen where an author naturally
writes one: "## Code pattern - Python" slugifies to "code-pattern--python".
A table of contents written by hand gets this wrong most times it comes up.

Checks:
  - every relative file link resolves to an existing file
  - every in-file anchor matches a heading in the same file
  - fenced code blocks and YAML frontmatter are excluded from both

Exit codes: 0 pass, 1 one or more failures.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
INLINE_CODE = re.compile(r"`[^`]*`")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}


def strip_fences(text: str) -> str:
    """Blank out fenced code blocks and YAML frontmatter, preserving line count."""
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    start = 0
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                out = [""] * (index + 1)
                start = index + 1
                break
    for line in lines[start:]:
        if FENCE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def slugify(heading: str) -> str:
    """GitHub's heading-to-anchor rule."""
    text = heading.strip()
    text = re.sub(r"`([^`]*)`", r"\1", text)          # inline code contributes its text
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links contribute their label
    # Emphasis markers vanish, but only as paired markup. A blanket strip of "_"
    # would eat the underscores in identifiers like changes_left and USE_HASH,
    # which GitHub keeps.
    for pattern in (r"\*\*(.+?)\*\*", r"__(.+?)__", r"\*(.+?)\*", r"~~(.+?)~~"):
        text = re.sub(pattern, r"\1", text)
    text = text.lower()
    text = re.sub(r"[^\w\- ]", "", text)               # everything else punctuation goes
    return text.replace(" ", "-")


def anchors_for(text: str) -> set[str]:
    """Every anchor the file exposes, including GitHub's -1/-2 duplicate suffixes."""
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    for line in strip_fences(text).split("\n"):
        match = HEADING.match(line)
        if not match:
            continue
        slug = slugify(match.group(2))
        if not slug:
            continue
        count = seen.get(slug, 0)
        anchors.add(slug if count == 0 else f"{slug}-{count}")
        seen[slug] = count + 1
    return anchors


def main() -> int:
    failures: list[str] = []
    checked_files = 0
    checked_links = 0

    for path in sorted(REPO_ROOT.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        checked_files += 1
        raw = path.read_text(encoding="utf-8")
        body = INLINE_CODE.sub("", strip_fences(raw))
        anchors = anchors_for(raw)
        relative = path.relative_to(REPO_ROOT)

        for line_number, line in enumerate(body.split("\n"), start=1):
            for target in LINK.findall(line):
                if target.startswith(("http://", "https://", "mailto:", "tel:")):
                    continue
                checked_links += 1

                file_part, _, anchor = target.partition("#")

                if not file_part:
                    if anchor and anchor not in anchors:
                        failures.append(
                            f"{relative}:{line_number}: anchor #{anchor} matches no heading "
                            f"in this file"
                        )
                    continue

                resolved = (path.parent / file_part).resolve()
                if not resolved.exists():
                    failures.append(f"{relative}:{line_number}: {file_part} does not exist")
                    continue

                if anchor and resolved.suffix == ".md":
                    target_anchors = anchors_for(resolved.read_text(encoding="utf-8"))
                    if anchor not in target_anchors:
                        failures.append(
                            f"{relative}:{line_number}: anchor #{anchor} matches no heading "
                            f"in {file_part}"
                        )

    for message in failures:
        print(f"FAIL {message}")
    print(
        f"Checked {checked_links} link(s) across {checked_files} file(s): "
        f"{len(failures)} failure(s)."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
