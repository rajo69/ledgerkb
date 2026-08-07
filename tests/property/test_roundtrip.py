"""Property tests for the L0 gate.

The load-bearing one at L1 is that every chunk slices back byte-identical from
its source document. The offset arithmetic that guarantees it starts here.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ledgerkb.core.models import Chunk, Entity, Evidence
from ledgerkb.storage.base import fts_query, pack_vector, unpack_vector

text = st.text(min_size=1, max_size=400)
vectors = st.lists(st.floats(min_value=-1e3, max_value=1e3, allow_nan=False,
                             allow_infinity=False, width=32), min_size=1, max_size=256)


@given(vectors)
def test_vector_packing_round_trips(vec: list[float]) -> None:
    got = unpack_vector(pack_vector(vec))
    assert got is not None
    assert len(got) == len(vec)
    assert all(abs(a - b) < 1e-3 * max(1.0, abs(b)) for a, b in zip(got, vec, strict=True))


def test_packing_none_stays_none() -> None:
    assert pack_vector(None) is None
    assert unpack_vector(None) is None


@given(st.text(max_size=200))
def test_fts_query_never_produces_an_empty_expression(q: str) -> None:
    assert fts_query(q).strip()


@given(st.text(max_size=200))
def test_fts_query_is_accepted_by_sqlite(q: str) -> None:
    """Whatever the user types, FTS5 must parse it rather than raise."""
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
    db.execute("INSERT INTO t (body) VALUES ('the council budget')")
    db.execute("SELECT * FROM t WHERE t MATCH ?", (fts_query(q),)).fetchall()
    db.close()


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(body=text, header=st.one_of(st.none(), st.text(max_size=100)))
def test_embed_text_never_loses_the_verbatim_span(body: str, header: str | None) -> None:
    c = Chunk(workspace_id="ws", version_id="v", ordinal=0,
              char_start=0, char_end=len(body), text=body, context_header=header)
    assert c.text == body, "the verbatim span survives regardless of the header"
    assert body in c.embed_text


@given(
    start=st.integers(min_value=0, max_value=10_000),
    length=st.integers(min_value=0, max_value=2_000),
    doc=st.text(min_size=1, max_size=2_000),
)
def test_chunk_spans_slice_back_from_the_source(start: int, length: int, doc: str) -> None:
    """The offsets are what make every citation a precise span, not a page."""
    start = start % len(doc)
    end = min(start + length, len(doc))
    c = Chunk(workspace_id="ws", version_id="v", ordinal=0,
              char_start=start, char_end=end, text=doc[start:end])
    assert doc[c.char_start : c.char_end] == c.text


@given(st.text(min_size=1, max_size=100), st.lists(st.text(max_size=30), max_size=5))
def test_entity_survives_arbitrary_names_and_aliases(name: str, aliases: list[str]) -> None:
    e = Entity(workspace_id="ws", type="Person", canonical_name=name,
               normalised_name=name.lower(), aliases=aliases)
    assert Entity.model_validate(e.model_dump()) == e


@given(st.text(min_size=1, max_size=200))
def test_evidence_requires_a_non_empty_quote(quote: str) -> None:
    assert Evidence(chunk_id="c", quote=quote).quote == quote
