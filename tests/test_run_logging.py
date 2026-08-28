"""Tests for run provenance helpers."""

from pathlib import Path

import pytest

from design_council.run_logging import DEFAULT_ENV_PATH, REPO_ROOT, load_env


def write_env(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text)
    return path


def test_reads_key_value_pairs(tmp_path):
    path = write_env(tmp_path, "ALPHA=one\nBETA=two\n")
    environ = {}

    loaded = load_env(path, environ)

    assert loaded == ["ALPHA", "BETA"]
    assert environ == {"ALPHA": "one", "BETA": "two"}


def test_skips_blank_lines_and_comments(tmp_path):
    path = write_env(
        tmp_path,
        "\n"
        "# a comment\n"
        "ALPHA=one\n"
        "\n"
        "   # an indented comment\n"
        "BETA=two\n"
        "\n",
    )
    environ = {}

    assert load_env(path, environ) == ["ALPHA", "BETA"]
    assert environ == {"ALPHA": "one", "BETA": "two"}


def test_does_not_override_an_existing_variable(tmp_path):
    """A value exported in the shell or set by CI wins over the file."""
    path = write_env(tmp_path, "ALPHA=from_file\nBETA=from_file\n")
    environ = {"ALPHA": "from_shell"}

    loaded = load_env(path, environ)

    assert loaded == ["BETA"]
    assert environ["ALPHA"] == "from_shell"
    assert environ["BETA"] == "from_file"


def test_strips_surrounding_quotes(tmp_path):
    path = write_env(tmp_path, "ALPHA=\"one\"\nBETA='two'\nGAMMA=three\n")
    environ = {}

    load_env(path, environ)

    assert environ == {"ALPHA": "one", "BETA": "two", "GAMMA": "three"}


def test_keeps_an_inline_hash_as_part_of_the_value(tmp_path):
    """Stripping inline comments would truncate any secret containing a '#',
    and would quietly accept a placeholder sitting in front of a real key."""
    path = write_env(tmp_path, "ALPHA=value # not-a-comment\n")
    environ = {}

    load_env(path, environ)

    assert environ["ALPHA"] == "value # not-a-comment"


def test_keeps_equals_signs_inside_the_value(tmp_path):
    path = write_env(tmp_path, "ALPHA=a=b=c\n")
    environ = {}

    load_env(path, environ)

    assert environ["ALPHA"] == "a=b=c"


def test_missing_file_is_not_an_error(tmp_path):
    """Correct when the variables come from the shell instead."""
    environ = {}

    assert load_env(tmp_path / "nonexistent.env", environ) == []
    assert environ == {}


def test_malformed_line_raises_without_quoting_the_line(tmp_path):
    """The line may be the secret, so only its number is reported."""
    path = write_env(tmp_path, "ALPHA=one\nthis-line-has-no-equals-sign\n")
    environ = {}

    with pytest.raises(ValueError) as excinfo:
        load_env(path, environ)

    message = str(excinfo.value)
    assert "line 2" in message
    assert "this-line-has-no-equals-sign" not in message


def test_empty_variable_name_raises(tmp_path):
    path = write_env(tmp_path, "=orphaned\n")

    with pytest.raises(ValueError, match="empty variable name"):
        load_env(path, {})


def test_returns_names_only_never_values(tmp_path):
    """A caller logging the return value must not be able to leak a secret."""
    path = write_env(tmp_path, "SECRET_TOKEN=sk-do-not-log-me\n")
    environ = {}

    loaded = load_env(path, environ)

    assert loaded == ["SECRET_TOKEN"]
    assert "sk-do-not-log-me" not in repr(loaded)


def test_default_path_points_at_the_repo_root(tmp_path):
    assert DEFAULT_ENV_PATH == REPO_ROOT / ".env"
    assert (REPO_ROOT / "design_council").is_dir()


