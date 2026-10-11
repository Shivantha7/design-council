"""Final draft of the section 6 control coding. Read-only on runs.

    python scripts/control_coding_final.py --set-name heldout-v1 --out docs/CONTROL_CODING_FINAL_DRAFT.md

Inputs, all in docs/control_coding/: controls_<wf>.json (candidates),
merges_<wf>.json (proposed controls), rejudge_<wf>.json (single-standard
presence), oneoff_resolutions.json. Rules: docs/CONTROL_MERGE_RULE.md.

Order of application:
  1. presence: the judge's call per run, counted only with a verified quote
  2. borderline calls by the author's pattern decisions:
       B1 and B5 present; B2, B3 and B4 absent
  3. one-off borderline resolutions (oneoff_resolutions.json "borderline")
  4. merges: every M1 or M2 merge question, plus the "merges" one-offs
     (union-find, so chains merge transitively). M3 and M4 stay separate.
  5. drops and splits from oneoff_resolutions.json
  6. PASS = council >= ceil(0.6 n) and baseline 0; STRICT-75 = ceil(0.75 n)

NEW one-offs carry the recommended answer in this draft. For each one, the PASS
total under the other answer is also given, so the author's confirmation is
informed. UNDECIDABLE cases use the outcome that does not pass.

Introducing role: from the members' candidate attributions. The primary role is
the first role of the lowest-numbered member. "Any role" counts every role named
by any member.
"""

import argparse
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = REPO_ROOT / "runs"
CODING = REPO_ROOT / "docs" / "control_coding"
TEMPLATE_WORKFLOWS = [
    "P2P-TWM-01", "P2P-PRE-01", "P2P-EXR-01",
    "R2R-ACR-01", "R2R-FSP-01",
    "FPA-VAR-01", "FPA-ABB-01",
]
BORDERLINE_DECISION = {"B1": True, "B5": True, "B2": False, "B3": False, "B4": False}
MERGE_PATTERNS = {"M1", "M2"}

spec = importlib.util.spec_from_file_location(
    "assemble", REPO_ROOT / "scripts" / "assemble_control_candidates.py")
assemble = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assemble)


def outcome(c, b, n, share=0.60):
    if b > 0:
        return "FAIL-BASELINE"
    return "PASS" if c >= math.ceil(share * n) else "FAIL-THRESHOLD"


def md(t):
    return (t or "").replace("|", "/").replace("\n", " ")


