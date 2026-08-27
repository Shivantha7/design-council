"""Tests for the IFRS/SLFRS knowledge base.

The KB itself is authored by hand. These tests guard its shape, its
determinism, and its links into the encoding corpus.

They skip while ifrs_slfrs_kb.yaml is absent, so the suite stays honest about
what has not been written yet rather than failing for an unrelated reason. The
skip reason names the missing file.
"""

import json
from pathlib import Path

import pytest

from design_council.kb.loader import KB_PATH, UNVERIFIED_REF, load_kb
from design_council.schemas import WorkflowEncoding

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODINGS_DIR = REPO_ROOT / "data" / "encodings"

EXPECTED_ENTRY_COUNT = 14

# Every ref starts unverified. Lowering this pin is how ref verification
# progress becomes visible; a new entry cannot ship unverified without moving
# it, and a verified ref cannot be silently un-verified.
EXPECTED_UNVERIFIED_REF_COUNT = 14

kb_required = pytest.mark.skipif(
    not KB_PATH.exists(),
    reason=f"knowledge base not yet authored: {KB_PATH} does not exist",
)


def load_json(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def corpus_step_ids() -> set[str]:
    """Every step id across every encoding under data/encodings/."""
    step_ids = set()
    for path in sorted(ENCODINGS_DIR.rglob("*.json")):
        encoding = WorkflowEncoding.model_validate(load_json(path))
        step_ids |= set(encoding.step_ids())

    return step_ids


@kb_required
def test_kb_loads_and_validates():
    kb = load_kb()

    assert len(kb.entries) == EXPECTED_ENTRY_COUNT


@kb_required
def test_kb_ids_are_unique_and_well_formed():
    kb = load_kb()

    ids = [entry.id for entry in kb.entries]
    assert len(set(ids)) == len(ids)
    assert sorted(ids) == [f"KB-{n:02d}" for n in range(1, EXPECTED_ENTRY_COUNT + 1)]


@kb_required
def test_every_entry_bears_on_a_real_step():
    """A principle tied to a step that does not exist cannot be acted on, and
    would silently drop out of any step-indexed lookup."""
    kb = load_kb()
    known = corpus_step_ids()

    dangling = sorted(
        {
            step_id
            for entry in kb.entries
            for step_id in entry.bears_on
            if step_id not in known
        }
    )

    assert not dangling, f"KB references step id(s) not in any encoding: {dangling}"


@kb_required
def test_every_entry_has_a_step_and_a_domain():
    kb = load_kb()

    for entry in kb.entries:
        assert entry.bears_on, f"{entry.id} bears on no step"
        assert entry.domains, f"{entry.id} has no domain"


@kb_required
def test_every_entry_has_a_relevance_tag():
    kb = load_kb()

    for entry in kb.entries:
        assert entry.relevance.value in {"core", "marginal"}


@kb_required
def test_render_for_prompt_is_deterministic():
    """The rendered KB is part of the agent's prompt, so a run is only
    reproducible if this string is."""
    kb = load_kb()

    assert kb.render_for_prompt() == kb.render_for_prompt()
    assert load_kb().render_for_prompt() == load_kb().render_for_prompt()


@kb_required
def test_render_for_prompt_mentions_every_entry():
    kb = load_kb()
    rendered = kb.render_for_prompt()

    for entry in kb.entries:
        assert f"[{entry.id}]" in rendered
        assert entry.principle in rendered


@kb_required
def test_render_for_prompt_orders_entries_by_id():
    kb = load_kb()
    rendered = kb.render_for_prompt()

    positions = [rendered.index(f"[{entry.id}]") for entry in kb.sorted_entries()]
    assert positions == sorted(positions)


@kb_required
def test_unverified_ref_count_is_pinned():
    """Paragraph citations are verified by hand against the standards texts.

    This pin makes that progress visible in the suite. Lower it as refs are
    verified; if it fails because the count rose, an entry shipped with an
    unverified ref that nobody accounted for.
    """
    kb = load_kb()

    unverified = kb.unverified_refs()
    assert len(unverified) == EXPECTED_UNVERIFIED_REF_COUNT, (
        f"{len(unverified)} entries still have ref == {UNVERIFIED_REF!r}, "
        f"expected {EXPECTED_UNVERIFIED_REF_COUNT}: {unverified}"
    )
