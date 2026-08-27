"""Tests for the workflow encoding and Target-State Specification contracts."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from design_council.schemas import (
    Disposition,
    TargetStateSpec,
    WorkflowEncoding,
    check_against_encoding,
)

DUMMY_DIR = Path(__file__).resolve().parent.parent / "data" / "dummy"
ENCODING_PATH = DUMMY_DIR / "dummy_p2p_encoding.json"
CONFORMANT_TSS_PATH = DUMMY_DIR / "dummy_p2p_tss_conformant.json"
VIOLATING_TSS_PATH = DUMMY_DIR / "dummy_p2p_tss_violating.json"
TSS_PATHS = [CONFORMANT_TSS_PATH, VIOLATING_TSS_PATH]


def load_json(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


# --- the dummy fixtures ------------------------------------------------------


def test_dummy_encoding_validates():
    encoding = WorkflowEncoding.model_validate(load_json(ENCODING_PATH))

    assert encoding.workflow_id == "DUMMY-P2P-001"
    assert encoding.domain.value == "P2P"
    assert encoding.step_ids() == ["REQ-01", "APR-01", "PO-01", "INV-01"]
    assert len(encoding.requirements) == 4


def test_every_requirement_carries_a_predicate():
    """Prose alone is not checkable; the gate reads rule_type and params."""
    encoding = WorkflowEncoding.model_validate(load_json(ENCODING_PATH))

    by_id = {r.requirement_id: r for r in encoding.requirements}
    assert by_id["DUMMY-R-01"].rule_type == "step_preserved"
    assert by_id["DUMMY-R-01"].params == {"baseline_step_id": "APR-01"}
    assert by_id["DUMMY-R-02"].rule_type == "inputs_required"
    assert by_id["DUMMY-R-03"].rule_type == "actor_separation"
    assert by_id["DUMMY-R-03"].params == {"baseline_step_ids": ["APR-01", "INV-01"]}
    assert by_id["DUMMY-R-04"].rule_type == "ordering_preserved"

    for requirement in encoding.requirements:
        assert requirement.statement.strip()
        assert requirement.rule_type.strip()


@pytest.mark.parametrize("path", TSS_PATHS, ids=lambda p: p.stem)
def test_dummy_tss_validates(path):
    """Both fixtures are schema-valid. The violating one is valid *structurally*;
    it is the gate, not the schema, that must reject it."""
    tss = TargetStateSpec.model_validate(load_json(path))

    assert tss.workflow_id == "DUMMY-P2P-001"
    assert len(tss.disposition_mapping) == 4


@pytest.mark.parametrize("path", TSS_PATHS, ids=lambda p: p.stem)
def test_dummy_tss_matches_dummy_encoding(path):
    encoding = WorkflowEncoding.model_validate(load_json(ENCODING_PATH))
    tss = TargetStateSpec.model_validate(load_json(path))

    check_against_encoding(tss, encoding)  # raises if inconsistent


def test_fixture_set_exercises_every_disposition():
    """Guards the fixtures themselves: a disposition no fixture uses is a
    disposition the gate is never tested against."""
    seen = set()
    for path in TSS_PATHS:
        tss = TargetStateSpec.model_validate(load_json(path))
        seen |= {entry.disposition for entry in tss.disposition_mapping}

    assert seen == set(Disposition)


def test_violating_fixture_eliminates_the_approval_step():
    """The deliberate defect: DUMMY-R-01 requires APR-01 to survive."""
    tss = TargetStateSpec.model_validate(load_json(VIOLATING_TSS_PATH))

    assert tss.disposition_for("APR-01") is Disposition.ELIMINATED
    assert tss.target_steps_for("APR-01") == []


# --- tracing baseline steps to target steps ----------------------------------


def test_target_steps_for_traces_through_the_mapping():
    tss = TargetStateSpec.model_validate(load_json(CONFORMANT_TSS_PATH))

    assert [s.step_id for s in tss.target_steps_for("REQ-01")] == ["TS-01"]
    assert [s.step_id for s in tss.target_steps_for("APR-01")] == ["TS-01"]
    assert [s.step_id for s in tss.target_steps_for("INV-01")] == ["TS-03"]
    assert tss.target_steps_for("INV-01")[0].actor == "Accounts payable system"


def test_target_steps_for_rejects_unknown_baseline_step():
    tss = TargetStateSpec.model_validate(load_json(CONFORMANT_TSS_PATH))

    with pytest.raises(KeyError):
        tss.target_steps_for("NOT-A-STEP")


# --- disposition mapping coverage --------------------------------------------


def test_tss_rejects_missing_disposition():
    """A baseline step with no entry in the mapping is a silent drop."""
    data = load_json(CONFORMANT_TSS_PATH)
    data["disposition_mapping"] = [
        entry
        for entry in data["disposition_mapping"]
        if entry["baseline_step_id"] != "INV-01"
    ]

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    assert "missing a disposition" in str(excinfo.value)
    assert "INV-01" in str(excinfo.value)


def test_tss_rejects_unknown_disposition_value():
    """Disposition is a closed enum; a free-text verdict must not validate."""
    data = load_json(CONFORMANT_TSS_PATH)
    data["disposition_mapping"][0]["disposition"] = "partially_automated"

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    message = str(excinfo.value)
    assert "disposition_mapping.0.disposition" in message
    assert "Input should be" in message
    assert "partially_automated" in message


def test_tss_rejects_disposition_for_unknown_step():
    """An entry for a step that is not in the baseline is equally wrong."""
    data = load_json(CONFORMANT_TSS_PATH)
    data["disposition_mapping"].append(
        {
            "baseline_step_id": "NOT-A-STEP",
            "disposition": "eliminated",
            "rationale": "DUMMY. Step invented by the agent.",
            "target_step_ids": [],
        }
    )

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    assert "not in the baseline" in str(excinfo.value)


def test_tss_rejects_duplicate_disposition():
    """Each baseline step is dispositioned exactly once, not merely at least once."""
    data = load_json(CONFORMANT_TSS_PATH)
    data["disposition_mapping"].append(dict(data["disposition_mapping"][0]))

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    assert "more than once" in str(excinfo.value)


# --- target_step_ids ---------------------------------------------------------


def test_eliminated_step_may_not_have_target_steps():
    data = load_json(VIOLATING_TSS_PATH)
    for entry in data["disposition_mapping"]:
        if entry["baseline_step_id"] == "APR-01":
            entry["target_step_ids"] = ["TS-01"]

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    assert "eliminated but" in str(excinfo.value)


@pytest.mark.parametrize(
    "disposition", ["merged", "absorbed", "retained", "restructured"]
)
def test_surviving_step_must_have_target_steps(disposition):
    """Anything other than eliminated means the work went somewhere."""
    data = load_json(CONFORMANT_TSS_PATH)
    data["disposition_mapping"][0]["disposition"] = disposition
    data["disposition_mapping"][0]["target_step_ids"] = []

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    assert "no target_step_ids" in str(excinfo.value)


def test_tss_rejects_target_step_id_that_does_not_exist():
    """A mapping pointing at a step not in the redesign would break tracing."""
    data = load_json(CONFORMANT_TSS_PATH)
    data["disposition_mapping"][0]["target_step_ids"] = ["TS-99"]

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    assert "not in the redesigned steps" in str(excinfo.value)
    assert "TS-99" in str(excinfo.value)


def test_tss_rejects_repeated_target_step_id():
    data = load_json(CONFORMANT_TSS_PATH)
    data["disposition_mapping"][0]["target_step_ids"] = ["TS-01", "TS-01"]

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    assert "more than once" in str(excinfo.value)


# --- encoding integrity ------------------------------------------------------


def test_encoding_rejects_duplicate_step_ids():
    data = load_json(ENCODING_PATH)
    data["steps"].append(dict(data["steps"][0]))

    with pytest.raises(ValidationError) as excinfo:
        WorkflowEncoding.model_validate(data)

    assert "duplicate step_id" in str(excinfo.value)


def test_check_against_encoding_rejects_wrong_workflow():
    encoding = WorkflowEncoding.model_validate(load_json(ENCODING_PATH))
    data = load_json(CONFORMANT_TSS_PATH)
    data["workflow_id"] = "DUMMY-P2P-999"
    tss = TargetStateSpec.model_validate(data)

    with pytest.raises(ValueError, match="does not match"):
        check_against_encoding(tss, encoding)
