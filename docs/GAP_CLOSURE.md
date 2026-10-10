# Pairing-gap closure and elimination space

Generated 10 October 2026 from commit history and the encoding files. Every
figure in the tables is reproducible with `python scripts/elimination_space.py`
(read-only, deterministic, no model calls).

## What a pairing gap is

Relational rules (`ordering_preserved`, `actor_separation`) pass **vacuously**
when the step they constrain is eliminated: if there is no step, there is nothing
left to be out of order or under the wrong actor. A step that is constrained
*only* relationally can therefore be deleted to silence its own rule, and the
gate still scores 1.0. A pairing gap is a relationally constrained step with no
survival requirement (`step_preserved`) and no recorded decision to leave it
open.

Only two rule types fail when their step is eliminated: `step_preserved` and
`inputs_required` (`design_council/gate/gate.py`, `_step_preserved` and
`_inputs_required`). Those are the only rules that "protect" a step.

## How the three gaps were closed

All three were closed in one commit, `ec273e2` (27 Aug 2026, "Dev corpus:
pairing-completeness audit, VIP-R-08/R2R-R-07/FPA-R-05, SoD fixture"). All three
were closed by **adding a survival requirement**. None was closed by adding the
step to the open list.

| # | Encoding | Step | Relational rule that left it exposed | Closure mechanism | Requirement added | Commit |
|---|---|---|---|---|---|---|
| 1 | P2P-VIP-01 | VIP-07 (payment execution) | VIP-R-04 `ordering_preserved` VIP-05 → VIP-07 | Survival requirement added | VIP-R-08 `step_preserved` VIP-07 | `ec273e2` |
| 2 | R2R-PC-01 | PC-07 (close review) | R2R-R-04 `ordering_preserved` PC-07 → PC-08 (also in R2R-R-05 `actor_separation`) | Survival requirement added | R2R-R-07 `step_preserved` PC-07 | `ec273e2` |
| 3 | FPA-RF-01 | RF-08 (publication) | FPA-R-04 `ordering_preserved` RF-07 → RF-08 | Survival requirement added | FPA-R-05 `step_preserved` RF-08 | `ec273e2` |

The same commit made the audit permanent rather than one-off:

- `WorkflowEncoding.unconstrained_by_design` was added: the list of steps
  deliberately left open to elimination.
- `tests/test_encodings.py::test_relational_requirements_are_paired_with_a_survival_decision`
  runs over **every** encoding under `data/encodings/` (dev and held-out). It
  asserts that each step named in a relational rule is either `step_preserved`
  or listed in `unconstrained_by_design`. A held-out encoding with an unpaired
  step therefore fails the suite.
- `test_unconstrained_steps_are_not_also_step_preserved` rules out the
  contradiction of a step that is both protected and listed as open.

**One relationally constrained step was left open on purpose.** PC-02 appears
in the separation rule R2R-R-05 (PC-02 / PC-07) but is listed in
`unconstrained_by_design`. Eliminating PC-02 would pass R2R-R-05 vacuously.
That is a recorded design decision, not a gap. The step is open as to survival,
and the separation rule still binds if the step survives.

### Provenance caveat

Only gap 1 is visible as a before/after in git. P2P-VIP-01 was committed without
VIP-R-08 at `245ef33` and amended at `ec273e2`. R2R-PC-01 and FPA-RF-01 were
**first committed** in `ec273e2`, with R2R-R-07 and FPA-R-05 already present.
Their pre-closure state was never committed. The evidence that PC-07 and RF-08
were gaps is the commit message, together with the pairing test, which would
fail without those requirements. The R2R and FPA "before" figures below are
therefore counterfactual: they are computed by removing the one requirement
each.

## Elimination space per encoding

"Gate-open" means steps a TSS could eliminate without failing any gate rule.
"Documented open" means steps listed in `unconstrained_by_design`. The script
checks that the two sets are identical.

### Development encodings (current state)

| Workflow | Split | Steps | Protected (fail if eliminated) | Documented open (unconstrained_by_design) | Gate-open | Check |
|---|---|---:|---|---|---:|---|
| FPA-RF-01 | dev | 8 | 4 (RF-05, RF-06, RF-07, RF-08) | 4 (RF-01, RF-02, RF-03, RF-04) | 4/8 | ok |
| P2P-VIP-01 | dev | 8 | 5 (VIP-03, VIP-05, VIP-06, VIP-07, VIP-08) | 3 (VIP-01, VIP-02, VIP-04) | 3/8 | ok |
| R2R-PC-01 | dev | 8 | 4 (PC-04, PC-05, PC-07, PC-08) | 4 (PC-01, PC-02, PC-03, PC-06) | 4/8 | ok |

RF-05 is protected by `inputs_required` (FPA-R-02), not by `step_preserved`.
`inputs_required` fails on elimination ("no target step carries the required
input(s)"), so RF-05 cannot be eliminated without a gate failure, even though it
has no survival requirement of its own.

### Before and after the audit

| Workflow | Gate-open before | Gate-open after | Basis for "before" |
|---|---:|---:|---|
| P2P-VIP-01 | 4/8 (VIP-01, 02, 04, 07; none documented) | 3/8 | Committed state at `245ef33` (re-run through the script) |
| R2R-PC-01 | 5/8 (adds PC-07) | 4/8 | Counterfactual: `ec273e2` without R2R-R-07 |
| FPA-RF-01 | 5/8 (adds RF-08) | 4/8 | Counterfactual: `ec273e2` without FPA-R-05 |
| **Dev corpus** | **14/24** | **11/24** | |

### Held-out encodings

Encoded 11 October 2026 (`docs/HELDOUT_SPEC_2026-10-10.md`, encoding log).
Output of `python scripts/elimination_space.py data/encodings/heldout/*.json`:

| Workflow | Split | Steps | Protected (fail if eliminated) | Documented open (unconstrained_by_design) | Gate-open | Check |
|---|---|---:|---|---|---:|---|
| FPA-ABB-01 | heldout | 9 | 7 (ABB-01, ABB-03, ABB-04, ABB-05, ABB-06, ABB-08, ABB-09) | 2 (ABB-02, ABB-07) | 2/9 | ok |
| FPA-VAR-01 | heldout | 8 | 5 (VAR-01, VAR-02, VAR-03, VAR-04, VAR-07) | 3 (VAR-05, VAR-06, VAR-08) | 3/8 | ok |
| P2P-EXR-01 | heldout | 8 | 5 (EXR-01, EXR-03, EXR-04, EXR-06, EXR-07) | 3 (EXR-02, EXR-05, EXR-08) | 3/8 | ok |
| P2P-PRE-01 | heldout | 8 | 6 (PRE-01, PRE-02, PRE-03, PRE-04, PRE-05, PRE-07) | 2 (PRE-06, PRE-08) | 2/8 | ok |
| P2P-TWM-01 | heldout | 7 | 5 (TWM-02, TWM-03, TWM-04, TWM-05, TWM-06) | 2 (TWM-01, TWM-07) | 2/7 | ok |
| R2R-ACR-01 | heldout | 8 | 6 (ACR-01, ACR-02, ACR-03, ACR-04, ACR-06, ACR-08) | 2 (ACR-05, ACR-07) | 2/8 | ok |
| R2R-FSP-01 | heldout | 9 | 7 (FSP-01, FSP-02, FSP-03, FSP-04, FSP-05, FSP-06, FSP-08) | 2 (FSP-07, FSP-09) | 2/9 | ok |

**Held-out total: 16 of 57 steps gate-open (28%)**, every one of them
documented, matching the specification. The pairing test added 15
`step_preserved` requirements across the set. Each closes a relational gap at
encoding time rather than after the fact. Open steps per workflow: TWM 2/7,
PRE 2/8, EXR 3/8, ACR 2/8, FSP 2/9, VAR 3/8, ABB 2/9.

## Conclusion

Yes, the audit narrowed the elimination space. On the development corpus it
went from **14/24** gate-open steps (three of them undocumented relational gaps)
to **11/24**, every one of them documented as deliberately open. All three
closures protected an ordering-constrained terminal or control step (payment,
close review, publication). None closed a gap by declaring it open. The 11
remaining open steps (3/8, 4/8, 4/8) are real room for elimination. The zero
elimination count in all 176 dev-grid dispositions is therefore not a ceiling
imposed by the gate.
