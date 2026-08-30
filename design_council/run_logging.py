"""Run provenance: what was sent to a model, what came back, and under what settings.

This module will hold the run-logging contract required by CLAUDE.md — model,
pinned version, seed, token counts and raw output written to runs/ for every
LLM call. It starts with the piece that has to come first: getting the
credential into the process without it ever reaching a log.

load_env() is deliberately small and dependency-free. python-dotenv would do
the same job, but a hand-written reader is auditable at a glance, which matters
more here than the handful of conveniences it lacks.
"""

import hashlib
import os
import socket
import time
import secrets
import subprocess
from collections.abc import MutableMapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from design_council.schemas.run_records import (
    AttemptStatus,
    CallRecord,
    Condition,
    ResolutionProbe,
    RunManifest,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = REPO_ROOT / ".env"
DEFAULT_RUNS_ROOT = REPO_ROOT / "runs"

DEFAULT_REQUESTED_MODEL = "claude-sonnet-5"

PROBE_AGENT_ROLE = "model_resolution_probe"
PROBE_PROMPT = "Reply with the single word: ok"

MANIFEST_NAME = "run_manifest.json"
CALLS_NAME = "calls.jsonl"


# Backoff between stream retries, in seconds: five retries after the first
# attempt, six attempts in all, spanning about five minutes of patience. Sized
# against observed reality — a machine that lost DNS mid-run defeated a ten
# second schedule three attempts in a row.
STREAM_RETRY_BACKOFF = (2.0, 8.0, 30.0, 90.0, 180.0)

# Before every retry after the first, wait for the network to come back rather
# than spending an attempt on a link that is provably dead.
CONNECTIVITY_HOST = "api.anthropic.com"
CONNECTIVITY_PORT = 443
CONNECTIVITY_WAIT_SECONDS = 60.0
CONNECTIVITY_POLL_SECONDS = 3.0


class StreamRetriesExhausted(Exception):
    """Every attempt at one call died mid-stream.

    Every attempt is in the log with attempt_status 'stream_failed'. After five
    retries spread over five minutes, with the network confirmed live before
    each one, another try is not obviously better than stopping — and a run
    that limped on through sustained network failure would be hard to trust.
    """


class CallTruncatedError(Exception):
    """A model call stopped at max_tokens instead of finishing.

    The completion is partial, and where the whole budget went to reasoning it
    may be empty. Either way it is not a contribution: a run that carried it
    forward would reconcile around something the model never finished saying.
    The call is logged with truncated=True before this is raised, so the record
    shows what happened.
    """


class RunIntegrityError(Exception):
    """A run cannot be recorded as the thing it claims to be.

    Raised when the provider resolved a different model than the run was
    started with, when a record belongs to another run, or when a run
    directory already exists. Each would make the recorded provenance false,
    so the write is refused rather than made.
    """


def load_env(
    path: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> list[str]:
    """Read KEY=VALUE lines from a .env file into the environment.

    Rules, all of them deliberate:

    - Blank lines and whole-line comments (first non-space character '#') are
      skipped. Inline comments are NOT stripped: a '#' after a value is part of
      the value. Stripping them would silently truncate any secret containing a
      '#', and would have quietly accepted a placeholder in place of a real key.
    - An existing environment variable is never overridden, so a value exported
      in the shell or set by CI wins over the file.
    - Surrounding single or double quotes are removed from the value.
    - A line that is neither blank, nor a comment, nor KEY=VALUE raises
      ValueError naming the line number only. The line's text is never included
      in the message, because it may be the secret.
    - A missing file is not an error: returning nothing is correct when the
      variables come from the shell instead.

    Returns the names of the variables it set, in file order. Names only —
    never values — so that a caller logging the result cannot leak a secret.
    """
    source = DEFAULT_ENV_PATH if path is None else path
    target = os.environ if environ is None else environ

    if not source.exists():
        return []

    loaded = []
    for number, raw in enumerate(source.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(
                f"{source.name} line {number}: expected KEY=VALUE, comment or "
                f"blank line"
            )

        name, _, value = line.partition("=")
        name = name.strip()
        if not name:
            raise ValueError(f"{source.name} line {number}: empty variable name")

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        if name in target:
            continue

        target[name] = value
        loaded.append(name)

    return loaded


# --- provenance helpers ------------------------------------------------------


def utc_now_iso() -> str:
    """Current UTC time as an ISO 8601 string ending in Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha256_text(text: str) -> str:
    """Hex digest of a string, encoded UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Hex digest of a file's bytes.

    Content-addressed rather than path-addressed: an encoding edited after a
    run cannot silently change what that run was carried out against.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit(repo_root: Path | None = None) -> str:
    """The commit the working tree is at.

    Records which code produced a run. It says nothing about whether the tree
    was clean at the time; see git_is_dirty().
    """
    root = REPO_ROOT if repo_root is None else repo_root
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def git_is_dirty(repo_root: Path | None = None) -> bool:
    """Whether the working tree has uncommitted changes.

    A run made from a dirty tree is not reproducible from its commit alone.
    The caller decides what to do about that; this only reports it.
    """
    root = REPO_ROOT if repo_root is None else repo_root
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def make_run_id(
    condition: Condition | str,
    workflow_id: str,
    now: datetime | None = None,
    suffix: str | None = None,
) -> str:
    """<UTC yyyymmdd-hhmmss>-<condition>-<workflow_id>-<4 hex>.

    The random suffix separates runs started in the same second; the timestamp
    keeps directory listings in chronological order.
    """
    moment = datetime.now(timezone.utc) if now is None else now
    value = condition.value if isinstance(condition, Condition) else condition
    tail = secrets.token_hex(2) if suffix is None else suffix

    return f"{moment.strftime('%Y%m%d-%H%M%S')}-{value}-{workflow_id}-{tail}"


# --- the model client seam ---------------------------------------------------


class ModelClient(Protocol):
    """The only surface the experiment code sees of any provider.

    Keeping this a protocol means no provider SDK is imported by the logging
    or agent code, and every test runs against a mock rather than the network.
    """

    def complete(self, prompt: str, **params: Any) -> tuple[str, int, int, str]:
        """Return (text, input_tokens, output_tokens, resolved_model)."""
        ...


class MockClient:
    """A ModelClient that returns canned values and makes no network call.

    resolved_model is configurable so that the mismatch path — a provider
    resolving an alias to a different snapshot mid-experiment — is testable
    without waiting for it to happen for real.
    """

    def __init__(
        self,
        text: str = "canned completion",
        input_tokens: int = 11,
        output_tokens: int = 22,
        resolved_model: str = "mock-model-1",
    ) -> None:
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.resolved_model = resolved_model
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def complete(self, prompt: str, **params: Any) -> tuple[str, int, int, str]:
        self.calls.append((prompt, dict(params)))
        return self.text, self.input_tokens, self.output_tokens, self.resolved_model


# --- model resolution --------------------------------------------------------


class ModelResolution(NamedTuple):
    """What a requested model id turned out to be, and the exchange that showed it.

    prompt and completion are carried so the probe can be written to the call
    log like any other exchange, rather than being a resolution that appears in
    the manifest with nothing behind it.
    """

    resolved_model: str
    probe: ResolutionProbe
    prompt: str
    completion: str
    params: dict[str, Any]
    thinking_tokens: int | None = None


def resolve_model(
    client: ModelClient,
    requested_model: str,
    prompt: str = PROBE_PROMPT,
    **params: Any,
) -> ModelResolution:
    """Ask the provider what a requested model id resolves to.

    Some ids are dated snapshots and resolve to themselves; others are aliases
    that move as new snapshots ship. Where a provider exposes no dated form,
    this single minimal completion is the only way to learn which snapshot a
    run actually used, so the resolution is measured rather than assumed.

    Set-level semantics, for when experiments span several runs: the first run
    of a set fixes the resolution, and every later run in that set asserts
    identity against it rather than probing afresh. A set whose model changed
    partway through is not one experiment, and the assertion is what turns that
    into a loud failure instead of a silent confound. RunLogger enforces this
    within a run today; carrying it across a set is the caller's job until
    there is a set-level object to hold it.
    """
    text, input_tokens, output_tokens, resolved_model = client.complete(
        prompt, model=requested_model, **params
    )

    return ModelResolution(
        thinking_tokens=getattr(client, "last_thinking_tokens", None),
        resolved_model=resolved_model,
        probe=ResolutionProbe(
            timestamp_utc=utc_now_iso(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
        prompt=prompt,
        completion=text,
        params=dict(params),
    )


# --- the run logger ----------------------------------------------------------


class RunLogger:
    """Writes one run's manifest and call log.

    The manifest is written once, when the logger is constructed: a run that
    crashes after two of four calls still leaves a valid manifest and two valid
    call lines, which is the point of writing as we go.

    Every call line is flushed and fsynced before log_call returns, so a record
    that the caller believes was written is on disk even if the process dies in
    the next instruction.
    """

    def __init__(
        self,
        runs_root: Path,
        *,
        condition: Condition | str,
        workflow_id: str,
        requested_model: str,
        resolution: ModelResolution,
        model_created_at: str,
        git_commit: str,
        encoding_sha256: str,
        kb_sha256: str,
        config: dict[str, Any] | None = None,
        allow_dirty: bool = False,
        git_dirty: bool | None = None,
        run_id: str | None = None,
        created_utc: str | None = None,
    ) -> None:
        dirty = git_is_dirty() if git_dirty is None else git_dirty
        if dirty and not allow_dirty:
            raise RunIntegrityError(
                "the working tree has uncommitted changes, so this run would not "
                "be reproducible from its commit alone. Commit first, or pass "
                "allow_dirty=True to record it as a dirty-tree run."
            )

        self.expected_model = resolution.resolved_model
        self.condition = (
            condition if isinstance(condition, Condition) else Condition(condition)
        )
        self.run_id = (
            make_run_id(self.condition, workflow_id) if run_id is None else run_id
        )

        self.run_dir = Path(runs_root) / self.run_id
        if self.run_dir.exists():
            raise RunIntegrityError(
                f"run directory already exists: {self.run_dir}. Refusing to write "
                f"into a run that has already been recorded."
            )

        self.manifest_path = self.run_dir / MANIFEST_NAME
        self.calls_path = self.run_dir / CALLS_NAME

        self.manifest = RunManifest(
            run_id=self.run_id,
            created_utc=utc_now_iso() if created_utc is None else created_utc,
            condition=self.condition,
            workflow_id=workflow_id,
            requested_model=requested_model,
            resolved_model=resolution.resolved_model,
            resolution_probe=resolution.probe,
            model_created_at=model_created_at,
            git_commit=git_commit,
            git_dirty=dirty,
            encoding_sha256=encoding_sha256,
            kb_sha256=kb_sha256,
            config={} if config is None else config,
        )

        self.run_dir.mkdir(parents=True)
        self._write_once(
            self.manifest_path, self.manifest.model_dump_json(indent=2) + "\n"
        )

        # The probe is an exchange with the model like any other, so it is
        # logged like any other — and first, since it is what fixed the model
        # every later call is checked against.
        self.log_call(
            CallRecord(
                timestamp_utc=resolution.probe.timestamp_utc,
                run_id=self.run_id,
                condition=self.condition,
                agent_role=PROBE_AGENT_ROLE,
                workflow_id=workflow_id,
                requested_model=requested_model,
                resolved_model=resolution.resolved_model,
                sampling_params=resolution.params,
                seed=None,
                prompt_hash=sha256_text(resolution.prompt),
                input_tokens=resolution.probe.input_tokens,
                output_tokens=resolution.probe.output_tokens,
                thinking_tokens=resolution.thinking_tokens,
                raw_completion=resolution.completion,
            )
        )

    @staticmethod
    def _write_once(path: Path, text: str) -> None:
        """Write a file that must not already exist, and get it onto disk."""
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

    def log_call(self, record: CallRecord) -> None:
        """Append one call to calls.jsonl.

        The model check happens before anything is written. A run whose model
        changed underneath it is not one experimental unit, and a half-written
        log of it would be worse than none: the mismatch is raised and the line
        is not appended.
        """
        if record.resolved_model != self.expected_model:
            raise RunIntegrityError(
                f"{self.run_id}: provider resolved {record.resolved_model!r} but "
                f"this run is recorded against {self.expected_model!r}. Nothing "
                f"was written."
            )

        if record.run_id != self.run_id:
            raise RunIntegrityError(
                f"record belongs to run {record.run_id!r}, not {self.run_id!r}. "
                f"Nothing was written."
            )

        with self.calls_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def call_count(self) -> int:
        """How many calls have been logged, read back from disk."""
        if not self.calls_path.exists():
            return 0

        return sum(1 for line in self.calls_path.read_text().splitlines() if line.strip())


def network_is_reachable(
    host: str = CONNECTIVITY_HOST,
    port: int = CONNECTIVITY_PORT,
    timeout: float = 5.0,
) -> bool:
    """Cheap liveness check: can we open a socket to the API host?

    No request is made and no tokens are spent. A DNS failure — the fault that
    defeated the previous schedule — surfaces here as a refused resolution.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_connectivity(
    timeout: float = CONNECTIVITY_WAIT_SECONDS,
    poll: float = CONNECTIVITY_POLL_SECONDS,
    probe=network_is_reachable,
    sleep=time.sleep,
) -> bool:
    """Block until the network answers, or until timeout.

    Returns whether it came back. A False result is not fatal: the retry is
    attempted anyway, so a probe that is itself broken cannot stall a run.
    """
    waited = 0.0
    while True:
        if probe():
            return True
        if waited >= timeout:
            return False

        sleep(poll)
        waited += poll


def log_model_call(
    client: ModelClient,
    logger: "RunLogger",
    prompt: str,
    agent_role: str,
    workflow_id: str,
    sampling_params: dict[str, Any] | None = None,
    sleep=time.sleep,
    await_network=wait_for_connectivity,
    **call_params: Any,
) -> CallRecord:
    """Make one model call, record it, and refuse to return a truncated one.

    A stream that dies mid-flight is retried on the same prompt: six attempts
    in all, backing off 2s, 8s, 30s, 90s and 180s. From the second retry
    onward the network is confirmed live before the attempt is spent, so a
    sustained outage consumes waiting rather than attempts. Every attempt gets its own
    CallRecord: the failures with attempt_status 'stream_failed' and whatever
    partial text arrived, the success with 'ok'. Only the success is returned,
    so a failed attempt's text can never reach the deliberation.

    Shared by every agent so the guard cannot be present in one caller and
    missing in another. Returns the CallRecord that was written, which carries
    the completion and the token counts.

    The order matters: the record is written first, then the truncation check
    raises. A truncated call is a fact about the run and belongs in the log
    whether or not the run survives it.
    """
    from design_council.agents.anthropic_client import StreamInterrupted

    requested_model = logger.manifest.requested_model
    recorded_params = dict(sampling_params or {})
    recorded_params.update(call_params)

    def record_for(**fields: Any) -> CallRecord:
        return CallRecord(
            timestamp_utc=utc_now_iso(),
            run_id=logger.run_id,
            condition=logger.condition,
            agent_role=agent_role,
            workflow_id=workflow_id,
            requested_model=requested_model,
            sampling_params=recorded_params,
            seed=None,
            prompt_hash=sha256_text(prompt),
            **fields,
        )

    attempts = len(STREAM_RETRY_BACKOFF) + 1
    for attempt in range(attempts):
        try:
            text, input_tokens, output_tokens, resolved_model = client.complete(
                prompt, model=requested_model, **call_params
            )
            break
        except StreamInterrupted as error:
            # The attempt was billed, so it is logged: whatever text arrived,
            # whatever usage the provider had already reported. Its text never
            # reaches the caller.
            logger.log_call(
                record_for(
                    resolved_model=error.resolved_model or logger.expected_model,
                    input_tokens=error.input_tokens,
                    output_tokens=error.output_tokens,
                    thinking_tokens=None,
                    truncated=False,
                    attempt_status=AttemptStatus.STREAM_FAILED,
                    raw_completion=error.partial_text,
                )
            )

            if attempt == attempts - 1:
                raise StreamRetriesExhausted(
                    f"{agent_role}: {attempts} consecutive attempts died "
                    f"mid-stream. All are logged with attempt_status "
                    f"'stream_failed'. Last error: {error}"
                ) from error

            sleep(STREAM_RETRY_BACKOFF[attempt])

            # From the second retry onward, confirm the network is actually
            # there before spending another attempt on it.
            if attempt >= 1:
                await_network()

    truncated = getattr(client, "last_stop_reason", None) == "max_tokens"

    record = record_for(
        resolved_model=resolved_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thinking_tokens=getattr(client, "last_thinking_tokens", None),
        truncated=truncated,
        attempt_status=AttemptStatus.OK,
        raw_completion=text,
    )
    logger.log_call(record)

    if truncated:
        raise CallTruncatedError(
            f"{agent_role} stopped at max_tokens ({recorded_params.get('max_tokens', '?')}) "
            f"without finishing: {output_tokens} output tokens, of which "
            f"{record.thinking_tokens} reasoning, leaving "
            f"{len(text)} visible characters. The call is logged with "
            f"truncated=true; the run stops here rather than carrying a partial "
            f"contribution forward."
        )

    return record
