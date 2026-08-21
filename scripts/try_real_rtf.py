#!/usr/bin/env python3
r"""Run a real Word-produced .rtf through the parser proposed in PR #1.

The tests in that PR and the parser it ships were written from the same reading
of the RTF spec, so anywhere that reading is wrong both sides are wrong
together. The only thing that breaks the tie is a file Word actually wrote.

    python scripts/try_real_rtf.py path\to\file.rtf

Prints what the parser recovered, what it dropped, and whether the offsets it
recorded index the text it returned. Nothing here is a test: it is a way to
look at one file. Delete this script once RTF has landed.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PR_REF = "refs/remotes/origin/pr-1"
PARSER_PATH = "src/ledgerkb/ingest/parsers/rtf.py"


def load_parser():  # noqa: ANN201 - a module object, imported at runtime
    """Fetch the parser out of the PR ref without checking the branch out."""
    try:
        # Both arguments are constants defined above, so there is no untrusted
        # input in this call and no shell to inject into.
        blob = subprocess.run(  # noqa: S603
            ["git", "show", f"{PR_REF}:{PARSER_PATH}"],  # noqa: S607
            cwd=ROOT, capture_output=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        sys.exit(
            f"could not read {PARSER_PATH} from {PR_REF}.\n"
            "Fetch it first:\n"
            "    git fetch origin pull/1/head:refs/remotes/origin/pr-1"
        )

    tmp = Path(tempfile.mkdtemp())
    (tmp / "rtf_from_pr.py").write_bytes(blob)
    sys.path.insert(0, str(tmp))
    import rtf_from_pr  # type: ignore[import-not-found]

    return rtf_from_pr


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1])
    if not path.is_file():
        sys.exit(f"no such file: {path}")

    from ledgerkb.core.ports import ParseHint

    parser = load_parser().RtfParser()
    doc = parser.parse(path.read_bytes(), ParseHint(filename=path.name))

    print(f"file          : {path.name} ({path.stat().st_size:,} bytes)")
    print(f"parse_quality : {doc.parse_quality}")
    print(f"title         : {doc.title!r}")
    print(f"characters    : {len(doc.text):,}")
    print()

    print(f"headings ({len(doc.headings)})")
    if not doc.headings:
        print("  none. If the document has Word heading styles, that is the bug.")
    for h in doc.headings:
        sliced = doc.text[h.char_start : h.char_start + len(h.text)]
        mark = "ok " if sliced == h.text else "BAD"
        print(f"  {mark} h{h.level} @{h.char_start:<6} {h.text[:70]!r}")
    print()

    hidden = [w for w in doc.warnings if w.startswith("hidden:")]
    other = [w for w in doc.warnings if not w.startswith("hidden:")]
    print(f"hidden runs quarantined ({len(hidden)})")
    for w in hidden:
        print(f"  {w[:100]}")
    print(f"other warnings ({len(other)})")
    for w in other:
        print(f"  {w[:100]}")
    print()

    print("first 600 characters of the recovered text")
    print("-" * 60)
    print(doc.text[:600])
    print("-" * 60)
    print()

    # The one thing worth checking automatically. Everything above is for
    # reading; this is the invariant the whole project rests on.
    from ledgerkb.core.config import ChunkingConfig
    from ledgerkb.ingest.chunk import chunk_document

    bad = [
        c for c in chunk_document(doc, "ws", "v", ChunkingConfig())
        if doc.text[c.char_start : c.char_end] != c.text
    ]
    print(f"offset invariant: {'FAILED on ' + str(len(bad)) + ' chunks' if bad else 'holds'}")


if __name__ == "__main__":
    main()
