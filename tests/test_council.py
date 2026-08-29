"""Tests for the Design Council skeleton, against mocked clients only.

Nothing here touches the network, and council.py imports no provider SDK.
"""

import json
from pathlib import Path

import pytest

from design_council.agents.council import (
    CHARTERS_DIR,
    GATE_RESULT_FILENAME,
    RAW_FAILURE_FILENAME,
    ROLE_ORDER,
    SYNTHESIS_REPAIR_ROLE,
    SYNTHESIS_ROLE,
    TRANSCRIPT_FILENAME,
    TSS_FILENAME,
    CouncilError,
    CouncilRole,
    CouncilState,
    build_round1_prompt,
    build_round2_prompt,
    build_synthesis_prompt,
    build_base_context,
    charter_hashes,
    load_charter,
    run_council,
)
from design_council.kb.loader import KB_PATH, load_kb
from design_council.run_logging import (
    DEFAULT_REQUESTED_MODEL,
    PROBE_PROMPT,
    RunLogger,
    resolve_model,
    sha256_file,
)
from design_council.schemas import CallRecord, RunManifest, TargetStateSpec, WorkflowEncoding
from tests.test_baseline import valid_tss_json

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODING_PATH = (
    REPO_ROOT / "data" / "encodings" / "dev" / "p2p_vendor_invoice_processing.json"
)
RESOLVED = "claude-sonnet-5-20260629"

EXPECTED_ROLES = [
    "maximalist",
    "pragmatist",
    "finance_domain",
    "emerging_economy",
    "hitl_designer",
    "agentic_architect",
    "accounting_standards",
]


def encoding() -> WorkflowEncoding:
    with ENCODING_PATH.open() as handle:
        return WorkflowEncoding.model_validate(json.load(handle))


class CouncilMockClient:
    """Returns role-tagged deliberation text, and a valid TSS for synthesis.

    The synthesis prompt is recognised by its transcript header rather than by
    call count, so a change to the number of rounds would not silently make
    this mock answer the wrong prompt.
    """

    def __init__(self, tss_json: str, synthesis_responses: list[str] | None = None):
        self.tss_json = tss_json
        self.synthesis_responses = list(synthesis_responses or [])
        self.resolved_model = RESOLVED
        self.prompts: list[str] = []
        self.last_thinking_tokens = 7

    def complete(self, prompt, **params):
        if prompt == PROBE_PROMPT:
            return "ok", 5, 1, self.resolved_model

        self.prompts.append(prompt)

        if "=== COUNCIL TRANSCRIPT ===" in prompt or "FAILED VALIDATION" in prompt:
            text = (
                self.synthesis_responses.pop(0)
                if self.synthesis_responses
                else self.tss_json
            )
            return text, 500, 400, self.resolved_model

        marker = "ROUND 1 POSITIONS" if "This is round 2." in prompt else "round 1"
        return f"deliberation text ({marker})", 100, 80, self.resolved_model


def make_logger(tmp_path, client) -> RunLogger:
    return RunLogger(
        tmp_path / "runs",
        condition="council",
        workflow_id="P2P-VIP-01",
        requested_model=DEFAULT_REQUESTED_MODEL,
        resolution=resolve_model(client, DEFAULT_REQUESTED_MODEL),
        model_created_at="2026-06-29T00:00:00Z",
        git_commit="0" * 40,
        encoding_sha256=sha256_file(ENCODING_PATH),
        kb_sha256=sha256_file(KB_PATH),
        git_dirty=False,
        config={"charter_hashes": charter_hashes()},
    )


def logged_records(logger: RunLogger) -> list[CallRecord]:
    lines = [l for l in logger.calls_path.read_text().splitlines() if l.strip()]
    return [CallRecord.model_validate(json.loads(l)) for l in lines]


# --- roles and charters ------------------------------------------------------


def test_the_seven_roles_are_fixed_and_ordered():
    assert [role.value for role in ROLE_ORDER] == EXPECTED_ROLES


def test_every_role_has_a_charter_file_on_disk():
    for role in ROLE_ORDER:
        path = CHARTERS_DIR / f"{role.value}.md"
        assert path.exists(), f"missing charter: {path}"
        assert load_charter(role).strip()


def test_charter_hashes_cover_every_role():
    hashes = charter_hashes()

    assert sorted(hashes) == sorted(EXPECTED_ROLES)
    assert all(len(h) == 64 for h in hashes.values())


