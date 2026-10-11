"""Apply proposed merges and the section 6 rule 4 to merged controls. Read-only on runs.

    python scripts/apply_control_merges.py --candidates-dir <dir> --set-name heldout-v1 \
        --out docs/CONTROL_MERGES_PROPOSED.md

Inputs per workflow: controls_<wf>.json (the 307 candidates) and merges_<wf>.json
(merge proposals under the author's rule, docs/CONTROL_MERGE_RULE.md, made by
LLM-assisted reading). PROPOSALS ONLY: the author approves the HIGH merges in
bulk and decides each LOW case.

Mechanical checks, with no judgement in this script:
    partition   every candidate is a member of exactly one proposed control
    council     a merged control is present in a council run if any member has a
                verified marker there (same check as assemble_control_candidates.py)
    baseline    fails baseline if any member has a verified baseline marker, or if
                a baseline-equivalence quote is found verbatim in the named baseline
                run's tss.json. Unverifiable equivalence claims are not counted and
                are listed among the LOW cases.
    PASS        council >= ceil(0.6 n) and baseline = 0   (pre-registered)
    STRICT-75   council >= ceil(0.75 n) and baseline = 0  (exploratory)

Disagreement between passes: the candidate pass recorded verified baseline
presence (some marked "weaker" or "implied"), and the merge pass may judge it not
equivalent and leave that run out of baseline_equivalence. Such baseline runs
still count (the conservative reading), and the control is listed as a LOW case
showing the outcome without them.

For every LOW case, the outcome is computed both ways (as proposed, and with the
merge undone or the equivalence evidence dropped), so the effect of each decision
is visible.
"""

import argparse
import importlib.util
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

spec = importlib.util.spec_from_file_location(
    "assemble", REPO_ROOT / "scripts" / "assemble_control_candidates.py")
assemble = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assemble)


def outcome(council: int, baseline: int, n: int, share: float) -> str:
    if baseline > 0:
        return "FAIL-BASELINE"
    return "PASS" if council >= math.ceil(share * n) else "FAIL-THRESHOLD"


