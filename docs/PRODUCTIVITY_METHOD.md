# Structural Productivity Potential (SPP): method and parameters

Status: exploratory, post hoc relative to the pre-registered study. This document is committed BEFORE any productivity figure is computed. Parameters are not changed after computation; any change is reported as a deviation.

Author: Shivantha Meepage. Date: 11 October 2026.

## 1. Question

How much human effort, and how many hand-offs, does each agentic redesign remove compared with the original workflow, and how certain is the estimate?

Comparison: original encoding versus each Council redesign (33 Council runs, 7 held-out workflows). The single-agent baseline is not included.

This is an estimate of productivity potential built into the design, under stated assumptions. It is not a measured operational outcome.

## 2. Step classification

Every step in the original encoding and in each Council TSS is classified by its actor field:

- HUMAN: a person performs the step (with or without conventional tools such as an ERP).
- HYBRID: an AI agent performs the step and a person reviews, approves or confirms it (human in the loop).
- AGENT: an AI agent performs the step; only exceptions go to a person.

Rules are deterministic keyword rules over the actor and description fields. All rules and every ambiguous case are listed for the author's decision before computation.

## 3. Human effort model

Each original step s has effort weight t_s (weights sum to 1 per workflow). Its effort is carried to the target step(s) that carry it in the disposition mapping:

Remaining human effort H = sum over s of t_s x r(class of carrying step) x m(disposition of s)

- r(HUMAN) = 1
- r(HYBRID) = r_h
- r(AGENT) = e x k
- m = 1 for retained or restructured; m for merged or absorbed
- If a step is carried by several target steps, the most human-intensive class is used (conservative).

Productivity Index PI = 1 - H / H_original, where H_original = 1 (all original steps classified HUMAN unless the encoding states agent automation).

## 4. Parameters (fixed)

| Parameter | Distribution | Source |
|---|---|---|
| t_s | Dirichlet(1, ..., 1) per workflow | Neutral: no equal-time assumption |
| r_h | Triangular(0.45, 0.65, 0.85) | Field and lab experiments: AI-assisted task time reductions of 22% to 54% (Dell'Acqua et al., 2026; Noy and Zhang, 2023; Fan et al., 2026; Fitz-Patrick et al., 2025). Upper bound kept high for verification burden (Simkute et al., 2024; Tan, 2026) |
| e, transactional (P2P-TWM, PRE, EXR; R2R-ACR) | Uniform(0.10, 0.30) | Deployed AP automation: 76% of invoices with low or no manual intervention (Tater et al., 2022); about 75% straight-through (Dameruppula, 2026) |
| e, judgment-dense (R2R-FSP; FPA-VAR, ABB) | Uniform(0.20, 0.50) | Author assumption: wider and more pessimistic than transactional evidence |
| k | Uniform(1.0, 1.5) | Author assumption: exceptions cost at least as much as the original manual step |
| m | Uniform(0.70, 1.00) | Author assumption; tested in sensitivity analysis |

Worst case: r_h = 0.85, e at its maximum, k = 1.5, m = 1.0, with step weights set adversarially (all weight on the most human-intensive carried steps).

## 5. Structural counts (no parameters)

Per original workflow and per Council run (mean and range per workflow):
- total steps; HUMAN, HYBRID, AGENT steps
- human-in-the-loop checkpoints (HYBRID steps plus explicit approval steps)
- actor hand-offs (consecutive steps with different actors), and human-to-human hand-offs
- approval steps

## 6. Statistics

- Monte Carlo: 10,000 parameter draws. For each draw, PI is computed for every Council run.
- Per workflow: median PI and 90% interval, pooling parameter and run-to-run variation.
- Pooled: median PI across workflows with a workflow-level bootstrap (7 workflows, 10,000 resamples).
- Subgroups: transactional versus judgment-dense.
- Sensitivity: partial rank correlation of each parameter with PI; one-at-a-time ranges.
- Worst-case PI per workflow.
- Plausibility check only (not an input): reported reductions of about 80% manual effort in deployed AP automation (Dameruppula, 2026) and 50% cost in a human-in-the-loop case (Wulf et al., 2026).

## 7. Reporting

Section 7.5 of the dissertation, labelled exploratory. Language: "expected productivity potential under stated assumptions". Naturalistic validation (benchmark-time simulation, pilot deployment) is future work.