def test_charter_hashes_change_when_a_charter_changes(tmp_path, monkeypatch):
    """The hash is what attributes a run to the charters it actually ran with."""
    before = charter_hashes()["maximalist"]

    path = CHARTERS_DIR / "maximalist.md"
    original = path.read_text()
    try:
        path.write_text(original + "\nan edit\n")
        assert charter_hashes()["maximalist"] != before
    finally:
        path.write_text(original)

    assert charter_hashes()["maximalist"] == before


# --- prompts -----------------------------------------------------------------


def test_base_context_is_identical_to_the_baseline_prompt():
    """Condition parity: the council must differ in organisation, not in what
    it was shown."""
    from design_council.agents.baseline import build_prompt

    source, kb = encoding(), load_kb()

    assert build_base_context(source, kb) == build_prompt(source, kb)


def test_round1_prompt_carries_the_charter_and_forbids_json():
    base = build_base_context(encoding(), load_kb())
    prompt = build_round1_prompt(base, CouncilRole.MAXIMALIST, "CHARTER BODY HERE")

    assert base in prompt
    assert "CHARTER BODY HERE" in prompt
    assert "round 1" in prompt
    assert "NON-NEGOTIABLES" in prompt
    assert "Do not produce JSON" in prompt


def test_round1_prompt_shows_no_other_position():
    """Independence is enforced by prompt content, not by scheduling."""
    base = build_base_context(encoding(), load_kb())
    prompt = build_round1_prompt(base, CouncilRole.PRAGMATIST, "charter")

    assert "POSITION: maximalist" not in prompt
    assert "have not seen" in prompt


def test_round2_prompt_carries_all_seven_positions_labelled():
    base = build_base_context(encoding(), load_kb())
    positions = {role.value: f"position of {role.value}" for role in ROLE_ORDER}

    prompt = build_round2_prompt(base, CouncilRole.PRAGMATIST, "charter", positions)

    for role in ROLE_ORDER:
        assert f"--- POSITION: {role.value}" in prompt
        assert f"position of {role.value}" in prompt
    assert "(yours)" in prompt
    assert "CONCEDE" in prompt and "HOLD" in prompt and "CONFLICTS" in prompt


def test_synthesis_prompt_carries_the_whole_transcript_and_the_output_rule():
    base = build_base_context(encoding(), load_kb())
    positions = {role.value: f"position {role.value}" for role in ROLE_ORDER}
    critiques = {role.value: f"critique {role.value}" for role in ROLE_ORDER}

    prompt = build_synthesis_prompt(base, positions, critiques)

    for role in ROLE_ORDER:
        assert f"ROUND 1 POSITION: {role.value}" in prompt
        assert f"ROUND 2 CRITIQUE: {role.value}" in prompt
    assert "single JSON object only" in prompt
    assert "disposition_mapping" in prompt  # the schema came through the base


# --- the graph ---------------------------------------------------------------


def test_graph_runs_end_to_end_and_logs_fifteen_calls(tmp_path):
    source = encoding()
    client = CouncilMockClient(valid_tss_json(source))
    logger = make_logger(tmp_path, client)

    tss, gate_result = run_council(source, load_kb(), client, logger)

    assert isinstance(tss, TargetStateSpec)

    records = logged_records(logger)
    council_calls = [r for r in records if r.agent_role != "model_resolution_probe"]
    assert len(council_calls) == 15


def test_calls_are_logged_in_protocol_order_with_the_right_roles(tmp_path):
    source = encoding()
    client = CouncilMockClient(valid_tss_json(source))
    logger = make_logger(tmp_path, client)

    run_council(source, load_kb(), client, logger)

    roles = [r.agent_role for r in logged_records(logger)]
    expected = (
        ["model_resolution_probe"]
        + [f"round1_{role}" for role in EXPECTED_ROLES]
        + [f"round2_{role}" for role in EXPECTED_ROLES]
        + [SYNTHESIS_ROLE]
    )

    assert roles == expected


def test_state_accumulates_positions_then_critiques(tmp_path):
    """Round 2 must be able to see round 1: the seventh critique prompt carries
    all seven positions."""
    source = encoding()
    client = CouncilMockClient(valid_tss_json(source))
    logger = make_logger(tmp_path, client)

    run_council(source, load_kb(), client, logger)

    round1_prompts = client.prompts[:7]
    round2_prompts = client.prompts[7:14]
    synthesis_prompt = client.prompts[14]

    for prompt in round1_prompts:
        assert "This is round 1." in prompt
    for prompt in round2_prompts:
        assert "This is round 2." in prompt
        for role in EXPECTED_ROLES:
            assert f"--- POSITION: {role}" in prompt
    assert "=== COUNCIL TRANSCRIPT ===" in synthesis_prompt


