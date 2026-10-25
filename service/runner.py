"""Background job execution: the research engine, called unchanged, on a live encoding.

For each requested condition, in order:
  1. resolve the model (the probe is logged like any call);
  2. open a LiveRunLogger under runs_live/ with allow_dirty=True (live runs are recorded
     as dirty-tree runs and never written to runs/);
  3. call design_council.agents.council.run_council or design_council.agents.baseline.run_baseline,
     which gate the TSS with the deterministic gate and write tss.json and gate_result.json;
  4. compute measures from the run directory: depth (design_council.measures.depth),
     productivity (the committed model in scripts/productivity_heldout.py, same parameters
     and seed), structural counts, tokens, cost and runtime.

Progress events are emitted as each call is logged, so the client sees round 1 role by
role, then round 2, synthesis, gate and measures.
"""

import importlib.util
import json
import random
from datetime import datetime
from pathlib import Path
from statistics import median

from design_council.agents.baseline import (
    DISPOSITION_CONVENTION_VERSION,
    prompt_fragment_hashes,
    run_baseline,
)
from design_council.agents.council import charter_hashes, run_council
from design_council.kb.loader import KB_PATH, load_kb
from design_council.measures.actor_class import AGENTIC_ONLY, PRIMARY
from design_council.measures.depth import measure_depth
from design_council.run_logging import (
    RunLogger,
    git_commit,
    resolve_model,
    sha256_file,
    sha256_text,
)
from design_council.schemas import CallRecord, WorkflowEncoding

from service.config import PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M, REPO_ROOT, Settings
from service.mock import ServiceMockClient
from service.store import Store

PROBE_ROLE = "model_resolution_probe"
SOURCE_LABEL = "live service demonstration (not part of the pre-registered study)"

_spec = importlib.util.spec_from_file_location("productivity_heldout", REPO_ROOT / "scripts" / "productivity_heldout.py")
productivity_model = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(productivity_model)


def phase_of(agent_role: str) -> tuple[str, str]:
    if agent_role.startswith("round1_"):
        return "round 1", agent_role[len("round1_"):]
    if agent_role.startswith("round2_"):
        return "round 2", agent_role[len("round2_"):]
    if agent_role.startswith("synthesis"):
        return "synthesis", agent_role
    if agent_role == PROBE_ROLE:
        return "setup", agent_role
    return "single agent", agent_role


class LiveRunLogger(RunLogger):
    """RunLogger that also emits a progress event after each call is safely on disk."""

    def __init__(self, *args, store: Store, job_id: str, **kwargs):
        # Set before super().__init__, which logs the resolution probe through log_call.
        self.store, self.job_id = store, job_id
        super().__init__(*args, **kwargs)

    def log_call(self, record: CallRecord) -> None:
        super().log_call(record)
        phase, role = phase_of(record.agent_role)
        self.store.emit(self.job_id, "call", condition=self.condition.value, run_id=self.run_id,
                        agent_role=record.agent_role, phase=phase, role=role,
                        attempt_status=record.attempt_status.value,
                        input_tokens=record.input_tokens, output_tokens=record.output_tokens or 0)


def make_client(settings: Settings, encoding: WorkflowEncoding):
    if settings.mock:
        return ServiceMockClient(encoding), "mock (no provider)"
    from design_council.agents.anthropic_client import AnthropicClient
    client = AnthropicClient(requested_model=settings.requested_model)
    created = str(client._client.models.retrieve(settings.requested_model).created_at)
    return client, created


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * PRICE_INPUT_PER_M / 1e6 + output_tokens * PRICE_OUTPUT_PER_M / 1e6


def read_calls(run_dir: Path) -> list[dict]:
    path = run_dir / "calls.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def productivity(encoding: WorkflowEncoding, tss: dict, profile: str) -> dict:
    """PI for one run under docs/PRODUCTIVITY_METHOD.md: same distributions, draws and seed.

    Only parameter uncertainty is sampled (a live run is a single design). If the design
    eliminates a step, the method gives no factor (choice C1), so no figure is reported.
    """
    p = productivity_model
    enc = encoding.model_dump(mode="json")
    out = {"exploratory": True, "profile": profile, "draws": p.DRAWS, "seed": p.SEED,
           "method": "docs/PRODUCTIVITY_METHOD.md"}
    e_lo, e_hi = p.E_RANGE[profile]
    for variant in (PRIMARY, AGENTIC_ONLY):
        try:
            carry = p.carried(enc, tss, variant)
        except ValueError as error:
            out[variant] = {"computed": False, "reason": str(error)}
            continue
        rng = random.Random(p.SEED)
        values = []
        for _ in range(p.DRAWS):
            rh = rng.triangular(p.RH[0], p.RH[2], p.RH[1])
            e = rng.uniform(e_lo, e_hi)
            k = rng.uniform(*p.K)
            m = rng.uniform(*p.M)
            t = p.dirichlet_ones(rng, len(enc["steps"]))
            values.append(p.pi(carry, t, rh, e, k, m))
        worst = 1.0 - max(p.r_value(c, p.RH[2], e_hi, p.K[1]) * p.m_value(d, 1.0) for c, d in carry)
        out[variant] = {"computed": True, "median": median(values), "p05": p.quantile(values, 0.05),
                        "p95": p.quantile(values, 0.95), "worst_case": worst}
    return out


