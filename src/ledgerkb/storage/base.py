"""Shared storage machinery: the migration runner and value codecs.

Backend-agnostic. The SQLite and Postgres stores both sit behind
:class:`ledgerkb.core.ports.Store` and share everything in here.
"""

from __future__ import annotations

import json
import re
import sys
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ledgerkb.core.errors import StorageError

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Numbered SQL files, in order. A gap in the sequence is an error, not a
    thing to shrug at — it usually means a file was lost in a bad merge."""
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        m = _MIGRATION_RE.match(path.name)
        if not m:
            raise StorageError(
                f"Migration filename {path.name!r} is malformed; expected NNN_name.sql"
            )
        found.append(Migration(int(m.group(1)), m.group(2), path.read_text(encoding="utf-8")))

    for expected, mig in enumerate(found, start=1):
        if mig.version != expected:
            raise StorageError(
                f"Migration sequence has a gap: expected {expected:03d}, found {mig.version:03d}"
            )
    return found


# --- value codecs ------------------------------------------------------------
#
# SQLite has no arrays, no JSON columns and no vector type, so lists and dicts
# travel as JSON text and embeddings as a float32 blob. Postgres overrides these.


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def loads(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StorageError(f"Corrupt JSON column: {exc}") from exc


def dt(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def pack_vector(vec: Sequence[float] | None) -> bytes | None:
    """float32, little-endian — the on-disk format the schema documents."""
    if vec is None:
        return None
    a = array("f", vec)
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


def unpack_vector(blob: bytes | None) -> list[float] | None:
    if blob is None:
        return None
    a = array("f")
    a.frombytes(blob)
    if sys.byteorder == "big":
        a.byteswap()
    return list(a)


def fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    FTS5 has its own query syntax, so raw user input can both error and mean
    something unintended. Every token is quoted and joined with OR; ranking,
    not the query, decides relevance.
    """
    tokens = re.findall(r"\w+", text, flags=re.UNICODE)
    if not tokens:
        return '""'
    return " OR ".join(f'"{t}"' for t in tokens)


__all__ = [
    "MIGRATIONS_DIR",
    "Migration",
    "discover_migrations",
    "dt",
    "dumps",
    "fts_query",
    "loads",
    "pack_vector",
    "unpack_vector",
]
