"""Tests for the deterministic conformance gate."""

import ast
import json
from pathlib import Path

import pytest

from design_council.gate import RULES, GateConfigError, evaluate
from design_council.schemas import TargetStateSpec, WorkflowEncoding

DUMMY_DIR = Path(__file__).resolve().parent.parent / "data" / "dummy"
ENCODING_PATH = DUMMY_DIR / "dummy_p2p_encoding.json"
CONFORMANT_PATH = DUMMY_DIR / "dummy_p2p_tss_conformant.json"
VIOLATING_PATH = DUMMY_DIR / "dummy_p2p_tss_violating.json"
UNMATCHED_INVOICE_PATH = DUMMY_DIR / "dummy_p2p_tss_unmatched_invoice.json"


def load_json(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def encoding() -> WorkflowEncoding:
    return WorkflowEncoding.model_validate(load_json(ENCODING_PATH))


def tss(path: Path) -> TargetStateSpec:
    return TargetStateSpec.model_validate(load_json(path))


def encoding_with(requirements: list[dict]) -> WorkflowEncoding:
    """The dummy encoding with its requirements replaced.

    Used to exercise a single rule in isolation without adding fixtures for
    every case.
    """
    data = load_json(ENCODING_PATH)
    data["requirements"] = requirements
    return WorkflowEncoding.model_validate(data)


# --- the three fixtures ------------------------------------------------------


def test_conformant_tss_scores_one():
    result = evaluate(encoding(), tss(CONFORMANT_PATH))

    assert result.conformance_score == 1.0
    assert result.failed_requirement_ids() == []
    assert [r.requirement_id for r in result.results] == [
        "DUMMY-R-01",
        "DUMMY-R-02",
        "DUMMY-R-03",
        "DUMMY-R-04",
    ]


def test_conformant_tss_has_no_vacuous_passes():
    """A score of 1.0 is only meaningful if the rules had something to check."""
    result = evaluate(encoding(), tss(CONFORMANT_PATH))

    for entry in result.results:
        assert not entry.reason.startswith("vacuously satisfied: ")


def test_violating_tss_fails_step_preserved():
    result = evaluate(encoding(), tss(VIOLATING_PATH))

    assert result.failed_requirement_ids() == ["DUMMY-R-01"]
    assert result.conformance_score == 0.75

    failure = result.result_for("DUMMY-R-01")
    assert failure.passed is False
    assert "APR-01" in failure.reason
    assert "eliminated" in failure.reason


def test_violating_tss_passes_actor_separation_vacuously():
    """R-03 passes only because the approval step no longer exists. The reason
    must say so, or the pass reads as evidence of separation of duties."""
    result = evaluate(encoding(), tss(VIOLATING_PATH))

    entry = result.result_for("DUMMY-R-03")
    assert entry.passed is True
    assert entry.reason.startswith("vacuously satisfied: ")
    assert "APR-01" in entry.reason


def test_unmatched_invoice_tss_fails_only_inputs_required():
    result = evaluate(encoding(), tss(UNMATCHED_INVOICE_PATH))

    assert result.failed_requirement_ids() == ["DUMMY-R-02"]
    assert result.conformance_score == 0.75

    failure = result.result_for("DUMMY-R-02")
    assert "TS-04" in failure.reason
    assert "Purchase order" in failure.reason
    assert "Goods receipt note" in failure.reason


def test_two_distinct_rule_types_have_a_demonstrated_failure():
    """Guards the fixture set: the gate must be shown to fail, not only pass."""
    failing_rule_types = set()
    source = encoding()
    by_id = {r.requirement_id: r for r in source.requirements}

    for path in [VIOLATING_PATH, UNMATCHED_INVOICE_PATH]:
        result = evaluate(source, tss(path))
        for requirement_id in result.failed_requirement_ids():
            failing_rule_types.add(by_id[requirement_id].rule_type)

    assert failing_rule_types == {"step_preserved", "inputs_required"}


# --- determinism -------------------------------------------------------------


def test_evaluate_is_deterministic():
    source = encoding()
    subject = tss(CONFORMANT_PATH)

    first = evaluate(source, subject)
    second = evaluate(source, subject)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_evaluate_is_deterministic_across_reloads():
    """Identical inputs read fresh from disk give an identical result."""
    first = evaluate(encoding(), tss(VIOLATING_PATH))
    second = evaluate(encoding(), tss(VIOLATING_PATH))

    assert first.model_dump_json() == second.model_dump_json()


def test_evaluate_does_not_mutate_its_inputs():
    source = encoding()
    subject = tss(UNMATCHED_INVOICE_PATH)
    before = (source.model_dump_json(), subject.model_dump_json())

    evaluate(source, subject)

    assert (source.model_dump_json(), subject.model_dump_json()) == before


# --- rule registry -----------------------------------------------------------


def test_registry_holds_the_five_rule_types():
    assert sorted(RULES) == [
        "actor_separation",
        "disposition_in",
        "inputs_required",
        "ordering_preserved",
        "step_preserved",
    ]


def test_unknown_rule_type_raises():
    """An unevaluated requirement must never be counted as passed."""
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-99",
                "statement": "DUMMY. A rule the gate does not implement.",
                "rule_type": "vibes_check",
                "params": {},
            }
        ]
    )

    with pytest.raises(GateConfigError, match="unknown rule_type"):
        evaluate(source, tss(CONFORMANT_PATH))


