"""Deterministic rule-conformance gate.

evaluate() judges a Target-State Specification against the requirements of the
encoding it came from, and returns a GateResult.

The gate is pure Python over the two pydantic structures. It makes no LLM
calls, no network calls, and uses no randomness or wall-clock time. It reads
only structured fields — step ids, actors, inputs, dispositions, step order —
and never the prose in `description` or `rationale`. Identical inputs
therefore produce an identical GateResult, which is what makes a conformance
score reproducible from the artefacts in runs/.

Every baseline step is resolved to its successors through the disposition
mapping helpers on TargetStateSpec, never by matching names or reading prose.
"""

from typing import Any, Callable

from design_council.schemas.gate_result import GateResult, RequirementResult, score_for
from design_council.schemas.tss import Disposition, TargetStateSpec, check_against_encoding
from design_council.schemas.workflow_encoding import Requirement, WorkflowEncoding


class GateConfigError(Exception):
    """A requirement the gate cannot evaluate.

    Raised for an unknown rule_type, missing or malformed params, or a
    reference to a baseline step that is not in the workflow. The gate never
    skips such a requirement and never treats it as passed: an unevaluated
    requirement silently counted as satisfied would overstate conformance.
    """


# --- parameter handling ------------------------------------------------------


def _params(
    requirement: Requirement, expected: dict[str, type]
) -> dict[str, Any]:
    """Return the requirement's params, checked against the rule's signature.

    Both a missing key and an unexpected one are configuration errors: an
    unexpected key usually means a typo that would otherwise be ignored.
    """
    missing = sorted(set(expected) - set(requirement.params))
    if missing:
        raise GateConfigError(
            f"requirement {requirement.requirement_id!r} of rule_type "
            f"{requirement.rule_type!r} is missing param(s): {missing}"
        )

    unexpected = sorted(set(requirement.params) - set(expected))
    if unexpected:
        raise GateConfigError(
            f"requirement {requirement.requirement_id!r} of rule_type "
            f"{requirement.rule_type!r} has unexpected param(s): {unexpected}"
        )

    for key, expected_type in expected.items():
        value = requirement.params[key]
        if not isinstance(value, expected_type):
            raise GateConfigError(
                f"requirement {requirement.requirement_id!r} param {key!r} should "
                f"be {expected_type.__name__}, got {type(value).__name__}"
            )

    return requirement.params


def _disposition_of(
    tss: TargetStateSpec, requirement: Requirement, baseline_step_id: str
) -> Disposition:
    """Look up a baseline step's disposition, or fail loudly."""
    try:
        return tss.disposition_for(baseline_step_id)
    except KeyError as error:
        raise GateConfigError(
            f"requirement {requirement.requirement_id!r} refers to baseline step "
            f"{baseline_step_id!r}, which is not in the TSS"
        ) from error


# --- rules -------------------------------------------------------------------
#
# Each rule takes the TSS and the requirement, and returns (passed, reason).
# A rule that passes only because it had nothing to compare prefixes its reason
# with "vacuously satisfied: " so that such passes can be counted separately.


def _step_preserved(tss: TargetStateSpec, requirement: Requirement) -> tuple[bool, str]:
    """The baseline step must survive the redesign in some form."""
    params = _params(requirement, {"baseline_step_id": str})
    step_id = params["baseline_step_id"]
    disposition = _disposition_of(tss, requirement, step_id)

    if disposition is Disposition.ELIMINATED:
        return False, f"baseline step {step_id} is eliminated; it must be preserved"

    target_ids = [step.step_id for step in tss.target_steps_for(step_id)]
    return True, (
        f"baseline step {step_id} is preserved as {disposition.value}, "
        f"carried by target step(s) {target_ids}"
    )


def _inputs_required(tss: TargetStateSpec, requirement: Requirement) -> tuple[bool, str]:
    """Every target step carrying the baseline step must receive given inputs."""
    params = _params(
        requirement, {"baseline_step_id": str, "required_inputs": list}
    )
    step_id = params["baseline_step_id"]
    required = list(params["required_inputs"])
    disposition = _disposition_of(tss, requirement, step_id)

    if disposition is Disposition.ELIMINATED:
        return False, (
            f"baseline step {step_id} is eliminated, so no target step carries "
            f"the required input(s) {required}"
        )

    shortfalls = []
    for step in tss.target_steps_for(step_id):
        missing = [item for item in required if item not in step.inputs]
        if missing:
            shortfalls.append(f"{step.step_id} is missing {missing}")

    if shortfalls:
        return False, (
            f"target step(s) carrying baseline step {step_id} do not receive all "
            f"required input(s) {required}: " + "; ".join(shortfalls)
        )

    target_ids = [step.step_id for step in tss.target_steps_for(step_id)]
    return True, (
        f"every target step carrying baseline step {step_id} {target_ids} "
        f"receives all required input(s) {required}"
    )


