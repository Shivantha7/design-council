"""Run the held-out experimental set: every workflow x both conditions, n = 4 or 5.

    python scripts/run_heldout.py --set-name heldout-v2 --prereg-tag <tag> --dry-run
    python scripts/run_heldout.py --set-name heldout-v2 --prereg-tag <tag>

Design
    Round-robin. Round k runs repetition k of every cell (workflow x condition),
    and round k+1 does not start until every cell has a completed run k. The
    cells of one round run in parallel, as separate processes.

Stopping rule (PREREGISTRATION_HELDOUT.md section 3)
    Rounds 1 to 4 run for every cell. After round 4, each cell's depth for run
    3 and run 4 is computed from the disposition mapping in tss.json, using the
    same measure_depth as every other depth figure. If the two are equal, the
    cell is complete at n=4. Otherwise run 5 is queued for that cell, and round
    5 runs only the queued cells. The rule is applied automatically.

    Each cell's decision is written to the ledger as one "stop_rule" event,
    with both depth values and the two run ids. The console shows only how
    many cells stopped and how many were queued. No depth value and no
    per-cell decision is printed, and this script prints no other held-out
    result. The run scripts' own reports (conformance, dispositions) go to the
    per-attempt log files, not the console.

    Checked against docs/PREREGISTRATION_HELDOUT.md section 3 (11 Oct 2026).

What counts as a completed run (pre-registration section 3)
    A run that reaches the gate, meaning its gate_result.json exists, is a
    completed run whatever its exit code or result. It is never discarded or
    replaced. A run that never reaches the gate (crash, timeout, malformed
    output) is a technical failure and is re-run in the same position. A
    gated run with a non-zero exit is kept, and is flagged "gated_nonzero_exit"
    in the ledger.

    Each run is a plain call to scripts/run_baseline.py or scripts/run_council.py,
    exactly as in the development grid. The run directory under runs/ (manifest,
    calls.jsonl, tss.json, gate_result.json, transcript) is therefore produced by
    the same code and logged in the same way as every dev-grid run. This script
    adds bookkeeping only. It makes no model calls itself.

Checkpoint / resume
    Every attempt is appended to a ledger, runs/_set-<name>.ledger.jsonl, as a
    "started" event and then a "finished" event. A (workflow, condition, rep) is
    done when it has a finished event with status "ok". Re-running the same
    command resumes: done cells are skipped, and failed or interrupted cells are
    attempted again. Earlier attempts stay in the ledger, and their run
    directories stay in runs/, so the full attempt history remains auditable.
    The analysis reads only "ok" runs.

    The output of each attempt goes to runs/_set-<name>.<workflow>.<condition>.r<k>.a<n>.log.
    The bookkeeping lives in flat files rather than a directory because tools
    that scan runs/ treat every subdirectory as a run.

Stability guards (live runs refuse to start, or stop after the round, on failure)
    - Working tree clean. RunLogger also enforces this per run.
    - The pre-registration tag exists, HEAD descends from it, and
      data/encodings/heldout/ is byte-identical to the tagged version.
    - The expected number of encodings, all valid, with unique workflow ids.
    - One commit for the whole set. The first live start pins HEAD in the
      ledger, and a resume from any other commit is refused.
    - One resolved model for the whole set. The first ok run pins
      (resolved_model, model_created_at). Any later run that differs is recorded
      as "model_drift" and the set halts after that round. Required by
      CLAUDE.md where the provider exposes no dated snapshot. A drifted run
      has reached the gate, so it is never re-run automatically: the guard
      refuses every later start until the author records a deviation
      (pre-registration section 7).

--dry-run
    Makes no API calls and writes nothing. Prints the guard results, the plan
    with each cell's ledger status, and runtime estimates from the completed
    dev runs on disk for both bounds of the stopping rule: 56 runs (every cell
    stops at n=4) and 70 runs (every cell needs run 5).
"""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from design_council.measures.depth import measure_depth  # noqa: E402
from design_council.run_logging import DEFAULT_REQUESTED_MODEL, git_is_dirty  # noqa: E402
from design_council.schemas import TargetStateSpec, WorkflowEncoding  # noqa: E402