def test_missing_param_raises():
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-98",
                "statement": "DUMMY. Missing its baseline_step_id.",
                "rule_type": "step_preserved",
                "params": {},
            }
        ]
    )

    with pytest.raises(GateConfigError, match="missing param"):
        evaluate(source, tss(CONFORMANT_PATH))


def test_unexpected_param_raises():
    """A typo'd param would otherwise be silently ignored."""
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-97",
                "statement": "DUMMY. Has a misspelled param.",
                "rule_type": "step_preserved",
                "params": {"baseline_step_id": "APR-01", "baseline_step_ids": ["X"]},
            }
        ]
    )

    with pytest.raises(GateConfigError, match="unexpected param"):
        evaluate(source, tss(CONFORMANT_PATH))


def test_unknown_baseline_step_raises():
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-96",
                "statement": "DUMMY. Refers to a step outside the workflow.",
                "rule_type": "step_preserved",
                "params": {"baseline_step_id": "NOT-A-STEP"},
            }
        ]
    )

    with pytest.raises(GateConfigError, match="not in the TSS"):
        evaluate(source, tss(CONFORMANT_PATH))


# --- individual rules --------------------------------------------------------


def test_inputs_required_fails_for_an_eliminated_step():
    """Nothing carries the inputs, so this is a failure and not a vacuous pass."""
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-95",
                "statement": "DUMMY. Approval must see the budget.",
                "rule_type": "inputs_required",
                "params": {
                    "baseline_step_id": "APR-01",
                    "required_inputs": ["Cost centre budget"],
                },
            }
        ]
    )

    result = evaluate(source, tss(VIOLATING_PATH))

    entry = result.result_for("DUMMY-R-95")
    assert entry.passed is False
    assert not entry.reason.startswith("vacuously satisfied: ")
    assert "eliminated" in entry.reason


def test_ordering_preserved_fails_when_order_is_reversed():
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-94",
                "statement": "DUMMY. The invoice must be posted before the PO is issued.",
                "rule_type": "ordering_preserved",
                "params": {"before_step_id": "INV-01", "after_step_id": "PO-01"},
            }
        ]
    )

    result = evaluate(source, tss(UNMATCHED_INVOICE_PATH))

    entry = result.result_for("DUMMY-R-94")
    assert entry.passed is False
    assert "ordering not preserved" in entry.reason


def test_ordering_preserved_is_vacuous_when_a_side_is_eliminated():
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-93",
                "statement": "DUMMY. Approval precedes PO issue.",
                "rule_type": "ordering_preserved",
                "params": {"before_step_id": "APR-01", "after_step_id": "PO-01"},
            }
        ]
    )

    result = evaluate(source, tss(VIOLATING_PATH))

    entry = result.result_for("DUMMY-R-93")
    assert entry.passed is True
    assert entry.reason.startswith("vacuously satisfied: ")


