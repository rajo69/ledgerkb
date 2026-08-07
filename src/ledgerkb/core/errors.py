"""Error taxonomy.

Every error carries enough context to name the offending document, because the
"fail loud, degrade gracefully" convention means a single bad file must never
take down a run of 56 good ones.
"""

from __future__ import annotations


class LedgerKBError(Exception):
    """Base class for every error this library raises deliberately."""


# --- configuration -----------------------------------------------------------


class ConfigError(LedgerKBError):
    """Configuration is malformed, incoherent, or violates a tier constraint."""


class LockedSettingError(ConfigError):
    """A tier-3 setting was changed after first use.

    Carries the destructive command that would legitimately apply the change.
    """

    def __init__(self, key: str, old: object, new: object, remedy: str) -> None:
        super().__init__(
            f"{key!r} is locked after first use (stored={old!r}, requested={new!r}). "
            f"To change it deliberately, run: {remedy}"
        )
        self.key = key
        self.old = old
        self.new = new
        self.remedy = remedy


class GatedSettingError(ConfigError):
    """A tier-2 setting changed; derived data must be rebuilt before continuing."""

    def __init__(self, key: str, rebuilds: str) -> None:
        super().__init__(f"Changing {key!r} invalidates derived data. It forces: {rebuilds}")
        self.key = key
        self.rebuilds = rebuilds


# --- invariants --------------------------------------------------------------


class InvariantError(LedgerKBError):
    """A tier-4 invariant would be violated. Never catchable into a warning."""


class EvidenceRequiredError(InvariantError):
    """An assertion was constructed with no supporting evidence."""


class QuoteVerificationError(InvariantError):
    """A quote does not occur in the chunk text it claims to come from."""


# --- pipeline ----------------------------------------------------------------


class ParseError(LedgerKBError):
    """A document could not be parsed. Names the document; never aborts the run."""

    def __init__(self, uri: str, reason: str) -> None:
        super().__init__(f"Could not parse {uri}: {reason}")
        self.uri = uri
        self.reason = reason


class StorageError(LedgerKBError):
    """The store rejected an operation."""


class ProviderError(LedgerKBError):
    """A chat / embedding / rerank provider failed."""


class BudgetExceededError(LedgerKBError):
    """A run hit its cost or document ceiling and aborted. Not suppressible."""
