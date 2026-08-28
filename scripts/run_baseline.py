"""Run the single-agent baseline over one encoding, live.

Usage:
    python scripts/run_baseline.py data/encodings/dev/p2p_vendor_invoice_processing.json
    python scripts/run_baseline.py <encoding.json> --model claude-sonnet-5 --runs-root runs

Makes real API calls and writes a run directory under runs/. The working tree
must be clean: a run from a modified tree is not reproducible from its commit,
and RunLogger refuses it.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from design_council.agents.anthropic_client import AnthropicClient  # noqa: E402
from design_council.agents.baseline import BaselineError, run_baseline  # noqa: E402
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
from design_council.schemas import WorkflowEncoding  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("encoding", type=Path, help="path to a workflow encoding JSON")
    parser.add_argument("--model", default=DEFAULT_REQUESTED_MODEL)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument(
        "--model-created-at",
        default=None,
        help="provider created_at for the model, from the models endpoint",
    )
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

    client = AnthropicClient(requested_model=args.model)

    print(f"resolving model   : {args.model} ...")
    resolution = resolve_model(client, args.model)
    print(f"resolved to       : {resolution.resolved_model}")

    model_created_at = args.model_created_at
    if model_created_at is None:
        model_created_at = _model_created_at(client, args.model)

    try:
        logger = RunLogger(
            args.runs_root,
            condition="baseline",
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
            },
        )
    except RunIntegrityError as error:
        print(f"\nRunIntegrityError: {error}", file=sys.stderr)
        return 1

    print(f"run_id            : {logger.run_id}")

    try:
        run_baseline(encoding, kb, client, logger, client.sampling_params())
    except BaselineError as error:
        print(f"\nBaselineError: {error}", file=sys.stderr)
        print(f"\nrun_id            : {logger.run_id}", file=sys.stderr)
        print(f"run directory     : {logger.run_dir}", file=sys.stderr)
        return 1

    print()
    print(f"run_id            : {logger.run_id}")
    print(f"run directory     : {logger.run_dir}")
    return 0


def _model_created_at(client: AnthropicClient, model: str) -> str:
    """Read created_at for the model straight from the provider."""
    info = client._client.models.retrieve(model)
    return str(info.created_at)


if __name__ == "__main__":
    sys.exit(main())
