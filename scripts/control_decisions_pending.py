"""Single-standard control outcomes and pending decisions, by pattern. Read-only on runs.

    python scripts/control_decisions_pending.py --candidates-dir <dir> --set-name heldout-v1 \
        --out docs/CONTROL_DECISIONS_PENDING.md

Inputs per workflow: merges_<wf>.json (proposed controls) and rejudge_<wf>.json,
a single judging pass per control applying ONE test to every council and baseline
run (docs/CONTROL_MERGE_RULE.md, decisions of 11 Oct 2026). A presence claim
counts only if its quote is found verbatim in that run's tss.json.

    default outcome   the judge's own call for every run. PASS = council
                      >= ceil(0.6 n) and baseline 0. STRICT-75 = ceil(0.75 n).
    borderline case   a (control, run) call the judge marked borderline. It is
                      outcome-changing only if some assignment of that control's
                      borderline calls changes its PASS/FAIL outcome. Otherwise it
                      is logged with its default and needs no decision.
    merge case        a LOW merge decision. A proposed split of a SINGLE-candidate
                      control is not a decision: the author ruled NO SPLITS, so it
                      is logged as kept whole. merge_with: compare the union's
                      outcome with the separate outcomes. split: the members
                      were not judged separately under the single standard, so
                      these are listed as one-offs.
    patterns          the judge tags each case with a fixed pattern (B1-B5,
                      M1-M4). The x9 tags are one-offs. For each pattern, the
                      total PASS is computed with every case in it answered A,
                      then B, all other calls at default.
"""

import argparse
import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = REPO_ROOT / "runs"
TEMPLATE_WORKFLOWS = [
    "P2P-TWM-01", "P2P-PRE-01", "P2P-EXR-01",
    "R2R-ACR-01", "R2R-FSP-01",
    "FPA-VAR-01", "FPA-ABB-01",
]
PATTERNS = {
    "B1": ("Does a less-detailed statement of a mechanism count as the same control?",
           "A: yes, it counts as present", "B: no, only a fully stated mechanism counts"),
    "B2": ("Does a principle or accountability statement count as an operative mechanism?",
           "A: yes, present", "B: no, absent"),
    "B3": ("Does the same mechanism at a neighbouring step count as the same point?",
           "A: yes, present", "B: no, absent"),
    "B4": ("Does a mechanism covering only a subset or lane of the object count?",
           "A: yes, present", "B: no, absent"),
    "B5": ("Does the same check by a different performer (actor or automation) count as the same mechanism?",
           "A: yes, present", "B: no, absent"),
    "M1": ("Are directional or variant pairs on the same object one control?",
           "A: merge", "B: keep separate"),
    "M2": ("Is a check and its own record/log one control?", "A: merge", "B: keep separate"),
    "M3": ("Is the same mechanism at adjacent points one control?", "A: merge", "B: keep separate"),
    "M4": ("Are controls on overlapping objects (one a subset of the other) one control?",
           "A: merge", "B: keep separate"),
}

spec = importlib.util.spec_from_file_location(
    "assemble", REPO_ROOT / "scripts" / "assemble_control_candidates.py")
assemble = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assemble)


def outcome(c: int, b: int, n: int, share: float = 0.60) -> str:
    if b > 0:
        return "FAIL-BASELINE"
    return "PASS" if c >= math.ceil(share * n) else "FAIL-THRESHOLD"


