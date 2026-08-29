"""Tests for the transformation depth measure."""

import json
from pathlib import Path

import pytest

from design_council.measures.depth import (
    depth_score,
    disposition_profile,
    measure_depth,
    supplementary_descriptives,
)
from design_council.schemas import Disposition, TargetStateSpec, WorkflowEncoding

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODING_PATH = (
    REPO_ROOT / "data" / "encodings" / "dev" / "p2p_vendor_invoice_processing.json"
)


def encoding() -> WorkflowEncoding:
    with ENCODING_PATH.open() as handle:
        return WorkflowEncoding.model_validate(json.load(handle))


def tss_with(source: WorkflowEncoding, dispositions: list[str], actors=None) -> TargetStateSpec:
    """A TSS assigning the given disposition to each baseline step in order.

    Every non-eliminated step traces to a target step mirroring the baseline,
    unless an actor override is supplied for it.
    """
    actors = actors or {}
    steps, mapping = [], []

    for step, disposition in zip(source.steps, dispositions):
        if disposition == "eliminated":
            mapping.append(
                {
                    "baseline_step_id": step.step_id,
                    "disposition": disposition,
                    "rationale": "Removed.",
                    "target_step_ids": [],
                }
            )
            continue

        target_id = f"T-{step.step_id}"
        payload = step.model_dump()
        payload["step_id"] = target_id
        payload["actor"] = actors.get(step.step_id, step.actor)
        steps.append(payload)
        mapping.append(
            {
                "baseline_step_id": step.step_id,
                "disposition": disposition,
                "rationale": "Carried.",
                "target_step_ids": [target_id],
            }
        )

    return TargetStateSpec.model_validate(
        {
            "workflow_id": source.workflow_id,
            "baseline_step_ids": source.step_ids(),
            "steps": steps,
            "disposition_mapping": mapping,
        }
    )


# --- the pre-registered primary measure --------------------------------------


def test_all_retained_scores_zero():
    source = encoding()
    tss = tss_with(source, ["retained"] * 8)

    profile = disposition_profile(tss)
    assert profile.count(Disposition.RETAINED) == 8
    assert profile.proportions["retained"] == 1.0
    assert depth_score(profile) == 0.0


@pytest.mark.parametrize(
    "disposition", ["eliminated", "merged", "absorbed", "restructured"]
)
def test_every_non_retained_disposition_scores_one(disposition):
    """The scalar counts them alike: any weighting would be a post-hoc choice."""
    source = encoding()
    tss = tss_with(source, [disposition] * 8)

    assert depth_score(disposition_profile(tss)) == 1.0


def test_a_known_mixed_profile_gives_a_known_score():
    source = encoding()
    tss = tss_with(
        source,
        ["retained", "retained", "merged", "merged", "absorbed", "eliminated",
         "restructured", "retained"],
    )

    profile = disposition_profile(tss)
    assert profile.counts == {
        "eliminated": 1,
        "merged": 2,
        "absorbed": 1,
        "retained": 3,
        "restructured": 1,
    }
    assert profile.total_baseline_steps == 8
    assert depth_score(profile) == pytest.approx(5 / 8)


def test_proportions_sum_to_one():
    source = encoding()
    tss = tss_with(
        source,
        ["retained", "merged", "merged", "absorbed", "eliminated", "restructured",
         "restructured", "retained"],
    )

    profile = disposition_profile(tss)
    assert sum(profile.proportions.values()) == pytest.approx(1.0)


# --- the two observed run shapes ---------------------------------------------


def test_baseline_shape_five_retained():
    """The shape the live baseline run produced: 2 merged, 1 restructured,
    5 retained."""
    source = encoding()
    tss = tss_with(
        source,
        ["merged", "merged", "restructured", "retained", "retained", "retained",
         "retained", "retained"],
    )

    report = measure_depth(source, tss)
    assert report.profile.count(Disposition.RETAINED) == 5
    assert report.profile.count(Disposition.RESTRUCTURED) == 1
    assert report.depth_score == pytest.approx(3 / 8)


def test_council_shape_five_restructured():
    """The shape the live council run produced: 2 merged, 5 restructured,
    1 retained. Identical conformance, very different depth."""
    source = encoding()
    tss = tss_with(
        source,
        ["merged", "merged", "restructured", "retained", "restructured",
         "restructured", "restructured", "restructured"],
    )

    report = measure_depth(source, tss)
    assert report.profile.count(Disposition.RETAINED) == 1
    assert report.profile.count(Disposition.RESTRUCTURED) == 5
    assert report.depth_score == pytest.approx(7 / 8)