def test_load_env_does_not_touch_os_environ_when_given_a_mapping(tmp_path):
    """The environ parameter exists so tests never mutate the real process."""
    import os

    path = write_env(tmp_path, "DESIGN_COUNCIL_TEST_ONLY=x\n")
    environ = {}

    load_env(path, environ)

    assert "DESIGN_COUNCIL_TEST_ONLY" in environ
    assert "DESIGN_COUNCIL_TEST_ONLY" not in os.environ


# --- run provenance ----------------------------------------------------------

import json
import subprocess
from datetime import datetime, timezone

from pydantic import ValidationError

from design_council.run_logging import (
    CALLS_NAME,
    DEFAULT_REQUESTED_MODEL,
    MANIFEST_NAME,
    PROBE_AGENT_ROLE,
    MockClient,
    RunIntegrityError,
    RunLogger,
    make_run_id,
    resolve_model,
    sha256_file,
    sha256_text,
    utc_now_iso,
)
from design_council.schemas import CallRecord, Condition, RunManifest

EXPECTED_MODEL = "claude-sonnet-5"
ENCODING_PATH = (
    REPO_ROOT / "data" / "encodings" / "dev" / "p2p_vendor_invoice_processing.json"
)
KB_PATH = REPO_ROOT / "design_council" / "kb" / "ifrs_slfrs_kb.yaml"


def make_logger(
    tmp_path,
    resolved_model=EXPECTED_MODEL,
    run_id="20260828-221500-baseline-P2P-VIP-01-a3f9",
    git_dirty=False,
    allow_dirty=False,
):
    """A logger over a mock resolution. git_dirty is passed explicitly so the
    tests do not depend on the state of the real working tree."""
    resolution = resolve_model(
        MockClient(resolved_model=resolved_model), DEFAULT_REQUESTED_MODEL
    )
    return RunLogger(
        tmp_path / "runs",
        condition="baseline",
        workflow_id="P2P-VIP-01",
        requested_model=DEFAULT_REQUESTED_MODEL,
        resolution=resolution,
        model_created_at="2026-06-29T00:00:00Z",
        git_commit="0" * 40,
        encoding_sha256=sha256_file(ENCODING_PATH),
        kb_sha256=sha256_file(KB_PATH),
        config={"temperature": 0.0},
        allow_dirty=allow_dirty,
        git_dirty=git_dirty,
        run_id=run_id,
        created_utc="2026-08-28T22:15:00.000000Z",
    )


def make_record(logger, prompt="a prompt", resolved_model=EXPECTED_MODEL, agent_role="baseline_designer"):
    return CallRecord(
        timestamp_utc=utc_now_iso(),
        run_id=logger.run_id,
        condition=Condition.BASELINE,
        agent_role=agent_role,
        workflow_id="P2P-VIP-01",
        requested_model=DEFAULT_REQUESTED_MODEL,
        resolved_model=resolved_model,
        sampling_params={"temperature": 0.0, "max_tokens": 4096},
        seed=7,
        prompt_hash=sha256_text(prompt),
        input_tokens=11,
        output_tokens=22,
        raw_completion="canned completion",
    )


def read_lines(logger):
    return [l for l in logger.calls_path.read_text().splitlines() if l.strip()]


def test_run_id_has_the_specified_shape():
    run_id = make_run_id(
        Condition.BASELINE,
        "P2P-VIP-01",
        now=datetime(2026, 8, 28, 22, 15, 0, tzinfo=timezone.utc),
        suffix="a3f9",
    )

    assert run_id == "20260828-221500-baseline-P2P-VIP-01-a3f9"


def test_run_id_suffix_separates_runs_in_the_same_second():
    now = datetime(2026, 8, 28, 22, 15, 0, tzinfo=timezone.utc)
    ids = {make_run_id("council", "R2R-PC-01", now=now) for _ in range(50)}

    assert len(ids) > 1


