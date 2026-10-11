"""Export everything the results app needs into export/. Read-only on runs; no model calls.

    python scripts/export_app_data.py [--out export]

export/ is the single source of truth for the Streamlit app (app.py) and any later
front end: nothing in the app reads runs/, docs/ or data/ directly. Output is
deterministic. Files are written with sorted keys and fixed float rounding, and
the content depends only on the run logs, the committed encodings and coding
data, and the commit, so re-running at the same commit gives byte-identical
files. The layout is documented in export/SCHEMA.md, written by this script.

Every figure is computed by the same code that produced the committed results
documents, imported here rather than re-implemented:
    classification   design_council.measures.actor_class.decided_class
    depth            design_council.measures.depth.measure_depth
    consistency      design_council.measures.consistency
    efficiency       scripts/efficiency_heldout.run_figures
    productivity     scripts/productivity_heldout.compute
    controls         scripts/control_coding_final.build
The held-out tables (X.1 to X.5) follow scripts/analyse_heldout.py and are
checked against docs/RESULTS_HELDOUT_tables.md by tests/test_export.py.
"""

import argparse
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
from argparse import Namespace
from collections import Counter
from datetime import datetime
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from design_council.measures.actor_class import AGENTIC_ONLY, PRIMARY, decided_class  # noqa: E402
from design_council.measures.consistency import pairwise_agreements  # noqa: E402
from design_council.measures.depth import measure_depth  # noqa: E402
from design_council.measures.packs import encoding_path_for, load_v1_runs  # noqa: E402
from design_council.schemas import Disposition, TargetStateSpec, WorkflowEncoding  # noqa: E402

RUNS_ROOT = REPO_ROOT / "runs"
HELDOUT_SET = "heldout-v1"
HELDOUT = ["P2P-TWM-01", "P2P-PRE-01", "P2P-EXR-01", "R2R-ACR-01", "R2R-FSP-01", "FPA-VAR-01", "FPA-ABB-01"]
DEV = ["P2P-VIP-01", "R2R-PC-01", "FPA-RF-01"]
TRANSACTIONAL = {"P2P-TWM-01", "P2P-PRE-01", "P2P-EXR-01", "R2R-ACR-01"}
AREA = {"P2P": "Procure-to-pay", "R2R": "Record-to-report", "FPA": "Financial planning and analysis"}
CONDITIONS = ["council", "baseline"]
DISPOSITIONS = ["eliminated", "absorbed", "merged", "restructured", "retained"]
PROBE = "model_resolution_probe"
EXCERPT = 600


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def r6(x):
    return None if x is None else round(float(x), 6)


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()


# --- runs ------------------------------------------------------------------------


def phase_of(role: str) -> tuple[str, str]:
    if role.startswith("round1_"):
        return "round 1", role[len("round1_"):]
    if role.startswith("round2_"):
        return "round 2", role[len("round2_"):]
    if role == "synthesis":
        return "synthesis", "synthesis"
    return "single agent", role


