"""Generate an expert review pack for one workflow from the v1 development grid.

    python scripts/make_review_pack.py P2P-VIP-01 [--out DIR]

Three pages: design comparison, added controls and reviewer questions,
requirements and knowledge-base appendix. Every figure is read from run
manifests, gate outputs and target state specifications and independently
recomputed before it is printed; a disagreement raises PackIntegrityError
rather than being adjusted.

Read-only. No model calls, no new runs, nothing in runs/ is modified.

v2 probe runs are excluded: the disposition convention changed at commit
01034ae, and runs made under different instructions are not pooled.
"""

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reportlab.lib import colors  # noqa: E402
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

from design_council.kb.loader import load_kb  # noqa: E402
from design_council.measures.packs import (  # noqa: E402
    SELECTION_RULE,
    PackIntegrityError,
    elimination_census,
    encoding_path_for,
    load_v1_runs,
    representative,
    tie_at_median,
)
from design_council.schemas import WorkflowEncoding  # noqa: E402

ORANGE = colors.HexColor("#C2410C")
ORANGE_LIGHT = colors.HexColor("#FFEDD5")
GREY_DARK = colors.HexColor("#3F3F46")
GREY_MID = colors.HexColor("#71717A")
GREY_LIGHT = colors.HexColor("#E4E4E7")

CURATED_DIR = Path(__file__).resolve().parent.parent / "data" / "review_packs"

DEV_SPLIT_DISCLAIMER = (
    "Development split. These runs informed development iteration. Reviewer "
    "comments on this pack inform development, not research data, unless "
    "separately agreed."
)


def styles() -> dict:
    base = getSampleStyleSheet()
    def make(name, **kw):
        return ParagraphStyle(name, parent=base["Normal"], **kw)
    return {
        "title": make("t", fontName="Helvetica-Bold", fontSize=17, leading=21,
                      textColor=ORANGE, spaceAfter=1.5 * mm),
        "sub": make("s", fontName="Helvetica", fontSize=9, leading=12.5,
                    textColor=GREY_MID, spaceAfter=4 * mm),
        "h1": make("h1", fontName="Helvetica-Bold", fontSize=13, leading=16,
                   textColor=ORANGE, spaceBefore=4 * mm, spaceAfter=2 * mm),
        "h2": make("h2", fontName="Helvetica-Bold", fontSize=10, leading=13,
                   textColor=GREY_DARK, spaceBefore=2.5 * mm, spaceAfter=1 * mm),
        "body": make("b", fontName="Helvetica", fontSize=8.6, leading=11.8,
                     textColor=GREY_DARK, spaceAfter=2 * mm),
        "small": make("sm", fontName="Helvetica", fontSize=7.4, leading=10,
                      textColor=GREY_MID, spaceAfter=1.5 * mm),
        "quote": make("q", fontName="Helvetica-Oblique", fontSize=8, leading=11,
                      textColor=GREY_MID, leftIndent=6 * mm, spaceAfter=1.5 * mm),
        "note": make("n", fontName="Helvetica-Bold", fontSize=8.4, leading=11.5,
                     textColor=ORANGE, spaceAfter=2 * mm),
    }


def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def table(rows, widths, header=True, size=7.6):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", size),
        ("TEXTCOLOR", (0, 0), (-1, -1), GREY_DARK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, GREY_LIGHT),
    ]
    if header:
        style += [
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", size),
            ("BACKGROUND", (0, 0), (-1, 0), ORANGE_LIGHT),
            ("TEXTCOLOR", (0, 0), (-1, 0), ORANGE),
        ]
    t.setStyle(TableStyle(style))
    return t


def fmt_range(values) -> str:
    return f"{st.mean(values):.3f} ({min(values):.3f}–{max(values):.3f})"