def test_manifest_is_written_once_and_validates(tmp_path):
    logger = make_logger(tmp_path)

    assert logger.manifest_path.name == MANIFEST_NAME
    manifest = RunManifest.model_validate_json(logger.manifest_path.read_text())

    assert manifest.run_id == logger.run_id
    assert manifest.condition is Condition.BASELINE
    assert manifest.workflow_id == "P2P-VIP-01"
    assert manifest.encoding_sha256 == sha256_file(ENCODING_PATH)


def test_a_second_logger_will_not_reuse_a_run_directory(tmp_path):
    """Two loggers on one run id would interleave into one call log."""
    make_logger(tmp_path)

    with pytest.raises(RunIntegrityError, match="already exists"):
        make_logger(tmp_path)


def test_each_call_appends_exactly_one_parseable_line(tmp_path):
    logger = make_logger(tmp_path)

    for index in range(4):
        logger.log_call(make_record(logger, prompt=f"prompt {index}"))

    lines = read_lines(logger)
    assert len(lines) == 5  # four calls plus the resolution probe
    assert logger.calls_path.name == CALLS_NAME

    for line in lines:
        record = CallRecord.model_validate(json.loads(line))
        assert record.run_id == logger.run_id
        assert record.resolved_model == EXPECTED_MODEL


def test_identical_prompts_hash_identically_and_different_ones_do_not():
    assert sha256_text("the same prompt") == sha256_text("the same prompt")
    assert sha256_text("one prompt") != sha256_text("another prompt")
    assert len(sha256_text("x")) == 64


def test_an_abandoned_run_leaves_valid_partial_records(tmp_path):
    """Simulated crash: two of four calls made, then the process dies.

    Writing as the run proceeds is only worth anything if what landed before
    the crash is readable on its own.
    """
    logger = make_logger(tmp_path)
    logger.log_call(make_record(logger, prompt="prompt 0"))
    logger.log_call(make_record(logger, prompt="prompt 1"))

    run_dir = logger.run_dir
    del logger  # the process dies here; calls 2 and 3 never happen

    manifest = RunManifest.model_validate_json((run_dir / MANIFEST_NAME).read_text())
    assert manifest.workflow_id == "P2P-VIP-01"

    lines = [l for l in (run_dir / CALLS_NAME).read_text().splitlines() if l.strip()]
    assert len(lines) == 3  # the probe, then two of the four calls
    for line in lines:
        CallRecord.model_validate(json.loads(line))


def test_resolved_model_mismatch_raises_and_writes_nothing(tmp_path):
    """A run whose model changed underneath it is not one experimental unit."""
    logger = make_logger(tmp_path)
    logger.log_call(make_record(logger, prompt="prompt 0"))

    with pytest.raises(RunIntegrityError, match="resolved"):
        logger.log_call(make_record(logger, resolved_model="mock-model-2"))

    assert len(read_lines(logger)) == 2  # the probe and the one good call
    assert logger.call_count() == 2


def test_a_record_from_another_run_is_refused(tmp_path):
    logger = make_logger(tmp_path)
    foreign = make_record(logger).model_copy(update={"run_id": "some-other-run"})

    with pytest.raises(RunIntegrityError, match="belongs to run"):
        logger.log_call(foreign)

    assert logger.call_count() == 1  # the probe only


def test_git_commit_matches_rev_parse_head():
    from design_council.run_logging import git_commit

    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert git_commit() == expected
    assert len(expected) == 40


def test_encoding_and_kb_hashes_match_recomputed_file_hashes(tmp_path):
    import hashlib

    logger = make_logger(tmp_path)
    manifest = RunManifest.model_validate_json(logger.manifest_path.read_text())

    assert manifest.encoding_sha256 == hashlib.sha256(ENCODING_PATH.read_bytes()).hexdigest()
    assert manifest.kb_sha256 == hashlib.sha256(KB_PATH.read_bytes()).hexdigest()