def export_run(run_dir: Path, set_name: str, rep: int | None, encoding: WorkflowEncoding, eff) -> dict:
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    tss = TargetStateSpec.model_validate_json((run_dir / "tss.json").read_text())
    gate = json.loads((run_dir / "gate_result.json").read_text())
    depth = measure_depth(encoding, tss)
    records = [json.loads(l) for l in (run_dir / "calls.jsonl").read_text().splitlines() if l.strip()]
    fig = eff.run_figures(run_dir)
    transcript = []
    for r in records:
        if r["agent_role"] == PROBE or r.get("attempt_status", "ok") != "ok":
            continue
        phase, role = phase_of(r["agent_role"])
        text = r["raw_completion"] or ""
        transcript.append({"phase": phase, "role": role, "excerpt": text[:EXCERPT],
                           "truncated": len(text) > EXCERPT, "chars": len(text)})
    steps = []
    for s in tss.steps:
        steps.append({"step_id": s.step_id, "name": s.name, "description": s.description, "actor": s.actor,
                      "inputs": s.inputs, "outputs": s.outputs,
                      "class_primary": decided_class(s.actor, s.description, PRIMARY),
                      "class_agentic_only": decided_class(s.actor, s.description, AGENTIC_ONLY)})
    passed = sum(1 for g in gate["results"] if g["passed"])
    return {
        "run_id": manifest["run_id"], "set": set_name, "workflow_id": manifest["workflow_id"],
        "condition": manifest["condition"], "rep": rep, "created_utc": manifest["created_utc"],
        "git_commit": manifest["git_commit"], "resolved_model": manifest["resolved_model"],
        "disposition_convention_version": manifest.get("config", {}).get("disposition_convention_version", "v1 (pre-01034ae)"),
        "steps": steps,
        "disposition_mapping": [d.model_dump(mode="json") for d in tss.disposition_mapping],
        "gate": {"conformance_score": r6(gate["conformance_score"]), "passed": passed, "total": len(gate["results"]),
                 "results": [{"requirement_id": g["requirement_id"], "passed": g["passed"],
                              "vacuous": g.get("vacuous", False), "reason": g["reason"]} for g in gate["results"]]},
        "depth": {"score": r6(depth.depth_score), "counts": depth.profile.counts,
                  "total_baseline_steps": depth.profile.total_baseline_steps},
        "consistency_inputs": {s: tss.disposition_for(s).value for s in encoding.step_ids()},
        "efficiency": {"input_tokens": fig["input"], "output_tokens": fig["output"], "calls": fig["calls"],
                       "failed_attempts": fig["failed_attempts"], "runtime_min": r6(fig["minutes"]),
                       "cost_usd": r6(eff.cost(fig["input"], fig["output"]))},
        "transcript": transcript,
    }


# --- held-out tables ----------------------------------------------------------------


