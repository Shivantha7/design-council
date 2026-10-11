# export/ schema

Written by `scripts/export_app_data.py`. Do not edit by hand. It is the single source of
truth for `app.py` and any later front end. Deterministic: the same commit gives the same
bytes. JSON files use sorted keys. Floats are rounded to 6 decimals.

## index.json
- `export_commit`: git commit the export was made from. `prereg_tag`: freeze tag of the held-out set.
- `research_question`: verbatim from the dissertation.
- `sets.heldout-v1`: `label`, `commit` (pinned run commit), `requested_model`, `workflows` (7 ids),
  `runs` (68 run ids), `cells[]` = {`workflow_id`, `condition`, `run_ids` in rep order, `stop_decision`
  (`complete_at_n4` | `run_5`)}.
- `sets.dev-v1`: `label`, `workflows` (3 ids), `runs` (18 v1 run ids).
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
- `run_id`, `set` (heldout-v1 | dev-v1), `workflow_id`, `condition` (council | baseline), `rep`
  (held-out: ledger repetition; dev: order by run id), `created_utc`, `git_commit`,
  `resolved_model`, `disposition_convention_version`.
- `steps[]`: target-state steps with `class_primary` and `class_agentic_only` (HUMAN | HYBRID |
  AGENT, `design_council/measures/actor_class.decided_class`).
- `disposition_mapping[]`: baseline_step_id, disposition, target_step_ids, rationale.
- `gate`: `conformance_score`, `passed`, `total`, `results[]` (requirement_id, passed, vacuous, reason).
- `depth`: `score` (pre-registered scalar), `counts` per disposition, `total_baseline_steps`.
- `consistency_inputs`: baseline step id → disposition (pairwise agreement is computed from these).
- `efficiency`: input/output tokens, calls (probe excluded, failed attempts included),
  `failed_attempts`, `runtime_min`, `cost_usd` ($2/M input, $10/M output).
- `transcript[]`: {`phase` (round 1 | round 2 | synthesis | single agent), `role`, `excerpt`
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

## results/dev_grid.json
v1 development grid per workflow x condition: n, run_ids, depth mean/min/max, conformance mean,
disposition counts, consistency, mean output tokens.
