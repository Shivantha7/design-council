"""Tests for stream-failure retry and full attempt logging."""

import json
from pathlib import Path

import pytest

from design_council.agents.anthropic_client import StreamInterrupted
from design_council.run_logging import (
    DEFAULT_REQUESTED_MODEL,
    PROBE_PROMPT,
    STREAM_RETRY_BACKOFF,
    RunLogger,
    StreamRetriesExhausted,
    log_model_call,
    resolve_model,
    sha256_file,
)
from design_council.schemas import AttemptStatus, CallRecord

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODING_PATH = (
    REPO_ROOT / "data" / "encodings" / "dev" / "p2p_vendor_invoice_processing.json"
)
KB_PATH = REPO_ROOT / "design_council" / "kb" / "ifrs_slfrs_kb.yaml"
RESOLVED = "claude-sonnet-5"


class FlakyClient:
    """Fails the first `failures` non-probe calls mid-stream, then succeeds."""

    def __init__(self, failures: int, text: str = "the completion") -> None:
        self.failures = failures
        self.text = text
        self.attempts = 0
        self.resolved_model = RESOLVED
        self.last_thinking_tokens = 5
        self.last_stop_reason = "end_turn"

    def complete(self, prompt, **params):
        if prompt == PROBE_PROMPT:
            return "ok", 5, 1, self.resolved_model

        self.attempts += 1
        if self.attempts <= self.failures:
            raise StreamInterrupted(
                "stream interrupted: RemoteProtocolError: incomplete chunked read",
                partial_text="a partial senten",
                input_tokens=7900,
                output_tokens=412,
                resolved_model=self.resolved_model,
            )

        return self.text, 8000, 900, self.resolved_model


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
    )


def records_of(logger) -> list[CallRecord]:
    return [
        CallRecord.model_validate_json(line)
        for line in logger.calls_path.read_text().splitlines()
        if line.strip()
    ]


def no_sleep(_seconds):
    return None


# --- retry mechanics ---------------------------------------------------------


def test_one_stream_failure_then_success_logs_two_records(tmp_path):
    client = FlakyClient(failures=1)
    logger = make_logger(tmp_path, client)

    record = log_model_call(
        client, logger, "a prompt", "round1_maximalist", "P2P-VIP-01",
        {"max_tokens": 16000}, sleep=no_sleep,
    )

    written = [r for r in records_of(logger) if r.agent_role == "round1_maximalist"]
    assert len(written) == 2
    assert written[0].attempt_status is AttemptStatus.STREAM_FAILED
    assert written[1].attempt_status is AttemptStatus.OK

    # only the successful attempt is returned to the caller
    assert record.attempt_status is AttemptStatus.OK
    assert record.raw_completion == "the completion"


def test_a_failed_attempt_keeps_its_partial_text_and_billed_tokens(tmp_path):
    client = FlakyClient(failures=1)
    logger = make_logger(tmp_path, client)

    log_model_call(
        client, logger, "a prompt", "round1_maximalist", "P2P-VIP-01",
        sleep=no_sleep,
    )

    failed = [
        r for r in records_of(logger) if r.attempt_status is AttemptStatus.STREAM_FAILED
    ][0]
    assert failed.raw_completion == "a partial senten"
    assert failed.input_tokens == 7900  # billed, and counted in cost totals
    assert failed.output_tokens == 412
    assert failed.agent_role == "round1_maximalist"


def test_two_failures_then_success(tmp_path):
    client = FlakyClient(failures=2)
    logger = make_logger(tmp_path, client)

    record = log_model_call(
        client, logger, "a prompt", "synthesis", "P2P-VIP-01", sleep=no_sleep
    )

    statuses = [r.attempt_status.value for r in records_of(logger) if r.agent_role == "synthesis"]
    assert statuses == ["stream_failed", "stream_failed", "ok"]
    assert record.raw_completion == "the completion"


def test_three_consecutive_failures_raise(tmp_path):
    client = FlakyClient(failures=3)
    logger = make_logger(tmp_path, client)

    with pytest.raises(StreamRetriesExhausted, match="3 consecutive attempts"):
        log_model_call(
            client, logger, "a prompt", "round2_pragmatist", "P2P-VIP-01",
            sleep=no_sleep,
        )

    written = [r for r in records_of(logger) if r.agent_role == "round2_pragmatist"]
    assert len(written) == 3
    assert all(r.attempt_status is AttemptStatus.STREAM_FAILED for r in written)


