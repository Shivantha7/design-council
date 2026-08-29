"""Tests for the read-only comparison tool, against mock-run fixtures."""

import json
import shutil
from pathlib import Path

import pytest

from design_council.agents.baseline import run_baseline
from design_council.kb.loader import load_kb
from design_council.schemas import WorkflowEncoding
from scripts.compare_tss import (
    COMPARISON_FILENAME,
    ELIMINATED_MARK,
    NET_NEW_MARK,
    disposition_rows,
    load_run,
    main,
    render_markdown,
    render_text,
    reverse_mapping,
)
from tests.test_baseline import ScriptedClient, make_logger, valid_tss_json

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODING_PATH = (
    REPO_ROOT / "data" / "encodings" / "dev" / "p2p_vendor_invoice_processing.json"
)


def encoding() -> WorkflowEncoding:
    with ENCODING_PATH.open() as handle:
        return WorkflowEncoding.model_validate(json.load(handle))


def redesigned_tss_json(source: WorkflowEncoding) -> str:
    """A mock run whose redesign eliminates nothing, merges two steps, and
    invents one step no baseline step traces into."""
    return json.dumps(
        {
            "workflow_id": source.workflow_id,
            "baseline_step_ids": source.step_ids(),
            "steps": [
                {
                    "step_id": "TGT-01",
                    "name": "Capture and extract",
                    "description": "Intake and extraction in one automated pass.",
                    "actor": "AP automation platform",
                    "inputs": ["Vendor invoice (email PDF, EDI, supplier portal or paper)"],
                    "outputs": ["Structured validated invoice record"],
                },
                {
                    "step_id": "TGT-02",
                    "name": "Three-way match",
                    "description": "Automated match with tolerance.",
                    "actor": "AP automation platform",
                    "inputs": [
                        "Structured validated invoice record",
                        "Purchase order data",
                        "Goods receipt note data",
                    ],
                    "outputs": ["Match result (clean, tolerance or exception)"],
                },
                {
                    "step_id": "TGT-03",
                    "name": "Exception resolution",
                    "description": "Analyst resolves exceptions.",
                    "actor": "AP analyst",
                    "inputs": ["Match result (clean, tolerance or exception)"],
                    "outputs": ["Resolved invoice (approved, rejected or held)"],
                },
                {
                    "step_id": "TGT-04",
                    "name": "Approval",
                    "description": "Risk-based approval.",
                    "actor": "Approver hierarchy",
                    "inputs": ["Matched invoice"],
                    "outputs": ["Fully approved invoice"],
                },
                {
                    "step_id": "TGT-05",
                    "name": "GL posting",
                    "description": "Coding and posting.",
                    "actor": "AP accountant",
                    "inputs": ["Fully approved invoice"],
                    "outputs": ["GL journal entry posted"],
                },
                {
                    "step_id": "TGT-06",
                    "name": "Payment run",
                    "description": "Scheduling and execution.",
                    "actor": "Treasury/AP payments officer",
                    "inputs": ["Approved posted invoice"],
                    "outputs": ["Payment transmitted"],
                },
                {
                    "step_id": "TGT-07",
                    "name": "Reconciliation",
                    "description": "Continuous reconciliation.",
                    "actor": "AP accountant",
                    "inputs": ["Bank confirmations"],
                    "outputs": ["Reconciled AP ledger"],
                },
                {
                    "step_id": "TGT-08",
                    "name": "Continuous controls monitoring",
                    "description": "A dashboard nobody's baseline step became.",
                    "actor": "Controls team",
                    "inputs": ["Posted payable"],
                    "outputs": ["Control exceptions raised"],
                },
            ],
            "disposition_mapping": [
                {"baseline_step_id": "VIP-01", "disposition": "merged",
                 "rationale": "Merged into capture.", "target_step_ids": ["TGT-01"]},
                {"baseline_step_id": "VIP-02", "disposition": "merged",
                 "rationale": "Merged into capture.", "target_step_ids": ["TGT-01"]},
                {"baseline_step_id": "VIP-03", "disposition": "restructured",
                 "rationale": "Automated.", "target_step_ids": ["TGT-02"]},
                {"baseline_step_id": "VIP-04", "disposition": "retained",
                 "rationale": "Unchanged.", "target_step_ids": ["TGT-03"]},
                {"baseline_step_id": "VIP-05", "disposition": "retained",
                 "rationale": "Unchanged.", "target_step_ids": ["TGT-04"]},
                {"baseline_step_id": "VIP-06", "disposition": "retained",
                 "rationale": "Unchanged.", "target_step_ids": ["TGT-05"]},
                {"baseline_step_id": "VIP-07", "disposition": "retained",
                 "rationale": "Unchanged.", "target_step_ids": ["TGT-06"]},
                {"baseline_step_id": "VIP-08", "disposition": "retained",
                 "rationale": "Unchanged.", "target_step_ids": ["TGT-07"]},
            ],
        }
    )


def mock_run(tmp_path, tss_json: str) -> Path:
    """Produce a real run directory using the mocked baseline pipeline."""
    source = encoding()
    client = ScriptedClient([tss_json])
    logger = make_logger(tmp_path, client)
    run_baseline(source, load_kb(), client, logger)
    return logger.run_dir


# --- loading -----------------------------------------------------------------


