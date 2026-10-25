"""Pre-run validation of an encoding (docs/LIVE_APP_BRIEF.md section 5). No model calls.

Checks, all of which block a run:
  1. pydantic validation of WorkflowEncoding (done by FastAPI when the body is parsed,
     and by validate_payload for raw JSON);
  2. pairing completeness: every step named in an ordering_preserved or actor_separation
     rule has a step_preserved requirement or is listed in unconstrained_by_design. This
     mirrors tests/test_encodings.py::test_relational_requirements_are_paired_with_a_survival_decision
     exactly, so a user encoding meets the same rule the research encodings meet;
  3. every inputs_required input appears in the inputs of the step it binds;
  4. at least one requirement and at least three steps;
  5. a gate dry run: the deterministic gate (design_council.gate, unmodified) is evaluated
     on an identity redesign, so malformed rule types or params fail here, before any spend,
     rather than after a 16-minute council run.
"""

import json

from pydantic import ValidationError

from design_council.gate import evaluate
from design_council.gate.gate import GateConfigError
from design_council.schemas import TargetStateSpec, WorkflowEncoding

from service.schemas import ValidationIssue, ValidationReport

RELATIONAL_RULE_TYPES = {"ordering_preserved", "actor_separation"}


def referenced_step_ids(requirement) -> list[str]:
    if requirement.rule_type == "ordering_preserved":
        return [requirement.params.get("before_step_id"), requirement.params.get("after_step_id")]
    if requirement.rule_type == "actor_separation":
        return list(requirement.params.get("baseline_step_ids") or [])
    return []


def identity_tss(encoding: WorkflowEncoding) -> TargetStateSpec:
    """Every step retained one to one: the redesign that changes nothing."""
    return TargetStateSpec.model_validate({
        "workflow_id": encoding.workflow_id,
        "baseline_step_ids": encoding.step_ids(),
        "steps": [step.model_dump() for step in encoding.steps],
        "disposition_mapping": [
            {"baseline_step_id": s.step_id, "disposition": "retained",
             "target_step_ids": [s.step_id], "rationale": "identity"} for s in encoding.steps
        ],
    })


def validate_encoding(encoding: WorkflowEncoding) -> ValidationReport:
    errors, warnings = [], []

    if len(encoding.steps) < 3:
        errors.append(ValidationIssue(code="too_few_steps", message=f"{len(encoding.steps)} steps; at least 3 required"))
    if not encoding.requirements:
        errors.append(ValidationIssue(code="no_requirements", message="at least one requirement is required"))

    protected = {r.params.get("baseline_step_id") for r in encoding.requirements if r.rule_type == "step_preserved"}
    unconstrained = set(encoding.unconstrained_by_design)
    known = set(encoding.step_ids())
    for r in encoding.requirements:
        if r.rule_type not in RELATIONAL_RULE_TYPES:
            continue
        for step_id in referenced_step_ids(r):
            if step_id not in known:
                errors.append(ValidationIssue(code="unknown_step", location=r.requirement_id,
                                              message=f"{r.requirement_id} names step {step_id!r}, which is not in the workflow"))
            elif step_id not in protected and step_id not in unconstrained:
                errors.append(ValidationIssue(
                    code="unpaired_relational_step", location=r.requirement_id,
                    message=(f"{step_id} is constrained only by {r.requirement_id} ({r.rule_type}). Add a "
                             f"step_preserved requirement for it, or list it as open to elimination: "
                             f"otherwise eliminating it would silence the rule.")))

    steps = {s.step_id: s for s in encoding.steps}
    for r in encoding.requirements:
        if r.rule_type != "inputs_required":
            continue
        step = steps.get(r.params.get("baseline_step_id"))
        if step is None:
            continue  # reported by the gate dry run below
        for needed in r.params.get("required_inputs") or []:
            if needed not in step.inputs:
                errors.append(ValidationIssue(
                    code="required_input_missing", location=r.requirement_id,
                    message=(f"{r.requirement_id} requires input {needed!r} on {step.step_id}, but it is not in "
                             f"that step's inputs. The gate matches input names exactly.")))

    try:
        result = evaluate(encoding, identity_tss(encoding))
        if result.conformance_score < 1.0:
            warnings.append(ValidationIssue(
                code="baseline_not_conformant",
                message=(f"the unchanged workflow scores {result.conformance_score:.3f} against its own "
                         f"requirements: {', '.join(result.failed_requirement_ids())}")))
    except GateConfigError as error:
        errors.append(ValidationIssue(code="gate_config", message=str(error)))
    except (ValidationError, ValueError, KeyError) as error:
        errors.append(ValidationIssue(code="gate_dry_run", message=str(error)))

    if not encoding.unconstrained_by_design:
        warnings.append(ValidationIssue(code="no_open_steps",
                                        message="no step is listed as open to elimination"))

    return ValidationReport(valid=not errors, errors=errors, warnings=warnings)


def validate_payload(payload: dict) -> tuple[WorkflowEncoding | None, ValidationReport]:
    """Validate raw JSON: schema first, then the rules above."""
    try:
        encoding = WorkflowEncoding.model_validate(payload)
    except ValidationError as error:
        issues = [ValidationIssue(code="schema", location=".".join(str(p) for p in e["loc"]), message=e["msg"])
                  for e in json.loads(error.json())]
        return None, ValidationReport(valid=False, errors=issues)
    return encoding, validate_encoding(encoding)
