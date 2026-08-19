#!/usr/bin/env python3
"""Generate the configuration reference from `ledgerkb.core.config`.

Every config field already carries its tunability tier as annotated metadata,
because validation enforces the tier rather than documentation asking nicely.
That makes the table in docs/reference/configuration.md derivable, so it is
derived: a new key that nobody documents fails CI instead of going unnoticed.

    python scripts/render_config_reference.py            rewrite in place
    python scripts/render_config_reference.py --check    exit 1 with a diff

Needs the package importable. Everything it touches is pure: `core` imports
nothing but the standard library and pydantic.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ledgerkb.core.config import Config, Profile, Tier, Tiered  # noqa: E402
from ledgerkb.core.config import _tier_of as tier_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "docs" / "reference" / "configuration.md"

BEGIN = "<!-- generated: {name}. Edit src/ledgerkb/core/config.py, then run scripts/render_config_reference.py -->"
END = "<!-- end generated: {name} -->"

TIER_LABEL = {
    Tier.FREE: "free",
    Tier.GATED: "gated",
    Tier.LOCKED: "locked",
}


def type_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is not None:
        args = ", ".join(type_name(a) for a in get_args(annotation))
        name = getattr(origin, "__name__", str(origin).replace("typing.", ""))
        if str(origin) == "typing.Literal":
            return " | ".join(repr(a) for a in get_args(annotation))
        if name == "UnionType" or str(origin).endswith("Union"):
            return " | ".join(type_name(a) for a in get_args(annotation))
        return f"{name}[{args}]"
    if annotation is type(None):
        return "None"
    return getattr(annotation, "__name__", str(annotation))


def default_of(model: type[BaseModel], name: str) -> str:
    info = model.model_fields[name]
    if info.default_factory is not None:
        try:
            value = info.default_factory()  # type: ignore[call-arg]
        except TypeError:
            return "(computed)"
    else:
        value = info.default
    if value is Ellipsis or repr(value) == "PydanticUndefined":
        return "required"
    if isinstance(value, BaseModel):
        return "(section)"
    return f"`{value!r}`"


def rows(model: type[BaseModel], prefix: str = "") -> list[tuple[str, str, str, Tiered]]:
    out: list[tuple[str, str, str, Tiered]] = []
    for name, info in model.model_fields.items():
        key = f"{prefix}{name}"
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            out.extend(rows(annotation, f"{key}."))
            continue
        out.append((key, type_name(annotation), default_of(model, name), tier_of(model, name)))
    return out


def cell(text: str) -> str:
    """A pipe ends a table cell, and union types are full of them."""
    return text.replace("|", "\\|")


def render(model: type[BaseModel], skip: tuple[str, ...] = ()) -> str:
    lines = ["| Key | Type | Default | Tier | Changing it forces |", "|---|---|---|---|---|"]
    for key, kind, default, tiered in rows(model):
        if key in skip or any(key.startswith(f"{s}.") for s in skip):
            continue
        forces = tiered.forces or "nothing. It is hot"
        lines.append(
            f"| `{cell(key)}` | `{cell(kind)}` | {cell(default)} "
            f"| {TIER_LABEL[tiered.tier]} | {forces} |"
        )
    return "\n".join(lines)


def splice(text: str, name: str, body: str) -> str:
    begin, end = BEGIN.format(name=name), END.format(name=name)
    pattern = re.compile(re.escape(begin) + r"\n(?:.*?\n)??" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        raise SystemExit(
            f"{TARGET}: no generated region named {name!r}.\n"
            f"Add these two lines where the table belongs:\n\n{begin}\n{end}"
        )
    return pattern.sub(lambda _: f"{begin}\n{body}\n{end}", text, count=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if not TARGET.is_file():
        raise SystemExit(f"{TARGET} does not exist")
    actual = TARGET.read_text(encoding="utf-8")

    wanted = splice(actual, "config-table", render(Config, skip=("resolved_profile",)))
    wanted = splice(wanted, "profile-table", render(Profile))

    if actual == wanted:
        return 0
    if args.check:
        rel = TARGET.relative_to(ROOT).as_posix()
        sys.stdout.writelines(
            difflib.unified_diff(
                actual.splitlines(keepends=True),
                wanted.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
        print(
            f"\n{rel} is out of date with src/ledgerkb/core/config.py.\n"
            "Run: python scripts/render_config_reference.py",
            file=sys.stderr,
        )
        return 1
    TARGET.write_text(wanted, encoding="utf-8", newline="\n")
    print(f"rendered {TARGET.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
