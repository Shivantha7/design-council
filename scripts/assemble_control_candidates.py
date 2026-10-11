"""Verify and assemble governance-control CANDIDATES for pre-registration section 6. Read-only.

    python scripts/assemble_control_candidates.py --candidates-dir <dir> --set-name heldout-v1 \
        --out docs/CONTROL_CODING_CANDIDATES.md

Input: one controls_<workflow_id>.json per held-out workflow, produced by
LLM-assisted reading of the council and baseline TSSs and transcripts. They are
candidates only. Every coding decision belongs to the author (section 6).

This script makes no model calls. It checks each candidate mechanically against
the run logs, and nothing unverified is counted:

    attribution quote   must be a substring of the named call's raw_completion
                        (named run, named agent_role, attempt_status ok). Exact
                        match first. A match after collapsing whitespace is
                        accepted and labelled. Otherwise the quote is UNVERIFIED.
    presence markers    each must be a substring of the named run's tss.json
                        steps, in the named step and field (exact, then
                        whitespace-collapsed). A marker found elsewhere in the
                        run's steps is accepted and labelled. Otherwise UNVERIFIED,
                        and that presence is not counted.
    run ids             must belong to the workflow and condition claimed,
                        per the set's ledger.

Presence counts are of runs with at least one verified marker. The section 6
threshold (>= 60% of council runs and no baseline run) is NOT applied here.
"""

import argparse
import json
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
DEV_PACKS = ["P2P-VIP-01", "R2R-PC-01", "FPA-RF-01"]


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def contains(haystack: str, needle: str) -> str | None:
    if needle and needle in haystack:
        return "exact"
    if needle and squash(needle) in squash(haystack):
        return "whitespace-normalised"
    return None


