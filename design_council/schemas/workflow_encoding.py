"""Data contract for an encoded finance workflow.

A WorkflowEncoding is the baseline artefact: a structured, human-encoded
description of how a finance workflow is performed today, together with the
rule statements that any redesign of it must satisfy. The conformance gate
checks a Target-State Specification against these requirements.

Encodings under data/encodings/heldout/ are frozen after the pre-registration
tag and must not be modified.
"""

from enum import Enum

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
    """A rule statement the workflow must satisfy.

    These are what the conformance gate later checks a redesign against, so
    requirement_id is stable and is quoted in gate output.
    """

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)


class WorkflowEncoding(BaseModel):
    """A finance workflow as it is performed today, plus its rule statements."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: Domain
    source: Source
    steps: list[WorkflowStep] = Field(min_length=1)
    requirements: list[Requirement] = Field(default_factory=list)

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

    def step_ids(self) -> list[str]:
        """Baseline step ids, in workflow order."""
        return [step.step_id for step in self.steps]