def test_manifest_rejects_a_malformed_commit_or_hash(tmp_path):
    from design_council.schemas import ResolutionProbe

    with pytest.raises(ValidationError):
        RunManifest(
            run_id="r",
            created_utc="t",
            condition=Condition.BASELINE,
            workflow_id="w",
            requested_model="m",
            resolved_model="m",
            resolution_probe=ResolutionProbe(
                timestamp_utc="t", input_tokens=1, output_tokens=1
            ),
            model_created_at="c",
            git_commit="not-a-commit",
            git_dirty=False,
            encoding_sha256="0" * 64,
            kb_sha256="0" * 64,
        )


def test_mock_client_records_calls_and_needs_no_network():
    client = MockClient(text="hello", input_tokens=3, output_tokens=5)

    text, input_tokens, output_tokens, resolved = client.complete(
        "a prompt", temperature=0.0
    )

    assert (text, input_tokens, output_tokens, resolved) == (
        "hello",
        3,
        5,
        "mock-model-1",
    )
    assert client.calls == [("a prompt", {"temperature": 0.0})]


def test_mock_client_can_simulate_a_model_switch(tmp_path):
    """The mismatch path is reachable without waiting for a provider to do it."""
    logger = make_logger(tmp_path)
    client = MockClient(resolved_model="mock-model-2")

    text, input_tokens, output_tokens, resolved = client.complete("a prompt")
    record = make_record(logger).model_copy(update={"resolved_model": resolved})

    with pytest.raises(RunIntegrityError):
        logger.log_call(record)


