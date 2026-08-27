"""Every JSON file under data/ must already be in canonical form.

Without this, a hand-edited file sits in the tree in whatever shape it was
typed until some later script rewrites it, and that reflow lands in an
unrelated commit as hundreds of lines of noise — obscuring the one line that
actually changed. Formatting is checked here so the diff for a change to the
corpus is the change itself.

Run `python scripts/format_encodings.py` to fix a failure.
"""

import json
from pathlib import Path

import pytest

from scripts.format_encodings import canonical_text, json_paths

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
JSON_PATHS = json_paths()


def test_data_directory_holds_json():
    """Guards the guard: parametrising over an empty glob would pass silently."""
    assert JSON_PATHS, f"no JSON files found under {DATA_DIR}"


@pytest.mark.parametrize("path", JSON_PATHS, ids=lambda p: p.stem)
def test_json_file_is_canonically_formatted(path):
    current = path.read_text()
    wanted = canonical_text(json.loads(current))

    assert current == wanted, (
        f"{path.relative_to(DATA_DIR.parent)} is not in canonical form; "
        f"run python scripts/format_encodings.py"
    )


@pytest.mark.parametrize("path", JSON_PATHS, ids=lambda p: p.stem)
def test_json_file_ends_with_a_single_trailing_newline(path):
    text = path.read_text()

    assert text.endswith("\n")
    assert not text.endswith("\n\n")
