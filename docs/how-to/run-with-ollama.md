# Run with Ollama

A full ingest to search loop, embedding through a local Ollama server instead
of the in-process default. No API key, no request leaving the machine, and
verified end to end against Ollama 0.33.1 on the fixture corpus.

[Use a hosted provider](use-a-hosted-provider.md) already has an Ollama config
snippet. This page is the fuller walkthrough: what to pull, the one config
detail that snippet leaves out, and a `doctor` false positive you will hit if
you follow the documented init-then-edit order.

## Install and pull models

```bash
ollama pull nomic-embed-text   # 274MB, 768 dimensions
ollama pull qwen3:8b           # chat: not called by anything yet, see below
```

Confirm the server answers the OpenAI-compatible embeddings endpoint before
involving `lkb` at all:

```bash
curl -s http://localhost:11434/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"nomic-embed-text","input":"hello world"}'
```

A response with a 768-long `embedding` array means the endpoint `lkb` will
call is up.

## Configure

```toml
# ledgerkb.toml

[chat]
provider    = "openai_compatible"
base_url    = "http://localhost:11434/v1"
model       = "qwen3:8b"
api_key_env = "OLLAMA_API_KEY"   # unset is fine; localhost skips the check

[chat.cheap]
model = "qwen3:8b"

[embeddings]
provider   = "openai_compatible"
model      = "nomic-embed-text"
dimensions = 768                 # locked after the store is stamped, see below
```

The detail the snippet in [Use a hosted provider](use-a-hosted-provider.md)
does not spell out: `EmbeddingsConfig` has no `base_url` or `api_key_env`
field of its own (see
[Configuration](../reference/configuration.md)). Setting
`embeddings.provider = "openai_compatible"` sends embedding requests to
**`chat.base_url` with `chat.api_key_env`**, the same endpoint as the chat
block, not a second one you configure separately. Point `[chat]` at Ollama and
embeddings follow it there. If you ever need embeddings and chat on two
different servers, that is a case the config format does not represent yet.

## Ingest, index, search

```console
$ lkb ingest ./your-documents
21 ingested, 0 unchanged, 0 failed - 59 chunks

$ lkb index
embedding 59 chunks with nomic-embed-text (768 dims, openai_compatible)
59 embedded in 1 batches

$ lkb search "who owns the footbridge decision?" --k 3 --explain
dense 50, headings 9, sparse 38 -> 3 shown

1. Footbridge Options Appraisal  0.0477
   ...
```

Nothing here differs from the local-embedder path in
[Run without an API key](run-without-an-api-key.md) except where the vectors
come from. `lkb search` does not know or care that they came from a server on
the same machine rather than a process in the same one.

## The `lkb doctor` gotcha

If you follow the order the top-level docs suggest, `lkb init` then edit
`ledgerkb.toml`, and run `lkb doctor` before your first `lkb index`, it fails:

```
error 'embeddings.model' is locked after first use
(stored='mixedbread-ai/mxbai-embed-large-v1', requested='nomic-embed-text').
To change it deliberately, run: lkb reindex --confirm
```

Two things are wrong with this, both confirmed against the code, not guessed:

- `lkb init` stamps the store with whatever `ledgerkb.toml` says **at init
  time**, which is always the just-written default template. Editing the file
  immediately afterward to name a different embedding model trips `doctor`'s
  drift check even though not one chunk has been embedded, contradicting the
  file's own `# LOCKED after the first index build` comment.
- The remedy the error names, `lkb reindex --confirm`, is not a command.
  `lkb --help` does not list it, and running it returns "No such command
  'reindex'."

`lkb ingest`, `lkb index` and `lkb search` do not run this check and are
unaffected, which is how the walkthrough above completed with a model
`doctor` insists is locked to something else. Until this is fixed, treat a
`LockedSettingError` from `doctor` alone, with no prior successful `lkb
index`, as a false positive: ignore it and continue with `ingest`/`index`/
`search` directly.

## Why the chat block above is untested

Nothing in `lkb` calls a chat model yet; grounded answering is L3 and is not
built. `qwen3:8b` and the `[chat]` block are there so the config is ready when
it lands, matching the pattern in
[Use a hosted provider](use-a-hosted-provider.md). Only the embeddings path
above, `ingest` through `search`, was actually run against a live server for
this page.

## Performance

`nomic-embed-text` on CPU embedded 59 chunks from the twenty-one document
fixture corpus in one batch, well under a second of wall time past model load.
Ollama keeps the model resident between calls, so the cost that shows up is
the first request in a session, not each one after it.
