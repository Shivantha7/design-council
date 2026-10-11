"""Mechanical triage of control candidates under pre-registration section 6 rule 4. Read-only.

    python scripts/triage_controls.py --candidates-dir <dir> --set-name heldout-v1 \
        --out docs/CONTROL_TRIAGE.md

No coding decisions and no merges are applied. Presence is VERIFIED presence,
by the same checks as scripts/assemble_control_candidates.py: a run counts only
if at least one of its cited markers is found in that run's tss.json.

    PASS            council presence >= ceil(0.6 n) of the workflow's n council runs
                    (3 of 5, 3 of 4) AND baseline presence = 0       [pre-registered]
    FAIL-BASELINE   present in any baseline run
    FAIL-THRESHOLD  baseline = 0 and council presence below the threshold
    STRICT-75       exploratory sensitivity: council >= ceil(0.75 n) (4 of 5, 3 of 4)
                    AND baseline = 0

Merge groups (mechanical, from the candidates' own flags): one flag on candidate X
that uses merge language (MERGE_WORDS) and names other candidate ids of the same
workflow gives the group {X} plus those ids. Identical groups are counted once.
Groups are not chained. For each group, presence of the union counts a run if any
member is present. A group is listed when the union's outcome differs from at
least one member's own outcome. Nothing is merged in the counts.
"""

import argparse
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = REPO_ROOT / "runs"
TEMPLATE_WORKFLOWS = [
    "P2P-TWM-01", "P2P-PRE-01", "P2P-EXR-01",
    "R2R-ACR-01", "R2R-FSP-01",
    "FPA-VAR-01", "FPA-ABB-01",
]
MERGE_WORDS = re.compile(r"one control|same control|overlap|merge|combine|variant of", re.IGNORECASE)
ID_PATTERN = re.compile(r"\b(?:([A-Z]{3})-)?C(\d\d)\b")

spec = importlib.util.spec_from_file_location(
    "assemble", REPO_ROOT / "scripts" / "assemble_control_candidates.py")
assemble = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assemble)


def outcome(council: int, baseline: int, n: int, share: float) -> str:
    if baseline > 0:
        return "FAIL-BASELINE"
    return "PASS" if council >= math.ceil(share * n) else "FAIL-THRESHOLD"


