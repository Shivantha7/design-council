"""Elimination-space accounting per encoding. Read-only; no model involvement.

    python scripts/elimination_space.py                      # every encoding under data/encodings/
    python scripts/elimination_space.py <encoding.json> ...  # named encodings only

For each encoding, prints one markdown table row:

    protected   steps whose elimination fails a gate rule. Two rule types fail
                when their step is eliminated: step_preserved and
                inputs_required. Relational rules (ordering_preserved,
                actor_separation) pass vacuously instead, so they protect
                nothing from elimination.
    documented  steps listed in unconstrained_by_design: the recorded decision
                that a step is deliberately open to elimination.
    gate-open   steps the gate would let a TSS eliminate without any failure,
                i.e. total minus protected.

documented and gate-open should be the same set. Where they differ, the row is
flagged: a step the gate leaves open but the encoding does not document is an
unrecorded gap; a documented step the gate actually protects is a contradiction.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from design_council.schemas import WorkflowEncoding  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODINGS_DIR = REPO_ROOT / "data" / "encodings"

# Rule types whose evaluation fails outright when the step is eliminated.
# See _step_preserved and _inputs_required in design_council/gate/gate.py.
FAILS_ON_ELIMINATION = {"step_preserved", "inputs_required"}


def protected_steps(encoding: WorkflowEncoding) -> list[str]:
    ids = {
        r.params["baseline_step_id"]
        for r in encoding.requirements
        if r.rule_type in FAILS_ON_ELIMINATION
    }
    return [s for s in encoding.step_ids() if s in ids]


def row(encoding: WorkflowEncoding, split: str) -> str:
    steps = encoding.step_ids()
    protected = protected_steps(encoding)
    gate_open = [s for s in steps if s not in protected]
    documented = [s for s in steps if s in encoding.unconstrained_by_design]

    if set(gate_open) == set(documented):
        check = "ok"
    else:
        undocumented = sorted(set(gate_open) - set(documented))
        contradicted = sorted(set(documented) - set(gate_open))
        parts = []
        if undocumented:
            parts.append(f"open but undocumented: {', '.join(undocumented)}")
        if contradicted:
            parts.append(f"documented but protected: {', '.join(contradicted)}")
        check = "**MISMATCH** " + "; ".join(parts)

    return (
        f"| {encoding.workflow_id} | {split} | {len(steps)} | "
        f"{len(protected)} ({', '.join(protected) or '-'}) | "
        f"{len(documented)} ({', '.join(documented) or '-'}) | "
        f"{len(gate_open)}/{len(steps)} | {check} |"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("encodings", nargs="*", type=Path)
    args = parser.parse_args()

    paths = [p.resolve() for p in args.encodings] or sorted(ENCODINGS_DIR.rglob("*.json"))
    if not paths:
        print("no encodings found", file=sys.stderr)
        return 1

    print("| Workflow | Split | Steps | Protected (fail if eliminated) "
          "| Documented open (unconstrained_by_design) | Gate-open | Check |")
    print("|---|---|---:|---|---|---:|---|")
    for path in paths:
        encoding = WorkflowEncoding.model_validate(json.loads(path.read_text()))
        split = path.parent.name if path.parent.parent == ENCODINGS_DIR else "-"
        print(row(encoding, split))

    return 0


if __name__ == "__main__":
    sys.exit(main())