def _ordering_preserved(
    tss: TargetStateSpec, requirement: Requirement
) -> tuple[bool, str]:
    """All targets of 'before' must precede all targets of 'after'."""
    params = _params(requirement, {"before_step_id": str, "after_step_id": str})
    before_id = params["before_step_id"]
    after_id = params["after_step_id"]

    before_disposition = _disposition_of(tss, requirement, before_id)
    after_disposition = _disposition_of(tss, requirement, after_id)

    eliminated = [
        step_id
        for step_id, disposition in (
            (before_id, before_disposition),
            (after_id, after_disposition),
        )
        if disposition is Disposition.ELIMINATED
    ]
    if eliminated:
        return True, (
            f"vacuously satisfied: baseline step(s) {eliminated} are eliminated, "
            f"so there is no ordering between {before_id} and {after_id} to check"
        )

    position = {step.step_id: index for index, step in enumerate(tss.steps)}
    before_steps = tss.target_steps_for(before_id)
    after_steps = tss.target_steps_for(after_id)

    last_before = max(position[step.step_id] for step in before_steps)
    first_after = min(position[step.step_id] for step in after_steps)

    before_ids = [step.step_id for step in before_steps]
    after_ids = [step.step_id for step in after_steps]

    if last_before < first_after:
        return True, (
            f"target step(s) {before_ids} for baseline {before_id} all precede "
            f"target step(s) {after_ids} for baseline {after_id}"
        )

    return False, (
        f"ordering not preserved: target step(s) {before_ids} for baseline "
        f"{before_id} do not all precede target step(s) {after_ids} for baseline "
        f"{after_id} in the redesigned step order"
    )


def _actor_separation(
    tss: TargetStateSpec, requirement: Requirement
) -> tuple[bool, str]:
    """The traced target steps of the listed baseline steps must not share an actor."""
    params = _params(requirement, {"baseline_step_ids": list})
    step_ids = list(params["baseline_step_ids"])

    if len(step_ids) < 2:
        raise GateConfigError(
            f"requirement {requirement.requirement_id!r} needs at least two "
            f"baseline_step_ids to separate, got {step_ids}"
        )

    dispositions = {
        step_id: _disposition_of(tss, requirement, step_id) for step_id in step_ids
    }
    eliminated = [
        step_id
        for step_id, disposition in dispositions.items()
        if disposition is Disposition.ELIMINATED
    ]
    if eliminated:
        return True, (
            f"vacuously satisfied: baseline step(s) {eliminated} are eliminated, "
            f"so there are no actors to separate across {step_ids}"
        )

    actors_by_step = {
        step_id: sorted({step.actor for step in tss.target_steps_for(step_id)})
        for step_id in step_ids
    }

    shared = set()
    for index, step_id in enumerate(step_ids):
        for other_id in step_ids[index + 1 :]:
            shared |= set(actors_by_step[step_id]) & set(actors_by_step[other_id])

    # Both verdicts report the same per-step form, so a reader can see which
    # actor sits behind each baseline step without going back to the TSS.
    per_step = ", ".join(f"{step_id} → {actors_by_step[step_id]}" for step_id in step_ids)

    if shared:
        return False, f"separation violated: {per_step}; shared: {sorted(shared)}"

    return True, f"actors separated: {per_step}"


def _disposition_in(tss: TargetStateSpec, requirement: Requirement) -> tuple[bool, str]:
    """The baseline step's disposition must be one of an allowed set."""
    params = _params(requirement, {"baseline_step_id": str, "allowed": list})
    step_id = params["baseline_step_id"]
    allowed = list(params["allowed"])

    valid = {d.value for d in Disposition}
    unknown = sorted(set(allowed) - valid)
    if unknown:
        raise GateConfigError(
            f"requirement {requirement.requirement_id!r} allows disposition(s) "
            f"that do not exist: {unknown}"
        )

    disposition = _disposition_of(tss, requirement, step_id)

    if disposition.value in allowed:
        return True, (
            f"baseline step {step_id} has disposition {disposition.value!r}, "
            f"which is within the allowed set {sorted(allowed)}"
        )

    return False, (
        f"baseline step {step_id} has disposition {disposition.value!r}, "
        f"which is outside the allowed set {sorted(allowed)}"
    )


RULES: dict[str, Callable[[TargetStateSpec, Requirement], tuple[bool, str]]] = {
    "step_preserved": _step_preserved,
    "inputs_required": _inputs_required,
    "ordering_preserved": _ordering_preserved,
    "actor_separation": _actor_separation,
    "disposition_in": _disposition_in,
}


# --- entry point -------------------------------------------------------------


def evaluate(encoding: WorkflowEncoding, tss: TargetStateSpec) -> GateResult:
    """Judge a TSS against the requirements of its encoding.

    Requirements are evaluated in the order they appear in the encoding, so the
    results list is stable across runs. Raises GateConfigError for a
    requirement the gate cannot evaluate, and ValueError if the TSS does not
    belong to this encoding — neither is reported as a failed requirement,
    because neither is a finding about the redesign.

    An encoding with no requirements is itself a configuration error. Scoring
    it would return 1.0 for any TSS, including a worthless one, so the gate
    refuses rather than emitting a perfect score that means nothing. This is
    checked before anything else, because it is a defect in the encoding and
    holds whatever TSS it is paired with.
    """
    if not encoding.requirements:
        raise GateConfigError(
            f"encoding {encoding.workflow_id!r} has no requirements; there is "
            f"nothing to check, and an unconstrained gate must not report a pass"
        )

    check_against_encoding(tss, encoding)

    results = []
    for requirement in encoding.requirements:
        rule = RULES.get(requirement.rule_type)
        if rule is None:
            raise GateConfigError(
                f"requirement {requirement.requirement_id!r} has unknown rule_type "
                f"{requirement.rule_type!r}; known rule types are "
                f"{sorted(RULES)}"
            )

        passed, reason = rule(tss, requirement)
        results.append(
            RequirementResult(
                requirement_id=requirement.requirement_id,
                passed=passed,
                reason=reason,
            )
        )

    return GateResult(results=results, conformance_score=score_for(results))
