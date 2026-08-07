"""``lkb`` — the command line.

L0 ships three commands: ``init``, ``version`` and ``doctor``. All three work
with **zero API keys**, which is the L0 gate and also the property that keeps
the offline CI workflow honest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ledgerkb import __version__
from ledgerkb.core.config import (
    CONFIG_FILENAME,
    Config,
    Tier,
    check_transition,
    find_config,
    load_config,
    tier_table,
)
from ledgerkb.core.errors import ConfigError, LedgerKBError
from ledgerkb.storage.sqlite.store import SqliteStore

app = typer.Typer(
    name="lkb",
    help="Turn scattered documents into a knowledge base that maintains a position over time.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err = Console(stderr=True)

DEFAULT_CONFIG = """\
config_version = 1
profile = "default"

[store]
backend = "sqlite"
path = ".lkb/store.db"

[chat]
provider = "openai_compatible"
base_url = "https://openrouter.ai/api/v1"
model = "qwen/qwen3-235b-a22b"
api_key_env = "OPENROUTER_API_KEY"

[chat.cheap]
model = "deepseek/deepseek-v3.2"

[embeddings]
provider = "openai_compatible"
model = "qwen/qwen3-embedding-8b"
dimensions = 1024          # LOCKED after the first index build

[chunking]
max_tokens = 512
overlap = 64
structure_first = true

[retrieval]
dense_k = 50
sparse_k = 50
rrf_k = 60
rerank_to = 8

[resolution]
trigram = 0.85
grey_band = [0.80, 0.92]
auto_merge = false

[parsing]
density_probe = 0.6
tier1 = "docling"

[budget]
max_cost_usd_per_run = 5.0
max_docs_per_run = 1000

[obs]
otlp_endpoint = ""
semconv_version = "1.42.0"
"""

DEFAULT_PROFILE = """\
# The default profile ships generic. Domain knowledge belongs in a profile,
# never in a code branch.

entity_types = ["Person","Organisation","Project","Meeting","Decision",
                "Action","Risk","Document","Location","Policy"]
predicates   = ["attended","owns","was_made_at","is_assigned_to","relates_to",
                "threatens","mentions","supersedes","depends_on","supports"]
doc_types    = ["minutes","report","register","policy","email","note"]

[staleness]
default_days = 180

[extraction]
hints = ""
"""


def _fail(exc: Exception) -> None:
    err.print(f"[bold red]error[/] {exc}")
    raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(__version__)


@app.command()
def init(
    directory: Annotated[Path, typer.Argument(help="Where to initialise.")] = Path("."),
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing config.")] = False,
) -> None:
    """Create ``ledgerkb.toml``, ``profiles/default.toml`` and an empty store."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    cfg_path = directory / CONFIG_FILENAME

    if cfg_path.exists() and not force:
        err.print(f"[yellow]{cfg_path} already exists.[/] Pass --force to overwrite.")
        raise typer.Exit(code=1)

    cfg_path.write_text(DEFAULT_CONFIG, encoding="utf-8")

    profiles = directory / "profiles"
    profiles.mkdir(exist_ok=True)
    profile_path = profiles / "default.toml"
    if not profile_path.exists():
        profile_path.write_text(DEFAULT_PROFILE, encoding="utf-8")

    try:
        cfg = load_config(cfg_path)
        store = SqliteStore(directory / cfg.store.path)
        applied = store.migrate()
        store.stamp_config(cfg.build_receipt())
        store.close()
    except LedgerKBError as exc:
        _fail(exc)

    console.print(f"[green]initialised[/] {directory}")
    console.print(f"  config   {cfg_path}")
    console.print(f"  profile  {profile_path}")
    console.print(f"  store    {directory / cfg.store.path} (schema v{applied})")
    console.print("\nNo API key is needed for [bold]lkb doctor[/].")


@app.command()
def doctor(
    tiers: Annotated[bool, typer.Option("--tiers", help="List every knob and its tier.")] = False,
) -> None:
    """Check the environment, config and store. Never needs an API key."""
    cfg_path = find_config()
    if cfg_path is None:
        err.print(
            f"[yellow]no {CONFIG_FILENAME} found[/] in this directory or any parent. "
            "Run [bold]lkb init[/] first."
        )
        raise typer.Exit(code=1)

    try:
        cfg = load_config(cfg_path)
    except ConfigError as exc:
        _fail(exc)

    console.print(f"[bold]ledgerkb[/] {__version__}")
    console.print(f"config   {cfg_path}  [dim](config_version {cfg.config_version})[/]")
    console.print(f"profile  {cfg.resolved_profile.name}  "
                  f"[dim]{len(cfg.resolved_profile.entity_types)} entity types, "
                  f"{len(cfg.resolved_profile.predicates)} predicates[/]")

    if tiers:
        _print_tiers()
        return

    _check_store(cfg, cfg_path.parent)
    _check_credentials(cfg)

    console.print("\n[green]ok[/] - the deterministic path is fully operational.")


def _check_store(cfg: Config, root: Path) -> None:
    db_path = root / cfg.store.path
    if not db_path.exists():
        err.print(f"[yellow]store missing[/] at {db_path} - run [bold]lkb init[/]")
        raise typer.Exit(code=1)

    store = SqliteStore(db_path)
    try:
        console.print(f"store    {db_path}  [dim](schema v{store.schema_version()})[/]")

        stamped = store.stamped_config()
        if stamped:
            try:
                previous = Config.model_validate(stamped)
                rebuilds = check_transition(previous, cfg, allow_gated=True)
            except ConfigError as exc:
                _fail(exc)
            else:
                if rebuilds:
                    console.print("\n[yellow]config changed since the store was built[/]")
                    for line in rebuilds:
                        console.print(f"  * {line}")

        counts = store.counts()
        table = Table(show_header=False, box=None, pad_edge=False)
        for name, n in counts.items():
            table.add_row(f"  {name}", f"[dim]{n}[/]")
        console.print(table)
    finally:
        store.close()


def _check_credentials(cfg: Config) -> None:
    """Missing keys are reported, never fatal — everything deterministic still runs."""
    import os

    key = os.environ.get(cfg.chat.api_key_env)
    state = "[green]set[/]" if key else "[dim]unset[/]"
    console.print(f"\nchat     {cfg.chat.model}  [dim]via {cfg.chat.provider}[/]")
    console.print(f"         {cfg.chat.api_key_env}: {state}")
    console.print(f"embed    {cfg.embeddings.model}  [dim]{cfg.embeddings.dimensions} dims "
                  "(locked after first index)[/]")
    if not key:
        console.print(
            "[dim]         no key set - ingest, chunking, retrieval and every eval "
            "still run.[/]"
        )


def _print_tiers() -> None:
    table = Table(title="Tunability", box=None)
    table.add_column("knob")
    table.add_column("tier")
    table.add_column("changing it forces")
    colour = {Tier.FREE: "green", Tier.GATED: "yellow", Tier.LOCKED: "red"}
    for key, tier, forces in tier_table():
        if key.startswith("resolved_profile."):
            continue
        table.add_row(key, f"[{colour[tier]}]{tier.value}[/]", forces or "-")
    console.print(table)
    console.print(
        "\n[dim]Tier-4 invariants — quote verification, zero tools in extraction, the "
        "append-only ledger, unmerged contradictions, required evidence, the closed "
        "predicate schema, path-traversal guards, budget aborts have no key at any "
        "level, by design.[/]"
    )


if __name__ == "__main__":  # pragma: no cover
    app()
