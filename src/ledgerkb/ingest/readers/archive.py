"""ZIP expansion, with guards.

An archive is attacker-controlled structure, not just attacker-controlled
content. Four separate things can go wrong, and each needs its own limit:

* **Path traversal** — an entry named ``../../../.ssh/authorized_keys`` writes
  outside the workspace. Absolute paths and drive letters do the same.
* **Compression bombs** — 42 kilobytes that expand to petabytes.
* **Nesting** — an archive of archives of archives.
* **Sheer volume** — ten million tiny entries.

Every limit refuses loudly and names the entry. None of them is configurable:
"you set the ceiling, you cannot set ignore it" applies here as it does to
budgets.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from ledgerkb.core.errors import LedgerKBError

MAX_RATIO = 100.0
"""Compressed-to-uncompressed ratio. Legitimate documents rarely exceed ~20."""

MAX_TOTAL_BYTES = 2 * 1024**3       # 2 GiB expanded, across the whole archive
MAX_ENTRY_BYTES = 512 * 1024**2     # 512 MiB for any single member
MAX_ENTRIES = 10_000
MAX_DEPTH = 3                       # archive inside archive inside archive


class ArchiveRejectedError(LedgerKBError):
    """An archive tripped a guard. Never downgraded to a warning."""

    def __init__(self, archive: str, entry: str, reason: str) -> None:
        super().__init__(f"Rejected {archive!r} at entry {entry!r}: {reason}")
        self.archive = archive
        self.entry = entry
        self.reason = reason


@dataclass(frozen=True)
class ArchiveMember:
    path: str
    """Normalised, relative, forward-slashed path within the archive."""
    data: bytes
    depth: int


def is_archive(name: str) -> bool:
    return name.lower().endswith(".zip")


def safe_entry_name(archive: str, name: str) -> str:
    """Normalise an entry name, refusing anything that escapes the root.

    Windows and POSIX disagree about what a separator is, and about drive
    letters, so both interpretations are checked. An entry only has to be
    dangerous under one of them to be dangerous.
    """
    if "\x00" in name:
        raise ArchiveRejectedError(archive, name, "null byte in entry name")

    candidate = name.replace("\\", "/")

    if PurePosixPath(candidate).is_absolute():
        raise ArchiveRejectedError(archive, name, "absolute path")
    win = PureWindowsPath(name)
    if win.is_absolute() or win.drive:
        raise ArchiveRejectedError(archive, name, "absolute path or drive letter")

    parts: list[str] = []
    for part in PurePosixPath(candidate).parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ArchiveRejectedError(archive, name, "path traversal outside the archive root")
        parts.append(part)

    if not parts:
        raise ArchiveRejectedError(archive, name, "empty entry name")
    return "/".join(parts)


def expand(
    data: bytes,
    archive_name: str = "<archive>",
    *,
    depth: int = 0,
    _budget: dict[str, int] | None = None,
) -> Iterator[ArchiveMember]:
    """Yield every file in an archive, recursively, subject to the guards."""
    if depth > MAX_DEPTH:
        raise ArchiveRejectedError(archive_name, "<nested>", f"nesting deeper than {MAX_DEPTH}")

    budget = _budget if _budget is not None else {"bytes": 0, "entries": 0}

    try:
        zf = zipfile.ZipFile(_BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveRejectedError(archive_name, "<archive>", f"not a readable zip: {exc}") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ArchiveRejectedError(
                archive_name, "<archive>", f"{len(infos)} entries exceeds the {MAX_ENTRIES} limit"
            )

        for info in infos:
            if info.is_dir():
                continue

            name = safe_entry_name(archive_name, info.filename)

            budget["entries"] += 1
            if budget["entries"] > MAX_ENTRIES:
                raise ArchiveRejectedError(
                    archive_name, name, f"more than {MAX_ENTRIES} entries once nesting is counted"
                )

            if info.file_size > MAX_ENTRY_BYTES:
                raise ArchiveRejectedError(
                    archive_name, name,
                    f"declared size {info.file_size} exceeds the per-entry limit",
                )

            # Check the declared ratio before reading a single byte, so a bomb
            # is refused rather than survived.
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > MAX_RATIO:
                    raise ArchiveRejectedError(
                        archive_name, name,
                        f"compression ratio {ratio:.0f}:1 exceeds {MAX_RATIO:.0f}:1",
                    )

            payload = _read_capped(zf, info, archive_name, name)

            budget["bytes"] += len(payload)
            if budget["bytes"] > MAX_TOTAL_BYTES:
                raise ArchiveRejectedError(
                    archive_name, name, "expanded size exceeds the total archive limit"
                )

            if is_archive(name):
                yield from expand(payload, name, depth=depth + 1, _budget=budget)
            else:
                yield ArchiveMember(path=name, data=payload, depth=depth)


def _read_capped(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, archive: str, name: str
) -> bytes:
    """Read with a hard cap.

    The header's declared size is attacker-controlled, so it is a routing hint,
    not a promise. This reads one byte past the limit and refuses if it gets it.
    """
    limit = MAX_ENTRY_BYTES
    with zf.open(info) as fh:
        payload = fh.read(limit + 1)
    if len(payload) > limit:
        raise ArchiveRejectedError(archive, name, "actual size exceeds the per-entry limit")
    if len(payload) != info.file_size:
        raise ArchiveRejectedError(
            archive, name,
            f"declared size {info.file_size} does not match actual {len(payload)}",
        )
    return payload


def _BytesIO(data: bytes):  # noqa: N802, ANN202 - kept local to avoid an import at module scope
    import io

    return io.BytesIO(data)


__all__ = [
    "MAX_DEPTH",
    "MAX_ENTRIES",
    "MAX_ENTRY_BYTES",
    "MAX_RATIO",
    "MAX_TOTAL_BYTES",
    "ArchiveMember",
    "ArchiveRejectedError",
    "expand",
    "is_archive",
    "safe_entry_name",
]
