"""Data contract for an encoded finance workflow.

A WorkflowEncoding is the baseline artefact: a structured, human-encoded
description of how a finance workflow is performed today, together with the
rule statements that any redesign of it must satisfy. The conformance gate
checks a Target-State Specification against these requirements.

Encodings under data/encodings/heldout/ are frozen after the pre-registration
tag and must not be modified.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Domain(str, Enum):
    """Finance process domain the workflow belongs to."""

    P2P = "P2P"  # purchase-to-pay
    R2R = "R2R"  # record-to-report
    FPA = "FPA"  # financial planning and analysis


class Source(BaseModel):
    """Where the encoded workflow was taken from."""

    model_config = ConfigDict(extra="forbid")

    publisher: str = Field(min_length=1)
    document_reference: str = Field(min_length=1)


class WorkflowStep(BaseModel):
    """One step of a workflow.

    step_id is stable and unique within its workflow. Disposition mappings in a
    Target-State Specification refer to baseline steps by this id, so it must
    not be renumbered once an encoding is published.
    """

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


class Requirement(BaseModel):
    """A rule statement the workflow must satisfy, in prose and as a predicate.

    statement is the English rule, quoted verbatim in gate output so a reader
    can see what was checked. rule_type and params are the machine-checkable
    form of that same rule: rule_type names a check in the gate's registry and
    params supplies its arguments.

    rule_type is a plain string rather than an enum so that adding a rule to
    the gate does not require changing this contract. The gate owns the
    registry and must reject an unknown rule_type rather than skipping it — a
    silently unchecked requirement would overstate conformance.
    """

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    rule_type: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class SourceMappingEntry(BaseModel):
    """Where one encoded step was anchored in the source framework.

    apqc_activity_ids lists the APQC PCF activity ids the step was mapped to.
    An empty list is a deliberate boundary decision, not a missing value: the
    step was encoded even though no activity in the referenced process anchors
    it. practitioner_note records why, in one line, for anchors that were
    weak, cross-group, or outside the process boundary.

    This is provenance for the encoding, not input to any rule. The gate does
    not read it.
    """

    model_config = ConfigDict(extra="forbid")

    apqc_activity_ids: list[int] = Field(default_factory=list)
    practitioner_note: str | None = None


class WorkflowEncoding(BaseModel):
    """A finance workflow as it is performed today, plus its rule statements."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: Domain
    source: Source
    steps: list[WorkflowStep] = Field(min_length=1)
    requirements: list[Requirement] = Field(default_factory=list)
    source_mapping: dict[str, SourceMappingEntry] = Field(default_factory=dict)
    unconstrained_by_design: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_ids_are_unique(self) -> "WorkflowEncoding":
        """step_id and requirement_id must each be unique within the encoding.

        Duplicate ids would make a disposition mapping ambiguous, so they are
        rejected at load time rather than surfacing later in the gate.
        """
        step_ids = [step.step_id for step in self.steps]
        duplicate_steps = sorted({i for i in step_ids if step_ids.count(i) > 1})
        if duplicate_steps:
            raise ValueError(f"duplicate step_id(s): {duplicate_steps}")

        requirement_ids = [r.requirement_id for r in self.requirements]
        duplicate_requirements = sorted(
            {i for i in requirement_ids if requirement_ids.count(i) > 1}
        )
        if duplicate_requirements:
            raise ValueError(f"duplicate requirement_id(s): {duplicate_requirements}")

        return self

    @model_validator(mode="after")
    def check_unconstrained_by_design_refers_to_real_steps(self) -> "WorkflowEncoding":
        """Steps deliberately left without a preservation requirement.

        Recording them makes the absence of a requirement a decision rather
        than an oversight: a step is either protected by a requirement or
        listed here as intentionally open to elimination. Listing a step does
        not exempt it from other requirements — a step may be unconstrained as
        to survival while still appearing in an ordering or separation rule.
        """
        known = set(self.step_ids())

        unknown = sorted(set(self.unconstrained_by_design) - known)
        if unknown:
            raise ValueError(
                f"unconstrained_by_design refers to step_id(s) not in the "
                f"workflow: {unknown}"
            )

        listed = self.unconstrained_by_design
        duplicates = sorted({i for i in listed if listed.count(i) > 1})
        if duplicates:
            raise ValueError(
                f"unconstrained_by_design lists step_id(s) more than once: "
                f"{duplicates}"
            )

        return self

    @model_validator(mode="after")
    def check_source_mapping_covers_every_step(self) -> "WorkflowEncoding":
        """source_mapping is optional, but partial coverage is not allowed.

        An absent mapping means the encoding was not source-mapped. A present
        one must account for every step, so that a step with no entry cannot be
        confused with a step deliberately mapped to no activity (which is
        recorded as an empty apqc_activity_ids list).
        """
        if not self.source_mapping:
            return self

        mapped = set(self.source_mapping)
        known = set(self.step_ids())

        missing = sorted(known - mapped)
        if missing:
            raise ValueError(f"source_mapping is missing step_id(s): {missing}")

        unknown = sorted(mapped - known)
        if unknown:
            raise ValueError(
                f"source_mapping refers to step_id(s) not in the workflow: {unknown}"
            )

        return self

    def step_ids(self) -> list[str]:
        """Baseline step ids, in workflow order."""
        return [step.step_id for step in self.steps]