def test_backoff_is_two_then_eight_seconds(tmp_path):
    client = FlakyClient(failures=2)
    logger = make_logger(tmp_path, client)
    slept = []

    log_model_call(
        client, logger, "a prompt", "synthesis", "P2P-VIP-01",
        sleep=slept.append,
    )

    assert slept == [2.0, 8.0]
    assert STREAM_RETRY_BACKOFF == (2.0, 8.0)


def test_the_normal_path_writes_one_ok_record(tmp_path):
    client = FlakyClient(failures=0)
    logger = make_logger(tmp_path, client)

    log_model_call(client, logger, "a prompt", "baseline_designer", "P2P-VIP-01")

    written = [r for r in records_of(logger) if r.agent_role == "baseline_designer"]
    assert len(written) == 1
    assert written[0].attempt_status is AttemptStatus.OK
    assert written[0].output_tokens == 900


# --- the state guarantee -----------------------------------------------------


def test_a_failed_attempt_never_enters_council_state(tmp_path):
    """The guarantee that matters: partial text from a broken stream must not
    become a council position."""
    from design_council.agents.council import CouncilState, build_graph
    from design_council.kb.loader import load_kb
    from design_council.schemas import WorkflowEncoding
    from tests.test_baseline import valid_tss_json
    from tests.test_council import CouncilMockClient

    with ENCODING_PATH.open() as handle:
        source = WorkflowEncoding.model_validate(json.load(handle))
    kb = load_kb()

    class FlakyCouncilClient(CouncilMockClient):
        """Breaks the stream once on the maximalist's first attempt."""

        def __init__(self, tss_json):
            super().__init__(tss_json)
            self.broken = False
            self.last_stop_reason = "end_turn"

        def complete(self, prompt, **params):
            if "This is round 1." in prompt and not self.broken:
                self.broken = True
                raise StreamInterrupted(
                    "stream interrupted", partial_text="PROPOSED DISPOSI",
                    input_tokens=7900, output_tokens=200,
                    resolved_model=self.resolved_model,
                )
            return super().complete(prompt, **params)

    client = FlakyCouncilClient(valid_tss_json(source))
    logger = make_logger(tmp_path, client)

    import design_council.run_logging as run_logging

    original = run_logging.time.sleep
    run_logging.time.sleep = no_sleep
    try:
        graph = build_graph(client, logger, kb)
        final = CouncilState.model_validate(
            graph.invoke(
                CouncilState(encoding=source, kb_rendering=kb.render_for_prompt())
            )
        )
    finally:
        run_logging.time.sleep = original

    # the partial text is in the log...
    failed = [
        r for r in records_of(logger) if r.attempt_status is AttemptStatus.STREAM_FAILED
    ]
    assert len(failed) == 1
    assert failed[0].raw_completion == "PROPOSED DISPOSI"

    # ...but never in the deliberation
    assert "PROPOSED DISPOSI" not in final.positions["maximalist"]
    assert all("PROPOSED DISPOSI" not in text for text in final.positions.values())
    assert all("PROPOSED DISPOSI" not in text for text in final.critiques.values())
    assert len(final.positions) == 7


# --- the accounting rule -----------------------------------------------------


def test_content_filters_to_ok_but_cost_counts_everything(tmp_path):
    """The rule fixed in docs/freeze_notes.md."""
    client = FlakyClient(failures=1)
    logger = make_logger(tmp_path, client)

    log_model_call(
        client, logger, "a prompt", "round1_maximalist", "P2P-VIP-01", sleep=no_sleep
    )

    written = [r for r in records_of(logger) if r.agent_role == "round1_maximalist"]

    content = [r.raw_completion for r in written if r.attempt_status is AttemptStatus.OK]
    assert content == ["the completion"]

    billed_input = sum(r.input_tokens for r in written)
    assert billed_input == 7900 + 8000  # the failed attempt counts


def test_the_accounting_rule_is_documented_where_it_applies():
    from design_council.measures import depth

    assert "ACCOUNTING RULE" in depth.__doc__
    assert "attempt_status == 'ok'" in depth.__doc__
    assert (REPO_ROOT / "docs" / "freeze_notes.md").exists()
    notes = (REPO_ROOT / "docs" / "freeze_notes.md").read_text()
    assert "Call-record accounting rule" in notes
    assert "before any held-out run" in notes
