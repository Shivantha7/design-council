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
    """The fate of one baseline step, with the reasoning behind it.

    target_step_ids traces this baseline step to the redesigned steps that now
    carry its work. It is the only path from baseline to target: rules resolve
    steps through this mapping and never by interpreting rationale prose.

    An eliminated step has no successor, so its target_step_ids is empty. Every
    other disposition means the work went somewhere, so its target_step_ids is
    non-empty.
    """

    model_config = ConfigDict(extra="forbid")

    baseline_step_id: str = Field(min_length=1)
    disposition: Disposition
    target_step_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_target_step_ids_match_disposition(self) -> "DispositionEntry":
        """target_step_ids is empty if and only if the step was eliminated."""
        if self.disposition is Disposition.ELIMINATED:
            if self.target_step_ids:
                raise ValueError(
                    f"baseline step {self.baseline_step_id!r} is eliminated but "
                    f"lists target_step_ids {self.target_step_ids}"
                )
        elif not self.target_step_ids:
            raise ValueError(
                f"baseline step {self.baseline_step_id!r} has disposition "
                f"{self.disposition.value!r} but no target_step_ids; only an "
                f"eliminated step may have none"
            )

        duplicates = sorted(
            {i for i in self.target_step_ids if self.target_step_ids.count(i) > 1}
        )
        if duplicates:
            raise ValueError(
                f"baseline step {self.baseline_step_id!r} lists target step_id(s) "
                f"more than once: {duplicates}"
            )

        return self


class TargetStateSpec(BaseModel):
    """A redesigned workflow, mapped back to the encoding it came from.

    Disposition convention. 'eliminated' means the function ceases to exist in
    the target state: nothing performs it, and target_step_ids is empty.
    'absorbed' and 'merged' mean the function persists, carried by another step
    identified in target_step_ids — the step boundary moved, the work did not
    stop. 'retained' and 'restructured' likewise mean the function persists.
    Only 'eliminated' asserts that the function is gone, which is why a
    requirement that a control survive is failed by elimination alone.

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
            raise ValueError(
                f"duplicate step_id(s) in redesigned steps: {duplicate_steps}"
            )

        dangling = sorted(
            {
                target_id
                for entry in self.disposition_mapping
                for target_id in entry.target_step_ids
                if target_id not in redesigned_ids
            }
        )
        if dangling:
            raise ValueError(
                f"disposition mapping points at target step_id(s) that are not "
                f"in the redesigned steps: {dangling}"
            )

        return self

    def target_steps_for(self, baseline_step_id: str) -> list[WorkflowStep]:
        """The redesigned steps that now carry a baseline step's work.

        This is how a gate rule resolves a baseline step to its successors:
        through the disposition mapping only. Returns an empty list for an
        eliminated step. Raises KeyError if the baseline step is not in this
        TSS at all, which the model validator should already have prevented.
        """
        for entry in self.disposition_mapping:
            if entry.baseline_step_id == baseline_step_id:
                by_id = {step.step_id: step for step in self.steps}
                return [by_id[target_id] for target_id in entry.target_step_ids]

        raise KeyError(f"no disposition entry for baseline step {baseline_step_id!r}")

    def disposition_for(self, baseline_step_id: str) -> Disposition:
        """The disposition recorded for a baseline step."""
        for entry in self.disposition_mapping:
            if entry.baseline_step_id == baseline_step_id:
                return entry.disposition

        raise KeyError(f"no disposition entry for baseline step {baseline_step_id!r}")


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
