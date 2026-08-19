"""Run the Python examples in the documentation, so a quickstart cannot rot.

A code block that CI executes is worth more than any amount of review
discipline. `pytest-examples` runs each block and compares its printed output
against the `#>` comments written under the print calls, so a change that alters
either the API or the output fails here rather than in somebody's terminal a
month later.

A block that cannot run, because it needs a provider or is an illustrative
fragment, is marked in its fence:

    ```python test="skip"

Marked rather than omitted, so a block that stops working is a decision somebody
made rather than something nobody noticed.

To refresh the expected output after a deliberate change:

    pytest tests/test_docs_examples.py --update-examples
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_examples import CodeExample, EvalExample, find_examples

ROOT = Path(__file__).resolve().parent.parent

SOURCES = [
    ROOT / "README.md",
    ROOT / "docs" / "tutorial",
    ROOT / "docs" / "how-to",
]


@pytest.mark.parametrize("example", list(find_examples(*SOURCES)), ids=str)
def test_documentation_example(example: CodeExample, eval_example: EvalExample) -> None:
    if example.prefix_settings().get("test") == "skip":
        pytest.skip("marked test=\"skip\" in the fence")

    # Formatting is a human decision in prose; only behaviour is checked here.
    if eval_example.update_examples:
        eval_example.run_print_update(example)
    else:
        eval_example.run_print_check(example)
