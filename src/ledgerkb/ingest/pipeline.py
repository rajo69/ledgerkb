"""The L1 pipeline: read → dedupe → parse → sanitise → chunk → store.

Stages 1-6 of the eleven. No LLM, no network, no credentials.

Two behaviours are load-bearing:

* **Dedupe by content hash comes before parsing.** An unchanged document costs
  one hash, not one parse. This is what makes refresh nearly free later.
* **A failure names its document and the run continues.** A parse error on one
  file must leave the other fifty-five usable; all-or-nothing ingest of a
  council's document set is useless in practice.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from ledgerkb.core.config import Config
from ledgerkb.core.errors import BudgetExceededError, LedgerKBError, ParseError
from ledgerkb.core.models import Document, DocumentVersion, IngestRun, Source
from ledgerkb.core.ports import ParseHint
from ledgerkb.ingest.chunk import chunk_document
from ledgerkb.ingest.metadata import DocumentMetadata, extract_metadata
from ledgerkb.ingest.parsers.registry import ParserRegistry, guess_mime, registry
from ledgerkb.ingest.readers.fs import FetchedDocument, FilesystemReader, sha256
from ledgerkb.ingest.sanitise import sanitise
from ledgerkb.storage.sqlite.store import SqliteStore


@dataclass
class DocumentOutcome:
    """What happened to one document. Every field is reportable."""

    external_id: str
    status: str
    """ingested | unchanged | failed"""
    document_id: str | None = None
    version_id: str | None = None
    chunks: int = 0
    quarantined: int = 0
    metadata: DocumentMetadata | None = None
    parser: str | None = None
    error: str | None = None


@dataclass
class IngestReport:
    run: IngestRun
    outcomes: list[DocumentOutcome] = field(default_factory=list)

    @property
    def ingested(self) -> list[DocumentOutcome]:
        return [o for o in self.outcomes if o.status == "ingested"]

    @property
    def unchanged(self) -> list[DocumentOutcome]:
        return [o for o in self.outcomes if o.status == "unchanged"]

    @property
    def failed(self) -> list[DocumentOutcome]:
        return [o for o in self.outcomes if o.status == "failed"]

    @property
    def total_chunks(self) -> int:
        return sum(o.chunks for o in self.outcomes)

    @property
    def total_quarantined(self) -> int:
        return sum(o.quarantined for o in self.outcomes)


class IngestPipeline:
    def __init__(
        self,
        store: SqliteStore,
        config: Config,
        parsers: ParserRegistry | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.parsers = parsers or registry

    def ingest_path(
        self,
        target: str | Path,
        workspace_id: str,
        source: Source,
        trigger: str = "manual",
    ) -> IngestReport:
        reader = FilesystemReader(workspace_id=workspace_id, source_id=source.id)
        return self.ingest(reader.read(target), workspace_id, source, trigger)

    def ingest(
        self,
        fetched: Iterable[FetchedDocument],
        workspace_id: str,
        source: Source,
        trigger: str = "manual",
    ) -> IngestReport:
        run = IngestRun(workspace_id=workspace_id, source_id=source.id, trigger=trigger)  # type: ignore[arg-type]
        self.store.start_run(run)
        report = IngestReport(run=run)

        for outcome in self._process_all(fetched, workspace_id):
            report.outcomes.append(outcome)

        run.docs_seen = len(report.outcomes)
        run.docs_new = len(report.ingested)
        run.docs_changed = len(report.ingested)
        run.stats = {
            "chunks": report.total_chunks,
            "quarantined": report.total_quarantined,
            "failed": len(report.failed),
        }
        self.store.finish_run(run)
        return report

    def _process_all(
        self, fetched: Iterable[FetchedDocument], workspace_id: str
    ) -> Iterator[DocumentOutcome]:
        for seen, item in enumerate(fetched, start=1):
            if seen > self.config.budget.max_docs_per_run:
                # The ceiling aborts. There is no "proceed anyway" setting.
                raise BudgetExceededError(
                    f"Run exceeded max_docs_per_run={self.config.budget.max_docs_per_run}. "
                    "Raise the ceiling deliberately, or narrow the source."
                )
            yield self._process(item, workspace_id)

    def _process(self, item: FetchedDocument, workspace_id: str) -> DocumentOutcome:
        doc = item.document
        try:
            return self._process_inner(item, workspace_id)
        except ParseError as exc:
            return DocumentOutcome(doc.external_id, "failed", error=str(exc))
        except LedgerKBError as exc:
            return DocumentOutcome(doc.external_id, "failed", error=str(exc))
        except Exception as exc:
            # Unexpected, but still only costs this one document. The type is
            # named so the report is diagnosable rather than just red.
            return DocumentOutcome(
                doc.external_id, "failed", error=f"{type(exc).__name__}: {exc}"
            )

    def _process_inner(self, item: FetchedDocument, workspace_id: str) -> DocumentOutcome:
        doc: Document = item.document
        content_hash = sha256(item.data)

        doc_id = self.store.upsert_document(doc)

        # Stage 3 — dedupe before parse. An unchanged document costs one hash.
        if self.store.find_version_by_hash(doc_id, content_hash) is not None:
            return DocumentOutcome(doc.external_id, "unchanged", document_id=doc_id)

        filename = Path(doc.external_id).name
        hint = ParseHint(
            mime=guess_mime(filename),
            filename=filename,
            uri=doc.uri,
            density_probe=self.config.parsing.density_probe,
        )

        parsed = self.parsers.parse(item.data, hint)           # stage 4
        clean = sanitise(parsed)                                # stage 5

        meta = extract_metadata(
            clean.doc,
            filename=filename,
            uri=doc.uri,
            profile=self.config.resolved_profile,
        )

        version = DocumentVersion(
            document_id=doc_id,
            version_no=self.store.next_version_no(doc_id),
            content_hash=content_hash,
            text_hash=sha256(clean.text.encode("utf-8")),
            mime=parsed.mime,
            bytes=len(item.data),
            page_count=parsed.page_count,
            parser=parsed.parser,
            parse_quality=parsed.parse_quality,
            text=clean.text,
            parse_warnings=[w for w in parsed.warnings if not w.startswith("hidden:")],
            metadata_misses=meta.misses,
        )
        self.store.add_version(version)

        # Metadata found here belongs on the document, which is what gets
        # filtered and displayed.
        self.store.upsert_document(
            doc.model_copy(
                update={
                    "id": doc_id,
                    "title": meta.title or doc.title,
                    "doc_type": meta.doc_type,
                    "meeting_or_project": meta.meeting_or_project,
                    "published_at": meta.published_at,
                    "authors": meta.authors,
                    "current_version_id": version.id,
                }
            )
        )

        self.store.add_quarantine(version.id, clean.quarantine)

        chunks = chunk_document(                                # stage 6
            clean.doc, workspace_id, version.id, self.config.chunking
        )
        self.store.add_chunks(chunks)

        return DocumentOutcome(
            external_id=doc.external_id,
            status="ingested",
            document_id=doc_id,
            version_id=version.id,
            chunks=len(chunks),
            quarantined=len(clean.quarantine),
            metadata=meta,
            parser=parsed.parser,
        )


__all__ = ["DocumentOutcome", "IngestPipeline", "IngestReport"]
