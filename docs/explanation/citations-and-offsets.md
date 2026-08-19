# Citations, and the offset invariant

Most systems in this category cite a document, or a page. This one cites a
character range, and the difference is load-bearing rather than cosmetic.

The rule, for every chunk:

```
document_text[chunk.char_start:chunk.char_end] == chunk.text
```

Exactly. Byte for byte.

## Why this is harder than it sounds

The easy way to build a chunker is to construct text. Join a heading onto its
body. Strip trailing whitespace. Normalise the quotes. Collapse the runs of
newlines a PDF extractor leaves behind. Every one of those is reasonable, and
every one breaks the equality above, because the chunk text is now a string that
does not appear in the document.

So there is no code path in `ingest/chunk.py` that builds a chunk's text. Chunks
are only ever sliced. Whitespace trimming moves the boundaries instead of editing
the text. Overlap extends a span backwards into the source rather than copying a
prefix onto the front.

Sanitisation is the harder half. It genuinely deletes characters: zero-width
joiners, bidi overrides, control characters, text coloured to match its
background, HTML comments. Every deletion shifts everything after it. So
sanitisation runs exactly once, before any offset is taken, and remaps every
heading offset and every page offset as it goes. Downstream there is exactly one
coordinate system, and the stored `DocumentVersion.text` is the sanitised text
that all offsets index into.

## What it buys

**A citation is a span.** "Planning Committee Minutes, 12 March 2026, Item 4,
Decision, characters 4182 to 4530" rather than "page 4, somewhere". A reader
following the citation lands on the sentence.

**Quote verification can be mechanical.** At L3, every claim in an answer carries
a verbatim quote and the chunk id it came from, and the quote is checked against
the stored chunk text before the answer is returned. A claim whose quote is not
there does not reach the caller.

That check is free: string matching, microseconds, no judge model. And it cannot
be prompted away. An injected instruction in a document can try to make a model
fabricate a citation, but it cannot make the fabricated quote appear in a chunk
that was stored before the attack ran. The guarantee is structural rather than
aspirational.

None of that works if chunk text is ever rewritten. Which is why this is the
invariant everything else is arranged around, and why "rewriting chunk text" is on
the list of things that get a pull request rejected.

## How it is checked

Three ways, because an invariant checked one way tends to be checked only where it
was already true.

1. **A Hypothesis property test** over arbitrary generated input, including text
   that sanitisation modifies and text it leaves alone.
2. **The full fixture corpus.** 55 chunks across ten formats, sliced back and
   compared.
3. **`lkb chunks <doc_id> --verify`**, which re-slices every stored chunk from the
   stored document text. That one works on your documents rather than on the
   fixtures, and it is the reason `DocumentVersion.text` is stored at all.

## The related rule about context headers

From L2 onward a chunk may carry a `context_header`: a short generated summary
situating it in its document. The header improves retrieval, and it is not part of
the source text.

So it lives in its own column and is never written into `chunk.text`. The store
combines the two into a generated column for indexing, so the dense and the sparse
index both see the same combined string while the verbatim span stays verbatim.
Header goes in `context_header`; text stays text.
