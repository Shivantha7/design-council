"""Held-out results tables, as markdown, from the held-out run logs. Read-only.

    python scripts/analyse_heldout.py --set-name heldout-v2 [--out results.md]

DO NOT RUN until the held-out grid has completed. Pre-registration section 3:
no held-out output is inspected for content until every cell has stopped. The
script enforces this. If any cell has not stopped, it prints only how many
cells are outstanding and exits without reading any run's content.

Produces, in the layout of docs/RESULTS_TEMPLATE_HELDOUT.md:

    Table X.1  Run completion by cell
    Table X.2  Conformance failures (only when Branch B applies; otherwise the
               Branch A statement)
    Table X.3  Mean depth by workflow and condition, with the SESOI row
    Table X.4  Disposition counts by condition (all runs)
    Table X.5  Cumulative mean depth after runs 3, 4 and 5, with stabilisation

followed by the mechanical [##] fill-in values for sections X.1 to X.4, and
Table X.5s, the pre-registration section 5 supplementary table (cumulative mean
and range of depth and consistency per cell after runs 3, 4 and 5).

Definitions, all from docs/PREREGISTRATION_HELDOUT.md:
    depth         (eliminated + merged + absorbed + restructured) / steps, from
                  each tss.json disposition mapping. Held as an exact
                  fraction, so the SESOI test (gap >= 0.2) is never decided by
                  floating-point rounding.
    cell mean     over all runs in the cell, n = 4 or n = 5 (section 5).
    stabilised    run 4 depth == run 3 depth (stopped at 4), or run 5 depth ==
                  run 4 depth (section 5, H3).
    H2 supported  gap >= 0.2 on at least 4 of 7 workflows.
    H3 supported  at least 8 of 14 cells stabilised.

    consistency   mean pairwise disposition agreement: the share of baseline
                  steps given the same label in two runs, averaged over every
                  pair (section 4; design_council/measures/consistency.py,
                  the same code as scripts/measure_consistency_dev.py).

Integrity checks, which fail loudly rather than skip:
    - every run's manifest matches the ledger (workflow, condition)
    - each run's encoding sha256 matches the encoding the set was started with
    - one git commit and one (resolved_model, model_created_at) across the set
    - conformance recounted from per-requirement results equals the logged score
    - the set's workflows are exactly the seven named in the template
"""

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from design_council.measures.consistency import pairwise_agreements  # noqa: E402
from design_council.measures.depth import measure_depth  # noqa: E402
from design_council.run_logging import sha256_file  # noqa: E402
from design_council.schemas import (  # noqa: E402
    Disposition,
    GateResult,
    TargetStateSpec,
    WorkflowEncoding,
)

RUNS_ROOT = REPO_ROOT / "runs"

# Row order of every per-workflow table in RESULTS_TEMPLATE_HELDOUT.md.
TEMPLATE_WORKFLOWS = [
    "P2P-TWM-01", "P2P-PRE-01", "P2P-EXR-01",
    "R2R-ACR-01", "R2R-FSP-01",
    "FPA-VAR-01", "FPA-ABB-01",
]
# Council first, as in the template's column order.
CONDITIONS = ["council", "baseline"]
# Row order of Table X.4.
DISPOSITION_ROWS = ["eliminated", "absorbed", "merged", "restructured", "retained"]

SESOI = Fraction(1, 5)          # 0.2, section 5 H2
H2_THRESHOLD = 4                # of 7 workflows
H3_THRESHOLD = 8                # of 14 cells
PREREGISTERED_OPEN_STEPS = 16   # section 1


class AnalysisIntegrityError(Exception):
    pass


# --- loading -----------------------------------------------------------------


def load_set(runs_root: Path, set_name: str) -> tuple[list[dict], dict]:
    ledger = runs_root / f"_set-{set_name}.ledger.jsonl"
    if not ledger.exists():
        raise AnalysisIntegrityError(f"no ledger at {ledger}")
    events = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    started = next((e for e in events if e["event"] == "set_started"), None)
    if started is None:
        raise AnalysisIntegrityError("ledger has no set_started event")
    return events, started