def test_run_logging_imports_no_provider_sdk():
    """No provider SDK may be imported by the logging path; every test here
    runs against a mock and makes no network call."""
    import ast

    tree = ast.parse((REPO_ROOT / "design_council" / "run_logging.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not (imported & {"anthropic", "openai", "httpx", "requests"})


# --- dirty-tree policy -------------------------------------------------------


def test_refuses_a_dirty_tree_by_default(tmp_path):
    """A run from a modified tree is not reproducible from its commit alone."""
    with pytest.raises(RunIntegrityError, match="uncommitted changes"):
        make_logger(tmp_path, git_dirty=True)

    assert not (tmp_path / "runs").exists()


def test_allows_a_dirty_tree_when_asked_and_records_it(tmp_path):
    """Permitted, but never hidden: the manifest says the tree was dirty."""
    logger = make_logger(tmp_path, git_dirty=True, allow_dirty=True)

    manifest = RunManifest.model_validate_json(logger.manifest_path.read_text())
    assert manifest.git_dirty is True


def test_clean_tree_is_recorded_as_clean(tmp_path):
    logger = make_logger(tmp_path, git_dirty=False)

    manifest = RunManifest.model_validate_json(logger.manifest_path.read_text())
    assert manifest.git_dirty is False


def test_dirty_flag_defaults_to_the_real_working_tree(tmp_path, monkeypatch):
    """With no explicit value the logger asks git, rather than assuming clean."""
    import design_council.run_logging as run_logging

    monkeypatch.setattr(run_logging, "git_is_dirty", lambda *a, **k: True)

    with pytest.raises(RunIntegrityError, match="uncommitted changes"):
        RunLogger(
            tmp_path / "runs",
            condition="baseline",
            workflow_id="P2P-VIP-01",
            requested_model=DEFAULT_REQUESTED_MODEL,
            resolution=resolve_model(
                MockClient(resolved_model=EXPECTED_MODEL), DEFAULT_REQUESTED_MODEL
            ),
            model_created_at="2026-06-29T00:00:00Z",
            git_commit="0" * 40,
            encoding_sha256=sha256_file(ENCODING_PATH),
            kb_sha256=sha256_file(KB_PATH),
        )


# --- model resolution probe --------------------------------------------------


def test_resolve_model_returns_the_provider_answer_not_the_request():
    """An alias may resolve to something else; that is the whole point."""
    client = MockClient(resolved_model="claude-sonnet-5-20260629", input_tokens=4, output_tokens=2)

    resolution = resolve_model(client, DEFAULT_REQUESTED_MODEL)

    assert resolution.resolved_model == "claude-sonnet-5-20260629"
    assert resolution.probe.input_tokens == 4
    assert resolution.probe.output_tokens == 2
    assert resolution.probe.timestamp_utc.endswith("Z")

    prompt, params = client.calls[0]
    assert params["model"] == DEFAULT_REQUESTED_MODEL


def test_probe_is_recorded_in_the_manifest(tmp_path):
    logger = make_logger(tmp_path, resolved_model="claude-sonnet-5-20260629")

    manifest = RunManifest.model_validate_json(logger.manifest_path.read_text())
    assert manifest.requested_model == DEFAULT_REQUESTED_MODEL
    assert manifest.resolved_model == "claude-sonnet-5-20260629"
    assert manifest.resolution_probe.input_tokens == 11
    assert manifest.resolution_probe.output_tokens == 22


def test_probe_is_also_logged_as_the_first_call(tmp_path):
    """The resolution is an exchange with the model, so it appears in the log
    like any other rather than only as a manifest field."""
    logger = make_logger(tmp_path)

    lines = read_lines(logger)
    assert len(lines) == 1

    probe = CallRecord.model_validate(json.loads(lines[0]))
    assert probe.agent_role == PROBE_AGENT_ROLE
    assert probe.run_id == logger.run_id
    assert probe.requested_model == DEFAULT_REQUESTED_MODEL
    assert probe.resolved_model == EXPECTED_MODEL
    assert probe.seed is None
    assert probe.input_tokens == 11


def test_enforcement_uses_the_probed_value_not_the_requested_one(tmp_path):
    """expected_model comes from the manifest's resolved_model."""
    logger = make_logger(tmp_path, resolved_model="claude-sonnet-5-20260629")

    assert logger.expected_model == "claude-sonnet-5-20260629"
    assert logger.expected_model != DEFAULT_REQUESTED_MODEL

    logger.log_call(
        make_record(logger, resolved_model="claude-sonnet-5-20260629")
    )
    assert logger.call_count() == 2

    with pytest.raises(RunIntegrityError, match="resolved"):
        logger.log_call(make_record(logger, resolved_model=DEFAULT_REQUESTED_MODEL))


def test_a_client_that_changes_model_mid_run_trips_integrity(tmp_path):
    """The confound this exists to catch: the provider swaps snapshot partway."""
    client = MockClient(resolved_model=EXPECTED_MODEL)
    logger = make_logger(tmp_path)

    text, input_tokens, output_tokens, resolved = client.complete("prompt 0")
    logger.log_call(make_record(logger, resolved_model=resolved))

    client.resolved_model = "claude-sonnet-5-20261101"  # a new snapshot ships
    text, input_tokens, output_tokens, resolved = client.complete("prompt 1")

    with pytest.raises(RunIntegrityError, match="resolved"):
        logger.log_call(make_record(logger, resolved_model=resolved))

    assert logger.call_count() == 2  # probe plus the one good call


# --- configured model --------------------------------------------------------


def test_the_configured_model_is_sonnet_5():
    assert DEFAULT_REQUESTED_MODEL == "claude-sonnet-5"


def test_no_file_in_the_repository_requests_opus_5():
    """The experimental set runs on Sonnet 5. A stray Opus id in a config or
    fixture would silently produce runs from a different model.

    The id is assembled rather than written out, so that this file does not
    itself contain the string it is searching for.
    """
    needle = "claude-" + "opus-5"
    searched = []
    for directory in ["design_council", "tests", "scripts", "data"]:
        searched += sorted((REPO_ROOT / directory).rglob("*"))
    searched += [REPO_ROOT / "CLAUDE.md", REPO_ROOT / "README.md"]

    offenders = []
    for path in searched:
        if not path.is_file() or path.suffix in {".pyc"}:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if needle in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, f"files requesting {needle}: {offenders}"
