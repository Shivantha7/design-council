"""Supervisor feedback point 4a and 4b: symmetric control count and length adjustment.

4a  Apply the section 6 rule in both directions to the final merged controls:
      council-attributed: present in >= 60% of council runs and no baseline run (as reported)
      baseline-attributed: present in >= 60% of baseline runs and no council run
    and count controls present in at least one baseline run but no council run.
    Candidates were produced from both conditions' TSSs, but the codebook was seeded
    from council deliberation, so a baseline-only mechanism outside the candidate
    list would be missed; that limitation is stated in the output.

4b  Length normalisation. For every successful run: TSS length in words (the design
    itself, not deliberation), distinct final controls present, and controls per
    1,000 TSS words. Reported by condition and per workflow.

Outputs export/results/controls_symmetric_length.json and docs/CONTROLS_SYMMETRIC_LENGTH.md.
"""
import json, argparse, importlib.util, statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ccf", ROOT / "scripts/control_coding_final.py")
ccf = importlib.util.module_from_spec(spec); spec.loader.exec_module(ccf)
final, _ = ccf.build(argparse.Namespace(set_name="heldout-v1", runs_root=ROOT / "runs"))

def tss_words(rid):
    t = json.loads((ROOT / "runs" / rid / "tss.json").read_text())
    txt = " ".join(" ".join([s.get("name", ""), s.get("actor", ""), s.get("description", "")] + s.get("inputs", []) + s.get("outputs", [])) for s in t["steps"])
    return len(txt.split()), len(t["steps"])

sym = defaultdict(lambda: {"final": 0, "council_pass": 0, "baseline_pass": 0, "baseline_any_no_council": 0, "council_any_no_baseline": 0, "both": 0})
per_run = defaultdict(lambda: {"controls": set()})
for f in final.values():
    wf = f["wf"]; c = f["council"]; b = f["baseline"]
    cp = sum(f["pres"][r] for r in c); bp = sum(f["pres"][r] for r in b)
    s = sym[wf]; s["final"] += 1
    if cp >= 0.6 * len(c) and bp == 0: s["council_pass"] += 1
    if bp >= 0.6 * len(b) and cp == 0: s["baseline_pass"] += 1
    if bp > 0 and cp == 0: s["baseline_any_no_council"] += 1
    if cp > 0 and bp == 0: s["council_any_no_baseline"] += 1
    if cp > 0 and bp > 0: s["both"] += 1
    for r in c + b:
        per_run[(wf, "council" if r in c else "baseline", r)]
        if f["pres"][r]: per_run[(wf, "council" if r in c else "baseline", r)]["controls"].add(f["name"])

rows = []
for (wf, cond, rid), v in per_run.items():
    w, steps = tss_words(rid)
    rows.append({"wf": wf, "cond": cond, "run": rid, "words": w, "steps": steps, "controls": len(v["controls"]),
                 "per_1000_words": 1000 * len(v["controls"]) / w, "per_step": len(v["controls"]) / steps})

def agg(sel):
    return {k: round(statistics.mean(r[k] for r in sel), 3) for k in ["words", "steps", "controls", "per_1000_words", "per_step"]}
by_cond = {c: agg([r for r in rows if r["cond"] == c]) for c in ["council", "baseline"]}
by_wf = {wf: {c: agg([r for r in rows if r["wf"] == wf and r["cond"] == c]) for c in ["council", "baseline"]} for wf in sorted(sym)}
out = {"symmetric": dict(sym), "length_by_condition": by_cond, "length_by_workflow": by_wf, "runs": rows}
(ROOT / "export/results/controls_symmetric_length.json").write_text(json.dumps(out, indent=1))

L = ["# Governance controls: symmetric count and length adjustment", "",
     "## 4a Symmetric application of the section 6 rule (final merged controls)", "",
     "| Workflow | Final controls | Council-attributed (>=60% council, 0 baseline) | Baseline-attributed (>=60% baseline, 0 council) | In >=1 baseline run, 0 council | In >=1 council run, 0 baseline | In both |",
     "|---|---:|---:|---:|---:|---:|---:|"]
T = defaultdict(int)
for wf, s in sorted(sym.items()):
    L.append(f"| {wf} | {s['final']} | {s['council_pass']} | {s['baseline_pass']} | {s['baseline_any_no_council']} | {s['council_any_no_baseline']} | {s['both']} |")
    for k, v in s.items(): T[k] += v
L.append(f"| Total | {T['final']} | {T['council_pass']} | {T['baseline_pass']} | {T['baseline_any_no_council']} | {T['council_any_no_baseline']} | {T['both']} |")
L += ["", "Limitation: candidates were extracted from both conditions' TSSs, but the codebook was seeded from council deliberation; a baseline mechanism with no council counterpart could be under-represented in the candidate list.", "",
      "## 4b Length normalisation (TSS text only, per successful run, means)", "",
      "| Condition | TSS words | Steps | Distinct controls present | Controls per 1,000 words | Controls per step |", "|---|---:|---:|---:|---:|---:|"]
for c in ["council", "baseline"]:
    a = by_cond[c]; L.append(f"| {c} | {a['words']:.0f} | {a['steps']:.1f} | {a['controls']:.1f} | {a['per_1000_words']:.2f} | {a['per_step']:.2f} |")
L += ["", "| Workflow | Council words | Baseline words | Ratio | Council controls | Baseline controls | Council per 1,000 w | Baseline per 1,000 w |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
for wf, d in by_wf.items():
    c, b = d["council"], d["baseline"]
    L.append(f"| {wf} | {c['words']:.0f} | {b['words']:.0f} | {c['words']/b['words']:.2f} | {c['controls']:.1f} | {b['controls']:.1f} | {c['per_1000_words']:.2f} | {b['per_1000_words']:.2f} |")
(ROOT / "docs/CONTROLS_SYMMETRIC_LENGTH.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
