"""The fakes are the default for every test, so their determinism is itself a
tested property — a flaky fake would poison the whole suite."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from ledgerkb.core.errors import ProviderError
from ledgerkb.providers.fake import FakeChatModel, FakeEmbedder, FakeReranker, canned

MSGS = [{"role": "user", "content": "summarise the Attercliffe decision"}]


class Summary(BaseModel):
    title: str
    sentences: int


class TestFakeChat:
    def test_completion_is_stable_across_instances(self) -> None:
        assert FakeChatModel().complete(MSGS) == FakeChatModel().complete(MSGS)

    def test_different_prompts_differ(self, chat: FakeChatModel) -> None:
        assert chat.complete(MSGS) != chat.complete([{"role": "user", "content": "other"}])

    def test_canned_response_wins_on_substring(self) -> None:
        m = FakeChatModel(responses={"Attercliffe": "the regeneration was approved"})
        assert m.complete(MSGS) == "the regeneration was approved"

    def test_structured_synthesises_a_valid_model(self, chat: FakeChatModel) -> None:
        out = chat.structured(MSGS, Summary)
        assert isinstance(out, Summary)
        assert chat.structured(MSGS, Summary) == out

    def test_structured_uses_a_canned_payload(self) -> None:
        m = FakeChatModel(responses={"Attercliffe": canned(Summary(title="Decision", sentences=3))})
        assert m.structured(MSGS, Summary).title == "Decision"

    def test_passing_tools_is_refused(self, chat: FakeChatModel) -> None:
        """Extraction calls carry zero tools. The fake makes a regression fail in CI."""
        with pytest.raises(ProviderError, match="zero tools"):
            chat.complete(MSGS, tools=[{"name": "search"}])

    def test_calls_are_recorded_for_assertions(self, chat: FakeChatModel) -> None:
        chat.complete(MSGS)
        assert len(chat.calls) == 1

    def test_capabilities_are_free(self, chat: FakeChatModel) -> None:
        caps = chat.capabilities()
        assert caps.structured_output is True
        assert caps.tools is False
        assert caps.cost_per_1m_input_usd == 0.0


class TestFakeEmbedder:
    def test_dimensions_are_honoured(self) -> None:
        assert len(FakeEmbedder(dimensions=1024).embed(["x"])[0]) == 1024

    def test_identical_text_embeds_identically(self, embedder: FakeEmbedder) -> None:
        assert embedder.embed(["council"]) == embedder.embed(["council"])

    def test_different_text_embeds_differently(self, embedder: FakeEmbedder) -> None:
        a, b = embedder.embed(["council", "refuse collection"])
        assert a != b

    def test_vectors_are_unit_length(self, embedder: FakeEmbedder) -> None:
        v = embedder.embed(["anything"])[0]
        assert sum(x * x for x in v) == pytest.approx(1.0, abs=1e-6)

    def test_batch_matches_singles(self, embedder: FakeEmbedder) -> None:
        batch = embedder.embed(["a", "b"])
        assert batch == [embedder.embed(["a"])[0], embedder.embed(["b"])[0]]


class TestFakeReranker:
    def test_overlap_wins(self) -> None:
        docs = ["refuse collection times", "the Attercliffe regeneration budget"]
        assert FakeReranker().rerank("attercliffe budget", docs, top_k=2)[0][0] == 1

    def test_top_k_truncates(self) -> None:
        assert len(FakeReranker().rerank("x", ["a", "b", "c"], top_k=2)) == 2

    def test_ties_break_on_original_order(self) -> None:
        out = FakeReranker().rerank("zzz", ["a", "b", "c"], top_k=3)
        assert [i for i, _ in out] == [0, 1, 2]