def heldout_tables(runs: dict, events: list) -> dict:
    """X.1 to X.5 and fill-ins, following scripts/analyse_heldout.py."""
    decisions = {(e["workflow_id"], e["condition"]): e["decision"] for e in events if e["event"] == "stop_rule"}
    cell = {(wf, c): sorted([r for r in runs.values() if r["workflow_id"] == wf and r["condition"] == c],
                            key=lambda r: r["rep"]) for wf in HELDOUT for c in CONDITIONS}

    def frac(r):
        d = r["depth"]
        return Fraction(d["total_baseline_steps"] - d["counts"]["retained"], d["total_baseline_steps"])

    def fmean(xs):
        return sum(xs, Fraction(0)) / len(xs)

    x1 = [{"workflow_id": wf, **{f"{c}_n": len(cell[(wf, c)]) for c in CONDITIONS},
           **{f"{c}_stopped_at_4": decisions.get((wf, c)) == "complete_at_n4" for c in CONDITIONS}} for wf in HELDOUT]
    x2 = [{"run_id": r["run_id"], "condition": r["condition"], "workflow_id": r["workflow_id"],
           "score": r["gate"]["conformance_score"], "passed": r["gate"]["passed"], "total": r["gate"]["total"],
           "failed": [g["requirement_id"] for g in r["gate"]["results"] if not g["passed"]]}
          for wf in HELDOUT for c in CONDITIONS for r in cell[(wf, c)] if r["gate"]["passed"] < r["gate"]["total"]]
    x3 = []
    for wf in HELDOUT:
        cd, bd = [frac(r) for r in cell[(wf, "council")]], [frac(r) for r in cell[(wf, "baseline")]]
        gap = fmean(cd) - fmean(bd)
        x3.append({"workflow_id": wf, "profile": "transactional" if wf in TRANSACTIONAL else "judgment-dense",
                   "council_mean": r6(fmean(cd)), "council_min": r6(min(cd)), "council_max": r6(max(cd)),
                   "baseline_mean": r6(fmean(bd)), "baseline_min": r6(min(bd)), "baseline_max": r6(max(bd)),
                   "gap": r6(gap), "gap_exact": f"{gap.numerator}/{gap.denominator}",
                   "meets_sesoi": gap >= Fraction(1, 5)})
    x4 = {c: {d: sum(r["depth"]["counts"].get(d, 0) for wf in HELDOUT for r in cell[(wf, c)]) for d in DISPOSITIONS}
          for c in CONDITIONS}
    x5, stab = [], 0
    for wf in HELDOUT:
        for c in CONDITIONS:
            ds = [frac(r) for r in cell[(wf, c)]]
            if len(ds) == 4:
                s = "Yes (stopped at 4)" if ds[3] == ds[2] else "No"
            else:
                s = "Yes (run 5 = run 4)" if ds[4] == ds[3] else "No (run 5 ≠ run 4)"
            stab += s.startswith("Yes")
            specs = [r["consistency_inputs"] for r in cell[(wf, c)]]
            pairs = [sum(a[k] == b[k] for k in a) / len(a) for a, b in combinations(specs, 2)]
            x5.append({"workflow_id": wf, "condition": c, "after_3": r6(fmean(ds[:3])), "after_4": r6(fmean(ds[:4])),
                       "after_5": r6(fmean(ds[:5])) if len(ds) == 5 else None, "stabilised": s,
                       "consistency": r6(mean(pairs)), "consistency_min": r6(min(pairs)),
                       "consistency_max": r6(max(pairs))})
    meeting = sum(r["meets_sesoi"] for r in x3)
    consistency = {c: r6(mean(r["consistency"] for r in x5 if r["condition"] == c)) for c in CONDITIONS}
    return {
        "x1_run_completion": x1, "x2_conformance_failures": x2, "x3_depth": x3, "x4_dispositions": x4,
        "x5_stabilisation": x5,
        "fill_ins": {
            "total_runs": sum(len(v) for v in cell.values()),
            "cells_stopped_at_4": sum(1 for d in decisions.values() if d == "complete_at_n4"),
            "cells_with_fifth_run": sum(1 for v in cell.values() if len(v) == 5),
            "runs_below_1": len(x2), "runs_below_1_council": sum(1 for r in x2 if r["condition"] == "council"),
            "runs_below_1_baseline": sum(1 for r in x2 if r["condition"] == "baseline"),
            "h1_branch": "B" if x2 else "A",
            "h2_workflows_meeting_sesoi": meeting, "h2_threshold": 4, "h2_supported": meeting >= 4,
            "h3_stabilised_cells": stab, "h3_threshold": 8, "h3_supported": stab >= 8,
            "consistency_by_condition": consistency,
        },
    }


