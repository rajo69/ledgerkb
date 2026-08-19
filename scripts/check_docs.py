#!/usr/bin/env python3
"""Lint the repository's Markdown, so the style rules stay true without review.

Four checks:

1. No em dash, outside fenced code blocks. A rule about a character has to be
   able to quote the character, so code blocks and inline code are exempt.
2. No word from scripts/banned-words.txt. Exempt inside code and inside double
   quotes, for the same reason.
3. Every relative link resolves on disk.
4. No stage status stated in prose outside a generated region. Status lives in
   docs/stages.toml and is rendered; a second copy in prose is the drift this
   whole arrangement exists to stop.

    python scripts/check_docs.py            check every tracked Markdown file
    python scripts/check_docs.py a.md b.md  check just these

Standard library only.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNED_WORDS = ROOT / "scripts" / "banned-words.txt"

EM_DASH = "—"

FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
DOUBLE_QUOTED = re.compile(r'"[^"\n]*"')
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
GENERATED = re.compile(
    r"<!-- generated: [\w-]+\..*?-->.*?<!-- end generated: [\w-]+ -->", re.DOTALL
)

# A stage id sitting next to a claim about how far along it is. Deliberately
# narrow: "quote verification is L3" and "(L6)" are fine, because they say which
# stage a capability belongs to rather than how much of it is finished.
STAGE_STATUS = re.compile(
    r"\b[LP][0-8]\b\s*(?:and\s+[LP][0-8]\s*)?(?:is|are)?\s*(?:now\s+)?"
    r"(?:complete|completed|done|half\s+done|half\s+complete|in\s+progress|"
    r"underway|under\s+way|finished|the\s+current\s+stage)\b"
    r"|\b(?:current\s+stage|currently\s+at|now\s+at|is\s+at|are\s+at)\b"
    r"[^.\n]{0,20}\b[LP][0-8]\b",
    re.IGNORECASE,
)

# Design records are dated accounts of what was true when they were written, and
# they say so in a banner. Freezing their prose is the point of keeping them.
STAGE_STATUS_EXEMPT = ("docs/design/",)


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"],  # noqa: S607 - git is expected on PATH
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ROOT / line for line in out.stdout.splitlines() if line]


def strip_fences(text: str) -> list[tuple[int, str]]:
    """Numbered lines with fenced blocks blanked out, so offsets stay usable."""
    lines, inside, fence = [], False, ""
    for number, line in enumerate(text.split("\n"), start=1):
        marker = FENCE.match(line)
        if marker and not inside:
            inside, fence = True, marker.group(1)
            lines.append((number, ""))
            continue
        if marker and inside and marker.group(1) == fence:
            inside = False
            lines.append((number, ""))
            continue
        lines.append((number, "" if inside else line))
    return lines


def strip_quotes(line: str) -> str:
    return DOUBLE_QUOTED.sub("", INLINE_CODE.sub("", line))


def load_banned() -> list[str]:
    words = []
    for raw in BANNED_WORDS.read_text(encoding="utf-8").splitlines():
        entry = raw.split("#", 1)[0].strip()
        if entry:
            words.append(entry)
    return words


def check(path: Path, banned: list[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    try:
        rel = path.relative_to(ROOT).as_posix()
    except ValueError:  # a path given on the command line from outside the repo
        rel = path.as_posix()
    problems: list[str] = []
    lines = strip_fences(text)

    for number, line in lines:
        if EM_DASH in line:
            problems.append(
                f"{rel}:{number}: em dash. Use a comma, a colon, a full stop or "
                f"parentheses, whichever the sentence needs"
            )

        prose = strip_quotes(line)
        lowered = prose.lower()
        for word in banned:
            pattern = r"\b" + re.escape(word).replace(r"\ ", r"\s+") + r"\b"
            if re.search(pattern, lowered):
                problems.append(f"{rel}:{number}: banned phrase {word!r}")

    # Links, over the whole file so a wrapped link still resolves.
    for match in LINK.finditer(text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#", "<")):
            continue
        target = target.split("#", 1)[0]
        if not target:
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            number = text[: match.start()].count("\n") + 1
            problems.append(f"{rel}:{number}: link does not resolve: {target}")

    # Stage status, outside the generated regions.
    if not rel.startswith(STAGE_STATUS_EXEMPT):
        outside = GENERATED.sub("", text)
        for number, line in strip_fences(outside):
            if STAGE_STATUS.search(line):
                problems.append(
                    f"{rel}:{number}: stage status in prose. Put it in "
                    f"docs/stages.toml and render it, or reword"
                )

    return problems


def main(argv: list[str]) -> int:
    paths = [Path(a).resolve() for a in argv] or tracked_markdown()
    banned = load_banned()

    problems: list[str] = []
    for path in paths:
        if path.is_file():
            problems.extend(check(path, banned))

    for problem in problems:
        print(problem, file=sys.stderr)

    if problems:
        print(
            f"\n{len(problems)} problem(s) in {len(paths)} file(s). "
            f"The rules are in AGENTS.md.",
            file=sys.stderr,
        )
        return 1
    print(f"{len(paths)} Markdown file(s) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
