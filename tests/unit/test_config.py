"""Config validation, profile merge, and the tier machinery."""

from __future__ import annotations

from pathlib import Path

import pytest

from ledgerkb.core.config import (
    Config,
    Tier,
    check_transition,
    load_config,
    load_profile,
    tier_table,
)
from ledgerkb.core.errors import ConfigError, GatedSettingError, LockedSettingError

MINIMAL = 'config_version = 1\nprofile = "default"\n'


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "default.toml").write_text(
        'entity_types = ["Person","Project"]\n'
        'predicates = ["owns"]\n'
        "[staleness]\ndefault_days = 180\n",
        encoding="utf-8",
    )
    (tmp_path / "ledgerkb.toml").write_text(MINIMAL, encoding="utf-8")
    return tmp_path


def _write(project: Path, body: str) -> Path:
    path = project / "ledgerkb.toml"
    path.write_text(MINIMAL + body, encoding="utf-8")
    return path


class TestIncoherentCombinations:
    """These must fail loudly at startup, never misbehave later."""

    def test_overlap_cannot_reach_chunk_size(self, project: Path) -> None:
        p = _write(project, "[chunking]\nmax_tokens = 256\noverlap = 256\n")
        with pytest.raises(ConfigError, match="smaller than"):
            load_config(p)

    def test_rerank_cannot_exceed_the_candidate_pool(self, project: Path) -> None:
        p = _write(project, "[retrieval]\ndense_k = 5\nsparse_k = 5\nrerank_to = 50\n")
        with pytest.raises(ConfigError, match="candidate pool"):
            load_config(p)

    def test_trigram_must_sit_inside_the_grey_band(self, project: Path) -> None:
        p = _write(project, "[resolution]\ntrigram = 0.5\ngrey_band = [0.80, 0.92]\n")
        with pytest.raises(ConfigError, match="grey_band"):
            load_config(p)

    def test_postgres_requires_a_dsn(self, project: Path) -> None:
        p = _write(project, '[store]\nbackend = "postgres"\n')
        with pytest.raises(ConfigError, match="dsn"):
            load_config(p)

    def test_unknown_key_is_rejected_not_ignored(self, project: Path) -> None:
        p = _write(project, "[retrieval]\ndense_k = 10\nnonsense = 3\n")
        with pytest.raises(ConfigError):
            load_config(p)

    def test_future_config_version_is_refused(self, project: Path) -> None:
        path = project / "ledgerkb.toml"
        path.write_text("config_version = 99\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="not supported"):
            load_config(path)


class TestProfiles:
    def test_named_profile_layers_over_default(self, project: Path) -> None:
        (project / "profiles" / "council.toml").write_text(
            '[staleness]\nminutes = 90\n[extraction]\nhints = "Formal minutes."\n',
            encoding="utf-8",
        )
        p = load_profile("council", project / "profiles")
        assert p.entity_types == ["Person", "Project"], "inherited from default"
        assert p.extraction.hints == "Formal minutes."
        assert p.staleness.model_extra["minutes"] == 90

    def test_missing_profile_is_an_error(self, project: Path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_profile("nope", project / "profiles")

    def test_empty_predicate_list_is_refused(self, project: Path) -> None:
        (project / "profiles" / "empty.toml").write_text("predicates = []\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="closed by design"):
            load_profile("empty", project / "profiles")

    def test_resolved_profile_lands_in_the_build_receipt(self, project: Path) -> None:
        cfg = load_config(project / "ledgerkb.toml")
        assert cfg.build_receipt()["resolved_profile"]["predicates"] == ["owns"]


class TestTiers:
    def test_free_knobs_change_without_complaint(self) -> None:
        old = Config()
        new = old.model_copy(deep=True)
        new.retrieval.dense_k = 80
        assert check_transition(old, new) == []

    def test_locked_embedding_model_raises(self) -> None:
        old = Config()
        new = old.model_copy(deep=True)
        new.embeddings.dimensions = 768
        with pytest.raises(LockedSettingError) as exc:
            check_transition(old, new)
        assert "lkb reindex --confirm" in str(exc.value)

    def test_locked_store_backend_raises(self) -> None:
        from ledgerkb.core.config import StoreConfig

        old = Config()
        new = old.model_copy(deep=True)
        # assigned whole, because backend and dsn must stay coherent at all times
        new.store = StoreConfig(backend="postgres", dsn="postgresql://localhost/x")
        with pytest.raises(LockedSettingError):
            check_transition(old, new)

    def test_gated_knob_refuses_unless_confirmed(self) -> None:
        old = Config()
        new = old.model_copy(deep=True)
        new.chunking.contextual_headers = False
        with pytest.raises(GatedSettingError, match="re-index"):
            check_transition(old, new)

    def test_gated_knob_reports_rebuilds_when_confirmed(self) -> None:
        old = Config()
        new = old.model_copy(deep=True)
        new.resolution.auto_merge = True
        rebuilds = check_transition(old, new, allow_gated=True)
        assert rebuilds == ["resolution.auto_merge: re-running resolution"]

    def test_every_knob_has_a_tier(self) -> None:
        rows = [r for r in tier_table() if not r[0].startswith("resolved_profile.")]
        assert rows
        assert all(isinstance(t, Tier) for _, t, _ in rows)

    def test_no_tier_four_invariant_is_exposed_as_a_key(self) -> None:
        """A PR that adds one of these is rejected. This is the check."""
        forbidden = {
            "verify_quotes", "quote_verification", "skip_verification",
            "allow_tools_in_extraction", "extraction_tools",
            "allow_delete", "hard_delete", "merge_contradictions",
            "require_evidence", "ignore_budget", "allow_zip_traversal",
        }
        keys = {k.rsplit(".", 1)[-1] for k, _, _ in tier_table()}
        assert not (keys & forbidden)