HELDOUT_DIR = REPO_ROOT / "data" / "encodings" / "heldout"
DEV_DIR = REPO_ROOT / "data" / "encodings" / "dev"
RUNS_ROOT = REPO_ROOT / "runs"
CONDITIONS = ["baseline", "council"]
RUN_SCRIPTS = {
    "baseline": REPO_ROOT / "scripts" / "run_baseline.py",
    "council": REPO_ROOT / "scripts" / "run_council.py",
}
EXPECTED_WORKFLOWS = 7
MIN_REPS = 4  # every cell runs at least this many
MAX_REPS = 5  # run 5 only where the stopping rule queues it
PROBE_ROLE = "model_resolution_probe"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


# --- ledger ------------------------------------------------------------------


def ledger_path(runs_root: Path, set_name: str) -> Path:
    return runs_root / f"_set-{set_name}.ledger.jsonl"


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_ledger(path: Path, event: dict) -> None:
    with path.open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()


def done_cells(events: list[dict]) -> dict[tuple[str, str, int], str]:
    """(workflow_id, condition, rep) -> run_id, for every ok finish."""
    done = {}
    for e in events:
        if e["event"] == "finished" and e["status"] == "ok":
            done[(e["workflow_id"], e["condition"], e["rep"])] = e["run_id"]
    return done


def attempt_count(events: list[dict], workflow_id: str, condition: str, rep: int) -> int:
    return sum(
        1
        for e in events
        if e["event"] == "started"
        and (e["workflow_id"], e["condition"], e["rep"]) == (workflow_id, condition, rep)
    )


def stop_decisions(events: list[dict]) -> dict[tuple[str, str], str]:
    """(workflow_id, condition) -> "complete_at_n4" or "run_5", as logged."""
    return {
        (e["workflow_id"], e["condition"]): e["decision"]
        for e in events
        if e["event"] == "stop_rule"
    }


def pins(events: list[dict]) -> tuple[dict | None, dict | None]:
    """The set's pinned commit and pinned model, if already recorded."""
    commit = next((e for e in events if e["event"] == "set_started"), None)
    model = next((e for e in events if e["event"] == "model_pinned"), None)
    return commit, model


# --- guards ------------------------------------------------------------------


def load_encodings(directory: Path) -> tuple[list[tuple[Path, WorkflowEncoding]], list[str]]:
    encodings, problems = [], []
    for path in sorted(directory.glob("*.json")):
        try:
            encodings.append(
                (path, WorkflowEncoding.model_validate(json.loads(path.read_text())))
            )
        except Exception as error:  # report every bad file, not just the first
            problems.append(f"{path.name}: {error}")

    ids = [e.workflow_id for _, e in encodings]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        problems.append(f"duplicate workflow_id(s): {duplicates}")
    return encodings, problems


def check_guards(
    args, encodings: list, encoding_problems: list[str], events: list[dict]
) -> list[tuple[str, bool, str]]:
    checks = []

    # The same test RunLogger applies to each run, untracked files included.
    # A looser check here would let the set start and then have every run refused.
    dirty = git_is_dirty(REPO_ROOT)
    status = git("status", "--porcelain").stdout.strip().splitlines()
    checks.append(("working tree clean (RunLogger's test, incl. untracked)", not dirty,
                   "clean" if not dirty else f"{len(status)} entries, e.g. {'; '.join(status[:4])}"))

    tag = args.prereg_tag
    if not tag:
        checks.append(("pre-registration tag given", False, "pass --prereg-tag"))
    else:
        exists = git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode == 0
        checks.append(("pre-registration tag exists", exists, tag))
        if exists:
            ancestor = git("merge-base", "--is-ancestor", tag, "HEAD").returncode == 0
            checks.append(("HEAD descends from tag", ancestor, ""))
            unchanged = git(
                "diff", "--quiet", tag, "--", str(HELDOUT_DIR.relative_to(REPO_ROOT))
            ).returncode == 0
            checks.append(("held-out encodings identical to tagged version", unchanged, ""))

    checks.append((
        f"{args.expect_workflows} valid encodings in {args.encodings_dir.relative_to(REPO_ROOT)}",
        len(encodings) == args.expect_workflows and not encoding_problems,
        f"found {len(encodings)}" + (f"; {'; '.join(encoding_problems)}" if encoding_problems else ""),
    ))

    head = git("rev-parse", "HEAD").stdout.strip()
    commit_pin, _ = pins(events)
    if commit_pin:
        checks.append(("HEAD matches set's pinned commit", commit_pin["git_commit"] == head,
                       f"pinned {commit_pin['git_commit'][:10]}, HEAD {head[:10]}"))

    if any(e["event"] == "finished" and e["status"] == "model_drift" for e in events):
        checks.append(("no model drift recorded in ledger", False,
                       "a run resolved to a different model; see ledger"))

    return checks


