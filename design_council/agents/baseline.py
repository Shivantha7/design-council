"""The single-agent baseline.

One model call produces a Target-State Specification from an encoding. This is
the control condition: whatever the council does, it must beat this.

Condition parity matters more than convenience here. The baseline is given
everything the council will be given — the full encoding including its
requirements, and the whole knowledge base — so that any difference in the
results is a difference in how the agents are organised, not in what they were
told.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from design_council.gate import evaluate
from design_council.kb.loader import KnowledgeBase
from design_council.run_logging import ModelClient, RunLogger, log_model_call
from design_council.schemas import (
    Disposition,
    GateResult,
    TargetStateSpec,
    WorkflowEncoding,
)

AGENT_ROLE = "baseline_designer"
REPAIR_AGENT_ROLE = "baseline_designer_repair"

TSS_FILENAME = "tss.json"
GATE_RESULT_FILENAME = "gate_result.json"
RAW_FAILURE_FILENAME = "raw_completion_unparseable.txt"


class BaselineError(Exception):
    """The baseline could not produce a valid Target-State Specification."""


def strip_code_fences(text: str) -> str:
    """Remove a wrapping markdown code fence if the model added one.

    The prompt asks for bare JSON, but models fence output habitually. Stripping
    is done here rather than by loosening the parser, so that anything else
    unexpected still fails loudly.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]

    return "\n".join(lines).strip()


def build_prompt(encoding: WorkflowEncoding, kb: KnowledgeBase) -> str:
    """The single prompt the baseline agent receives."""
    return "\n".join(
        [
            "You are a finance workflow redesign specialist producing a "
            "Target-State Specification.",
            "",
            "You are given a finance workflow as it is performed today, the "
            "accounting-standards principles that bear on it, and a JSON schema. "
            "Produce a redesigned target state for the workflow.",
            "",
            "=== CURRENT-STATE WORKFLOW ENCODING ===",
            json.dumps(encoding.model_dump(mode="json"), indent=2),
            "",
            "=== ACCOUNTING STANDARDS KNOWLEDGE BASE ===",
            kb.render_for_prompt(),
            "",
            "=== OUTPUT SCHEMA (JSON Schema for the object you must return) ===",
            json.dumps(TargetStateSpec.model_json_schema(), indent=2),
            "",
            "=== DISPOSITION CONVENTION ===",
            "Every baseline step must appear exactly once in disposition_mapping "
            "— no omissions, no duplicates, no steps that are not in the "
            "baseline.",
            "",
            "  eliminated   the function ceases to exist in the target state. "
            "Nothing performs it. target_step_ids must be empty.",
            "  merged       the function persists, combined with other steps "
            "into the step(s) named in target_step_ids.",
            "  absorbed     the function persists, subsumed into the scope of "
            "the step(s) named in target_step_ids.",
            "  retained     the function persists substantially unchanged, "
            "carried by the step(s) named in target_step_ids.",
            "  restructured the function persists but is reorganised, carried "
            "by the step(s) named in target_step_ids.",
            "",
            "Only 'eliminated' asserts the function is gone. Every other "
            "disposition requires a non-empty target_step_ids, and every id "
            "listed there must be the step_id of a step you define in 'steps'.",
            "",
            "Set workflow_id to the encoding's workflow_id, and "
            "baseline_step_ids to the step_ids of the current-state workflow in "
            "order.",
            "",
            "=== OUTPUT RULE ===",
            "Respond with a single JSON object only. No prose before or after "
            "it. No markdown code fences. No explanation. The first character "
            "of your response must be '{' and the last must be '}'.",
        ]
    )


def build_repair_prompt(original_prompt: str, bad_output: str, error: str) -> str:
    """The one repair attempt, feeding the validation error back verbatim."""
    return "\n".join(
        [
            original_prompt,
            "",
            "=== YOUR PREVIOUS RESPONSE FAILED VALIDATION ===",
            "You produced this:",
            "",
            bad_output,
            "",
            "It was rejected with this error, verbatim:",
            "",
            error,
            "",
            "Correct the specific problem named above and return the corrected "
            "object. Respond with a single JSON object only: no prose, no "
            "markdown code fences.",
        ]
    )


