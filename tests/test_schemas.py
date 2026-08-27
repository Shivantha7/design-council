"""Tests for the workflow encoding and Target-State Specification contracts."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from design_council.schemas import (
    TargetStateSpec,
    WorkflowEncoding,
    check_against_encoding,
)

DUMMY_DIR = Path(__file__).resolve().parent.parent / "data" / "dummy"
ENCODING_PATH = DUMMY_DIR / "dummy_p2p_encoding.json"
TSS_PATH = DUMMY_DIR / "dummy_p2p_tss.json"


def load_json(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def test_dummy_encoding_validates():
    encoding = WorkflowEncoding.model_validate(load_json(ENCODING_PATH))

    assert encoding.workflow_id == "DUMMY-P2P-001"
    assert encoding.domain.value == "P2P"
    assert encoding.step_ids() == ["REQ-01", "APR-01", "PO-01", "INV-01"]
    assert len(encoding.requirements) == 3


def test_dummy_tss_validates():
    tss = TargetStateSpec.model_validate(load_json(TSS_PATH))

    assert tss.workflow_id == "DUMMY-P2P-001"
    assert len(tss.disposition_mapping) == 4


def test_dummy_tss_matches_dummy_encoding():
    encoding = WorkflowEncoding.model_validate(load_json(ENCODING_PATH))
    tss = TargetStateSpec.model_validate(load_json(TSS_PATH))

    check_against_encoding(tss, encoding)  # raises if inconsistent


def test_tss_rejects_missing_disposition():
    """A baseline step with no entry in the mapping is a silent drop."""
    data = load_json(TSS_PATH)
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
    data = load_json(TSS_PATH)
    data["disposition_mapping"][0]["disposition"] = "partially_automated"

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    message = str(excinfo.value)
    assert "disposition_mapping.0.disposition" in message
    assert "Input should be" in message
    assert "partially_automated" in message


def test_tss_rejects_disposition_for_unknown_step():
    """An entry for a step that is not in the baseline is equally wrong."""
    data = load_json(TSS_PATH)
    data["disposition_mapping"].append(
        {
            "baseline_step_id": "NOT-A-STEP",
            "disposition": "eliminated",
            "rationale": "DUMMY. Step invented by the agent.",
        }
    )

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    assert "not in the baseline" in str(excinfo.value)


def test_tss_rejects_duplicate_disposition():
    """Each baseline step is dispositioned exactly once, not merely at least once."""
    data = load_json(TSS_PATH)
    data["disposition_mapping"].append(dict(data["disposition_mapping"][0]))

    with pytest.raises(ValidationError) as excinfo:
        TargetStateSpec.model_validate(data)

    assert "more than once" in str(excinfo.value)


def test_encoding_rejects_duplicate_step_ids():
    data = load_json(ENCODING_PATH)
    data["steps"].append(dict(data["steps"][0]))

    with pytest.raises(ValidationError) as excinfo:
        WorkflowEncoding.model_validate(data)

    assert "duplicate step_id" in str(excinfo.value)


def test_check_against_encoding_rejects_wrong_workflow():
    encoding = WorkflowEncoding.model_validate(load_json(ENCODING_PATH))
    data = load_json(TSS_PATH)
    data["workflow_id"] = "DUMMY-P2P-999"
    tss = TargetStateSpec.model_validate(data)

    with pytest.raises(ValueError, match="does not match"):
        check_against_encoding(tss, encoding)