def test_actor_separation_fails_when_targets_share_an_actor():
    """REQ-01 and APR-01 both trace to TS-01 in the conformant fixture."""
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-92",
                "statement": "DUMMY. Raising and approving must be separated.",
                "rule_type": "actor_separation",
                "params": {"baseline_step_ids": ["REQ-01", "APR-01"]},
            }
        ]
    )

    result = evaluate(source, tss(CONFORMANT_PATH))

    entry = result.result_for("DUMMY-R-92")
    assert entry.passed is False
    assert "Requester" in entry.reason


def test_actor_separation_needs_two_steps():
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-91",
                "statement": "DUMMY. Only one step listed.",
                "rule_type": "actor_separation",
                "params": {"baseline_step_ids": ["APR-01"]},
            }
        ]
    )

    with pytest.raises(GateConfigError, match="at least two"):
        evaluate(source, tss(CONFORMANT_PATH))


def test_disposition_in_passes_and_fails():
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-90",
                "statement": "DUMMY. Approval may only be retained or restructured.",
                "rule_type": "disposition_in",
                "params": {
                    "baseline_step_id": "APR-01",
                    "allowed": ["retained", "restructured"],
                },
            }
        ]
    )

    passing = evaluate(source, tss(UNMATCHED_INVOICE_PATH))  # APR-01 retained
    assert passing.result_for("DUMMY-R-90").passed is True
    assert passing.conformance_score == 1.0

    failing = evaluate(source, tss(CONFORMANT_PATH))  # APR-01 merged
    entry = failing.result_for("DUMMY-R-90")
    assert entry.passed is False
    assert "merged" in entry.reason
    assert failing.conformance_score == 0.0


def test_disposition_in_rejects_a_disposition_that_does_not_exist():
    source = encoding_with(
        [
            {
                "requirement_id": "DUMMY-R-89",
                "statement": "DUMMY. Allows a value outside the enum.",
                "rule_type": "disposition_in",
                "params": {
                    "baseline_step_id": "APR-01",
                    "allowed": ["retained", "partially_automated"],
                },
            }
        ]
    )

    with pytest.raises(GateConfigError, match="do not exist"):
        evaluate(source, tss(CONFORMANT_PATH))


# --- an encoding with nothing to check ---------------------------------------


def minimal_tss_for(encoding: WorkflowEncoding) -> TargetStateSpec:
    """A trivially valid TSS for an encoding: every step retained, one to one.

    Used to reach the gate with a TSS that is definitely not the reason for a
    failure, so a raised error can only have come from the encoding.
    """
    return TargetStateSpec.model_validate(
        {
            "workflow_id": encoding.workflow_id,
            "baseline_step_ids": encoding.step_ids(),
            "steps": [step.model_dump() for step in encoding.steps],
            "disposition_mapping": [
                {
                    "baseline_step_id": step.step_id,
                    "disposition": "retained",
                    "rationale": "Carried over unchanged.",
                    "target_step_ids": [step.step_id],
                }
                for step in encoding.steps
            ],
        }
    )


def test_dev_encoding_p2p_vip_01_is_satisfied_by_its_own_baseline():
    """The seven VIP requirements must be consistent with the workflow they
    were authored against: a redesign that changes nothing scores 1.0.

    A failure here means a requirement contradicts the baseline encoding — an
    authoring bug in the requirement, not a finding about any redesign.
    """
    path = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "encodings"
        / "dev"
        / "p2p_vendor_invoice_processing.json"
    )
    source = WorkflowEncoding.model_validate(load_json(path))
    assert [r.requirement_id for r in source.requirements] == [
        f"VIP-R-0{n}" for n in range(1, 9)
    ]

    result = evaluate(source, minimal_tss_for(source))

    assert result.conformance_score == 1.0
    for entry in result.results:
        assert not entry.reason.startswith("vacuously satisfied: ")


DEV_ENCODING_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "encodings"
    / "dev"
    / "p2p_vendor_invoice_processing.json"
)
VIP_CONFORMANT_PATH = DUMMY_DIR / "vip_smoke_conformant.json"
VIP_VIOLATING_PATH = DUMMY_DIR / "vip_smoke_violating.json"
VIP_NO_APPROVAL_PATH = DUMMY_DIR / "vip_smoke_no_approval.json"
VIP_SOD_VIOLATION_PATH = DUMMY_DIR / "vip_smoke_sod_violation.json"


