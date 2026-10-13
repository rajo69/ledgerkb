# Run with Ollama

A full ingest to search loop, embedding through a local Ollama server instead
of the in-process default. No API key, no request leaving the machine, and
verified end to end against Ollama 0.33.1 on the fixture corpus.

[Use a hosted provider](use-a-hosted-provider.md) already has an Ollama config
snippet. This page is the fuller walkthrough: what to pull, the one config
detail that is easy to miss, and the `doctor` note you will see if you follow
the documented init-then-edit order.

## Install and pull models

```bash
ollama pull nomic-embed-text   # 274MB, 768 dimensions
ollama pull qwen3:8b           # chat: ready for L3, see below
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
dimensions = 768                 # locked once vectors exist, see below
```

The detail that is easy to miss, and that
[Use a hosted provider](use-a-hosted-provider.md) also states:
`EmbeddingsConfig` has no `base_url` or `api_key_env`
field of its own (see
[Configuration](../reference/configuration.md)). Setting
`embeddings.provider = "openai_compatible"` sends embedding requests to
**`chat.base_url` with `chat.api_key_env`**, the same endpoint as the chat
block, not a second one you configure separately. Point `[chat]` at Ollama and
embeddings follow it there. If you ever need embeddings and chat on two
different servers, the way through is the `Embedder` port in code.

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

## `lkb doctor` after init-then-edit

If you follow the order the top-level docs suggest, `lkb init` then edit
`ledgerkb.toml`, and run `lkb doctor` before your first `lkb index`, it prints
a yellow note:

```
locked setting changed 'embeddings.model' is locked after first use
(stored='mixedbread-ai/mxbai-embed-large-v1', requested='nomic-embed-text').
To change it deliberately, run: lkb index --rebuild
```

It is a note, not a failure: `doctor` carries on and finishes the rest of its
check. `lkb init` stamps the store with the default template it has just
written, and `doctor` compares your edited file against that stamp. Only
`lkb init` writes the stamp, so the note stays after indexing too.

What tells you whether anything is at risk is the `vectors` line `doctor`
prints once something has been indexed. With no vectors stored there is
nothing for the lock to protect, and `lkb index` embeds with the configured
model. If the `vectors` line says `not what is configured`, `lkb index` refuses
to mix the two models until you run `lkb index --rebuild`, which drops the
existing vectors and re-embeds.

## The chat block

Grounded answering is L3. `qwen3:8b` and the `[chat]` block are there so the
config is ready when it lands, matching the pattern in
[Use a hosted provider](use-a-hosted-provider.md). The embeddings path above,
`ingest` through `search`, was run against a live Ollama server for this page.

## Performance

`nomic-embed-text` on CPU embedded 59 chunks from the twenty-one document
fixture corpus in one batch, well under a second of wall time past model load.
Ollama keeps the model resident between calls, so the cost that shows up is
the first request in a session, not each one after it.
