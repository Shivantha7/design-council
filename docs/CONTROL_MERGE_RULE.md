# Control merge rule (pre-registration section 6 coding)

Author's rule, recorded verbatim, 11 October 2026. Applied to the 307 control candidates
in `docs/CONTROL_CODING_CANDIDATES.md` before the section 6 rule 4 threshold is applied
to merged controls.

> MERGE two candidates if they describe the same control mechanism acting at
> the same point in the workflow (same object, same check or action), differing
> only in wording or granularity. DO NOT MERGE related but distinct controls
> (a check vs its escalation; preventive vs detective; checks on different
> objects). BASELINE EQUIVALENCE: if any baseline run of the same workflow
> contains a control meeting the same test, the merged control fails baseline,
> whatever its wording.

## Author's decisions, 11 October 2026

> ONE EVIDENCE STANDARD: re-judge every baseline-equivalence call with exactly
> the same test used for council presence (same wording tolerance both ways).
>
> NO SPLITS. Candidates possibly holding two controls stay whole; list them
> as a limitation.

**Operational test used to implement the single standard** (applied identically
to every council and baseline run, one judging pass per control): a run *has* a
control if its TSS states the same mechanism (the same check or action) acting on
the same object at the same point in the workflow. Wording is irrelevant. A less
detailed statement of that same mechanism counts. A statement of principle or goal
with no operative mechanism does not count. Where the mechanism comes from (council
deliberation, the encoding's requirements, the current-state workflow) does not
matter. A run is marked *borderline* when its text could reasonably be read either
way under this test. Borderline calls are resolved by the author, pattern by
pattern.

**Limitation: candidates that may hold two controls, kept whole.** ACR-C27,
ACR-C42, PRE-C17, PRE-C33, FSP-C05, FSP-C34, ABB-C03, ABB-C09, VAR-C04, VAR-C06,
VAR-C10, VAR-C24, EXR-C16. Each is scored as one control. A split could add a
control or change an outcome.

## Author's decisions on the decision patterns, 11 October 2026

Recorded verbatim:

> B1 = A (implicit baseline performance counts as baseline having the control)
> B2 = no (a principle/accountability statement is not an operative mechanism)
> B3 = no (a neighbouring step is a different point)
> B5 = yes (same check by a different performer is the same control)
> M1 = merge (directional/variant pairs on the same object are one control)
> M2 = merge (a check and its own record/log are one control)
> M3 = keep separate (same mechanism at adjacent points)
> B4 / M4 = distinct (subsets, lanes or overlapping objects are not the same control)

Pattern definitions are as listed in `docs/CONTROL_DECISIONS_PENDING.md`. In
presence terms: a B1 or B5 borderline run counts as present; a B2, B3 or B4
borderline run counts as absent; M1 and M2 pairs are merged (presence is the union
of the members'); M3 and M4 pairs stay separate. One-offs that are instances of
these principles are resolved by them. Genuinely new one-offs are listed for the
author, and an undecidable one-off defaults to the outcome that does not pass.

## Final author decisions, 11 October 2026

- **Attribute, property or component of a mechanism = the same control: MERGE.**
  Applied to 9 cases: ABB-M15+M13, EXR-M02+M03, EXR-M24+M23, TWM-M24+M23,
  TWM-M37+M36, ACR-M07+M14, ACR-M23+M22, ACR-M28+M26, FSP-M03+M01.
- **One-off recommendations accepted:**
  - EXR-M27 is present in the four baselines where finance review is folded into the posting step.
  - ACR-M29/M26 and ABB-M27/M21 are kept separate.
  - VAR-M05 is dropped as not a governance control.
- **PRE-C19 re-judged under the single evidence standard** after the M4 split of
  PRE-M18 (`docs/control_coding/rejudge_PRE-C19.json`).
- **Undecidable EXR-M14 (run 2ec9):** the conservative default (absent) stands.
- **Role attribution convention.** Both are reported. **Primary role** = the first
  attributed role of the lowest-numbered member candidate of the final control.
  **Any role** = every role named in any member candidate's attribution. A control
  proposed independently by several roles counts once under each.

Every resolution, with its basis, is recorded in
`docs/control_coding/oneoff_resolutions.json`. The final coding is
`docs/CONTROL_CODING_FINAL.md` (`scripts/control_coding_final.py`).