def condition_result(condition: str, run_dir: Path, encoding: WorkflowEncoding, profile: str) -> dict:
    from design_council.schemas import TargetStateSpec
    tss = json.loads((run_dir / "tss.json").read_text())
    gate = json.loads((run_dir / "gate_result.json").read_text())
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    depth = measure_depth(encoding, TargetStateSpec.model_validate(tss))
    calls = read_calls(run_dir)
    work = [c for c in calls if c["agent_role"] != PROBE_ROLE]
    tokens = {"input": sum(c["input_tokens"] for c in work),
              "output": sum(c["output_tokens"] or 0 for c in work),
              "thinking": sum(c.get("thinking_tokens") or 0 for c in work),
              "calls": len(work),
              "failed_attempts": sum(1 for c in work if c.get("attempt_status", "ok") != "ok")}
    start = datetime.fromisoformat(manifest["created_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(calls[-1]["timestamp_utc"].replace("Z", "+00:00"))
    transcript = []
    for c in work:
        if c.get("attempt_status", "ok") != "ok":
            continue
        phase, role = phase_of(c["agent_role"])
        transcript.append({"phase": phase, "role": role, "agent_role": c["agent_role"], "text": c["raw_completion"]})
    structural = {"original": productivity_model.structural([s.model_dump() for s in encoding.steps], PRIMARY),
                  "target": productivity_model.structural(tss["steps"], PRIMARY)}
    return {
        "condition": condition, "run_id": run_dir.name, "run_dir": str(run_dir),
        "tss": tss, "gate": gate, "depth": depth.model_dump(mode="json"),
        "productivity": productivity(encoding, tss, profile), "structural": structural,
        "transcript": transcript, "tokens": tokens,
        "cost_usd": cost_usd(tokens["input"], tokens["output"]),
        "runtime_min": (end - start).total_seconds() / 60,
    }


def run_job(job_id: str, settings: Settings, store: Store, client_factory=make_client) -> None:
    job = store.get(job_id)
    encoding = WorkflowEncoding.model_validate_json(job["encoding"])
    store.update(job_id, status="running")
    store.emit(job_id, "job_started", conditions=job["conditions"], workflow_id=encoding.workflow_id)
    kb = load_kb()
    run_ids, total = {}, 0.0
    try:
        for condition in job["conditions"]:
            client, model_created_at = client_factory(settings, encoding)
            resolution = resolve_model(client, settings.requested_model)
            sampling = client.sampling_params() if hasattr(client, "sampling_params") else {}
            config = {
                "source": SOURCE_LABEL, "live_job_id": job_id, "profile": job["profile"],
                "sampling_params": sampling,
                "prompt_fragment_hashes": prompt_fragment_hashes(),
                "disposition_convention_version": DISPOSITION_CONVENTION_VERSION,
            }
            if condition == "council":
                config["protocol"] = "council: 7 round1 + 7 round2 + 1 synthesis"
                config["charter_hashes"] = charter_hashes()
            logger = LiveRunLogger(
                settings.runs_live_root, store=store, job_id=job_id, condition=condition,
                workflow_id=encoding.workflow_id, requested_model=settings.requested_model,
                resolution=resolution, model_created_at=model_created_at, git_commit=git_commit(),
                encoding_sha256=sha256_text(encoding.model_dump_json()), kb_sha256=sha256_file(KB_PATH),
                config=config, allow_dirty=True,
            )
            run_ids[condition] = logger.run_id
            store.update(job_id, run_ids=run_ids)
            store.emit(job_id, "condition_started", condition=condition, run_id=logger.run_id)
            if condition == "council":
                run_council(encoding, kb, client, logger, sampling or None)
            else:
                run_baseline(encoding, kb, client, logger, sampling or None)
            result = condition_result(condition, logger.run_dir, encoding, job["profile"])
            g = result["gate"]
            passed = sum(1 for r in g["results"] if r["passed"])
            store.emit(job_id, "gate", condition=condition, conformance_score=g["conformance_score"],
                       passed=passed, total=len(g["results"]))
            store.emit(job_id, "measures", condition=condition, depth=result["depth"]["depth_score"],
                       pi_median=(result["productivity"][PRIMARY] or {}).get("median"))
            (store.jobs_root / job_id / f"result_{condition}.json").write_text(json.dumps(result, indent=2))
            total += result["cost_usd"]
            store.emit(job_id, "condition_finished", condition=condition, cost_usd=result["cost_usd"],
                       runtime_min=result["runtime_min"])
        store.update(job_id, status="succeeded", cost_usd=total, finished_utc=_now())
        store.emit(job_id, "job_finished", status="succeeded", cost_usd=total)
    except Exception as error:  # the job must end in a recorded state whatever went wrong
        spent = total + sum(_logged_cost(settings.runs_live_root / rid) for c, rid in run_ids.items()
                            if not (store.jobs_root / job_id / f"result_{c}.json").exists())
        store.update(job_id, status="failed", error=f"{type(error).__name__}: {error}", cost_usd=spent,
                     finished_utc=_now())
        store.emit(job_id, "job_failed", error=f"{type(error).__name__}: {error}", cost_usd=spent)


def _logged_cost(run_dir: Path) -> float:
    work = [c for c in read_calls(run_dir) if c["agent_role"] != PROBE_ROLE]
    return cost_usd(sum(c["input_tokens"] for c in work), sum(c["output_tokens"] or 0 for c in work))


def _now() -> str:
    from design_council.run_logging import utc_now_iso
    return utc_now_iso()
