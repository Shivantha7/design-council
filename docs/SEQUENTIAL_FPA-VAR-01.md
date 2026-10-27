# Sequential single agent vs council vs baseline: FPA-VAR-01

Exploratory, post-freeze. Sequential = one agent, seven cumulative perspectives, seven reconsiderations, synthesis (15 calls).

| Condition | n | Depth (mean) | min | max | Verified depth | Conformance | Runs < 1 | Consistency | Input tok | Output tok | Cost USD | Design words |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 5 | 0.525 | 0.250 | 0.750 | 0.450 | 1.000 | 0 | 0.750 | 7,364 | 4,905 | 0.06 | 324 |
| sequential | 5 | 0.875 | 0.750 | 1.000 | 0.800 | 0.900 | 2 | 0.575 | 424,027 | 70,623 | 1.55 | 955 |
| council | 5 | 0.875 | 0.750 | 1.000 | 0.825 | 1.000 | 0 | 0.800 | 272,729 | 77,910 | 1.32 | 883 |

Gap council minus sequential, depth as recorded: +0.000; verified: +0.025.
Gap sequential minus baseline, depth as recorded: +0.350; verified: +0.350.
Compute ratio sequential/council: input 1.55, output 0.91, cost 1.17.

## Sequential runs

Consistency is the run's mean disposition agreement with the other sequential runs. Runtime is first to last call, excluding the shared model-resolution probe.

| Run | Depth | Verified depth | Conformance | Consistency | Calls | Input tok | Output tok | Cost USD | Runtime min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20261027-080433-sequential-FPA-VAR-01-272d | 0.875 | 0.625 | 1.000 | 0.500 | 16 | 446,253 | 77,226 | 1.66 | 15.4 |
| 20261027-082215-sequential-FPA-VAR-01-dad8 | 0.750 | 0.750 | 0.625 | 0.625 | 16 | 443,435 | 63,207 | 1.52 | 12.8 |
| 20261027-083540-sequential-FPA-VAR-01-0e87 | 0.875 | 0.875 | 1.000 | 0.719 | 16 | 402,376 | 72,622 | 1.53 | 14.2 |
| 20261027-085058-sequential-FPA-VAR-01-f7d2 | 0.875 | 0.875 | 1.000 | 0.594 | 16 | 397,190 | 77,381 | 1.57 | 15.1 |
| 20261027-090712-sequential-FPA-VAR-01-a7de | 1.000 | 0.875 | 0.875 | 0.438 | 16 | 430,882 | 62,680 | 1.49 | 12.4 |

Failed attempts (kept in runs/, no TSS, excluded from every figure): none.

## Pre-stated outcome

Pre-registration note: `docs/SEQUENTIAL_FPA-VAR-01_preregistration.md`, commit `987d710ba37e0c3946c197a3f96ab7f1bf99bac8`.

G = council mean depth minus sequential mean depth = 0 = +0.000; one quantum = 1/8 = 0.125.

Outcome **a** applies: "on both workflows tested, a single agent given the Council's compute and walked through the seven role charters matched the Council's depth; the depth advantage is attributable to computation, not deliberation, on this evidence".

## Workflows with sequential runs

Depth as recorded (mean), conformance (mean), run-to-run consistency; sequential / council / baseline.

| Workflow | Depth seq | Depth council | Depth baseline | Conf. seq | Conf. council | Conf. baseline | Cons. seq | Cons. council | Cons. baseline |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P2P-TWM-01 | 0.971 | 0.971 | 0.771 | 0.880 | 0.920 | 1.000 | 0.786 | 0.829 | 0.829 |
| FPA-VAR-01 | 0.875 | 0.875 | 0.525 | 0.900 | 1.000 | 1.000 | 0.575 | 0.800 | 0.750 |

## Run notes (written by hand, not generated)

- All five runs: commit 987d710 (the pre-registration commit), clean tree, requested and resolved
  model `claude-sonnet-5`, provider `created_at` 2026-06-29, re-checked through the models endpoint
  before each invocation.
- Two invocations of `scripts/run_sequential.py ... --reps N`. The first (`--reps 5`) completed run
  272d and then refused to start its second rep because the working tree had become dirty (an
  uncommitted edit to this analysis script, made during the run). No model call was made for that
  rep and no run directory was created. The edit was set aside, the tree restored to 987d710, and
  the remaining four runs made with `--reps 4`. Manifests therefore record `rep` 1 for 272d and 1 to 4
  for dad8, 0e87, f7d2 and a7de; each invocation has its own model-resolution probe, logged in its
  runs' `calls.jsonl`.
- No rep failed before the gate. Two runs fell below 1.0 conformance (dad8 0.625, a7de 0.875); they
  are complete runs and are included, as below-1.0 runs are in every other cell.
- Compute: the sequential runs used more input than the council on this workflow (ratio 1.55) and
  cost 1.17 times as much per run, against 1.01 on P2P-TWM-01.
