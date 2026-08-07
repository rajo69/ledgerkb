"""Configuration — the whole tuning surface, in one place.

The governing rule: **tunable = quality/cost tradeoffs; not tunable =
correctness invariants.** If a setting could make the system lie, it is not a
setting.

Tunability is an *attribute of each field*, so validation enforces it rather
than documentation asking nicely:

* :attr:`Tier.FREE` — hot, no rebuild.
* :attr:`Tier.GATED` — changing it invalidates derived data; the caller is told
  exactly what must be rebuilt and refuses to leave the store inconsistent.
* :attr:`Tier.LOCKED` — locked after first use; needs an explicit destructive
  command.
* Tier 4 invariants have **no field at all**, at any level. That is the point.
  A PR adding one is rejected regardless of how convenient it is.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ledgerkb.core.errors import ConfigError, GatedSettingError, LockedSettingError

CONFIG_FILENAME = "ledgerkb.toml"
CONFIG_VERSION = 1


class Tier(StrEnum):
    FREE = "free"
    GATED = "gated"
    LOCKED = "locked"


@dataclass(frozen=True)
class Tiered:
    """Annotated metadata carrying a field's tunability tier."""

    tier: Tier
    forces: str = ""
    """What changing this field invalidates. Shown to the user verbatim."""


FREE = Tiered(Tier.FREE)


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --- sections ----------------------------------------------------------------


class StoreConfig(Section):
    backend: Annotated[
        Literal["sqlite", "postgres"],
        Tiered(Tier.LOCKED, "a migration, not a setting"),
    ] = "sqlite"
    path: Annotated[str, FREE] = ".lkb/store.db"
    dsn: Annotated[str | None, FREE] = None
    """Postgres connection string. Ignored when backend is sqlite."""

    @model_validator(mode="after")
    def _backend_has_its_target(self) -> StoreConfig:
        if self.backend == "postgres" and not self.dsn:
            raise ValueError("store.backend='postgres' requires store.dsn")
        return self


class ChatTier(Section):
    """A per-stage model override. Only the model differs; the endpoint is shared."""

    model: Annotated[str, FREE]
    temperature: Annotated[float, FREE] = Field(default=0.0, ge=0.0, le=2.0)


class ChatConfig(Section):
    provider: Annotated[str, FREE] = "openai_compatible"
    base_url: Annotated[str, FREE] = "https://openrouter.ai/api/v1"
    model: Annotated[str, FREE] = "qwen/qwen3-235b-a22b"
    api_key_env: Annotated[str, FREE] = "OPENROUTER_API_KEY"
    temperature: Annotated[float, FREE] = Field(default=0.0, ge=0.0, le=2.0)
    concurrency: Annotated[int, FREE] = Field(default=4, ge=1, le=64)
    timeout_s: Annotated[float, FREE] = Field(default=120.0, gt=0)
    cheap: Annotated[ChatTier, FREE] = ChatTier(model="deepseek/deepseek-v3.2")
    """Headers, extraction and grading run here — the bulk of the token spend."""


class EmbeddingsConfig(Section):
    provider: Annotated[str, FREE] = "openai_compatible"
    model: Annotated[
        str,
        Tiered(Tier.LOCKED, "every stored vector becomes meaningless"),
    ] = "qwen/qwen3-embedding-8b"
    dimensions: Annotated[
        int,
        Tiered(Tier.LOCKED, "every stored vector becomes meaningless"),
    ] = Field(default=1024, gt=0)
    batch_size: Annotated[int, FREE] = Field(default=64, ge=1)


class ChunkingConfig(Section):
    max_tokens: Annotated[int, FREE] = Field(default=512, ge=64, le=8192)
    overlap: Annotated[int, FREE] = Field(default=64, ge=0)
    structure_first: Annotated[bool, FREE] = True
    contextual_headers: Annotated[bool, Tiered(Tier.GATED, "a full re-index")] = True
    tokenizer: Annotated[
        str,
        Tiered(Tier.LOCKED, "chunk boundaries shift, breaking every existing offset"),
    ] = "cl100k_base"

    @model_validator(mode="after")
    def _overlap_fits(self) -> ChunkingConfig:
        if self.overlap >= self.max_tokens:
            raise ValueError(
                f"chunking.overlap ({self.overlap}) must be smaller than "
                f"chunking.max_tokens ({self.max_tokens}) — otherwise chunking cannot advance"
            )
        return self


