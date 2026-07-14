"""Docs-vs-code contract linter. Stdlib only. Exit 1 on any failure.

What keeps the SKILL.md layer honest permanently:
  1. Frontmatter: name == directory name; description present, <= 550 chars.
  2. Flag parity, both directions: every --flag a SKILL.md documents exists in
     one of that skill's scripts' argparse definitions, and every argparse
     flag is documented somewhere in the SKILL.md.
  3. State-file claims: every .seo-engine/... path a SKILL.md names must
     appear in that skill's script sources or in common-setup.md (the
     snapshot-store contract).
  4. Pointer resolution: ../seo-references/<file>.md links resolve lexically
     from the skill dir; every "<playbook> §N" mention (in SKILL.md AND in
     script sources) has a matching "## N." heading in the target file.
  5. Skeleton: H1 == skill name; the ten canonical headings, in order.
  6. Skill-name integrity: backticked seo-*/geo-* tokens refer to skills that
     actually exist.
  7. Lint: mojibake (SS4-style, U+FFFD), bare years in prose (dated facts
     belong in the references), 40+-word paragraphs duplicated across files.

Usage: python3 scripts/dev/check_docs.py  (from the engine root; CI runs it)
"""

from __future__ import annotations

import ast
import re
import sys
from hashlib import sha256
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = ENGINE_ROOT / "skills"
REFERENCES_DIR = SKILLS_DIR / "seo-references"

CANONICAL_HEADINGS = [
    "## When to use this skill",
    "## What it checks / does",
    "## Running it",
    "## Expected output",
    "## State files",
    "## How to interpret results",
    "## Safe to auto-apply vs. human review",
    "## Guardrails",
    "## References",
    "## Graceful degradation",
]

FLAG_ALLOWLIST = {"--help"}
YEAR_RE = re.compile(r"\b20\d{2}\b")
SECTION_REF_RE = re.compile(r"(geo-playbook|seo-playbook|red-flags)(?:\.md)?\s*§\s*(\d+)")
MOJIBAKE_RE = re.compile(r"\bSS\d|�")
BACKTICK_SKILL_RE = re.compile(r"`((?:seo|geo)-[a-z][a-z-]*)`")

errors: list[str] = []


def fail(path: Path, message: str) -> None:
    errors.append(f"{path.relative_to(ENGINE_ROOT)}: {message}")


