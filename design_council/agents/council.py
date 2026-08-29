"""The Design Council: seven agents, two rounds, one synthesis.

The protocol is fixed and deliberately simple, because the experiment is about
whether structured disagreement improves a redesign, not about finding the best
possible orchestration:

    Round 1   seven agents write positions independently, each from the same
              base context plus its own role charter. No agent sees another's
              position, so the seven are genuinely independent rather than
              anchored on whoever spoke first.
    Round 2   each agent sees all seven positions and responds — conceding,
              holding, or naming a conflict it cannot resolve.
    Synthesis one call turns the whole transcript into a Target-State
              Specification.

Fifteen model calls per run. Every one is logged, so the transcript is
recoverable from runs/ rather than existing only in memory.

The base context is identical to the baseline's: same encoding, same knowledge
base, same disposition convention. Condition parity is what makes the
comparison mean anything — the council must differ from the baseline in how it
is organised, not in what it was told.
"""

import hashlib
from enum import Enum
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, ValidationError

from design_council.agents.baseline import (
    build_prompt as build_baseline_prompt,
)
from design_council.agents.baseline import (
    parse_tss,
)
from design_council.gate import evaluate
from design_council.kb.loader import KnowledgeBase
from design_council.run_logging import ModelClient, RunLogger, sha256_text, utc_now_iso
from design_council.schemas import (
    CallRecord,
    Disposition,
    GateResult,
    TargetStateSpec,
    WorkflowEncoding,
)

CHARTERS_DIR = Path(__file__).resolve().parent / "charters"

SYNTHESIS_ROLE = "synthesis"
SYNTHESIS_REPAIR_ROLE = "synthesis_repair"

TSS_FILENAME = "tss.json"
GATE_RESULT_FILENAME = "gate_result.json"
TRANSCRIPT_FILENAME = "transcript.md"
RAW_FAILURE_FILENAME = "raw_completion_unparseable.txt"


class CouncilError(Exception):
    """The council could not produce a valid Target-State Specification."""


class CouncilRole(str, Enum):
    """The seven seats. Order is fixed and is the order they speak in."""

    MAXIMALIST = "maximalist"
    PRAGMATIST = "pragmatist"
    FINANCE_DOMAIN = "finance_domain"
    EMERGING_ECONOMY = "emerging_economy"
    HITL_DESIGNER = "hitl_designer"
    AGENTIC_ARCHITECT = "agentic_architect"
    ACCOUNTING_STANDARDS = "accounting_standards"


ROLE_ORDER = list(CouncilRole)


