"""Bootstrap the H2 decision rule over the held-out runs (supervisor feedback point 3).

Rule (PREREGISTRATION_HELDOUT.md): H2 supported if mean council depth exceeds mean
baseline depth by >= 0.2 (SESOI) on at least 4 of the 7 held-out workflows.

Within each cell the successful runs are resampled with replacement (same n as the
cell), cell means are recomputed, and the rule is re-applied. 10,000 replicates,
fixed seed. Reported for depth as recorded and, as a sensitivity check, for the
verified depth of scripts/verify_dispositions.py. Also: leave-one-run-out, which
shows whether any single run decides the outcome.

Outputs export/results/bootstrap_h2.json and docs/BOOTSTRAP_H2.md. No model calls.
"""
import json, random, statistics, itertools
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESOI, NEED, B, SEED = 0.2, 4, 10_000, 20261025
def ge(gap): return round(gap, 9) >= SESOI   # gaps are ratios of small integers; avoid float error at exactly 0.200
events = [json.loads(l) for l in (ROOT / "runs/_set-heldout-v1.ledger.jsonl").read_text().splitlines()]
wf_files = next(e for e in events if e["event"] == "set_started")["workflows"]
enc = {wf: json.loads((ROOT / p).read_text()) for wf, p in wf_files.items()}
ok = [e for e in events if e["event"] == "finished" and e["status"] == "ok"]

def depth_values(verified):
    cells = defaultdict(list)
    for e in ok:
        tss = json.loads((ROOT / "runs" / e["run_id"] / "tss.json").read_text())
        m = tss["disposition_mapping"]
        if not verified:
            d = sum(1 for x in m if x["disposition"] != "retained") / len(m)
        else:
            d = verified_depth(e["workflow_id"], tss)
        cells[(e["workflow_id"], e["condition"])].append(d)
    return cells

import re
def norm(x): return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()
def verified_depth(wf, tss):
    base = {s["step_id"]: (i, s) for i, s in enumerate(enc[wf]["steps"])}
    tidx = {s["step_id"]: (i, s) for i, s in enumerate(tss["steps"])}
    share = defaultdict(int)
    for m in tss["disposition_mapping"]:
        for t in m["target_step_ids"]: share[t] += 1
    first = {m["baseline_step_id"]: min((tidx[t][0] for t in m["target_step_ids"]), default=None) for m in tss["disposition_mapping"]}
    touched = 0
    for m in tss["disposition_mapping"]:
        bid, disp, targets = m["baseline_step_id"], m["disposition"], m["target_step_ids"]
        if disp == "retained": continue
        if not targets: touched += 1; continue
        bi, bs = base[bid]; ts = [tidx[t][1] for t in targets]
        actor = any(norm(t["actor"]) != norm(bs["actor"]) for t in ts)
        inputs = set().union(*({norm(x) for x in t["inputs"]} for t in ts)) != {norm(x) for x in bs["inputs"]}
        merged = any(share[t] > 1 for t in targets); split = len(targets) > 1
        mine = first[bid]
        reordered = any((base[o][0] < bi and ft is not None and ft > mine) or (base[o][0] > bi and ft is not None and ft < mine)
                        for o, ft in first.items() if o != bid and mine is not None)
        changed = actor or inputs or split or merged or reordered
        if disp == "restructured" and changed: touched += 1
        elif disp in ("merged", "absorbed") and (merged or split): touched += 1
    return touched / len(tss["disposition_mapping"])

def analyse(cells, label):
    wfs = sorted(wf_files)
    rng = random.Random(SEED)
    point = {wf: statistics.mean(cells[(wf, "council")]) - statistics.mean(cells[(wf, "baseline")]) for wf in wfs}
    passes = 0; per_wf = defaultdict(int); dist = defaultdict(int); gaps_acc = defaultdict(list)
    for _ in range(B):
        k = 0
        for wf in wfs:
            c = cells[(wf, "council")]; b = cells[(wf, "baseline")]
            gap = statistics.mean(rng.choices(c, k=len(c))) - statistics.mean(rng.choices(b, k=len(b)))
            gaps_acc[wf].append(gap)
            if ge(gap): per_wf[wf] += 1; k += 1
        dist[k] += 1
        if k >= NEED: passes += 1
    # leave-one-run-out
    loo = []
    for wf in wfs:
        for cond in ("council", "baseline"):
            for i in range(len(cells[(wf, cond)])):
                cc = dict(cells); cc[(wf, cond)] = cells[(wf, cond)][:i] + cells[(wf, cond)][i + 1:]
                k = sum(1 for w in wfs if ge(statistics.mean(cc[(w, "council")]) - statistics.mean(cc[(w, "baseline")])))
                loo.append((wf, cond, i + 1, k, k >= NEED))
    ci = {wf: (sorted(g)[int(0.025 * B)], sorted(g)[int(0.975 * B) - 1]) for wf, g in gaps_acc.items()}
    return {"label": label, "point_gaps": point, "point_pass": sum(1 for v in point.values() if ge(v)),
            "bootstrap_pass_rate": passes / B, "per_workflow_pass_prob": {wf: per_wf[wf] / B for wf in wfs},
            "gap_95ci": ci, "count_distribution": {k: dist[k] / B for k in sorted(dist)},
            "loo_pass_rate": sum(1 for x in loo if x[4]) / len(loo), "loo_fail_cases": [x[:4] for x in loo if not x[4]]}

res = {"B": B, "seed": SEED, "sesoi": SESOI, "need": NEED,
       "reported": analyse(depth_values(False), "depth as recorded"),
       "verified": analyse(depth_values(True), "verified depth")}
(ROOT / "export/results/bootstrap_h2.json").write_text(json.dumps(res, indent=1))

L = ["# Bootstrap of the H2 decision rule (held-out set)", "",
     f"{B} replicates, seed {SEED}; runs resampled with replacement within each cell; rule: gap >= {SESOI} on >= {NEED} of 7 workflows.", ""]
for key in ("reported", "verified"):
    r = res[key]
    L += [f"## {r['label']}", "", f"Point estimate: {r['point_pass']} of 7 workflows pass; H2 {'supported' if r['point_pass'] >= NEED else 'not supported'}.",
          f"Bootstrap: H2 passes in {100 * r['bootstrap_pass_rate']:.1f}% of replicates.",
          f"Leave-one-run-out: H2 passes in {100 * r['loo_pass_rate']:.1f}% of the 68 single-run deletions ({len(r['loo_fail_cases'])} deletions make it fail).", "",
          "| Workflow | Gap (point) | 95% interval | P(gap >= 0.2) |", "|---|---:|---:|---:|"]
    for wf in sorted(r["point_gaps"]):
        lo, hi = r["gap_95ci"][wf]
        L.append(f"| {wf} | {r['point_gaps'][wf]:.3f} | [{lo:.3f}, {hi:.3f}] | {r['per_workflow_pass_prob'][wf]:.2f} |")
    L += ["", "Distribution of the number of passing workflows: " + ", ".join(f"{k}: {100 * v:.1f}%" for k, v in r["count_distribution"].items()), ""]
    if r["loo_fail_cases"]:
        from collections import Counter
        cnt = Counter(f"{wf} {cond}" for wf, cond, i, k in r["loo_fail_cases"])
        L += ["Cells in which deleting a single run makes H2 fail (number of such runs): " + "; ".join(f"{c} ({n})" for c, n in sorted(cnt.items())), ""]
(ROOT / "docs/BOOTSTRAP_H2.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