def parse_tss(text: str) -> TargetStateSpec:
    """Strip fences, parse, validate. Raises ValidationError or ValueError."""
    return TargetStateSpec.model_validate_json(strip_code_fences(text))


def run_baseline(
    encoding: WorkflowEncoding,
    kb: KnowledgeBase,
    client: ModelClient,
    logger: RunLogger,
    sampling_params: dict[str, Any] | None = None,
) -> tuple[TargetStateSpec, GateResult]:
    """Produce a TSS for one encoding, gate it, and write both to the run.

    One repair attempt is allowed on a validation failure, with the error fed
    back verbatim. If that also fails the raw text is saved and BaselineError is
    raised — the run does not loop, because a model that cannot satisfy the
    schema in two attempts is a result worth recording, not one worth retrying
    until it happens to work.
    """
    params = {} if sampling_params is None else dict(sampling_params)
    requested_model = logger.manifest.requested_model
    prompt = build_prompt(encoding, kb)

    record = log_model_call(
        client, logger, prompt, AGENT_ROLE, encoding.workflow_id, params
    )
    text = record.raw_completion
    total_input, total_output = record.input_tokens, record.output_tokens

    try:
        tss = parse_tss(text)
    except (ValidationError, ValueError) as first_error:
        repair_prompt = build_repair_prompt(prompt, text, str(first_error))
        repair_record = log_model_call(
            client,
            logger,
            repair_prompt,
            REPAIR_AGENT_ROLE,
            encoding.workflow_id,
            params,
        )
        repair_text = repair_record.raw_completion
        total_input += repair_record.input_tokens
        total_output += repair_record.output_tokens

        try:
            tss = parse_tss(repair_text)
        except (ValidationError, ValueError) as second_error:
            failure_path = logger.run_dir / RAW_FAILURE_FILENAME
            failure_path.write_text(
                "=== first attempt ===\n"
                f"{text}\n\n"
                "=== first error ===\n"
                f"{first_error}\n\n"
                "=== repair attempt ===\n"
                f"{repair_text}\n\n"
                "=== repair error ===\n"
                f"{second_error}\n"
            )
            raise BaselineError(
                f"the model did not produce a valid TargetStateSpec in two "
                f"attempts. Raw output saved to {failure_path}.\n\n"
                f"Repair attempt error:\n{second_error}"
            ) from second_error

    tss_path = logger.run_dir / TSS_FILENAME
    tss_path.write_text(tss.model_dump_json(indent=2) + "\n")

    gate_result = evaluate(encoding, tss)
    gate_path = logger.run_dir / GATE_RESULT_FILENAME
    gate_path.write_text(gate_result.model_dump_json(indent=2) + "\n")

    print_report(encoding, tss, gate_result, total_input, total_output)

    return tss, gate_result


def print_report(
    encoding: WorkflowEncoding,
    tss: TargetStateSpec,
    gate_result: GateResult,
    total_input_tokens: int,
    total_output_tokens: int,
) -> None:
    """Human-readable summary of one baseline run."""
    substantive = gate_result.substantive_score
    substantive_text = (
        "undefined (every requirement was vacuous)"
        if substantive is None
        else f"{substantive:.4f}"
    )
    passed = sum(1 for r in gate_result.results if r.passed)

    print()
    print(f"workflow          : {encoding.workflow_id}")
    print(f"baseline steps    : {len(encoding.steps)}")
    print(f"target steps      : {len(tss.steps)}")
    print()
    print(f"conformance_score : {gate_result.conformance_score:.4f}  ({passed}/{len(gate_result.results)})")
    print(f"vacuous_count     : {gate_result.vacuous_count}")
    print(f"substantive_score : {substantive_text}")
    print()

    for entry in gate_result.results:
        verdict = "PASS" if entry.passed else "FAIL"
        marker = " [vacuous]" if entry.vacuous else ""
        print(f"  {entry.requirement_id}  {verdict}{marker}  {entry.reason}")

    print()
    print("dispositions:")
    for disposition in Disposition:
        count = sum(
            1 for e in tss.disposition_mapping if e.disposition is disposition
        )
        print(f"  {disposition.value:14} {count}")

    print()
    print(f"tokens            : {total_input_tokens} in, {total_output_tokens} out")