def test_positions_and_critiques_are_keyed_by_role(tmp_path):
    source = encoding()
    kb = load_kb()
    client = CouncilMockClient(valid_tss_json(source))
    logger = make_logger(tmp_path, client)

    from design_council.agents.council import build_graph

    graph = build_graph(client, logger, kb)
    final = CouncilState.model_validate(
        graph.invoke(CouncilState(encoding=source, kb_rendering=kb.render_for_prompt()))
    )

    assert sorted(final.positions) == sorted(EXPECTED_ROLES)
    assert sorted(final.critiques) == sorted(EXPECTED_ROLES)
    assert final.tss is not None
    assert final.tss_raw is not None


# --- the run directory -------------------------------------------------------


def test_run_directory_shape_matches_a_baseline_run(tmp_path):
    source = encoding()
    client = CouncilMockClient(valid_tss_json(source))
    logger = make_logger(tmp_path, client)

    run_council(source, load_kb(), client, logger)

    names = {p.name for p in logger.run_dir.iterdir()}
    assert {"run_manifest.json", "calls.jsonl", TSS_FILENAME, GATE_RESULT_FILENAME} <= names
    assert TRANSCRIPT_FILENAME in names  # the council's one addition

    manifest = RunManifest.model_validate_json(
        (logger.run_dir / "run_manifest.json").read_text()
    )
    assert manifest.condition.value == "council"
    assert sorted(manifest.config["charter_hashes"]) == sorted(EXPECTED_ROLES)


def test_transcript_records_both_rounds_for_every_role(tmp_path):
    source = encoding()
    client = CouncilMockClient(valid_tss_json(source))
    logger = make_logger(tmp_path, client)

    run_council(source, load_kb(), client, logger)

    transcript = (logger.run_dir / TRANSCRIPT_FILENAME).read_text()
    assert "Round 1 — independent positions" in transcript
    assert "Round 2 — critiques" in transcript
    for role in EXPECTED_ROLES:
        assert f"### {role}" in transcript


def test_the_council_run_is_comparable_with_compare_tss(tmp_path):
    """A council run must be readable by the same instrument as a baseline run."""
    from scripts.compare_tss import load_run, render_text

    source = encoding()
    client = CouncilMockClient(valid_tss_json(source))
    logger = make_logger(tmp_path, client)
    run_council(source, load_kb(), client, logger)

    tss, gate_result = load_run(logger.run_dir)
    text = "\n".join(render_text(source, tss, gate_result, logger.run_dir))

    assert "1. DISPOSITION OF EVERY BASELINE STEP" in text
    assert "3. GATE RESULT" in text


# --- the synthesis repair path -----------------------------------------------


def test_synthesis_repair_path_logs_both_attempts(tmp_path):
    source = encoding()
    client = CouncilMockClient(
        valid_tss_json(source), synthesis_responses=["not json at all"]
    )
    logger = make_logger(tmp_path, client)

    tss, _ = run_council(source, load_kb(), client, logger)

    assert tss.workflow_id == source.workflow_id
    roles = [r.agent_role for r in logged_records(logger)]
    assert roles[-2:] == [SYNTHESIS_ROLE, SYNTHESIS_REPAIR_ROLE]
    assert len([r for r in roles if r != "model_resolution_probe"]) == 16


def test_two_synthesis_failures_save_raw_output_and_raise(tmp_path):
    source = encoding()
    client = CouncilMockClient(
        valid_tss_json(source), synthesis_responses=["not json", "still not json"]
    )
    logger = make_logger(tmp_path, client)

    with pytest.raises(CouncilError, match="two attempts"):
        run_council(source, load_kb(), client, logger)

    raw = (logger.run_dir / RAW_FAILURE_FILENAME).read_text()
    assert "not json" in raw and "still not json" in raw
    assert not (logger.run_dir / TSS_FILENAME).exists()


def test_council_imports_no_provider_sdk():
    import ast

    tree = ast.parse((REPO_ROOT / "design_council" / "agents" / "council.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not (imported & {"anthropic", "openai"})
