"""Check the model-written disposition labels against the structure of the TSS.

Supervisor request (held-out draft feedback, point 1): the labels 'restructured' and
'retained' are written by the model under test and nothing checks them. This script
reads every successful held-out run and tests each label against observable change
between the baseline step (from the frozen encoding) and the target step(s) the
mapping traces it to. No model call is made.

A 'restructured' label is VERIFIED if at least one of these holds:
    actor     the target step's actor differs from the baseline step's actor
    inputs    the set of inputs differs (case- and punctuation-insensitive)
    position  the step was split (>1 target), merged (shares a target with another
              baseline step) or reordered relative to the other traced baseline steps
Otherwise it is UNVERIFIED: the only change is in the description or outputs.
'outputs' is reported separately as a weaker signal, not counted for verification.

A 'retained' label is CONSISTENT if none of actor, inputs or position changed.

Outputs: export/results/depth_verification.json, docs/DEPTH_VERIFICATION.md
"""
import json, re, sys, statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "runs" / "_set-heldout-v1.ledger.jsonl"

def norm(x): return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()
def nset(xs): return {norm(x) for x in xs}

events = [json.loads(l) for l in LEDGER.read_text().splitlines()]
wf_files = next(e for e in events if e["event"] == "set_started")["workflows"]
encodings = {wf: json.loads((ROOT / p).read_text()) for wf, p in wf_files.items()}
ok_runs = [e for e in events if e["event"] == "finished" and e["status"] == "ok"]
failed = [e for e in events if e["event"] == "finished" and e["status"] != "ok"]

rows = []
for e in ok_runs:
    wf, cond, rid = e["workflow_id"], e["condition"], e["run_id"]
    enc = encodings[wf]; tss = json.loads((ROOT / "runs" / rid / "tss.json").read_text())
    base = {s["step_id"]: (i, s) for i, s in enumerate(enc["steps"])}
    tidx = {s["step_id"]: (i, s) for i, s in enumerate(tss["steps"])}
    # how many baseline steps map to each target step (for merge detection)
    share = defaultdict(int)
    for m in tss["disposition_mapping"]:
        for t in m["target_step_ids"]: share[t] += 1
    # order check: first target index of each traced baseline step, in baseline order
    first_t = {m["baseline_step_id"]: min((tidx[t][0] for t in m["target_step_ids"]), default=None)
               for m in tss["disposition_mapping"]}
    for m in tss["disposition_mapping"]:
        bid, disp, targets = m["baseline_step_id"], m["disposition"], m["target_step_ids"]
        bi, bs = base[bid]
        if not targets:
            rows.append(dict(run_id=rid, wf=wf, cond=cond, step=bid, label=disp, actor=None, inputs=None,
                             position=None, outputs=None, verified=disp == "eliminated")); continue
        ts = [tidx[t][1] for t in targets]
        actor = any(norm(t["actor"]) != norm(bs["actor"]) for t in ts)
        inputs = set().union(*(nset(t["inputs"]) for t in ts)) != nset(bs["inputs"])
        outputs = set().union(*(nset(t["outputs"]) for t in ts)) != nset(bs["outputs"])
        split = len(targets) > 1
        merged = any(share[t] > 1 for t in targets)
        # reordered: another traced baseline step that comes before this one in the baseline
        # has its first target after this one's (or vice versa)
        mine = first_t[bid]
        reordered = any((base[o][0] < bi and ft is not None and mine is not None and ft > mine) or
                        (base[o][0] > bi and ft is not None and mine is not None and ft < mine)
                        for o, ft in first_t.items() if o != bid)
        position = split or merged or reordered
        changed = actor or inputs or position
        verified = {"restructured": changed, "retained": not changed,
                    "merged": merged or split, "absorbed": merged}.get(disp, None)
        rows.append(dict(run_id=rid, wf=wf, cond=cond, step=bid, label=disp, actor=actor, inputs=inputs,
                         position=position, outputs=outputs, verified=verified,
                         only_outputs=(disp == "restructured" and not changed and outputs)))

