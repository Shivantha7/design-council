# Classification of held-out conformance failures (exploratory)

**Exploratory and not pre-registered. No score is changed.** Table X.2
(`docs/RESULTS_HELDOUT_tables.md`) and every gate result stand as recorded. The
deterministic gate's verdict is the result. This note only describes *why* each of the
10 runs fell below 1.0, as context for interpreting H1.

Classes:
- **SUBSTANTIVE**: the control or input is genuinely missing from a carrying step.
- **NAMING**: the input is present under a different name, so the gate's exact-string
  match (`inputs_required`) did not recognise it.
- **UNCLEAR**: the evidence supports more than one reading.

Method: for each failed requirement, I read the gate reason (`gate_result.json`), the
disposition and carrying target steps (`tss.json`) and the relevant deliberation passage
(`calls.jsonl`, council runs). Baseline runs have no deliberation, so their disposition
rationale is quoted instead. Quotes are verbatim; "…" marks truncation.

## Summary

| Class | Council | Baseline | Total |
|---|---:|---:|---:|
| NAMING | 8 | 0 | 8 |
| SUBSTANTIVE | 1 | 0 | 1 |
| UNCLEAR | 0 | 1 | 1 |
| **Total** | **9** | **1** | **10** |

All 10 failures are `inputs_required` rules. In the 8 NAMING cases, the carrying step lists
the required input with a **parenthetical qualifier appended**, for example "Tolerance policy
(versioned)". The qualifier comes directly from the deliberation, where a role argued for
the extra property: versioning, a manual fallback, invoice-level detail, or a paper/scan
channel. Exact matching treats the qualified string as a different input. That is the
gate's documented behaviour (FPA-R-02 is bound verbatim and tested; see
`tests/test_encodings.py`), and the scores stand.

## Per run

### 1. 20261010-185003-council-P2P-TWM-01-6c3b: TWM-R-06, NAMING
- **Required input:** "Tolerance policy" on the step carrying TWM-04.
- **Gate:** "TS-02 is missing ['Tolerance policy']".
- **TSS (TS-02 inputs):** "Tolerance policy (versioned, centrally governed with locally parameterized bands)".
- **Transcript (round1_finance_domain):** "It must, however, retain the tolerance policy as an explicit, versioned input to Step 1 — this is where the control actually lives, and it must not become an opaque hard-coded threshold invisible to audit."

### 2. 20261010-194038-council-P2P-TWM-01-0842: TWM-R-06, NAMING
- **Required input:** "Tolerance policy".
- **Gate:** "TS-02 is missing ['Tolerance policy']".
- **TSS (TS-02 inputs):** "Tolerance policy (versioned)".
- **Transcript (round1_pragmatist):** "Tolerance policy is a governance artefact that controllers and procurement jointly own, gets revised periodically (currency thresholds, category-specific bands, override rules), and needs its own change-control trail…"

### 3. 20261010-203143-council-P2P-TWM-01-5ef7: TWM-R-06, NAMING
- **Required input:** "Tolerance policy".
- **Gate:** "TS-02 is missing ['Tolerance policy']".
- **TSS (TS-02 inputs):** "Tolerance policy (versioned)".
- **Transcript (round1_pragmatist):** "…the classification output (clean / tolerance / exception) and the tolerance policy version applied must remain a separately visible, logged artifact…"

### 4. 20261010-205046-council-P2P-TWM-01-c32a: TWM-R-06, NAMING
- **Required input:** "Tolerance policy".
- **Gate:** "TGT-02 is missing ['Tolerance policy']".
- **TSS (TGT-02 inputs):** "Tolerance policy (versioned, human-governed)".
- **Transcript (round1_finance_domain):** "Tolerance evaluation is a *policy application*, not a *computation*: someone owns the tolerance table, it gets recalibrated, and auditors ask \"what tolerance was in force on this date and who approved it.\""

### 5. 20261010-194035-council-P2P-PRE-01-64dc: PRE-R-07, NAMING
- **Required input:** "Settlement-date exchange rate".
- **Gate:** "TS-06 is missing ['Settlement-date exchange rate']".
- **TSS (TS-06 inputs):** "Settlement-date exchange rate (with documented manual fallback)".
- **Transcript (round1_emerging_economy):** "Both the bank settlement confirmation and the settlement-date exchange rate inputs are preserved per the requirements, with an explicit manual-entry fallback path for the FX rate where no live feed is licensed."

