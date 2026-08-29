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
