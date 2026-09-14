#!/usr/bin/env bash
#
# Validate every skill in skills/ against the Agent Skills specification and this
# repository's house conventions.
#
# Specification checks (https://agentskills.io/specification):
#   - SKILL.md exists and opens with a YAML frontmatter block
#   - frontmatter contains only allowed keys:
#       name, description, license, allowed-tools, compatibility, metadata
#   - name and description are present and non-empty
#   - name is kebab-case, <= 64 chars, no leading/trailing/double hyphen
#   - name does not contain the reserved words "anthropic" or "claude"
#   - name matches the containing directory
#   - description <= 1024 characters and contains no angle brackets
#   - compatibility <= 500 characters
#   - exactly one SKILL.md per skill (no nested SKILL.md files)
#
# House checks:
#   - license is present and is Apache-2.0
#   - SKILL.md size: warn > 500 lines, fail > 800 lines
#   - references/ is one level deep and never empty when present
#   - every references/*.md is linked from SKILL.md
#   - no backslash paths in markdown links
#   - no personal repository references or MIT licensing language in the skill
#
# Exit code: 0 = pass, 1 = one or more failures.
# Directories beginning with "_" (e.g. _template) are skipped.

set -uo pipefail

# Portability note: this script deliberately uses no `find` and no `sort`.
# On Windows, a bash launched without -l inherits the Windows PATH, where
# C:\Windows\System32\find.exe and sort.exe shadow the GNU tools. Windows'
# find.exe does not understand these arguments and blocks reading stdin, so
# the script would hang rather than fail. Shell globbing has no such problem.
shopt -s nullglob
if ((BASH_VERSINFO[0] >= 4)); then
  shopt -s globstar
  HAVE_GLOBSTAR=1
else
  HAVE_GLOBSTAR=0
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="${1:-$REPO_ROOT/skills}"

ALLOWED_KEYS="name description license allowed-tools compatibility metadata"
# Personal REPOSITORY references and personal licensing. A bare GitHub handle is
# not banned -- skills/OWNERS.yaml legitimately names maintainers by handle.
# The original author's personal repositories and licensing, from before this
# collection was donated. Names are matched as repository paths rather than as
# bare handles, so skills/OWNERS.yaml can still name maintainers by handle.
BANNED_PATTERN='celticht32/|github.com/celticht32|license: MIT|MIT License|Copyright \(c\) [0-9]{4} [A-Z]'

fail=0
warn=0
count=0

say_fail() { echo "FAIL [$1] $2"; fail=$((fail + 1)); }
say_warn() { echo "WARN [$1] $2"; warn=$((warn + 1)); }

if [[ ! -d "$SKILLS_DIR" ]]; then
  echo "No skills/ directory found at $SKILLS_DIR"
  exit 0
fi

