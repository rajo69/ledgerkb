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
from rich.markup import escape
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
from ledgerkb.core.models import Source, Workspace
from ledgerkb.index.embed import embed_workspace, guard_embedding_space
from ledgerkb.index.hybrid import explain as explain_hits
from ledgerkb.index.hybrid import search as hybrid_search
from ledgerkb.ingest.metadata import coverage_report
from ledgerkb.ingest.pipeline import IngestPipeline
from ledgerkb.providers.factory import build_embedder
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
provider = "local"                              # fastembed, in-process, no API key
model = "mixedbread-ai/mxbai-embed-large-v1"    # Apache-2.0
dimensions = 1024          # LOCKED after the first index build

[chunking]
max_tokens = 512           # GATED: changing it forces a full re-chunk and re-index
overlap = 64               # GATED
structure_first = true     # GATED
contextual_headers = false # off until the A/B earns the cost

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


def safe(value: object, limit: int | None = None) -> str:
    """Neutralise Rich markup in anything a document controls.

    Console output is styled with Rich markup, and every string below that came
    out of an ingested file is attacker-controlled under this project's own
    threat model. Left unescaped, a document containing ``[bold red]APPROVED[/]``
    restyles our output, and a stray ``[/]`` raises MarkupError and kills the
    command outright. Quarantined spans make the point concrete: they are
    printed *because* they are adversarial.
    """
    text = str(value)
    if limit is not None and len(text) > limit:
        text = text[:limit]
    return escape(text)


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

        _report_embedding_space(store, cfg)

        counts = store.counts()
        table = Table(show_header=False, box=None, pad_edge=False)
        for name, n in counts.items():
            table.add_row(f"  {name}", f"[dim]{n}[/]")
        console.print(table)
    finally:
        store.close()


def _report_embedding_space(store: SqliteStore, cfg: Config) -> None:
    """What the vectors were actually made with, next to what is configured.

    The index path refuses a mismatch, so this exists to show it coming rather
    than to catch it. A store that has never been indexed says nothing.
    """
    spaces = store.embedding_spaces()
    if not spaces:
        return

    configured = (cfg.embeddings.model, cfg.embeddings.dimensions)
    for _, model, dims in spaces:
        line = f"vectors  {safe(model)}  [dim]{dims} dims[/]"
        if (model, dims) == configured:
            console.print(line)
            continue
        console.print(f"{line}  [yellow]not what is configured[/]")
        console.print(
            f"         configured: {safe(cfg.embeddings.model)} "
            f"({cfg.embeddings.dimensions} dims)"
        )
        console.print(
            "         [dim]lkb index refuses this until you run "
            "lkb index --rebuild[/]"
        )


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


# --- L1 commands -------------------------------------------------------------


def _open() -> tuple[Config, SqliteStore]:
    cfg_path = find_config()
    if cfg_path is None:
        err.print(f"[yellow]no {CONFIG_FILENAME} found.[/] Run [bold]lkb init[/] first.")
        raise typer.Exit(code=1)
    try:
        cfg = load_config(cfg_path)
    except ConfigError as exc:
        _fail(exc)
    store = SqliteStore(cfg_path.parent / cfg.store.path)
    store.migrate()
    return cfg, store


def _default_workspace(store: SqliteStore, cfg: Config) -> Workspace:
    row = store.db.execute("SELECT id FROM workspace ORDER BY created_at LIMIT 1").fetchone()
    if row:
        ws = store.get_workspace(row["id"])
        if ws is not None:
            return ws
    ws = Workspace(name="default", profile=cfg.profile)
    store.add_workspace(ws)
    return ws


