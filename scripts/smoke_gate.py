"""Run the conformance gate over one encoding and one TSS, and print the result.

Usage:
    python scripts/smoke_gate.py <encoding.json> <tss.json>

A developer convenience for eyeballing gate behaviour on a fixture. It is not
part of the experiment harness: it writes nothing to runs/ and records no
provenance, so its output is for reading, not for citing.
"""

import json
import sys
from pathlib import Path

# scripts/ is not a package, so put the repo root on the path before importing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from design_council.gate import GateConfigError, evaluate  # noqa: E402
from design_council.schemas import TargetStateSpec, WorkflowEncoding  # noqa: E402


def load_json(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    encoding_path = Path(argv[1])
    tss_path = Path(argv[2])

    encoding = WorkflowEncoding.model_validate(load_json(encoding_path))
    tss = TargetStateSpec.model_validate(load_json(tss_path))

    print(f"encoding : {encoding_path}  ({encoding.workflow_id})")
    print(f"tss      : {tss_path}")

    try:
        result = evaluate(encoding, tss)
    except GateConfigError as error:
        print(f"\nGateConfigError: {error}", file=sys.stderr)
        return 1

    passed = sum(1 for r in result.results if r.passed)
    total = len(result.results)
    print(f"\nconformance_score: {result.conformance_score:.4f}  ({passed}/{total})\n")

    for entry in result.results:
        verdict = "PASS" if entry.passed else "FAIL"
        print(f"{entry.requirement_id}  {verdict}  {entry.reason}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
