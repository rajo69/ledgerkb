# 0003. Vary the phrasing of generated facts

**Date:** 2026-08-21 · **Status:** accepted

## Context

[0002](0002-grow-the-corpus.md) grew the corpus and gave it a decoy structure:
every capital programme carries four different budget figures across four
quarters, so a question about an allocation has one correct chunk and three that
share nearly all of its vocabulary.

The first version stated every one of those figures in a single sentence
template, varying only the programme, the date and the amount. Across 99 minutes
files the budget sentence was byte-identical apart from those three fields.

Review caught that this biases the measurement it exists to support. Templated
text collapses under an embedding model: four sentences differing by one number
sit almost on top of each other, so the dense arm cannot separate them. BM25
meanwhile has exact tokens for the year and the amount, which is what it is best
at.

L2's gate asks whether hybrid beats dense-only and BM25-only. A corpus shaped
that way answers "BM25 was enough" before the retriever gets a say. That would
be a fact about the fixtures reported as a fact about retrieval.

## Decision

The facts are the decoys; the wording is not. Each repeated fact is stated
several ways, drawn from a phrasing bank by document index, so the same
programme discussed by two committees in the same quarter states the same figure
in different words.

Every phrasing keeps the amount and the financial year as literal tokens.

## Alternatives

**Leave it templated and note the bias in the results.** Cheapest, and the
caveat would have been honest. Rejected because the affected criterion is one of
the four the stage exists to measure, and a caveat that invalidates a headline
number is not a caveat, it is a missing result.

**Vary the wording with a language model.** More natural text, and it would have
introduced a model into the fixture path, a network dependency into corpus
generation, and non-determinism into a corpus whose value rests on regenerating
identically. Rejected on all three counts.

**Vary the facts as well as the wording.** Rejected: the four-figures-per-quarter
structure is what makes the decoys decoys. Varying the facts would remove the
thing being measured.

## Consequences

Two properties are now load-bearing and tested. At least five of the seven
allocation phrasings must reach the corpus, and every phrasing must keep the
amount and the financial year as literal tokens. The second test exists because
helping the dense arm must not quietly remove the handle the sparse arm is
entitled to.

Varying the wording changed no counts, because chunking splits on headings and
no section crossed the 512-token boundary. The corpus is 196 documents and 4,437
chunks, and it reached those figures by gaining the RTF anchor from #1, not by
anything in this decision.

The phrasing banks are prose, so anyone editing `corpus_world.py` can flatten
them back into a template without noticing what they cost. The tests are the
defence, and the reasoning is here.
