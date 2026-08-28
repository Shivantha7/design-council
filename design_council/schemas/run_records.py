"""Data contracts for run provenance.

A run is one experimental unit: one condition, over one workflow, with one
model. Its manifest records the conditions it ran under; its call records
record every exchange with the model.

Together these are what makes a reported score checkable months later. The
manifest fixes what the code and inputs were, the call records fix what was
asked and what came back. Neither is reconstructable after the fact, which is
why they are written as the run proceeds rather than summarised at the end.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SHA256_HEX = r"^[0-9a-f]{64}$"
GIT_COMMIT_HEX = r"^[0-9a-f]{40}$"


class Condition(str, Enum):
    """Which arm of the experiment produced this run."""

    BASELINE = "baseline"
    COUNCIL = "council"


class CallRecord(BaseModel):
    """One exchange with a model.

    requested_model is what the caller asked for; resolved_model is what the
    provider says it used. They differ whenever an undated alias resolves to a
    snapshot, which is exactly the case a reproducible run has to record.

    thinking_tokens is the reasoning portion of output_tokens, where the
    provider reports it. It is not a separate charge — output_tokens already
    includes it — but without it a run's visible completion length looks
    inexplicably small next to its billed output. None means the provider did
    not report a breakdown.

    prompt_hash rather than the prompt itself keeps the line a manageable size
    while still letting two runs be compared for identical input. The prompt is
    reconstructable from the KB and encoding, both of which the manifest pins by
    hash.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp_utc: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    condition: Condition
    agent_role: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    requested_model: str = Field(min_length=1)
    resolved_model: str = Field(min_length=1)
    sampling_params: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    prompt_hash: str = Field(pattern=SHA256_HEX)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    thinking_tokens: int | None = None
    raw_completion: str


class ResolutionProbe(BaseModel):
    """The single minimal completion used to learn what a model id resolves to.

    Recorded because the resolution is a measurement, not a configuration
    value: it was obtained by asking the provider at a particular moment, and
    the token counts show the probe was a real exchange rather than an assumed
    answer.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp_utc: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class RunManifest(BaseModel):
    """The conditions one run was carried out under.

    model_created_at is captured by the caller from the provider's models
    endpoint. Where a provider exposes no dated snapshot id, it is the only
    thing distinguishing one resolution of an alias from another, so it is
    required rather than optional.

    resolved_model is what the provider actually used, learned by probe rather
    than assumed. It is the value enforced on every call in the run.

    git_dirty is always recorded, even when the run was allowed to proceed from
    a modified tree. A run from a dirty tree is not reproducible from its
    commit alone, and a reader must be able to see that without inferring it.

    encoding_sha256 and kb_sha256 pin the inputs by content, not by path: a
    later edit to an encoding cannot silently change what a recorded run was
    run against.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    created_utc: str = Field(min_length=1)
    condition: Condition
    workflow_id: str = Field(min_length=1)
    requested_model: str = Field(min_length=1)
    resolved_model: str = Field(min_length=1)
    resolution_probe: ResolutionProbe
    model_created_at: str = Field(min_length=1)
    git_commit: str = Field(pattern=GIT_COMMIT_HEX)
    git_dirty: bool
    encoding_sha256: str = Field(pattern=SHA256_HEX)
    kb_sha256: str = Field(pattern=SHA256_HEX)
    config: dict[str, Any] = Field(default_factory=dict)
