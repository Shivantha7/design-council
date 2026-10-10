# Held-out encodings: STOP report against HELDOUT_SPEC_2026-10-10.md

> **Resolved, 11 October 2026.** The author decided B1–B5 on 10 October 2026,
> 23:55. The encodings were produced under those decisions. See the encoding
> log at the end of `docs/HELDOUT_SPEC_2026-10-10.md`. This report is kept as
> the record of why each decision was needed.

Prepared 11 October 2026 for the author's decision. **No held-out encoding has
been written.** `data/encodings/heldout/` still contains only `.gitkeep`.

The spec's own instructions require a stop. Instruction 3 says to stop when a
requirement fits no existing `rule_type`. Instruction 4 says to stop when an
outcome rule cannot be expressed. Instruction 6 forbids an empty PCF list for a
pending anchor. All three conditions occur, and each one changes what would be
frozen. The pre-registration (§1) fixes the totals at 57 steps, 60 rules and
16 open steps, so the encodings cannot be written provisionally and patched
later.

## The gate vocabulary

There are five rule types (`design_council/gate/gate.py`). Every one is bound
to baseline step ids, and none inspects content.

| rule_type | Checks | On eliminate | On merge / absorb |
|---|---|---|---|
| `step_preserved` | step not eliminated | fails | passes |
| `inputs_required` | carrying target steps list given input strings (exact match) | fails | checks carrying steps |
| `ordering_preserved` | all targets of A strictly precede all targets of B | **passes vacuously** | **fails if A and B land in the same target step** |
| `actor_separation` | carrying target steps of the listed steps share **no** actor, pairwise | **passes vacuously** | **fails if both land in the same target step** |
| `disposition_in` | disposition within an allowed set | per set | per set |

The schema has no outcome-level form: no rule type is unbound from a step.
VIP, the named template, contains no outcome rules to copy.

## Blocking items

**B1. P2P-TWM-01 cannot be produced.** The spec says "existing draft, amend"
and names `p2p_three_way_matching.json` as the held-out pattern. That file does
not exist on this machine (I searched the whole disk and all git history), and
the spec gives no step table for TWM. Its 7 steps and 9 rules are unknown.
Needed: the draft file.

**B2. Rules no rule type can express (instruction 3/4 STOP).**

| Rule | Why it cannot be expressed |
|---|---|
| PRE R8, EXR R8, FSP R10, VAR R8, ABB R9 (audit trail / version trail) | Bound to no step in the spec tables, and no rule type is step-unbound |
| EXR R4 (duplicate-claim detection, "not bound to a step") | Same: an explicit step-unbound outcome rule |
| VAR R4 (commentary attributed to budget holder, "collection method open") | Same. Its natural home, VAR-05, is OPEN |
| FSP R9 (approval precedes release; "FSP-08 and FSP-09 may be merged") | `ordering_preserved` **fails** when both steps merge into one target step, so the permitted merge would be scored as a violation |
| ACR R4 (preparer is not the reviewer; "sign-off step may be absorbed") | `actor_separation(ACR-05, ACR-06)` fails if ACR-05 is absorbed into the reviewer's step, and passes vacuously if ACR-05 (OPEN) is eliminated. One option that survives both: `actor_separation(ACR-04, ACR-06)`, which reads "preparer" as the journal preparer. That is an interpretive choice for you |
| PRE R4 ("propose, approve and release must involve at least two distinct actors") | `actor_separation` requires pairwise-distinct actors, which is stricter (three distinct). Options: three-way pairwise (stricter than signed off) or one pair, e.g. PRE-02/PRE-04 (weaker). There is no exact form |

That is 11 of the 51 specified rules (TWM excluded). Options: (a) reword each
to an expressible predicate and record the change in the sign-off log; (b) drop
it from the gate and report it qualitatively; (c) add a rule type. Option (c)
changes the gate, which the spec forbids without a decision.

