"""Run provenance: what was sent to a model, what came back, and under what settings.

This module will hold the run-logging contract required by CLAUDE.md — model,
pinned version, seed, token counts and raw output written to runs/ for every
LLM call. It starts with the piece that has to come first: getting the
credential into the process without it ever reaching a log.

load_env() is deliberately small and dependency-free. python-dotenv would do
the same job, but a hand-written reader is auditable at a glance, which matters
more here than the handful of conveniences it lacks.
"""

import os
from collections.abc import MutableMapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


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
