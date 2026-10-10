"""Data assembly for review packs. Read-only; no model involvement.

Everything a pack prints is read from run manifests, gate outputs and target
state specifications, then checked against an independent recomputation. A pack
that cannot be reconciled with its own artefacts is not emitted.

The v1/v2 split is mechanical. A run whose manifest records
config.disposition_convention_version starting "v2" was produced under the v2
disposition convention and is excluded from these packs per the
instrument-versioning rule. Runs before 01034ae carry no version (v1); held-out
runs record "v1, restored 11 Oct 2026".
"""

import json
import statistics as st
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from design_council.measures.depth import DepthReport, measure_depth
from design_council.schemas import CallRecord, GateResult, TargetStateSpec, WorkflowEncoding

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_ROOT = REPO_ROOT / "runs"
ENCODINGS_DIR = REPO_ROOT / "data" / "encodings"
KB_PATH = REPO_ROOT / "design_council" / "kb" / "ifrs_slfrs_kb.yaml"

PROBE_ROLE = "model_resolution_probe"

SELECTION_RULE = (
    "Representative run selected by median per-condition depth; where two runs "
    "tie at the median, the earlier timestamp is used. Ties occurred in five of "
    "six cells owing to the coarse depth quantum."
)


class PackIntegrityError(Exception):
    """A pack's numbers cannot be reconciled with the artefacts they came from.

    Raised rather than adjusted. A review pack whose figures have been nudged
    into agreement is worse than no pack.
    """