# --- runtime estimates ---------------------------------------------------------


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def dev_durations(runs_root: Path) -> dict[str, list[float]]:
    """Wall-clock minutes of every completed dev run on disk, by condition.

    Duration = manifest created_utc to the last call record's timestamp. That
    includes the resolution probe, stream retries and backoff, which are real
    costs of a run. Incomplete runs (no tss.json) are excluded and counted
    separately by dev_incomplete_counts.
    """
    dev_ids = {
        json.loads(p.read_text())["workflow_id"] for p in sorted(DEV_DIR.glob("*.json"))
    }
    durations: dict[str, list[float]] = {c: [] for c in CONDITIONS}
    for directory in sorted(runs_root.glob("*/")):
        manifest_path = directory / "run_manifest.json"
        if not manifest_path.exists() or not (directory / "tss.json").exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        if manifest["workflow_id"] not in dev_ids:
            continue
        calls = [json.loads(l) for l in (directory / "calls.jsonl").read_text().splitlines() if l.strip()]
        start = parse_utc(manifest["created_utc"])
        end = parse_utc(calls[-1]["timestamp_utc"])
        durations[manifest["condition"]].append((end - start).total_seconds() / 60)
    return durations


def dev_incomplete_counts(runs_root: Path) -> dict[str, tuple[int, int]]:
    """(incomplete, total attempts) per condition across all dev runs on disk."""
    counts = {c: [0, 0] for c in CONDITIONS}
    for directory in sorted(runs_root.glob("*/")):
        manifest_path = directory / "run_manifest.json"
        if not manifest_path.exists():
            continue
        condition = json.loads(manifest_path.read_text())["condition"]
        counts[condition][1] += 1
        if not (directory / "tss.json").exists():
            counts[condition][0] += 1
    return {c: (v[0], v[1]) for c, v in counts.items()}


def expected_max(values: list[float], draws: int) -> float:
    """Expected maximum of `draws` independent draws from the empirical distribution.

    E[max] = sum_i x_(i) * (F(x_(i))^k - F(x_(i-1))^k), over the sorted values.
    Used for a parallel round, whose wall time is set by its slowest run.
    """
    xs = sorted(values)
    n = len(xs)
    return sum(x * (((i + 1) / n) ** draws - (i / n) ** draws) for i, x in enumerate(xs))