def test_the_two_shapes_are_separated_by_depth_where_the_gate_could_not():
    source = encoding()
    baseline = tss_with(
        source,
        ["merged", "merged", "restructured", "retained", "retained", "retained",
         "retained", "retained"],
    )
    council = tss_with(
        source,
        ["merged", "merged", "restructured", "retained", "restructured",
         "restructured", "restructured", "restructured"],
    )

    assert measure_depth(source, council).depth_score > measure_depth(
        source, baseline
    ).depth_score


# --- supplementary descriptives ----------------------------------------------


def test_actor_reassignments_counts_changed_actors():
    source = encoding()
    tss = tss_with(
        source,
        ["retained"] * 8,
        actors={"VIP-05": "Automated policy engine", "VIP-06": "Robot"},
    )

    supplementary = supplementary_descriptives(source, tss)
    assert supplementary.actor_reassignments == 2
    assert supplementary.actor_reassignment_ids == ["VIP-05", "VIP-06"]


def test_eliminated_steps_are_excluded_from_actor_reassignments():
    """An eliminated step has no actor to compare; counting it would conflate
    removing work with moving it."""
    source = encoding()
    tss = tss_with(source, ["eliminated"] + ["retained"] * 7)

    supplementary = supplementary_descriptives(source, tss)
    assert supplementary.actor_reassignments == 0


def test_net_new_steps_are_detected():
    source = encoding()
    tss = tss_with(source, ["retained"] * 8)
    payload = json.loads(tss.model_dump_json())
    payload["steps"].append(
        {
            "step_id": "T-NEW",
            "name": "Invented step",
            "description": "No baseline step traces here.",
            "actor": "Controls team",
            "inputs": [],
            "outputs": [],
        }
    )

    supplementary = supplementary_descriptives(
        source, TargetStateSpec.model_validate(payload)
    )
    assert supplementary.net_new_steps == 1
    assert supplementary.net_new_step_ids == ["T-NEW"]


def test_step_count_delta_and_fan_out():
    source = encoding()
    tss = tss_with(source, ["eliminated", "eliminated"] + ["retained"] * 6)

    supplementary = supplementary_descriptives(source, tss)
    assert supplementary.baseline_step_count == 8
    assert supplementary.target_step_count == 6
    assert supplementary.step_count_delta == -2
    assert supplementary.mean_fan_out == pytest.approx(6 / 8)


def test_supplementary_is_labelled_as_not_pre_registered():
    """The distinction must survive in the code, not only in the write-up."""
    from design_council.measures import depth

    assert "NOT pre-registered" in depth.SupplementaryDescriptives.__doc__
    assert "PRE-REGISTERED — PRIMARY" in depth.__doc__
    assert "SUPPLEMENTARY — DESCRIPTIVE, NOT PRE-REGISTERED" in depth.__doc__


# --- round trip from a run directory -----------------------------------------


def test_round_trip_from_a_run_directory(tmp_path):
    """Reads tss.json off disk exactly as the script does."""
    from design_council.agents.baseline import run_baseline
    from design_council.kb.loader import load_kb
    from scripts.measure_depth import load_report
    from tests.test_baseline import ScriptedClient, make_logger, valid_tss_json

    source = encoding()
    client = ScriptedClient([valid_tss_json(source)])
    logger = make_logger(tmp_path, client)
    run_baseline(source, load_kb(), client, logger)

    report = load_report(source, logger.run_dir)

    assert report.workflow_id == source.workflow_id
    assert report.profile.count(Disposition.RETAINED) == 8
    assert report.depth_score == 0.0


def test_markdown_writes_depth_into_each_run_directory(tmp_path):
    from design_council.agents.baseline import run_baseline
    from design_council.kb.loader import load_kb
    from scripts.measure_depth import DEPTH_FILENAME, main
    from tests.test_baseline import ScriptedClient, make_logger, valid_tss_json

    source = encoding()
    client = ScriptedClient([valid_tss_json(source)])
    logger = make_logger(tmp_path, client)
    run_baseline(source, load_kb(), client, logger)

    watched = ["tss.json", "gate_result.json", "run_manifest.json", "calls.jsonl"]
    before = {name: (logger.run_dir / name).read_bytes() for name in watched}

    assert main([str(ENCODING_PATH), str(logger.run_dir), "--markdown"]) == 0

    markdown = (logger.run_dir / DEPTH_FILENAME).read_text()
    assert "Primary measure (pre-registered)" in markdown
    assert "Supplementary descriptives (not pre-registered)" in markdown
    assert "**depth_score**" in markdown

    after = {name: (logger.run_dir / name).read_bytes() for name in watched}
    assert after == before