# --- main --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "export")
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    args = parser.parse_args()
    out = args.out
    if out.exists():
        shutil.rmtree(out)

    eff = load_script("efficiency_heldout")
    prod = load_script("productivity_heldout")
    coding = load_script("control_coding_final")

    events = [json.loads(l) for l in (args.runs_root / f"_set-{HELDOUT_SET}.ledger.jsonl").read_text().splitlines()]
    started = next(e for e in events if e["event"] == "set_started")
    heldout_paths = started["workflows"]

    # Workflows.
    encodings, workflow_index = {}, []
    for wf in HELDOUT + DEV:
        path = REPO_ROOT / heldout_paths[wf] if wf in HELDOUT else encoding_path_for(wf)
        enc = WorkflowEncoding.model_validate(json.loads(path.read_text()))
        encodings[wf] = enc
        split = "heldout" if wf in HELDOUT else "dev"
        profile = ("transactional" if wf in TRANSACTIONAL else "judgment-dense") if split == "heldout" else None
        write(out / "workflows" / f"{wf}.json", {
            "workflow_id": wf, "name": enc.name, "split": split, "domain": enc.domain.value,
            "function_area": AREA[enc.domain.value], "profile": profile,
            "source": enc.source.model_dump(), "open_steps": enc.unconstrained_by_design,
            "steps": [s.model_dump() for s in enc.steps],
            "requirements": [r.model_dump() for r in enc.requirements],
        })
        workflow_index.append({"workflow_id": wf, "name": enc.name, "split": split, "profile": profile,
                               "function_area": AREA[enc.domain.value], "steps": len(enc.steps),
                               "requirements": len(enc.requirements), "open_steps": len(enc.unconstrained_by_design)})

    # Held-out runs (completed, per the ledger).
    reps = {e["run_id"]: e["rep"] for e in events if e["event"] == "finished" and e["status"] == "ok"}
    heldout_runs = {}
    for run_id, rep in sorted(reps.items()):
        wf = json.loads((args.runs_root / run_id / "run_manifest.json").read_text())["workflow_id"]
        heldout_runs[run_id] = export_run(args.runs_root / run_id, HELDOUT_SET, rep, encodings[wf], eff)
    # Dev v1 runs (the 18-run v1 grid, as selected by the review-pack code).
    dev_runs = {}
    for wf in DEV:
        for cond, summaries in load_v1_runs(wf).items():
            for i, s in enumerate(sorted(summaries, key=lambda s: s.run_id), start=1):
                dev_runs[s.run_id] = export_run(s.path, "dev-v1", i, encodings[wf], eff)
    for run_id, data in {**heldout_runs, **dev_runs}.items():
        write(out / "runs" / f"{run_id}.json", data)

    # Held-out tables.
    tables = heldout_tables(heldout_runs, events)
    write(out / "results" / "heldout_tables.json", tables)

    # Conformance failure classification (exploratory, from the committed document).
    doc = (REPO_ROOT / "docs" / "CONFORMANCE_FAILURE_CLASSIFICATION.md").read_text()
    classes = {m.group(1): m.group(3) for m in re.finditer(r"^### \d+\. (\S+): (\S+), (\w+)$", doc, re.M)}
    write(out / "results" / "conformance_failures.json", {
        "exploratory": True, "source": "docs/CONFORMANCE_FAILURE_CLASSIFICATION.md",
        "failures": [dict(f, classification=classes.get(f["run_id"])) for f in tables["x2_conformance_failures"]],
    })

    # Efficiency.
    cells = {}
    for r in heldout_runs.values():
        cells.setdefault((r["workflow_id"], r["condition"]), []).append(r["efficiency"])
    eff_rows = [{"workflow_id": wf, "condition": c, "n": len(cells[(wf, c)]),
                 **{k: r6(mean(x[k] for x in cells[(wf, c)])) for k in
                    ("input_tokens", "output_tokens", "calls", "runtime_min", "cost_usd")}}
                for wf in HELDOUT for c in CONDITIONS]
    totals = {}
    for c in CONDITIONS:
        xs = [x for (wf, cc), v in cells.items() if cc == c for x in v]
        i, o = sum(x["input_tokens"] for x in xs), sum(x["output_tokens"] for x in xs)
        totals[c] = {"runs": len(xs), "input_tokens": i, "output_tokens": o, "calls": sum(x["calls"] for x in xs),
                     "cost_usd": r6(eff.cost(i, o)), "mean_cost_usd": r6(eff.cost(i, o) / len(xs)),
                     "mean_runtime_min": r6(mean(x["runtime_min"] for x in xs))}
    write(out / "results" / "efficiency.json", {
        "descriptive": True, "prices_usd_per_million": {"input": eff.PRICE_INPUT_PER_M, "output": eff.PRICE_OUTPUT_PER_M},
        "per_cell": eff_rows, "totals": totals,
        "council_to_baseline_cost_ratio": r6(totals["council"]["cost_usd"] / totals["baseline"]["cost_usd"]),
    })

    # Productivity (exploratory).
    p_enc, p_council, p_tss, p_res = prod.compute(HELDOUT_SET, args.runs_root)
    keys = ["steps", "HUMAN", "HYBRID", "AGENT", "HITL", "handoffs", "h2h", "approvals"]
    productivity = {"exploratory": True, "seed": prod.SEED, "draws": prod.DRAWS, "bootstrap": prod.BOOTSTRAP,
                    "method": "docs/PRODUCTIVITY_METHOD.md", "decisions": "docs/PRODUCTIVITY_DECISIONS.md",
                    "variants": {}}
    for v in prod.VARIANTS:
        res = p_res[v]
        structural = []
        for wf in HELDOUT:
            o = prod.structural(p_enc[wf]["steps"], v)
            cs = [prod.structural(p_tss[r]["steps"], v) for r in p_council[wf]]
            structural.append({"workflow_id": wf, "original": o,
                               "council": {k: {"mean": r6(mean(c[k] for c in cs)), "min": min(c[k] for c in cs),
                                               "max": max(c[k] for c in cs)} for k in keys}})
        productivity["variants"][v] = {
            "per_workflow": [{"workflow_id": wf, "profile": prod.SUBGROUP[wf], "runs": len(p_council[wf]),
                              "median": r6(res["wf"][wf][0]), "p05": r6(res["wf"][wf][1]), "p95": r6(res["wf"][wf][2]),
                              "worst_case": r6(res["worst"][wf])} for wf in HELDOUT],
            "pooled": {g: {"pi": r6(p), "p05": r6(lo), "p95": r6(hi)} for g, (p, lo, hi) in res["pooled"].items()},
            "prcc": {k: r6(x) for k, x in res["prcc"].items()},
            "oat": {k: {"at_min": r6(lo), "at_max": r6(hi)} for k, (lo, hi) in res["oat"].items()},
            "structural": structural,
        }
    write(out / "results" / "productivity.json", productivity)

    # Governance controls (section 6 coding, final).
    final, _ = coding.build(Namespace(set_name=HELDOUT_SET, runs_root=args.runs_root))
    rejudge = {}
    for wf in HELDOUT:
        for c in json.loads((coding.CODING / f"rejudge_{wf}.json").read_text())["controls"]:
            rejudge[c["id"]] = c["presence"]
    controls = []
    for f in final.values():
        quote = run = None
        for cid in f["ids"]:
            for rid in f["council"]:
                p = (rejudge.get(cid) or {}).get(rid) or {}
                if f["pres"][rid] and p.get("quote"):
                    quote, run = p["quote"], rid
                    break
            if quote:
                break
        controls.append({"control_id": f["ids"][0], "merged_ids": f["ids"], "name": f["name"], "workflow_id": f["wf"],
                         "members": f["members"], "primary_role": f["primary"], "roles": f["roles"],
                         "council_present": f["c"], "council_n": f["n"], "baseline_present": f["b"],
                         "outcome": f["out"], "strict_75": f["strict"], "quote": quote, "quote_run_id": run})
    controls.sort(key=lambda c: (HELDOUT.index(c["workflow_id"]), c["control_id"]))
    passing = [c for c in controls if c["outcome"] == "PASS"]
    write(out / "results" / "governance_controls.json", {
        "rule": "pre-registration section 6 item 4: >= 60% of council runs and no baseline run",
        "role_convention": "primary = first attributed role of the lowest-numbered member candidate; any = every role named",
        "per_workflow": [{"workflow_id": wf, "final_controls": sum(1 for c in controls if c["workflow_id"] == wf),
                          "pass": sum(1 for c in passing if c["workflow_id"] == wf),
                          "strict_75": sum(1 for c in passing if c["workflow_id"] == wf and c["strict_75"])}
                         for wf in HELDOUT],
        "by_role": [{"role": role, "primary": n, "any": sum(1 for c in passing if role in c["roles"])}
                    for role, n in sorted(Counter(c["primary_role"] for c in passing).items(), key=lambda kv: (-kv[1], kv[0]))]
                   + [{"role": role, "primary": 0, "any": sum(1 for c in passing if role in c["roles"])}
                      for role in sorted({r for c in passing for r in c["roles"]} - {c["primary_role"] for c in passing})],
        "controls": controls,
    })

    # Development grid (v1).
    dev_rows = []
    for wf in DEV:
        for c in CONDITIONS:
            rs = [r for r in dev_runs.values() if r["workflow_id"] == wf and r["condition"] == c]
            specs = [TargetStateSpec.model_validate({"workflow_id": wf,
                                                     "baseline_step_ids": encodings[wf].step_ids(),
                                                     "steps": r["steps"] and [{k: s[k] for k in ("step_id", "name", "description", "actor", "inputs", "outputs")} for s in r["steps"]],
                                                     "disposition_mapping": r["disposition_mapping"]}) for r in rs]
            pairs = pairwise_agreements(specs, encodings[wf].step_ids())
            dev_rows.append({"workflow_id": wf, "condition": c, "n": len(rs), "run_ids": sorted(r["run_id"] for r in rs),
                             "depth_mean": r6(mean(r["depth"]["score"] for r in rs)),
                             "depth_min": r6(min(r["depth"]["score"] for r in rs)),
                             "depth_max": r6(max(r["depth"]["score"] for r in rs)),
                             "conformance_mean": r6(mean(r["gate"]["conformance_score"] for r in rs)),
                             "dispositions": {d: sum(r["depth"]["counts"].get(d, 0) for r in rs) for d in DISPOSITIONS},
                             "consistency": r6(mean(pairs)),
                             "mean_output_tokens": r6(mean(r["efficiency"]["output_tokens"] for r in rs))})
    write(out / "results" / "dev_grid.json", {"set": "dev-v1", "instrument": "disposition convention v1",
                                              "cells": dev_rows})

    # Findings (headline statements, built from the exported numbers).
    fi = tables["fill_ins"]
    pp = productivity["variants"][PRIMARY]["pooled"]
    pa = productivity["variants"][AGENTIC_ONLY]["pooled"]
    cls = Counter(f["classification"] for f in json.loads((out / "results" / "conformance_failures.json").read_text())["failures"])
    exact = [r["workflow_id"] for r in tables["x3_depth"] if r["gap_exact"] == "1/5"]
    top_role = governance_top = None
    gc = json.loads((out / "results" / "governance_controls.json").read_text())
    if gc["by_role"]:
        top_role, governance_top = gc["by_role"][0]["role"], gc["by_role"][0]["primary"]
    findings = [
        {"id": "H1", "status": "pre-registered", "title": "Conformance is a floor, not a discriminator",
         "text": f"{fi['runs_below_1']} of {fi['total_runs']} runs fell below 1.0 ({fi['runs_below_1_council']} council, "
                 f"{fi['runs_below_1_baseline']} baseline), so Branch {fi['h1_branch']} applies. In an exploratory "
                 f"classification, {cls.get('NAMING', 0)} of these are naming mismatches under exact matching, "
                 f"{cls.get('SUBSTANTIVE', 0)} substantive and {cls.get('UNCLEAR', 0)} unclear."},
        {"id": "H2", "status": "pre-registered", "title": "Agentic AI deliberation transforms more deeply",
         "text": f"Council mean depth exceeded the single agentic AI baseline by at least the 0.2 SESOI on "
                 f"{fi['h2_workflows_meeting_sesoi']} of 7 workflows (threshold {fi['h2_threshold']}), so H2 is "
                 f"{'supported' if fi['h2_supported'] else 'not supported'}. {len(exact)} of those gaps are exactly 0.2 "
                 f"({', '.join(exact)}), decided by exact-fraction comparison."},
        {"id": "H3", "status": "pre-registered", "title": "Depth does not stabilise by run 4 or 5",
         "text": f"{fi['h3_stabilised_cells']} of 14 cells stabilised against a threshold of {fi['h3_threshold']}, so the "
                 f"stabilisation claim is {'supported' if fi['h3_supported'] else 'not supported'}. The stopping rule "
                 f"is reported as an efficiency rule, not as evidence of convergence."},
        {"id": "ELIM", "status": "pre-registered", "title": "No step is eliminated; the council restructures",
         "text": f"Neither condition eliminated any step. Absorbed dispositions: council {tables['x4_dispositions']['council']['absorbed']}, "
                 f"baseline {tables['x4_dispositions']['baseline']['absorbed']}. The council restructures "
                 f"({tables['x4_dispositions']['council']['restructured']} vs {tables['x4_dispositions']['baseline']['restructured']}) "
                 f"rather than removing steps."},
        {"id": "GOV", "status": "pre-registered coding", "title": "Deliberation adds governance controls",
         "text": f"{len(passing)} council-attributed controls (present in ≥ 60% of council runs and in no baseline run). "
                 f"The {top_role.replace('_', ' ') if top_role else '–'} role introduced the most "
                 f"({governance_top} as primary role)."},
        {"id": "PROD", "status": "exploratory", "title": "Productivity potential is concentrated in transactional work",
         "text": f"Pooled structural productivity potential (PI) is {pp['all']['pi']:.3f} under the primary classification "
                 f"and {pa['all']['pi']:.3f} when only agentic AI (not deterministic automation) counts. Transactional "
                 f"workflows {pp['transactional']['pi']:.3f}, judgment-dense {pp['judgment-dense']['pi']:.3f}. These are "
                 f"estimates under stated assumptions, not measured outcomes."},
    ]

    commit = git("rev-parse", "HEAD")
    index = {
        "export_commit": commit,
        "prereg_tag": started.get("prereg_tag"),
        "research_question": ("Does a multi-agent Design Council of agentic AI roles produce deeper, standards-"
                              "conformant redesigns of finance workflows than a single agentic AI baseline, and "
                              "what governance does deliberation add?"),
        "sets": {
            HELDOUT_SET: {"label": "Held-out (pre-registered)", "commit": started["git_commit"],
                          "requested_model": started["requested_model"], "workflows": HELDOUT,
                          "runs": sorted(heldout_runs),
                          "cells": [{"workflow_id": wf, "condition": c,
                                     "run_ids": [r["run_id"] for r in sorted(heldout_runs.values(), key=lambda r: r["rep"])
                                                 if r["workflow_id"] == wf and r["condition"] == c],
                                     "stop_decision": next((e["decision"] for e in events if e["event"] == "stop_rule"
                                                            and e["workflow_id"] == wf and e["condition"] == c), None)}
                                    for wf in HELDOUT for c in CONDITIONS]},
            "dev-v1": {"label": "Development grid (v1)", "workflows": DEV, "runs": sorted(dev_runs)},
        },
        "workflows": workflow_index,
        "findings": findings,
        "headline": {"heldout_runs": len(heldout_runs), "council_attributed_controls": len(passing),
                     "h2": f"{fi['h2_workflows_meeting_sesoi']} of 7", "h3": f"{fi['h3_stabilised_cells']} of 14",
                     "runs_below_1": fi["runs_below_1"], "pooled_pi_primary": pp["all"]["pi"],
                     "council_to_baseline_cost_ratio": r6(totals["council"]["cost_usd"] / totals["baseline"]["cost_usd"])},
    }
    write(out / "index.json", index)
    (out / "SCHEMA.md").write_text(SCHEMA)
    print(f"exported {len(heldout_runs)} held-out runs, {len(dev_runs)} dev runs, {len(controls)} controls "
          f"({len(passing)} PASS) to {out}")
    return 0


