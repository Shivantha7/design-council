"""Data contract for a Target-State Specification (TSS).

A TSS is what an agent (baseline or council) produces from a WorkflowEncoding:
a redesigned set of steps, plus an explicit account of what happened to every
step of the baseline workflow.

The disposition mapping is the auditable link between the two artefacts. It
must account for every baseline step exactly once, so that no step is silently
dropped from a redesign and no invented step is dispositioned.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from design_council.schemas.workflow_encoding import WorkflowEncoding, WorkflowStep


class Disposition(str, Enum):
    """What the redesign did to a baseline step."""

    ELIMINATED = "eliminated"  # step no longer performed at all
    MERGED = "merged"  # combined with other steps into a new one
    ABSORBED = "absorbed"  # subsumed into an adjacent step's scope
    RETAINED = "retained"  # carried over substantially unchanged
    RESTRUCTURED = "restructured"  # still performed, but reorganised


class DispositionEntry(BaseModel):
    """The fate of one baseline step, with the reasoning behind it."""

    model_config = ConfigDict(extra="forbid")

    baseline_step_id: str = Field(min_length=1)
    disposition: Disposition
    rationale: str = Field(min_length=1)


class TargetStateSpec(BaseModel):
    """A redesigned workflow, mapped back to the encoding it came from.

    baseline_step_ids records the step ids of the source encoding as they stood
    when this TSS was produced. Carrying them here — rather than only in the
    encoding file — lets the coverage rule below be enforced by the model
    itself, so a TSS read back from runs/ is checkable on its own. Use
    check_against_encoding() to confirm the copy still matches the encoding.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(min_length=1)
    baseline_step_ids: list[str] = Field(min_length=1)
    steps: list[WorkflowStep] = Field(default_factory=list)
    disposition_mapping: list[DispositionEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def check_disposition_mapping_covers_baseline(self) -> "TargetStateSpec":
        """Every baseline step_id appears exactly once in the mapping.

        Three ways this fails, reported separately so the cause is obvious:
        a baseline step with no entry, an entry for an unknown step, and an
        entry made twice.
        """
        mapped_ids = [entry.baseline_step_id for entry in self.disposition_mapping]

        duplicates = sorted({i for i in mapped_ids if mapped_ids.count(i) > 1})
        if duplicates:
            raise ValueError(
                f"baseline step_id(s) dispositioned more than once: {duplicates}"
            )

        missing = sorted(set(self.baseline_step_ids) - set(mapped_ids))
        if missing:
            raise ValueError(f"baseline step_id(s) missing a disposition: {missing}")

        unknown = sorted(set(mapped_ids) - set(self.baseline_step_ids))
        if unknown:
            raise ValueError(
                f"disposition(s) for step_id(s) not in the baseline: {unknown}"
            )

        redesigned_ids = [step.step_id for step in self.steps]
        duplicate_steps = sorted(
            {i for i in redesigned_ids if redesigned_ids.count(i) > 1}
        )
        if duplicate_steps:
            raise ValueError(f"duplicate step_id(s) in redesigned steps: {duplicate_steps}")

        return self


def check_against_encoding(tss: TargetStateSpec, encoding: WorkflowEncoding) -> None:
    """Confirm a TSS actually belongs to the encoding it claims to.

    The model validator checks the TSS against its own copy of the baseline
    step ids. This checks that copy against the real encoding: same workflow,
    same steps. Raises ValueError on mismatch; returns None when consistent.
    """
    if tss.workflow_id != encoding.workflow_id:
        raise ValueError(
            f"TSS workflow_id {tss.workflow_id!r} does not match "
            f"encoding workflow_id {encoding.workflow_id!r}"
        )

    if sorted(tss.baseline_step_ids) != sorted(encoding.step_ids()):
        missing = sorted(set(encoding.step_ids()) - set(tss.baseline_step_ids))
        unknown = sorted(set(tss.baseline_step_ids) - set(encoding.step_ids()))
        raise ValueError(
            f"TSS baseline_step_ids do not match the encoding "
            f"(missing: {missing}, not in encoding: {unknown})"
        )
