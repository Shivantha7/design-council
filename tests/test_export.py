"""The app export reproduces the committed results documents, deterministically.

Needs runs/ (gitignored). On a clone without the run archive, the tests skip.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "runs" / "_set-heldout-v1.ledger.jsonl"
DOCS = REPO_ROOT / "docs"

pytestmark = pytest.mark.skipif(not LEDGER.exists(), reason="runs/ archive not present")


def export(out: Path) -> Path:
    subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "export_app_data.py"), "--out", str(out)],
                   check=True, capture_output=True)
    return out


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    return export(tmp_path_factory.mktemp("export"))


def load(base: Path, rel: str):
    return json.loads((base / rel).read_text())


def test_export_is_deterministic(exported, tmp_path):
    again = export(tmp_path / "again")
    first = sorted(p.relative_to(exported) for p in exported.rglob("*") if p.is_file())
    second = sorted(p.relative_to(again) for p in again.rglob("*") if p.is_file())
    assert first == second
    for rel in first:
        assert (exported / rel).read_bytes() == (again / rel).read_bytes(), rel


def test_run_counts(exported):
    index = load(exported, "index.json")
    assert len(index["sets"]["heldout-v1"]["runs"]) == 68
    assert len(index["sets"]["dev-v1"]["runs"]) == 18
    assert len(list((exported / "runs").glob("*.json"))) == 86
    assert sum(len(c["run_ids"]) for c in index["sets"]["heldout-v1"]["cells"]) == 68


def test_heldout_tables_match_document(exported):
    doc = (DOCS / "RESULTS_HELDOUT_tables.md").read_text()
    t = load(exported, "results/heldout_tables.json")
    fi = t["fill_ins"]
    assert f"| Workflows meeting SESOI | | | | {fi['h2_workflows_meeting_sesoi']} of 7 |" in doc
    assert fi["h2_workflows_meeting_sesoi"] == 4 and fi["h2_supported"]
    assert f"Stabilised cells: {fi['h3_stabilised_cells']} of 14" in doc
    assert f"Runs below 1.0: {fi['runs_below_1']} ({fi['runs_below_1_council']} council, " \
           f"{fi['runs_below_1_baseline']} baseline)" in doc
    c = fi["consistency_by_condition"]
    assert f"{c['council']:.3f} vs {c['baseline']:.3f}" in doc
    for row in t["x3_depth"]:
        line = (f"| {row['workflow_id']} | {row['council_mean']:.3f} ({row['council_min']:.3f}–{row['council_max']:.3f}) | "
                f"{row['baseline_mean']:.3f} ({row['baseline_min']:.3f}–{row['baseline_max']:.3f}) | {row['gap']:+.3f} | "
                f"{'Yes' if row['meets_sesoi'] else 'No'} |")
        assert line in doc, line
    for d, n in t["x4_dispositions"]["council"].items():
        assert f"| {d.capitalize()} | {n} | {t['x4_dispositions']['baseline'][d]} |" in doc


def test_controls_match_final_coding(exported):
    doc = (DOCS / "CONTROL_CODING_FINAL.md").read_text()
    g = load(exported, "results/governance_controls.json")
    passing = [c for c in g["controls"] if c["outcome"] == "PASS"]
    assert len(passing) == 78
    assert f"| **Total** | | {len(g['controls'])} | {len(passing)} |" in doc
    for row in g["per_workflow"]:
        assert re.search(rf"^\| {row['workflow_id']} \| \d \| {row['final_controls']} \| {row['pass']} \| {row['strict_75']} \|$",
                         doc, re.M), row
    for r in g["by_role"]:
        assert f"| {r['role']} | {r['primary']} | {r['any']} |" in doc, r


def test_productivity_and_efficiency_match_documents(exported):
    prod = (DOCS / "RESULTS_PRODUCTIVITY.md").read_text()
    p = load(exported, "results/productivity.json")
    for v in ("primary", "agentic-only"):
        pooled = p["variants"][v]["pooled"]["all"]
        assert f"| all | 7 | {pooled['pi']:.3f} | {pooled['p05']:.3f} – {pooled['p95']:.3f} |" in prod
    eff = (DOCS / "RESULTS_HELDOUT_efficiency.md").read_text()
    e = load(exported, "results/efficiency.json")
    assert f"| council | 33 | {e['totals']['council']['input_tokens']:,} |" in eff
    assert f"{e['totals']['council']['cost_usd']:,.2f}" in eff
