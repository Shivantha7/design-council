"""Standards citations in the held-out set (X.6). Descriptive. Read-only.

    python scripts/standards_heldout.py --set-name heldout-v1 [--out docs/RESULTS_HELDOUT_standards.md]

Per workflow x condition, over the completed runs in the set's ledger:

    TSS citations   distinct KB principle ids (KB-01 .. KB-14) appearing anywhere
                    in tss.json (step text and disposition rationales). Union over
                    the cell's runs, plus the mean count per run.
    AS citations    council only: distinct KB ids in the Accounting Standards
                    role's own contributions (round1_ and round2_accounting_standards,
                    attempt_status ok). Union and mean per run. The baseline has
                    no such role, so n/a.
    silences        council only: sentences in the Accounting Standards
                    contributions that declare the knowledge base silent, matched
                    by SILENCE_PATTERN below. Reported as the number of runs with
                    at least one declaration, plus every matching sentence, so the
                    author can judge each one. The pattern is a search aid, not a
                    coding decision.

Ids are matched by the regex KB-\\d\\d and kept only if they exist in the KB, so a
malformed or invented id is reported separately rather than counted.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from design_council.kb.loader import load_kb  # noqa: E402

RUNS_ROOT = REPO_ROOT / "runs"
TEMPLATE_WORKFLOWS = [
    "P2P-TWM-01", "P2P-PRE-01", "P2P-EXR-01",
    "R2R-ACR-01", "R2R-FSP-01",
    "FPA-VAR-01", "FPA-ABB-01",
]
CONDITIONS = ["council", "baseline"]
AS_ROLES = {"round1_accounting_standards", "round2_accounting_standards"}
KB_ID = re.compile(r"KB-\d\d")
SILENCE_PATTERN = re.compile(
    r"\b(silent|silence|is thin on|no (?:matching |relevant )?(?:KB|knowledge[- ]base) "
    r"(?:entry|entries|principle|principles|coverage)|not covered by the (?:KB|knowledge base)|"
    r"(?:KB|knowledge base) does not (?:cover|address))\b",
    re.IGNORECASE,
)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set-name", required=True)
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    known = {entry.id for entry in load_kb().entries}
    ledger = args.runs_root / f"_set-{args.set_name}.ledger.jsonl"
    events = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]

    cells: dict[tuple[str, str], list[str]] = {}
    for e in events:
        if e["event"] == "finished" and e["status"] == "ok":
            cells.setdefault((e["workflow_id"], e["condition"]), []).append(e["run_id"])

    rows, silence_rows, unknown_ids = [], [], []
    for wf in TEMPLATE_WORKFLOWS:
        for cond in CONDITIONS:
            tss_sets, as_sets, silence_runs = [], [], 0
            for run_id in cells.get((wf, cond), []):
                run_dir = args.runs_root / run_id
                found = set(KB_ID.findall((run_dir / "tss.json").read_text()))
                unknown_ids += [(run_id, "tss", i) for i in sorted(found - known)]
                tss_sets.append(found & known)
                if cond == "council":
                    text = "\n".join(
                        r["raw_completion"] or ""
                        for r in map(json.loads, (run_dir / "calls.jsonl").read_text().splitlines())
                        if r["agent_role"] in AS_ROLES and r.get("attempt_status", "ok") == "ok"
                    )
                    found = set(KB_ID.findall(text))
                    unknown_ids += [(run_id, "AS", i) for i in sorted(found - known)]
                    as_sets.append(found & known)
                    hits = [s for s in sentences(text) if SILENCE_PATTERN.search(s)]
                    if hits:
                        silence_runs += 1
                    silence_rows += [(wf, run_id, s) for s in hits]

            tss_union = sorted(set().union(*tss_sets)) if tss_sets else []
            row = (f"| {wf} | {cond} | {len(tss_sets)} | {len(tss_union)} | "
                   f"{mean(len(s) for s in tss_sets):.1f} | {', '.join(tss_union) or '–'} | ")
            if cond == "council":
                as_union = sorted(set().union(*as_sets))
                row += (f"{len(as_union)} | {mean(len(s) for s in as_sets):.1f} | "
                        f"{', '.join(as_union) or '–'} | {silence_runs} of {len(as_sets)} |")
            else:
                row += "n/a | n/a | n/a | n/a |"
            rows.append(row)

    out = []
    add = out.append
    add(f"# Held-out standards citations (X.6): set `{args.set_name}`")
    add("")
    add("Generated by `scripts/standards_heldout.py` from the run logs. Descriptive. "
        "Distinct ids are counted against the 14-entry KB. \"AS\" means the Accounting "
        "Standards role's round 1 and round 2 contributions. The baseline has no such "
        "role. Silence declarations are pattern matches for the author to judge, not "
        "coded findings.")
    add("")
    add("**Caveats for X.6.** (1) An id counts as cited wherever it is mentioned, "
        "including where the role names an entry to rule it out (e.g. \"KB-04, KB-10, "
        "KB-12 are not engaged\"), so the AS counts are an upper bound on substantive "
        "citation. Telling the two apart is a coding judgement. (2) The silence pattern "
        "also matches non-declarations (e.g. \"not a silent auto-correction\"). Each "
        "listed sentence needs the author's reading.")
    add("")
    add("| Workflow | Condition | Runs | TSS distinct KB (union) | TSS KB per run (mean) "
        "| TSS ids | AS distinct KB (union) | AS KB per run (mean) | AS ids "
        "| Runs with a declared silence |")
    add("|---|---|---:|---:|---:|---|---:|---:|---|---|")
    out += rows
    add("")
    add("## Declared-silence sentences (Accounting Standards role, council runs)")
    add("")
    if silence_rows:
        add("| Workflow | Run | Sentence |")
        add("|---|---|---|")
        for wf, run_id, s in silence_rows:
            add(f"| {wf} | {run_id} | {s.replace('|', '/')[:400]} |")
    else:
        add("No sentence matched the silence pattern.")
    add("")
    add("## Ids not in the KB")
    add("")
    add("None." if not unknown_ids else "\n".join(f"- {r} ({w}): {i}" for r, w, i in unknown_ids))
    add("")

    text = "\n".join(out) + "\n"
    if args.out:
        args.out.write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
