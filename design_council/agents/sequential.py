"""Compute-matched single agent: one designer, seven perspectives in sequence.

EXPLORATORY, POST-FREEZE (25 Oct 2026). Not pre-registered. Added in response to
the supervisor's observation that the council spends roughly 19x the baseline's
cost, so its depth and control advantages may be bought with compute rather than
with deliberation structure.

The protocol mirrors the council call for call, with one difference: there is no
independence. One agent writes all seven perspectives in turn, each seeing the
ones already written; then reconsiders each perspective in the light of all
seven; then synthesises. Fifteen calls, the same charters, the same base
context, the same synthesis prompt and the same output schema. Whatever the
council gains over this condition is attributable to seven independent
positions and cross-critique, not to the number of tokens spent or the role
content supplied.

    Pass 1   seven perspective calls, sequential and cumulative (each sees the
             earlier perspectives in the same thread)
    Pass 2   seven reconsideration calls, each seeing all seven perspectives
             (the council's round-2 prompt, verbatim)
    Synth    the council's synthesis prompt, verbatim
"""

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from design_council.agents.baseline import parse_tss
from design_council.agents.council import (
    ROLE_ORDER,
    SYNTHESIS_MAX_TOKENS,
    CouncilRole,
    build_base_context,
    build_round2_prompt,
    build_synthesis_prompt,
    build_synthesis_repair_prompt,
    load_charter,
)
from design_council.gate import evaluate
from design_council.kb.loader import KnowledgeBase
from design_council.run_logging import ModelClient, RunLogger, log_model_call
from design_council.schemas import GateResult, TargetStateSpec, WorkflowEncoding

TSS_FILENAME = "tss.json"
GATE_RESULT_FILENAME = "gate_result.json"
TRANSCRIPT_FILENAME = "transcript.md"
RAW_FAILURE_FILENAME = "raw_completion_unparseable.txt"


class SequentialError(Exception):
    """The sequential agent could not produce a valid Target-State Specification."""


def build_perspective_prompt(
    base_context: str, role: CouncilRole, charter: str, earlier: dict[str, str]
) -> str:
    prior = []
    for other in ROLE_ORDER:
        if other.value in earlier:
            prior += [f"--- PERSPECTIVE ALREADY WRITTEN: {other.value}", earlier[other.value], ""]
    return "\n".join(
        [
            base_context,
            "",
            "=== HOW YOU ARE WORKING ===",
            "You are a single finance workflow redesign specialist. Before "
            "producing a specification you reason through the redesign from "
            "seven perspectives in turn, one per message, in a single thread. "
            "You have written the perspectives below already and may build on "
            "them; you are the same designer throughout.",
            "",
            *(prior if prior else ["(no perspectives written yet)", ""]),
            "=== PERSPECTIVE TO TAKE NOW ===",
            f"Take the {role.value} perspective.",
            "",
            charter,
            "",
            "Set out your position on the redesign from this perspective, covering:",
            "  1. PROPOSED DISPOSITIONS — for each baseline step, the "
            "disposition you argue for and the target step you would have "
            "carry it.",
            "  2. NON-NEGOTIABLES — what must not change, from this "
            "perspective, and why.",
            "  3. RATIONALE — the reasoning behind your proposal, in this "
            "perspective's terms.",
            "",
            "Write prose under those three headings. Do not produce JSON in "
            "this message.",
        ]
    )


def run_sequential(
    encoding: WorkflowEncoding,
    kb: KnowledgeBase,
    client: ModelClient,
    logger: RunLogger,
    sampling_params: dict[str, Any] | None = None,
    synthesis_max_tokens: int = SYNTHESIS_MAX_TOKENS,
) -> tuple[TargetStateSpec, GateResult]:
    params = {} if sampling_params is None else dict(sampling_params)
    base = build_base_context(encoding, kb)
    charters = {role: load_charter(role) for role in ROLE_ORDER}
    wf = encoding.workflow_id

    positions: dict[str, str] = {}
    for role in ROLE_ORDER:
        prompt = build_perspective_prompt(base, role, charters[role], positions)
        rec = log_model_call(client, logger, prompt, f"seq1_{role.value}", wf, params)
        positions[role.value] = rec.raw_completion

    critiques: dict[str, str] = {}
    for role in ROLE_ORDER:
        prompt = build_round2_prompt(base, role, charters[role], positions)
        rec = log_model_call(client, logger, prompt, f"seq2_{role.value}", wf, params)
        critiques[role.value] = rec.raw_completion

    prompt = build_synthesis_prompt(base, positions, critiques)
    rec = log_model_call(client, logger, prompt, "seq_synthesis", wf, params,
                         max_tokens=synthesis_max_tokens)
    text = rec.raw_completion
    try:
        tss = parse_tss(text)
    except (ValidationError, ValueError) as first_error:
        repair = build_synthesis_repair_prompt(prompt, text, str(first_error))
        rec2 = log_model_call(client, logger, repair, "seq_synthesis_repair", wf, params,
                              max_tokens=synthesis_max_tokens)
        try:
            tss = parse_tss(rec2.raw_completion)
        except (ValidationError, ValueError) as second_error:
            (logger.run_dir / RAW_FAILURE_FILENAME).write_text(
                f"=== synthesis ===\n{text}\n\n=== error ===\n{first_error}\n\n"
                f"=== repair ===\n{rec2.raw_completion}\n\n=== repair error ===\n{second_error}\n")
            raise SequentialError("no valid TargetStateSpec in two synthesis attempts") from second_error

    lines = [f"# Sequential single agent: {wf}", ""]
    for role in ROLE_ORDER:
        lines += [f"## Perspective: {role.value}", "", positions[role.value], "",
                  f"## Reconsideration: {role.value}", "", critiques[role.value], ""]
    (logger.run_dir / TRANSCRIPT_FILENAME).write_text("\n".join(lines))
    (logger.run_dir / TSS_FILENAME).write_text(tss.model_dump_json(indent=2) + "\n")
    gate_result = evaluate(encoding, tss)
    (logger.run_dir / GATE_RESULT_FILENAME).write_text(gate_result.model_dump_json(indent=2) + "\n")
    return tss, gate_result