def step_text(step: dict, field: str | None) -> str:
    if field in ("inputs", "outputs"):
        return "\n".join(step.get(field) or [])
    if field in ("name", "description", "actor"):
        return step.get(field) or ""
    return json.dumps(step, ensure_ascii=False)


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

    ledger = args.runs_root / f"_set-{args.set_name}.ledger.jsonl"
    cells: dict[tuple[str, str], list[str]] = {}
    for e in map(json.loads, ledger.read_text().splitlines()):
        if e["event"] == "finished" and e["status"] == "ok":
            cells.setdefault((e["workflow_id"], e["condition"]), []).append(e["run_id"])

    tss_cache, calls_cache = {}, {}

    def tss_steps(run_id):
        if run_id not in tss_cache:
            tss_cache[run_id] = {s["step_id"]: s for s in
                                 json.loads((args.runs_root / run_id / "tss.json").read_text())["steps"]}
        return tss_cache[run_id]

    def completion(run_id, role):
        key = (run_id, role)
        if key not in calls_cache:
            texts = [r["raw_completion"] or "" for r in
                     map(json.loads, (args.runs_root / run_id / "calls.jsonl").read_text().splitlines())
                     if r["agent_role"] == role and r.get("attempt_status", "ok") == "ok"]
            calls_cache[key] = "\n".join(texts)
        return calls_cache[key]

    out = []
    add = out.append
    add("# Governance-control coding candidates (pre-registration section 6)")
    add("")
    add("**Candidates only. Every coding decision is the author's.** Produced by "
        "LLM-assisted reading of the held-out council and baseline TSSs and council "
        "transcripts, then checked mechanically by `scripts/assemble_control_candidates.py`. "
        "Every attribution quote and presence marker shown as verified is an exact (or "
        "whitespace-normalised) substring of the cited log. Unverified items are shown and "
        "flagged but not counted. The section 6 threshold (≥ 60% of council runs and no "
        "baseline run) is **not** applied. The counts are given so the author can apply it.")
    add("")

    add("## Codebook seed: development-phase controls")
    add("")
    add("Pre-registration section 6 says \"the ten controls found in the development "
        "phase\". The dev review packs record ten per workflow (30 in all). **Ambiguity "
        "for the author:** the dev-grid handoff and DRAFT4 attach \"ten role-attributed "
        "controls absent from every baseline\" to R2R-PC-01, which suggests those ten are "
        "the referent. All 30 are listed, and candidate matches below may cite any of them.")
    add("")
    add("| Dev workflow | Control | Roles (dev pack) | KB |")
    add("|---|---|---|---|")
    for wf in DEV_PACKS:
        pack = json.loads((REPO_ROOT / "data" / "review_packs" / f"{wf}.json").read_text())
        for c in pack["controls"]:
            tag = " *(likely \"the ten\")*" if wf == "R2R-PC-01" else ""
            add(f"| {wf}{tag} | {md(c['title'])} | {', '.join(c['roles'])} | {', '.join(c['kb']) or '–'} |")
    add("")

    summary_rows, detail = [], []
    problems = []
    for wf in TEMPLATE_WORKFLOWS:
        path = args.candidates_dir / f"controls_{wf}.json"
        council_runs, baseline_runs = cells[(wf, "council")], cells[(wf, "baseline")]
        if not path.exists():
            problems.append(f"{wf}: no candidates file")
            continue
        data = json.loads(path.read_text())
        detail.append(f"## {wf} ({len(council_runs)} council runs, {len(baseline_runs)} baseline runs)")
        detail.append("")
        detail.append("| Id | Candidate | Category | Codebook | Introducing role(s) | Quote (run, call) "
                      "| Council present | Baseline present | Flags |")
        detail.append("|---|---|---|---|---|---|---:|---:|---|")
        evidence = []
        for c in data["candidates"]:
            flags = list(c.get("flags") or [])
            att = c.get("attribution") or {}
            quote_status = None
            if att.get("run_id") in council_runs and att.get("agent_role"):
                quote_status = contains(completion(att["run_id"], att["agent_role"]), att.get("quote", ""))
            if quote_status is None:
                flags.append("ATTRIBUTION QUOTE UNVERIFIED (not found in the cited call)")
            elif quote_status != "exact":
                flags.append(f"quote matched {quote_status}")

            counts = {}
            for cond, allowed, key in (("council", council_runs, "council_present"),
                                       ("baseline", baseline_runs, "baseline_present")):
                verified_runs = set()
                for p in c.get(key) or []:
                    rid = p.get("run_id")
                    if rid not in allowed:
                        flags.append(f"{cond} presence cites run not in this cell: {rid}")
                        continue
                    steps = tss_steps(rid)
                    status = None
                    if p.get("step_id") in steps:
                        status = contains(step_text(steps[p["step_id"]], p.get("field")), p.get("marker", ""))
                    if status is None:
                        anywhere = contains(json.dumps(list(steps.values()), ensure_ascii=False),
                                            p.get("marker", ""))
                        if anywhere is None:
                            anywhere = contains("\n".join(step_text(s, None) for s in steps.values()),
                                                p.get("marker", ""))
                        status = f"found elsewhere in TSS ({anywhere})" if anywhere else None
                    if status is None:
                        flags.append(f"{cond} marker UNVERIFIED in {rid}: \"{p.get('marker', '')[:60]}\"")
                        continue
                    verified_runs.add(rid)
                    evidence.append(f"- {c['id']} {cond} `{rid}` {p.get('step_id')}.{p.get('field')} "
                                    f"({status}): \"{md(p.get('marker', ''))}\"")
                counts[cond] = len(verified_runs)

            roles = ", ".join(att.get("roles") or []) or "–"
            q = md(att.get("quote", ""))[:300]
            detail.append(
                f"| {c['id']} | {md(c.get('title', ''))} | {c.get('category', '')} | "
                f"{md(c.get('codebook_match', ''))} | {roles} | \"{q}\" (`{att.get('run_id', '–')}`, "
                f"{att.get('agent_role', '–')}) | {counts['council']} of {len(council_runs)} | "
                f"{counts['baseline']} of {len(baseline_runs)} | {md('; '.join(flags)) or '–'} |")
            summary_rows.append((wf, c["id"], bool(flags)))
        detail.append("")
        detail.append(f"<details><summary>{wf}: verified presence markers</summary>")
        detail.append("")
        detail += evidence
        detail.append("")
        detail.append("</details>")
        detail.append("")

    add("## Summary")
    add("")
    add("| Workflow | Candidates | Flagged |")
    add("|---|---:|---:|")
    for wf in TEMPLATE_WORKFLOWS:
        rows = [r for r in summary_rows if r[0] == wf]
        add(f"| {wf} | {len(rows)} | {sum(1 for r in rows if r[2])} |")
    add("")
    if problems:
        add("Problems: " + "; ".join(problems))
        add("")
    out += detail

    args.out.write_text("\n".join(out) + "\n")
    print(f"wrote {args.out}: {len(summary_rows)} candidates, "
          f"{sum(1 for r in summary_rows if r[2])} flagged; problems: {problems or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
