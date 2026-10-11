# Productivity analysis: author's classification decisions

Decided by the author (Shivantha Meepage) on 11 October 2026, after reviewing `docs/PRODUCTIVITY_CLASSIFICATION_REVIEW.md` and **before any productivity figure was computed**. Method: `docs/PRODUCTIVITY_METHOD.md` (commit `a67c2af`). Exploratory analysis.

## Decisions

| Item | Decision |
|---|---|
| G1 deterministic automation | **Yes** for the PRIMARY PI: rules engines, matching engines, pipelines and "system-executed" steps count as automated (HYBRID or AGENT per the rules). **Declared variant "agentic-only"**, fixed now: every G1 step (deterministic automation, no AI term) is HUMAN. Both are reported. |
| G2 person performs, agent assists | HYBRID (default). |
| G3 person owns policy only | AGENT (default). |
| G4 counting | Defaults. Hand-offs compare base role (actor text before the first "(", "," or ";", case-folded). Approval steps = approval vocabulary in the step name only. HITL checkpoints = HYBRID steps + approval steps, each step counted once. Human-to-human hand-off = both steps HUMAN. |
| A3 actor human, agent only in description | Keep HUMAN. |
| A4 automation term not the performer | HUMAN, unless the actor also names an automated lane that performs the step, in which case the default stands. Implemented as `PERFORMING_LANE`: `\b(automat\w*|system-executed|engine|gate)\b[^;]*\b(for clean|lane)\b`. |
| A1, A2 | Keep defaults. |

Implementation: `decided_class()` in `design_council/measures/actor_class.py`. The 57 original steps are all HUMAN under both classifications. No held-out encoding states agent automation.

## Steps whose class changes: primary vs default rules (6)

All are A4 tie-breaks. A3, A1 and A2 change nothing by construction. One A4 step keeps its default because its actor names a performing automated lane: `0842:TS-04` (P2P-TWM-01), AGENT, "…; automated release gate for clean/in-tolerance, no-exception matches".

| Key | Workflow | Default | Primary | Actor |
|---|---|---|---|---|
| 7759:TS-07 | FPA-VAR-01 | HYBRID | HUMAN | FP&A manager (presentation, for material/sensitive items) with an automated distribution agent (mechanical push) |
| 59a3:TS-03 | P2P-EXR-01 | HYBRID | HUMAN | Line manager (with automatic next-level escalation on self-approval conflict) |
| 8682:TGT-03 | P2P-PRE-01 | HYBRID | HUMAN | Authorised signatory, assisted by non-decisioning DOA validation/routing agent |
| 8682:TGT-05 | P2P-PRE-01 | AGENT | HUMAN | Second authorised releaser (treasury officer/manager, or system-enforced delegation chain, distinct from file-generation role) |
| 4f3e:TS-04 | FPA-VAR-01 | AGENT | HUMAN | Budget holders (commentary authors); orchestration agent (logistics only) |
| 5ef7:TS-03 | P2P-TWM-01 | HYBRID | HUMAN | AP analyst, with agent-assisted evidence retrieval (no write/decision authority) |

## Steps whose class changes: agentic-only variant vs primary (45)

Every G1 step that is not already HUMAN under the primary classification.

