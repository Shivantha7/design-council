# design-council

A research codebase for studying whether a multi-agent "council" of LLM reviewers produces
more standards-conformant financial-reporting design decisions than a single baseline agent.
Cases are expressed as structured encodings (`data/encodings/`) validated against pydantic
schemas (`design_council/schemas/`), routed through either a baseline agent or the council
(`design_council/agents/`), and scored by a conformance gate (`design_council/gate/`) that
checks proposed treatments against an IFRS/SLFRS knowledge base (`design_council/kb/`).
Experiment outputs land in `runs/` (gitignored); `data/encodings/heldout/` is reserved for
evaluation and `data/dummy/` holds small fixtures for tests.
