"""Run-to-run consistency for the v1 development grid. Read-only.

    python scripts/measure_consistency_dev.py

Uses design_council.measures.consistency, the same code the held-out analysis
uses, over every completed v1 dev run (design_council.measures.packs selects
them and excludes v2). Prints, per cell, n and consistency with the range of
its pairwise agreements, then the mean of cell consistencies per condition. The
held-out analysis reports its condition comparison the same way.
"""

import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from design_council.measures.consistency import (  # noqa: E402
    consistency,
    pairwise_agreements,
)
from design_council.measures.packs import load_v1_runs  # noqa: E402

DEV_WORKFLOWS = ["P2P-VIP-01", "R2R-PC-01", "FPA-RF-01"]
CONDITIONS = ["council", "baseline"]


def main() -> int:
    print("| Cell | n | Consistency (pairwise range) |")
    print("|---|---:|---|")
    by_condition = {c: [] for c in CONDITIONS}
    for workflow_id in DEV_WORKFLOWS:
        grouped = load_v1_runs(workflow_id)
        for condition in CONDITIONS:
            runs = grouped[condition]
            specs = [r.tss for r in runs]
            step_ids = specs[0].baseline_step_ids
            pairs = pairwise_agreements(specs, step_ids)
            value = consistency(specs, step_ids)
            by_condition[condition].append(value)
            print(f"| {workflow_id} {condition} | {len(runs)} | "
                  f"{value:.3f} ({min(pairs):.3f}–{max(pairs):.3f}) |")
    print()
    for condition in CONDITIONS:
        print(f"{condition}: mean of cell consistencies {mean(by_condition[condition]):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
