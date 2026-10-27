# Sequential single agent on FPA-VAR-01: pre-registration note

Exploratory, post-freeze. Written and committed before any model call for this cell. The
write-up (docs/SEQUENTIAL_FPA-VAR-01.md) records this note's commit hash.

## Purpose

The sequential condition was run on one transactional workflow (P2P-TWM-01, n=5,
docs/SEQUENTIAL_P2P-TWM-01.md). This cell adds one judgment-dense workflow, so the
exploratory check covers one workflow of each profile. No other workflows will be run.

## Cell

- Workflow: FPA-VAR-01, encoding `data/encodings/heldout/fpa_variance_analysis.json`
  (8 baseline steps, 8 requirements).
- Condition: sequential. n = 5.
- Command: `python scripts/run_sequential.py data/encodings/heldout/fpa_variance_analysis.json --reps 5`.
  Reps run in sequence, as the script does. No change to the runner, the agent, the prompts or
  the charters. Clean tree; `--allow-dirty` is not used.

## Budget and calls (same as the TWM sequential runs)

- Model: requested `claude-sonnet-5`. Before any call, the model must still resolve to
  `claude-sonnet-5` with provider `created_at` 2026-06-29. If it does not, nothing is run.
- 16 logged calls per run: 1 model-resolution probe, 7 cumulative perspective calls (one per role
  charter), 7 reconsiderations, 1 synthesis.
- `max_tokens` 16,000 per call and 24,000 for synthesis (`SYNTHESIS_MAX_TOKENS`), as in the TWM
  sequential runs. No seed is exposed by the provider; none is set.
- A rep that fails before the gate is re-run, and the failed attempt's run directory is kept in
  `runs/`, as with TWM.

## Reference values (held-out grid, FPA-VAR-01)

| Cell | n | Mean depth |
|---|---:|---:|
| council | 5 | 0.875 |
| baseline | 5 | 0.525 |
| gap, council minus baseline | | +0.350 |

## Decision rule

Measure: depth as recorded (the pre-registered depth scalar), mean over the five sequential runs.
Let G = council mean (0.875) minus sequential mean. Compared as exact fractions. One quantum is one
baseline step of per-run depth: 1/8 = 0.125.

- a) |G| <= 1/8 (sequential within one quantum of the council, either side):
  "on both workflows tested, a single agent given the Council's compute and walked through the
  seven role charters matched the Council's depth; the depth advantage is attributable to
  computation, not deliberation, on this evidence".
- b) G >= 0.2 (council ahead of sequential by at least 0.2):
  "the compute-matched agent matched the Council on transactional work but not on judgment-dense
  work, consistent with the exploratory finding in Section 7.5".
- c) 1/8 < G < 0.2 (in between):
  "the compute-matched agent closed most but not all of the gap; the attribution to deliberation
  on judgment-dense work remains open".

Not covered by a pre-stated sentence: sequential ahead of the council by more than one quantum
(G < -1/8). If that occurs it is reported descriptively, with no pre-stated sentence.

Verified depth, conformance, consistency, tokens, cost and runtime are reported alongside but do
not enter the decision rule.
