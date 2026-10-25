# Live Design Council app: build brief for Cursor

Author: Shivantha Meepage. Date: 11 October 2026.

Read this file and `CLAUDE.md` before writing any code. `CLAUDE.md` rules apply in full.

## 1. Goal

A live web app where a user uploads a finance workflow description as a PDF and the app does the rest:

1. Extracts a `WorkflowEncoding` (steps, actors, inputs, outputs, typed requirements, open steps) from the PDF.
2. Shows the extracted encoding for human review and editing before anything runs.
3. Runs the Design Council (seven roles, two rounds, synthesis) and, optionally, the budget-matched single agent, live.
4. Gates every Target-State Specification with the existing deterministic gate.
5. Shows the results: redesigned workflow, dispositions, gate scorecard, transformation depth, before-and-after diagram, productivity estimate, deliberation transcript by role, cost and runtime.

The existing Streamlit app (`app.py`, `app_pages/`, `export/`) stays as the read-only record of the dissertation results. The live app is a separate product built on the same engine.

## 2. Non-negotiables

- **The research engine is reused, not rewritten.** Call the existing functions:
  - `design_council.agents.council.run_council(encoding, kb, client, logger)` returns `(TargetStateSpec, GateResult)`.
  - `design_council.agents.baseline.run_baseline(encoding, kb, client, logger)` returns `(TargetStateSpec, GateResult)`.
  - `design_council.gate.gate.evaluate(encoding, tss)` (deterministic, no LLM, never modify).
  - `design_council.measures.depth.measure_depth(encoding, tss)`.
  - `design_council.measures.actor_class` for the human / hybrid / agent classification used by the productivity estimate.
  - `design_council.kb.loader.load_kb`, `design_council.run_logging.RunLogger`, `resolve_model`, `AnthropicClient`.
- **Do not modify** `design_council/gate/`, `data/encodings/heldout/`, the agent charters, prompts, or anything that would change a research result. Changes inside `design_council/` must be additive, keep current defaults, and the full test suite must still pass.
- **Live runs never mix with research runs.** Write them to `runs_live/` (git-ignored), never to `runs/`. Use `RunLogger(..., allow_dirty=True)` so every live run is recorded as a dirty-tree run.
- **Every LLM call is logged** exactly as today (model, resolved id, tokens, raw output). The PDF extraction step is a new LLM call: log it the same way under the run directory as `extraction.jsonl`.
- **The API key stays on the server** (`ANTHROPIC_API_KEY` in `.env`). Never send it to the browser.
- **Label clearly in the UI:** live runs are demonstrations on user-supplied workflows. They are not part of the pre-registered study. The productivity figure is an exploratory estimate under stated assumptions.

## 3. Architecture

```
web/        Next.js (App Router, TypeScript, Tailwind) front end
service/    FastAPI back end in Python 3.12, imports design_council directly
runs_live/  live run directories (same shape as runs/)
```

- **Back end (`service/`)**
  - `POST /encodings/extract`: upload a PDF, return a draft `WorkflowEncoding` plus validation errors and warnings.
  - `POST /encodings/validate`: validate an edited encoding against the pydantic model and the pairing rules in section 5.
  - `POST /runs`: body is `{encoding, conditions: ["council","baseline"]}`. Creates a job and returns `job_id`.
  - `GET /runs/{job_id}/events`: server-sent events for progress (round 1 role by role, round 2, synthesis, gate, measures).
  - `GET /runs/{job_id}`: full result (TSS, gate result, depth report, productivity, transcript, tokens, cost, runtime).
  - `GET /runs`: history list.
  - `GET /template`: downloads the encoding template (section 4).
- **Jobs:** a Council run makes 15 to 16 calls and takes about 16 minutes. Run jobs in a background worker (start with a simple thread-pool worker plus a SQLite job table; no Redis needed for version 1). Survive a browser refresh: the job keeps running and the page reconnects to the event stream.
- **Cost guard:** before a run, show the estimate (Council about $1.40, baseline about $0.07 at Sonnet 5 pricing of $2/M input and $10/M output) and require confirmation. Add a daily spend cap in `.env` (`LIVE_DAILY_CAP_USD`, default 20) that blocks new runs once reached.
- **Access:** a single shared password from `.env` for version 1.