def dev_encoding() -> WorkflowEncoding:
    return WorkflowEncoding.model_validate(load_json(DEV_ENCODING_PATH))


def assert_substantive(result, requirement_ids: list[str]) -> None:
    """These requirements passed because they were checked and held."""
    for requirement_id in requirement_ids:
        entry = result.result_for(requirement_id)
        assert entry.passed is True, f"{requirement_id} failed: {entry.reason}"
        assert not entry.reason.startswith("vacuously satisfied: "), (
            f"{requirement_id} passed vacuously: {entry.reason}"
        )


def assert_vacuous(result, requirement_ids: list[str]) -> None:
    """These requirements passed only because nothing was left to check."""
    for requirement_id in requirement_ids:
        entry = result.result_for(requirement_id)
        assert entry.passed is True, f"{requirement_id} failed: {entry.reason}"
        assert entry.reason.startswith("vacuously satisfied: "), (
            f"{requirement_id} was expected to pass vacuously: {entry.reason}"
        )


ALL_VIP_REQUIREMENTS = [f"VIP-R-0{n}" for n in range(1, 9)]


def test_conformant_smoke_fixture_scores_eight_of_eight():
    """A plausible touchless-AP redesign that keeps every control it should.

    Every pass must be substantive: a 1.0 built partly on vacuous passes would
    mean the redesign scored well by deleting what the rules constrain.
    """
    result = evaluate(dev_encoding(), tss(VIP_CONFORMANT_PATH))

    assert result.failed_requirement_ids() == []
    assert result.conformance_score == 1.0
    assert [r.requirement_id for r in result.results] == ALL_VIP_REQUIREMENTS

    assert_substantive(result, ALL_VIP_REQUIREMENTS)


def test_violating_smoke_fixture_scores_six_of_eight():
    """Eliminating the three-way match fails both requirements that rest on it.

    Unlike the no-approval fixture, nothing here passes vacuously: VIP-05
    survives, so VIP-R-04 and VIP-R-06 are both genuinely checked. VIP-R-06 in
    particular must be a substantive pass — the separation of approval from
    posting is real in this redesign, not an artefact of a missing step.
    """
    result = evaluate(dev_encoding(), tss(VIP_VIOLATING_PATH))

    assert result.failed_requirement_ids() == ["VIP-R-01", "VIP-R-02"]
    assert result.conformance_score == pytest.approx(6 / 8)

    for requirement_id in ["VIP-R-01", "VIP-R-02"]:
        entry = result.result_for(requirement_id)
        assert "VIP-03" in entry.reason
        assert "eliminated" in entry.reason

    assert_substantive(
        result,
        ["VIP-R-03", "VIP-R-04", "VIP-R-05", "VIP-R-06", "VIP-R-07", "VIP-R-08"],
    )


def test_no_approval_smoke_fixture_scores_seven_of_eight():
    """Eliminating approval fails one requirement and silences two others.

    VIP-R-03 requires VIP-05 to survive, so removing it fails. But VIP-R-04
    (approval before payment) and VIP-R-06 (approval separated from posting)
    both constrain VIP-05, and with it gone they have nothing left to check, so
    both pass vacuously. The score therefore falls only to 6/7 for a redesign
    that removed authorisation from the process entirely.

    This is the gate behaving as specified, not a defect. The test pins it so
    that the vacuity is visible in the suite rather than only in a run.
    """
    result = evaluate(dev_encoding(), tss(VIP_NO_APPROVAL_PATH))

    assert result.failed_requirement_ids() == ["VIP-R-03"]
    assert result.conformance_score == pytest.approx(7 / 8)

    failure = result.result_for("VIP-R-03")
    assert "VIP-05" in failure.reason
    assert "eliminated" in failure.reason

    assert_vacuous(result, ["VIP-R-04", "VIP-R-06"])
    for requirement_id in ["VIP-R-04", "VIP-R-06"]:
        assert "VIP-05" in result.result_for(requirement_id).reason

    assert_substantive(
        result, ["VIP-R-01", "VIP-R-02", "VIP-R-05", "VIP-R-07", "VIP-R-08"]
    )


# --- R2R-PC-01 and FPA-RF-01 smoke fixtures ----------------------------------

