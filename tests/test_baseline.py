"""Tests for the single-agent baseline, against a mocked client only.

Nothing here touches the network. The provider SDK is never imported by the
code under test: AnthropicClient lives in its own module and is not exercised
here, which is what keeps the whole pipeline testable offline.
"""

import json
from pathlib import Path

import pytest

from design_council.agents.baseline import (
    AGENT_ROLE,
    GATE_RESULT_FILENAME,
    RAW_FAILURE_FILENAME,
    REPAIR_AGENT_ROLE,
    TSS_FILENAME,
    BaselineError,
    build_prompt,
    run_baseline,
    strip_code_fences,
)
from design_council.kb.loader import KB_PATH, load_kb
from design_council.run_logging import (
    DEFAULT_REQUESTED_MODEL,
    PROBE_PROMPT,
    RunLogger,
    resolve_model,
    sha256_file,
)
from design_council.schemas import CallRecord, GateResult, TargetStateSpec, WorkflowEncoding

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODING_PATH = (
    REPO_ROOT / "data" / "encodings" / "dev" / "p2p_vendor_invoice_processing.json"
)
RESOLVED = "claude-sonnet-5-20260629"


def encoding() -> WorkflowEncoding:
    with ENCODING_PATH.open() as handle:
        return WorkflowEncoding.model_validate(json.load(handle))


def valid_tss_json(source: WorkflowEncoding) -> str:
    """An identity redesign: schema-valid and gate-clean."""
    return json.dumps(
        {
            "workflow_id": source.workflow_id,
            "baseline_step_ids": source.step_ids(),
            "steps": [step.model_dump() for step in source.steps],
            "disposition_mapping": [
                {
                    "baseline_step_id": step.step_id,
                    "disposition": "retained",
                    "rationale": "Carried over unchanged.",
                    "target_step_ids": [step.step_id],
                }
                for step in source.steps
            ],
        }
    )


class ScriptedClient:
    """A ModelClient returning a fixed sequence of completions.

    The resolution probe is answered without consuming the script, since it is
    infrastructure rather than part of the baseline's exchange — the same
    client serves both in production.
    """

    def __init__(self, responses: list[str], resolved_model: str = RESOLVED) -> None:
        self.responses = list(responses)
        self.resolved_model = resolved_model
        self.prompts: list[str] = []

    def complete(self, prompt, **params):
        if prompt == PROBE_PROMPT:
            return "ok", 5, 1, self.resolved_model

        self.prompts.append(prompt)
        text = self.responses.pop(0) if self.responses else "{}"
        return text, 100, 200, self.resolved_model


def make_logger(tmp_path, client) -> RunLogger:
    return RunLogger(
        tmp_path / "runs",
        condition="baseline",
        workflow_id="P2P-VIP-01",
        requested_model=DEFAULT_REQUESTED_MODEL,
        resolution=resolve_model(client, DEFAULT_REQUESTED_MODEL),
        model_created_at="2026-06-29T00:00:00Z",
        git_commit="0" * 40,
        encoding_sha256=sha256_file(ENCODING_PATH),
        kb_sha256=sha256_file(KB_PATH),
        git_dirty=False,
    )


def logged_roles(logger: RunLogger) -> list[str]:
    lines = [l for l in logger.calls_path.read_text().splitlines() if l.strip()]
    return [CallRecord.model_validate(json.loads(l)).agent_role for l in lines]


# --- the prompt --------------------------------------------------------------


def test_prompt_contains_the_encoding_including_requirements():
    source = encoding()
    prompt = build_prompt(source, load_kb())

    assert source.workflow_id in prompt
    for step in source.steps:
        assert step.step_id in prompt
    for requirement in source.requirements:
        assert requirement.requirement_id in prompt
        assert requirement.statement in prompt


def test_prompt_contains_the_whole_knowledge_base():
    """Condition parity: the baseline sees everything the council will see."""
    kb = load_kb()
    prompt = build_prompt(encoding(), kb)

    assert kb.render_for_prompt() in prompt
    for entry in kb.entries:
        assert f"[{entry.id}]" in prompt