def ok_runs(events: list[dict]) -> dict[tuple[str, str], dict[int, str]]:
    """(workflow_id, condition) -> {rep: run_id} for runs that reached the gate."""
    cells: dict[tuple[str, str], dict[int, str]] = {}
    for e in events:
        if e["event"] == "finished" and e["status"] == "ok":
            reps = cells.setdefault((e["workflow_id"], e["condition"]), {})
            if e["rep"] in reps:
                raise AnalysisIntegrityError(
                    f"two completed runs recorded for {e['workflow_id']} "
                    f"{e['condition']} rep {e['rep']}: {reps[e['rep']]}, {e['run_id']}"
                )
            reps[e["rep"]] = e["run_id"]
    return cells


def stop_decisions(events: list[dict]) -> dict[tuple[str, str], str]:
    return {
        (e["workflow_id"], e["condition"]): e["decision"]
        for e in events
        if e["event"] == "stop_rule"
    }


def cell_status(reps: dict[int, str], decision: str | None) -> str | None:
    """None if the cell stopped validly; otherwise why it has not."""
    n = len(reps)
    if sorted(reps) != list(range(1, n + 1)):
        return f"reps {sorted(reps)} are not 1..{n}"
    if decision == "complete_at_n4" and n == 4:
        return None
    if decision == "run_5" and n == 5:
        return None
    return f"n={n}, stopping-rule decision {decision!r}"


class Run:
    """One completed run, read from its directory and checked."""

    def __init__(self, run_dir: Path, encoding: WorkflowEncoding, encoding_sha: str,
                 workflow_id: str, condition: str):
        manifest = json.loads((run_dir / "run_manifest.json").read_text())
        if (manifest["workflow_id"], manifest["condition"]) != (workflow_id, condition):
            raise AnalysisIntegrityError(f"{run_dir.name}: manifest disagrees with ledger")
        if manifest["encoding_sha256"] != encoding_sha:
            raise AnalysisIntegrityError(f"{run_dir.name}: encoding sha256 differs from the set's")

        self.run_id = run_dir.name
        self.commit = manifest["git_commit"]
        self.model = (manifest["resolved_model"], manifest["model_created_at"])
        self.tss = TargetStateSpec.model_validate_json((run_dir / "tss.json").read_text())
        self.gate = GateResult.model_validate_json((run_dir / "gate_result.json").read_text())

        # Depth as an exact fraction, checked against the shared measure.
        steps = encoding.step_ids()
        not_retained = sum(
            1 for s in steps if self.tss.disposition_for(s) is not Disposition.RETAINED
        )
        self.depth = Fraction(not_retained, len(steps))
        logged = measure_depth(encoding, self.tss).depth_score
        if float(self.depth) != logged:
            raise AnalysisIntegrityError(
                f"{self.run_id}: exact depth {self.depth} != measure_depth {logged}"
            )

        passed = sum(1 for r in self.gate.results if r.passed)
        self.passed, self.total = passed, len(self.gate.results)
        if Fraction(passed, self.total) != Fraction(self.gate.conformance_score).limit_denominator(1000):
            raise AnalysisIntegrityError(
                f"{self.run_id}: {passed}/{self.total} passed but conformance_score "
                f"{self.gate.conformance_score}"
            )
        self.failed = self.gate.failed_requirement_ids()
        self.dispositions = {s: self.tss.disposition_for(s).value for s in steps}
        self.step_ids = steps


# --- measures ----------------------------------------------------------------


def pairwise(runs: list[Run]) -> list[float]:
    return pairwise_agreements([r.tss for r in runs], runs[0].step_ids)


def fmean(values: list[Fraction]) -> Fraction:
    return sum(values, Fraction(0)) / len(values)


def d3(x) -> str:
    return f"{float(x):.3f}"


def mean_range(values: list) -> str:
    return f"{d3(fmean(values) if isinstance(values[0], Fraction) else mean(values))} " \
           f"({d3(min(values))}–{d3(max(values))})"


def stabilisation(runs: list[Run]) -> str:
    if len(runs) == 4:
        return "Yes (stopped at 4)" if runs[3].depth == runs[2].depth else "No (n=4 without stop)"
    return "Yes (run 5 = run 4)" if runs[4].depth == runs[3].depth else "No (run 5 ≠ run 4)"


# --- report ------------------------------------------------------------------


