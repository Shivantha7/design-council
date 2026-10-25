"""Compare the exploratory sequential single agent with the council and baseline on one workflow.

    python3 scripts/analyse_sequential.py P2P-TWM-01

Per condition: n, depth as recorded (mean, min, max), verified depth, conformance,
run-to-run consistency, tokens and cost (all attempts, same rates as efficiency_heldout.py).
Writes docs/SEQUENTIAL_<wf>.md. No model calls.
"""
import json, sys, re, statistics, itertools
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
wf = sys.argv[1] if len(sys.argv) > 1 else "P2P-TWM-01"
PI, PO = 2.0, 10.0

events = [json.loads(l) for l in (ROOT / "runs/_set-heldout-v1.ledger.jsonl").read_text().splitlines()]
enc_path = next(e for e in events if e["event"] == "set_started")["workflows"][wf]
enc = json.loads((ROOT / enc_path).read_text())
runs = defaultdict(list)
for e in events:
    if e["event"] == "finished" and e["status"] == "ok" and e["workflow_id"] == wf:
        runs[e["condition"]].append(e["run_id"])
for d in sorted((ROOT / "runs").glob(f"*-sequential-{wf}-*")):
    if (d / "tss.json").exists(): runs["sequential"].append(d.name)

def norm(x): return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()
def verified_depth(tss):
    base = {s["step_id"]: (i, s) for i, s in enumerate(enc["steps"])}
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
        merged = any(share[t] > 1 for t in targets); split = len(targets) > 1; mine = first[bid]
        reordered = any((base[o][0] < bi and ft is not None and ft > mine) or (base[o][0] > bi and ft is not None and ft < mine)
                        for o, ft in first.items() if o != bid and mine is not None)
        if (disp == "restructured" and (actor or inputs or merged or split or reordered)) or (disp in ("merged", "absorbed") and (merged or split)):
            touched += 1
    return touched / len(tss["disposition_mapping"])

rows = {}
for cond, ids in runs.items():
    deps, vdeps, confs, toks_i, toks_o, labels, words = [], [], [], [], [], [], []
    for rid in ids:
        d = ROOT / "runs" / rid
        tss = json.loads((d / "tss.json").read_text()); gate = json.loads((d / "gate_result.json").read_text())
        m = tss["disposition_mapping"]
        deps.append(sum(1 for x in m if x["disposition"] != "retained") / len(m)); vdeps.append(verified_depth(tss))
        confs.append(gate["conformance_score"])
        labels.append({x["baseline_step_id"]: x["disposition"] for x in m})
        words.append(len(" ".join(" ".join([s.get("name",""), s.get("actor",""), s.get("description","")] + s.get("inputs",[]) + s.get("outputs",[])) for s in tss["steps"]).split()))
        ti = to = 0
        for line in (d / "calls.jsonl").read_text().splitlines():
            c = json.loads(line); ti += c.get("input_tokens") or 0; to += c.get("output_tokens") or 0
        toks_i.append(ti); toks_o.append(to)
    pairs = [sum(1 for k in a if a[k] == b.get(k)) / len(a) for a, b in itertools.combinations(labels, 2)]
    rows[cond] = dict(n=len(ids), depth=statistics.mean(deps), dmin=min(deps), dmax=max(deps), vdepth=statistics.mean(vdeps),
                      conf=statistics.mean(confs), below1=sum(1 for c in confs if c < 1), cons=statistics.mean(pairs) if pairs else float("nan"),
                      ti=statistics.mean(toks_i), to=statistics.mean(toks_o), cost=statistics.mean(i * PI / 1e6 + o * PO / 1e6 for i, o in zip(toks_i, toks_o)),
                      words=statistics.mean(words))
L = [f"# Sequential single agent vs council vs baseline: {wf}", "", "Exploratory, post-freeze. Sequential = one agent, seven cumulative perspectives, seven reconsiderations, synthesis (15 calls).", "",
     "| Condition | n | Depth (mean) | min | max | Verified depth | Conformance | Runs < 1 | Consistency | Input tok | Output tok | Cost USD | Design words |",
     "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
for cond in ["baseline", "sequential", "council"]:
    if cond not in rows: continue
    r = rows[cond]
    L.append(f"| {cond} | {r['n']} | {r['depth']:.3f} | {r['dmin']:.3f} | {r['dmax']:.3f} | {r['vdepth']:.3f} | {r['conf']:.3f} | {r['below1']} | {r['cons']:.3f} | {r['ti']:,.0f} | {r['to']:,.0f} | {r['cost']:.2f} | {r['words']:.0f} |")
if "sequential" in rows and "council" in rows:
    L += ["", f"Gap council minus sequential, depth as recorded: {rows['council']['depth'] - rows['sequential']['depth']:+.3f}; verified: {rows['council']['vdepth'] - rows['sequential']['vdepth']:+.3f}.",
          f"Gap sequential minus baseline, depth as recorded: {rows['sequential']['depth'] - rows['baseline']['depth']:+.3f}; verified: {rows['sequential']['vdepth'] - rows['baseline']['vdepth']:+.3f}.",
          f"Compute ratio sequential/council: input {rows['sequential']['ti'] / rows['council']['ti']:.2f}, output {rows['sequential']['to'] / rows['council']['to']:.2f}, cost {rows['sequential']['cost'] / rows['council']['cost']:.2f}."]
(ROOT / f"docs/SEQUENTIAL_{wf}.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
