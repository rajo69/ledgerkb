"""The invariants must be impossible to violate, not merely discouraged."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from ledgerkb.core.models import Answer, Assertion, Chunk, Claim, Evidence

EV = [Evidence(chunk_id="c1", quote="the budget was set at £2.4m")]


def _assertion(**kw) -> Assertion:
    base = {
        "workspace_id": "ws",
        "predicate": "owns",
        "claim_text": "The council owns the Attercliffe site.",
        "modality": "explicit",
        "evidence": EV,
    }
    return Assertion(**{**base, **kw})


class TestEvidenceRequired:
    def test_assertion_without_evidence_cannot_be_constructed(self) -> None:
        with pytest.raises(ValidationError):
            _assertion(evidence=[])

    def test_evidence_quote_cannot_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            Evidence(chunk_id="c1", quote="")

    def test_assertion_with_evidence_is_fine(self) -> None:
        assert len(_assertion().evidence) == 1


class TestInferenceIsNeverCertain:
    def test_inferred_at_full_confidence_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"confidence < 1\.0"):
            _assertion(modality="inferred", confidence=1.0)

    def test_inferred_below_one_is_accepted(self) -> None:
        assert _assertion(modality="inferred", confidence=0.7).confidence == 0.7

    def test_explicit_may_be_certain(self) -> None:
        assert _assertion(modality="explicit", confidence=1.0).confidence == 1.0

    def test_validate_assignment_catches_a_later_demotion(self) -> None:
        a = _assertion(modality="explicit", confidence=1.0)
        with pytest.raises(ValidationError):
            a.modality = "inferred"


class TestInvalidationCoherence:
    def test_invalid_at_requires_a_reason(self) -> None:
        from ledgerkb.core.models import utcnow

        with pytest.raises(ValidationError, match="invalidation_reason"):
            _assertion(invalid_at=utcnow())

    def test_reason_requires_invalid_at(self) -> None:
        with pytest.raises(ValidationError, match="invalid_at"):
            _assertion(invalidation_reason="superseded")


class TestWorldTime:
    def test_valid_to_cannot_precede_valid_from(self) -> None:
        with pytest.raises(ValidationError, match="precedes"):
            _assertion(valid_from=date(2026, 6, 1), valid_to=date(2026, 1, 1))


class TestChunk:
    def test_inverted_span_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="inverted"):
            Chunk(workspace_id="ws", version_id="v", ordinal=0,
                  char_start=100, char_end=10, text="x")

    def test_embed_text_combines_header_and_body(self) -> None:
        c = Chunk(workspace_id="ws", version_id="v", ordinal=0, char_start=0, char_end=5,
                  text="hello", context_header="A council meeting.")
        assert c.embed_text == "A council meeting.\n\nhello"
        assert c.text == "hello", "text must stay the verbatim span"


class TestAnswer:
    def test_abstention_must_name_its_gaps(self) -> None:
        with pytest.raises(ValidationError, match="name its gaps"):
            Answer(query="who owns the site?", abstained=True)

    def test_abstention_with_gaps_is_fine(self) -> None:
        a = Answer(query="q", abstained=True, gaps=["no documents after March 2026"])
        assert a.gaps

    def test_demoting_a_claim_does_not_mutate_the_original(self) -> None:
        c = Claim(text="t", chunk_id="c1", quote="q", verified=True)
        d = c.demoted()
        assert c.verified is True
        assert d.verified is False
        assert d.modality == "inferred"