R2R_ENCODING_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "encodings"
    / "dev"
    / "r2r_period_close_management.json"
)
FPA_ENCODING_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "encodings"
    / "dev"
    / "fpa_rolling_forecast_update.json"
)
PC_CONFORMANT_PATH = DUMMY_DIR / "pc_smoke_conformant.json"
PC_VIOLATING_PATH = DUMMY_DIR / "pc_smoke_violating.json"
RF_CONFORMANT_PATH = DUMMY_DIR / "rf_smoke_conformant.json"
RF_VIOLATING_PATH = DUMMY_DIR / "rf_smoke_violating.json"

ALL_R2R_REQUIREMENTS = [f"R2R-R-0{n}" for n in range(1, 8)]
ALL_FPA_REQUIREMENTS = [f"FPA-R-0{n}" for n in range(1, 6)]


def r2r_encoding() -> WorkflowEncoding:
    return WorkflowEncoding.model_validate(load_json(R2R_ENCODING_PATH))


def fpa_encoding() -> WorkflowEncoding:
    return WorkflowEncoding.model_validate(load_json(FPA_ENCODING_PATH))


def test_pc_conformant_smoke_fixture_scores_seven_of_seven():
    """A plausible continuous-close redesign that keeps every control it should."""
    result = evaluate(r2r_encoding(), tss(PC_CONFORMANT_PATH))

    assert result.failed_requirement_ids() == []
    assert result.conformance_score == 1.0
    assert [r.requirement_id for r in result.results] == ALL_R2R_REQUIREMENTS

    assert_substantive(result, ALL_R2R_REQUIREMENTS)


def test_pc_violating_smoke_fixture_scores_six_of_seven():
    """Eliminating reconciliation fails R2R-R-01 and silences R2R-R-03.

    R2R-R-03 requires reconciliation to precede the reporting package. With
    PC-05 gone there is no ordering left to check, so it passes vacuously —
    the same interaction the VIP no-approval fixture records.
    """
    result = evaluate(r2r_encoding(), tss(PC_VIOLATING_PATH))

    assert result.failed_requirement_ids() == ["R2R-R-01"]
    assert result.conformance_score == pytest.approx(6 / 7)

    failure = result.result_for("R2R-R-01")
    assert "PC-05" in failure.reason
    assert "eliminated" in failure.reason

    assert_vacuous(result, ["R2R-R-03"])
    assert "PC-05" in result.result_for("R2R-R-03").reason

    assert_substantive(
        result, ["R2R-R-02", "R2R-R-04", "R2R-R-05", "R2R-R-06", "R2R-R-07"]
    )


def test_rf_conformant_smoke_fixture_scores_five_of_five():
    result = evaluate(fpa_encoding(), tss(RF_CONFORMANT_PATH))

    assert result.failed_requirement_ids() == []
    assert result.conformance_score == 1.0
    assert [r.requirement_id for r in result.results] == ALL_FPA_REQUIREMENTS

    assert_substantive(result, ALL_FPA_REQUIREMENTS)


def test_rf_violating_smoke_fixture_fails_ordering_substantively():
    """Publishing before approval: the first fixture to fail ordering_preserved.

    Both RF-07 and RF-08 survive, so nothing is silenced — the failure is a
    genuine ordering violation rather than a step being deleted, and every
    other requirement passes on its merits.
    """
    result = evaluate(fpa_encoding(), tss(RF_VIOLATING_PATH))

    assert result.failed_requirement_ids() == ["FPA-R-04"]
    assert result.conformance_score == pytest.approx(4 / 5)

    failure = result.result_for("FPA-R-04")
    assert failure.reason.startswith("ordering not preserved: ")
    assert not failure.reason.startswith("vacuously satisfied: ")
    assert "RF-07" in failure.reason
    assert "RF-08" in failure.reason

    assert_substantive(result, ["FPA-R-01", "FPA-R-02", "FPA-R-03", "FPA-R-05"])