| Key | Workflow | Primary | Agentic-only | Actor |
|---|---|---|---|---|
| 60e6:TS-01 | R2R-ACR-01 | AGENT | HUMAN | GL accountant (extraction exception handler, supported by automated extraction where infrastructure and data quality allow) |
| 7759:TS-02 | FPA-VAR-01 | HYBRID | HUMAN | FP&A analyst (methodology owner) with automated computation engine, overseen by FP&A manager |
| 7759:TS-04 | FPA-VAR-01 | HYBRID | HUMAN | Budget holders, supported by commentary orchestration tooling |
| 59a3:TS-02 | P2P-EXR-01 | HYBRID | HUMAN | Policy compliance engine with AP analyst / policy officer adjudication |
| 59a3:TS-05 | P2P-EXR-01 | AGENT | HUMAN | Posting engine with GL accountant exception ownership |
| 6c3b:TS-02 | P2P-TWM-01 | AGENT | HUMAN | Tolerance rules engine (automated application); tolerance policy owner (accountable for policy content and version governance, not for per-invoice classification) |
| 6c3b:TS-04 | P2P-TWM-01 | AGENT | HUMAN | Automated release gate (logged policy engine) for clean/in-tolerance no-exception matches; AP supervisor (distinct from the TS-03 actor) for exception-touched or override matches |
| 333a:T4 | FPA-ABB-01 | HYBRID | HUMAN | Cost centre owners, supported by baseline-drafting automation |
| e0a8:T-02 | P2P-PRE-01 | HYBRID | HUMAN | AP supervisor (with screening engine) |
| e0a8:T-05 | P2P-PRE-01 | HYBRID | HUMAN | Treasury officer (with reconciliation engine) |
| e0a8:T-06 | P2P-PRE-01 | HYBRID | HUMAN | GL accountant (with posting engine) |
| c9c7:T1 | R2R-FSP-01 | HYBRID | HUMAN | GL accountant (supported by close-readiness monitoring automation) |
| c9c7:T2 | R2R-FSP-01 | HYBRID | HUMAN | GL accountant (adjustment-posting automation under accountant oversight) |
| b45d:T3 | P2P-EXR-01 | AGENT | HUMAN | System (policy engine) / AP analyst |
| 6fd0:TS-01 | FPA-VAR-01 | HYBRID | HUMAN | FP&A analyst (data steward) with automated extraction system |
| 6fd0:TS-02 | FPA-VAR-01 | HYBRID | HUMAN | FP&A analyst (data steward) with automated load system |
| 6fd0:TS-03 | FPA-VAR-01 | HYBRID | HUMAN | FP&A analyst with automated computation engine |
| 6fd0:TS-09 | FPA-VAR-01 | HYBRID | HUMAN | Automated publishing system, triggered by FP&A manager sign-off |
| 0842:TS-02 | P2P-TWM-01 | AGENT | HUMAN | Deterministic matching/tolerance rules engine (system-executed), governed by AP controller/policy owner; AP analyst monitors output |
| 0842:TS-04 | P2P-TWM-01 | AGENT | HUMAN | AP supervisor (system-enforced distinct role); automated release gate for clean/in-tolerance, no-exception matches |
| 64dc:TS-01 | P2P-PRE-01 | AGENT | HUMAN | AP analyst (system-executed selection/grouping; analyst configures, stewards master data, and triages exceptions) |
| 64dc:TS-02 | P2P-PRE-01 | HYBRID | HUMAN | AP supervisor (with automated screening tool) |
| 64dc:TS-04 | P2P-PRE-01 | HYBRID | HUMAN | Treasury officer (system-executed generation; human-triggered release; second signatory above threshold) |
| 64dc:TS-05 | P2P-PRE-01 | AGENT | HUMAN | Treasury officer (exception queue owner; automated matching for routine case) |
| 64dc:TS-06 | P2P-PRE-01 | AGENT | HUMAN | GL accountant (system-executed routine postings; accountant reviews/releases variances and fallback rate entries) |
| 64dc:TS-07 | P2P-PRE-01 | AGENT | HUMAN | AP analyst (delivery-exception owner; automated generation and dispatch) |
| a8a0:TS-01 | FPA-VAR-01 | HYBRID | HUMAN | FP&A analyst (with automated ingestion pipeline) |
| a8a0:TS-02 | FPA-VAR-01 | HYBRID | HUMAN | FP&A analyst (with automated computation engine) |
| df77:TS-01 | P2P-TWM-01 | AGENT | HUMAN | Automated matching engine, with AP analyst performing manual-completion fallback |
| df77:TS-02 | P2P-TWM-01 | AGENT | HUMAN | Automated tolerance engine (tolerance policy owned and periodically re-approved by AP supervisor/controller) |
| df77:TS-04 | P2P-TWM-01 | AGENT | HUMAN | System-executed release (clean/tolerance lane); AP supervisor (exception-resolved and override cases) |
| 8682:TGT-06 | P2P-PRE-01 | HYBRID | HUMAN | Treasury officer, with automated matching engine |
| 8682:TGT-08 | P2P-PRE-01 | AGENT | HUMAN | AP analyst (automated generation/delivery, exception-queue owner for failed delivery) |
| 4f3e:TS-01 | FPA-VAR-01 | HYBRID | HUMAN | FP&A analyst (data steward) with automated ingestion job |
| 4f3e:TS-02 | FPA-VAR-01 | HYBRID | HUMAN | FP&A analyst (policy/FX configuration sign-off) with computation engine |
| 4f3e:TS-07 | FPA-VAR-01 | HYBRID | HUMAN | FP&A manager (with gated automated distribution) |
| 5ef7:TS-01 | P2P-TWM-01 | AGENT | HUMAN | Matching automation engine, with AP analyst oversight of flagged data-quality exceptions |
| 5ef7:TS-02 | P2P-TWM-01 | AGENT | HUMAN | Tolerance classification engine, with AP supervisor as accountable policy owner |
| 5ef7:TS-04 | P2P-TWM-01 | AGENT | HUMAN | Release control system (clean/in-tolerance lane); AP supervisor (exception and override lane) |
| 8d63:TS-01 | FPA-VAR-01 | AGENT | HUMAN | Automated ingestion pipeline, with FP&A analyst as exception-handler and version-identity validator |
| 8d63:TS-02 | FPA-VAR-01 | AGENT | HUMAN | Automated variance computation engine, with FP&A analyst as anomaly reviewer |
| 517f:T1 | R2R-ACR-01 | AGENT | HUMAN | GL accountant (extraction exception owner), automated extraction/retranslation engine |
| 517f:T2 | R2R-ACR-01 | AGENT | HUMAN | GL accountant (matching exception owner), automated/manual matching engine |
| c32a:TGT-02 | P2P-TWM-01 | AGENT | HUMAN | Automated tolerance-classification engine (system identity: tolerance-classification), with named AP control owner accountable for the policy |
| c32a:TGT-04 | P2P-TWM-01 | AGENT | HUMAN | Automated release engine (system identity: release-automated, distinct from match-execution and tolerance-classification identities) |

## Resulting class counts (239 council steps, 33 TSSs)

| Classification | HUMAN | HYBRID | AGENT |
|---|---:|---:|---:|
| primary | 155 | 42 | 42 |
| agentic-only | 200 | 21 | 18 |