@app.command()
def ingest(
    path: Annotated[Path, typer.Argument(help="File, directory or .zip to ingest.")],
    source_label: Annotated[
        str, typer.Option("--source", help="Name for this source.")
    ] = "local",
) -> None:
    """Read, parse, sanitise and chunk documents. No network, no API key."""
    cfg, store = _open()
    try:
        ws = _default_workspace(store, cfg)

        row = store.db.execute(
            "SELECT id FROM source WHERE workspace_id = ? AND label = ?", (ws.id, source_label)
        ).fetchone()
        if row:
            source = Source(id=row["id"], workspace_id=ws.id, kind="upload", label=source_label)
        else:
            source = Source(workspace_id=ws.id, kind="upload", label=source_label)
            store.add_source(source)

        try:
            report = IngestPipeline(store, cfg).ingest_path(path, ws.id, source)
        except LedgerKBError as exc:
            _fail(exc)

        table = Table(box=None, pad_edge=False)
        table.add_column("document")
        table.add_column("status")
        table.add_column("chunks", justify="right")
        table.add_column("parser")
        for o in report.outcomes:
            colour = {"ingested": "green", "unchanged": "dim", "failed": "red"}[o.status]
            table.add_row(
                safe(o.external_id, 60),
                f"[{colour}]{o.status}[/]",
                str(o.chunks) if o.chunks else "",
                safe(o.parser or ""),
            )
        console.print(table)

        console.print(
            f"\n[bold]{len(report.ingested)} ingested[/], {len(report.unchanged)} unchanged, "
            f"{len(report.failed)} failed - {report.total_chunks} chunks"
        )

        if report.total_quarantined:
            console.print(
                f"[yellow]{report.total_quarantined} quarantined span(s)[/] "
                "- stored and excluded from prompts, not deleted"
            )

        # Failures are named. Never a silent count.
        for o in report.failed:
            err.print(f"  [red]failed[/] {safe(o.external_id)}: {safe(o.error)}")

        metas = [o.metadata for o in report.ingested if o.metadata]
        if metas:
            console.print("\n[bold]metadata coverage[/]")
            for name, pct in coverage_report(metas).items():
                colour = "green" if pct >= 0.9 else "yellow"
                console.print(f"  {name:20} [{colour}]{pct:.0%}[/]")
    finally:
        store.close()


@app.command()
def docs() -> None:
    """List ingested documents."""
    cfg, store = _open()
    try:
        ws = _default_workspace(store, cfg)
        documents = store.list_documents(ws.id)
        if not documents:
            console.print("[dim]no documents yet - run [bold]lkb ingest <path>[/][/]")
            return

        table = Table(box=None, pad_edge=False)
        for col in ("id", "title", "type", "date", "meeting/project", "chunks"):
            table.add_column(col)
        for d in documents:
            version = store.latest_version_for(d.id)
            n = len(store.chunks_for_version(version.id)) if version else 0
            table.add_row(
                d.id[:8],
                safe(d.title or "", 40),
                safe(d.doc_type) if d.doc_type else "[dim]-[/]",
                str(d.published_at) if d.published_at else "[dim]-[/]",
                safe(d.meeting_or_project, 30) if d.meeting_or_project else "[dim]-[/]",
                str(n),
            )
        console.print(table)
    finally:
        store.close()


@app.command()
def chunks(
    doc_id: Annotated[str, typer.Argument(help="Document id, or a unique prefix.")],
    verify: Annotated[
        bool, typer.Option("--verify", help="Re-slice every chunk from the stored text.")
    ] = False,
) -> None:
    """Show a document's chunks, optionally re-checking every offset."""
    _, store = _open()
    try:
        row = store.db.execute(
            "SELECT id FROM document WHERE id LIKE ?", (f"{doc_id}%",)
        ).fetchone()
        if not row:
            err.print(f"[yellow]no document matching {doc_id!r}[/]")
            raise typer.Exit(code=1)

        version = store.latest_version_for(row["id"])
        if version is None:
            err.print("[yellow]document has no version[/]")
            raise typer.Exit(code=1)

        rows = store.chunks_for_version(version.id)
        console.print(f"[bold]{len(rows)} chunks[/] from version {version.id[:8]} "
                      f"[dim]({version.parser}, quality {version.parse_quality:.2f})[/]")

        if verify:
            text = version.text or ""
            bad = [c for c in rows if text[c.char_start : c.char_end] != c.text]
            if bad:
                err.print(f"[bold red]{len(bad)} chunk(s) do not slice back[/]")
                for c in bad[:5]:
                    err.print(f"  ordinal {c.ordinal} at {c.char_start}:{c.char_end}")
                raise typer.Exit(code=1)
            console.print("[green]all chunks slice back byte-identical[/]")

        for c in rows[:40]:
            path = safe(" > ".join(c.heading_path)) if c.heading_path else "[dim]no heading[/]"
            page = f" p.{c.page_from}" if c.page_from else ""
            console.print(f"\n[bold]{c.ordinal}[/] {path}{page} "
                          f"[dim]{c.char_start}:{c.char_end} ~{c.token_count} tokens[/]")
            preview = safe(c.text[:200].replace("\n", " "))
            console.print(f"  {preview}{'...' if len(c.text) > 200 else ''}")

        quarantined = store.quarantine_for_version(version.id)
        if quarantined:
            console.print(f"\n[yellow]{len(quarantined)} quarantined span(s)[/]")
            for q in quarantined[:10]:
                console.print(f"  [dim]{safe(q['reason'])}[/] {safe(q['text'], 80)!r}")
    finally:
        store.close()


