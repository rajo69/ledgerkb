"""Metadata extraction — the five fields the brief names.

``title``, ``published_at``, ``doc_type``, ``meeting_or_project`` and the source
URL. Entirely deterministic: no model is involved at this stage, so ingest runs
offline and costs nothing.

Every field that cannot be found is **reported as a miss**, never silently left
null. A null that nobody noticed is how a corpus quietly develops a hole; the
L1 gate asks for 90% coverage precisely because the remaining 10% has to be
visible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ledgerkb.core.config import Profile
from ledgerkb.core.ports import ParsedDocument

# 11 March 2026 · 11 Mar 2026 · March 11, 2026
_LONG_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\b",
    re.IGNORECASE,
)
_LONG_DATE_US = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")   # UK order: D/M/Y

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1
    )
}

# "Planning Committee", "Cabinet", "Attercliffe Regeneration Programme"
_MEETING = re.compile(
    r"\b((?:[A-Z][\w'&-]*\s+){0,4}"
    r"(?:Committee|Cabinet|Board|Council|Panel|Sub-Committee|Working Group|"
    r"Programme|Project|Partnership|Forum|Task Force))\b"
)

_DOC_TYPE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("minutes", ("minutes", "minute", "meeting record")),
    ("agenda", ("agenda",)),
    ("register", ("register", "risk log", "action log", "action tracker")),
    ("policy", ("policy", "strategy", "framework", "guidance", "terms of reference")),
    ("report", ("report", "review", "assessment", "briefing", "appraisal")),
    ("decision_notice", ("decision notice", "decision record")),
    ("committee_paper", ("committee paper", "cabinet paper")),
    ("email", ("email", "e-mail")),
    ("note", ("note", "memo", "memorandum")),
)

REQUIRED_FIELDS = ("title", "published_at", "doc_type", "meeting_or_project", "uri")


@dataclass
class DocumentMetadata:
    """What was found, and what was not."""

    title: str | None = None
    published_at: date | None = None
    doc_type: str | None = None
    meeting_or_project: str | None = None
    uri: str | None = None
    authors: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        found = sum(1 for f in REQUIRED_FIELDS if getattr(self, f) not in (None, "", []))
        return found / len(REQUIRED_FIELDS)


def extract_metadata(
    doc: ParsedDocument,
    *,
    filename: str | None = None,
    uri: str | None = None,
    profile: Profile | None = None,
) -> DocumentMetadata:
    """Pull the five fields from the parser output, filename and leading text.

    Only the head of the document is searched for a date. Council papers put the
    meeting date near the top and then cite a dozen other dates in the body;
    scanning everything would reliably pick the wrong one.
    """
    profile = profile or Profile()
    head = doc.text[:4000]
    name = filename or ""

    meta = DocumentMetadata(uri=uri)

    meta.title = doc.title or (doc.headings[0].text if doc.headings else None)
    if not meta.title and name:
        meta.title = Path(name).stem.replace("_", " ").replace("-", " ").strip() or None

    meta.published_at = doc.published_at or _find_date(name) or _find_date(head)

    meta.doc_type = _find_doc_type(name, meta.title or "", head, profile)
    meta.meeting_or_project = _find_meeting(meta.title or "", head)
    meta.authors = list(doc.authors)

    meta.misses = [
        f for f in REQUIRED_FIELDS if getattr(meta, f) in (None, "", [])
    ]
    return meta


def _find_date(text: str) -> date | None:
    if not text:
        return None

    if m := _ISO_DATE.search(text):
        return _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    if m := _LONG_DATE.search(text):
        return _safe(int(m.group(3)), _MONTHS[m.group(2).lower()[:3]], int(m.group(1)))

    if m := _LONG_DATE_US.search(text):
        return _safe(int(m.group(3)), _MONTHS[m.group(1).lower()[:3]], int(m.group(2)))

    if m := _SLASH_DATE.search(text):
        # Day-first. The corpus is British; guessing month-first would silently
        # relabel the 3rd of April as the 4th of March.
        return _safe(int(m.group(3)), int(m.group(2)), int(m.group(1)))

    return None


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


# Last resort, when nothing in the text names a document type. The container
# format is a real signal — a spreadsheet of rows is a register whatever it is
# called — but it is weaker than a stated type, so it is only consulted after
# the wording has had its chance.
_FORMAT_FALLBACK: tuple[tuple[tuple[str, ...], str], ...] = (
    ((".csv", ".tsv", ".xlsx", ".xlsm", ".json", ".jsonl"), "register"),
    ((".eml", ".mbox"), "email"),
    ((".txt", ".log"), "note"),
    ((".pdf", ".docx", ".pptx", ".md", ".markdown", ".html", ".htm"), "report"),
)


def _find_doc_type(filename: str, title: str, head: str, profile: Profile) -> str | None:
    """Filename and title first — they are curated; body text is incidental."""
    allowed = set(profile.doc_types)
    haystacks = (filename.lower(), title.lower(), head[:600].lower())

    for haystack in haystacks:
        if not haystack:
            continue
        for doc_type, hints in _DOC_TYPE_HINTS:
            if doc_type not in allowed:
                continue
            if any(hint in haystack for hint in hints):
                return doc_type

    suffix = Path(filename).suffix.lower()
    for suffixes, doc_type in _FORMAT_FALLBACK:
        if suffix in suffixes and doc_type in allowed:
            return doc_type
    return None


def _find_meeting(title: str, head: str) -> str | None:
    for haystack in (title, head[:600]):
        if m := _MEETING.search(haystack):
            return " ".join(m.group(1).split())
    return None


def coverage_report(metas: list[DocumentMetadata]) -> dict[str, float]:
    """Per-field coverage across a corpus. Backs the L1 gate's 90% threshold."""
    if not metas:
        return {f: 0.0 for f in REQUIRED_FIELDS}
    return {
        f: sum(1 for m in metas if getattr(m, f) not in (None, "", [])) / len(metas)
        for f in REQUIRED_FIELDS
    }


__all__ = [
    "REQUIRED_FIELDS",
    "DocumentMetadata",
    "coverage_report",
    "extract_metadata",
]
