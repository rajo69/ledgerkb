"""Stage 5 — sanitisation and instruction quarantine.

The threat is not a user typing a jailbreak. It is **indirect prompt injection
from an ingested document**: one poisoned file compromising every user whose
query retrieves it.

Two different things happen here, and the difference matters:

* **Invisible text is removed.** Zero-width characters, bidi overrides, control
  characters, text coloured to match its background, ``display:none`` and HTML
  comments are all content that a human reader cannot see. Anything a reader
  cannot see has no business influencing an answer they will read.
* **Instruction-shaped text is kept but quarantined.** It stays in the document
  text — removing it would silently rewrite the record — and is recorded so it
  can be excluded from prompts and surfaced as a finding.

**Keyword guardrails are deliberately not used.** Council minutes are full of
sentences like *"the committee resolved to ignore the previous
recommendation"*, and a blunt trigger-word filter does more damage on this
corpus than the attack it prevents. Detection here requires an instruction verb
*and* a token addressing a model, together, in a short window.

Every removal is offset-mapped, because the guarantee that a chunk slices back
byte-identical from its document is worth more than the convenience of editing
text in place.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field

from ledgerkb.core.ports import ParsedDocument

# --- what counts as invisible ------------------------------------------------

ZERO_WIDTH = {
    "​",  # zero width space
    "‌",  # zero width non-joiner
    "‍",  # zero width joiner
    "⁠",  # word joiner
    "﻿",  # zero width no-break space / BOM
    "᠎",  # mongolian vowel separator
}

BIDI_CONTROLS = {
    "‪", "‫", "‬", "‭", "‮",   # embedding / override
    "⁦", "⁧", "⁨", "⁩",             # isolates
    "؜",                                            # arabic letter mark
}

# Tag characters. Invisible to a reader, and a known channel for smuggling an
# entire instruction past visual review.
TAG_RANGE = range(0xE0000, 0xE0080)


def _is_invisible(ch: str) -> bool:
    if ch in ZERO_WIDTH or ch in BIDI_CONTROLS:
        return True
    if ord(ch) in TAG_RANGE:
        return True
    if ch in "\t\n\r":
        return False
    return unicodedata.category(ch) in {"Cc", "Cf"}


# --- instruction shape -------------------------------------------------------

_ADDRESSES_A_MODEL = (
    r"(?:you|your|assistant|ai\b|a\.?i\.?\b|model|llm|chatbot|chatgpt|claude|gpt|"
    r"system\s+prompt|previous\s+instructions?|above\s+instructions?|"
    r"prior\s+instructions?)"
)
_INSTRUCTION_VERB = (
    r"(?:ignore|disregard|forget|override|bypass|reveal|disclose|print|output|"
    r"repeat|execute|run|follow|obey|comply|respond\s+with|answer\s+with|"
    r"instead\s+say|must\s+say|do\s+not\s+mention|never\s+mention)"
)

# The verb and the address must co-occur within a short window. That is what
# separates an attack from "the committee resolved to ignore the previous
# recommendation", which has the verb but addresses nobody.
_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_addressed_to_model",
        re.compile(
            rf"{_INSTRUCTION_VERB}\W+(?:\w+\W+){{0,4}}?{_ADDRESSES_A_MODEL}",
            re.IGNORECASE,
        ),
    ),
    (
        "instruction_addressed_to_model",
        re.compile(
            rf"{_ADDRESSES_A_MODEL}\W+(?:\w+\W+){{0,3}}?{_INSTRUCTION_VERB}",
            re.IGNORECASE,
        ),
    ),
    (
        "fake_role_marker",
        re.compile(
            r"^[ \t]*(?:#{1,6}[ \t]*)?(?:system|assistant|user|human|instruction[s]?)"
            r"[ \t]*[:>]",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "fake_delimiter",
        re.compile(
            r"(?:<\|[^|>]{1,40}\|>|\[/?INST\]|<</?SYS>>|###\s*end\s+of\s+document)",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration_shape",
        re.compile(
            r"(?:send|post|upload|transmit|exfiltrat\w+)\W+(?:\w+\W+){0,4}?"
            r"(?:https?://|api[_ ]?key|token|credential|password)",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class QuarantineSpan:
    """An instruction-shaped or invisible span, recorded rather than discarded."""

    char_start: int
    char_end: int
    text: str
    reason: str

    def __post_init__(self) -> None:
        if self.char_end < self.char_start:
            raise ValueError("quarantine span is inverted")


@dataclass
class SanitisedDocument:
    """The canonical form of a document.

    ``text`` here is what everything downstream treats as the source: chunk
    offsets index into it, quote verification checks against it, and its hash is
    the version's ``text_hash``. Sanitisation happens once, before any offset is
    taken, so there is exactly one coordinate system.
    """

    doc: ParsedDocument
    quarantine: list[QuarantineSpan] = field(default_factory=list)
    removed_chars: int = 0

    @property
    def text(self) -> str:
        return self.doc.text

    def prompt_safe_text(self) -> str:
        """The text with quarantined spans blanked out.

        Used when building a prompt. The stored text keeps them, because
        silently rewriting the record would be its own kind of dishonesty.
        """
        if not self.quarantine:
            return self.doc.text
        out = list(self.doc.text)
        for span in self.quarantine:
            for i in range(span.char_start, min(span.char_end, len(out))):
                out[i] = " "
        return "".join(out)


class OffsetMap:
    """Maps offsets in the original text to offsets in the cleaned text.

    Sanitisation deletes characters, which shifts everything after them. The
    parser has already recorded page boundaries and heading positions against
    the original, so those have to move with it — otherwise a citation would
    point at the wrong page for the sake of a stripped zero-width space.
    """

    def __init__(self, kept: list[int], new_length: int) -> None:
        self._kept = kept            # original index of each surviving character
        self._new_length = new_length

    def __call__(self, old: int) -> int:
        """Map an original offset forward. Deleted positions map to the next
        surviving character, so a span never collapses onto the wrong side."""
        return min(bisect_right(self._kept, old - 1), self._new_length)


def sanitise(doc: ParsedDocument) -> SanitisedDocument:
    """Strip invisible text, normalise, and quarantine instruction-shaped spans."""
    original = doc.text
    out: list[str] = []
    kept: list[int] = []
    removed: list[tuple[int, int, str, str]] = []   # start, end, text, reason

    run_start: int | None = None
    run_chars: list[str] = []

    def close_run(end: int) -> None:
        nonlocal run_start, run_chars
        if run_start is not None:
            removed.append((run_start, end, "".join(run_chars), "invisible_character"))
            run_start, run_chars = None, []

    for i, ch in enumerate(original):
        if _is_invisible(ch):
            if run_start is None:
                run_start = i
            run_chars.append(ch)
            continue
        close_run(i)
        # NFKC per character, so the map stays exact. Whole-string normalisation
        # can compose across boundaries and there is then no honest way to say
        # which original character a given output position came from.
        folded = unicodedata.normalize("NFKC", ch)
        for out_ch in folded:
            out.append(out_ch)
            kept.append(i)
    close_run(len(original))

    cleaned = "".join(out)
    remap = OffsetMap(kept, len(cleaned))

    quarantine = [
        QuarantineSpan(
            char_start=remap(start),
            char_end=remap(start),      # the text is gone; the span is a point
            text=text,
            reason=reason,
        )
        for start, _end, text, reason in removed
    ]
    quarantine.extend(_find_instruction_spans(cleaned))
    quarantine.extend(_carry_hidden_findings(doc, remap))

    sanitised = doc.model_copy(
        update={
            "text": cleaned,
            "page_offsets": [remap(o) for o in doc.page_offsets],
            "headings": [
                h.model_copy(update={"char_start": remap(h.char_start)})
                for h in doc.headings
            ],
        }
    )
    return SanitisedDocument(
        doc=sanitised,
        quarantine=_merge(quarantine, cleaned),
        removed_chars=len(original) - len(cleaned),
    )


def _find_instruction_spans(text: str) -> list[QuarantineSpan]:
    found: list[QuarantineSpan] = []
    for reason, pattern in _INJECTION_PATTERNS:
        for m in pattern.finditer(text):
            found.append(
                QuarantineSpan(
                    char_start=m.start(),
                    char_end=m.end(),
                    text=m.group(0),
                    reason=reason,
                )
            )
    return found


def _carry_hidden_findings(doc: ParsedDocument, remap: OffsetMap) -> list[QuarantineSpan]:
    """Parsers report hidden text they dropped (white-on-white, display:none,
    HTML comments) as warnings of the form ``hidden:<offset>:<text>``."""
    out: list[QuarantineSpan] = []
    for w in doc.warnings:
        if not w.startswith("hidden:"):
            continue
        _, _, rest = w.partition(":")
        offset_s, _, hidden_text = rest.partition(":")
        try:
            offset = remap(int(offset_s))
        except ValueError:
            continue
        out.append(
            QuarantineSpan(
                char_start=offset,
                char_end=offset,
                text=hidden_text,
                reason="hidden_text",
            )
        )
    return out


def _merge(spans: list[QuarantineSpan], text: str) -> list[QuarantineSpan]:
    """Overlapping detections collapse into one finding, so a span that trips
    three patterns is reported once rather than inflating the count.

    The merged span is re-sliced from the text rather than inheriting either
    original's ``text``. A span whose recorded text does not match its own
    offsets is worse than no span at all — it would be reported to an operator
    as evidence of something the document does not say there.
    """
    if not spans:
        return []
    spans = sorted(spans, key=lambda s: (s.char_start, s.char_end))
    merged = [spans[0]]
    for s in spans[1:]:
        last = merged[-1]
        if s.char_start <= last.char_end and s.reason == last.reason:
            if s.char_end > last.char_end:
                merged[-1] = QuarantineSpan(
                    char_start=last.char_start,
                    char_end=s.char_end,
                    text=text[last.char_start : s.char_end],
                    reason=last.reason,
                )
        else:
            merged.append(s)
    return merged


__all__ = ["OffsetMap", "QuarantineSpan", "SanitisedDocument", "sanitise"]
