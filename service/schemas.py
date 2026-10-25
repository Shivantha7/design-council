"""Request and response contracts for the live service (pydantic, per CLAUDE.md)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from design_council.schemas import WorkflowEncoding

Condition = Literal["council", "baseline"]
Profile = Literal["transactional", "judgment-dense"]


class ValidationIssue(BaseModel):
    code: str
    message: str
    location: str = ""


class ValidationReport(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


class RunRequest(BaseModel):
    encoding: WorkflowEncoding
    conditions: list[Condition] = Field(default_factory=lambda: ["council"], min_length=1)
    # Productivity estimate subgroup (docs/PRODUCTIVITY_METHOD.md section 4). Judgment-dense
    # is the wider, more pessimistic exception-rate assumption.
    profile: Profile = "judgment-dense"
    confirm_cost: bool = False


class CostEstimate(BaseModel):
    conditions: list[Condition]
    estimate_usd: float
    spent_today_usd: float
    daily_cap_usd: float
    message: str


class JobCreated(BaseModel):
    job_id: str
    status: str
    estimate_usd: float


class JobSummary(BaseModel):
    job_id: str
    created_utc: str
    status: str
    workflow_id: str
    workflow_name: str
    conditions: list[Condition]
    run_ids: dict[str, str]
    estimate_usd: float
    cost_usd: float | None
    error: str | None
    finished_utc: str | None


class ConditionResult(BaseModel):
    condition: Condition
    run_id: str
    run_dir: str
    tss: dict[str, Any]
    gate: dict[str, Any]
    depth: dict[str, Any]
    productivity: dict[str, Any]
    structural: dict[str, Any]
    transcript: list[dict[str, Any]]
    tokens: dict[str, int]
    cost_usd: float
    runtime_min: float


class JobResult(BaseModel):
    job: JobSummary
    label: str = ("Live demonstration on a user-supplied workflow. Not part of the pre-registered "
                  "study. The productivity figure is an exploratory estimate under stated assumptions.")
    results: dict[str, ConditionResult]