### 6. 20261010-201339-council-P2P-PRE-01-8682: PRE-R-06, NAMING
- **Required input:** "Bank settlement confirmation".
- **Gate:** "TGT-07 is missing ['Bank settlement confirmation']".
- **TSS (TGT-07 inputs):** "Bank settlement confirmation (invoice-level)".
- **Transcript (round2_agentic_architect):** "…the matching function's output schema must carry invoice-level allocation through to the posting entry, because that's what makes derecogniti…"

### 7. 20261010-201338-council-P2P-EXR-01-2ec9: EXR-R-01, NAMING
- **Required input:** "Receipts for claim lines above the receipt threshold".
- **Gate:** "T1 is missing […]".
- **TSS (T1 inputs):** "Receipts for claim lines above the receipt threshold (app photo or paper/scan upload)".
- **Transcript (round1_emerging_economy):** "A redesigned target step must keep a manual/paper-and-scan submission path alongside any mobile app, because smartphone penetration, data-plan costs and corporate device provisioning are uneven across offshore and field-based workforces."

### 8. 20261010-192227-council-FPA-ABB-01-333a: ABB-R-07, NAMING
- **Required input:** "Central FX assumptions".
- **Gate:** "T5 is missing ['Central FX assumptions']".
- **TSS (T5 inputs):** "Central FX assumptions (versioned)".
- **Transcript (synthesis, T5 description):** "A single, version-controlled Consolidation Agent performs the mechanical roll-up of T3/T4 submissions, applies the central FX assumptions and the same accounting policies used for actuals…"

### 9. 20261010-205048-council-R2R-FSP-01-106a: FSP-R-06, SUBSTANTIVE
- **Required input:** "Revenue cut-off evidence" on every step carrying FSP-02.
- **Gate:** "TS-02a is missing ['Revenue cut-off evidence']".
- **TSS:** FSP-02 is split into TS-02a (automated mechanical posting) and TS-02b (estimate review). The cut-off evidence goes to TS-02b only, yet TS-02a's description says it posts "deterministic cut-off entries".
- **Disposition rationale:** "TS-02b additionally consumes revenue cut-off evidence (FSP-R-06), since cut-off judgment calls are the estimation-adjacent subset of this function."
- **Transcript (round2_agentic_architect):** "I concede the point: TS-02 should split into two named target steps — an agent-executed mechanical-posting step and a separate, human-owned \"estimate-based adjustment review and approval\" step…"
- **Reading:** the omission is deliberate, not accidental. Even so, a step that posts cut-off entries has no cut-off evidence among its inputs, so the input is genuinely missing from one of the two carrying steps.

### 10. 20261010-193948-baseline-P2P-PRE-01-208e: PRE-R-06, UNCLEAR
- **Required input:** "Bank settlement confirmation".
- **Gate:** "TS-05 is missing ['Bank settlement confirmation']".
- **TSS:** the bank-confirmation step (PRE-06) is absorbed into TS-05. TS-05's inputs are "Payment file transmitted to bank", "Bank statement", "Settlement-date exchange rate" and "AP subledger open items". Its outputs include "Bank settlement confirmation". Its description: "An automated bank reconciliation engine ingests the bank statement/confirmation feed, matches executed payments to the transmitted file, and triggers posting of settled payments…"
- **Disposition rationale (baseline, no deliberation):** "Posting and clearing survives but is restructured to be automation-driven, continuing to consume the bank settlement confirmation (PRE-R-06)…"
- **Reading:** two readings are open.
  - NAMING: the step ingests the confirmation feed, listed as "Bank statement", and produces the confirmation itself.
  - SUBSTANTIVE: the listed input is a statement, not the settlement confirmation.

  The rationale claims the confirmation is consumed, but the input list does not show it.

## Observations (descriptive)

- Every NAMING case is an `inputs_required` string carrying a qualifier the council
  argued for. These redesigns kept the required input and specified it further, and
  exact matching does not credit that. All 8 NAMING cases are council runs.
- The single SUBSTANTIVE case follows a deliberate council design choice: splitting a step
  and routing evidence to one half only.
- Under the pre-registration, H1's interpretation is fixed: conformance is a validity floor
  and every run below 1.0 is reported individually (Table X.2). This classification adds
  context to that report and changes nothing in it.
