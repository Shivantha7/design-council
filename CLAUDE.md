# Project rules

MSc dissertation codebase: a multi-agent **Design Council** that produces Target-State
Specifications for finance workflows.

## Stack
- Python 3.12.
- pydantic for all data contracts — no ad-hoc dicts crossing module boundaries.
- LangGraph for orchestration.

## Hard constraints
- **The conformance gate (`design_council/gate/`) must stay fully deterministic.**
  Never add LLM calls to it.
- **Files under `data/encodings/heldout/` are frozen after the pre-registration tag.**
  Never modify them.
- **Every LLM call must log** model, pinned version, seed, token counts, and raw output
  to `runs/`.

## Style
Prefer plain, simple code over clever abstractions. This is research code that must be
auditable — a reader reconstructing a result from the repo should not have to unpick
indirection to see what happened.