def md(text: str) -> str:
    return (text or "").replace("|", "/").replace("\n", " ")


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

    def found(run_id, step_id, field, text):
        steps = steps_of(run_id)
        if step_id in steps and assemble.contains(assemble.step_text(steps[step_id], field), text):
            return True
        return bool(assemble.contains(json.dumps(list(steps.values()), ensure_ascii=False), text)
                    or assemble.contains("\n".join(assemble.step_text(s, None) for s in steps.values()), text))

    def verified_runs(entries, allowed):
        return {p["run_id"] for p in entries or []
                if p.get("run_id") in allowed and found(p["run_id"], p.get("step_id"), p.get("field"), p.get("marker", ""))}

    summary, pass_tables, high_rows, low_rows, problems = [], [], [], [], []
    for wf in TEMPLATE_WORKFLOWS:
        council_runs, baseline_runs = cells[(wf, "council")], cells[(wf, "baseline")]
        n = len(council_runs)
        cands = {c["id"]: c for c in json.loads((args.candidates_dir / f"controls_{wf}.json").read_text())["candidates"]}
        path = args.candidates_dir / f"merges_{wf}.json"
        if not path.exists():
            problems.append(f"{wf}: no merges file")
            continue
        controls = json.loads(path.read_text())["controls"]

        members = [m for c in controls for m in c["members"]]
        missing = sorted(set(cands) - set(members))
        dup = sorted({m for m in members if members.count(m) > 1})
        unknown = sorted(set(members) - set(cands))
        if missing or dup or unknown:
            problems.append(f"{wf}: partition broken (missing {missing}, duplicated {dup}, unknown {unknown})")

        cr = {cid: verified_runs(c.get("council_present"), council_runs) for cid, c in cands.items()}
        br = {cid: verified_runs(c.get("baseline_present"), baseline_runs) for cid, c in cands.items()}

        rows, n_pass, n_strict, n_low = [], 0, 0, 0
        for ctl in controls:
            mem = [m for m in ctl["members"] if m in cands]
            council = set().union(*(cr[m] for m in mem)) if mem else set()
            base_members = set().union(*(br[m] for m in mem)) if mem else set()
            equiv_ok, equiv_bad = set(), []
            for q in ctl.get("baseline_equivalence") or []:
                if q.get("run_id") in baseline_runs and found(q["run_id"], q.get("step_id"), q.get("field"), q.get("quote", "")):
                    equiv_ok.add(q["run_id"])
                else:
                    equiv_bad.append(q)
            baseline = base_members | equiv_ok
            disputed = base_members - equiv_ok
            out = outcome(len(council), len(baseline), n, 0.60)
            strict = outcome(len(council), len(baseline), n, 0.75) == "PASS"
            roles = []
            for m in mem:
                for r in (cands[m].get("attribution") or {}).get("roles") or []:
                    if r not in roles:
                        roles.append(r)
            ev = next(iter(ctl.get("baseline_equivalence") or []), None)

            low_reasons = []
            if ctl.get("confidence") == "LOW":
                separate = [f"{m} {outcome(len(cr[m]), len(br[m] | equiv_ok), n, 0.60)} ({len(cr[m])}/{n})" for m in mem]
                low_reasons.append(f"merge: {md(ctl.get('low_reason'))}. Merged → {out} ({len(council)}/{n}); "
                                   f"members alone → {'; '.join(separate)}")
            if ctl.get("baseline_confidence") == "LOW":
                alt = outcome(len(council), len(base_members), n, 0.60)
                low_reasons.append(f"baseline equivalence: {md(ctl.get('baseline_low_reason'))}. With the evidence → "
                                   f"{out}; without it → {alt}")
            if disputed:
                alt = outcome(len(council), len(equiv_ok), n, 0.60)
                low_reasons.append(f"baseline disagreement: candidate pass found baseline presence in "
                                   f"{len(disputed)} run(s) that the merge pass did not judge equivalent. "
                                   f"Counted (conservative) → {out}; if not equivalent → {alt}")
            if equiv_bad:
                low_reasons.append(f"{len(equiv_bad)} baseline-equivalence quote(s) could not be verified and are "
                                   f"not counted, e.g. \"{md(equiv_bad[0].get('quote', ''))[:120]}\" "
                                   f"({equiv_bad[0].get('run_id')})")
            if low_reasons:
                n_low += 1
                low_rows.append(f"| {ctl['id']} | {wf} | {md(ctl.get('name'))} | {', '.join(mem)} | "
                                f"{' / '.join(low_reasons)} |")
            elif len(mem) > 1:
                high_rows.append(f"- **{ctl['id']}** ({wf}) = {' + '.join(mem)}: {md(ctl.get('reason'))}")

            if out == "PASS":
                n_pass += 1
                n_strict += strict
                rows.append(f"| {ctl['id']} | {md(ctl.get('name'))} | {', '.join(mem)} | {', '.join(roles) or '–'} | "
                            f"{len(council)}/{n} | {'yes' if strict else 'no'} | "
                            f"{'LOW: see section 3' if low_reasons else 'HIGH'} |")
        summary.append((wf, n, len(cands), len(controls), sum(1 for c in controls if len(c["members"]) > 1),
                        n_pass, n_strict, n_low))
        pass_tables.append((wf, rows))

    out = []
    add = out.append
    add("# Control merges: proposals and resulting section 6 outcomes")
    add("")
    add("**Proposals for the author's decision. Nothing has been applied to the record.** Rule: "
        "`docs/CONTROL_MERGE_RULE.md` (author's, verbatim). Merge proposals and baseline-equivalence "
        "checks were made by LLM-assisted reading, one pass per workflow. This script "
        "(`scripts/apply_control_merges.py`) checks the partition and verifies every "
        "presence marker and baseline quote against the logs, then applies the pre-registered "
        "rule (≥ 60% of council runs, zero baseline) and the exploratory STRICT-75.")
    add("")
    if problems:
        add("**Problems:** " + "; ".join(problems))
        add("")
    add("## 1. Summary")
    add("")
    add("| Workflow | Council n | Candidates | Proposed controls | of which merged | PASS | STRICT-75 | LOW cases |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|")
    tot = [0] * 6
    for row in summary:
        add("| " + " | ".join(str(x) for x in row) + " |")
        for i, v in enumerate(row[2:]):
            tot[i] += v
    add(f"| **Total** | | {tot[0]} | {tot[1]} | {tot[2]} | {tot[3]} | {tot[4]} | {tot[5]} |")
    add("")
    add("## 2. Final PASS controls per workflow (as proposed)")
    add("")
    for wf, rows in pass_tables:
        add(f"### {wf}")
        add("")
        if rows:
            add("| Id | Control | Members | Introducing role(s) | Council n/N | STRICT-75 | Status |")
            add("|---|---|---|---|---:|---|---|")
            out.extend(rows)
        else:
            add("No control passes.")
        add("")
    add("## 3. LOW-confidence cases (individual decisions)")
    add("")
    add("Each shows the outcome as proposed and the outcome the other way.")
    add("")
    add("| Id | Workflow | Control | Members | Decision needed |")
    add("|---|---|---|---|---|")
    out.extend(low_rows or ["| – | | | | None |"])
    add("")
    add("## 4. HIGH-confidence merges (for bulk approval)")
    add("")
    out.extend(high_rows or ["None."])
    add("")
    args.out.write_text("\n".join(out) + "\n")

    print("| Workflow | n | Candidates | Controls | Merged | PASS | STRICT-75 | LOW |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for row in summary:
        print("| " + " | ".join(str(x) for x in row) + " |")
    print(f"| Total | | {tot[0]} | {tot[1]} | {tot[2]} | {tot[3]} | {tot[4]} | {tot[5]} |")
    print("problems:", problems or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
