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
import secrets
import subprocess
from collections.abc import MutableMapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from design_council.schemas.run_records import (
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
