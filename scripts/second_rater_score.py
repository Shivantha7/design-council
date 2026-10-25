"""Score the returned second-rater answer sheet against the author's coding.

Usage: python3 scripts/second_rater_score.py [path/to/returned.xlsx]

Reports, per workflow and pooled:
  - raw agreement and Cohen's kappa (Present vs not-Present; rater Borderline counted as not-Present,
    matching how the author's borderline calls were resolved before the rule was applied)
  - the same with Borderline cells excluded
  - section 6 rule 4 re-applied to the rater's coding (>= 60% of council runs, no baseline run):
    how many of the author's PASS controls the rater also passes, and any new passes
Writes docs/second_rater/agreement.json for the dissertation tables.
"""
import json, sys
from pathlib import Path
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "second_rater"
sheet = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "Second_Rater_Answer_Sheet.xlsx"
final = json.load(open(ROOT / "export/results/governance_controls.json"))["controls"]
outcome = {x["control_id"]: x["outcome"] for x in final}

def kappa(pairs):
    n = len(pairs)
    if n == 0: return float("nan"), float("nan")
    po = sum(1 for a, b in pairs if a == b) / n
    pa = sum(1 for a, _ in pairs if a) / n; pb = sum(1 for _, b in pairs if b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return po, (po - pe) / (1 - pe) if pe < 1 else float("nan")

wb = load_workbook(sheet)
report = {}; pooled = []; pooled_strict = []
for keyfile in sorted(OUT.glob("KEY_*.json")):
    key = json.load(open(keyfile)); wf = key["workflow_id"]
    ws = wb[wf]
    hdr = [c.value for c in ws[1]]
    cols = {h.split()[-1]: i for i, h in enumerate(hdr) if h and h.startswith("Design ")}
    rater = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None: continue
        rater[int(row[0])] = {L: (row[i] or "").strip() if isinstance(row[i], str) else "" for L, i in cols.items()}
    pairs, strict, missing = [], [], 0
    rater_pass, author_pass, new_pass = [], [], []
    for c in key["controls"]:
        n, cid = c["n"], c["id"]
        council = [rid for rid in c["author"] if "-council-" in rid]
        base = [rid for rid in c["author"] if "-baseline-" in rid]
        r_present = {}
        for L, rid in key["key"].items():
            ans = rater.get(n, {}).get(L, "")
            if ans == "": missing += 1; continue
            a = bool(c["author"][rid]["present"]); b = ans == "Present"
            pairs.append((a, b)); pooled.append((a, b))
            if ans != "Borderline": strict.append((a, b)); pooled_strict.append((a, b))
            r_present[rid] = b
        if r_present:
            cp = sum(r_present.get(r, False) for r in council); bp = sum(r_present.get(r, False) for r in base)
            passes = cp >= 0.6 * len(council) and bp == 0
            if outcome[cid] == "PASS": author_pass.append(cid); rater_pass += [cid] if passes else []
            elif passes: new_pass.append(cid)
    po, k = kappa(pairs); po_s, k_s = kappa(strict)
    report[wf] = {"cells": len(pairs), "missing": missing, "agreement": round(po, 3), "kappa": round(k, 3),
                  "agreement_excl_borderline": round(po_s, 3), "kappa_excl_borderline": round(k_s, 3),
                  "author_pass": len(author_pass), "rater_confirms_pass": len(rater_pass),
                  "rater_new_pass": new_pass, "author_pass_not_confirmed": sorted(set(author_pass) - set(rater_pass))}
po, k = kappa(pooled); po_s, k_s = kappa(pooled_strict)
report["pooled"] = {"cells": len(pooled), "agreement": round(po, 3), "kappa": round(k, 3),
                    "agreement_excl_borderline": round(po_s, 3), "kappa_excl_borderline": round(k_s, 3)}
json.dump(report, open(OUT / "agreement.json", "w"), indent=1)
print(json.dumps(report, indent=1))