def test_every_rule_type_in_the_corpus_has_a_demonstrated_failure():
    """Each rule type used by a real requirement must be shown failing at least
    once, not only passing. A rule that has never failed in a fixture is a rule
    whose failure path is untested against real data."""
    failing_rule_types = set()

    for source, path in [
        (dev_encoding(), VIP_VIOLATING_PATH),
        (dev_encoding(), VIP_NO_APPROVAL_PATH),
        (dev_encoding(), VIP_SOD_VIOLATION_PATH),
        (r2r_encoding(), PC_VIOLATING_PATH),
        (fpa_encoding(), RF_VIOLATING_PATH),
    ]:
        result = evaluate(source, tss(path))
        by_id = {r.requirement_id: r for r in source.requirements}
        for requirement_id in result.failed_requirement_ids():
            failing_rule_types.add(by_id[requirement_id].rule_type)

    assert failing_rule_types == {
        "step_preserved",
        "inputs_required",
        "ordering_preserved",
        "actor_separation",
    }

    # disposition_in is implemented and unit-tested, but no real requirement
    # uses it yet, so it is deliberately absent from this set.
    rule_types_in_use = {
        r.rule_type
        for source in [dev_encoding(), r2r_encoding(), fpa_encoding()]
        for r in source.requirements
    }
    assert failing_rule_types == rule_types_in_use


def test_sod_violation_smoke_fixture_fails_actor_separation_substantively():
    """Approval and posting performed by the same actor.

    Both VIP-05 and VIP-06 survive, so nothing is silenced: this is a genuine
    separation-of-duties failure rather than a step being deleted. It is the
    first fixture to fail actor_separation.
    """
    result = evaluate(dev_encoding(), tss(VIP_SOD_VIOLATION_PATH))

    assert result.failed_requirement_ids() == ["VIP-R-06"]
    assert result.conformance_score == pytest.approx(7 / 8)

    failure = result.result_for("VIP-R-06")
    assert failure.reason.startswith("separation violated: ")
    assert not failure.reason.startswith("vacuously satisfied: ")
    assert "VIP-05 → ['AP accountant']" in failure.reason
    assert "VIP-06 → ['AP accountant']" in failure.reason
    assert "shared: ['AP accountant']" in failure.reason

    assert_substantive(
        result,
        ["VIP-R-01", "VIP-R-02", "VIP-R-03", "VIP-R-04", "VIP-R-05", "VIP-R-07", "VIP-R-08"],
    )


def test_encoding_with_no_requirements_raises():
    """A gate with nothing to check must never report a pass."""
    source = encoding_with([])

    with pytest.raises(GateConfigError, match="no requirements"):
        evaluate(source, tss(CONFORMANT_PATH))


def test_empty_requirements_is_checked_before_the_tss():
    """The defect is in the encoding, so it is reported whatever TSS is paired
    with it — including one from another workflow entirely."""
    source = encoding_with([])
    data = load_json(CONFORMANT_PATH)
    data["workflow_id"] = "DUMMY-P2P-999"
    mismatched = TargetStateSpec.model_validate(data)

    with pytest.raises(GateConfigError, match="no requirements"):
        evaluate(source, mismatched)


# --- guards on the gate itself -----------------------------------------------


FORBIDDEN_IN_GATE = {
    "anthropic",
    "openai",
    "langgraph",
    "requests",
    "httpx",
    "urllib",
    "socket",
    "random",
    "secrets",
    "time",
    "datetime",
}


def gate_imports() -> set[str]:
    """Top-level module names imported anywhere in design_council/gate/."""
    gate_dir = Path(__file__).resolve().parent.parent / "design_council" / "gate"
    imported = set()

    for path in sorted(gate_dir.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

    return imported


def test_gate_imports_nothing_that_could_make_it_nondeterministic():
    """The gate must stay pure: no LLM client, no network, no randomness, no
    clock. Checked against real imports rather than the text of the file, so
    that prose about determinism does not trip it."""
    offenders = sorted(gate_imports() & FORBIDDEN_IN_GATE)

    assert offenders == [], f"gate imports {offenders}"


def test_gate_only_imports_stdlib_and_the_schemas():
    """Anything new here is worth a second look before it lands."""
    assert gate_imports() <= {"typing", "design_council"}


def test_evaluate_rejects_a_tss_from_another_workflow():
    data = load_json(CONFORMANT_PATH)
    data["workflow_id"] = "DUMMY-P2P-999"
    other = TargetStateSpec.model_validate(data)

    with pytest.raises(ValueError, match="does not match"):
        evaluate(encoding(), other)
