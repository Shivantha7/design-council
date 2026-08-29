"""Compare a run's Target-State Specification against the encoding it came from.

    python scripts/compare_tss.py <encoding.json> <run_dir> [--markdown]

READ-ONLY. This is an inspection instrument, not part of the experiment. It
reads the encoding and the run's tss.json and gate_result.json and prints what
the redesign did; it never modifies an experimental artefact. With --markdown it
additionally writes comparison.md into the run directory — a derived,
regenerable file that sits beside the JSON so a run's human-readable record
travels with it. Nothing else in the run directory is touched.

Reading a run's output and then editing prompts to improve the next one is how
a held-out set stops being held out. This tool exists to let a redesign be read,
not tuned against.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.smoke_gate import gate_report_lines  # noqa: E402

from design_council.schemas import (  # noqa: E402
    GateResult,
    TargetStateSpec,
    WorkflowEncoding,
)
from design_council.schemas.tss import check_against_encoding  # noqa: E402

TSS_FILENAME = "tss.json"
GATE_RESULT_FILENAME = "gate_result.json"
COMPARISON_FILENAME = "comparison.md"

ELIMINATED_MARK = "— ELIMINATED —"
NET_NEW_MARK = "NET-NEW"


def load_run(run_dir: Path) -> tuple[TargetStateSpec, GateResult]:
    """Read the two artefacts this tool compares. Neither is written back."""
    tss_path = run_dir / TSS_FILENAME
    gate_path = run_dir / GATE_RESULT_FILENAME

    for path in (tss_path, gate_path):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; is {run_dir} a completed run?")

    return (
        TargetStateSpec.model_validate_json(tss_path.read_text()),
        GateResult.model_validate_json(gate_path.read_text()),
    )


def reverse_mapping(tss: TargetStateSpec) -> dict[str, list[str]]:
    """target_step_id -> the baseline steps that trace into it.

    Built from the disposition mapping only, never from prose, so a target step
    with no entry here is genuinely unaccounted for rather than merely
    undescribed.
    """
    reverse: dict[str, list[str]] = {step.step_id: [] for step in tss.steps}
    for entry in tss.disposition_mapping:
        for target_id in entry.target_step_ids:
            reverse.setdefault(target_id, []).append(entry.baseline_step_id)

    return reverse


def disposition_rows(
    encoding: WorkflowEncoding, tss: TargetStateSpec
) -> list[dict[str, str]]:
    """One row per baseline step, in baseline order."""
    target_by_id = {step.step_id: step for step in tss.steps}
    rows = []

    for step in encoding.steps:
        entry = next(
            e for e in tss.disposition_mapping if e.baseline_step_id == step.step_id
        )
        targets = [target_by_id[i] for i in entry.target_step_ids if i in target_by_id]

        rows.append(
            {
                "step_id": step.step_id,
                "baseline": f"{step.name} ({step.actor})",
                "disposition": entry.disposition.value,
                "target_ids": ", ".join(entry.target_step_ids) or ELIMINATED_MARK,
                "target": "; ".join(f"{t.name} ({t.actor})" for t in targets)
                or ELIMINATED_MARK,
            }
        )

    return rows


def render_table(rows: list[dict[str, str]], headers: list[tuple[str, str]]) -> list[str]:
    """A plain fixed-width table, sized to its contents so nothing is truncated."""
    widths = {
        key: max(len(title), *(len(row[key]) for row in rows)) if rows else len(title)
        for key, title in headers
    }

    lines = ["  ".join(title.ljust(widths[key]) for key, title in headers)]
    lines.append("  ".join("-" * widths[key] for key, _ in headers))
    for row in rows:
        lines.append("  ".join(row[key].ljust(widths[key]) for key, _ in headers))

    return lines


def render_text(
    encoding: WorkflowEncoding,
    tss: TargetStateSpec,
    gate_result: GateResult,
    run_dir: Path,
) -> list[str]:
    rows = disposition_rows(encoding, tss)
    reverse = reverse_mapping(tss)

    lines = [
        f"encoding   : {encoding.workflow_id} — {encoding.name}",
        f"run        : {run_dir}",
        f"steps      : {len(encoding.steps)} baseline -> {len(tss.steps)} target",
        "",
        "=" * 78,
        "1. DISPOSITION OF EVERY BASELINE STEP",
        "=" * 78,
        "",
    ]
    lines += render_table(
        rows,
        [
            ("step_id", "STEP"),
            ("baseline", "BASELINE (ACTOR)"),
            ("disposition", "DISPOSITION"),
            ("target_ids", "TARGET IDS"),
            ("target", "TARGET (ACTOR)"),
        ],
    )

    eliminated = [r["step_id"] for r in rows if r["disposition"] == "eliminated"]
    lines += [
        "",
        f"eliminated : {', '.join(eliminated) if eliminated else 'none'}",
        "",
        "=" * 78,
        "2. TARGET-STATE NARRATIVE",
        "=" * 78,
    ]

    for step in tss.steps:
        sources = reverse.get(step.step_id, [])
        origin = ", ".join(sources) if sources else NET_NEW_MARK
        lines += [
            "",
            f"[{step.step_id}] {step.name}",
            f"  actor      : {step.actor}",
            f"  traces from: {origin}",
            f"  inputs     : {', '.join(step.inputs) or '(none)'}",
            f"  outputs    : {', '.join(step.outputs) or '(none)'}",
            f"  description: {step.description}",
        ]

    net_new = [s.step_id for s in tss.steps if not reverse.get(s.step_id)]
    lines += [
        "",
        f"net-new steps (no baseline step traces into them): "
        f"{', '.join(net_new) if net_new else 'none'}",
        "",
        "=" * 78,
        "3. GATE RESULT",
        "=" * 78,
    ]
    lines += gate_report_lines(gate_result)

    return lines


def render_markdown(
    encoding: WorkflowEncoding,
    tss: TargetStateSpec,
    gate_result: GateResult,
    run_dir: Path,
) -> str:
    rows = disposition_rows(encoding, tss)
    reverse = reverse_mapping(tss)

    lines = [
        f"# {encoding.workflow_id} — target-state comparison",
        "",
        f"- **Encoding**: {encoding.workflow_id} — {encoding.name}",
        f"- **Run**: `{run_dir.name}`",
        f"- **Steps**: {len(encoding.steps)} baseline → {len(tss.steps)} target",
        "",
        "> Generated by `scripts/compare_tss.py`. Derived from `tss.json` and "
        "`gate_result.json`; regenerate rather than edit.",
        "",
        "## 1. Disposition of every baseline step",
        "",
        "| Step | Baseline (actor) | Disposition | Target ids | Target (actor) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        disposition = row["disposition"]
        if disposition == "eliminated":
            disposition = f"**{disposition}**"
        lines.append(
            f"| `{row['step_id']}` | {row['baseline']} | {disposition} | "
            f"{row['target_ids']} | {row['target']} |"
        )

    lines += ["", "## 2. Target-state narrative", ""]
    for step in tss.steps:
        sources = reverse.get(step.step_id, [])
        origin = ", ".join(f"`{s}`" for s in sources) if sources else f"**{NET_NEW_MARK}**"
        lines += [
            f"### `{step.step_id}` {step.name}",
            "",
            f"- **Actor**: {step.actor}",
            f"- **Traces from**: {origin}",
            f"- **Inputs**: {', '.join(step.inputs) or '(none)'}",
            f"- **Outputs**: {', '.join(step.outputs) or '(none)'}",
            "",
            step.description,
            "",
        ]

    lines += ["## 3. Gate result", "", "```"]
    lines += [line for line in gate_report_lines(gate_result)]
    lines += ["```", ""]

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("encoding", type=Path)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--markdown",
        action="store_true",
        help=f"also write {COMPARISON_FILENAME} into the run directory",
    )
    args = parser.parse_args(argv)

    with args.encoding.open() as handle:
        encoding = WorkflowEncoding.model_validate(json.load(handle))

    tss, gate_result = load_run(args.run_dir)
    check_against_encoding(tss, encoding)  # the run must belong to this encoding

    for line in render_text(encoding, tss, gate_result, args.run_dir):
        print(line)

    if args.markdown:
        path = args.run_dir / COMPARISON_FILENAME
        path.write_text(render_markdown(encoding, tss, gate_result, args.run_dir))
        print()
        print(f"wrote {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