def md(t) -> str:
    return (t or "").replace("|", "/").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates-dir", type=Path, required=True)
    parser.add_argument("--set-name", required=True)
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    cells = {}
    for e in map(json.loads, (args.runs_root / f"_set-{args.set_name}.ledger.jsonl").read_text().splitlines()):
        if e["event"] == "finished" and e["status"] == "ok":
            cells.setdefault((e["workflow_id"], e["condition"]), []).append(e["run_id"])

    steps_cache = {}

    def found(run_id, step_id, field, text):
        if run_id not in steps_cache:
            steps_cache[run_id] = {s["step_id"]: s for s in
                                   json.loads((args.runs_root / run_id / "tss.json").read_text())["steps"]}
        steps = steps_cache[run_id]
        if step_id in steps and assemble.contains(assemble.step_text(steps[step_id], field), text or ""):
            return True
        return bool(assemble.contains("\n".join(assemble.step_text(s, None) for s in steps.values()), text or ""))

    controls = {}      # id -> dict
    problems, unverified = [], 0
    for wf in TEMPLATE_WORKFLOWS:
        council, baseline = cells[(wf, "council")], cells[(wf, "baseline")]
        path = args.candidates_dir / f"rejudge_{wf}.json"
        if not path.exists():
            problems.append(f"{wf}: no rejudge file")
            continue
        names = {c["id"]: c for c in json.loads((args.candidates_dir / f"merges_{wf}.json").read_text())["controls"]}
        judged = json.loads(path.read_text())["controls"]
        if set(names) != {c["id"] for c in judged}:
            problems.append(f"{wf}: rejudge ids differ from merges ids")
        for c in judged:
            pres, border = {}, {}
            for rid in council + baseline:
                p = (c.get("presence") or {}).get(rid)
                if p is None:
                    problems.append(f"{c['id']}: run {rid} not judged")
                    pres[rid] = False
                    continue
                ok = bool(p.get("present")) and found(rid, p.get("step_id"), p.get("field"), p.get("quote"))
                if p.get("present") and not ok:
                    unverified += 1
                pres[rid] = ok
                if p.get("borderline"):
                    border[rid] = {"pattern": p.get("pattern") or "B9", "quote": p.get("quote", ""),
                                   "note": p.get("note", "")}
            controls[c["id"]] = {"wf": wf, "name": names.get(c["id"], {}).get("name", ""),
                                 "members": names.get(c["id"], {}).get("members", []),
                                 "pres": pres, "border": border, "merge_low": c.get("merge_low"),
                                 "council": council, "baseline": baseline}

    def result(cid, flips=None):
        c = controls[cid]
        pres = dict(c["pres"])
        for rid, v in (flips or {}).items():
            pres[rid] = v
        return (sum(pres[r] for r in c["council"]), sum(pres[r] for r in c["baseline"]))

    def out_of(cid, flips=None, share=0.60):
        cc, bb = result(cid, flips)
        return outcome(cc, bb, len(controls[cid]["council"]), share)

    # Borderline: keep a control's cases if any assignment of its borderline runs changes the outcome.
    changing_border, logged = [], []
    for cid, c in controls.items():
        runs = list(c["border"])
        if not runs:
            continue
        default = out_of(cid)
        outs = {out_of(cid, dict(zip(runs, combo))) for combo in itertools.product([True, False], repeat=len(runs))}
        target = changing_border if len(outs | {default}) > 1 else logged
        for rid in runs:
            target.append((cid, rid))

    # Merge LOW cases.
    changing_merge, logged_merge, oneoff_split, kept_whole = [], [], [], []
    oneoff_drop, logged_drop = [], []
    for cid, c in controls.items():
        ml = c["merge_low"]
        if not ml:
            continue
        alt = ml.get("alternative") or {}
        if alt.get("type") == "split":
            (kept_whole if len(c["members"]) <= 1 else oneoff_split).append(cid)
            continue
        if alt.get("type") == "drop":
            # Whether this is a governance control at all: changes an outcome only if it passes.
            (oneoff_drop if out_of(cid) == "PASS" else logged_drop).append(cid)
            continue
        others = [o for o in alt.get("control_ids") or [] if o in controls]
        group = [cid] + others
        cr = sum(any(controls[g]["pres"][r] for g in group) for r in c["council"])
        br = sum(any(controls[g]["pres"][r] for g in group) for r in c["baseline"])
        union = outcome(cr, br, len(c["council"]))
        separate = {g: out_of(g) for g in group}
        (changing_merge if any(v != union for v in separate.values()) else logged_merge).append(
            (cid, ml, group, union, separate))

    # The same pair can be raised from both sides (M01 "merge with M02", M02 "merge with M01"):
    # one question, counted once.
    def dedupe(cases):
        seen, kept = set(), []
        for x in cases:
            key = frozenset(x[2])
            if key not in seen:
                seen.add(key)
                kept.append(x)
        return kept

    changing_merge, logged_merge = dedupe(changing_merge), dedupe(logged_merge)

    def total_pass(flips_by_control=None):
        return sum(out_of(cid, (flips_by_control or {}).get(cid)) == "PASS" for cid in controls)

    base_pass = total_pass()
    out = []
    add = out.append
    add("# Control coding: pending decisions under the single evidence standard")
    add("")
    add("Single standard: `docs/CONTROL_MERGE_RULE.md` (author's decisions of 11 Oct 2026; one judging "
        "pass per control, the same test for council and baseline runs). Presence counts only where the "
        "judge's quote is found verbatim in the run's `tss.json`. Generated by "
        "`scripts/control_decisions_pending.py`. **Nothing is decided here.** Defaults are the judge's "
        "calls, and every outcome-changing question is listed for the author.")
    add("")
    if problems or unverified:
        add(f"**Checks:** {unverified} presence claims had unverifiable quotes and are counted absent. "
            + ("Problems: " + "; ".join(problems[:10]) if problems else "No other problems."))
        add("")

    add("## 1. Outcomes at default (single standard)")
    add("")
    add("| Workflow | Council n | Controls | PASS | STRICT-75 | Outcome-changing LOW cases |")
    add("|---|---:|---:|---:|---:|---:|")
    summary = []
    for wf in TEMPLATE_WORKFLOWS:
        ids = [i for i, c in controls.items() if c["wf"] == wf]
        if not ids:
            continue
        p = sum(out_of(i) == "PASS" for i in ids)
        s = sum(out_of(i, share=0.75) == "PASS" for i in ids)
        low = (len({cid for cid, _ in changing_border if controls[cid]["wf"] == wf})
               + sum(1 for x in changing_merge if controls[x[0]]["wf"] == wf)
               + sum(1 for x in oneoff_split + oneoff_drop if controls[x]["wf"] == wf))
        summary.append((wf, len(controls[ids[0]]["council"]), len(ids), p, s, low))
        add(f"| {wf} | {summary[-1][1]} | {len(ids)} | {p} | {s} | {low} |")
    tot = [sum(r[i] for r in summary) for i in (2, 3, 4, 5)]
    add(f"| **Total** | | {tot[0]} | {tot[1]} | {tot[2]} | {tot[3]} |")
    add("")
    add("LOW cases are counted per control (a control with several outcome-changing borderline runs is "
        "one decision unit).")
    add("")

    add("## 2. Decision patterns")
    add("")
    pattern_rows = []
    for pat, (question, a_ans, b_ans) in PATTERNS.items():
        if pat.startswith("B"):
            cases = [(cid, rid) for cid, rid in changing_border if controls[cid]["border"][rid]["pattern"] == pat]
            if not cases:
                continue
            flips_a, flips_b = {}, {}
            for cid, rid in cases:
                flips_a.setdefault(cid, {})[rid] = True
                flips_b.setdefault(cid, {})[rid] = False
            pa, pb = total_pass(flips_a), total_pass(flips_b)
            ctl = sorted({cid for cid, _ in cases})
            examples = [f"{cid} `{rid[-4:]}` \"{md(controls[cid]['border'][rid]['quote'])[:90]}\"" for cid, rid in cases[:2]]
        else:
            cases = [x for x in changing_merge if (x[1].get("pattern") or "M9") == pat]
            if not cases:
                continue
            ctl = [x[0] for x in cases]
            delta = sum((x[3] == "PASS") - sum(v == "PASS" for v in x[4].values()) for x in cases)
            pa, pb = base_pass + delta, base_pass
            examples = [f"{x[0]} + {', '.join(x[2][1:])}: {md(x[1].get('question'))[:110]}" for x in cases[:2]]
        pattern_rows.append((pat, question, a_ans, b_ans, len(cases), len(ctl), pa, pb, examples))
        add(f"### {pat}. {question}")
        add("")
        add(f"- **Answers:** {a_ans} / {b_ans}")
        add(f"- **Cases:** {len(cases)} ({len(ctl)} controls)")
        add(f"- **Effect:** total PASS = **{pa}** under A, **{pb}** under B (default {base_pass})")
        add(f"- **Examples:** " + "; ".join(examples))
        add("")

    add("## 3. One-offs (individual decisions)")
    add("")
    add("| Control | Workflow | Question | Outcome as default | Outcome the other way |")
    add("|---|---|---|---|---|")
    for cid, rid in changing_border:
        b = controls[cid]["border"][rid]
        if b["pattern"] in PATTERNS:
            continue
        cur = controls[cid]["pres"][rid]
        add(f"| {cid} | {controls[cid]['wf']} | run {rid[-4:]}: {md(b['note'])[:140]} \"{md(b['quote'])[:80]}\" | "
            f"{out_of(cid)} ({'present' if cur else 'absent'}) | {out_of(cid, {rid: not cur})} |")
    for cid, ml, group, union, separate in changing_merge:
        if (ml.get("pattern") or "M9") in PATTERNS:
            continue
        add(f"| {cid} | {controls[cid]['wf']} | merge with {', '.join(group[1:])}: {md(ml.get('question'))[:140]} | "
            f"separate: {', '.join(f'{g} {v}' for g, v in separate.items())} | merged: {union} |")
    for cid in oneoff_drop:
        add(f"| {cid} | {controls[cid]['wf']} | is this a governance control at all? "
            f"{md(controls[cid]['merge_low'].get('question'))[:140]} | {out_of(cid)} | excluded (not a control) |")
    for cid in oneoff_split:
        add(f"| {cid} | {controls[cid]['wf']} | split {' / '.join(map(str, controls[cid]['merge_low']['alternative'].get('into', [])))}: "
            f"{md(controls[cid]['merge_low'].get('question'))[:140]} | merged: {out_of(cid)} | split: members not judged "
            f"separately under the single standard |")
    add("")

    add("## 4. Logged LOW cases that cannot change any outcome (no decision needed)")
    add("")
    add(f"{len(logged)} borderline presence calls and {len(logged_merge)} merge questions. In each, "
        "every possible answer leaves every affected control's PASS/FAIL unchanged. Recorded with the "
        "default.")
    add("")
    add("<details><summary>Logged cases</summary>")
    add("")
    add("| Control | Run / question | Pattern | Default call | Outcome (fixed) |")
    add("|---|---|---|---|---|")
    for cid, rid in logged:
        b = controls[cid]["border"][rid]
        add(f"| {cid} | {rid[-4:]} | {b['pattern']} | {'present' if controls[cid]['pres'][rid] else 'absent'} | {out_of(cid)} |")
    for cid, ml, group, union, separate in logged_merge:
        add(f"| {cid} | merge with {', '.join(group[1:])} | {ml.get('pattern')} | keep separate | {union} |")
    for cid in logged_drop:
        add(f"| {cid} | is it a control at all? | drop question | kept | {out_of(cid)} (does not pass either way) |")
    for cid in kept_whole:
        add(f"| {cid} | proposed split of a single candidate | NO SPLITS (author) | kept whole | {out_of(cid)} |")
    add("")
    add("</details>")
    add("")
    args.out.write_text("\n".join(out) + "\n")

    print("| Workflow | n | Controls | PASS | STRICT-75 | Outcome-changing LOW |")
    print("|---|---:|---:|---:|---:|---:|")
    for r in summary:
        print("| " + " | ".join(map(str, r)) + " |")
    print(f"| Total | | {tot[0]} | {tot[1]} | {tot[2]} | {tot[3]} |")
    print()
    print("| Pattern | Question | Cases (controls) | PASS if A | PASS if B |")
    print("|---|---|---:|---:|---:|")
    for pat, q, a, b, nc, nctl, pa, pb, _ in pattern_rows:
        print(f"| {pat} | {q} | {nc} ({nctl}) | {pa} | {pb} |")
    one_offs = (sum(1 for cid, rid in changing_border if controls[cid]['border'][rid]['pattern'] not in PATTERNS)
                + sum(1 for x in changing_merge if (x[1].get('pattern') or 'M9') not in PATTERNS) + len(oneoff_split)
                + len(oneoff_drop))
    print(f"default PASS {base_pass}; one-offs {one_offs}; logged (no decision) {len(logged)} borderline + "
          f"{len(logged_merge)} merge; unverified presence claims {unverified}; problems {problems or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