def print_estimates(runs_root: Path, n_workflows: int, max_parallel: int) -> None:
    durations = dev_durations(runs_root)
    incomplete = dev_incomplete_counts(runs_root)
    b, c = durations["baseline"], durations["council"]

    print("\nRuntime estimates (from completed dev runs on disk; wall-clock minutes)")
    print(f"  {'condition':10} {'n':>3} {'median':>8} {'mean':>8} {'max':>8}   incomplete attempts")
    for name, xs in (("baseline", b), ("council", c)):
        bad, total = incomplete[name]
        print(f"  {name:10} {len(xs):>3} {median(xs):>8.1f} {mean(xs):>8.1f} {max(xs):>8.1f}"
              f"   {bad} of {total}")

    runs_per_round = 2 * n_workflows
    bounds = [(MIN_REPS, "every cell complete at n=4"), (MAX_REPS, "every cell queued for run 5")]
    print(f"\n  Plan: {n_workflows} workflows x 2 conditions; rounds 1-{MIN_REPS} always, "
          f"round {MAX_REPS} only for cells the stopping rule queues")
    for rounds, meaning in bounds:
        print(f"    {rounds * runs_per_round}-run bound: {meaning}")

    print("\n  Sequential (one run at a time, as the dev grid was run):")
    print(f"    {'per-run figure':16}" + "".join(
        f"{str(r * runs_per_round) + '-run bound':>22}" for r, _ in bounds))
    for label, f in (("median", median), ("mean", mean), ("max", max)):
        per_cell_rep = n_workflows * (f(b) + f(c))
        print(f"    {label:16}" + "".join(
            f"{r * per_cell_rep:9.0f} min ={r * per_cell_rep / 60:6.1f} h" for r, _ in bounds))

    # Baselines are submitted before councils (see main), so a round is
    # ceil(n/slots) waves of baselines, then ceil(n/slots) waves of councils.
    # Overlap between the two is ignored, which errs long. A partial round 5
    # is costed as a full one, so the 70-run figures are upper bounds.
    waves = -(-n_workflows // max_parallel)
    concurrent_councils = min(max_parallel, n_workflows)
    baseline_part = waves * max(b)
    print(f"\n  Parallel within a round (max {max_parallel} concurrent; baselines first, "
          f"then councils in {waves} wave(s) of up to {concurrent_councils}):")
    rows = (
        ("lower bound (median council run)", baseline_part + waves * median(c)),
        (f"expected slowest of {concurrent_councils} council runs",
         baseline_part + waves * expected_max(c, concurrent_councils)),
        ("worst observed (max council run)", baseline_part + waves * max(c)),
    )
    print(f"    {'per-round figure':42}{'min/round':>10}" + "".join(
        f"{str(r * runs_per_round) + '-run (' + str(r) + ' rounds)':>22}" for r, _ in bounds))
    for label, round_minutes in rows:
        print(f"    {label:42}{round_minutes:10.0f}" + "".join(
            f"{r * round_minutes:9.0f} min ={r * round_minutes / 60:6.1f} h" for r, _ in bounds))

    print("\n  Caveats: the dev grid ran one run at a time. Up to 14 concurrent streams were")
    print("  never tested and may raise rate-limit and stream-failure rates, which the long")
    print("  council tail already reflects. Estimates exclude reruns of failed attempts, so")
    print("  scale by the incomplete-attempt rate above. Held-out workflows may be larger")
    print("  than the 8-step dev encodings.")


# --- running -----------------------------------------------------------------


def parse_run_id(log_text: str) -> str | None:
    """The run scripts print 'run_id            : <id>'; take the last one."""
    found = None
    for line in log_text.splitlines():
        if line.startswith("run_id") and ":" in line:
            found = line.split(":", 1)[1].strip()
    return found


def run_one(args, ledger: Path, encoding_path: Path, workflow_id: str,
            condition: str, rep: int, attempt: int) -> dict:
    log_path = args.runs_root / (
        f"_set-{args.set_name}.{workflow_id}.{condition}.r{rep}.a{attempt}.log"
    )
    command = [
        sys.executable, str(RUN_SCRIPTS[condition]), str(encoding_path),
        "--model", args.model, "--runs-root", str(args.runs_root),
    ]
    append_ledger(ledger, {
        "event": "started", "set": args.set_name, "workflow_id": workflow_id,
        "condition": condition, "rep": rep, "attempt": attempt,
        "utc": utc_now(), "command": command, "log": log_path.name,
    })

    with log_path.open("w") as log:
        exit_code = subprocess.run(
            command, cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT
        ).returncode

    run_id = parse_run_id(log_path.read_text())
    run_dir = args.runs_root / run_id if run_id else None
    manifest = {}
    if run_dir and (run_dir / "run_manifest.json").exists():
        manifest = json.loads((run_dir / "run_manifest.json").read_text())

    # Reaching the gate is the test, not the exit code: a gated run is never
    # replaced (pre-registration section 3).
    reached_gate = (
        run_dir is not None
        and (run_dir / "gate_result.json").exists()
        and manifest.get("workflow_id") == workflow_id
        and manifest.get("condition") == condition
    )
    return {
        "event": "finished", "set": args.set_name, "workflow_id": workflow_id,
        "condition": condition, "rep": rep, "attempt": attempt, "utc": utc_now(),
        "exit_code": exit_code, "run_id": run_id,
        "status": "ok" if reached_gate else "failed",
        "gated_nonzero_exit": reached_gate and exit_code != 0,
        "resolved_model": manifest.get("resolved_model"),
        "model_created_at": manifest.get("model_created_at"),
        "git_commit": manifest.get("git_commit"),
    }


def apply_model_pin(ledger: Path, result: dict) -> dict:
    """Pin the model on the first ok run; downgrade any later mismatch to model_drift.

    Reads the ledger afresh for each result. Results are applied one at a time
    from the main thread, in completion order, so the first ok run to finish
    sets the pin.
    """
    if result["status"] != "ok":
        return result
    _, model_pin = pins(read_ledger(ledger))
    observed = {"resolved_model": result["resolved_model"],
                "model_created_at": result["model_created_at"]}
    if model_pin is None:
        append_ledger(ledger, {"event": "model_pinned", "utc": utc_now(),
                               "pinned_by_run": result["run_id"], **observed})
    elif {k: model_pin[k] for k in observed} != observed:
        result = {**result, "status": "model_drift",
                  "expected": {k: model_pin[k] for k in observed}}
    return result


def apply_stopping_rule(ledger: Path, encodings: list, runs_root: Path) -> None:
    """After round 4: log one stop_rule event per cell not yet decided.

    Depth for run 3 and run 4 is recomputed from each run's tss.json
    (disposition mapping) with measure_depth. Equal depths mark the cell
    complete at n=4; unequal depths queue run 5. Nothing is printed here.
    The values go to the ledger only.

    Cells already decided keep their logged decision, so a resume never
    re-decides or double-logs.
    """
    events = read_ledger(ledger)
    done = done_cells(events)
    decided = stop_decisions(events)
    for _, encoding in encodings:
        for condition in CONDITIONS:
            cell = (encoding.workflow_id, condition)
            if cell in decided:
                continue
            run3 = done[(*cell, 3)]
            run4 = done[(*cell, 4)]
            depth3 = measure_depth(encoding, TargetStateSpec.model_validate_json(
                (runs_root / run3 / "tss.json").read_text())).depth_score
            depth4 = measure_depth(encoding, TargetStateSpec.model_validate_json(
                (runs_root / run4 / "tss.json").read_text())).depth_score
            append_ledger(ledger, {
                "event": "stop_rule", "utc": utc_now(),
                "workflow_id": encoding.workflow_id, "condition": condition,
                "run3_id": run3, "run4_id": run4,
                "depth_run3": depth3, "depth_run4": depth4,
                "decision": "complete_at_n4" if depth3 == depth4 else "run_5",
            })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set-name", required=True,
                        help="name of the experimental set; keys the ledger")
    parser.add_argument("--prereg-tag", default=None,
                        help="git tag freezing data/encodings/heldout/")
    parser.add_argument("--max-parallel", type=int, default=2 * EXPECTED_WORKFLOWS)
    parser.add_argument("--model", default=DEFAULT_REQUESTED_MODEL)
    parser.add_argument("--encodings-dir", type=Path, default=HELDOUT_DIR)
    parser.add_argument("--expect-workflows", type=int, default=EXPECTED_WORKFLOWS)
    parser.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    parser.add_argument("--dry-run", action="store_true",
                        help="no API calls, nothing written: guards, plan, estimates")
    args = parser.parse_args()
    args.encodings_dir = args.encodings_dir.resolve()
    args.runs_root = args.runs_root.resolve()

    ledger = ledger_path(args.runs_root, args.set_name)
    events = read_ledger(ledger)
    encodings, encoding_problems = load_encodings(args.encodings_dir)
    checks = check_guards(args, encodings, encoding_problems, events)

    print(f"set               : {args.set_name}")
    print(f"ledger            : {ledger}{'' if ledger.exists() else ' (new)'}")
    print(f"model requested   : {args.model}")
    print(f"design            : {len(encodings)} workflows x {CONDITIONS} x n={MIN_REPS} "
          f"(+ run {MAX_REPS} where the stopping rule queues it), round-robin, "
          f"max {args.max_parallel} parallel")
    print("\nGuards")
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  — ' + detail if detail else ''}")

    done = done_cells(events)
    decided = stop_decisions(events)

    def mark(workflow_id: str, condition: str, rep: int) -> str:
        if (workflow_id, condition, rep) in done:
            return "x"
        if rep == MAX_REPS:
            decision = decided.get((workflow_id, condition))
            if decision is None:
                return "?"
            if decision == "complete_at_n4":
                return "-"
        return "."

    # The round-5 marks show which cells the rule queued, never the depths.
    print("\nPlan (b=baseline c=council; x=done .=pending "
          "?=awaiting stopping rule -=complete at n=4)")
    for rep in range(1, MAX_REPS + 1):
        marks = [f"{enc.workflow_id}:{mark(enc.workflow_id, 'baseline', rep)}"
                 f"{mark(enc.workflow_id, 'council', rep)}" for _, enc in encodings]
        print(f"  round {rep}: {'  '.join(marks) or '(no encodings)'}")

    if args.dry_run:
        print_estimates(args.runs_root, len(encodings) or args.expect_workflows,
                        args.max_parallel)
        print("\nDry run: no API calls made, nothing written.")
        return 0

    if not all(ok for _, ok, _ in checks):
        print("\nRefusing to start: a guard failed.", file=sys.stderr)
        return 1

    commit_pin, _ = pins(events)
    if commit_pin is None:
        append_ledger(ledger, {
            "event": "set_started", "set": args.set_name, "utc": utc_now(),
            "git_commit": git("rev-parse", "HEAD").stdout.strip(),
            "prereg_tag": args.prereg_tag, "requested_model": args.model,
            "min_reps": MIN_REPS, "max_reps": MAX_REPS,
            "stopping_rule": "after round 4: depth(run 3) == depth(run 4) -> complete at "
                             "n=4, else run 5 (PREREGISTRATION_HELDOUT.md section 3)",
            "conditions": CONDITIONS,
            "workflows": {
                e.workflow_id: str(p.relative_to(REPO_ROOT)) if p.is_relative_to(REPO_ROOT) else str(p)
                for p, e in encodings
            },
        })

    for rep in range(1, MAX_REPS + 1):
        if rep == MAX_REPS:
            apply_stopping_rule(ledger, encodings, args.runs_root)
            decided = stop_decisions(read_ledger(ledger))
            queued = [cell for cell, d in decided.items() if d == "run_5"]
            print(f"\nstopping rule applied after round {MIN_REPS}: "
                  f"{len(decided) - len(queued)} cell(s) complete at n={MIN_REPS}, "
                  f"{len(queued)} queued for run {MAX_REPS} (decisions and depths in ledger)")

        events = read_ledger(ledger)
        done = done_cells(events)
        decided = stop_decisions(events)
        # Baselines are submitted first. They take about a minute, so with
        # fewer slots than runs they clear quickly and the council runs then
        # start together. The round time is set by the councils either way.
        pending = [
            (path, enc.workflow_id, condition)
            for condition in CONDITIONS
            for path, enc in encodings
            if (enc.workflow_id, condition, rep) not in done
            and (rep < MAX_REPS or decided[(enc.workflow_id, condition)] == "run_5")
        ]
        if not pending:
            print(f"\nround {rep}: already complete")
            continue

        print(f"\nround {rep}: launching {len(pending)} run(s)")
        with ThreadPoolExecutor(max_workers=args.max_parallel) as pool:
            futures = [
                pool.submit(run_one, args, ledger, path, wid, cond, rep,
                            attempt_count(events, wid, cond, rep) + 1)
                for path, wid, cond in pending
            ]
            # Record each result as soon as its run ends, so an interrupt mid-round
            # loses no finished run.
            results = []
            for future in as_completed(futures):
                result = apply_model_pin(ledger, future.result())
                append_ledger(ledger, result)
                results.append(result)
                print(f"  {result['workflow_id']:12} {result['condition']:9} r{rep} "
                      f"{result['status']:12} {result['run_id']}")

        bad = [r for r in results if r["status"] != "ok"]
        if bad:
            print(f"\nround {rep} incomplete: {len(bad)} run(s) not ok. Stopping before "
                  f"round {rep + 1}. Inspect the logs, then re-run this command to resume.",
                  file=sys.stderr)
            return 1

    print("\nall rounds complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
