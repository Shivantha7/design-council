"""Tests over the real encodings in data/encodings/.

These guard the corpus rather than the code: an encoding that no longer
validates would break every run that cites it, and a step id that shifts would
silently invalidate the disposition mappings of TSSs already produced against
it.
"""

import json
from pathlib import Path

import pytest

from design_council.schemas import WorkflowEncoding

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODINGS_DIR = REPO_ROOT / "data" / "encodings"
DEV_DIR = ENCODINGS_DIR / "dev"
DEV_PATHS = sorted(DEV_DIR.glob("*.json"))
ALL_ENCODING_PATHS = sorted(ENCODINGS_DIR.rglob("*.json"))

# Rules that constrain how a step relates to another step. They say nothing
# about whether the step survives at all, so eliminating it silences them.
RELATIONAL_RULE_TYPES = {"ordering_preserved", "actor_separation"}


def load_json(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def test_dev_directory_is_not_empty():
    """Guards the guard: parametrising over an empty glob would pass silently."""
    assert DEV_PATHS, f"no encodings found in {DEV_DIR}"


@pytest.mark.parametrize("path", DEV_PATHS, ids=lambda p: p.stem)
def test_dev_encoding_validates(path):
    encoding = WorkflowEncoding.model_validate(load_json(path))

    assert encoding.workflow_id.strip()
    assert encoding.steps


@pytest.mark.parametrize("path", DEV_PATHS, ids=lambda p: p.stem)
def test_dev_encoding_filename_is_not_misleading(path):
    """A file under encodings/dev/ must not be dummy fixture data."""
    encoding = WorkflowEncoding.model_validate(load_json(path))

    assert "DUMMY" not in encoding.workflow_id.upper()


def test_vendor_invoice_processing_step_order_is_stable():
    """Step ids are cited by every TSS produced against this encoding, so a
    reordering or renumbering here is a breaking change."""
    path = DEV_DIR / "p2p_vendor_invoice_processing.json"
    encoding = WorkflowEncoding.model_validate(load_json(path))

    assert encoding.workflow_id == "P2P-VIP-01"
    assert encoding.domain.value == "P2P"
    assert encoding.step_ids() == [
        "VIP-01",
        "VIP-02",
        "VIP-03",
        "VIP-04",
        "VIP-05",
        "VIP-06",
        "VIP-07",
        "VIP-08",
    ]


def test_period_close_management_step_order_is_stable():
    """Step ids are cited by every TSS produced against this encoding, so a
    reordering or renumbering here is a breaking change."""
    path = DEV_DIR / "r2r_period_close_management.json"
    encoding = WorkflowEncoding.model_validate(load_json(path))

    assert encoding.workflow_id == "R2R-PC-01"
    assert encoding.domain.value == "R2R"
    assert encoding.step_ids() == [f"PC-0{n}" for n in range(1, 9)]


def test_rolling_forecast_update_step_order_is_stable():
    """As above: the RF ids are the stable handle for every disposition mapping."""
    path = DEV_DIR / "fpa_rolling_forecast_update.json"
    encoding = WorkflowEncoding.model_validate(load_json(path))

    assert encoding.workflow_id == "FPA-RF-01"
    assert encoding.domain.value == "FPA"
    assert encoding.step_ids() == [f"RF-0{n}" for n in range(1, 9)]


def test_rolling_forecast_actuals_input_string_is_bound_verbatim():
    """FPA-R-02 matches an RF-05 input by exact string. Editing either without
    the other silently turns the requirement into one that can never pass."""
    path = DEV_DIR / "fpa_rolling_forecast_update.json"
    encoding = WorkflowEncoding.model_validate(load_json(path))

    rf05 = next(s for s in encoding.steps if s.step_id == "RF-05")
    requirement = next(
        r for r in encoding.requirements if r.requirement_id == "FPA-R-02"
    )

    for required in requirement.params["required_inputs"]:
        assert required in rf05.inputs


def test_vendor_invoice_processing_source_mapping_is_complete():
    """Every step carries a provenance decision, including the deliberate
    boundary case with no APQC anchor."""
    path = DEV_DIR / "p2p_vendor_invoice_processing.json"
    encoding = WorkflowEncoding.model_validate(load_json(path))

    assert set(encoding.source_mapping) == set(encoding.step_ids())

    # VIP-01 sits outside 9.6.1 by decision, so it is anchored to no activity
    # and must carry a note saying why.
    intake = encoding.source_mapping["VIP-01"]
    assert intake.apqc_activity_ids == []
    assert intake.practitioner_note

    for step_id, entry in encoding.source_mapping.items():
        if not entry.apqc_activity_ids:
            assert entry.practitioner_note, (
                f"{step_id} has no APQC anchor and no note explaining why"
            )


# --- pairing completeness ----------------------------------------------------


def referenced_step_ids(requirement) -> list[str]:
    """Step ids a relational requirement constrains."""
    if requirement.rule_type == "ordering_preserved":
        return [
            requirement.params["before_step_id"],
            requirement.params["after_step_id"],
        ]
    if requirement.rule_type == "actor_separation":
        return list(requirement.params["baseline_step_ids"])

    raise AssertionError(f"not a relational rule type: {requirement.rule_type}")


@pytest.mark.parametrize("path", ALL_ENCODING_PATHS, ids=lambda p: p.stem)
def test_relational_requirements_are_paired_with_a_survival_decision(path):
    """Every step named in an ordering or separation rule must either be
    protected from elimination or recorded as deliberately unprotected.

    Relational rules pass vacuously when the step they constrain is gone, so a
    step constrained only relationally can be deleted to silence its own rule.
    Pairing each with a step_preserved requirement closes that. Where the pair
    is deliberately absent, the step is listed in unconstrained_by_design, so
    the gap is a recorded decision rather than an oversight.

    Being listed in unconstrained_by_design does not exempt a step from
    relational rules: PC-02 is unconstrained as to survival while still being
    subject to the separation of duties rule R2R-R-05.
    """
    encoding = WorkflowEncoding.model_validate(load_json(path))

    protected = {
        r.params["baseline_step_id"]
        for r in encoding.requirements
        if r.rule_type == "step_preserved"
    }
    unconstrained = set(encoding.unconstrained_by_design)

    unpaired = []
    for requirement in encoding.requirements:
        if requirement.rule_type not in RELATIONAL_RULE_TYPES:
            continue
        for step_id in referenced_step_ids(requirement):
            if step_id not in protected and step_id not in unconstrained:
                unpaired.append(f"{step_id} (via {requirement.requirement_id})")

    assert not unpaired, (
        f"{encoding.workflow_id}: step(s) constrained only relationally, with no "
        f"step_preserved requirement and no entry in unconstrained_by_design: "
        f"{sorted(set(unpaired))}"
    )


@pytest.mark.parametrize("path", ALL_ENCODING_PATHS, ids=lambda p: p.stem)
def test_unconstrained_by_design_names_real_steps(path):
    encoding = WorkflowEncoding.model_validate(load_json(path))

    assert set(encoding.unconstrained_by_design) <= set(encoding.step_ids())


@pytest.mark.parametrize("path", ALL_ENCODING_PATHS, ids=lambda p: p.stem)
def test_unconstrained_steps_are_not_also_step_preserved(path):
    """A step cannot be both protected from elimination and recorded as
    deliberately open to it — that is a contradiction in the encoding."""
    encoding = WorkflowEncoding.model_validate(load_json(path))

    protected = {
        r.params["baseline_step_id"]
        for r in encoding.requirements
        if r.rule_type == "step_preserved"
    }

    contradiction = sorted(protected & set(encoding.unconstrained_by_design))
    assert not contradiction, (
        f"{encoding.workflow_id}: step(s) both step_preserved and listed "
        f"unconstrained_by_design: {contradiction}"
    )