def build_report(set_name: str, started: dict, encodings: dict, grid: dict,
                 decisions: dict, deviations: list[str], events: list[dict]) -> list[str]:
    out = []
    add = out.append

    all_runs = [r for runs in grid.values() for r in runs]
    commit = all_runs[0].commit
    model = all_runs[0].model

    add(f"# Held-out results tables: set `{set_name}`")
    add("")
    add(f"Generated by `scripts/analyse_heldout.py` from the run logs. Commit `{commit}`; "
        f"model `{model[0]}` (provider created_at {model[1]}); {len(all_runs)} runs. "
        "Layout per `docs/RESULTS_TEMPLATE_HELDOUT.md`.")
    add("")

    # X.1
    add("## X.1 Run completion and stopping")
    add("")
    add("Table X.1 Run completion by cell")
    add("")
    add("| Workflow | Council n | Council stopped at 4? | Baseline n | Baseline stopped at 4? |")
    add("|---|---|---|---|---|")
    for wf in TEMPLATE_WORKFLOWS:
        cols = []
        for cond in CONDITIONS:
            cols.append(str(len(grid[(wf, cond)])))
            cols.append("Yes" if decisions.get((wf, cond)) == "complete_at_n4" else "No")
        add(f"| {wf} | " + " | ".join(cols) + " |")
    add("")

    # X.2
    failures = [(r, wf, cond) for (wf, cond), runs in grid.items() for r in runs if r.failed]
    order = {wf: i for i, wf in enumerate(TEMPLATE_WORKFLOWS)}
    failures.sort(key=lambda x: (order[x[1]], CONDITIONS.index(x[2]), x[0].run_id))
    add("## X.2 Rule conformance (H1)")
    add("")
    if not failures:
        add("BRANCH A applies: conformance was 1.0 in every run in both conditions. "
            "Table X.2 is not produced.")
    else:
        add("BRANCH B applies.")
        add("")
        add("Table X.2 Conformance failures (only if Branch B)")
        add("")
        add("| Run | Condition | Workflow | Score | Rules failed |")
        add("|---|---|---|---|---|")
        for r, wf, cond in failures:
            add(f"| {r.run_id} | {cond.capitalize()} | {wf} | "
                f"{r.passed / r.total:.3f} ({r.passed}/{r.total}) | {', '.join(r.failed)} |")
    add("")

    # X.3
    gaps = {}
    add("## X.3 Transformation depth (H2)")
    add("")
    add("Table X.3 Mean depth by workflow and condition")
    add("")
    add("| Workflow | Council mean (range) | Baseline mean (range) | Gap | Gap >= 0.2? |")
    add("|---|---|---|---|---|")
    for wf in TEMPLATE_WORKFLOWS:
        council = [r.depth for r in grid[(wf, "council")]]
        baseline = [r.depth for r in grid[(wf, "baseline")]]
        gap = fmean(council) - fmean(baseline)
        gaps[wf] = gap
        add(f"| {wf} | {mean_range(council)} | {mean_range(baseline)} | "
            f"{float(gap):+.3f} | {'Yes' if gap >= SESOI else 'No'} |")
    meeting = sum(1 for g in gaps.values() if g >= SESOI)
    add(f"| Workflows meeting SESOI | | | | {meeting} of 7 |")
    add("")

    # X.4
    counts = {c: {d: 0 for d in DISPOSITION_ROWS} for c in CONDITIONS}
    open_hits = {c: set() for c in CONDITIONS}
    open_events = {c: 0 for c in CONDITIONS}
    for (wf, cond), runs in grid.items():
        open_steps = set(encodings[wf].unconstrained_by_design)
        for r in runs:
            for step, disposition in r.dispositions.items():
                counts[cond][disposition] += 1
                if step in open_steps and disposition in ("eliminated", "absorbed"):
                    open_hits[cond].add((wf, step))
                    open_events[cond] += 1
    add("### Dispositions and elimination")
    add("")
    add("Table X.4 Disposition counts by condition (all runs)")
    add("")
    add("| Disposition | Council | Baseline |")
    add("|---|---|---|")
    for d in DISPOSITION_ROWS:
        add(f"| {d.capitalize()} | {counts['council'][d]} | {counts['baseline'][d]} |")
    add("")

    # X.5
    add("## X.4 Stabilisation (H3)")
    add("")
    add("Table X.5 Cumulative mean depth after runs 3, 4 and 5")
    add("")
    add("| Cell | After run 3 | After run 4 | After run 5 | Stabilised? |")
    add("|---|---|---|---|---|")
    stab = {}
    for wf in TEMPLATE_WORKFLOWS:
        for cond in CONDITIONS:
            runs = grid[(wf, cond)]
            depths = [r.depth for r in runs]
            after5 = d3(fmean(depths[:5])) if len(runs) == 5 else "–"
            stab[(wf, cond)] = stabilisation(runs)
            add(f"| {wf} {cond} | {d3(fmean(depths[:3]))} | {d3(fmean(depths[:4]))} | "
                f"{after5} | {stab[(wf, cond)]} |")
    add("")

    # Fill-ins
    open_total = sum(len(e.unconstrained_by_design) for e in encodings.values())
    stopped4 = sum(1 for d in decisions.values() if d == "complete_at_n4")
    fifth = sum(1 for runs in grid.values() if len(runs) == 5)
    stabilised = sum(1 for s in stab.values() if s.startswith("Yes"))
    settled5 = sum(1 for s in stab.values() if s == "Yes (run 5 = run 4)")
    consistency = {
        cond: mean(mean(pairwise(grid[(wf, cond)])) for wf in TEMPLATE_WORKFLOWS)
        for cond in CONDITIONS
    }
    largest = max(gaps, key=lambda w: gaps[w])
    smallest = min(gaps, key=lambda w: gaps[w])
    gated_nonzero = [e["run_id"] for e in events
                     if e["event"] == "finished" and e.get("gated_nonzero_exit")]

    add("## Fill-in values for the template's [##] markers")
    add("")
    add("**X.1**")
    add(f"- Cells stopped at four runs: {stopped4}")
    add(f"- Cells that received a fifth run: {fifth}")
    add(f"- Total runs: {len(all_runs)} (pre-registered bound 56 to 70)")
    add(f"- Deviations: {'; '.join(deviations) if deviations else 'none recorded'}")
    if gated_nonzero:
        add(f"- Gated runs with a non-zero exit (kept, per section 3): {', '.join(gated_nonzero)}")
    add("")
    add("**X.2**")
    if failures:
        add(f"- Runs below 1.0: {len(failures)} "
            f"({sum(1 for f in failures if f[2] == 'council')} council, "
            f"{sum(1 for f in failures if f[2] == 'baseline')} baseline)")
    else:
        add("- Runs below 1.0: 0 (Branch A)")
    add("")
    add("**X.3**")
    add(f"- Workflows with gap >= 0.2: {meeting} of 7. Threshold {H2_THRESHOLD}. "
        f"{'BRANCH A (H2 supported)' if meeting >= H2_THRESHOLD else 'BRANCH B (H2 not supported)'}")
    add(f"- Largest gap: {largest} ({float(gaps[largest]):+.3f}); "
        f"smallest gap: {smallest} ({float(gaps[smallest]):+.3f})")
    add(f"- Open steps in the encodings: {open_total} "
        f"({'matches' if open_total == PREREGISTERED_OPEN_STEPS else 'DOES NOT MATCH'} "
        f"the pre-registered {PREREGISTERED_OPEN_STEPS})")
    add(f"- Distinct open steps eliminated or absorbed in at least one run: "
        f"council {len(open_hits['council'])}, baseline {len(open_hits['baseline'])} "
        f"(disposition events on open steps: council {open_events['council']}, "
        f"baseline {open_events['baseline']})")
    if not open_hits["council"] and not open_hits["baseline"]:
        add("- IF ZERO paragraph applies")
    add("- Per cell (pre-registration section 5), distinct open steps eliminated or "
        "absorbed in at least one run:")
    for wf in TEMPLATE_WORKFLOWS:
        open_steps = encodings[wf].unconstrained_by_design
        for cond in CONDITIONS:
            hits = sorted(s for s in open_steps if any(
                r.dispositions[s] in ("eliminated", "absorbed") for r in grid[(wf, cond)]))
            add(f"  - {wf} {cond}: {len(hits)} of {len(open_steps)} open"
                + (f" ({', '.join(hits)})" if hits else ""))
    add("")
    add("**X.4**")
    add(f"- Stabilised cells: {stabilised} of 14 ({stopped4} stopped at run 4; "
        f"{settled5} had run 5 equal to run 4). Threshold {H3_THRESHOLD}: "
        f"{'supported' if stabilised >= H3_THRESHOLD else 'not supported'}")
    add(f"- Consistency, council vs baseline (mean of cell consistencies): "
        f"{consistency['council']:.3f} vs {consistency['baseline']:.3f}. Development "
        "pattern for comparison: `python scripts/measure_consistency_dev.py`")
    add("")

    # Supplementary, section 5
    add("## Supplementary")
    add("")
    add("Table X.5s Cumulative mean and range of depth and consistency per cell "
        "(pre-registration section 5)")
    add("")
    add("Consistency: mean (range) of pairwise disposition agreement over the "
        "k(k-1)/2 run pairs among runs 1..k.")
    add("")
    add("| Cell | After run | Depth mean (range) | Consistency mean (range) |")
    add("|---|---|---|---|")
    for wf in TEMPLATE_WORKFLOWS:
        for cond in CONDITIONS:
            runs = grid[(wf, cond)]
            for k in (3, 4, 5):
                if len(runs) < k:
                    add(f"| {wf} {cond} | {k} | complete at n=4 (stopping rule) | – |")
                    continue
                add(f"| {wf} {cond} | {k} | {mean_range([r.depth for r in runs[:k]])} | "
                    f"{mean_range(pairwise(runs[:k]))} |")
    add("")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set-name", required=True)
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--out", type=Path, default=None,
                        help="write the markdown here instead of stdout")
    parser.add_argument("--accept-deviations", action="store_true",
                        help="produce tables although some cell did not stop validly; "
                             "every such cell is listed as a deviation (section 7)")
    args = parser.parse_args()

    events, started = load_set(args.runs_root, args.set_name)
    cells = ok_runs(events)
    decisions = stop_decisions(events)

    if set(started["workflows"]) != set(TEMPLATE_WORKFLOWS):
        raise AnalysisIntegrityError(
            f"set workflows {sorted(started['workflows'])} are not the seven in the template"
        )

    # Completion check first: nothing below reads run content until every cell
    # has stopped (pre-registration section 3).
    problems = {}
    for wf in TEMPLATE_WORKFLOWS:
        for cond in CONDITIONS:
            status = cell_status(cells.get((wf, cond), {}), decisions.get((wf, cond)))
            if status:
                problems[(wf, cond)] = status
    if problems and not args.accept_deviations:
        print(f"{len(problems)} of 14 cells have not stopped. Not producing any output "
              f"(pre-registration section 3). Re-run after the grid completes.",
              file=sys.stderr)
        return 1
    deviations = [f"{wf} {cond}: {why}" for (wf, cond), why in sorted(problems.items())]

    encodings, shas = {}, {}
    for wf, path in started["workflows"].items():
        path = REPO_ROOT / path
        encodings[wf] = WorkflowEncoding.model_validate(json.loads(path.read_text()))
        shas[wf] = sha256_file(path)

    grid = {}
    for wf in TEMPLATE_WORKFLOWS:
        for cond in CONDITIONS:
            reps = cells.get((wf, cond), {})
            grid[(wf, cond)] = [
                Run(args.runs_root / reps[k], encodings[wf], shas[wf], wf, cond)
                for k in sorted(reps)
            ]
            if len(grid[(wf, cond)]) < 3:
                raise AnalysisIntegrityError(f"{wf} {cond}: fewer than 3 runs; cannot tabulate")

    all_runs = [r for runs in grid.values() for r in runs]
    if len({r.commit for r in all_runs}) > 1:
        raise AnalysisIntegrityError(f"set spans commits {sorted({r.commit for r in all_runs})}")
    if len({r.model for r in all_runs}) > 1:
        raise AnalysisIntegrityError(f"set spans models {sorted({r.model for r in all_runs})}")

    text = "\n".join(build_report(args.set_name, started, encodings, grid,
                                  decisions, deviations, events)) + "\n"
    if args.out:
        args.out.write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AnalysisIntegrityError as error:
        print(f"AnalysisIntegrityError: {error}", file=sys.stderr)
        sys.exit(1)
