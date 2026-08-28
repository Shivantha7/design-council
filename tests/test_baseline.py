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
