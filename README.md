# design-council

A research codebase for studying whether a multi-agent "council" of LLM reviewers produces
more standards-conformant financial-reporting design decisions than a single baseline agent.
Cases are expressed as structured encodings (`data/encodings/`) validated against pydantic
schemas (`design_council/schemas/`), routed through either a baseline agent or the council
(`design_council/agents/`), and scored by a conformance gate (`design_council/gate/`) that
checks proposed treatments against an IFRS/SLFRS knowledge base (`design_council/kb/`).
Experiment outputs land in `runs/` (gitignored); `data/encodings/heldout/` is reserved for
evaluation and `data/dummy/` holds small fixtures for tests.

## Install

`requirements.lock` is the authoritative build: every dependency is pinned to an exact
version and verified against its artifact hashes. Installs **must** use it, so that a
result can be rebuilt years later from the repo alone:

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock --require-hashes
```

`requirements.txt` lists only the direct, unpinned dependencies and exists solely as
input for regenerating the lock:

```
uv pip compile requirements.txt -o requirements.lock --generate-hashes
```

Never install from `requirements.txt` directly — it resolves to whatever is current on
PyPI that day, which silently breaks reproducibility.