def summarise(sel):
    out = {}
    for disp in ["restructured", "retained", "merged", "absorbed", "eliminated"]:
        xs = [r for r in sel if r["label"] == disp]
        if not xs: out[disp] = {"n": 0}; continue
        out[disp] = {"n": len(xs), "verified": sum(1 for r in xs if r["verified"]),
                     "rate": round(sum(1 for r in xs if r["verified"]) / len(xs), 3)}
        if disp == "restructured":
            out[disp].update(by_actor=sum(r["actor"] for r in xs), by_inputs=sum(r["inputs"] for r in xs),
                             by_position=sum(r["position"] for r in xs),
                             unverified_outputs_only=sum(1 for r in xs if r.get("only_outputs")),
                             unverified_description_only=sum(1 for r in xs if not r["verified"] and not r.get("only_outputs")))
        if disp == "retained":
            out[disp].update(inconsistent_actor=sum(1 for r in xs if r["actor"]),
                             inconsistent_inputs=sum(1 for r in xs if r["inputs"]),
                             inconsistent_position=sum(1 for r in xs if r["position"]))
    return out

# depth as reported vs depth counting only verified non-retained labels
def depth(rs, verified_only=False):
    n = len(rs)
    if verified_only:
        touched = sum(1 for r in rs if r["label"] != "retained" and r["verified"])
    else:
        touched = sum(1 for r in rs if r["label"] != "retained")
    return touched / n

by_run = defaultdict(list)
for r in rows: by_run[(r["wf"], r["cond"], r["run_id"])].append(r)
cells = defaultdict(lambda: {"reported": [], "verified": []})
for (wf, cond, rid), rs in by_run.items():
    cells[(wf, cond)]["reported"].append(depth(rs)); cells[(wf, cond)]["verified"].append(depth(rs, True))

report = {"runs_ok": len(ok_runs), "runs_failed_excluded": len(failed),
          "failed_run_ids": [e["run_id"] for e in failed],
          "labels_total": len(rows),
          "by_condition": {c: summarise([r for r in rows if r["cond"] == c]) for c in ["council", "baseline"]},
          "overall": summarise(rows),
          "cells": {f"{wf}|{cond}": {"n": len(v["reported"]),
                                     "depth_reported_mean": round(statistics.mean(v["reported"]), 3),
                                     "depth_verified_mean": round(statistics.mean(v["verified"]), 3)}
                    for (wf, cond), v in sorted(cells.items())}}
(ROOT / "export/results/depth_verification.json").write_text(json.dumps(report, indent=1))

L = ["# Disposition label verification (held-out set)", "",
     f"Successful runs: {len(ok_runs)}; failed attempts excluded from every depth figure: {len(failed)}. "
     f"Baseline-step labels checked: {len(rows)}. Generated by scripts/verify_dispositions.py; no model calls.", "",
     "## Restructured labels", "", "| Condition | n | Verified | Rate | by actor | by inputs | by position | Unverified: outputs only | Unverified: description only |",
     "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
for c in ["council", "baseline"]:
    s = report["by_condition"][c]["restructured"]
    L.append(f"| {c} | {s['n']} | {s['verified']} | {s['rate']:.3f} | {s['by_actor']} | {s['by_inputs']} | {s['by_position']} | {s['unverified_outputs_only']} | {s['unverified_description_only']} |")
L += ["", "## Retained labels (consistent = no change in actor, inputs or position)", "",
      "| Condition | n | Consistent | Rate | actor changed | inputs changed | position changed |", "|---|---:|---:|---:|---:|---:|---:|"]
for c in ["council", "baseline"]:
    s = report["by_condition"][c]["retained"]
    L.append(f"| {c} | {s['n']} | {s['verified']} | {s['rate']:.3f} | {s['inconsistent_actor']} | {s['inconsistent_inputs']} | {s['inconsistent_position']} |")
L += ["", "## Other labels", ""]
for c in ["council", "baseline"]:
    for d in ["merged", "absorbed", "eliminated"]:
        s = report["by_condition"][c][d]
        L.append(f"- {c} {d}: n={s['n']}" + (f", verified {s['verified']}" if s['n'] else ""))
L += ["", "## Depth per cell: as reported vs counting only verified non-retained labels", "",
      "| Workflow | Condition | n | Depth (reported) | Depth (verified) |", "|---|---|---:|---:|---:|"]
for k, v in report["cells"].items():
    wf, cond = k.split("|")
    L.append(f"| {wf} | {cond} | {v['n']} | {v['depth_reported_mean']:.3f} | {v['depth_verified_mean']:.3f} |")
(ROOT / "docs/DEPTH_VERIFICATION.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