def test_load_run_reads_both_artefacts(tmp_path):
    run_dir = mock_run(tmp_path, valid_tss_json(encoding()))

    tss, gate_result = load_run(run_dir)

    assert tss.workflow_id == "P2P-VIP-01"
    assert len(gate_result.results) == 8


def test_load_run_reports_an_incomplete_run(tmp_path):
    run_dir = mock_run(tmp_path, valid_tss_json(encoding()))
    (run_dir / "tss.json").unlink()

    with pytest.raises(FileNotFoundError, match="completed run"):
        load_run(run_dir)


# --- section 1: dispositions -------------------------------------------------


def test_disposition_rows_cover_every_baseline_step_in_order(tmp_path):
    source = encoding()
    run_dir = mock_run(tmp_path, redesigned_tss_json(source))
    tss, _ = load_run(run_dir)

    rows = disposition_rows(source, tss)

    assert [r["step_id"] for r in rows] == source.step_ids()
    assert rows[0]["disposition"] == "merged"
    assert rows[0]["target_ids"] == "TGT-01"
    assert "AP automation platform" in rows[0]["target"]


def test_eliminated_rows_are_marked(tmp_path):
    source = encoding()
    data = json.loads(redesigned_tss_json(source))
    for entry in data["disposition_mapping"]:
        if entry["baseline_step_id"] == "VIP-04":
            entry["disposition"] = "eliminated"
            entry["target_step_ids"] = []
    run_dir = mock_run(tmp_path, json.dumps(data))
    tss, _ = load_run(run_dir)

    rows = disposition_rows(source, tss)
    row = next(r for r in rows if r["step_id"] == "VIP-04")

    assert row["disposition"] == "eliminated"
    assert row["target_ids"] == ELIMINATED_MARK
    assert row["target"] == ELIMINATED_MARK


# --- section 2: reverse mapping ----------------------------------------------


def test_reverse_mapping_lists_the_baseline_steps_feeding_each_target(tmp_path):
    source = encoding()
    run_dir = mock_run(tmp_path, redesigned_tss_json(source))
    tss, _ = load_run(run_dir)

    reverse = reverse_mapping(tss)

    assert reverse["TGT-01"] == ["VIP-01", "VIP-02"]
    assert reverse["TGT-02"] == ["VIP-03"]


def test_net_new_target_steps_are_flagged(tmp_path):
    """A target step no baseline step traces into is work the redesign invented."""
    source = encoding()
    run_dir = mock_run(tmp_path, redesigned_tss_json(source))
    tss, _ = load_run(run_dir)

    reverse = reverse_mapping(tss)
    assert reverse["TGT-08"] == []

    text = "\n".join(render_text(source, tss, load_run(run_dir)[1], run_dir))
    assert NET_NEW_MARK in text
    assert "net-new steps (no baseline step traces into them): TGT-08" in text


# --- section 3 and output ----------------------------------------------------


def test_text_output_has_all_three_sections_and_the_gate_scores(tmp_path):
    source = encoding()
    run_dir = mock_run(tmp_path, redesigned_tss_json(source))
    tss, gate_result = load_run(run_dir)

    text = "\n".join(render_text(source, tss, gate_result, run_dir))

    assert "1. DISPOSITION OF EVERY BASELINE STEP" in text
    assert "2. TARGET-STATE NARRATIVE" in text
    assert "3. GATE RESULT" in text
    assert "conformance_score:" in text
    assert "vacuous_count:" in text
    assert "substantive_score:" in text
    for requirement in source.requirements:
        assert requirement.requirement_id in text


def test_markdown_writes_comparison_into_the_run_directory(tmp_path):
    source = encoding()
    run_dir = mock_run(tmp_path, redesigned_tss_json(source))
    before = sorted(p.name for p in run_dir.iterdir())

    exit_code = main([str(ENCODING_PATH), str(run_dir), "--markdown"])

    assert exit_code == 0
    after = sorted(p.name for p in run_dir.iterdir())
    assert set(after) - set(before) == {COMPARISON_FILENAME}

    markdown = (run_dir / COMPARISON_FILENAME).read_text()
    assert markdown.startswith("# P2P-VIP-01")
    assert "| Step | Baseline (actor) |" in markdown
    assert "## 2. Target-state narrative" in markdown
    assert "## 3. Gate result" in markdown


def test_the_tool_does_not_modify_the_experimental_artefacts(tmp_path):
    """READ-ONLY: tss.json, gate_result.json, the manifest and the call log must
    be byte-identical after running the tool, with or without --markdown."""
    source = encoding()
    run_dir = mock_run(tmp_path, redesigned_tss_json(source))

    watched = ["tss.json", "gate_result.json", "run_manifest.json", "calls.jsonl"]
    before = {name: (run_dir / name).read_bytes() for name in watched}

    main([str(ENCODING_PATH), str(run_dir)])
    main([str(ENCODING_PATH), str(run_dir), "--markdown"])

    after = {name: (run_dir / name).read_bytes() for name in watched}
    assert after == before


def test_a_run_from_another_encoding_is_refused(tmp_path):
    run_dir = mock_run(tmp_path, valid_tss_json(encoding()))
    other = REPO_ROOT / "data" / "encodings" / "dev" / "r2r_period_close_management.json"

    with pytest.raises(ValueError, match="does not match"):
        main([str(other), str(run_dir)])