class RetrievalConfig(Section):
    dense_k: Annotated[int, FREE] = Field(default=50, ge=1, le=1000)
    sparse_k: Annotated[int, FREE] = Field(default=50, ge=1, le=1000)
    rrf_k: Annotated[int, FREE] = Field(default=60, ge=1)
    rerank_to: Annotated[int, FREE] = Field(default=8, ge=1)

    @model_validator(mode="after")
    def _rerank_has_something_to_rank(self) -> RetrievalConfig:
        pool = self.dense_k + self.sparse_k
        if self.rerank_to > pool:
            raise ValueError(
                f"retrieval.rerank_to ({self.rerank_to}) exceeds the candidate pool "
                f"dense_k + sparse_k ({pool}) — reranking cannot invent candidates"
            )
        return self


class ResolutionConfig(Section):
    trigram: Annotated[float, Tiered(Tier.GATED, "re-running resolution")] = Field(
        default=0.85, ge=0.0, le=1.0
    )
    grey_band: Annotated[
        tuple[float, float], Tiered(Tier.GATED, "re-running resolution")
    ] = (0.80, 0.92)
    auto_merge: Annotated[bool, Tiered(Tier.GATED, "re-running resolution")] = False
    """Off by default. Over-merging is the failure that matters."""

    @model_validator(mode="after")
    def _band_is_coherent(self) -> ResolutionConfig:
        low, high = self.grey_band
        if low >= high:
            raise ValueError(f"resolution.grey_band must be ascending; got [{low}, {high}]")
        if not low <= self.trigram <= high:
            raise ValueError(
                f"resolution.trigram ({self.trigram}) must sit inside grey_band "
                f"[{low}, {high}] — a threshold outside the review band means either "
                "everything or nothing is reviewed"
            )
        return self


class ParsingConfig(Section):
    density_probe: Annotated[float, FREE] = Field(default=0.6, ge=0.0, le=1.0)
    tier1: Annotated[str, FREE] = "docling"
    pdf: Annotated[Literal["pypdfium2", "pymupdf"], FREE] = "pypdfium2"
    """Default is Apache/BSD. PyMuPDF is AGPL-3.0 and stays an explicit opt-in."""


class BudgetConfig(Section):
    max_cost_usd_per_run: Annotated[float, FREE] = Field(default=5.0, gt=0)
    max_docs_per_run: Annotated[int, FREE] = Field(default=1000, ge=1)
    # Note: there is deliberately no "ignore budget" key. You set the ceiling;
    # you cannot set "proceed anyway".


class ObsConfig(Section):
    otlp_endpoint: Annotated[str, FREE] = ""
    semconv_version: Annotated[str, FREE] = "1.42.0"
    log_level: Annotated[
        Literal["debug", "info", "warning", "error"], FREE
    ] = "info"


# --- profile -----------------------------------------------------------------


class StalenessConfig(Section):
    model_config = ConfigDict(extra="allow")  # per-doc_type overrides

    default_days: int = Field(default=180, ge=1)


class ExtractionProfile(Section):
    hints: str = ""


class Profile(Section):
    """Domain knowledge lives here so the code stays corpus-agnostic.

    Never add a code branch for a corpus. Add a profile.
    """

    name: str = "default"
    entity_types: Annotated[list[str], Tiered(Tier.GATED, "re-extraction")] = Field(
        default_factory=lambda: [
            "Person", "Organisation", "Project", "Meeting", "Decision",
            "Action", "Risk", "Document", "Location", "Policy",
        ]
    )
    predicates: Annotated[list[str], Tiered(Tier.GATED, "re-extraction")] = Field(
        default_factory=lambda: [
            "attended", "owns", "was_made_at", "is_assigned_to", "relates_to",
            "threatens", "mentions", "supersedes", "depends_on", "supports",
        ]
    )
    doc_types: Annotated[list[str], FREE] = Field(
        default_factory=lambda: ["minutes", "report", "register", "policy", "email", "note"]
    )
    staleness: Annotated[StalenessConfig, FREE] = Field(default_factory=StalenessConfig)
    extraction: Annotated[ExtractionProfile, FREE] = Field(default_factory=ExtractionProfile)

    @model_validator(mode="after")
    def _schema_is_non_empty(self) -> Profile:
        if not self.entity_types:
            raise ValueError(
                "profile.entity_types cannot be empty — the schema is closed by design"
            )
        if not self.predicates:
            raise ValueError("profile.predicates cannot be empty — the schema is closed by design")
        return self


# --- root --------------------------------------------------------------------


