"""ledgerkb — turn scattered documents into a knowledge base that maintains a
position over time.

One append-only ledger of evidence-bearing assertions. The RAG index, knowledge
graph, OKF wiki, briefing PDF and change report are all projections of it.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ledgerkb")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.1"

__all__ = ["__version__"]
