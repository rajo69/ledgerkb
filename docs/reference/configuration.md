# Configuration

`ledgerkb.toml` holds every knob that exists. `lkb init` writes one with the
defaults. `lkb doctor --tiers` prints the same tiers this page lists, straight
from the code.

The governing rule: **tunable means a quality or cost tradeoff. Not tunable means
a correctness invariant.** If a setting could make the system lie, it is not a
setting. See [Tunability tiers](../explanation/tunability-tiers.md) for why, and
what to do instead when you need to change behaviour that has no key.

## The four tiers

| Tier | Meaning |
|---|---|
| **free** | Hot. Change it, rerun, done |
| **gated** | Changing it invalidates derived data. The caller is told exactly what must be rebuilt, and refuses rather than leaving the store inconsistent |
| **locked** | Locked after first use. Needs an explicit destructive command |
| **(tier 4)** | Has no key at any level, and never will. Not listed below, because there is nothing to list |

## Settings

Generated from `src/ledgerkb/core/config.py`. A key that does not appear here
does not exist.

<!-- generated: config-table. Edit src/ledgerkb/core/config.py, then run scripts/render_config_reference.py -->
| Key | Type | Default | Tier | Changing it forces |
|---|---|---|---|---|
| `config_version` | `int` | `1` | free | nothing. It is hot |
| `profile` | `str` | `'default'` | free | nothing. It is hot |
| `store.backend` | `'sqlite' \| 'postgres'` | `'sqlite'` | locked | a migration, not a setting |
| `store.path` | `str` | `'.lkb/store.db'` | free | nothing. It is hot |
| `store.dsn` | `str \| None` | `None` | free | nothing. It is hot |
| `chat.provider` | `str` | `'openai_compatible'` | free | nothing. It is hot |
| `chat.base_url` | `str` | `'https://openrouter.ai/api/v1'` | free | nothing. It is hot |
| `chat.model` | `str` | `'qwen/qwen3-235b-a22b'` | free | nothing. It is hot |
| `chat.api_key_env` | `str` | `'OPENROUTER_API_KEY'` | free | nothing. It is hot |
| `chat.temperature` | `float` | `0.0` | free | nothing. It is hot |
| `chat.concurrency` | `int` | `4` | free | nothing. It is hot |
| `chat.timeout_s` | `float` | `120.0` | free | nothing. It is hot |
| `chat.cheap.model` | `str` | required | free | nothing. It is hot |
| `chat.cheap.temperature` | `float` | `0.0` | free | nothing. It is hot |
| `embeddings.provider` | `str` | `'local'` | free | nothing. It is hot |
| `embeddings.model` | `str` | `'mixedbread-ai/mxbai-embed-large-v1'` | locked | every stored vector becomes meaningless |
| `embeddings.dimensions` | `int` | `1024` | locked | every stored vector becomes meaningless |
| `embeddings.batch_size` | `int` | `64` | free | nothing. It is hot |
| `chunking.max_tokens` | `int` | `512` | gated | a full re-chunk and re-index |
| `chunking.overlap` | `int` | `64` | gated | a full re-chunk and re-index |
| `chunking.structure_first` | `bool` | `True` | gated | a full re-chunk and re-index |
| `chunking.contextual_headers` | `bool` | `False` | gated | a full re-index |
| `chunking.tokenizer` | `str` | `'cl100k_base'` | locked | chunk boundaries shift, breaking every existing offset |
| `retrieval.dense_k` | `int` | `50` | free | nothing. It is hot |
| `retrieval.sparse_k` | `int` | `50` | free | nothing. It is hot |
| `retrieval.rrf_k` | `int` | `60` | free | nothing. It is hot |
| `retrieval.fuse_to` | `int` | `30` | free | nothing. It is hot |
| `retrieval.rerank_to` | `int` | `8` | free | nothing. It is hot |
| `resolution.trigram` | `float` | `0.85` | gated | re-running resolution |
| `resolution.grey_band` | `tuple[float, float]` | `(0.8, 0.92)` | gated | re-running resolution |
| `resolution.auto_merge` | `bool` | `False` | gated | re-running resolution |
| `parsing.density_probe` | `float` | `0.6` | free | nothing. It is hot |
| `parsing.tier1` | `str` | `'docling'` | free | nothing. It is hot |
| `parsing.pdf` | `'pypdfium2' \| 'pymupdf'` | `'pypdfium2'` | free | nothing. It is hot |
| `budget.max_cost_usd_per_run` | `float` | `5.0` | free | nothing. It is hot |
| `budget.max_docs_per_run` | `int` | `1000` | free | nothing. It is hot |
| `obs.otlp_endpoint` | `str` | `''` | free | nothing. It is hot |
| `obs.semconv_version` | `str` | `'1.42.0'` | free | nothing. It is hot |
| `obs.log_level` | `'debug' \| 'info' \| 'warning' \| 'error'` | `'info'` | free | nothing. It is hot |
<!-- end generated: config-table -->

## Profile

Profiles carry domain knowledge so the code stays corpus-agnostic. There is never
a code branch for a particular corpus; there is a profile.
`profiles/default.toml` ships generic, and a named profile layers over it.
`profile = "council"` in `ledgerkb.toml` loads `profiles/council.toml`.

<!-- generated: profile-table. Edit src/ledgerkb/core/config.py, then run scripts/render_config_reference.py -->
| Key | Type | Default | Tier | Changing it forces |
|---|---|---|---|---|
| `name` | `str` | `'default'` | free | nothing. It is hot |
| `entity_types` | `list[str]` | `['Person', 'Organisation', 'Project', 'Meeting', 'Decision', 'Action', 'Risk', 'Document', 'Location', 'Policy']` | gated | re-extraction |
| `predicates` | `list[str]` | `['attended', 'owns', 'was_made_at', 'is_assigned_to', 'relates_to', 'threatens', 'mentions', 'supersedes', 'depends_on', 'supports']` | gated | re-extraction |
| `doc_types` | `list[str]` | `['minutes', 'report', 'register', 'policy', 'email', 'note']` | free | nothing. It is hot |
| `staleness.default_days` | `int` | `180` | free | nothing. It is hot |
| `extraction.hints` | `str` | `''` | free | nothing. It is hot |
<!-- end generated: profile-table -->

`staleness` also accepts a key per document type, so
`staleness.minutes = 90` overrides `default_days` for minutes alone.

## What validation rejects at startup

Incoherent combinations fail loudly when the config loads, never by misbehaving
later:

- `chunking.overlap` at or above `chunking.max_tokens`, because chunking could
  not advance.
- `retrieval.rerank_to` above `retrieval.fuse_to`, because reranking cannot
  invent candidates. The check is against `fuse_to` rather than
  `dense_k + sparse_k`, since fusion is what the reranker actually sees and the
  arms overlap heavily by design.
- `retrieval.fuse_to` above `dense_k + sparse_k`.
- `resolution.grey_band` not ascending, or `resolution.trigram` outside the band,
  because a threshold outside the review band means either everything or nothing
  gets reviewed.
- `store.backend = "postgres"` with no `store.dsn`.
- An empty `entity_types` or `predicates`, because the schema is closed by
  design.
- A `config_version` this build does not support.

## Where the config ends up

The fully resolved config, including the merged profile, is stamped into the
store and into every export's build receipt. Any artifact can therefore be
audited for how it was produced, including whether a custom port was substituted
for a built-in one.