def md(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


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

    def steps_of(run_id):
        if run_id not in steps_cache:
            steps_cache[run_id] = {s["step_id"]: s for s in
                                   json.loads((args.runs_root / run_id / "tss.json").read_text())["steps"]}
        return steps_cache[run_id]

    def verified(entries, allowed):
        runs, first_marker = set(), None
        for p in entries or []:
            rid = p.get("run_id")
            if rid not in allowed:
                continue
            steps = steps_of(rid)
            ok = None
            if p.get("step_id") in steps:
                ok = assemble.contains(assemble.step_text(steps[p["step_id"]], p.get("field")), p.get("marker", ""))
            if ok is None:
                ok = (assemble.contains(json.dumps(list(steps.values()), ensure_ascii=False), p.get("marker", ""))
                      or assemble.contains("\n".join(assemble.step_text(s, None) for s in steps.values()),
                                           p.get("marker", "")))
            if ok:
                runs.add(rid)
                first_marker = first_marker or p.get("marker", "")
        return runs, first_marker

    summary, pass_rows, group_rows = [], [], []
    for wf in TEMPLATE_WORKFLOWS:
        council_runs, baseline_runs = cells[(wf, "council")], cells[(wf, "baseline")]
        n = len(council_runs)
        data = json.loads((args.candidates_dir / f"controls_{wf}.json").read_text())
        prefix = data["candidates"][0]["id"].split("-")[0]
        cand = {}
        for c in data["candidates"]:
            cr, marker = verified(c.get("council_present"), council_runs)
            br, _ = verified(c.get("baseline_present"), baseline_runs)
            cand[c["id"]] = {"c": c, "cr": cr, "br": br, "marker": marker or "",
                             "out": outcome(len(cr), len(br), n, 0.60),
                             "strict": outcome(len(cr), len(br), n, 0.75) == "PASS"}

        groups = set()
        for cid, x in cand.items():
            for flag in x["c"].get("flags") or []:
                if not MERGE_WORDS.search(flag):
                    continue
                ids = {f"{p or prefix}-C{num}" for p, num in ID_PATTERN.findall(flag) if (p or prefix) == prefix}
                ids = {i for i in ids if i in cand} - {cid}
                if ids:
                    groups.add(tuple(sorted(ids | {cid})))
        changing = []
        for g in sorted(groups):
            cr = set().union(*(cand[i]["cr"] for i in g))
            br = set().union(*(cand[i]["br"] for i in g))
            union_out = outcome(len(cr), len(br), n, 0.60)
            if any(cand[i]["out"] != union_out for i in g):
                changing.append(g)
                members = ", ".join(f"{i} {cand[i]['out']} ({len(cand[i]['cr'])}/{n}, b{len(cand[i]['br'])})" for i in g)
                group_rows.append(f"- **{wf}** {' + '.join(g)}: members {members} → union "
                                  f"{union_out} ({len(cr)}/{n} council, {len(br)} baseline)")

        outs = [x["out"] for x in cand.values()]
        summary.append((wf, n, len(cand), outs.count("FAIL-BASELINE"), outs.count("FAIL-THRESHOLD"),
                        outs.count("PASS"), sum(x["strict"] for x in cand.values()), len(changing), len(groups)))
        for cid, x in cand.items():
            if x["out"] == "PASS":
                att = x["c"].get("attribution") or {}
                pass_rows.append(
                    f"| {cid} | {wf} | {md(x['c'].get('title', ''))} | \"{md(x['marker'])}\" | "
                    f"{', '.join(att.get('roles') or []) or '–'} | {len(x['cr'])}/{n} | "
                    f"{'yes' if x['strict'] else 'no'} | {md('; '.join(x['c'].get('flags') or [])) or '–'} |")

    out = []
    add = out.append
    add("# Control triage: pre-registration section 6, rule 4 (mechanical)")
    add("")
    add("**Mechanical application only. No coding decisions and no merges are applied.** Input: "
        "the 307 candidates behind `docs/CONTROL_CODING_CANDIDATES.md`, with presence counted "
        "only where a marker is verified against the run's `tss.json`. Generated by "
        "`scripts/triage_controls.py`, whose docstring gives the definitions. PASS (≥ 60% of "
        "council runs, i.e. 3 of 5 or 3 of 4, and no baseline run) is the pre-registered "
        "rule. STRICT-75 (4 of 5, or 3 of 4) is an exploratory sensitivity check.")
    add("")
    add("## 1. Summary")
    add("")
    add("| Workflow | Council n | Candidates | FAIL-BASELINE | FAIL-THRESHOLD | PASS | STRICT-75 "
        "| Flagged merge groups | Groups that change an outcome |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    tot = [0] * 7
    for wf, n, c, fb, ft, p, s, ch, g in summary:
        add(f"| {wf} | {n} | {c} | {fb} | {ft} | {p} | {s} | {g} | {ch} |")
        for i, v in enumerate((c, fb, ft, p, s, g, ch)):
            tot[i] += v
    add(f"| **Total** | | {tot[0]} | {tot[1]} | {tot[2]} | {tot[3]} | {tot[4]} | {tot[5]} | {tot[6]} |")
    add("")
    add("## 2. PASS list")
    add("")
    add("| Id | Workflow | Candidate | Marker (first verified council presence) | Introducing role(s) "
        "| Council n/N | STRICT-75 | Flags |")
    add("|---|---|---|---|---|---:|---|---|")
    out += pass_rows
    add("")
    add("## 3. Merge groups that would change an outcome")
    add("")
    add("Each line shows the members' own outcomes (council presence / n, baseline b) and the "
        "outcome of their union. Listed for the author's coding decision. Nothing is merged "
        "above.")
    add("")
    out += group_rows or ["None."]
    add("")
    args.out.write_text("\n".join(out) + "\n")

    print("| Workflow | n | Candidates | FAIL-BASELINE | FAIL-THRESHOLD | PASS | STRICT-75 | Merge groups changing outcome |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for wf, n, c, fb, ft, p, s, ch, g in summary:
        print(f"| {wf} | {n} | {c} | {fb} | {ft} | {p} | {s} | {ch} of {g} |")
    print(f"| Total | | {tot[0]} | {tot[1]} | {tot[2]} | {tot[3]} | {tot[4]} | {tot[6]} of {tot[5]} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