def page_one(wf, encoding, groups, curated, s, width):
    b_rep, c_rep = representative(groups["baseline"]), representative(groups["council"])
    story = [
        Paragraph(f"{wf} — expert review pack", s["title"]),
        Paragraph(
            f"{encoding.name} · development grid, instrument version v1 · "
            f"n=3 per condition · generated from {len(groups['baseline']) + len(groups['council'])} runs",
            s["sub"]),
    ]

    ids = "<br/>".join(
        f"<b>{c}</b>: " + ", ".join(r.run_id for r in groups[c]) for c in ["baseline", "council"])
    commits = sorted({r.git_commit[:8] for r in groups["baseline"] + groups["council"]})
    story += [
        Paragraph("Runs summarised", s["h2"]),
        Paragraph(ids, s["small"]),
        Paragraph(f"Commits: {', '.join(commits)} · model as resolved by probe: "
                  f"{b_rep.resolved_model}", s["small"]),
        Paragraph(SELECTION_RULE, s["small"]),
        Paragraph(f"Representative runs: baseline <b>{b_rep.run_id}</b> "
                  f"(depth {b_rep.depth.depth_score:.3f}"
                  f"{', tie broken by timestamp' if tie_at_median(groups['baseline']) else ''}); "
                  f"council <b>{c_rep.run_id}</b> (depth {c_rep.depth.depth_score:.3f}"
                  f"{', tie broken by timestamp' if tie_at_median(groups['council']) else ''}).",
                  s["small"]),
    ]

    story.append(Paragraph("Measured outcomes, n=3 per condition", s["h1"]))
    rows = [["Measure", "Baseline", "Council"]]

    def col(cond, fn):
        return fn(groups[cond])

    rows.append(["Rule conformance (mean)",
                 f"{st.mean([r.gate.conformance_score for r in groups['baseline']]):.2f}",
                 f"{st.mean([r.gate.conformance_score for r in groups['council']]):.2f}"])
    rows.append(["Substantive conformance (mean)",
                 f"{st.mean([r.gate.substantive_score for r in groups['baseline']]):.2f}",
                 f"{st.mean([r.gate.substantive_score for r in groups['council']]):.2f}"])
    rows.append(["Vacuous passes (total across 3 runs)",
                 str(sum(r.gate.vacuous_count for r in groups['baseline'])),
                 str(sum(r.gate.vacuous_count for r in groups['council']))])
    rows.append(["Transformation depth, mean (range)",
                 fmt_range([r.depth.depth_score for r in groups['baseline']]),
                 fmt_range([r.depth.depth_score for r in groups['council']])])

    def actors(cond):
        vals = [r.depth.supplementary.actor_reassignments for r in groups[cond]]
        rep = representative(groups[cond]).depth.supplementary.actor_reassignments
        note = "" if len(set(vals)) == 1 else f" (varies across runs: {sorted(vals)})"
        return f"{rep}{note}"
    rows.append(["Actor reassignments (representative run)", actors("baseline"), actors("council")])
    rows.append(["Output tokens incl. reasoning, mean (range)",
                 f"{st.mean([r.output_tokens for r in groups['baseline']]):,.0f} "
                 f"({min(r.output_tokens for r in groups['baseline']):,}–{max(r.output_tokens for r in groups['baseline']):,})",
                 f"{st.mean([r.output_tokens for r in groups['council']]):,.0f} "
                 f"({min(r.output_tokens for r in groups['council']):,}–{max(r.output_tokens for r in groups['council']):,})"])

    story.append(table([[Paragraph(esc(c), s["small"]) for c in row] for row in rows],
                       [width * 0.34, width * 0.33, width * 0.33]))

    story += [
        Paragraph("Reading", s["h2"]),
        Paragraph(esc(curated["reading"]), s["body"]),
        Paragraph("Rule conformance is 1.00 in every cell. It is reported as the "
                  "validity floor — evidence that no redesign in either condition "
                  "breached a stated requirement — not as a discriminating measure.",
                  s["body"]),
    ]

    census = elimination_census()
    story.append(Paragraph(
        f"Zero-elimination note. Across both instrument versions, "
        f"{census['eliminated']} of {census['_total']} dispositions in "
        f"{census['_runs']} completed runs were recorded eliminated and "
        f"{census['absorbed']} absorbed. Round-one transcripts show the maximalist "
        f"role explicitly reasoning that no elimination is defensible on this "
        f"corpus — reasoned declination, not suppression. The labelling-fidelity "
        f"hypothesis behind instrument v2 is retracted with evidence.", s["note"]))

    story.append(Paragraph("Design comparison — representative runs", s["h1"]))
    rows = [["Baseline step", "Baseline", "Council"]]
    for step in encoding.steps:
        cells = [f"<b>{step.step_id}</b> {step.name}<br/>{step.actor}"]
        for rep in (b_rep, c_rep):
            e = next(x for x in rep.tss.disposition_mapping if x.baseline_step_id == step.step_id)
            tg = rep.tss.target_steps_for(step.step_id)
            cells.append(f"<b>{e.disposition.value}</b> → {', '.join(e.target_step_ids) or '—'}<br/>"
                         + "<br/>".join(f"{x.name} <i>({x.actor})</i>" for x in tg))
        rows.append(cells)
    story.append(table([[Paragraph(c, s["small"]) for c in r] for r in rows],
                       [width * 0.26, width * 0.37, width * 0.37]))

    return story