**B3. Most remaining rules are checkable only as a structural proxy.** These
include the standards rules (IFRS 9 derecognition, IAS 21 rates, IAS 8
retrospective correction, IFRS 15 cut-off, IAS 1 basis and presentation) and
the content rules (thresholds, "only approved", "cannot be altered",
"independently verified"). The gate can check that the carrying step survives
(`step_preserved`) or that it consumes a named input (`inputs_required`). It
cannot check the accounting treatment itself. The dev corpus handled this by
writing each statement as its predicate (for example "Payment execution must
survive in some form"), because the gate quotes the statement verbatim in its
output. Encoding the spec's wording over a survival check would overstate what
a pass means. Needed: confirmation that held-out statements may be reworded to
their predicates in the dev convention, with the signed-off wording kept in
the sign-off log.

| Workflow | Expressible as stated (structural) | Proxy only (needs predicate wording) |
|---|---|---|
| P2P-PRE-01 | R2 `ordering_preserved` PRE-03→PRE-04 | R1, R3, R5, R6, R7 |
| P2P-EXR-01 | R2 ordering EXR-03→EXR-04; R3 `actor_separation` EXR-01/EXR-04; R7 ordering EXR-04→EXR-07 | R1, R5, R6 |
| R2R-ACR-01 | none | R1, R2, R3, R5, R6, R7 |
| R2R-FSP-01 | R8 `actor_separation` FSP-06/FSP-08 | R1, R2, R3, R4, R5, R6, R7 |
| FPA-VAR-01 | none (R5 needs an author choice of commentary step, and VAR-05 is OPEN) | R1, R2, R3, R6, R7 |
| FPA-ABB-01 | R7 ordering ABB-08→ABB-09 | R1, R2 (no actor-identity rule type), R3, R4, R5, R6, R8 (cross-workflow link), R10 |

**B4. The pairing test will raise the rule count above 60.** Since `ec273e2`,
every step named in an ordering or separation rule must carry a
`step_preserved` requirement or be listed OPEN. Otherwise eliminating the step
silences its own rule. Under the mappings above, steps the spec marks
constrained but which would be bound only relationally include EXR-03, EXR-04,
EXR-07, PRE-02 and PRE-04 (if R4 binds them), ABB-08 and ACR-06 (if R4 binds
it). Each one needs an extra `step_preserved`. The number depends on B2 and B3,
but the total will not be 60 unless rules are merged. **The pre-registration
§1 counts (57 steps, 60 rules, 16 open) must be re-derived from the final
encodings before the freeze.** `scripts/elimination_space.py` gives the open
count mechanically.

**B5. PENDING PCF IDs cannot be represented.** `SourceMappingEntry.apqc_activity_ids`
is `list[int]`. The only way to record "pending" is an empty list plus a note,
and instruction 6 forbids that because an empty list means "deliberately
unanchored". I also cannot verify any PCF v8.0 ID here, as the PCF document is
not in the repo and IDs from memory would be unverified. So, as things stand,
**every held-out step's PCF ID is PENDING (57 of 57)**. Options: (a) omit
`source_mapping` entirely, which the schema allows and which means "not
source-mapped"; (b) add a schema field for pending verification, which is a
contract change; (c) supply the verified IDs.

## Not blocking

- **KB coverage (instruction 7).** Every cited standard has KB principles:
  IAS 1 → KB-01..03, IAS 8 → KB-04..06, IAS 21 → KB-07/08, IFRS 9 → KB-11,
  IFRS 15 → KB-13, IFRS 10 → KB-14. One near miss to report: VAR R6 and ABB R4
  cite "IAS 1 consistency" of accounting basis. No IAS 1 KB principle covers
  that. The closest is KB-06 (IAS 8, policy consistency). I have not added a
  principle.
- **Requirements carry no KB field.** `Requirement` forbids extra fields, so a
  KB principle id could appear only in the statement text. That is consistent
  with dev, which cites none.
- **Cross-workflow links** (EXR→PRE payment run, ABB R8→VAR R2) cannot be
  checked by a per-workflow gate. They are scope notes only.
