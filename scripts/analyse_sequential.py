"""Compare the exploratory sequential single agent with the council and baseline on one workflow.

    python3 scripts/analyse_sequential.py P2P-TWM-01

Per condition: n, depth as recorded (mean, min, max), verified depth, conformance,
run-to-run consistency, tokens and cost (all attempts, same rates as efficiency_heldout.py).
Then, for the sequential runs: one row per run, any failed attempts, and, where
docs/SEQUENTIAL_<wf>_preregistration.md exists, the pre-stated outcome that applies and a
table comparing every workflow that has sequential runs.
Writes docs/SEQUENTIAL_<wf>.md. No model calls.
"""
import json, sys, re, statistics, itertools, subprocess
from collections import defaultdict
from datetime import datetime
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
wf = sys.argv[1] if len(sys.argv) > 1 else "P2P-TWM-01"
PI, PO = 2.0, 10.0
PROBE = "model_resolution_probe"

events = [json.loads(l) for l in (ROOT / "runs/_set-heldout-v1.ledger.jsonl").read_text().splitlines()]
ENC_PATHS = next(e for e in events if e["event"] == "set_started")["workflows"]


def norm(x): return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()


def verified_depth(enc, tss):
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


def analyse(wf):
    """Per condition aggregates, per-run details and failed attempts for one workflow."""
    enc = json.loads((ROOT / ENC_PATHS[wf]).read_text())
    runs, failed = defaultdict(list), []
    for e in events:
        if e["event"] == "finished" and e["status"] == "ok" and e["workflow_id"] == wf:
            runs[e["condition"]].append(e["run_id"])
    for d in sorted((ROOT / "runs").glob(f"*-sequential-{wf}-*")):
        if (d / "tss.json").exists(): runs["sequential"].append(d.name)
        else: failed.append(d.name)
    rows, per_run = {}, {}
    for cond, ids in runs.items():
        deps, vdeps, confs, toks_i, toks_o, labels, words, details = [], [], [], [], [], [], [], []
        for rid in ids:
            d = ROOT / "runs" / rid
            tss = json.loads((d / "tss.json").read_text()); gate = json.loads((d / "gate_result.json").read_text())
            m = tss["disposition_mapping"]
            deps.append(Fraction(sum(1 for x in m if x["disposition"] != "retained"), len(m))); vdeps.append(verified_depth(enc, tss))
            confs.append(gate["conformance_score"])
            labels.append({x["baseline_step_id"]: x["disposition"] for x in m})
            words.append(len(" ".join(" ".join([s.get("name",""), s.get("actor",""), s.get("description","")] + s.get("inputs",[]) + s.get("outputs",[])) for s in tss["steps"]).split()))
            calls = [json.loads(line) for line in (d / "calls.jsonl").read_text().splitlines() if line.strip()]
            ti = sum(c.get("input_tokens") or 0 for c in calls); to = sum(c.get("output_tokens") or 0 for c in calls)
            toks_i.append(ti); toks_o.append(to)
            # Runtime from the first to the last call of this run. The probe is excluded: one probe
            # serves every rep of an invocation, so its timestamp is the invocation start.
            ts = [datetime.fromisoformat(c["timestamp_utc"].replace("Z", "+00:00")) for c in calls if c["agent_role"] != PROBE]
            details.append(dict(run_id=rid, depth=deps[-1], vdepth=vdeps[-1], conf=confs[-1], calls=len(calls),
                                ti=ti, to=to, cost=ti * PI / 1e6 + to * PO / 1e6,
                                minutes=(max(ts) - min(ts)).total_seconds() / 60, words=words[-1]))
        pairs = [sum(1 for k in a if a[k] == b.get(k)) / len(a) for a, b in itertools.combinations(labels, 2)]
        for i, det in enumerate(details):
            others = [sum(1 for k in labels[i] if labels[i][k] == labels[j].get(k)) / len(labels[i]) for j in range(len(labels)) if j != i]
            det["cons"] = statistics.mean(others) if others else float("nan")
        per_run[cond] = details
        rows[cond] = dict(n=len(ids), depth=sum(deps, Fraction(0)) / len(deps), dmin=min(deps), dmax=max(deps), vdepth=statistics.mean(vdeps),
                          conf=statistics.mean(confs), below1=sum(1 for c in confs if c < 1), cons=statistics.mean(pairs) if pairs else float("nan"),
                          ti=statistics.mean(toks_i), to=statistics.mean(toks_o), cost=statistics.mean(i * PI / 1e6 + o * PO / 1e6 for i, o in zip(toks_i, toks_o)),
                          words=statistics.mean(words))
    return dict(rows=rows, per_run=per_run, failed=failed, steps=len(enc["steps"]))


