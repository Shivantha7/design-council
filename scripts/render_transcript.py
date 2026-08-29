"""Render a run's deliberation to an A4 PDF.

    python scripts/render_transcript.py <run_dir> [--pdf OUT] [--encoding PATH]

READ-ONLY with respect to experimental artefacts: it reads run_manifest.json,
calls.jsonl, tss.json and gate_result.json, and writes only the PDF it is asked
to produce. No API calls.

The deliberation is rendered from calls.jsonl rather than transcript.md,
because the call log is the richer and more faithful record: it holds every
call in the order it was made, including the synthesis and any repair attempt,
with the token figures attached. transcript.md carries the prose only.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from design_council.measures.depth import measure_depth  # noqa: E402
from design_council.schemas import (  # noqa: E402
    CallRecord,
    Disposition,
    GateResult,
    RunManifest,
    TargetStateSpec,
    WorkflowEncoding,
)

# House style: orange accent on a grey scale.
ORANGE = colors.HexColor("#C2410C")
ORANGE_LIGHT = colors.HexColor("#FFEDD5")
GREY_DARK = colors.HexColor("#3F3F46")
GREY_MID = colors.HexColor("#71717A")
GREY_LIGHT = colors.HexColor("#E4E4E7")

PROBE_ROLE = "model_resolution_probe"
SYNTHESIS_ROLES = {"synthesis", "synthesis_repair"}


def styles() -> dict:
    base = getSampleStyleSheet()

    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=20, leading=24, textColor=ORANGE, alignment=TA_LEFT,
            spaceAfter=2 * mm,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=13, textColor=GREY_MID, spaceAfter=6 * mm,
        ),
        "heading": ParagraphStyle(
            "heading", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, leading=16, textColor=GREY_DARK,
            spaceBefore=6 * mm, spaceAfter=1 * mm,
        ),
        "badge": ParagraphStyle(
            "badge", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8, leading=11, textColor=ORANGE, spaceAfter=0.5 * mm,
        ),
        "meta": ParagraphStyle(
            "meta", parent=base["Normal"], fontName="Helvetica",
            fontSize=8, leading=11, textColor=GREY_MID, spaceAfter=2.5 * mm,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.5, leading=13.5, textColor=GREY_DARK, spaceAfter=2.5 * mm,
        ),
        "section": ParagraphStyle(
            "section", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=15, leading=19, textColor=ORANGE, spaceAfter=4 * mm,
        ),
    }


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def round_badge(agent_role: str) -> str:
    if agent_role == PROBE_ROLE:
        return "PROBE"
    if agent_role.startswith("round1_"):
        return "ROUND 1 · INDEPENDENT POSITION"
    if agent_role.startswith("round2_"):
        return "ROUND 2 · CRITIQUE"
    if agent_role == "synthesis":
        return "SYNTHESIS"
    if agent_role == "synthesis_repair":
        return "SYNTHESIS · REPAIR ATTEMPT"
    if agent_role.endswith("_repair"):
        return "REPAIR ATTEMPT"

    return "SINGLE-AGENT BASELINE"


def load_run(run_dir: Path) -> tuple[RunManifest, list[CallRecord], TargetStateSpec | None, GateResult | None]:
    manifest = RunManifest.model_validate_json((run_dir / "run_manifest.json").read_text())
    records = [
        CallRecord.model_validate_json(line)
        for line in (run_dir / "calls.jsonl").read_text().splitlines()
        if line.strip()
    ]

    tss_path, gate_path = run_dir / "tss.json", run_dir / "gate_result.json"
    tss = TargetStateSpec.model_validate_json(tss_path.read_text()) if tss_path.exists() else None
    gate = GateResult.model_validate_json(gate_path.read_text()) if gate_path.exists() else None

    return manifest, records, tss, gate


def key_value_table(rows: list[tuple[str, str]], width: float) -> Table:
    table = Table([[k, v] for k, v in rows], colWidths=[38 * mm, width - 38 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8.5),
                ("FONT", (1, 0), (1, -1), "Helvetica", 8.5),
                ("TEXTCOLOR", (0, 0), (0, -1), GREY_MID),
                ("TEXTCOLOR", (1, 0), (1, -1), GREY_DARK),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, GREY_LIGHT),
            ]
        )
    )

    return table


def build_story(
    manifest: RunManifest,
    records: list[CallRecord],
    tss: TargetStateSpec | None,
    gate: GateResult | None,
    encoding: WorkflowEncoding | None,
    width: float,
) -> list:
    style = styles()
    story = [
        Paragraph(f"{manifest.workflow_id} — {manifest.condition.value} run", style["title"]),
        Paragraph(
            f"Deliberation transcript · {len(records)} calls · rendered from calls.jsonl",
            style["subtitle"],
        ),
        key_value_table(
            [
                ("run_id", manifest.run_id),
                ("condition", manifest.condition.value),
                ("model", f"{manifest.requested_model} → {manifest.resolved_model}"),
                ("commit", manifest.git_commit + ("  (dirty tree)" if manifest.git_dirty else "")),
                ("created", manifest.created_utc),
            ],
            width,
        ),
        Spacer(1, 6 * mm),
    ]

    ordered = [r for r in records if r.agent_role not in SYNTHESIS_ROLES]
    ordered += [r for r in records if r.agent_role in SYNTHESIS_ROLES]

    for record in ordered:
        thinking = "—" if record.thinking_tokens is None else str(record.thinking_tokens)
        meta = (
            f"{record.input_tokens:,} in · {record.output_tokens:,} out · "
            f"{thinking} reasoning · {len(record.raw_completion):,} characters"
        )
        if record.truncated:
            meta += " · TRUNCATED"

        header = [
            Paragraph(round_badge(record.agent_role), style["badge"]),
            Paragraph(escape(record.agent_role), style["heading"]),
            Paragraph(meta, style["meta"]),
        ]
        story.append(KeepTogether(header))

        text = record.raw_completion.strip() or "(no visible content)"
        for block in [b for b in text.split("\n\n") if b.strip()]:
            story.append(Paragraph(escape(block).replace("\n", "<br/>"), style["body"]))

    if gate is None or tss is None or encoding is None:
        story.append(PageBreak())
        story.append(Paragraph("Summary", style["section"]))
        story.append(
            Paragraph(
                "This run did not complete: no target-state specification or gate "
                "result was written, so no summary can be computed.",
                style["body"],
            )
        )
        return story

    story.append(PageBreak())
    story.append(Paragraph("Summary", style["section"]))

    substantive = gate.substantive_score
    substantive_text = "undefined" if substantive is None else f"{substantive:.4f}"
    passed = sum(1 for r in gate.results if r.passed)

    story.append(Paragraph("Gate result", style["heading"]))
    story.append(
        key_value_table(
            [
                ("conformance", f"{gate.conformance_score:.4f}   ({passed}/{len(gate.results)} requirements)"),
                ("vacuous", f"{gate.vacuous_count}"),
                ("substantive", substantive_text),
            ],
            width,
        )
    )
    story.append(Spacer(1, 5 * mm))

    report = measure_depth(encoding, tss)
    profile = report.profile

    story.append(Paragraph("Disposition profile", style["heading"]))
    rows = [["Disposition", "Count", "Proportion"]]
    rows += [
        [d.value, str(profile.count(d)), f"{profile.proportions[d.value]:.2f}"]
        for d in Disposition
    ]
    table = Table(rows, colWidths=[width - 60 * mm, 30 * mm, 30 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), ORANGE_LIGHT),
                ("TEXTCOLOR", (0, 0), (-1, 0), ORANGE),
                ("TEXTCOLOR", (0, 1), (-1, -1), GREY_DARK),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, GREY_LIGHT),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph("Transformation depth", style["heading"]))
    story.append(
        key_value_table(
            [
                ("depth_score", f"{report.depth_score:.4f}"),
                ("definition", "proportion of baseline steps not retained (pre-registered)"),
                ("baseline steps", str(profile.total_baseline_steps)),
            ],
            width,
        )
    )

    return story


def render(run_dir: Path, out_path: Path, encoding_path: Path | None = None) -> Path:
    manifest, records, tss, gate = load_run(run_dir)

    if encoding_path is None:
        recorded = manifest.config.get("encoding_path")
        encoding_path = Path(recorded) if recorded else None

    encoding = None
    if encoding_path is not None and Path(encoding_path).exists():
        with Path(encoding_path).open() as handle:
            encoding = WorkflowEncoding.model_validate(json.load(handle))

    margin = 18 * mm
    document = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=f"{manifest.workflow_id} {manifest.condition.value} transcript",
        author="design-council",
    )
    width = A4[0] - 2 * margin
    document.build(build_story(manifest, records, tss, gate, encoding, width))

    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--pdf", type=Path, default=None, help="output path")
    parser.add_argument("--encoding", type=Path, default=None)
    args = parser.parse_args(argv)

    out = args.pdf or args.run_dir / "transcript.pdf"
    render(args.run_dir, out, args.encoding)
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
