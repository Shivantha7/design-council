# Freeze notes

Decisions fixed before any held-out run, recorded here so that the definitions
cannot be chosen after seeing held-out results. Each is also enforced or
documented in code at the point it applies.

## Transformation depth — scalar definition

Fixed in commit `39327c6`, before any held-out run.

The disposition profile is the pre-registered measure. Its scalar collapse is:

    depth = (eliminated + merged + absorbed + restructured) / total baseline steps

That is, the proportion of baseline steps **not retained**. `retained` is the
only disposition asserting a step carried over substantially unchanged, so its
complement is the share of the workflow a redesign actually touched.

The scalar is **unweighted**: eliminating a step and restructuring one count
alike. Any weighting that called elimination "deeper" would itself be a
post-hoc choice.

`actor_reassignments`, `net_new_steps`, `step_count_delta` and mean fan-out are
**supplementary descriptives**, not pre-registered, for qualitative analysis
only.

## Call-record accounting rule

Fixed alongside the stream-retry mechanism, before any held-out run.

A call may be attempted more than once when a stream dies mid-flight. Every
attempt is logged as its own `CallRecord`, with `attempt_status` of `ok` or
`stream_failed`.

- **Content** is read only from records with `attempt_status == "ok"`. A
  failed attempt's partial text is never a contribution.
- **Per-condition token comparisons count every record**, failed attempts
  included. Those tokens were billed. A condition that needed three attempts
  to obtain one answer really did cost three attempts, and reporting only
  successful attempts would understate the cost of precisely the condition
  whose calls run longest.

## Reasoning tokens

`output_tokens` includes reasoning tokens; `thinking_tokens` records the
reasoning portion separately where the provider reports it. Reasoning is not an
additional charge on top of output, and must not be added to it.

The resolution probe (`agent_role == "model_resolution_probe"`) is
infrastructure, not experimental work. Exclude it from per-condition token
comparisons.

## Disposition labelling fidelity — prompt strengthened, 30 Aug 2026

Fixed after the dev sweep, before any held-out run.

**Evidence.** Across 18 dev runs (3 workflows x 2 conditions x 3 repetitions)
the 144 recorded dispositions were:

| disposition | count |
| --- | ---: |
| restructured | 90 |
| retained | 38 |
| merged | 16 |
| absorbed | 0 |
| eliminated | 0 |

Two of the five categories never occurred. The rendered transcript of the
completed VIP council run shows why this is a labelling problem rather than an
absence of ambition: the maximalist argued explicitly for eliminating VIP-01
and VIP-02 ("eliminate as a discrete human-mediated step; absorb into TGT-01"),
and the synthesis recorded both as `merged`. A depth measure whose scalar
counts "not retained" was therefore, in practice, counting how often a step got
called `restructured` rather than `retained`.

**Change.** The disposition convention shared by the baseline prompt and every
council prompt (including the synthesis) gains a labelling-fidelity paragraph
instructing the model to label by what structurally happened rather than by
what sounds safer, and stating that the requirements gate — not the label — is
the safety mechanism.

The convention is versioned (`v2, 30 Aug 2026`) and its sha256 is recorded in
every run manifest as `config.prompt_fragment_hashes.disposition_convention`,
so a run is attributable to the wording that produced it. Runs made before this
change carry no such key and are identifiable by its absence.

**Consequence for analysis.** Dev runs before and after this change were made
under different instructions and must not be pooled. The pre-change dev sweep
stands as its own set; comparisons across the change are between-prompt
comparisons, not between-condition ones.

## Run-to-run consistency — definition, 11 Oct 2026

Fixed before any held-out run, by author decision (10 Oct 2026, 23:55).

    agreement(a, b) = share of baseline steps given the same disposition label
                      in run a and run b
    consistency     = mean of agreement over every pair of runs in a cell
                      (k(k-1)/2 pairs for k runs)

It is unweighted and compares labels only. Code:
`design_council/measures/consistency.py`, shared by the held-out analysis
(`scripts/analyse_heldout.py`) and the development-grid computation
(`scripts/measure_consistency_dev.py`). The condition-level figure is the mean
of the cell consistencies.

The pre-registration (section 4) had defined consistency "as defined for the
development grid", but no definition existed before this entry. The same code
applied to the 18-run v1 development grid gives:

| Cell | n | Consistency (pairwise range) |
| --- | ---: | --- |
| P2P-VIP-01 council | 3 | 0.917 (0.875–1.000) |
| P2P-VIP-01 baseline | 3 | 0.917 (0.875–1.000) |
| R2R-PC-01 council | 3 | 0.833 (0.750–1.000) |
| R2R-PC-01 baseline | 3 | 0.833 (0.750–0.875) |
| FPA-RF-01 council | 3 | 0.625 (0.500–0.750) |
| FPA-RF-01 baseline | 3 | 0.625 (0.500–0.750) |

Mean of cell consistencies: council 0.792, baseline 0.792.

## Disposition convention — v1 restored for the held-out set, 11 Oct 2026

Fixed before any held-out run, by author decision (10 Oct 2026, 23:55).

The held-out set runs under the **v1** disposition convention, the wording of
the 18-run development grid it is compared against. The v2 labelling-fidelity
paragraph (commit `01034ae`, 30 Aug 2026, recorded above) is removed from
`DISPOSITION_CONVENTION` in `design_council/agents/baseline.py`.

**Verification.** With the restored constant, the assembled baseline prompt
and council base context for every encoding (3 dev, 7 held-out) are
byte-identical to those built by the code at `01034ae^`. The knowledge base
is byte-identical too.

**Provenance.** The convention is still hashed into every manifest
(`config.prompt_fragment_hashes`). `config.disposition_convention_version`
now reads `"v1, restored 11 Oct 2026"`, so presence of the hash no longer
marks a v2 run. `design_council/measures/packs.py::is_v2` reads the version
string instead. On the runs on disk, it selects exactly the same four v2 runs
as the old rule.

**Consequence for analysis.** Held-out runs are poolable with the v1
development grid in respect of instructions. The four v2 dev runs remain
excluded, as before. The v2 hypothesis (that labelling, not ambition, caused
the zero-elimination result) is not tested on the held-out set.