if __name__ == "__main__":  # pragma: no cover
    app()


# --- L2 commands -------------------------------------------------------------


def _embedder(cfg: Config, *, required: bool):  # noqa: ANN202 - returns an Embedder port
    """Build the embedder, or explain in one line why search is sparse-only."""
    try:
        return build_embedder(cfg)
    except LedgerKBError as exc:
        if required:
            _fail(exc)
        err.print(f"[yellow]dense retrieval unavailable[/] {exc}")
        return None


@app.command()
def index(
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Re-embed every chunk, not just new ones.")
    ] = False,
) -> None:
    """Embed the chunks. Local by default, so no API key is needed."""
    cfg, store = _open()
    try:
        ws = _default_workspace(store, cfg)
        if rebuild:
            store.clear_embeddings(ws.id)

        embedder = _embedder(cfg, required=True)
        pending = len(store.chunks_missing_embeddings(ws.id))

        if not pending:
            # Still checked, because a model swapped on a fully embedded
            # workspace has nothing to embed and is the case most worth
            # catching: without this it reports success and changes nothing,
            # while every later query is vectorised by the wrong model.
            try:
                guard_embedding_space(store, embedder, ws.id, pending=0)
            except LedgerKBError as exc:
                _fail(exc)
            console.print("[dim]every current chunk already has a vector[/]")
            return

        console.print(
            f"embedding [bold]{pending}[/] chunks with [bold]{cfg.embeddings.model}[/] "
            f"[dim]({cfg.embeddings.dimensions} dims, {cfg.embeddings.provider})[/]"
        )
        try:
            with console.status("embedding..."):
                report = embed_workspace(store, cfg, embedder, ws.id)
        except LedgerKBError as exc:
            _fail(exc)

        console.print(
            f"[green]{report.embedded} embedded[/] in {report.batches} batches"
        )
        # Superseded chunks are deliberately not embedded: retrieval hides them,
        # so vectorising them would be paying for something never returned.
        console.print("[dim]superseded versions are kept, but not indexed[/]")
    finally:
        store.close()


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="What to look for.")],
    k: Annotated[int, typer.Option("--k", help="How many results.")] = 8,
    explain: Annotated[
        bool, typer.Option("--explain", help="Show each arm's rank and the fused score.")
    ] = False,
    arms: Annotated[
        str, typer.Option("--arms", help="Comma-separated: dense,sparse,headings.")
    ] = "dense,sparse,headings",
    json_out: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Hybrid retrieval. Retrieval only — grounded answering with verified quotes is L3."""
    import json as _json

    cfg, store = _open()
    try:
        ws = _default_workspace(store, cfg)
        wanted = tuple(a.strip() for a in arms.split(",") if a.strip())
        embedder = _embedder(cfg, required=False) if "dense" in wanted else None

        result = hybrid_search(
            store, cfg, query, embedder=embedder, workspace_id=ws.id, k=k, arms=wanted
        )

        if json_out:
            console.print_json(_json.dumps(explain_hits(result)))
            return

        if not result.hits:
            console.print("[yellow]nothing matched[/] - the corpus may not be indexed yet")
            return

        sizes = ", ".join(f"{name} {len(hits)}" for name, hits in sorted(result.arms.items()))
        console.print(f"[dim]{sizes} -> {len(result.hits)} shown[/]")
        console.print()

        for position, hit in enumerate(result.hits, start=1):
            path = safe(" > ".join(hit.heading_path)) if hit.heading_path else "[dim]no heading[/]"
            page = f" p.{hit.page_from}" if hit.page_from else ""
            console.print(f"[bold]{position}.[/] {path}{page}  [dim]{hit.score:.4f}[/]")
            console.print(f"   {safe(hit.text[:220].replace(chr(10), ' '))}")
            if explain:
                ranks = "  ".join(f"{name}#{r}" for name, r in hit.ranks.items()) or "-"
                console.print(f"   [dim]{hit.chunk_id[:8]}  {ranks}[/]")
            console.print()
    finally:
        store.close()