def strip_fences(text: str) -> str:
    """Remove fenced code blocks and inline code (lint targets prose only)."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


def strip_urls(text: str) -> str:
    return re.sub(r"https?://\S+", "", text)


def parse_frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not m:
        return {}
    fields: dict[str, str] = {}
    current_key = None
    for line in m.group(1).splitlines():
        key_match = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if key_match:
            current_key = key_match.group(1)
            fields[current_key] = key_match.group(2).strip()
        elif current_key and line.startswith(" "):
            fields[current_key] += " " + line.strip()
    return fields


def argparse_flags(script: Path) -> set[str]:
    """All --flags defined via parser.add_argument in a script (AST-based)."""
    flags: set[str] = set()
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        fail(script, f"does not parse: {exc}")
        return flags
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("--"):
                    flags.add(arg.value)
    return flags


def documented_flags(text: str) -> set[str]:
    """--flags mentioned anywhere in a SKILL.md (code fences + inline code + prose)."""
    return set(re.findall(r"(--[a-z][a-z0-9-]+)", text))


def section_headings(ref_file: Path) -> set[str]:
    numbers = set()
    if not ref_file.is_file():
        return numbers
    for line in ref_file.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(\d+)\.", line)
        if m:
            numbers.add(m.group(1))
    return numbers


def check_section_refs(path: Path, text: str, sections: dict[str, set[str]]) -> None:
    for ref_name, number in SECTION_REF_RE.findall(text):
        if number not in sections[ref_name]:
            fail(path, f"points at {ref_name}.md §{number}, which has no '## {number}.' heading")


def main() -> int:
    skill_dirs = sorted(
        d for d in SKILLS_DIR.iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file() and d.name != "seo-references"
    )
    skill_names = {d.name for d in skill_dirs} | {"seo-references", "seo-engine"}

    sections = {
        "geo-playbook": section_headings(REFERENCES_DIR / "geo-playbook.md"),
        "seo-playbook": section_headings(REFERENCES_DIR / "seo-playbook.md"),
        "red-flags": section_headings(REFERENCES_DIR / "red-flags.md"),
    }
    common_setup_text = (REFERENCES_DIR / "common-setup.md").read_text(encoding="utf-8")

    paragraph_owners: dict[str, Path] = {}

    for skill_dir in skill_dirs:
        skill_md = skill_dir / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        prose = strip_urls(strip_fences(text))

        # 1. Frontmatter.
        fm = parse_frontmatter(text)
        if fm.get("name") != skill_dir.name:
            fail(skill_md, f"frontmatter name {fm.get('name')!r} != directory {skill_dir.name!r}")
        description = fm.get("description", "")
        if not description:
            fail(skill_md, "frontmatter has no description")
        elif len(description) > 550:
            fail(skill_md, f"description is {len(description)} chars (max 550)")

        # 5. Skeleton.
        body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
        first_heading = next((line for line in body.splitlines() if line.startswith("#")), "")
        if first_heading.strip() != f"# {skill_dir.name}":
            fail(skill_md, f"H1 is {first_heading.strip()!r}, expected '# {skill_dir.name}'")
        positions = []
        for heading in CANONICAL_HEADINGS:
            idx = text.find(heading + "\n")
            if idx == -1:
                idx = text.find(heading + " ")
            if idx == -1:
                fail(skill_md, f"missing canonical heading {heading!r}")
            positions.append(idx)
        present = [p for p in positions if p != -1]
        if present != sorted(present):
            fail(skill_md, "canonical headings are out of order")

        # 2. Flag parity.
        scripts = sorted(skill_dir.glob("scripts/*.py"))
        script_flags: set[str] = set()
        for script in scripts:
            script_flags |= argparse_flags(script)
        doc_flags = documented_flags(text) - FLAG_ALLOWLIST
        for flag in sorted(doc_flags - script_flags):
            fail(skill_md, f"documents flag {flag} that no script in this skill defines")
        for flag in sorted((script_flags - FLAG_ALLOWLIST) - doc_flags):
            fail(skill_md, f"script flag {flag} is not documented anywhere in the SKILL.md")

        # 3. State-file claims.
        script_sources = "\n".join(s.read_text(encoding="utf-8") for s in scripts)
        for state_ref in set(re.findall(r"\.seo-engine/[\w./<>{}\[\]*-]+", text)):
            token = state_ref.rstrip(".,)")
            basename = token.split("/")[-1]
            core = re.split(r"[<{\[*]", basename)[0].rstrip("-_")
            if not core:
                continue
            if core in script_sources or core in common_setup_text or token in common_setup_text:
                continue
            if any(part in ("state", "reports", "crawls", "config.yml", "http-cache")
                   for part in (core,)):
                continue
            fail(skill_md, f"claims state/report path {token!r} not found in this skill's scripts")

        # 4. Pointer resolution.
        for link in re.findall(r"\]\(([^)]+\.md)(?:#[^)]*)?\)", text):
            if link.startswith("http"):
                continue
            target = (skill_dir / link).resolve()
            lexical = Path(str((skill_dir / link)).replace("/./", "/"))
            if not target.is_file():
                fail(skill_md, f"markdown link {link!r} does not resolve")
            elif "../.." in link or link.startswith("references/") and not (skill_dir / "references").is_dir():
                fail(skill_md, f"link {link!r} uses a fragile path form")
        if "../../references" in text or re.search(r"[^.]\./references/", text):
            fail(skill_md, "contains a dead ../../references or bare references/ pointer")
        check_section_refs(skill_md, text, sections)

        # 6. Skill-name integrity.
        for token in set(BACKTICK_SKILL_RE.findall(text)):
            if token not in skill_names:
                fail(skill_md, f"references skill `{token}` which does not exist")

        # 7. Lint.
        if MOJIBAKE_RE.search(text):
            fail(skill_md, "contains SS-mojibake or replacement characters")
        for year in set(YEAR_RE.findall(prose)):
            fail(skill_md, f"bare year {year} in prose — dated facts belong in seo-references")
        for para in re.split(r"\n\s*\n", prose):
            if para.lstrip().startswith((">", "|")):
                # Blockquote callouts (incl. the mandated Paths block) and
                # tables (incl. the mandated snapshot-store State row) are
                # structured/mandated repetition, not prose duplication.
                continue
            words = para.split()
            if len(words) >= 40:
                digest = sha256(" ".join(w.lower() for w in words).encode()).hexdigest()
                owner = paragraph_owners.get(digest)
                if owner and owner != skill_md:
                    fail(skill_md, f"40+-word paragraph duplicated from {owner.relative_to(ENGINE_ROOT)}")
                paragraph_owners[digest] = skill_md

    # Script-embedded section refs (finding text carries e.g. "geo-playbook.md §4").
    for script in sorted(SKILLS_DIR.glob("*/scripts/*.py")) + sorted((ENGINE_ROOT / "scripts" / "lib").glob("*.py")):
        check_section_refs(script, script.read_text(encoding="utf-8"), sections)

    if errors:
        print(f"check_docs: {len(errors)} problem(s)\n")
        for e in errors:
            print(f"  {e}")
        return 1
    print(f"check_docs: OK ({len(skill_dirs)} skills, 0 problems)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