SCHEMA = """# export/ schema

Written by `scripts/export_app_data.py`. Do not edit by hand. It is the single source of
truth for `app.py` and any later front end. Deterministic: the same commit gives the same
bytes. JSON files use sorted keys. Floats are rounded to 6 decimals.

## index.json
- `export_commit`: git commit the export was made from. `prereg_tag`: freeze tag of the held-out set.
- `research_question`: one sentence.
- `sets.heldout-v1`: `label`, `commit` (pinned run commit), `requested_model`, `workflows` (7 ids),
  `runs` (68 run ids), `cells[]` = {`workflow_id`, `condition`, `run_ids` in rep order, `stop_decision`
  (`complete_at_n4` | `run_5`)}.
- `sets.dev-v1`: `label`, `workflows` (3 ids), `runs` (18 v1 run ids).
- `workflows[]`: {`workflow_id`, `name`, `split` (heldout | dev), `profile` (transactional |
  judgment-dense | null), `function_area`, `steps`, `requirements`, `open_steps`} (the last three are counts).
- `findings[]`: {`id`, `status` (pre-registered | pre-registered coding | exploratory), `title`, `text`}.
- `headline`: headline numbers used by the overview page.

## workflows/<workflow_id>.json
The baseline encoding: `name`, `split`, `domain`, `function_area`, `profile`, `source`,
`open_steps` (unconstrained_by_design), `steps[]` (step_id, name, description, actor, inputs,
outputs), `requirements[]` (requirement_id, statement, rule_type, params).

## runs/<run_id>.json
- `run_id`, `set` (heldout-v1 | dev-v1), `workflow_id`, `condition` (council | baseline), `rep`
  (held-out: ledger repetition; dev: order by run id), `created_utc`, `git_commit`,
  `resolved_model`, `disposition_convention_version`.
- `steps[]`: target-state steps with `class_primary` and `class_agentic_only` (HUMAN | HYBRID |
  AGENT, `design_council/measures/actor_class.decided_class`).
- `disposition_mapping[]`: baseline_step_id, disposition, target_step_ids, rationale.
- `gate`: `conformance_score`, `passed`, `total`, `results[]` (requirement_id, passed, vacuous, reason).
- `depth`: `score` (pre-registered scalar), `counts` per disposition, `total_baseline_steps`.
- `consistency_inputs`: baseline step id → disposition (pairwise agreement is computed from these).
- `efficiency`: input/output tokens, calls (probe excluded, failed attempts included),
  `failed_attempts`, `runtime_min`, `cost_usd` ($2/M input, $10/M output).
- `transcript[]`: {`phase` (round 1 | round 2 | synthesis | single agent), `role`, `excerpt`
  (first 600 characters), `truncated`, `chars`}.

## results/heldout_tables.json
`x1_run_completion`, `x2_conformance_failures`, `x3_depth` (with `gap_exact` as a fraction and
`meets_sesoi` decided exactly), `x4_dispositions`, `x5_stabilisation` (with per-cell consistency),
`fill_ins` (H1 branch, H2 and H3 counts and verdicts, consistency by condition).

## results/conformance_failures.json
Exploratory. X.2 rows plus `classification` (NAMING | SUBSTANTIVE | UNCLEAR) from
`docs/CONFORMANCE_FAILURE_CLASSIFICATION.md`.

## results/efficiency.json
Descriptive. `per_cell` means (tokens, calls, runtime, cost), `totals` per condition,
`council_to_baseline_cost_ratio`.

## results/productivity.json
Exploratory. `variants.primary` and `variants.agentic-only`, each with `per_workflow` (median,
p05, p95, worst_case PI), `pooled` (all | transactional | judgment-dense: pi, p05, p95), `prcc`,
`oat`, and `structural` (original counts vs council mean/min/max for steps, HUMAN, HYBRID,
AGENT, HITL, handoffs, h2h, approvals). `seed`, `draws` and `bootstrap` are recorded.

## results/governance_controls.json
Section 6 coding (final). `per_workflow` (final_controls, pass, strict_75), `by_role` (primary,
any), and `controls[]` = {control_id, merged_ids, name, workflow_id, members, primary_role, roles,
council_present, council_n, baseline_present, outcome, strict_75, quote, quote_run_id}.

## results/dev_grid.json
v1 development grid per workflow x condition: n, run_ids, depth mean/min/max, conformance mean,
disposition counts, consistency, mean output tokens.
"""


if __name__ == "__main__":
    sys.exit(main())
