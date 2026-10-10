# Held-out encoding specification and sign-off log

Date: 10 October 2026, signed off by Shivantha Meepage in chat
Purpose: input for Claude Code to produce the seven held-out `WorkflowEncoding` JSON files.

## Instructions for Claude Code

1. Follow CLAUDE.md discipline: no self-commits, no LLM calls in the gate, no edits to frozen files.
2. Use `p2p_vendor_invoice_processing.json` (VIP) as the structural template and `p2p_three_way_matching.json` as the held-out pattern.
3. Map each requirement below to the EXISTING `rule_type` vocabulary in `design_council/schemas/workflow_encoding.py`. If a requirement does not fit any existing rule type, STOP and report it. Do not add rule types, because that changes the gate.
4. "Outcome rule" means the requirement must be satisfied somewhere in the target state but is not bound to preserving a specific step. Encode it the way the schema expresses outcome-level constraints (check how VIP handles this). If the schema cannot express it, STOP and report.
5. Steps marked OPEN must be listed in `unconstrained_by_design` (or the schema's equivalent).
6. APQC PCF activity IDs: anchor each step to the PCF v8.0 hierarchy where you can verify it. Where you cannot, leave the PENDING PCF VERIFICATION note. Never use an empty list for a pending item (empty list means deliberately unanchored, per the model docstring).
7. Standards references must use the principle IDs from the IFRS/SLFRS KB (14 principles, 7 standards). If a referenced standard has no matching KB principle, report it rather than adding one.
8. Validate every file against `WorkflowEncoding`. Write `HANDOFF_2026-10-11.md` listing: files produced, validation result, every STOP item, every PENDING PCF ID.

## Summary

| ID | Workflow | Area | Steps | Rules | Constrained | Open |
|---|---|---|---|---|---|---|
| P2P-TWM-01 | Three-way matching | P2P | 7 | 9 | 5 | 2 |
| P2P-PRE-01 | Payment run execution | P2P | 8 | 8 | 6 | 2 |
| P2P-EXR-01 | Expense reimbursement | P2P | 8 | 8 | 5 | 3 |
| R2R-ACR-01 | Account reconciliation | R2R | 8 | 7 | 6 | 2 |
| R2R-FSP-01 | Financial statement preparation | R2R | 9 | 10 | 7 | 2 |
| FPA-VAR-01 | Variance analysis | FPA | 8 | 8 | 5 | 3 |
| FPA-ABB-01 | Annual budget build | FPA | 9 | 10 | 7 | 2 |
| **Total** | | | **57** | **60** | **41** | **16** |

Elimination space: 16 of 57 steps (28%) are open to elimination by design. This answers Draft 4 feedback demand 2: the held-out set gives the council genuine room to eliminate.

---

## 1. P2P-TWM-01 Three-way matching (existing draft, amend)

Decisions:
- Requirement density: keep 9 rules constraining 5 of 7 steps.
- Quantity and price matching: protect the match OUTCOME, not two separate steps. Amend the existing rules so both checks must occur but the council may merge the two steps.
- Release approval actor: AP supervisor.

---

## 2. P2P-PRE-01 Payment run execution

| Step | Name | Actor | Rules |
|---|---|---|---|
| PRE-01 | Due-item selection (approved invoices due per terms) | AP analyst | R1 |
| PRE-02 | Payment proposal generation | AP analyst (ERP) | R4 |
| PRE-03 | Proposal review (duplicates, blocked vendors, bank-detail changes) | AP supervisor | R2, R3 |
| PRE-04 | Payment approval | Authorised signatory | R4 |
| PRE-05 | Payment file generation and release to bank | Treasury officer | R4, R5 |
| PRE-06 | Bank confirmation receipt | Treasury officer | OPEN |
| PRE-07 | Posting and clearing (AP subledger, GL cash) | GL accountant | R6, R7 |
| PRE-08 | Remittance advice to vendors | AP analyst | OPEN |

Rules:
- R1 Only matched and approved invoices enter a payment run.
- R2 Duplicate-payment check before approval.
- R3 Vendor bank master data changes independently verified before payment.
- R4 Combined separation rule: propose, approve and release must involve at least two distinct actors.
- R5 Payment file cannot be altered between approval and transmission.
- R6 Liability derecognised only on settlement (IFRS 9).
- R7 Foreign-currency settlement differences recognised in profit or loss (IAS 21).
- R8 Audit trail retained across the run.

Goal layer: capture early-payment discounts (goal, not a gate rule).
Scope: includes foreign-currency payments.

---

## 3. P2P-EXR-01 Expense reimbursement

| Step | Name | Actor | Rules |
|---|---|---|---|
| EXR-01 | Claim submission with receipts | Employee | R1 |
| EXR-02 | Receipt capture and data extraction | AP analyst | OPEN |
| EXR-03 | Policy compliance check (limits, categories, per diem) | AP analyst | R2 |
| EXR-04 | Line manager approval | Line manager | R3 |
| EXR-05 | Finance review | Finance reviewer | OPEN |
| EXR-06 | Posting (expense, cost centre, period) | GL accountant | R5, R6 |
| EXR-07 | Reimbursement via AP payment run | AP analyst | R7 |
| EXR-08 | Employee notification | AP analyst | OPEN |

Rules:
- R1 Receipts required for claim lines above a value threshold; per diem and items below threshold exempt.
- R2 Policy compliance check occurs before approval.
- R3 Approver is not the claimant.
- R4 Duplicate-claim detection (outcome rule, not bound to a step).
- R5 Expense recognised in the period incurred (IAS 1, accrual basis).
- R6 Foreign-currency claims translated at the transaction-date rate (IAS 21).
- R7 Only approved claims are reimbursed.
- R8 Audit trail retained.

Scope: out-of-pocket claims only; corporate cards out of scope. Reimbursement is paid through the AP payment run (links to P2P-PRE-01).

---

## 4. R2R-ACR-01 Account reconciliation

| Step | Name | Actor | Rules |
|---|---|---|---|
| ACR-01 | Extract GL and comparison balances (bank, subledger, third party) | GL accountant | R1, R6 |
| ACR-02 | Transaction matching (auto and manual) | GL accountant | R1 |
| ACR-03 | Investigate and classify reconciling items | GL accountant | R2 |
| ACR-04 | Prepare adjusting journal entries | GL accountant | R3, R5 |
| ACR-05 | Preparer sign-off | GL accountant | OPEN |
| ACR-06 | Reviewer approval | Finance controller | R4 |
| ACR-07 | Escalate aged reconciling items | Finance controller | OPEN |
| ACR-08 | Retain evidence and report status | GL accountant | R7 |

Rules:
- R1 Every in-scope account reconciled at its risk-rated frequency.
- R2 Reconciling differences explained and supported.
- R3 Adjustments booked only through approved journal entries.
- R4 Preparer is not the reviewer (outcome rule; sign-off step may be absorbed).
- R5 Prior-period errors corrected retrospectively (IAS 8).
- R6 Foreign-currency balances retranslated at the closing rate before reconciliation (IAS 21).
- R7 Reconciliation evidence retained.

Scope: all balance-sheet accounts, frequency set by risk rating. No escalation rule.

---

## 5. R2R-FSP-01 Financial statement preparation

| Step | Name | Actor | Rules |
|---|---|---|---|
| FSP-01 | Confirm trial balance close (subledgers closed, recs complete) | GL accountant | R1 |
| FSP-02 | Post period-end adjustments (accruals, provisions, deferrals, cut-off) | GL accountant | R2, R6 |
| FSP-03 | Consolidation and intercompany elimination | Group accountant | R3 |
| FSP-04 | Translate foreign operation | Group accountant | R4 |
| FSP-05 | Map trial balance to statement line items | Financial reporting | R5 |
| FSP-06 | Draft primary statements and key notes | Financial reporting | R5, R7, R8 |
| FSP-07 | Analytical review and tie-out | Financial reporting | OPEN |
| FSP-08 | Management review and approval | CFO | R8, R9 |
| FSP-09 | Release / submission | CFO | OPEN |

Rules:
- R1 Statements prepared only from a closed, reconciled trial balance.
- R2 Period-end adjustments approved before posting.
- R3 Intercompany balances and transactions eliminated (IFRS 10 / SLFRS 10).
- R4 Foreign operation translated, with translation differences in OCI (IAS 21).
- R5 Presentation and minimum line items (IAS 1).
- R6 Revenue cut-off verified at period end (IFRS 15).
- R7 Accounting policy changes and errors disclosed (IAS 8).
- R8 Preparer is not the approver.
- R9 Approval precedes release (outcome rule; FSP-08 and FSP-09 may be merged).
- R10 Audit trail retained.

Scope: group with one foreign subsidiary. Primary statements plus key notes (accounting policies, revenue, FX, errors).

---

## 6. FPA-VAR-01 Variance analysis

| Step | Name | Actor | Rules |
|---|---|---|---|
| VAR-01 | Extract actuals from the closed period | FP&A analyst | R1 |
| VAR-02 | Load approved budget and latest forecast | FP&A analyst | R2 |
| VAR-03 | Compute price, volume and mix variances | FP&A analyst | R6, R7 |
| VAR-04 | Apply materiality thresholds, select variances to explain | FP&A analyst | R3 |
| VAR-05 | Obtain commentary from budget holders | Budget holders | OPEN |
| VAR-06 | Consolidate and draft variance report | FP&A analyst | OPEN |
| VAR-07 | Review and challenge | FP&A manager | R5 |
| VAR-08 | Present and distribute to management | FP&A manager | OPEN |

Rules:
- R1 Actuals only from a locked period.
- R2 Comparatives from the approved budget version and latest forecast.
- R3 Variances exceeding either the percentage or the absolute threshold must be explained.
- R4 Commentary attributed to the accountable budget holder (outcome rule; collection method open, e.g. AI-drafted and holder-confirmed).
- R5 Reviewer independent of commentary author.
- R6 Actuals and budget on the same accounting basis (IAS 1 consistency).
- R7 FX effect isolated at constant currency (IAS 21 rates).
- R8 Version control and audit trail.

---

## 7. FPA-ABB-01 Annual budget build

| Step | Name | Actor | Rules |
|---|---|---|---|
| ABB-01 | Issue calendar and central planning assumptions (inflation, FX, rates) | FP&A manager | R1, R6, R10 |
| ABB-02 | Set top-down targets | CEO / CFO | OPEN |
| ABB-03 | Revenue and volume plans | Business unit heads | R2 |
| ABB-04 | Cost centre and headcount budgets | Cost centre owners | R2 |
| ABB-05 | Capex requests | Business unit heads | R3 |
| ABB-06 | Consolidate into draft P&L, balance sheet, cash flow | FP&A analyst | R4, R5, R6 |
| ABB-07 | Review and challenge iterations | FP&A manager / CFO | OPEN |
| ABB-08 | Board approval | Board | R7 |
| ABB-09 | Load and lock approved version | FP&A analyst | R8 |

Rules:
- R1 Central planning assumptions applied to all submissions.
- R2 Submissions owned by accountable unit heads.
- R3 Capex above threshold requires a business case.
- R4 Budget on the same accounting basis as actuals (IAS 1).
- R5 P&L, balance sheet and cash flow reconcile.
- R6 FX assumptions applied consistently (IAS 21).
- R7 Board approval before lock.
- R8 Locked approved version is the single version used by variance analysis (links to FPA-VAR-01 R2).
- R9 Version audit trail.
- R10 Budget includes at least one downside macro scenario (e.g. LKR depreciation, inflation shock).

Scope: hybrid top-down / bottom-up; three-statement budget.

---

## Encoding log, 11 October 2026

Encoded by Claude Code under the author's decisions of 10 October 2026, 23:55 (B1–B5 in `docs/HELDOUT_ENCODING_STOP_REPORT.md`). The signed-off rule wording above is kept unchanged as the sign-off log. Each encoded statement is the predicate the gate checks (dev convention), with KB principle ids cited where a standards rule is carried.

Decisions applied:
- P2P-TWM-01: the supplied draft (`docs/p2p_three_way_matching.json`) is used as-is. `step_preserved` allows merge, which satisfies "protect the match outcome". TWM-R-10 was added because the pairing test requires it.
- Named mappings: PRE R4 → separation PRE-02/PRE-04; ACR R4 → separation ACR-04/ACR-06; FSP R9 → FSP-08 survives, FSP-09 stays OPEN; VAR R5 → separation VAR-04/VAR-07; ABB R2 → ABB-03 and ABB-04 survive; ABB R8 → ABB-09 survives.
- Standards rules: `inputs_required` on the carrying step where a named input carries the treatment, with the input added to that step's inputs. VAR R6 and ABB R4 cite KB-06 (IAS 8 policy consistency), not IAS 1.
- **Not encoded in the gate, reported qualitatively:** PRE R8, EXR R8, FSP R10, VAR R8, ABB R9 (audit trail), EXR R4 (duplicate-claim detection), VAR R4 (commentary attribution).
- "Pairing (B4)" rows are `step_preserved` requirements added because the pairing test (`tests/test_encodings.py`) requires one for every step named in an ordering or separation rule.
- APQC PCF: every step carries an empty `apqc_activity_ids` with practitioner_note "PENDING PCF VERIFICATION". This is reported as a limitation (57 of 57 steps pending).

Result: 57 steps, 70 requirements, 16 open steps (`scripts/elimination_space.py`). Every encoding scores 1.0 against its own baseline with no vacuous passes.

### P2P-TWM-01 (7 steps, 10 requirements, open: TWM-01, TWM-07)

| Spec rule | Encoded requirement_id | rule_type | Params | Encoded statement |
|---|---|---|---|---|
| Draft TWM-R-01..09 (used as supplied) | TWM-R-01 | `step_preserved` | TWM-02 | Quantity matching against goods receipt data must survive the redesign in some form. |
| Draft TWM-R-01..09 (used as supplied) | TWM-R-02 | `step_preserved` | TWM-03 | Price and terms matching against purchase order data must survive the redesign in some form. |
| Draft TWM-R-01..09 (used as supplied) | TWM-R-03 | `inputs_required` | TWM-02: "Goods receipt note data" | Whatever carries the quantity matching function must still consume goods receipt note data. |
| Draft TWM-R-01..09 (used as supplied) | TWM-R-04 | `inputs_required` | TWM-03: "Purchase order data" | Whatever carries the price and terms matching function must still consume purchase order data. |
| Draft TWM-R-01..09 (used as supplied) | TWM-R-05 | `step_preserved` | TWM-04 | Tolerance evaluation against a stated tolerance policy must survive in some form; matching without a tolerance discipline is not a control. |
| Draft TWM-R-01..09 (used as supplied) | TWM-R-06 | `inputs_required` | TWM-04: "Tolerance policy" | Whatever carries the tolerance evaluation function must still consume the tolerance policy. |
| Draft TWM-R-01..09 (used as supplied) | TWM-R-07 | `step_preserved` | TWM-06 | Match release approval must survive in some form. |
| Draft TWM-R-01..09 (used as supplied) | TWM-R-08 | `ordering_preserved` | TWM-05 → TWM-06 | Exception resolution must occur before match release approval. |
| Draft TWM-R-01..09 (used as supplied) | TWM-R-09 | `actor_separation` | TWM-05, TWM-06 | The exception resolution function and the release approval function must not be performed by the same actor. |
| pairing (B4) | TWM-R-10 | `step_preserved` | TWM-05 | Exception investigation and resolution must survive in some form. |

### P2P-PRE-01 (8 steps, 11 requirements, open: PRE-06, PRE-08)

| Spec rule | Encoded requirement_id | rule_type | Params | Encoded statement |
|---|---|---|---|---|
| R1 | PRE-R-01 | `inputs_required` | PRE-01: "Approved matched invoices" | Whatever carries due-item selection must still consume approved matched invoices. |
| R2 | PRE-R-02 | `ordering_preserved` | PRE-03 → PRE-04 | Proposal review, which includes the duplicate-payment check, must occur before payment approval. |
| R3 | PRE-R-03 | `ordering_preserved` | PRE-03 → PRE-05 | Proposal review, which verifies vendor bank-detail changes, must occur before the payment file is released to the bank. |
| R4 | PRE-R-04 | `actor_separation` | PRE-02, PRE-04 | Payment proposal and payment approval must not be performed by the same actor. |
| R5 | PRE-R-05 | `ordering_preserved` | PRE-04 → PRE-05 | Payment approval must occur before the payment file is generated and released to the bank. |
| R6 | PRE-R-06 | `inputs_required` | PRE-07: "Bank settlement confirmation" | Whatever carries posting and clearing must still consume the bank settlement confirmation (KB-11). |
| R7 | PRE-R-07 | `inputs_required` | PRE-07: "Settlement-date exchange rate" | Whatever carries posting and clearing must still consume the settlement-date exchange rate (KB-08). |
| R8 | NOT ENCODED (qualitative) | – | – | – |
| pairing (B4) | PRE-R-08 | `step_preserved` | PRE-02 | Payment proposal generation must survive in some form. |
| pairing (B4) | PRE-R-09 | `step_preserved` | PRE-03 | Proposal review must survive in some form. |
| pairing (B4) | PRE-R-10 | `step_preserved` | PRE-04 | Payment approval must survive in some form. |
| pairing (B4) | PRE-R-11 | `step_preserved` | PRE-05 | Payment file generation and release must survive in some form. |

### P2P-EXR-01 (8 steps, 10 requirements, open: EXR-02, EXR-05, EXR-08)

| Spec rule | Encoded requirement_id | rule_type | Params | Encoded statement |
|---|---|---|---|---|
| R1 | EXR-R-01 | `inputs_required` | EXR-01: "Receipts for claim lines above the receipt threshold" | Whatever carries claim submission must still consume receipts for claim lines above the receipt threshold. |
| R2 | EXR-R-02 | `ordering_preserved` | EXR-03 → EXR-04 | The policy compliance check must occur before line manager approval. |
| R3 | EXR-R-03 | `actor_separation` | EXR-01, EXR-04 | Claim submission and claim approval must not be performed by the same actor. |
| R4 | NOT ENCODED (qualitative) | – | – | – |
| R5 | EXR-R-04 | `inputs_required` | EXR-06: "Expense transaction date" | Whatever carries posting must still consume the expense transaction date (KB-01). |
| R6 | EXR-R-05 | `inputs_required` | EXR-06: "Transaction-date exchange rate" | Whatever carries posting must still consume the transaction-date exchange rate (KB-07). |
| R7 | EXR-R-06 | `ordering_preserved` | EXR-04 → EXR-07 | Line manager approval must occur before reimbursement. |
| R8 | NOT ENCODED (qualitative) | – | – | – |
| pairing (B4) | EXR-R-07 | `step_preserved` | EXR-03 | The policy compliance check must survive in some form. |
| pairing (B4) | EXR-R-08 | `step_preserved` | EXR-04 | Line manager approval must survive in some form. |
| pairing (B4) | EXR-R-09 | `step_preserved` | EXR-07 | Reimbursement must survive in some form. |
| pairing (B4) | EXR-R-10 | `step_preserved` | EXR-01 | Claim submission must survive in some form. |

### R2R-ACR-01 (8 steps, 9 requirements, open: ACR-05, ACR-07)

| Spec rule | Encoded requirement_id | rule_type | Params | Encoded statement |
|---|---|---|---|---|
| R1 | ACR-R-01 | `inputs_required` | ACR-01: "Reconciliation schedule by account risk rating" | Whatever carries balance extraction must still consume the reconciliation schedule by account risk rating. |
| R1 | ACR-R-02 | `step_preserved` | ACR-02 | Transaction matching must survive in some form. |
| R2 | ACR-R-03 | `step_preserved` | ACR-03 | Investigation and classification of reconciling items must survive in some form. |
| R3 | ACR-R-04 | `step_preserved` | ACR-04 | Preparation of adjusting journal entries must survive in some form. |
| R4 | ACR-R-05 | `actor_separation` | ACR-04, ACR-06 | Journal entry preparation and reconciliation review must not be performed by the same actor. |
| R5 | ACR-R-06 | `inputs_required` | ACR-04: "Prior-period error record" | Whatever carries preparation of adjusting journal entries must still consume the prior-period error record (KB-05). |
| R6 | ACR-R-07 | `inputs_required` | ACR-01: "Closing exchange rates" | Whatever carries balance extraction must still consume closing exchange rates (KB-07). |
| R7 | ACR-R-08 | `step_preserved` | ACR-08 | Retention of reconciliation evidence must survive in some form. |
| pairing (B4) | ACR-R-09 | `step_preserved` | ACR-06 | Reviewer approval must survive in some form. |

### R2R-FSP-01 (9 steps, 11 requirements, open: FSP-07, FSP-09)

| Spec rule | Encoded requirement_id | rule_type | Params | Encoded statement |
|---|---|---|---|---|
| R1 | FSP-R-01 | `ordering_preserved` | FSP-01 → FSP-06 | Trial balance close must be confirmed before the primary statements are drafted. |
| R2 | FSP-R-02 | `inputs_required` | FSP-02: "Approved period-end adjustment schedule" | Whatever carries posting of period-end adjustments must still consume the approved period-end adjustment schedule. |
| R3 | FSP-R-03 | `inputs_required` | FSP-03: "Intercompany balances and transactions" | Whatever carries consolidation must still consume intercompany balances and transactions (KB-14). |
| R4 | FSP-R-04 | `inputs_required` | FSP-04: "Closing and average exchange rates" | Whatever carries translation of the foreign operation must still consume closing and average exchange rates (KB-07, KB-08). |
| R5 | FSP-R-05 | `inputs_required` | FSP-05: "Statement line-item structure" | Whatever carries mapping to statement line items must still consume the statement line-item structure (KB-02). |
| R6 | FSP-R-06 | `inputs_required` | FSP-02: "Revenue cut-off evidence" | Whatever carries posting of period-end adjustments must still consume revenue cut-off evidence (KB-13, KB-03). |
| R7 | FSP-R-07 | `inputs_required` | FSP-06: "Accounting policy change and prior-period error record" | Whatever carries drafting of the statements and notes must still consume the accounting policy change and prior-period error record (KB-05, KB-06). |
| R8 | FSP-R-08 | `actor_separation` | FSP-06, FSP-08 | Statement drafting and management approval must not be performed by the same actor. |
| R9 | FSP-R-09 | `step_preserved` | FSP-08 | Management review and approval must survive in some form. |
| R10 | NOT ENCODED (qualitative) | – | – | – |
| pairing (B4) | FSP-R-10 | `step_preserved` | FSP-01 | Confirmation of trial balance close must survive in some form. |
| pairing (B4) | FSP-R-11 | `step_preserved` | FSP-06 | Drafting of the primary statements and key notes must survive in some form. |

### FPA-VAR-01 (8 steps, 8 requirements, open: VAR-05, VAR-06, VAR-08)

| Spec rule | Encoded requirement_id | rule_type | Params | Encoded statement |
|---|---|---|---|---|
| R1 | VAR-R-01 | `inputs_required` | VAR-01: "Locked-period actuals" | Whatever carries extraction of actuals must still consume locked-period actuals. |
| R2 | VAR-R-02 | `inputs_required` | VAR-02: "Approved budget version; Latest forecast" | Whatever carries loading of comparatives must still consume the approved budget version and the latest forecast. |
| R3 | VAR-R-03 | `inputs_required` | VAR-04: "Materiality thresholds (percentage and absolute)" | Whatever carries selection of variances to explain must still consume the percentage and absolute materiality thresholds. |
| R4 | NOT ENCODED (qualitative) | – | – | – |
| R5 | VAR-R-04 | `actor_separation` | VAR-04, VAR-07 | Selection of variances to explain and review of the variance report must not be performed by the same actor. |
| R6 | VAR-R-05 | `inputs_required` | VAR-03: "Accounting policies applied to actuals" | Whatever carries variance computation must still consume the accounting policies applied to actuals (KB-06). |
| R7 | VAR-R-06 | `inputs_required` | VAR-03: "Constant-currency exchange rates" | Whatever carries variance computation must still consume constant-currency exchange rates (KB-07). |
| R8 | NOT ENCODED (qualitative) | – | – | – |
| pairing (B4) | VAR-R-07 | `step_preserved` | VAR-07 | Review and challenge of the variance report must survive in some form. |
| pairing (B4) | VAR-R-08 | `step_preserved` | VAR-04 | Application of materiality thresholds must survive in some form. |

### FPA-ABB-01 (9 steps, 11 requirements, open: ABB-02, ABB-07)

| Spec rule | Encoded requirement_id | rule_type | Params | Encoded statement |
|---|---|---|---|---|
| R1 | ABB-R-01 | `step_preserved` | ABB-01 | Issue of the budget calendar and central planning assumptions must survive in some form. |
| R2 | ABB-R-02 | `step_preserved` | ABB-03 | Revenue and volume planning must survive in some form. |
| R2 | ABB-R-03 | `step_preserved` | ABB-04 | Cost centre and headcount budgeting must survive in some form. |
| R3 | ABB-R-04 | `inputs_required` | ABB-05: "Business case for capex above threshold" | Whatever carries capex requests must still consume a business case for capex above threshold. |
| R4 | ABB-R-05 | `inputs_required` | ABB-06: "Accounting policies applied to actuals" | Whatever carries consolidation of the draft budget must still consume the accounting policies applied to actuals (KB-06). |
| R5 | ABB-R-06 | `step_preserved` | ABB-06 | Consolidation into a draft P&L, balance sheet and cash flow must survive in some form. |
| R6 | ABB-R-07 | `inputs_required` | ABB-06: "Central FX assumptions" | Whatever carries consolidation of the draft budget must still consume the central FX assumptions (KB-07). |
| R7 | ABB-R-08 | `ordering_preserved` | ABB-08 → ABB-09 | Board approval must occur before the approved version is loaded and locked. |
| R8 | ABB-R-09 | `step_preserved` | ABB-09 | Loading and locking of the approved version must survive in some form. |
| R9 | NOT ENCODED (qualitative) | – | – | – |
| R10 | ABB-R-10 | `inputs_required` | ABB-01: "Downside macro scenario" | Whatever carries issue of the central planning assumptions must still consume a downside macro scenario. |
| pairing (B4) | ABB-R-11 | `step_preserved` | ABB-08 | Board approval must survive in some form. |
