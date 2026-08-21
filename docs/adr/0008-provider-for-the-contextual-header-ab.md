# 0008. Provider for the contextual-header A/B

**Date:** 2026-08-21 · **Status:** proposed

## Context

L2's fourth criterion asks whether contextual headers improve `recall@20` by at
least 5 points, "which is what would justify their cost". Measuring it means
generating a header for every chunk: 4,433 calls, roughly 2.4M tokens, each call
small.

This is the only part of L2 that needs a language model. Embeddings run
in-process through fastembed with no key, and the whole deterministic path runs
offline.

There is no API key in the environment and no local model server. The machine is
an i5-1235U with Iris Xe integrated graphics and 16GB of memory, so no discrete
GPU.

Options priced on 2026-08-21:

| Option | Elapsed | Model | Note |
|---|---|---|---|
| Cerebras free | ~2.5 days | `gpt-oss-120b` | 1M tokens/day, 8K context, OpenAI-compatible |
| Google AI Studio free | ~3 days | Gemini 2.5 Flash | trains on free-tier prompts outside the EU, UK and EEA |
| OpenRouter free | ~5 days | many | 50 requests/day, or 1,000 after a one-time $10 |
| Groq free | ~24 days | Llama 3.3 70B | 100K tokens/day binds; best privacy posture |
| Local Ollama | ~15 to 20 hours | 4B class | CPU-bound, machine unusable meanwhile |
| Paid Gemini Flash Lite | minutes | Flash Lite | about $0.33 for the whole job |

## Decision

Not yet taken. Recorded so the research is not repeated.

The recommendation is Cerebras free, or paying about $0.33, on the grounds that
the interpretability of the result matters more than the elapsed time. The
valuable outcome here is a negative one: if contextual headers do not clear 5
points, the highest-volume language model call in the system gets deleted. A
negative result from a 4B model cannot be distinguished from a bad model, so it
would have to be run again.

## Alternatives

**Descope the criterion in writing.** Permitted by the roadmap, which allows
"fix it, or descope it in writing". The argument is real: the knob defaults to
off, and the baseline to beat is the heading arm, which already carries
"Planning Committee Minutes > Item 4 > Decision" deterministically and for free.
On a corpus this structured the heading arm may carry the whole gain.

**Run the A/B at reduced corpus scale**, around 950 chunks, which fits inside a
free tier in under a day. The other three criteria still run on the full corpus.
Weaker evidence, documented as reduced.

## Consequences

If the A/B runs, the baseline is the heading arm, not an unlabelled index.
Beating "no context" would be a meaningless win and would justify a cost the
deterministic path already covers.

Whichever way this goes, the result is about this corpus: synthetic, and
structured enough that the heading path is unusually informative. A negative
result here is weaker evidence about real council PDFs than it looks, and should
be reported as such.

Local Ollama remains worth installing for reasons unrelated to this decision. It
closes the third contribution ask in `CONTRIBUTING.md` and it fits the offline
principle. It is the wrong tool for this particular measurement only.
