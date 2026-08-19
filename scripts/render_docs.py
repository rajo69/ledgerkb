#!/usr/bin/env python3
"""Render the generated regions of README.md and ROADMAP.md from docs/stages.toml.

Stage status used to be stated in prose in four separate files, and it had
already drifted once. Everything that states where the project is now comes from
one machine-readable file, and CI runs this script with ``--check`` so a status
change that does not regenerate the documents fails the build.

    python scripts/render_docs.py            rewrite the files in place
    python scripts/render_docs.py --check    exit 1 with a diff if anything differs

Standard library only, on purpose: this has to run before anything is installed.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STAGES = ROOT / "docs" / "stages.toml"

BEGIN = "<!-- generated: {name}. Edit docs/stages.toml, then run scripts/render_docs.py -->"
END = "<!-- end generated: {name} -->"

STATUS_LABEL = {
    "done": "done",
    "in-progress": "in progress",
    "not-started": "not started",
}
TRACK_LABEL = {"library": "Library", "product": "Product"}


@dataclass(frozen=True)
class Stage:
    id: str
    track: str
    title: str
    status: str
    goal: str
    summary: str
    ships: str
    effort: str
    risk: str
    gate: tuple[tuple[str, bool], ...]

    @property
    def met(self) -> int:
        return sum(1 for _, met in self.gate if met)


def load(path: Path = STAGES) -> tuple[dict[str, Any], list[Stage]]:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    if data.get("schema_version") != 1:
        raise SystemExit(f"{path}: unsupported schema_version {data.get('schema_version')!r}")

    stages: list[Stage] = []
    for raw in data["stage"]:
        status = raw["status"]
        if status not in STATUS_LABEL:
            raise SystemExit(f"{path}: stage {raw['id']} has unknown status {status!r}")
        if raw["track"] not in TRACK_LABEL:
            raise SystemExit(f"{path}: stage {raw['id']} has unknown track {raw['track']!r}")
        stages.append(
            Stage(
                id=raw["id"],
                track=raw["track"],
                title=raw["title"],
                status=status,
                goal=raw["goal"].strip(),
                summary=unwrap(raw["summary"]),
                ships=raw.get("ships", ""),
                effort=raw.get("effort", ""),
                risk=raw.get("risk", ""),
                gate=tuple((g["text"], bool(g["met"])) for g in raw.get("gate", [])),
            )
        )

    ids = [s.id for s in stages]
    if len(set(ids)) != len(ids):
        raise SystemExit(f"{path}: duplicate stage ids")
    if data["current"] not in ids:
        raise SystemExit(f"{path}: current = {data['current']!r} is not a stage id")
    return data, stages


def unwrap(text: str) -> str:
    """Collapse a TOML multi-line string into one paragraph.

    The source file wraps for review; the rendered output rewraps for reading.
    """
    return " ".join(text.split())


def wrap(text: str, width: int = 92, indent: str = "") -> str:
    words, lines, line = text.split(), [], indent
    for word in words:
        candidate = f"{line} {word}" if line.strip() else f"{indent}{word}"
        if len(candidate) > width and line.strip():
            lines.append(line)
            line = f"{indent}{word}"
        else:
            line = candidate
    if line.strip():
        lines.append(line)
    return "\n".join(lines)


# --- regions -----------------------------------------------------------------


def render_status(data: dict[str, Any], stages: list[Stage]) -> str:
    current = next(s for s in stages if s.id == data["current"])
    out = [
        f"**Current stage: {current.id}, {current.title.lower()}.** "
        f"{current.met} of its {len(current.gate)} gate criteria are met.",
        "",
    ]

    for track in ("library", "product"):
        members = [s for s in stages if s.track == track]
        span = f"{members[0].id} to {members[-1].id}"
        done = [s.id for s in members if s.status == "done"]
        doing = [s.id for s in members if s.status == "in-progress"]
        todo = [s.id for s in members if s.status == "not-started"]
        groups = [(done, "done"), (doing, "in progress"), (todo, "not started")]
        present = [(ids_, label) for ids_, label in groups if ids_]
        if len(present) == 1:
            # A whole track in one state reads badly as "P1 to P6: P1 to P6 not started".
            line = present[0][1]
        else:
            line = "; ".join(f"{join(ids_)} {label}" for ids_, label in present)
        out.append(f"- **{TRACK_LABEL[track]}** ({span}): {line}.")

    out.append("")
    for paragraph in data["works_today"].strip().split("\n\n"):
        out.append(wrap(unwrap(paragraph)))
        out.append("")

    out.append(
        wrap(
            f"Which {current.id} criteria are outstanding, and what every other stage "
            f"commits to, is in [ROADMAP.md](ROADMAP.md)."
        )
    )
    return "\n".join(out).rstrip()


def join(items: list[str]) -> str:
    """`L0 and L1`, `L3 to L8` when the run is contiguous, `L0` on its own."""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{items[0]} to {items[-1]}"


def render_roadmap_table(data: dict[str, Any], stages: list[Stage]) -> str:
    rows = ["| Stage | Title | Status | Gate | Ships |", "|---|---|---|---|---|"]
    for s in stages:
        marker = "**" if s.id == data["current"] else ""
        gate = f"{s.met}/{len(s.gate)}" if s.gate else "-"
        rows.append(
            f"| {marker}{s.id}{marker} | {s.title} | {STATUS_LABEL[s.status]} "
            f"| {gate} | {s.ships or '-'} |"
        )
    return "\n".join(rows)


def render_roadmap_detail(data: dict[str, Any], stages: list[Stage]) -> str:
    out: list[str] = []
    for s in stages:
        out.append(f"### {s.id}. {s.title}")
        out.append("")
        bits = [STATUS_LABEL[s.status]]
        if s.ships:
            bits.append(f"ships {s.ships}")
        if s.effort:
            bits.append(f"effort {s.effort}")
        if s.risk:
            bits.append(f"risk {s.risk}")
        out.append(f"*{' · '.join(bits)}*")
        out.append("")
        out.append(f"**Goal.** {s.goal}")
        out.append("")
        out.append(wrap(s.summary))
        out.append("")
        out.append("Gate:")
        out.append("")
        for text, met in s.gate:
            box = "x" if met else " "
            # Hanging indent, so a wrapped criterion stays inside its list item.
            body = wrap(text, width=86, indent="      ").lstrip()
            out.append(f"- [{box}] {body}")
        out.append("")
    return "\n".join(out).rstrip()


REGIONS = {
    "status": ("README.md", render_status),
    "roadmap-table": ("ROADMAP.md", render_roadmap_table),
    "roadmap-detail": ("ROADMAP.md", render_roadmap_detail),
}


# --- splicing ----------------------------------------------------------------


def splice(text: str, name: str, body: str, path: Path) -> str:
    begin, end = BEGIN.format(name=name), END.format(name=name)
    pattern = re.compile(
        # The body may be empty, which is how a region is first added by hand.
        re.escape(begin) + r"\n(?:.*?\n)??" + re.escape(end),
        re.DOTALL,
    )
    if not pattern.search(text):
        raise SystemExit(
            f"{path}: no generated region named {name!r}.\n"
            f"Add these two lines where the content belongs:\n\n{begin}\n{end}"
        )
    return pattern.sub(lambda _: f"{begin}\n{body}\n{end}", text, count=1)


def render_all() -> dict[Path, str]:
    data, stages = load()
    wanted: dict[Path, str] = {}
    for name, (filename, renderer) in REGIONS.items():
        path = ROOT / filename
        current = wanted.get(path)
        if current is None:
            if not path.is_file():
                raise SystemExit(f"{path} does not exist")
            current = path.read_text(encoding="utf-8")
        wanted[path] = splice(current, name, renderer(data, stages), path)
    return wanted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write. Exit non-zero with a diff if a file is out of date.",
    )
    args = parser.parse_args()

    rendered = render_all()
    stale: list[Path] = []
    for path, wanted in rendered.items():
        actual = path.read_text(encoding="utf-8")
        if actual == wanted:
            continue
        stale.append(path)
        if args.check:
            rel = path.relative_to(ROOT).as_posix()
            sys.stdout.writelines(
                difflib.unified_diff(
                    actual.splitlines(keepends=True),
                    wanted.splitlines(keepends=True),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
            )
        else:
            path.write_text(wanted, encoding="utf-8", newline="\n")

    if args.check and stale:
        names = ", ".join(p.name for p in stale)
        print(
            f"\n{names} is out of date with docs/stages.toml.\n"
            "Run: python scripts/render_docs.py",
            file=sys.stderr,
        )
        return 1
    if not args.check:
        print(f"rendered {len(rendered)} file(s) from docs/stages.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
