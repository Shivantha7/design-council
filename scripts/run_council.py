"""Run the Design Council over one encoding, live.

    python scripts/run_council.py data/encodings/dev/p2p_vendor_invoice_processing.json

Fifteen model calls: seven independent positions, seven critiques, one
synthesis. Writes a run directory under runs/ with the same shape as a baseline
run, plus the deliberation transcript.

The working tree must be clean — a run from a modified tree is not reproducible
from its commit, and RunLogger refuses it.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from design_council.agents.anthropic_client import AnthropicClient  # noqa: E402
from design_council.agents.council import (  # noqa: E402
    CouncilError,
    charter_hashes,
    run_council,
)
from design_council.kb.loader import KB_PATH, load_kb  # noqa: E402
from design_council.run_logging import (  # noqa: E402
    DEFAULT_REQUESTED_MODEL,
    DEFAULT_RUNS_ROOT,
    RunIntegrityError,
    RunLogger,
    git_commit,
    load_env,
    resolve_model,
    sha256_file,
)
from design_council.schemas import (  # noqa: E402
    CallRecord,
    Disposition,
    GateResult,
    TargetStateSpec,
    WorkflowEncoding,
)


def print_call_table(logger: RunLogger) -> None:
    """Per-call accounting, read back from the log rather than accumulated."""
    lines = [l for l in logger.calls_path.read_text().splitlines() if l.strip()]
    records = [CallRecord.model_validate(json.loads(l)) for l in lines]

    print()
    print(f"{'agent_role':28} {'status':>14} {'in':>7} {'out':>7} {'thinking':>9}")
    print(f"{'-' * 28} {'-' * 14} {'-' * 7} {'-' * 7} {'-' * 9}")

    total_in = total_out = total_thinking = 0
    for record in records:
        thinking = "-" if record.thinking_tokens is None else str(record.thinking_tokens)
        out = "-" if record.output_tokens is None else str(record.output_tokens)
        print(
            f"{record.agent_role:28} {record.attempt_status.value:>14} "
            f"{record.input_tokens:>7} {out:>7} {thinking:>9}"
        )
        # Every attempt counts toward cost, including failed streams: those
        # tokens were billed. See docs/freeze_notes.md.
        total_in += record.input_tokens
        total_out += record.output_tokens or 0
        total_thinking += record.thinking_tokens or 0

    failed = sum(1 for r in records if r.attempt_status.value != "ok")
    print(f"{'-' * 28} {'-' * 14} {'-' * 7} {'-' * 7} {'-' * 9}")
    print(f"{'TOTAL (' + str(len(records)) + ' attempts)':28} {'':>14} {total_in:>7} "
          f"{total_out:>7} {total_thinking:>9}")
    print()
    print("Reasoning tokens are part of output, not additional to it.")
    if failed:
        print(f"{failed} attempt(s) failed mid-stream; their tokens are counted "
              f"(billed) but their text was discarded.")


def print_report(
    encoding: WorkflowEncoding, tss: TargetStateSpec, gate_result: GateResult
) -> None:
    substantive = gate_result.substantive_score
    substantive_text = (
        "undefined (every requirement was vacuous)"
        if substantive is None
        else f"{substantive:.4f}"
    )
    passed = sum(1 for r in gate_result.results if r.passed)

    print()
    print(f"workflow          : {encoding.workflow_id}")
    print(f"baseline steps    : {len(encoding.steps)}")
    print(f"target steps      : {len(tss.steps)}")
    print()
    print(f"conformance_score : {gate_result.conformance_score:.4f}  "
          f"({passed}/{len(gate_result.results)})")
    print(f"vacuous_count     : {gate_result.vacuous_count}")
    print(f"substantive_score : {substantive_text}")
    print()

    for entry in gate_result.results:
        verdict = "PASS" if entry.passed else "FAIL"
        marker = " [vacuous]" if entry.vacuous else ""
        print(f"  {entry.requirement_id}  {verdict}{marker}  {entry.reason}")

    print()
    print("dispositions:")
    for disposition in Disposition:
        count = sum(1 for e in tss.disposition_mapping if e.disposition is disposition)
        print(f"  {disposition.value:14} {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("encoding", type=Path)
    parser.add_argument("--model", default=DEFAULT_REQUESTED_MODEL)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--model-created-at", default=None)
    args = parser.parse_args()

    loaded = load_env()
    if loaded:
        print(f"loaded from .env: {loaded}")

    with args.encoding.open() as handle:
        encoding = WorkflowEncoding.model_validate(json.load(handle))
    kb = load_kb()
    print(f"encoding          : {encoding.workflow_id} ({len(encoding.steps)} steps, "
          f"{len(encoding.requirements)} requirements)")
    print(f"knowledge base    : {len(kb.entries)} entries")
    print("protocol          : 7 positions + 7 critiques + 1 synthesis = 15 calls")

    client = AnthropicClient(requested_model=args.model)

    print(f"resolving model   : {args.model} ...")
    resolution = resolve_model(client, args.model)
    print(f"resolved to       : {resolution.resolved_model}")

    model_created_at = args.model_created_at
    if model_created_at is None:
        model_created_at = str(client._client.models.retrieve(args.model).created_at)

    try:
        logger = RunLogger(
            args.runs_root,
            condition="council",
            workflow_id=encoding.workflow_id,
            requested_model=args.model,
            resolution=resolution,
            model_created_at=model_created_at,
            git_commit=git_commit(),
            encoding_sha256=sha256_file(args.encoding),
            kb_sha256=sha256_file(KB_PATH),
            config={
                "encoding_path": str(args.encoding),
                "sampling_params": client.sampling_params(),
                "sampling": (
                    "provider default; temperature/top_p/top_k not settable on "
                    "this model family"
                ),
                "protocol": "council: 7 round1 + 7 round2 + 1 synthesis",
                "charter_hashes": charter_hashes(),
            },
        )
    except RunIntegrityError as error:
        print(f"\nRunIntegrityError: {error}", file=sys.stderr)
        return 1

    print(f"run_id            : {logger.run_id}")

    try:
        tss, gate_result = run_council(encoding, kb, client, logger, client.sampling_params())
    except CouncilError as error:
        print(f"\nCouncilError: {error}", file=sys.stderr)
        print_call_table(logger)
        print(f"run directory     : {logger.run_dir}", file=sys.stderr)
        return 1

    print_report(encoding, tss, gate_result)
    print_call_table(logger)

    print(f"run_id            : {logger.run_id}")
    print(f"run directory     : {logger.run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