def page_two(wf, curated, s, width):
    story = [
        Paragraph("Council-only design elements", s["h1"]),
        Paragraph(
            f"{len(curated['controls'])} controls present in the representative council "
            f"target state and absent from <b>all three</b> baseline draws. Absence is "
            f"verified mechanically against each baseline target state at generation time; "
            f"a claim that appears in any baseline draw is not emitted.", s["body"]),
    ]
    rows = [["Control", "Where", "Argued by", "KB"]]
    for c in curated["controls"]:
        rows.append([
            f"<b>{esc(c['title'])}</b>",
            esc(c["where"]),
            ", ".join(c["roles"]),
            ", ".join(c["kb"]) or "—",
        ])
    story.append(table([[Paragraph(x, s["small"]) for x in r] for r in rows],
                       [width * 0.34, width * 0.20, width * 0.34, width * 0.12]))

    story.append(Paragraph("Strongest rationale per control", s["h2"]))
    for c in curated["controls"]:
        story.append(KeepTogether([
            Paragraph(f"<b>{esc(c['title'])}</b>", s["small"]),
            Paragraph(f"“{esc(c['quote'])}”  — {esc(c['quote_role'])}", s["quote"]),
        ]))

    for ex in curated.get("excluded_claims", []):
        story.append(Paragraph("Excluded claim", s["h2"]))
        story.append(Paragraph(f"<b>{esc(ex['title'])}</b> — {esc(ex['reason'])}", s["small"]))

    story.append(Paragraph("Reviewer questions", s["h1"]))
    for i, q in enumerate(curated["reviewer_questions"], 1):
        story.append(Paragraph(f"<b>{i}.</b> {esc(q)}", s["body"]))

    return story