class CouncilState(BaseModel):
    """What the council has said so far.

    The client and the logger are deliberately absent: state is data, and
    keeping it serialisable means a transcript can be written out and read back
    without reconstructing anything live.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    encoding: WorkflowEncoding
    kb_rendering: str
    positions: dict[str, str] = {}
    critiques: dict[str, str] = {}
    tss_raw: str | None = None
    tss: TargetStateSpec | None = None


# --- charters ----------------------------------------------------------------


def charter_path(role: CouncilRole) -> Path:
    return CHARTERS_DIR / f"{role.value}.md"


def load_charter(role: CouncilRole) -> str:
    """Read one role charter from disk.

    Charters are files rather than string literals so they can be edited,
    reviewed and hashed independently of the code that uses them. Their hashes
    go into the run manifest, which is what lets a run be attributed to the
    charters it actually ran with.
    """
    path = charter_path(role)
    if not path.exists():
        raise CouncilError(f"missing charter for {role.value}: {path}")

    return path.read_text()


def charter_hashes() -> dict[str, str]:
    """role -> sha256 of its charter, for the run manifest config."""
    return {
        role.value: hashlib.sha256(load_charter(role).encode("utf-8")).hexdigest()
        for role in ROLE_ORDER
    }


# --- prompts -----------------------------------------------------------------


def build_base_context(encoding: WorkflowEncoding, kb: KnowledgeBase) -> str:
    """The context every council agent shares with the baseline.

    Reuses the baseline's prompt builder outright rather than restating it, so
    the two conditions cannot drift apart in what they were shown.
    """
    return build_baseline_prompt(encoding, kb)


def build_round1_prompt(base_context: str, role: CouncilRole, charter: str) -> str:
    return "\n".join(
        [
            base_context,
            "",
            "=== YOUR ROLE ===",
            f"You are the {role.value} member of a design council.",
            "",
            charter,
            "",
            "=== THIS ROUND ===",
            "This is round 1. You are writing independently: you have not seen "
            "any other member's position, and they have not seen yours.",
            "",
            "Set out your position on the redesign, covering:",
            "  1. PROPOSED DISPOSITIONS — for each baseline step, the "
            "disposition you argue for and the target step you would have "
            "carry it.",
            "  2. NON-NEGOTIABLES — what must not change, from your role's "
            "perspective, and why.",
            "  3. RATIONALE — the reasoning behind your proposal, in your own "
            "role's terms.",
            "",
            "Write prose under those three headings. Do not produce JSON in "
            "this round.",
        ]
    )


def build_round2_prompt(
    base_context: str,
    role: CouncilRole,
    charter: str,
    positions: dict[str, str],
) -> str:
    transcript = []
    for other in ROLE_ORDER:
        transcript += [
            f"--- POSITION: {other.value}"
            + (" (yours)" if other is role else ""),
            positions.get(other.value, "(no position recorded)"),
            "",
        ]

    return "\n".join(
        [
            base_context,
            "",
            "=== YOUR ROLE ===",
            f"You are the {role.value} member of a design council.",
            "",
            charter,
            "",
            "=== ROUND 1 POSITIONS FROM ALL SEVEN MEMBERS ===",
            "",
            *transcript,
            "=== THIS ROUND ===",
            "This is round 2. Having read all seven positions, respond under "
            "these headings:",
            "",
            "  1. CONCEDE — where another member has changed your mind, name "
            "the member and what you now accept.",
            "  2. HOLD — where you maintain your position against a specific "
            "objection, name the objection and why it does not move you.",
            "  3. CONFLICTS — where two positions cannot both be satisfied, "
            "state the conflict plainly rather than papering over it. A "
            "conflict named here is more useful to the synthesis than a "
            "compromise invented here.",
            "",
            "Write prose under those three headings. Do not produce JSON in "
            "this round.",
        ]
    )


def build_synthesis_prompt(
    base_context: str,
    positions: dict[str, str],
    critiques: dict[str, str],
) -> str:
    transcript = []
    for role in ROLE_ORDER:
        transcript += [
            f"--- ROUND 1 POSITION: {role.value}",
            positions.get(role.value, "(no position recorded)"),
            "",
            f"--- ROUND 2 CRITIQUE: {role.value}",
            critiques.get(role.value, "(no critique recorded)"),
            "",
        ]

    return "\n".join(
        [
            base_context,
            "",
            "=== COUNCIL TRANSCRIPT ===",
            "Seven members wrote positions independently, then responded to "
            "each other. The full transcript follows.",
            "",
            *transcript,
            "=== YOUR TASK ===",
            "You are the synthesist. Produce the Target-State Specification "
            "that best answers the council's deliberation.",
            "",
            "Where the members agree, follow them. Where they conflict, decide "
            "— and let the decision show in the dispositions and rationales "
            "rather than splitting the difference into something no member "
            "argued for.",
            "",
            "=== OUTPUT RULE ===",
            "Respond with a single JSON object only, conforming to the schema "
            "given above. No prose before or after it. No markdown code "
            "fences. The first character of your response must be '{' and the "
            "last must be '}'.",
        ]
    )


def build_synthesis_repair_prompt(
    original_prompt: str, bad_output: str, error: str
) -> str:
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


# --- the graph ---------------------------------------------------------------


def _call_and_log(
    client: ModelClient,
    logger: RunLogger,
    prompt: str,
    agent_role: str,
    workflow_id: str,
    sampling_params: dict[str, Any],
) -> str:
    """One call, recorded before its result is used for anything."""
    requested_model = logger.manifest.requested_model
    text, input_tokens, output_tokens, resolved_model = client.complete(
        prompt, model=requested_model
    )

    logger.log_call(
        CallRecord(
            timestamp_utc=utc_now_iso(),
            run_id=logger.run_id,
            condition=logger.condition,
            agent_role=agent_role,
            workflow_id=workflow_id,
            requested_model=requested_model,
            resolved_model=resolved_model,
            sampling_params=sampling_params,
            seed=None,
            prompt_hash=sha256_text(prompt),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=getattr(client, "last_thinking_tokens", None),
            raw_completion=text,
        )
    )

    return text


def build_graph(
    client: ModelClient,
    logger: RunLogger,
    kb: KnowledgeBase,
    sampling_params: dict[str, Any] | None = None,
):
    """Seven round-1 nodes, then seven round-2 nodes, then synthesis.

    The wiring is sequential rather than parallel. Round 1 agents are logically
    independent — none reads another's position — but running them in sequence
    keeps the call log in a fixed, reproducible order and avoids concurrent
    appends to it. Independence is enforced by what each prompt contains, not
    by when it runs.

    The client and logger are closed over rather than carried in the state:
    neither is data, and the state has to stay serialisable.
    """
    params = {} if sampling_params is None else dict(sampling_params)
    charters = {role: load_charter(role) for role in ROLE_ORDER}

    def round1_node(role: CouncilRole):
        def node(state: CouncilState) -> dict:
            base = build_base_context(state.encoding, kb)
            prompt = build_round1_prompt(base, role, charters[role])
            text = _call_and_log(
                client,
                logger,
                prompt,
                f"round1_{role.value}",
                state.encoding.workflow_id,
                params,
            )
            return {"positions": {**state.positions, role.value: text}}

        return node

    def round2_node(role: CouncilRole):
        def node(state: CouncilState) -> dict:
            base = build_base_context(state.encoding, kb)
            prompt = build_round2_prompt(base, role, charters[role], state.positions)
            text = _call_and_log(
                client,
                logger,
                prompt,
                f"round2_{role.value}",
                state.encoding.workflow_id,
                params,
            )
            return {"critiques": {**state.critiques, role.value: text}}

        return node

    def synthesis_node(state: CouncilState) -> dict:
        base = build_base_context(state.encoding, kb)
        prompt = build_synthesis_prompt(base, state.positions, state.critiques)
        text = _call_and_log(
            client,
            logger,
            prompt,
            SYNTHESIS_ROLE,
            state.encoding.workflow_id,
            params,
        )

        try:
            return {"tss_raw": text, "tss": parse_tss(text)}
        except (ValidationError, ValueError) as first_error:
            repair_prompt = build_synthesis_repair_prompt(prompt, text, str(first_error))
            repair_text = _call_and_log(
                client,
                logger,
                repair_prompt,
                SYNTHESIS_REPAIR_ROLE,
                state.encoding.workflow_id,
                params,
            )

            try:
                return {"tss_raw": repair_text, "tss": parse_tss(repair_text)}
            except (ValidationError, ValueError) as second_error:
                failure_path = logger.run_dir / RAW_FAILURE_FILENAME
                failure_path.write_text(
                    "=== synthesis ===\n"
                    f"{text}\n\n"
                    "=== synthesis error ===\n"
                    f"{first_error}\n\n"
                    "=== synthesis repair ===\n"
                    f"{repair_text}\n\n"
                    "=== repair error ===\n"
                    f"{second_error}\n"
                )
                raise CouncilError(
                    f"the council's synthesis did not produce a valid "
                    f"TargetStateSpec in two attempts. Raw output saved to "
                    f"{failure_path}.\n\nRepair attempt error:\n{second_error}"
                ) from second_error

    graph = StateGraph(CouncilState)

    for role in ROLE_ORDER:
        graph.add_node(f"round1_{role.value}", round1_node(role))
    for role in ROLE_ORDER:
        graph.add_node(f"round2_{role.value}", round2_node(role))
    graph.add_node(SYNTHESIS_ROLE, synthesis_node)

    node_names = (
        [f"round1_{role.value}" for role in ROLE_ORDER]
        + [f"round2_{role.value}" for role in ROLE_ORDER]
        + [SYNTHESIS_ROLE]
    )
    graph.add_edge(START, node_names[0])
    for earlier, later in zip(node_names, node_names[1:]):
        graph.add_edge(earlier, later)
    graph.add_edge(node_names[-1], END)

    return graph.compile()


def render_transcript(state: CouncilState) -> str:
    """The deliberation as a readable document, written beside the JSON."""
    lines = [
        f"# Council transcript — {state.encoding.workflow_id}",
        "",
        "## Round 1 — independent positions",
        "",
    ]
    for role in ROLE_ORDER:
        lines += [f"### {role.value}", "", state.positions.get(role.value, "(none)"), ""]

    lines += ["## Round 2 — critiques", ""]
    for role in ROLE_ORDER:
        lines += [f"### {role.value}", "", state.critiques.get(role.value, "(none)"), ""]

    return "\n".join(lines)


def run_council(
    encoding: WorkflowEncoding,
    kb: KnowledgeBase,
    client: ModelClient,
    logger: RunLogger,
    sampling_params: dict[str, Any] | None = None,
) -> tuple[TargetStateSpec, GateResult]:
    """Execute the council protocol and write the run directory.

    The run directory has the same shape as a baseline run — tss.json,
    gate_result.json, the manifest and the call log — so the two conditions are
    comparable with the same tools. The transcript is the one addition.
    """
    graph = build_graph(client, logger, kb, sampling_params)
    initial = CouncilState(encoding=encoding, kb_rendering=kb.render_for_prompt())

    final = CouncilState.model_validate(graph.invoke(initial))
    if final.tss is None:
        raise CouncilError("the council finished without a Target-State Specification")

    (logger.run_dir / TRANSCRIPT_FILENAME).write_text(render_transcript(final))
    (logger.run_dir / TSS_FILENAME).write_text(
        final.tss.model_dump_json(indent=2) + "\n"
    )

    gate_result = evaluate(encoding, final.tss)
    (logger.run_dir / GATE_RESULT_FILENAME).write_text(
        gate_result.model_dump_json(indent=2) + "\n"
    )

    return final.tss, gate_result