def test_prompt_contains_the_output_schema():
    prompt = build_prompt(encoding(), load_kb())

    assert "disposition_mapping" in prompt
    assert "baseline_step_ids" in prompt
    assert "target_step_ids" in prompt


def test_prompt_states_the_disposition_convention():
    prompt = build_prompt(encoding(), load_kb())

    assert "exactly once" in prompt
    for word in ["eliminated", "merged", "absorbed", "retained", "restructured"]:
        assert word in prompt


def test_prompt_states_the_output_rule():
    prompt = build_prompt(encoding(), load_kb())

    assert "single JSON object only" in prompt
    assert "no markdown code fences" in prompt.lower()


# --- fence stripping ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"a": 1}',
        '```\n{"a": 1}\n```',
        '```json\n{"a": 1}\n```',
        '  ```json\n{"a": 1}\n```  ',
    ],
)
def test_strip_code_fences(raw):
    assert json.loads(strip_code_fences(raw)) == {"a": 1}


# --- the happy path ----------------------------------------------------------


def test_valid_response_writes_tss_and_gate_result(tmp_path):
    source = encoding()
    client = ScriptedClient([valid_tss_json(source)])
    logger = make_logger(tmp_path, client)

    tss, gate_result = run_baseline(source, load_kb(), client, logger)

    assert isinstance(tss, TargetStateSpec)
    assert (logger.run_dir / TSS_FILENAME).exists()
    assert (logger.run_dir / GATE_RESULT_FILENAME).exists()

    written = TargetStateSpec.model_validate_json(
        (logger.run_dir / TSS_FILENAME).read_text()
    )
    assert written.workflow_id == source.workflow_id

    written_gate = GateResult.model_validate_json(
        (logger.run_dir / GATE_RESULT_FILENAME).read_text()
    )
    assert written_gate.conformance_score == gate_result.conformance_score

    assert logged_roles(logger) == ["model_resolution_probe", AGENT_ROLE]


def test_a_fenced_response_still_succeeds(tmp_path):
    source = encoding()
    client = ScriptedClient([f"```json\n{valid_tss_json(source)}\n```"])
    logger = make_logger(tmp_path, client)

    tss, _ = run_baseline(source, load_kb(), client, logger)

    assert tss.workflow_id == source.workflow_id
    assert logged_roles(logger) == ["model_resolution_probe", AGENT_ROLE]


# --- the repair path ---------------------------------------------------------


def test_invalid_json_triggers_one_repair_attempt(tmp_path):
    source = encoding()
    client = ScriptedClient(["this is not JSON at all", valid_tss_json(source)])
    logger = make_logger(tmp_path, client)

    tss, _ = run_baseline(source, load_kb(), client, logger)

    assert tss.workflow_id == source.workflow_id
    assert logged_roles(logger) == [
        "model_resolution_probe",
        AGENT_ROLE,
        REPAIR_AGENT_ROLE,
    ]


def test_repair_prompt_feeds_back_the_error_verbatim(tmp_path):
    """A schema-valid JSON object that breaks a model validator."""
    source = encoding()
    broken = json.loads(valid_tss_json(source))
    broken["disposition_mapping"] = broken["disposition_mapping"][:-1]  # drop one step

    client = ScriptedClient([json.dumps(broken), valid_tss_json(source)])
    logger = make_logger(tmp_path, client)

    run_baseline(source, load_kb(), client, logger)

    repair_prompt = client.prompts[-1]
    assert "FAILED VALIDATION" in repair_prompt
    assert "missing a disposition" in repair_prompt
    assert "VIP-08" in repair_prompt