class RunSummary(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    path: Path
    condition: str
    workflow_id: str
    git_commit: str
    resolved_model: str
    encoding_sha256: str
    kb_sha256: str
    depth: DepthReport
    gate: GateResult
    tss: TargetStateSpec
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    failed_attempts: int


def _encoding_for(workflow_id: str) -> WorkflowEncoding:
    for path in sorted(ENCODINGS_DIR.rglob("*.json")):
        with path.open() as handle:
            data = json.load(handle)
        if data.get("workflow_id") == workflow_id:
            return WorkflowEncoding.model_validate(data)

    raise PackIntegrityError(f"no encoding found for workflow {workflow_id!r}")


def encoding_path_for(workflow_id: str) -> Path:
    for path in sorted(ENCODINGS_DIR.rglob("*.json")):
        with path.open() as handle:
            if json.load(handle).get("workflow_id") == workflow_id:
                return path

    raise PackIntegrityError(f"no encoding found for workflow {workflow_id!r}")


def is_v2(manifest: dict[str, Any]) -> bool:
    """v2 runs record a convention version starting "v2".

    Presence of prompt_fragment_hashes no longer marks v2: the restored v1
    convention is hashed too.
    """
    version = manifest.get("config", {}).get("disposition_convention_version", "")
    return version.startswith("v2")


def _tokens(path: Path) -> tuple[int, int, int, int]:
    """Totals over every attempt, excluding the resolution probe.

    Failed attempts are counted: those tokens were billed. The probe is
    infrastructure and is not experimental work. See docs/freeze_notes.md.
    """
    records = [
        CallRecord.model_validate_json(line)
        for line in (path / "calls.jsonl").read_text().splitlines()
        if line.strip()
    ]
    work = [r for r in records if r.agent_role != PROBE_ROLE]

    return (
        sum(r.input_tokens for r in work),
        sum(r.output_tokens or 0 for r in work),
        sum(r.thinking_tokens or 0 for r in work),
        sum(1 for r in work if r.attempt_status.value != "ok"),
    )


def load_v1_runs(workflow_id: str) -> dict[str, list[RunSummary]]:
    """Every completed v1 run for a workflow, grouped by condition.

    Each summary's depth is recomputed from the disposition mapping and its
    conformance recounted from the per-requirement results; a disagreement with
    the logged values raises.
    """
    encoding = _encoding_for(workflow_id)
    grouped: dict[str, list[RunSummary]] = {"baseline": [], "council": []}

    for directory in sorted(RUNS_ROOT.glob("*/")):
        manifest_path = directory / "run_manifest.json"
        if not manifest_path.exists() or not (directory / "tss.json").exists():
            continue

        manifest = json.loads(manifest_path.read_text())
        if manifest["workflow_id"] != workflow_id or is_v2(manifest):
            continue

        tss = TargetStateSpec.model_validate_json((directory / "tss.json").read_text())
        gate = GateResult.model_validate_json(
            (directory / "gate_result.json").read_text()
        )
        depth = measure_depth(encoding, tss)

        _assert_consistent(directory, manifest, encoding, tss, gate, depth)

        input_tokens, output_tokens, thinking, failed = _tokens(directory)
        grouped[manifest["condition"]].append(
            RunSummary(
                run_id=manifest["run_id"],
                path=directory,
                condition=manifest["condition"],
                workflow_id=workflow_id,
                git_commit=manifest["git_commit"],
                resolved_model=manifest["resolved_model"],
                encoding_sha256=manifest["encoding_sha256"],
                kb_sha256=manifest["kb_sha256"],
                depth=depth,
                gate=gate,
                tss=tss,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                thinking_tokens=thinking,
                failed_attempts=failed,
            )
        )

    for condition, runs in grouped.items():
        if len(runs) != 3:
            raise PackIntegrityError(
                f"{workflow_id} {condition}: expected 3 v1 runs, found "
                f"{len(runs)}: {[r.run_id for r in runs]}"
            )

    return grouped


def _assert_consistent(directory, manifest, encoding, tss, gate, depth) -> None:
    """Every printed number must survive an independent recomputation."""
    recounted = sum(1 for r in gate.results if r.passed) / len(gate.results)
    if abs(recounted - gate.conformance_score) > 1e-9:
        raise PackIntegrityError(
            f"{directory.name}: conformance recount {recounted} disagrees with "
            f"logged {gate.conformance_score}. Manifest: {manifest}"
        )

    if len(gate.results) != len(encoding.requirements):
        raise PackIntegrityError(
            f"{directory.name}: gate reports {len(gate.results)} requirements, "
            f"encoding has {len(encoding.requirements)}. Manifest: {manifest}"
        )

    profile = depth.profile
    retained = profile.count_by_value("retained")
    recomputed = (profile.total_baseline_steps - retained) / profile.total_baseline_steps
    if abs(recomputed - depth.depth_score) > 1e-9:
        raise PackIntegrityError(
            f"{directory.name}: depth recompute {recomputed} disagrees with "
            f"{depth.depth_score}. Manifest: {manifest}"
        )

    if set(tss.baseline_step_ids) != set(encoding.step_ids()):
        raise PackIntegrityError(
            f"{directory.name}: TSS baseline ids do not match the encoding. "
            f"Manifest: {manifest}"
        )

    if manifest["encoding_sha256"] != _sha(encoding_path_for(encoding.workflow_id)):
        raise PackIntegrityError(
            f"{directory.name}: the encoding on disk has changed since this run. "
            f"Manifest: {manifest}"
        )


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def representative(runs: list[RunSummary]) -> RunSummary:
    """Median depth; earlier timestamp breaks a tie. See SELECTION_RULE."""
    ordered = sorted(runs, key=lambda r: (r.depth.depth_score, r.run_id))
    median = st.median(r.depth.depth_score for r in ordered)

    for run in ordered:  # ordered by score then run_id, so this is the earliest
        if abs(run.depth.depth_score - median) < 1e-9:
            return run

    raise PackIntegrityError(f"no run at median depth {median}")


def tie_at_median(runs: list[RunSummary]) -> bool:
    median = st.median(r.depth.depth_score for r in runs)
    return sum(1 for r in runs if abs(r.depth.depth_score - median) < 1e-9) > 1


def elimination_census() -> dict[str, int]:
    """Dispositions across every completed run, both instrument versions."""
    counts: dict[str, int] = {}
    runs = 0
    for directory in sorted(RUNS_ROOT.glob("*/")):
        if not (directory / "tss.json").exists():
            continue
        manifest = json.loads((directory / "run_manifest.json").read_text())
        encoding = _encoding_for(manifest["workflow_id"])
        tss = TargetStateSpec.model_validate_json((directory / "tss.json").read_text())
        for key, value in measure_depth(encoding, tss).profile.counts.items():
            counts[key] = counts.get(key, 0) + value
        runs += 1

    counts["_runs"] = runs
    counts["_total"] = sum(v for k, v in counts.items() if not k.startswith("_"))

    return counts
