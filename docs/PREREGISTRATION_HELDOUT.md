# Pre-registration: held-out evaluation

Study: A Multi-Agent Design Council for Outcome-Anchored Redesign of Finance Workflows (CS7P01NM)
Author: Shivantha Meepage
Date: 11 October 2026
Status: committed before the freeze tag and before any held-out run. Nothing in this document changes after the freeze.

## 1. Frozen artefacts

The following are frozen at the freeze tag and hashed in the freeze commit:

- The seven held-out encodings: P2P-TWM-01, P2P-PRE-01, P2P-EXR-01, R2R-ACR-01, R2R-FSP-01, FPA-VAR-01, FPA-ABB-01.
- The specification and sign-off log for those encodings (HELDOUT_SPEC_2026-10-10.md).
- Gate rules, the IFRS/SLFRS knowledge base, all agent prompts, the baseline prompt (disposition convention v1, as used by the development grid; see freeze_notes.md), model and sampling settings.
- The run script and the analysis helper.
- This document.

The held-out set contains 57 steps and 70 rules. 16 steps (28%) are open to elimination by design. These counts are taken from the frozen encodings by `scripts/elimination_space.py`. The specification's 60 rules became 70 encoded requirements: 7 rules are reported qualitatively rather than gated, some rules map to more than one requirement, and survival requirements were added where the pairing test requires them (mapping in HELDOUT_SPEC_2026-10-10.md, encoding log).

## 2. Conditions

- Council: the seven-role Design Council (Maximalist, Pragmatist, Finance Domain, Emerging-Economy Constraint, Human-in-the-Loop Designer, Agentic Architect, Accounting Standards).
- Baseline: a single agent, compute-matched to the council.
- One model family is used for both conditions. A second model family is out of scope. The study tests deliberation, not model choice.

## 3. Sample and run order

- Up to 5 runs per cell, with a pre-registered stopping rule. 7 workflows x 2 conditions = 14 cells; between 56 and 70 runs in total.
- Runs 1 to 4 execute round-robin for every cell: every cell completes run k before any cell starts run k+1. Cells may run in parallel within a round.
- Stopping rule: after run 4, the run script computes the cell's depth for run 3 and run 4. If they are equal, the cell stops at n = 4. If they differ, the cell receives run 5 and stops there. The rule is applied automatically by the script from the deterministic depth computation, without the author inspecting any held-out content.
- A valid cell has n = 4 (stopped by the rule) or n = 5. Any other count is reported as a deviation.
- A technical failure (crash, timeout, malformed output that never reaches the gate) is re-run in the same position. A run that reaches the gate is never discarded or replaced, whatever its result.
- No held-out output is inspected for content until every cell has stopped. Checks during the run are limited to confirming that logs are written.

## 4. Measures

The three measures are defined as in the development phase and are not changed:

- Rule conformance: deterministic gate result against the encoded requirements.
- Transformation depth: computed from the disposition mapping (eliminated, merged, absorbed, retained, restructured).
- Run-to-run consistency: mean pairwise disposition agreement. For two runs of a cell, agreement is the share of baseline steps given the same disposition label. A cell's consistency is the mean agreement over every pair of its runs. The same code is applied to the development grid for comparison (freeze_notes.md).

## 5. Hypotheses and decision rules

### H1 Rule conformance
Expectation: conformance at 1.0 in both conditions, as in the development phase.
Interpretation fixed in advance: a ceiling at 1.0 means the gate is working as designed. Conformance is treated as a validity floor that every acceptable redesign must clear. It is not a discriminator between conditions. Any run below 1.0 is reported individually with the rules it failed.

### H2 Transformation depth
Smallest effect size of interest (SESOI): 0.2, the equivalent of two steps in a ten-step workflow.
Decision rule: H2 is supported if council mean depth exceeds baseline mean depth by at least 0.2 on at least 4 of the 7 held-out workflows.

Conditional conclusion if H2 is not supported: the primary finding becomes the governance value of multi-agent deliberation rather than transformation depth. The thesis will then state that, in standardised and rule-dense finance workflows, deliberation adds value mainly through the controls it introduces, not through deeper structural change.

Elimination: the number of eliminated or absorbed steps is reported for each cell against the 16 steps open to elimination. If no condition eliminates or absorbs any open step, that is reported as a finding about the corpus and the council, not as a limit of the instrument, since the elimination space exists by design.

### H3 Stabilisation (supports the stopping rule)
A cell is stabilised if its run 4 depth equals its run 3 depth (the cell stops at n = 4), or if its run 5 depth equals its run 4 depth (the cell settled by run 5). A cell where run 5 differs from run 4 is reported as not stabilised.
The stabilisation claim is supported if at least 8 of the 14 cells are stabilised.
Because depth moves in coarse quanta, equal consecutive scores can occur by chance. Stopping at n = 4 is therefore reported as an efficiency rule supported by the data, not as proof of convergence.
Cumulative mean and range of depth and consistency are reported for every cell after runs 3, 4 and (where run) 5. Cell means for H2 use all runs in the cell, whether n = 4 or n = 5.

## 6. Qualitative coding of governance controls

1. Every control in each council target-state specification is listed and attributed to the role that introduced it, using the deliberation transcript.
2. The ten controls found in the development phase seed the codebook. New controls are added as they appear and are all reported.
3. Each control is checked for presence in every council run and every baseline run of the same workflow.
4. A control is council-attributed if it appears in at least 60% of that workflow's council runs (3 of 5, or 3 of 4 where the cell stopped at n = 4) and in none of its baseline runs.
5. Results are reported by workflow and by introducing role.

Coding is done by the author. The codebook and every coding decision are logged and committed with the results.

## 7. Deviations

Any departure from this document is recorded with the date, the reason and its effect on interpretation, and is reported in the dissertation. Results that depend on a deviation are labelled as exploratory.
