"""Transformation depth: how far a target state departs from its baseline.

Motivation. The conformance gate answers whether a redesign broke a rule. It
does not answer how much the redesign changed, and on the first paired runs it
could not tell them apart: a baseline that retained five of eight steps and a
council that restructured four of those same five both scored 1.0 with no
vacuous passes. Depth is the measure that separates them.

PRE-REGISTERED — PRIMARY
    The disposition profile: the count and proportion of baseline steps under
    each disposition. This is the measure named in the proposal.

    The scalar depth score is the proportion of baseline steps not retained:

        depth = (eliminated + merged + absorbed + restructured) / total

    The profile concept is pre-registered; this scalar collapse of it is being
    fixed HERE AND NOW, before any held-out run, so that the definition cannot
    be chosen after seeing held-out results. 'retained' is the only disposition
    asserting a step carried over substantially unchanged, so its complement is
    the share of the workflow the redesign actually touched. Nothing in the
    scalar is weighted: eliminating a step and restructuring one count alike,
    because a defensible weighting would itself be a post-hoc choice.

SUPPLEMENTARY — DESCRIPTIVE, NOT PRE-REGISTERED
    actor_reassignments, net_new_steps, step_count_delta and mean fan-out are
    exploratory descriptives for the qualitative analysis in section 7.4. They
    are not pre-registered, must not be reported as confirmatory findings, and
    are labelled as supplementary everywhere they are emitted.

Everything here is computed from a TargetStateSpec and its WorkflowEncoding.
No model is involved and no network call is made, so a measure can be recomputed
from artefacts already on disk at any time.
"""

from pydantic import BaseModel, ConfigDict, Field

from design_council.schemas import Disposition, TargetStateSpec, WorkflowEncoding

RETAINED = Disposition.RETAINED


class DispositionProfile(BaseModel):
    """Counts and proportions of baseline steps under each disposition."""

    model_config = ConfigDict(extra="forbid")

    total_baseline_steps: int = Field(ge=1)
    counts: dict[str, int]
    proportions: dict[str, float]

    def count(self, disposition: Disposition) -> int:
        return self.counts[disposition.value]


class SupplementaryDescriptives(BaseModel):
    """Exploratory descriptives. NOT pre-registered; not confirmatory.

    For the qualitative analysis only. Reporting any of these as a primary
    result would be a post-hoc measure choice.
    """

    model_config = ConfigDict(extra="forbid")

    actor_reassignments: int = Field(ge=0)
    actor_reassignment_ids: list[str]
    net_new_steps: int = Field(ge=0)
    net_new_step_ids: list[str]
    baseline_step_count: int = Field(ge=1)
    target_step_count: int = Field(ge=0)
    step_count_delta: int
    mean_fan_out: float = Field(ge=0.0)


class DepthReport(BaseModel):
    """The primary measure and, separately, the supplementary descriptives."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    profile: DispositionProfile
    depth_score: float = Field(ge=0.0, le=1.0)
    supplementary: SupplementaryDescriptives


def disposition_profile(tss: TargetStateSpec) -> DispositionProfile:
    """Count baseline steps under each disposition, in enum order."""
    entries = tss.disposition_mapping
    total = len(entries)

    counts = {
        disposition.value: sum(
            1 for e in entries if e.disposition is disposition
        )
        for disposition in Disposition
    }
    proportions = {key: value / total for key, value in counts.items()}

    return DispositionProfile(
        total_baseline_steps=total, counts=counts, proportions=proportions
    )


def depth_score(profile: DispositionProfile) -> float:
    """Proportion of baseline steps not retained. The pre-registered scalar."""
    retained = profile.count(RETAINED)

    return (profile.total_baseline_steps - retained) / profile.total_baseline_steps


def supplementary_descriptives(
    encoding: WorkflowEncoding, tss: TargetStateSpec
) -> SupplementaryDescriptives:
    """Exploratory descriptives. NOT pre-registered.

    actor_reassignments counts baseline steps whose traced target steps carry
    any actor other than the baseline's. Eliminated steps are excluded: they
    have no target step, so there is no actor to compare, and counting them
    would conflate removing work with moving it.

    mean_fan_out averages the number of target steps per baseline step across
    all baseline steps, counting eliminated steps as zero.
    """
    reassigned = []
    fan_out_total = 0

    for step in encoding.steps:
        targets = tss.target_steps_for(step.step_id)
        fan_out_total += len(targets)

        if not targets:  # eliminated: no actor to compare
            continue
        if {target.actor for target in targets} != {step.actor}:
            reassigned.append(step.step_id)

    traced = {
        target_id
        for entry in tss.disposition_mapping
        for target_id in entry.target_step_ids
    }
    net_new = [step.step_id for step in tss.steps if step.step_id not in traced]

    return SupplementaryDescriptives(
        actor_reassignments=len(reassigned),
        actor_reassignment_ids=reassigned,
        net_new_steps=len(net_new),
        net_new_step_ids=net_new,
        baseline_step_count=len(encoding.steps),
        target_step_count=len(tss.steps),
        step_count_delta=len(tss.steps) - len(encoding.steps),
        mean_fan_out=fan_out_total / len(encoding.steps),
    )


def measure_depth(encoding: WorkflowEncoding, tss: TargetStateSpec) -> DepthReport:
    """The full report: pre-registered primary measure plus descriptives."""
    profile = disposition_profile(tss)

    return DepthReport(
        workflow_id=encoding.workflow_id,
        profile=profile,
        depth_score=depth_score(profile),
        supplementary=supplementary_descriptives(encoding, tss),
    )