def build(args, override=None):
    """Return final controls. `override` flips one NEW resolution (for the alternative totals)."""
    cells = {}
    for e in map(json.loads, (args.runs_root / f"_set-{args.set_name}.ledger.jsonl").read_text().splitlines()):
        if e["event"] == "finished" and e["status"] == "ok":
            cells.setdefault((e["workflow_id"], e["condition"]), []).append(e["run_id"])
    res = json.loads((CODING / "oneoff_resolutions.json").read_text())

    steps_cache = {}

    def found(rid, step_id, field, text):
        if rid not in steps_cache:
            steps_cache[rid] = {s["step_id"]: s for s in
                                json.loads((args.runs_root / rid / "tss.json").read_text())["steps"]}
        st = steps_cache[rid]
        if step_id in st and assemble.contains(assemble.step_text(st[step_id], field), text or ""):
            return True
        return bool(assemble.contains("\n".join(assemble.step_text(s, None) for s in st.values()), text or ""))

    ctl, cand = {}, {}
    for wf in TEMPLATE_WORKFLOWS:
        council, baseline = cells[(wf, "council")], cells[(wf, "baseline")]
        for c in json.loads((CODING / f"controls_{wf}.json").read_text())["candidates"]:
            cand[c["id"]] = c
        merges = {c["id"]: c for c in json.loads((CODING / f"merges_{wf}.json").read_text())["controls"]}
        for c in json.loads((CODING / f"rejudge_{wf}.json").read_text())["controls"]:
            pres = {}
            for rid in council + baseline:
                p = c["presence"][rid]
                val = bool(p.get("present")) and found(rid, p.get("step_id"), p.get("field"), p.get("quote"))
                if p.get("borderline") and p.get("pattern") in BORDERLINE_DECISION:
                    # Absent-by-decision needs no quote. Present-by-decision needs the judge's quote.
                    want = BORDERLINE_DECISION[p["pattern"]]
                    val = want and found(rid, p.get("step_id"), p.get("field"), p.get("quote"))
                pres[rid] = val
            ctl[c["id"]] = {"wf": wf, "name": merges[c["id"]]["name"], "members": list(merges[c["id"]]["members"]),
                            "pres": pres, "council": council, "baseline": baseline,
                            "merge_low": c.get("merge_low"), "note": ""}

    def short(cid, r4):
        return next(r for r in ctl[cid]["pres"] if r.endswith(r4))

    for b in res["borderline"]:
        val = b["present"]
        if override == ("borderline", b["control"]):
            val = not val
        for r4 in b["runs"]:
            ctl[b["control"]]["pres"][short(b["control"], r4)] = val

    # Union-find merges.
    parent = {k: k for k in ctl}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for cid, c in ctl.items():
        ml = c["merge_low"]
        if ml and ml.get("pattern") in MERGE_PATTERNS and (ml.get("alternative") or {}).get("type") == "merge_with":
            for o in ml["alternative"]["control_ids"]:
                if o in ctl:
                    union(cid, o)
    for m in res["merges"]:
        if override == ("merge", tuple(m["controls"])):
            continue
        for o in m["controls"][1:]:
            union(m["controls"][0], o)

    for d in res["drops"]:
        if override != ("drop", d["control"]):
            ctl[d["control"]]["dropped"] = True

    for s in res["splits"]:
        base = ctl.pop(s["control"])
        parent.pop(s["control"])
        for new_id, member in s["into"].items():
            entry = dict(base, members=[member], name=f"{base['name']} ({member})")
            if new_id != s["carries_presence"]:
                pfile = (s.get("presence_files") or {}).get(new_id)
                if pfile:
                    judged = json.loads((CODING / pfile).read_text())["presence"]
                    pres = {r: bool(judged[r]["present"]) and found(r, judged[r]["step_id"], judged[r]["field"],
                                                                     judged[r]["quote"]) for r in base["pres"]}
                    entry = dict(entry, pres=pres, note=f"judged separately: {pfile}")
                else:
                    entry = dict(entry, pres={r: False for r in base["pres"]},
                                 note="not judged under the single standard: conservative, not pass")
            ctl[new_id] = entry
            parent[new_id] = new_id

    final = {}
    for cid in ctl:
        if ctl[cid].get("dropped"):
            continue
        root = find(cid)
        if root in final:
            f = final[root]
            f["ids"].append(cid)
            f["members"] += ctl[cid]["members"]
            for r, v in ctl[cid]["pres"].items():
                f["pres"][r] = f["pres"][r] or v
        else:
            final[root] = {"ids": [cid], "wf": ctl[cid]["wf"], "name": ctl[cid]["name"],
                           "members": list(ctl[cid]["members"]), "pres": dict(ctl[cid]["pres"]),
                           "council": ctl[cid]["council"], "baseline": ctl[cid]["baseline"], "note": ctl[cid]["note"]}
    for f in final.values():
        c = sum(f["pres"][r] for r in f["council"])
        b = sum(f["pres"][r] for r in f["baseline"])
        n = len(f["council"])
        f["c"], f["b"], f["n"] = c, b, n
        f["out"] = outcome(c, b, n)
        f["strict"] = outcome(c, b, n, 0.75) == "PASS"
        mem = sorted(f["members"], key=lambda m: (m.split("-")[0], int(m.split("-C")[1][:2]) if "-C" in m else 0))
        roles = []
        for m in mem:
            for r in ((cand.get(m) or {}).get("attribution") or {}).get("roles") or []:
                if r not in roles:
                    roles.append(r)
        first = ((cand.get(mem[0]) or {}).get("attribution") or {}).get("roles") or ["unattributed"]
        f["primary"], f["roles"] = first[0], roles
    return final, res


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set-name", required=True)
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    final, res = build(args)
    total = sum(f["out"] == "PASS" for f in final.values())

    out = []
    add = out.append
    add("# Control coding: final (pre-registration section 6)")
    add("")
    add("**Final, with the author's decisions of 11 October 2026.** All pattern decisions and "
        "conventions (`docs/CONTROL_MERGE_RULE.md`) and every one-off resolution "
        "(`docs/control_coding/oneoff_resolutions.json`) are applied. The one undecidable case "
        "takes the outcome that does not pass, as confirmed by the author. Presence "
        "counts only with a verified quote. Generated by `scripts/control_coding_final.py`. "
        "Section 6 rule 4: council-attributed = present in ≥ 60% of the workflow's council runs "
        "(3 of 5, 3 of 4) and in no baseline run. STRICT-75 is exploratory.")
    add("")

    add("## 1. Council-attributed controls per workflow")
    add("")
    add("| Workflow | Council n | Final controls | PASS | STRICT-75 |")
    add("|---|---:|---:|---:|---:|")
    rows = []
    for wf in TEMPLATE_WORKFLOWS:
        fs = [f for f in final.values() if f["wf"] == wf]
        rows.append((wf, fs[0]["n"], len(fs), sum(f["out"] == "PASS" for f in fs), sum(f["strict"] for f in fs)))
        add("| " + " | ".join(map(str, rows[-1])) + " |")
    tot = [sum(r[i] for r in rows) for i in (2, 3, 4)]
    add(f"| **Total** | | {tot[0]} | {tot[1]} | {tot[2]} |")
    add("")

    add("## 2. PASS controls by introducing role (section 6 item 5)")
    add("")
    passing = [f for f in final.values() if f["out"] == "PASS"]
    prim = Counter(f["primary"] for f in passing)
    anyr = Counter(r for f in passing for r in f["roles"])
    roles = sorted(set(prim) | set(anyr), key=lambda r: (-prim[r], -anyr[r], r))
    add("| Role | PASS controls (primary role) | PASS controls naming the role at all |")
    add("|---|---:|---:|")
    role_rows = []
    for r in roles:
        role_rows.append((r, prim[r], anyr[r]))
        add(f"| {r} | {prim[r]} | {anyr[r]} |")
    add(f"| **Total** | {sum(prim.values())} | – |")
    add("")
    add("Primary role = the first role of the lowest-numbered member candidate. Where a control "
        "was proposed independently by several roles, the right-hand column counts it for each.")
    add("")

    add("## 3. PASS controls")
    add("")
    add("| Control | Workflow | Primary role | Other roles | Council n/N | STRICT-75 | Members |")
    add("|---|---|---|---|---:|---|---|")
    for f in sorted(passing, key=lambda f: (TEMPLATE_WORKFLOWS.index(f["wf"]), f["ids"][0])):
        others = ", ".join(r for r in f["roles"] if r != f["primary"]) or "–"
        add(f"| {md(f['name'])} | {f['wf']} | {f['primary']} | {others} | {f['c']}/{f['n']} | "
            f"{'yes' if f['strict'] else 'no'} | {', '.join(f['members'])} |")
    add("")

    add("## 4. One-offs decided by the author (sensitivity)")
    add("")
    add(f"Each is applied as decided (total PASS {total}). The right-hand column is a sensitivity "
        "check: the total PASS under the other answer.")
    add("")
    add("| Case | Basis | Decision applied | Detail | Total PASS under the other answer |")
    add("|---|---|---|---|---:|")
    new = []
    for b in res["borderline"]:
        if b["basis"].startswith(("AUTHOR", "UNDECIDABLE")):
            alt, _ = build(args, ("borderline", b["control"]))
            new.append((f"{b['control']} ({', '.join(b['runs'])})", b["basis"],
                        "present" if b["present"] else "absent", sum(f["out"] == "PASS" for f in alt.values())))
    for m in res["merges"]:
        if m["basis"].startswith("AUTHOR"):
            alt, _ = build(args, ("merge", tuple(m["controls"])))
            new.append((" + ".join(m["controls"]), m["basis"], "merge", sum(f["out"] == "PASS" for f in alt.values())))
    for k in res["keep_separate"]:
        if k["basis"].startswith("AUTHOR"):
            new.append((" / ".join(k["controls"]), k["basis"], "keep separate", "see note"))
    for d in res["drops"]:
        alt, _ = build(args, ("drop", d["control"]))
        new.append((d["control"], d["basis"], "drop", sum(f["out"] == "PASS" for f in alt.values())))
    for s in res["splits"]:
        new.append((s["control"], s["basis"], "split; C19 re-judged", "–"))
    for case, basis, ans, alt in new:
        head, _, detail = basis.partition(". ")
        add(f"| {case} | {md(head)} | {ans} | {md(detail) or '–'} | {alt} |")
    add("")
    add("\"See note\": merging the keep-separate pairs is not computed here. The PASS total "
        "would change only if the union crosses the threshold or picks up a baseline run.")
    add("")
    args.out.write_text("\n".join(out) + "\n")

    print("| Workflow | n | Final controls | PASS | STRICT-75 |")
    print("|---|---:|---:|---:|---:|")
    for r in rows:
        print("| " + " | ".join(map(str, r)) + " |")
    print(f"| Total | | {tot[0]} | {tot[1]} | {tot[2]} |")
    print()
    print("| Role | PASS (primary) | PASS (any role) |")
    print("|---|---:|---:|")
    for r in role_rows:
        print(f"| {r[0]} | {r[1]} | {r[2]} |")
    print(f"\nAuthor-decided one-offs applied: {len(new)}; total PASS {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
