"""Tests for the transcript PDF renderer. Read-only, no API calls."""

import json
from pathlib import Path

import pytest

from scripts.render_transcript import load_run, main, render, round_badge

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODING_PATH = (
    REPO_ROOT / "data" / "encodings" / "dev" / "p2p_vendor_invoice_processing.json"
)
COUNCIL_RUN = REPO_ROOT / "runs" / "20260829-051950-council-P2P-VIP-01-13b0"

needs_council_run = pytest.mark.skipif(
    not (COUNCIL_RUN / "calls.jsonl").exists(),
    reason=f"completed council run not present at {COUNCIL_RUN} (runs/ is gitignored)",
)


def mock_council_run(tmp_path) -> Path:
    from design_council.agents.council import run_council
    from design_council.kb.loader import load_kb
    from design_council.schemas import WorkflowEncoding
    from tests.test_baseline import valid_tss_json
    from tests.test_council import CouncilMockClient, make_logger

    with ENCODING_PATH.open() as handle:
        source = WorkflowEncoding.model_validate(json.load(handle))
    client = CouncilMockClient(valid_tss_json(source))
    logger = make_logger(tmp_path, client)
    run_council(source, load_kb(), client, logger)

    return logger.run_dir


def pdf_page_count(path: Path) -> int:
    data = path.read_bytes()
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


# --- badges ------------------------------------------------------------------


@pytest.mark.parametrize(
    "role,expected",
    [
        ("model_resolution_probe", "PROBE"),
        ("round1_maximalist", "ROUND 1 · INDEPENDENT POSITION"),
        ("round2_pragmatist", "ROUND 2 · CRITIQUE"),
        ("synthesis", "SYNTHESIS"),
        ("synthesis_repair", "SYNTHESIS · REPAIR ATTEMPT"),
        ("baseline_designer", "SINGLE-AGENT BASELINE"),
    ],
)
def test_round_badges(role, expected):
    assert round_badge(role) == expected


# --- rendering a mocked run --------------------------------------------------


def test_renders_a_mocked_council_run(tmp_path):
    run_dir = mock_council_run(tmp_path)
    out = tmp_path / "transcript.pdf"

    render(run_dir, out, ENCODING_PATH)

    assert out.exists() and out.stat().st_size > 2000
    assert pdf_page_count(out) >= 2  # deliberation plus the summary page


def test_rendering_modifies_no_experimental_artefact(tmp_path):
    run_dir = mock_council_run(tmp_path)
    watched = ["tss.json", "gate_result.json", "run_manifest.json", "calls.jsonl"]
    before = {name: (run_dir / name).read_bytes() for name in watched}

    render(run_dir, tmp_path / "out.pdf", ENCODING_PATH)

    assert {name: (run_dir / name).read_bytes() for name in watched} == before


def test_synthesis_is_ordered_last(tmp_path):
    """Deliberation first, synthesis last, whatever order the log holds."""
    from design_council.schemas import CallRecord
    from scripts.render_transcript import SYNTHESIS_ROLES

    run_dir = mock_council_run(tmp_path)
    records = [
        CallRecord.model_validate_json(line)
        for line in (run_dir / "calls.jsonl").read_text().splitlines()
        if line.strip()
    ]
    ordered = [r for r in records if r.agent_role not in SYNTHESIS_ROLES]
    ordered += [r for r in records if r.agent_role in SYNTHESIS_ROLES]

    assert ordered[-1].agent_role == "synthesis"
    assert [r.agent_role for r in ordered[:-1]] == [
        r.agent_role for r in records if r.agent_role != "synthesis"
    ]


def test_an_incomplete_run_renders_without_a_summary(tmp_path):
    """A run that died before writing a TSS must still render its transcript."""
    run_dir = mock_council_run(tmp_path)
    (run_dir / "tss.json").unlink()
    (run_dir / "gate_result.json").unlink()

    out = tmp_path / "partial.pdf"
    render(run_dir, out, ENCODING_PATH)

    assert out.exists()
    manifest, records, tss, gate = load_run(run_dir)
    assert tss is None and gate is None


def test_encoding_path_is_read_from_the_manifest(tmp_path):
    """The manifest records which encoding the run used, so the renderer does
    not have to be told again."""
    run_dir = mock_council_run(tmp_path)
    manifest, _, _, _ = load_run(run_dir)
    manifest_data = json.loads((run_dir / "run_manifest.json").read_text())
    manifest_data["config"]["encoding_path"] = str(ENCODING_PATH)
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest_data, indent=2))

    out = tmp_path / "from_manifest.pdf"
    render(run_dir, out)  # no encoding argument

    assert pdf_page_count(out) >= 2


def test_cli_defaults_to_transcript_pdf_in_the_run_directory(tmp_path):
    run_dir = mock_council_run(tmp_path)

    assert main([str(run_dir), "--encoding", str(ENCODING_PATH)]) == 0
    assert (run_dir / "transcript.pdf").exists()


# --- the real completed run --------------------------------------------------


@needs_council_run
def test_renders_the_completed_council_run(tmp_path):
    out = tmp_path / "council.pdf"
    render(COUNCIL_RUN, out, ENCODING_PATH)

    assert out.stat().st_size > 50_000
    assert pdf_page_count(out) > 10  # fifteen calls of deliberation prose

    manifest, records, tss, gate = load_run(COUNCIL_RUN)
    assert len(records) == 16
    assert gate is not None and gate.conformance_score == 1.0
