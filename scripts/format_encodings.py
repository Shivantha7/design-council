"""Rewrite every JSON file under data/ in canonical form.

Usage:
    python scripts/format_encodings.py [--check]

Canonical form is json.dumps(indent=2, ensure_ascii=False, sort_keys=False)
plus a trailing newline. Key order is preserved as authored, because the order
of steps and requirements in an encoding carries meaning.

Files under data/encodings/heldout/ are frozen after the pre-registration tag
and are never written to. If one is not in canonical form it is reported and
the script exits non-zero, so it is caught before the freeze rather than
silently rewritten after it.
"""

import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HELDOUT_DIR = DATA_DIR / "encodings" / "heldout"


def canonical_text(data) -> str:
    """The one definition of canonical form, used by the formatter and the test."""
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def json_paths() -> list[Path]:
    return sorted(DATA_DIR.rglob("*.json"))


def is_frozen(path: Path) -> bool:
    return HELDOUT_DIR in path.parents


def main(argv: list[str]) -> int:
    check_only = "--check" in argv[1:]

    changed = []
    frozen_violations = []

    for path in json_paths():
        current = path.read_text()
        wanted = canonical_text(json.loads(current))
        if current == wanted:
            continue

        relative = path.relative_to(DATA_DIR.parent)
        if is_frozen(path):
            frozen_violations.append(relative)
            continue

        changed.append(relative)
        if not check_only:
            path.write_text(wanted)

    for relative in changed:
        print(f"{'would format' if check_only else 'formatted'}: {relative}")

    for relative in frozen_violations:
        print(
            f"NOT canonical and NOT rewritten (frozen heldout file): {relative}",
            file=sys.stderr,
        )

    total = len(json_paths())
    print(f"\n{total} JSON file(s) under data/; {len(changed)} {'to change' if check_only else 'rewritten'}")

    if frozen_violations:
        return 1
    if check_only and changed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