## 4. PDF to encoding

Support two kinds of input:

1. **Template PDF (reliable path).** Generate a downloadable Word/PDF template with fixed sections: workflow name and function (P2P, R2R, FPA, O2C, Treasury, Tax); goal; a steps table (ID, name, description, actor, inputs, outputs); a requirements table (ID, plain-English statement, rule type, steps it binds, required inputs); steps open to elimination; source. Parse it with `pdfplumber` table extraction first, and use the LLM only to fill gaps.
2. **Free-form PDF (best effort).** A process narrative or SOP. Extract text with `pdfplumber`, then make one LLM call that returns JSON matching `WorkflowEncoding`. Validate it with pydantic and repair once with the error fed back, as the baseline does.

In both cases:

- Map each requirement to one of the gate's rule types (`step_preserved`, `inputs_required`, `ordering_preserved`, `actor_separation`, `disposition_in`) with valid `params`. Requirements that cannot be expressed as a rule type are listed as "assessed qualitatively" and not sent to the gate.
- Show a confidence flag per step and per requirement, and highlight anything the LLM inferred rather than read.
- **Nothing runs until the user has reviewed and confirmed the encoding.** The review screen is an editable table for steps and one for requirements, with live validation.

## 5. Validation before a run

Reuse the existing rules:

- pydantic validation of `WorkflowEncoding`;
- the pairing-completeness check: every step named in an ordering or separation rule must have a `step_preserved` requirement or be listed as open (see the tests that implement it and reuse that code);
- every `inputs_required` input must appear in the inputs of the step it binds;
- at least one requirement, at least three steps.

Show errors inline on the review screen and block the run until they are fixed.

## 6. Results screens (Next.js)

Mirror the Streamlit run explorer, but live:

1. **Progress:** seven role cards that fill as round-one positions arrive, then round two, then synthesis, gate and measures, with elapsed time and tokens so far.
2. **Redesign:** before-and-after workflow diagram (original steps against target steps, coloured by human / agent-assisted / automated), the disposition of every original step, human checkpoints and the mechanism for each outcome.
3. **Gate:** requirement-by-requirement pass, fail or vacuous pass with the gate's reason. Naming mismatches are shown as such (exact-match rule).
4. **Measures:** transformation depth, disposition counts, productivity estimate (median and 90% interval from the same model and parameters as `docs/PRODUCTIVITY_METHOD.md`) and structural indicators (human steps, checkpoints, human-to-human hand-offs).
5. **Deliberation:** the transcript by role and round.
6. **Compare:** if both conditions were run, Council against the single agent side by side.
7. **Export:** download the run as JSON and as a PDF report.

Use the same terms as the dissertation: "Design Council", "budget-matched single agent", "agentic AI", "Target-State Specification". No em dashes in UI copy.

## 7. Build phases

1. **Service, JSON input only.** FastAPI endpoints for validate, run (both conditions), events and results, using an existing encoding from `data/encodings/dev/`. Test with the mock client first (`design_council.run_logging.MockClient`), then one live baseline run.
2. **PDF extraction and review.** The template, the extraction endpoint, validation, plus tests on PDFs generated from the ten existing encodings (round trip: encoding to PDF to encoding should reproduce the steps and requirements).
3. **Next.js front end.** Upload, review, run with live progress, results, history.
4. **Packaging.** `docker compose up` runs both services locally. Deployment (Vercel for `web/`, Render or Fly for `service/`) only after local works end to end.

## 8. Done means

- Upload the template PDF for three-way matching. The extracted encoding matches `data/encodings/heldout/p2p_three_way_matching.json` on steps and requirements, a Council run completes live, and the gate result and depth display.
- The existing test suite still passes, plus new tests for the service and extraction.
- No file under `design_council/gate/` or `data/encodings/heldout/` is changed (`git diff --stat` shows none).
- A README section explains how to run it locally.

Do not commit unless the author says so. Work on a branch named `live-app`.
