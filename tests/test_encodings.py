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
DEV_DIR = REPO_ROOT / "data" / "encodings" / "dev"
DEV_PATHS = sorted(DEV_DIR.glob("*.json"))


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
