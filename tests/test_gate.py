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
