"""Run the compute-matched sequential single agent over one encoding, live. EXPLORATORY.

    python scripts/run_sequential.py data/encodings/heldout/p2p_three_way_matching.json --reps 5

Same logging, gate and measures as the baseline and council runners. Each rep is
its own run directory under runs/, condition 'sequential'. Use --allow-dirty only
if you choose not to commit first; the manifest records the dirty flag.
"""
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from design_council.agents.anthropic_client import AnthropicClient  # noqa: E402
from design_council.agents.baseline import DISPOSITION_CONVENTION_VERSION, prompt_fragment_hashes  # noqa: E402
from design_council.agents.council import charter_hashes  # noqa: E402
from design_council.agents.sequential import SequentialError, run_sequential  # noqa: E402
from design_council.kb.loader import KB_PATH, load_kb  # noqa: E402
from design_council.run_logging import (  # noqa: E402
    DEFAULT_REQUESTED_MODEL, DEFAULT_RUNS_ROOT, RunIntegrityError, RunLogger,
    git_commit, load_env, resolve_model, sha256_file,
)
from design_council.schemas import WorkflowEncoding  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("encoding", type=Path)
    ap.add_argument("--model", default=DEFAULT_REQUESTED_MODEL)
    ap.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--allow-dirty", action="store_true")
    args = ap.parse_args()
    load_env()
    encoding = WorkflowEncoding.model_validate(json.loads(args.encoding.read_text()))
    kb = load_kb()
    client = AnthropicClient(requested_model=args.model)
    resolution = resolve_model(client, args.model)
    created = str(client._client.models.retrieve(args.model).created_at)
    failures = 0
    for rep in range(1, args.reps + 1):
        try:
            logger = RunLogger(
                args.runs_root, condition="sequential", workflow_id=encoding.workflow_id,
                requested_model=args.model, resolution=resolution, model_created_at=created,
                git_commit=git_commit(), encoding_sha256=sha256_file(args.encoding),
                kb_sha256=sha256_file(KB_PATH), allow_dirty=args.allow_dirty,
                config={"encoding_path": str(args.encoding), "sampling_params": client.sampling_params(),
                        "protocol": "sequential single agent: 7 cumulative perspectives, 7 reconsiderations, synthesis (15 calls)",
                        "exploratory": True, "post_freeze": "2026-10-25", "rep": rep,
                        "prompt_fragment_hashes": prompt_fragment_hashes(), "charter_hashes": charter_hashes(),
                        "disposition_convention_version": DISPOSITION_CONVENTION_VERSION},
            )
        except RunIntegrityError as e:
            print(f"RunIntegrityError: {e}", file=sys.stderr); return 1
        t0 = time.time()
        print(f"[rep {rep}] run_id {logger.run_id}")
        try:
            tss, gate = run_sequential(encoding, kb, client, logger, client.sampling_params())
            print(f"[rep {rep}] conformance {gate.conformance_score:.3f}  target steps {len(tss.steps)}  "
                  f"{(time.time() - t0) / 60:.1f} min")
        except SequentialError as e:
            failures += 1; print(f"[rep {rep}] FAILED: {e}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
