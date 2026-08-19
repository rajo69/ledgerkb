# Run without an API key

This is the default. You do not have to configure anything to get it, and this
page exists mostly to say what the boundary is.

## What works with no key and no network

Everything that exists today.

| Command | Needs a key |
|---|---|
| `lkb init`, `lkb version`, `lkb doctor` | No |
| `lkb ingest` | No |
| `lkb docs`, `lkb chunks --verify` | No |
| `lkb index` | No. The default embedder runs in-process |
| `lkb search` | No |
| `pytest` | No. Every test uses the fake providers |

The one thing that touches the network is the first `lkb index`, which downloads
the embedding model. After that it is local.

## Why the embedder is local by default

`embeddings.provider = "local"` runs `mixedbread-ai/mxbai-embed-large-v1` through
fastembed, which is ONNX rather than torch, so it installs in seconds rather than
pulling two gigabytes of CUDA wheels.

It is 1024 dimensions, which is the width both design documents settled on, and it
is Apache-2.0. It was chosen over the originally recommended BGE-M3 for a blunt
reason: BGE-M3 is in no fastembed model list, dense or sparse or
late-interaction, so the in-process path that had been designed around it did not
exist.

Other permissively licensed 1024-dimension options, if your corpus argues for one:
`BAAI/bge-large-en-v1.5`, `snowflake/snowflake-arctic-embed-l`, and
`intfloat/multilingual-e5-large` if the documents stop being English.
`jinaai/jina-embeddings-v3` is excluded on purpose: a fine model, but CC-BY-NC-4.0
is non-commercial.

The model and its dimensions are a **locked** setting. Changing either makes every
stored vector meaningless, so it needs an explicit rebuild rather than a quiet
config edit.

## Pre-downloading the model

For a machine that will be offline, or a CI job inside a network namespace, warm
the cache first:

```bash
lkb index                    # anywhere with network, once
```

fastembed caches under the usual Hugging Face cache directory. A job that enters
an isolated network namespace must warm the cache before it enters, or stay on the
fake providers.

## Proving it, rather than trusting it

The `offline.yml` workflow runs the whole test suite and a full ingest inside a
network namespace. The interesting part is the first thing it does inside the
namespace:

```bash
if timeout 8 curl -sS https://pypi.org > /dev/null 2>&1; then
  echo "::error::network is reachable - this job would prove nothing"
  exit 1
fi
```

A job that can reach the internet cannot report green. Without that check the
workflow could pass while proving nothing, which is the usual failure mode of
"offline" test jobs.

Isolation is a namespace rather than a firewall rule on purpose: dropping OUTPUT
globally would also cut the runner's link to GitHub, so the job could never report
its result.

## Running the tests offline yourself

```bash
uv run pytest
```

Nothing in the suite calls a provider. Tests that would need credentials are
marked `@pytest.mark.live` and are not collected by default. If you add a test
that reaches the network, `offline.yml` will fail and that is the point.

## What will need a key, and when

Extraction (L4), grounded answering (L3) and entity adjudication (L5) call a chat
model. When those land, the choices are a hosted provider, an aggregator, or a
local server. See [Use a hosted provider](use-a-hosted-provider.md).

The commitment that survives all of it: **the headline evaluation metrics require
no judge and no API key**. Citation validity, correct abstention, retrieval recall
and over-merge rate are all counted deterministically against labelled data.
An eval that costs money is an eval that stops being run.
