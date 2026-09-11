# HANDOFF: Regenerate expert review packs from the completed v1 development grid

Date: 11 September 2026
Priority: tonight, before supervision session 12 September
Environment: Claude Code / VS Code, per CLAUDE.md discipline (no self-commits, no modification of frozen files, no LLM calls in the gate or in pack generation)

## Objective

Replace the pre-grid VIP review pack (generated from single runs 20260828-175146 / 20260829-051950) with three review packs generated from the completed v1 development grid: P2P-VIP-01, R2R-PC-01, FPA-RF-01. Each pack summarises n=3 runs per condition. Build this as a reusable generator so held-out packs are one command after the held-out runs on 17 September.

## Why regeneration is required

The existing VIP pack reports depth 0.375 (baseline) vs 0.875 (council) from n=1. The completed grid shows baseline mean 0.458 (range 0.375 to 0.500) and council mean 0.958 (range 0.875 to 1.000). The baseline improved on repetition, narrowing the gap. Packs presented in review must reflect the full grid, not the first draw.

## Inputs (all exist in repo, no new runs)

- Run archive for all 18 v1 dev-grid runs: manifests, calls.jsonl, gate outputs, disposition mappings, token accounting
- The three development encodings and their requirement sets
- Standards knowledge base (sha-pinned version referenced by the runs)
- The existing VIP pack layout as the template (three-page structure: design comparison, added controls plus reviewer questions, requirements and KB appendix)
- v2 probe runs are EXCLUDED from all packs per the instrument-versioning rule; state this in the provenance footer

## Generator specification

One script (ReportLab, matching the existing pack pipeline) taking a workflow ID and emitting the pack PDF.

1. Representative-run selection. Page 1 design comparison shows one baseline TSS and one council TSS. Selection rule: the run whose depth equals the per-condition median; tie-break by earliest run timestamp. Document the rule on the page. Header lists ALL run IDs summarised and both commits.

2. Measured outcomes table, per condition, n=3:
   - Rule conformance: mean (it will be 1.00 in all cells; state it as the validity floor)
   - Substantive conformance and vacuous-pass count
   - Transformation depth: mean (range)
   - Actor reassignments: per representative run, with note if variable across runs
   - Compute: output tokens including reasoning, mean (range)
   - Reading column, workflow-specific, see honesty requirements below

3. Honesty requirements, non-negotiable wording constraints:
   - VIP: ranges are disjoint; depth separates cleanly on this workflow only
   - R2R and FPA: mean gap is a single 0.125 quantum, inside the sampling spread measured at n=3; no separation claim; the reading points to the qualitative section
   - Every pack carries the zero-elimination note: 0 of 176 dispositions eliminated or absorbed across both instrument versions; round-one transcripts show the maximalist role explicitly reasoning that no elimination is defensible on this corpus (reasoned declination, not suppression; v2 hypothesis retracted with evidence)

4. R2R pack page 2 leads with the ten role-attributed governance controls absent from every baseline draw, each traceable to a role and, where applicable, a KB citation. This is the primary demonstrated advantage where depth does not separate. VIP page 2 keeps its ten-control structure updated to the representative run. FPA page 2 includes the standards-role citation contraction finding (twelve KB entries on R2R to seven on FPA, tracking KB coverage, with declared silences), confirming the pre-registered prediction.

5. Data integrity: every number in the pack is read from gate outputs and run manifests, never hand-entered. The script asserts consistency (recomputed depth from disposition mapping equals logged depth; conformance count equals gate output) and fails loudly on mismatch.

6. Provenance footer per pack: all run IDs, commit hashes, encoding and KB content hashes, instrument version v1, v2 exclusion statement, model identity as resolved by probe, generation date, development-split disclaimer (comments inform development iteration, not research data unless separately agreed).

## Secondary task, same session (feeds tomorrow directly)

Extract the pairing-gap closure record and elimination-space accounting from commit history and encoding files:

- Per encoding: total steps; steps protected by survival requirements; steps on the documented open-to-elimination list; net elimination space
- For each of the three closed pairing gaps: which encoding, which step, closure mechanism (survival requirement added vs added to open list), commit reference
- One-line conclusion: whether the audit narrowed the elimination space, and from what to what

Output: a small markdown table saved alongside the packs. This answers supervisor feedback demand 1 and grounds the ceiling-question response.

## Deliverables

1. `review_pack_P2P-VIP-01_devgrid.pdf`
2. `review_pack_R2R-PC-01_devgrid.pdf`
3. `review_pack_FPA-RF-01_devgrid.pdf`
4. Generator script committed with a make target or CLI entry so held-out packs are one command
5. `pairing_gap_elimination_space.md` table
6. Visual QA: render each PDF to images and inspect before handing off

## Out of scope tonight

- Held-out encodings (resume after supervision per the week plan)
- SESOI pre-registration document (drafted in claude.ai, ratified with supervisor tomorrow, frozen 16 September)
- Any change to frozen or gate code paths

## Handback

Return the three PDFs and the pairing-gap table to the claude.ai session for assembly into the supervision status report.
