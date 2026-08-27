"""Data contract for the output of the conformance gate.

A GateResult is the gate's verdict on one Target-State Specification: one
entry per requirement in the source encoding, and the fraction of those
requirements that passed. It is written to runs/ alongside the TSS it judged,
so the reason strings must stand on their own months later.
"""

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RequirementResult(BaseModel):
    """The gate's verdict on a single requirement.

    reason states what was checked and what was found, in terms of step ids and
    actors rather than prose, so that a reader can confirm the verdict against
    the TSS by hand. A requirement that passed only because it had nothing to
    check says so, prefixed 'vacuously satisfied: '.
    """

    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(min_length=1)
    passed: bool
    reason: str = Field(min_length=1)


class GateResult(BaseModel):
    """Per-requirement verdicts and the resulting conformance score."""

    model_config = ConfigDict(extra="forbid")

    results: list[RequirementResult] = Field(default_factory=list)
    conformance_score: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def check_score_matches_results(self) -> "GateResult":
        """The score is a function of the results; it may not disagree with them.

        Recomputed here so that a GateResult read back from runs/ is checked
        against its own contents rather than trusted.
        """
        requirement_ids = [r.requirement_id for r in self.results]
        duplicates = sorted(
            {i for i in requirement_ids if requirement_ids.count(i) > 1}
        )
        if duplicates:
            raise ValueError(f"duplicate requirement_id(s) in results: {duplicates}")

        expected = score_for(self.results)
        if not math.isclose(self.conformance_score, expected, rel_tol=1e-9):
            raise ValueError(
                f"conformance_score {self.conformance_score} does not match the "
                f"results, which give {expected}"
            )

        return self

    def result_for(self, requirement_id: str) -> RequirementResult:
        """The verdict on one requirement."""
        for result in self.results:
            if result.requirement_id == requirement_id:
                return result

        raise KeyError(f"no result for requirement {requirement_id!r}")

    def failed_requirement_ids(self) -> list[str]:
        """Requirements that did not pass, in the order they were evaluated."""
        return [r.requirement_id for r in self.results if not r.passed]


def score_for(results: list[RequirementResult]) -> float:
    """Fraction of requirements passed.

    An encoding with no requirements scores 1.0: nothing was checked, so
    nothing failed. That is vacuous rather than meaningful, and the caller is
    responsible for not reading it as evidence of conformance.
    """
    if not results:
        return 1.0

    return sum(1 for r in results if r.passed) / len(results)
