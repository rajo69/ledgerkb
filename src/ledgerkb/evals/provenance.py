"""What a committed measurement has to carry, collected rather than typed.

``docs/adr/0006-measurement-provenance.md`` decided the shape of a committed
result before any result existed, which was the last moment at which it could be
decided honestly. This module is that decision in code: the header is gathered
from the environment, the store and git, and there is no argument through which a
human can hand-write one of its values.

The distinction the header keeps is between *intent* and *fact*. ``config_hash``
records what was asked for. ``embedding_model`` and the corpus counts record what
the run actually had in front of it, read from the store rather than from the
config, following ADR 0004. A result should describe the run, not the plan.

Two details are load-bearing and easy to break:

``.gitattributes`` pins the whole repository to LF in the working tree. That is
what makes ``lockfile_sha256`` and ``golden_set_sha256`` comparable between a
Windows run and a Linux one. Remove that line and two runs of the same commit
start disagreeing about their own inputs.

``dirty`` counts modifications to tracked files only. Untracked files are
excluded deliberately: a scratch file beside the checkout does not change what
``git checkout <sha>`` reproduces, and counting it would make almost every local
run inadmissible for no gain in reproducibility.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from platform import machine, processor, python_version
from platform import platform as os_description
from typing import Any

from ledgerkb.core.config import Config
from ledgerkb.core.models import utcnow
from ledgerkb.storage.sqlite.store import SqliteStore

# git is asked about the tree the code was imported from, not the working
# directory, so a measurement driven from anywhere still describes ledgerkb.
_PACKAGE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Provenance:
    """The header both halves of a committed result carry.

    Field order is ADR 0006's order, and both renderers follow it, so the record
    can be laid beside the decision and checked for gaps.
    """

    run_at: str
    ledgerkb_commit: str | None
    dirty: bool
    lockfile_sha256: str | None
    config_hash: str
    corpus_scale: int
    corpus_documents: int
    corpus_chunks: int
    golden_set_sha256: str | None
    embedding_model: str | None
    embedding_dims: int | None
    python: str
    platform: str
    command: str

    @property
    def admissible(self) -> bool:
        """Whether this run may be cited as gate evidence.

        ADR 0006 rules out a dirty tree. A run with no commit at all is ruled
        out by the same argument rather than by a separate one: neither can be
        re-derived, and the one that cannot even name a starting point is the
        weaker of the two.
        """
        return not self.dirty and self.ledgerkb_commit is not None

    @property
    def inadmissible_because(self) -> str | None:
        """Why this run is not gate evidence, or None if it is."""
        if self.ledgerkb_commit is None:
            return "the code was not running from a git checkout, so it names no commit"
        if self.dirty:
            return "the working tree had uncommitted changes to tracked files"
        return None

    def as_dict(self) -> dict[str, Any]:
        """The JSON half.

        ``admissible`` is included so a later reader applies ADR 0006's rule
        rather than reimplementing it.
        """
        out = asdict(self)
        out["admissible"] = self.admissible
        return out

    def as_markdown(self) -> str:
        """The Markdown half, as a table because that is what diffs by line.

        Generated results are committed, and ``git ls-files`` over Markdown is
        what ``scripts/check_docs.py`` lints, so this output obeys the
        documentation rules too: no em dashes, no banned words.
        """
        lines = ["## Provenance", ""]
        if (reason := self.inadmissible_because) is not None:
            lines += [f"**Not admissible as gate evidence:** {reason}.", ""]
        lines += ["| field | value |", "| --- | --- |"]
        lines += [f"| {key} | {_cell(value)} |" for key, value in asdict(self).items()]
        return "\n".join(lines) + "\n"


def collect(
    *,
    store: SqliteStore,
    cfg: Config,
    workspace_id: str,
    corpus_scale: int,
    golden_set: Path | None = None,
    command: str | None = None,
) -> Provenance:
    """Gather the header for a run about to happen.

    Called before the measurement, not after, so ``dirty`` describes the tree the
    numbers came from rather than a tree the runner has since written results
    into.

    ``command`` defaults to this process's own argv and exists as an argument
    only so a caller that is not a command line can say what it was.
    """
    root = _repo_root()
    space = store.embedding_space(workspace_id)
    counts = store.counts_for_workspace(workspace_id)

    return Provenance(
        run_at=utcnow().isoformat(),
        ledgerkb_commit=_git(root, "rev-parse", "HEAD") if root else None,
        dirty=_is_dirty(root),
        lockfile_sha256=_sha256(root / "uv.lock") if root else None,
        config_hash=_sha256_bytes(_canonical(cfg.build_receipt())),
        corpus_scale=corpus_scale,
        corpus_documents=counts["document"],
        corpus_chunks=counts["chunk"],
        golden_set_sha256=_sha256(golden_set) if golden_set is not None else None,
        embedding_model=space[0] if space else None,
        embedding_dims=space[1] if space else None,
        python=python_version(),
        platform=f"{os_description()} ({processor() or machine()})",
        command=command if command is not None else _command(),
    )


def _repo_root() -> Path | None:
    """The checkout this code was imported from, or None if it is not in one."""
    top = _git(_PACKAGE_DIR, "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def _git(cwd: Path, *args: str) -> str | None:
    """A git answer, or None.

    Every caller treats absent git as missing provenance rather than as a
    failure, because a wheel is a legitimate way to run this and it simply has
    no commit to report.
    """
    try:
        out = subprocess.run(  # noqa: S603 - arguments are literals and there is no shell
            ["git", *args],  # noqa: S607 - git is expected on PATH, and absent git is handled
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _is_dirty(root: Path | None) -> bool:
    """Tracked modifications only. See the module docstring for why.

    No checkout means nothing to be dirty against, and ``admissible`` already
    rejects that case on the stronger ground that there is no commit.
    """
    if root is None:
        return False
    return bool(_git(root, "status", "--porcelain", "--untracked-files=no"))


def _canonical(value: dict[str, Any]) -> bytes:
    """Bytes that depend on the content and not on how a dict was built.

    ``sort_keys`` rather than trusting pydantic's field order, so that reordering
    a config model cannot silently change the hash of an unchanged config.
    """
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    """Hash of a file that has to exist.

    A path that was passed and cannot be read is a mistake worth stopping for,
    not a field worth leaving empty.
    """
    return _sha256_bytes(path.read_bytes())


def _command() -> str:
    """This process's command line.

    ``argv[0]`` is cut to its basename so a committed result does not carry
    somebody's home directory.
    """
    if not sys.argv:
        return ""
    return shlex.join([Path(sys.argv[0]).name, *sys.argv[1:]])


def _cell(value: object) -> str:
    """A table cell.

    Pipes are escaped, and None reads as a word rather than a gap, so an absent
    value is visibly absent instead of looking like an oversight. Booleans are
    spelled the way the JSON half spells them, so the two files can be read
    against each other without a translation step.
    """
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("|", r"\|")


__all__ = ["Provenance", "collect"]
