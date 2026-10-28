# design-council

This repository holds the code, data and results for an MSc dissertation that asks whether
structured multi-agent deliberation produces better finance workflow redesigns than a strong
single agent. A seven-role Design Council (two deliberation rounds and a synthesis) and a
budget-matched single agent, both on the same model, each redesign a finance workflow into a
Target-State Specification. Every specification is scored by a deterministic conformance gate
against the workflow's own encoded requirements, with no model in the loop, and its
transformation depth is measured from the disposition of each original step. The evaluation
uses seven held-out workflows (procure-to-pay, record-to-report, and financial planning and
analysis) under a pre-registered protocol frozen before any held-out run. An exploratory,
post-freeze sequential condition, in which one agent is given a comparable budget and walked
through the seven role charters in turn, was run on two of those workflows.

- Dissertation: A Multi-Agent Design Council for Outcome-Anchored Redesign of Finance Workflows
- Author: Shivantha Meepage
- Module: CS7P01NM, London Metropolitan University
- Supervisor: Dr Sidath Weerasinghe

## Repository map

- `design_council/`: the engine. `agents/` (council, budget-matched baseline, sequential
  agent, role charters, model client), `gate/` (the deterministic conformance gate), `kb/`
  (knowledge base), `measures/` (depth, consistency, actor classification), `schemas/`
  (pydantic data contracts), `run_logging.py` (per-call logging and model resolution).
- `data/encodings/`: workflow encodings. `heldout/` holds the seven held-out workflows, frozen
  at the pre-registration tag; `dev/` holds the three development workflows.
- `docs/`: pre-registration, results documents, coding decisions, the sequential condition's
  pre-registration note and write-ups, and screenshots of the results app.
- `export/`: everything the results app reads, written by `scripts/export_app_data.py`
  (layout in `export/SCHEMA.md`), including one file per run in `export/runs/`.
- `scripts/`: runners, analysis scripts and the export.
- `app.py` and `app_pages/`: the read-only results app.
- `tests/`: the test suite (`pytest`).

## Install

`requirements.lock` is the authoritative build: every dependency is pinned to an exact
version and verified against its artifact hashes. It is resolved universally, so the same
lock installs on macOS, Linux, and Windows; platform-specific dependencies are gated by
environment markers. Installs **must** use it, so that a result can be rebuilt years later
from the repo alone, on whatever machine is to hand:

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock --require-hashes
```

`requirements.txt` lists only the direct, unpinned dependencies and exists solely as
input for regenerating the lock:

```
uv pip compile requirements.txt -o requirements.lock --generate-hashes --universal
```

Keep `--universal`: without it the lock is resolved against one machine's platform and
Python version, and stops being a cross-platform build.

Never install from `requirements.txt` directly: it resolves to whatever is current on
PyPI that day, which silently breaks reproducibility.

## Results app

The app replays the logged runs. It reads only `export/`, makes no API calls and writes
nothing, so it needs no API key and no run logs. It uses its own small environment:

```
python3.12 -m venv .venv-viewer
.venv-viewer/bin/pip install streamlit==1.64.0 altair==6.3.0 pandas==3.0.6
.venv-viewer/bin/streamlit run app.py
```

## Reproducing the results

Model calls need an Anthropic API key in `.env`. Every call is logged to `runs/` with the
requested and resolved model, the provider's `created_at`, token counts and raw output.

1. Check out the freeze tag `prereg-heldout-2026-10-11` for the held-out protocol as
   pre-registered (`docs/PREREGISTRATION_HELDOUT.md`).
2. Held-out set: `python scripts/run_heldout.py --set-name <name> --prereg-tag prereg-heldout-2026-10-11`
   runs every workflow under both conditions, round-robin, with the pre-registered stopping
   rule (n = 4 or 5 per cell). `--dry-run` shows the plan without calling the model.
3. Sequential condition (exploratory): `python scripts/run_sequential.py data/encodings/heldout/<encoding>.json --reps 5`.
4. Analysis, with no model calls: `scripts/analyse_heldout.py` (held-out tables),
   `scripts/efficiency_heldout.py`, `scripts/productivity_heldout.py`,
   `scripts/control_coding_final.py`, `scripts/bootstrap_h2.py`,
   `scripts/verify_dispositions.py`, `scripts/controls_symmetric_length.py` and
   `scripts/analyse_sequential.py <workflow>`. `scripts/export_app_data.py` rebuilds `export/`
   from the run logs, and `pytest` checks the export against the committed results documents.

The raw run logs (`runs/`) are distributed as a release asset, not in git. Unpack them at the
repository root to rerun the analysis scripts and the export tests.

## Key commits

- `fe1a87a`: held-out set frozen (seven encodings, pre-registration, run and analysis harness).
- `47425d4`: held-out results, productivity and analysis scripts.
- `a67c2af` and `4ab2958`: productivity method and classification decisions, fixed before computation.
- `42c397d`: governance-control coding under pre-registration section 6.
- `5e047d3`: exploratory classification of conformance failures.
- `987d710`: sequential condition, pre-registration note for FPA-VAR-01, committed before any model call.
- `20829e9`: sequential condition, FPA-VAR-01 write-up.
