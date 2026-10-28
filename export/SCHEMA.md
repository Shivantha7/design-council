# export/ schema

Written by `scripts/export_app_data.py`. Do not edit by hand. It is the single source of
truth for `app.py` and any later front end. Deterministic: the same commit gives the same
bytes. JSON files use sorted keys. Floats are rounded to 6 decimals.

## index.json
- `export_commit`: git commit the export was made from. `prereg_tag`: freeze tag of the held-out set.
  `repo_url`: public repository URL (null until published).
- `research_question`: verbatim from the dissertation.
- `sets.heldout-v1`: `label`, `commit` (pinned run commit), `requested_model`, `workflows` (7 ids),
  `runs` (68 run ids), `cells[]` = {`workflow_id`, `condition`, `run_ids` in rep order, `stop_decision`
  (`complete_at_n4` | `run_5`)}.
- `sets.dev-v1`: `label`, `workflows` (3 ids), `runs` (18 v1 run ids).
- `sets.sequential`: exploratory, post-freeze. `label`, `exploratory`, `workflows` (the held-out
  workflows that have sequential runs), `runs` (run ids with a TSS; failed attempts left out).
- `workflows[]`: {`workflow_id`, `name`, `split` (heldout | dev), `profile` (transactional |
  judgment-dense | null), `function_area`, `steps`, `requirements`, `open_steps`} (the last three are counts).
- `findings[]`: {`id` (F1 to F6), `status` (pre-registered | pre-registered counts | pre-registered coding |
  exploratory), `title`, `text`}.
- `limits[]`: {`id`, `text`}.
- `headline`: headline numbers used by the overview page.

## workflows/<workflow_id>.json
The baseline encoding: `name`, `split`, `domain`, `function_area`, `profile`, `source`,
`open_steps` (unconstrained_by_design), `steps[]` (step_id, name, description, actor, inputs,
outputs), `requirements[]` (requirement_id, statement, rule_type, params).

## runs/<run_id>.json
- `run_id`, `set` (heldout-v1 | dev-v1 | sequential), `workflow_id`, `condition` (council | baseline |
  sequential), `rep` (held-out: ledger repetition; dev and sequential: order by run id within the workflow), `created_utc`, `git_commit`,
  `resolved_model`, `disposition_convention_version`.
- `steps[]`: target-state steps with `class_primary` and `class_agentic_only` (HUMAN | HYBRID |
  AGENT, `design_council/measures/actor_class.decided_class`).
- `disposition_mapping[]`: baseline_step_id, disposition, target_step_ids, rationale.
- `gate`: `conformance_score`, `passed`, `total`, `results[]` (requirement_id, passed, vacuous, reason).
- `depth`: `score` (pre-registered scalar), `counts` per disposition, `total_baseline_steps`.
- `consistency_inputs`: baseline step id → disposition (pairwise agreement is computed from these).
- `efficiency`: input/output tokens, calls (probe excluded, failed attempts included),
  `failed_attempts`, `runtime_min`, `cost_usd` ($2/M input, $10/M output).
- `transcript[]`: {`phase` (round 1 | round 2 | synthesis | single agent | perspectives |
  reconsiderations), `role`, `excerpt`
  (first 600 characters), `truncated`, `chars`}.

## results/heldout_tables.json
`x1_run_completion`, `x2_conformance_failures`, `x3_depth` (with `gap_exact` as a fraction and
`meets_sesoi` decided exactly), `x4_dispositions`, `x5_stabilisation` (with per-cell consistency),
`fill_ins` (H1 branch, H2 and H3 counts and verdicts, consistency by condition).

## results/conformance_failures.json
Exploratory. X.2 rows plus `classification` (NAMING | SUBSTANTIVE | UNCLEAR) from
`docs/CONFORMANCE_FAILURE_CLASSIFICATION.md`.

## results/efficiency.json
Descriptive. `per_cell` means (tokens, calls, runtime, cost), `totals` per condition,
`council_to_baseline_cost_ratio`.

## results/productivity.json
Exploratory. `variants.primary` and `variants.agentic-only`, each with `per_workflow` (median,
p05, p95, worst_case PI), `pooled` (all | transactional | judgment-dense: pi, p05, p95), `prcc`,
`oat`, and `structural` (original counts vs council mean/min/max for steps, HUMAN, HYBRID,
AGENT, HITL, handoffs, h2h, approvals). `seed`, `draws` and `bootstrap` are recorded.

## results/governance_controls.json
Section 6 coding (final). `per_workflow` (final_controls, pass, strict_75), `by_role` (primary,
any), and `controls[]` = {control_id, merged_ids, name, workflow_id, members, primary_role, roles,
council_present, council_n, baseline_present, outcome, strict_75, quote, quote_run_id}.

## results/sequential.json
Exploratory, post-freeze. `label`, `protocol`, and `workflows[]` = {`workflow_id`, `doc`,
`preregistration` (path or null), `conditions` (sequential | council | baseline: n, run_ids,
depth_mean/min/max, conformance_mean, runs_below_1, consistency, mean_cost_usd, mean_runtime_min)}.
Council and baseline are the held-out cells for the same workflow. Not part of any held-out table.

## results/dev_grid.json
v1 development grid per workflow x condition: n, run_ids, depth mean/min/max, conformance mean,
disposition counts, consistency, mean output tokens.

## Carried over from separate analysis scripts (exploratory, no model calls)
Not computed by this script. Each is written by its own script into `export/results/` and
copied here byte for byte, so these files keep that script's formatting (not sorted keys,
floats unrounded).
- `results/bootstrap_h2.json` (`scripts/bootstrap_h2.py`, `docs/BOOTSTRAP_H2.md`): H2 rule under
  resampling of runs within cells. `B`, `seed`, `sesoi`, `need`, and for `reported` (depth as
  recorded) and `verified` (verified depth): `point_gaps`, `point_pass`, `bootstrap_pass_rate`,
  `per_workflow_pass_prob`, `gap_95ci`, `count_distribution`, `loo_pass_rate`, `loo_fail_cases`.
- `results/depth_verification.json` (`scripts/verify_dispositions.py`, `docs/DEPTH_VERIFICATION.md`):
  disposition labels checked against the TSS. `by_condition` and `overall` label checks, and
  `cells` ("<workflow>|<condition>": n, depth_reported_mean, depth_verified_mean).
- `results/controls_symmetric_length.json` (`scripts/controls_symmetric_length.py`,
  `docs/CONTROLS_SYMMETRIC_LENGTH.md`): the section 6 rule applied in both directions
  (`symmetric` per workflow) and control counts per TSS length (`length_by_condition`,
  `length_by_workflow`, `runs`).
