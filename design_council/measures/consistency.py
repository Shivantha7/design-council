"""Run-to-run consistency: how alike repeated runs of one cell are.

PRE-REGISTERED (docs/freeze_notes.md, docs/PREREGISTRATION_HELDOUT.md section 4)

    agreement(a, b) = the share of baseline steps given the same disposition
                      label in run a and run b

    consistency of a set of runs = the mean of agreement over every pair of
                                   runs, k(k-1)/2 pairs for k runs

It runs from 0 to 1, where 1 means every pair of runs labelled every step
identically. It is unweighted, for the same reason the depth scalar is. It
compares labels only: target-step structure and actors are not part of it.

Computed from TargetStateSpecs alone. No model is involved and nothing is
written, so it can be recomputed from artefacts on disk at any time.
"""

from itertools import combinations

from design_council.schemas import TargetStateSpec


def agreement(a: TargetStateSpec, b: TargetStateSpec, step_ids: list[str]) -> float:
    """Share of the given baseline steps labelled alike in two runs."""
    same = sum(1 for s in step_ids if a.disposition_for(s) is b.disposition_for(s))
    return same / len(step_ids)


def pairwise_agreements(specs: list[TargetStateSpec], step_ids: list[str]) -> list[float]:
    """agreement for every pair of runs, in combinations() order."""
    if len(specs) < 2:
        raise ValueError(f"consistency needs at least two runs, got {len(specs)}")
    return [agreement(a, b, step_ids) for a, b in combinations(specs, 2)]


def consistency(specs: list[TargetStateSpec], step_ids: list[str]) -> float:
    """Mean pairwise agreement across a set of runs of one cell."""
    pairs = pairwise_agreements(specs, step_ids)
    return sum(pairs) / len(pairs)