class Config(Section):
    config_version: int = CONFIG_VERSION
    profile: str = "default"

    store: StoreConfig = Field(default_factory=StoreConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    resolution: ResolutionConfig = Field(default_factory=ResolutionConfig)
    parsing: ParsingConfig = Field(default_factory=ParsingConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    obs: ObsConfig = Field(default_factory=ObsConfig)

    resolved_profile: Profile = Field(default_factory=Profile)
    """The merged profile. Stamped into every build receipt."""

    @model_validator(mode="after")
    def _version_is_known(self) -> Config:
        if self.config_version != CONFIG_VERSION:
            raise ValueError(
                f"config_version {self.config_version} is not supported by this build "
                f"(expected {CONFIG_VERSION})"
            )
        return self

    def build_receipt(self) -> dict[str, Any]:
        """The fully-resolved config, for stamping into every export.

        Any artifact can then be audited for how it was produced — including
        whether a custom port was substituted.
        """
        return self.model_dump(mode="json")


# --- loading -----------------------------------------------------------------


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc


def find_config(start: Path | None = None) -> Path | None:
    """Walk upwards for ``ledgerkb.toml``, like git looks for ``.git``."""
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        candidate = d / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_profile(name: str, profiles_dir: Path) -> Profile:
    """Load ``profiles/<name>.toml``, layered over ``default.toml``."""
    data: dict[str, Any] = {}
    default_path = profiles_dir / "default.toml"
    if default_path.is_file():
        data = _read_toml(default_path)
    if name != "default":
        path = profiles_dir / f"{name}.toml"
        if not path.is_file():
            raise ConfigError(
                f"Profile {name!r} not found at {path}. "
                "Profiles carry domain knowledge; they are never code branches."
            )
        data = _deep_merge(data, _read_toml(path))
    data["name"] = name
    try:
        return Profile.model_validate(data)
    except ValueError as exc:
        raise ConfigError(f"Profile {name!r} is invalid: {exc}") from exc


def load_config(path: Path | None = None, profiles_dir: Path | None = None) -> Config:
    """Load, merge and validate. Incoherent combinations fail here — loudly, at
    startup — never by misbehaving later."""
    path = path or find_config()
    raw: dict[str, Any] = _read_toml(path) if path and path.is_file() else {}
    root = path.parent if path else Path.cwd()
    profiles_dir = profiles_dir or (root / "profiles")

    profile_name = str(raw.get("profile", "default"))
    raw["resolved_profile"] = load_profile(profile_name, profiles_dir).model_dump()

    try:
        return Config.model_validate(raw)
    except ValueError as exc:
        where = str(path) if path else "<defaults>"
        raise ConfigError(f"Invalid configuration in {where}:\n{exc}") from exc


# --- tier enforcement --------------------------------------------------------


def _tier_of(model: type[BaseModel], field: str) -> Tiered:
    info = model.model_fields[field]
    for meta in info.metadata:
        if isinstance(meta, Tiered):
            return meta
    return FREE


def _walk(old: BaseModel, new: BaseModel, prefix: str = "") -> list[tuple[str, Tiered, Any, Any]]:
    changes: list[tuple[str, Tiered, Any, Any]] = []
    for name in type(new).model_fields:
        o, n = getattr(old, name, None), getattr(new, name)
        key = f"{prefix}{name}"
        if isinstance(n, BaseModel) and isinstance(o, BaseModel):
            changes.extend(_walk(o, n, f"{key}."))
        elif o != n:
            changes.append((key, _tier_of(type(new), name), o, n))
    return changes


def check_transition(old: Config, new: Config, *, allow_gated: bool = False) -> list[str]:
    """Compare a stored config against an incoming one.

    Raises :class:`LockedSettingError` on any tier-3 change. Returns the list of
    rebuilds forced by tier-2 changes; raises :class:`GatedSettingError` instead
    unless the caller has confirmed them, so the store is never left inconsistent.
    """
    rebuilds: list[str] = []
    for key, tiered, o, n in _walk(old, new):
        if tiered.tier is Tier.LOCKED:
            raise LockedSettingError(key, o, n, remedy="lkb reindex --confirm")
        if tiered.tier is Tier.GATED:
            if not allow_gated:
                raise GatedSettingError(key, tiered.forces)
            rebuilds.append(f"{key}: {tiered.forces}")
    return rebuilds


def tier_table(model: type[BaseModel] = Config, prefix: str = "") -> list[tuple[str, Tier, str]]:
    """Every knob that exists, with its tier. Backs ``lkb doctor --tiers``."""
    rows: list[tuple[str, Tier, str]] = []
    for name, info in model.model_fields.items():
        key = f"{prefix}{name}"
        ann = info.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            rows.extend(tier_table(ann, f"{key}."))
        else:
            t = _tier_of(model, name)
            rows.append((key, t.tier, t.forces))
    return rows


__all__ = [
    "CONFIG_FILENAME",
    "CONFIG_VERSION",
    "BudgetConfig",
    "ChatConfig",
    "ChunkingConfig",
    "Config",
    "EmbeddingsConfig",
    "ObsConfig",
    "ParsingConfig",
    "Profile",
    "ResolutionConfig",
    "RetrievalConfig",
    "StoreConfig",
    "Tier",
    "Tiered",
    "check_transition",
    "find_config",
    "load_config",
    "load_profile",
    "tier_table",
]