def test_two_failures_save_raw_output_and_raise(tmp_path):
    """No looping: two attempts is the whole budget."""
    source = encoding()
    client = ScriptedClient(["not json", "still not json"])
    logger = make_logger(tmp_path, client)

    with pytest.raises(BaselineError, match="two"):
        run_baseline(source, load_kb(), client, logger)

    raw = (logger.run_dir / RAW_FAILURE_FILENAME).read_text()
    assert "not json" in raw
    assert "still not json" in raw

    assert not (logger.run_dir / TSS_FILENAME).exists()
    assert not (logger.run_dir / GATE_RESULT_FILENAME).exists()
    assert logged_roles(logger) == [
        "model_resolution_probe",
        AGENT_ROLE,
        REPAIR_AGENT_ROLE,
    ]


def test_baseline_does_not_import_a_provider_sdk():
    import ast

    tree = ast.parse((REPO_ROOT / "design_council" / "agents" / "baseline.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not (imported & {"anthropic", "openai"})


# --- reasoning token accounting ----------------------------------------------


class ThinkingClient(ScriptedClient):
    """A client that reports a reasoning-token breakdown, as the real one does."""

    def __init__(self, responses, thinking_tokens=64, **kwargs):
        super().__init__(responses, **kwargs)
        self.last_thinking_tokens = thinking_tokens


def test_thinking_tokens_are_recorded_when_the_provider_reports_them(tmp_path):
    source = encoding()
    client = ThinkingClient([valid_tss_json(source)], thinking_tokens=64)
    logger = make_logger(tmp_path, client)

    run_baseline(source, load_kb(), client, logger)

    lines = [l for l in logger.calls_path.read_text().splitlines() if l.strip()]
    designer = [
        CallRecord.model_validate(json.loads(l))
        for l in lines
        if CallRecord.model_validate(json.loads(l)).agent_role == AGENT_ROLE
    ][0]

    assert designer.thinking_tokens == 64
    assert designer.output_tokens >= designer.thinking_tokens


def test_thinking_tokens_are_none_when_the_provider_reports_nothing(tmp_path):
    """A client with no breakdown must not fabricate one."""
    source = encoding()
    client = ScriptedClient([valid_tss_json(source)])
    logger = make_logger(tmp_path, client)

    run_baseline(source, load_kb(), client, logger)

    lines = [l for l in logger.calls_path.read_text().splitlines() if l.strip()]
    records = [CallRecord.model_validate(json.loads(l)) for l in lines]

    assert all(r.thinking_tokens is None for r in records)


def test_sampling_params_carry_only_what_is_sent():
    from design_council.agents.anthropic_client import AnthropicClient

    client = AnthropicClient("claude-sonnet-5", max_tokens=8000)

    assert client.sampling_params() == {"max_tokens": 8000}
    assert "temperature" not in client.sampling_params()


# --- SDK limits and the streaming contract -----------------------------------


def test_sdk_nonstreaming_limit_matches_the_sdk_arithmetic():
    """Pinned from anthropic/_base_client.py: a non-streaming request whose
    max_tokens implies more than ten minutes is refused."""
    from design_council.agents.anthropic_client import SDK_NONSTREAMING_MAX_TOKENS

    assert SDK_NONSTREAMING_MAX_TOKENS == 21333

    maximum_time, default_time = 60 * 60, 60 * 10
    expected = maximum_time * SDK_NONSTREAMING_MAX_TOKENS / 128_000
    assert expected <= default_time

    just_over = maximum_time * (SDK_NONSTREAMING_MAX_TOKENS + 1) / 128_000
    assert just_over > default_time


def test_the_ceilings_sit_where_they_are_meant_to():
    from design_council.agents.anthropic_client import (
        DEFAULT_MAX_TOKENS,
        SDK_NONSTREAMING_MAX_TOKENS,
        SYNTHESIS_MAX_TOKENS,
    )

    assert DEFAULT_MAX_TOKENS == 16000
    assert SYNTHESIS_MAX_TOKENS == 24000

    # Deliberation would survive without streaming; synthesis would not. This
    # is the asymmetry that made the failure appear only on the last call.
    assert DEFAULT_MAX_TOKENS < SDK_NONSTREAMING_MAX_TOKENS
    assert SYNTHESIS_MAX_TOKENS > SDK_NONSTREAMING_MAX_TOKENS


def test_the_council_synthesis_ceiling_matches_the_client_constant():
    from design_council.agents.anthropic_client import SYNTHESIS_MAX_TOKENS as client_ceiling
    from design_council.agents.council import SYNTHESIS_MAX_TOKENS as council_ceiling

    assert council_ceiling == client_ceiling


def test_the_client_streams_every_call():
    """A revert to messages.create() would work in tests and fail in production
    on the synthesis call only, so the call style is asserted directly."""
    source = (REPO_ROOT / "design_council" / "agents" / "anthropic_client.py").read_text()

    assert "messages.stream(" in source
    assert "get_final_message()" in source
    assert "messages.create(" not in source


def test_the_pipeline_reads_only_fields_a_streamed_message_carries():
    """The three contract points between the SDK and this project: the resolved
    model, the usage block, and the stop reason. All three are present on the
    final message of a stream, and all three are read by name here."""
    source = (REPO_ROOT / "design_council" / "agents" / "anthropic_client.py").read_text()

    assert "response.model" in source
    assert "response.usage.input_tokens" in source
    assert "response.usage.output_tokens" in source
    assert "response.stop_reason" in source


# --- disposition labelling fidelity ------------------------------------------


def test_the_convention_is_v1_without_the_labelling_fidelity_paragraph():
    """v1 restored for the held-out set (docs/freeze_notes.md, 11 Oct 2026).

    The v2 paragraph must be absent, so held-out prompts match the v1 dev grid.
    """
    from design_council.agents.baseline import DISPOSITION_CONVENTION

    assert DISPOSITION_CONVENTION.endswith(
        "listed there must be the step_id of a step you define in 'steps'."
    )
    for phrase in [
        "Label dispositions by what structurally happened, not by what sounds safer",
        "the disposition is eliminated",
        "target_step_ids must identify the carrier",
        "Do not record an elimination as a merge to soften it",
        "the requirements gate, not the label, is the safety mechanism",
        "a renamed step with the same actor and mechanism is retained",
    ]:
        assert phrase not in DISPOSITION_CONVENTION, phrase


def test_the_convention_reaches_both_conditions_identically():
    """Condition parity: one definition, so baseline and council cannot drift."""
    from design_council.agents.baseline import DISPOSITION_CONVENTION, build_prompt
    from design_council.agents.council import build_base_context, build_round1_prompt
    from design_council.kb.loader import load_kb

    source, kb = encoding(), load_kb()
    baseline_prompt = build_prompt(source, kb)
    council_context = build_base_context(source, kb)

    assert DISPOSITION_CONVENTION in baseline_prompt
    assert DISPOSITION_CONVENTION in council_context
    assert baseline_prompt == council_context

    round1 = build_round1_prompt(council_context, list(__import__(
        "design_council.agents.council", fromlist=["CouncilRole"]).CouncilRole)[0],
        "charter")
    assert DISPOSITION_CONVENTION in round1


def test_the_convention_hash_is_recorded_and_versioned():
    import hashlib

    from design_council.agents.baseline import (
        DISPOSITION_CONVENTION,
        DISPOSITION_CONVENTION_VERSION,
        prompt_fragment_hashes,
    )

    expected = hashlib.sha256(DISPOSITION_CONVENTION.encode("utf-8")).hexdigest()
    assert prompt_fragment_hashes()["disposition_convention"] == expected
    assert DISPOSITION_CONVENTION_VERSION == "v1, restored 11 Oct 2026"

    for script in ["run_baseline.py", "run_council.py"]:
        source = (REPO_ROOT / "scripts" / script).read_text()
        assert '"prompt_fragment_hashes": prompt_fragment_hashes()' in source
        assert (
            '"disposition_convention_version": DISPOSITION_CONVENTION_VERSION' in source
        )