for skill_md in "$SKILLS_DIR"/*/SKILL.md; do
  [[ -e "$skill_md" ]] || continue
  skill_path="$(dirname "$skill_md")"
  dir="$(basename "$skill_path")"
  case "$dir" in _*) continue ;; esac
  count=$((count + 1))

  # --- frontmatter present -------------------------------------------------
  if [[ "$(head -n 1 "$skill_md")" != "---" ]]; then
    say_fail "$dir" "missing YAML frontmatter (must start with '---')"
    continue
  fi

  frontmatter="$(awk 'NR>1 && /^---[[:space:]]*$/{exit} NR>1{print}' "$skill_md")"

  # --- allowed keys only ---------------------------------------------------
  while IFS= read -r key; do
    [[ -n "$key" ]] || continue
    if [[ " $ALLOWED_KEYS " != *" $key "* ]]; then
      say_fail "$dir" "frontmatter key '$key' is not in the Agent Skills specification (allowed: $ALLOWED_KEYS)"
    fi
  done < <(printf '%s\n' "$frontmatter" | grep -E '^[A-Za-z][A-Za-z0-9_-]*:' | sed 's/:.*//')

  # --- name ----------------------------------------------------------------
  name_val="$(printf '%s\n' "$frontmatter" | sed -n 's/^name:[[:space:]]*//p' | head -n 1 | tr -d '"'"'" | xargs || true)"
  if [[ -z "$name_val" ]]; then
    say_fail "$dir" "frontmatter missing 'name'"
  else
    [[ "$name_val" == "$dir" ]] || say_fail "$dir" "frontmatter name '$name_val' does not match directory"
    [[ ${#name_val} -le 64 ]] || say_fail "$dir" "name is ${#name_val} characters (max 64)"
    [[ "$name_val" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || say_fail "$dir" "name '$name_val' is not kebab-case (lowercase, digits, single hyphens, no leading/trailing hyphen)"
    case "$name_val" in
      *anthropic*|*claude*) say_fail "$dir" "name '$name_val' contains a reserved word (anthropic, claude)" ;;
    esac
  fi

  # --- description ---------------------------------------------------------
  if ! printf '%s\n' "$frontmatter" | grep -qE '^description:'; then
    say_fail "$dir" "frontmatter missing 'description'"
  else
    desc="$(printf '%s\n' "$frontmatter" | awk '
      /^description:/ {capture=1; sub(/^description:[[:space:]]*/, ""); print; next}
      capture && /^[A-Za-z][A-Za-z0-9_-]*:/ {capture=0}
      capture {print}
    ' | sed 's/^[[:space:]]*[>|][-+]*[[:space:]]*$//' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr '\n' ' ')"
    desc_len=${#desc}
    if (( desc_len > 1024 )); then
      say_fail "$dir" "description is $desc_len characters (max 1024)"
    fi
    if [[ "$desc" == *"<"* || "$desc" == *">"* ]]; then
      say_fail "$dir" "description contains angle brackets, which the specification forbids"
    fi
  fi

  # --- compatibility -------------------------------------------------------
  compat="$(printf '%s\n' "$frontmatter" | sed -n 's/^compatibility:[[:space:]]*//p' | head -n 1 || true)"
  if [[ -n "$compat" && ${#compat} -gt 500 ]]; then
    say_fail "$dir" "compatibility is ${#compat} characters (max 500)"
  fi

  # --- license -------------------------------------------------------------
  license_val="$(printf '%s\n' "$frontmatter" | sed -n 's/^license:[[:space:]]*//p' | head -n 1 | tr -d '"'"'" | xargs || true)"
  if [[ -z "$license_val" ]]; then
    say_fail "$dir" "frontmatter missing 'license'"
  elif [[ "$license_val" != "Apache-2.0" ]]; then
    say_fail "$dir" "license is '$license_val'; this repository is Apache-2.0"
  fi

  # --- size ----------------------------------------------------------------
  lines="$(wc -l < "$skill_md" | xargs)"
  if (( lines > 800 )); then
    say_fail "$dir" "SKILL.md is $lines lines (>800)"
  elif (( lines > 500 )); then
    say_warn "$dir" "SKILL.md is $lines lines (>500) — move depth into references/"
  fi

  # --- exactly one SKILL.md ------------------------------------------------
  if (( HAVE_GLOBSTAR )); then
    nested=0
    for candidate in "$skill_path"/**/SKILL.md; do
      [[ "$candidate" == "$skill_md" ]] || nested=$((nested + 1))
    done
    if (( nested > 0 )); then
      say_fail "$dir" "found $nested nested SKILL.md file(s); a skill must contain exactly one"
    fi
  fi

  # --- references ----------------------------------------------------------
  if [[ -d "$skill_path/references" ]]; then
    ref_count=0
    for ref in "$skill_path"/references/*.md; do
      ref_count=$((ref_count + 1))
    done
    if (( ref_count == 0 )); then
      say_fail "$dir" "references/ exists but contains no .md files — remove the empty directory"
    fi
    if (( HAVE_GLOBSTAR )); then
      deep=0
      for nested_ref in "$skill_path"/references/*/**/*.md "$skill_path"/references/*/*.md; do
        deep=$((deep + 1))
      done
      if (( deep > 0 )); then
        say_fail "$dir" "references/ must be one level deep; found $deep nested file(s)"
      fi
    fi
    for ref in "$skill_path"/references/*.md; do
      [[ -e "$ref" ]] || continue
      ref_name="$(basename "$ref")"
      grep -q "references/$ref_name" "$skill_md" || \
        say_fail "$dir" "references/$ref_name is not linked from SKILL.md"
    done
  fi

  # --- paths ---------------------------------------------------------------
  if grep -qE '\]\([^)]*\\[^)]*\)' "$skill_md"; then
    say_fail "$dir" "SKILL.md contains a backslash path in a markdown link; use forward slashes"
  fi

  # --- branding ------------------------------------------------------------
  if grep -rIqE "$BANNED_PATTERN" "$skill_path"; then
    offenders="$(grep -rIlE "$BANNED_PATTERN" "$skill_path" | sed "s|$REPO_ROOT/||" | tr '\n' ' ')"
    say_fail "$dir" "personal branding or MIT licensing language found in: $offenders"
  fi
done

# Finding nothing is a failure, not a pass. Skills resolve exactly one level
# under skills/; a grouped tree (skills/<group>/<name>/SKILL.md) matches the
# glob zero times, and without this check the run would report success while
# validating nothing at all.
if (( count == 0 )); then
  echo "FAIL no skills found under $SKILLS_DIR"
  echo "     Each skill must be at skills/<skill-name>/SKILL.md, one level down."
  echo "     A grouped tree such as skills/<group>/<skill-name>/SKILL.md is not discovered."
  exit 1
fi

echo "Validated $count skill(s): $fail failure(s), $warn warning(s)."
[[ $fail -eq 0 ]] || exit 1
