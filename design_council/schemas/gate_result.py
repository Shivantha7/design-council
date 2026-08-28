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
    vacuous: bool = False

    @model_validator(mode="after")
    def check_only_passes_are_vacuous(self) -> "RequirementResult":
        """A failing requirement is never vacuous.

        Vacuity means the rule had nothing left to check and so could not be
        violated. A rule that was violated was, by definition, checked.
        """
        if self.vacuous and not self.passed:
            raise ValueError(
                f"{self.requirement_id}: a failing requirement cannot be vacuous"
            )

        return self


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

    def vacuous_requirement_ids(self) -> list[str]:
        """Requirements that passed only because nothing was left to check."""
        return [r.requirement_id for r in self.results if r.vacuous]

    @property
    def vacuous_count(self) -> int:
        """How many passes held only because their subject was eliminated.

        Read from the structured `vacuous` flag on each result, not from the
        reason text — the prose marking is for human readers and must not be
        load-bearing.
        """
        return sum(1 for r in self.results if r.vacuous)

    @property
    def substantive_score(self) -> float | None:
        """Conformance over only those requirements that were actually tested.

        conformance_score counts a vacuous pass as a pass, which flatters a
        redesign that deleted the step a rule constrained. This view removes
        vacuous requirements from both the numerator and the denominator, so it
        answers a narrower question: of the rules that had something to check,
        what fraction held?

        Returns None when every requirement was vacuous. There is no defensible
        number for that case: 1.0 would claim total conformance on the strength
        of nothing having been checked, and 0.0 would claim a failure that no
        rule reported. An undefined score must stay undefined.
        """
        tested = [r for r in self.results if not r.vacuous]
        if not tested:
            return None

        return sum(1 for r in tested if r.passed) / len(tested)


def score_for(results: list[RequirementResult]) -> float:
    """Fraction of requirements passed.

    An empty results list scores 1.0: nothing was checked, so nothing failed.
    That is vacuous rather than meaningful, which is why evaluate() refuses an
    encoding with no requirements instead of producing one. The case remains
    defined here only so that a GateResult constructed directly is total.
    """
    if not results:
        return 1.0

    return sum(1 for r in results if r.passed) / len(results)
