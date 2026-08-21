# Use a hosted provider

One adapter speaks `/chat/completions` and `/embeddings` in the OpenAI format,
which covers most hosted providers, every aggregator worth using, and every local
server that imitates them. Switching provider is a config change rather than a
code change.

Nothing built today calls a chat model. This page is about embeddings, which is
the only provider call that currently happens, and about setting up the chat side
ready for L3.

## The shape of it

```toml
# ledgerkb.toml

[chat]
provider    = "openai_compatible"
base_url    = "https://openrouter.ai/api/v1"
model       = "qwen/qwen3-235b-a22b"
api_key_env = "OPENROUTER_API_KEY"     # a variable NAME, never a key

[chat.cheap]
model = "deepseek/deepseek-v3.2"       # headers, extraction and grading run here

[embeddings]
provider   = "openai_compatible"
base_url   = "https://openrouter.ai/api/v1"
model      = "qwen/qwen3-embedding-8b"
dimensions = 1024                      # LOCKED after the first index build
```

Then:

```bash
export OPENROUTER_API_KEY=sk-...
lkb doctor          # confirms the variable is set, without printing it
```

`api_key_env` names an environment variable. The library never stores a key, which
is what makes `ledgerkb.toml` safe to commit and safe to include verbatim in an
export's build receipt.

## Known-good endpoints

Anything OpenAI-compatible works with no extra code:

| Category | Examples |
|---|---|
| Aggregators | OpenRouter, Vercel AI Gateway, LiteLLM Proxy |
| Frontier | OpenAI, Azure OpenAI, Mistral, DeepSeek |
| Fast inference | Groq, Together, Fireworks, DeepInfra, Cerebras |
| Local servers | Ollama, vLLM, llama.cpp, LM Studio, SGLang, TGI |
| Embedding servers | Hugging Face TEI, Infinity, Ollama |

## Running against Cerebras

This is the endpoint the contextual-header measurement will use when it is
written, decided in
[ADR 0008](../adr/0008-provider-for-the-contextual-header-ab.md). Nothing calls
it yet, for the reason at the top of this page.

```toml
[chat]
provider    = "openai_compatible"
base_url    = "https://api.cerebras.ai/v1"
model       = "gpt-oss-120b"
api_key_env = "CEREBRAS_API_KEY"

[chat.cheap]
model = "gpt-oss-120b"     # the same model; the free tier has nothing cheaper
```

```bash
export CEREBRAS_API_KEY=csk-...
lkb doctor          # confirms the variable is set, without printing it
```

Embeddings stay local. Nothing about this section changes the `[embeddings]`
block, which runs in-process through fastembed with no key, and the whole
deterministic path still works with this endpoint unreachable.

The free tier is capped per day rather than per request, which will matter for
the one job that is going to use it. Generating a context header for every chunk
of the measurement corpus is roughly 2.4M tokens against a 1M daily allowance,
so it is a job measured in days and interrupted at least twice. Write it to
resume when the time comes:
`context_header` is a column on `chunk`, so the work outstanding is the chunks
that do not have one, and repeating a finished chunk is a no-op.

## Running against Ollama

```toml
[chat]
provider    = "openai_compatible"
base_url    = "http://localhost:11434/v1"
model       = "qwen3:8b"
api_key_env = "OLLAMA_API_KEY"     # unset is fine; local endpoints skip the check

[embeddings]
provider   = "openai_compatible"
base_url   = "http://localhost:11434/v1"
model      = "nomic-embed-text"
dimensions = 768
```

A local endpoint is recognised by its hostname (`localhost`, `127.0.0.1`, `::1`,
`0.0.0.0`, `host.docker.internal`) and does not require a key. The match is on the
hostname rather than on the URL as a substring, so a hosted endpoint whose path
happens to contain `localhost` is not mistaken for a local one.

Note the `dimensions = 768`. It must match the model. A mismatch is refused at
construction rather than surfacing as a shape error on the first search.

## Changing the embedding model on an existing store

You cannot, without a rebuild, and the library will stop you.

`embeddings.model` and `embeddings.dimensions` are tier-3, locked after first use.
Every stored vector was produced by one model in one space; a vector from a
different model is not comparable to it, and a store containing both silently
returns nonsense. Changing either raises a `LockedSettingError` naming the key,
the old value, the new value, and the command that would do it deliberately.

The chat model is free to change at any time. Only embeddings are locked.

## The cheap tier

`[chat.cheap]` overrides the model for the high-volume calls: context headers,
extraction and grading. Only the model differs, and the endpoint is shared.

This matters more than it looks. Context headers are one call per chunk and are the
highest-volume LLM call in the system by a wide margin. Everything else is
rounding error next to it.

## Bringing your own client

If your provider is not OpenAI-compatible, or you want your own retry, caching or
routing, implement the port and pass it in:

```python
from collections.abc import Sequence


class MyEmbedder:
    name = "my-embedder"
    dimensions = 1024

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...
```

That satisfies `Embedder`. There is nothing to subclass and nothing to register.
See [Ports](../reference/ports.md).

## What is not configurable

The budget ceiling aborts a run and has no override. You set
`budget.max_cost_usd_per_run`; you cannot set "proceed anyway". When extraction
lands, its calls will carry zero tools and that will have no key either. See
[Tunability tiers](../explanation/tunability-tiers.md).