a = analyse(wf)
rows = a["rows"]
L = [f"# Sequential single agent vs council vs baseline: {wf}", "", "Exploratory, post-freeze. Sequential = one agent, seven cumulative perspectives, seven reconsiderations, synthesis (15 calls).", "",
     "| Condition | n | Depth (mean) | min | max | Verified depth | Conformance | Runs < 1 | Consistency | Input tok | Output tok | Cost USD | Design words |",
     "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
for cond in ["baseline", "sequential", "council"]:
    if cond not in rows: continue
    r = rows[cond]
    L.append(f"| {cond} | {r['n']} | {float(r['depth']):.3f} | {float(r['dmin']):.3f} | {float(r['dmax']):.3f} | {r['vdepth']:.3f} | {r['conf']:.3f} | {r['below1']} | {r['cons']:.3f} | {r['ti']:,.0f} | {r['to']:,.0f} | {r['cost']:.2f} | {r['words']:.0f} |")
if "sequential" in rows and "council" in rows:
    L += ["", f"Gap council minus sequential, depth as recorded: {float(rows['council']['depth'] - rows['sequential']['depth']):+.3f}; verified: {rows['council']['vdepth'] - rows['sequential']['vdepth']:+.3f}.",
          f"Gap sequential minus baseline, depth as recorded: {float(rows['sequential']['depth'] - rows['baseline']['depth']):+.3f}; verified: {rows['sequential']['vdepth'] - rows['baseline']['vdepth']:+.3f}.",
          f"Compute ratio sequential/council: input {rows['sequential']['ti'] / rows['council']['ti']:.2f}, output {rows['sequential']['to'] / rows['council']['to']:.2f}, cost {rows['sequential']['cost'] / rows['council']['cost']:.2f}."]

if "sequential" in a["per_run"]:
    L += ["", "## Sequential runs", "",
          "Consistency is the run's mean disposition agreement with the other sequential runs. Runtime is first to last call, "
          "excluding the shared model-resolution probe.", "",
          "| Run | Depth | Verified depth | Conformance | Consistency | Calls | Input tok | Output tok | Cost USD | Runtime min |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in a["per_run"]["sequential"]:
        L.append(f"| {r['run_id']} | {float(r['depth']):.3f} | {r['vdepth']:.3f} | {r['conf']:.3f} | {r['cons']:.3f} | {r['calls']} | "
                 f"{r['ti']:,} | {r['to']:,} | {r['cost']:.2f} | {r['minutes']:.1f} |")
    L += ["", "Failed attempts (kept in runs/, no TSS, excluded from every figure): "
          + (", ".join(a["failed"]) if a["failed"] else "none") + "."]

prereg = ROOT / f"docs/SEQUENTIAL_{wf}_preregistration.md"
if prereg.exists() and "sequential" in rows:
    commit = subprocess.run(["git", "log", "-1", "--format=%H", "--", str(prereg.relative_to(ROOT))], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    q = Fraction(1, a["steps"])
    g = rows["council"]["depth"] - rows["sequential"]["depth"]
    if abs(g) <= q: outcome = "a"
    elif g >= Fraction(1, 5): outcome = "b"
    elif q < g < Fraction(1, 5): outcome = "c"
    else: outcome = None
    sentence = {"a": "on both workflows tested, a single agent given the Council's compute and walked through the seven role charters "
                     "matched the Council's depth; the depth advantage is attributable to computation, not deliberation, on this evidence",
                "b": "the compute-matched agent matched the Council on transactional work but not on judgment-dense work, consistent "
                     "with the exploratory finding in Section 7.5",
                "c": "the compute-matched agent closed most but not all of the gap; the attribution to deliberation on "
                     "judgment-dense work remains open"}
    L += ["", "## Pre-stated outcome", "",
          f"Pre-registration note: `{prereg.relative_to(ROOT)}`, commit `{commit}`.", "",
          f"G = council mean depth minus sequential mean depth = {g} = {float(g):+.3f}; one quantum = {q} = {float(q):.3f}.", ""]
    if outcome:
        L.append(f"Outcome **{outcome}** applies: \"{sentence[outcome]}\".")
    else:
        L.append("Sequential is ahead of the council by more than one quantum: not covered by a pre-stated sentence; reported descriptively.")

    # In the order the workflows were first run (run ids start with a timestamp).
    seq_wfs = []
    for p in sorted((ROOT / "runs").glob("*-sequential-*")):
        w = p.name.split("-sequential-")[1].rsplit("-", 1)[0]
        if (p / "tss.json").exists() and w not in seq_wfs: seq_wfs.append(w)
    L += ["", "## Workflows with sequential runs", "",
          "Depth as recorded (mean), conformance (mean), run-to-run consistency; sequential / council / baseline.", "",
          "| Workflow | Depth seq | Depth council | Depth baseline | Conf. seq | Conf. council | Conf. baseline | Cons. seq | Cons. council | Cons. baseline |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for w in seq_wfs:
        r = analyse(w)["rows"]
        c = ["sequential", "council", "baseline"]
        L.append(f"| {w} | " + " | ".join(f"{float(r[x]['depth']):.3f}" for x in c) + " | "
                 + " | ".join(f"{r[x]['conf']:.3f}" for x in c) + " | " + " | ".join(f"{r[x]['cons']:.3f}" for x in c) + " |")

(ROOT / f"docs/SEQUENTIAL_{wf}.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