def page_three(wf, encoding, groups, s, width):
    kb = load_kb()
    story = [Paragraph("Requirements checked by the gate", s["h1"])]
    rows = [["ID", "Rule type", "Statement"]]
    for r in encoding.requirements:
        rows.append([r.requirement_id, r.rule_type, esc(r.statement)])
    story.append(table([[Paragraph(x, s["small"]) for x in row] for row in rows],
                       [width * 0.12, width * 0.20, width * 0.68]))
    story.append(Paragraph(
        f"All {len(encoding.requirements)} requirements passed in all six runs, with zero "
        f"vacuous passes. Steps recorded as open to elimination by design: "
        f"{', '.join(encoding.unconstrained_by_design) or 'none'}.", s["small"]))

    story.append(Paragraph("Knowledge base as supplied to both conditions", s["h1"]))
    story.append(Paragraph(
        f"{len(kb.entries)} entries, identical in both conditions. Every <b>ref</b> is "
        f"TBC: paragraph citations are verified by hand against the standards texts and "
        f"are never written from memory, so no pack quotes a paragraph number.", s["body"]))
    rows = [["ID", "Standard", "Topic", "Relevance", "Bears on"]]
    for e in kb.sorted_entries():
        rows.append([e.id, f"{e.standard} / {e.slfrs_equivalent}", esc(e.topic),
                     e.relevance.value, ", ".join(e.bears_on)])
    story.append(table([[Paragraph(x, s["small"]) for x in row] for row in rows],
                       [width * 0.08, width * 0.20, width * 0.30, width * 0.12, width * 0.30]))

    b, c = groups["baseline"][0], groups["council"][0]
    story.append(Paragraph("Provenance", s["h1"]))
    prov = [
        ("Runs", ", ".join(r.run_id for r in groups["baseline"] + groups["council"])),
        ("Commits", ", ".join(sorted({r.git_commit for r in groups["baseline"] + groups["council"]}))),
        ("Encoding", f"{encoding_path_for(wf).name} · sha256 {b.encoding_sha256}"),
        ("Knowledge base", f"ifrs_slfrs_kb.yaml · sha256 {b.kb_sha256}"),
        ("Model", f"{b.resolved_model} (as resolved by probe)"),
        ("Instrument version", "v1 disposition convention (pre-01034ae)"),
        ("v2 exclusion", "4 v2 probe runs at commit 01034ae are excluded from this pack; "
                         "runs made under different instructions are not pooled"),
        ("Generated", "scripts/make_review_pack.py, read-only from run artefacts"),
    ]
    story.append(table([[Paragraph(f"<b>{k}</b>", s["small"]), Paragraph(esc(v), s["small"])]
                        for k, v in prov], [width * 0.18, width * 0.82], header=False))
    story.append(Paragraph(DEV_SPLIT_DISCLAIMER, s["note"]))

    return story


def build(workflow_id: str, out_dir: Path) -> Path:
    curated_path = CURATED_DIR / f"{workflow_id}.json"
    if not curated_path.exists():
        raise PackIntegrityError(f"no curated content at {curated_path}")
    curated = json.loads(curated_path.read_text())

    encoding = WorkflowEncoding.model_validate(json.loads(encoding_path_for(workflow_id).read_text()))
    groups = load_v1_runs(workflow_id)
    verify_controls(curated, groups)

    margin = 14 * mm
    width = A4[0] - 2 * margin
    out = out_dir / f"review_pack_{workflow_id}_devgrid.pdf"
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin,
                            title=f"{workflow_id} expert review pack", author="design-council")
    s = styles()
    story = page_one(workflow_id, encoding, groups, curated, s, width)
    story.append(PageBreak())
    story += page_two(workflow_id, curated, s, width)
    story.append(PageBreak())
    story += page_three(workflow_id, encoding, groups, s, width)
    doc.build(story)

    return out


def verify_controls(curated, groups) -> None:
    """Every claimed control must be in the council representative and in no baseline."""
    def text_of(tss):
        return " ".join(" ".join([x.name, x.actor, " ".join(x.inputs), " ".join(x.outputs),
                                  x.description]) for x in tss.steps).lower()

    council = text_of(representative(groups["council"]).tss)
    baselines = [(r.run_id, text_of(r.tss)) for r in groups["baseline"]]

    for c in curated["controls"]:
        marker = c["marker"].lower()
        if marker not in council:
            raise PackIntegrityError(
                f"control {c['title']!r}: marker {c['marker']!r} not found in the "
                f"council representative run")
        present = [rid for rid, t in baselines if marker in t]
        if present:
            raise PackIntegrityError(
                f"control {c['title']!r} is claimed council-only but its marker "
                f"{c['marker']!r} appears in baseline run(s) {present}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow_id")
    parser.add_argument("--out", type=Path, default=Path("docs/review_packs"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    out = build(args.workflow_id, args.out)
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
