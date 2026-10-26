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


def test_analysis_results_are_carried_over(exported):
    """Files written by the separate analysis scripts survive a re-export unchanged."""
    for rel in ("results/bootstrap_h2.json", "results/depth_verification.json",
                "results/controls_symmetric_length.json"):
        assert (exported / rel).read_bytes() == (REPO_ROOT / "export" / rel).read_bytes(), rel


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


def test_findings_and_limits_match_the_dissertation(exported):
    """The overview's findings and limits, as worded in the final dissertation, are built from the export."""
    index = load(exported, "index.json")
    assert index["research_question"].startswith(
        "Does structured multi-agent deliberation, implemented as a role-differentiated Design Council")
    f = {x["id"]: x for x in index["findings"]}
    assert list(f) == ["F1", "F2", "F3", "F4", "F5", "F6"]
    assert f["F1"]["status"] == "pre-registered"
    assert "on 7 of 7 workflows" in f["F1"]["text"] and "on 4 of 7" in f["F1"]["text"]
    assert "p = 0.008 (one-sided, exploratory)" in f["F1"]["text"]
    assert "0.257" in f["F2"]["text"] and "0.119" in f["F2"]["text"] and f["F2"]["status"] == "exploratory"
    assert "0 eliminations in the council and 0" in f["F3"]["text"] and "16 of 57 steps" in f["F3"]["text"]
    for s in ("restructured 170 vs 95", "absorbed 5 vs 17", "merged 55 vs 81", "0.789 vs 0.702"):
        assert s in f["F4"]["text"], s
    for s in ("ranges from about 2%", "to about 37%", "AI agents only: 18% transactional, 4% pooled", "Pooled: 20%"):
        assert s in f["F5"]["text"], s
    assert "compress" not in f["F4"]["title"]
    assert not any("—" in x.get("title", "") + x["text"] for x in index["findings"] + index["limits"])
    for s in ("78 council-attributed controls in 7 of 7 workflows (57 at 75%)",
              "from 277 distinct controls (307 candidates)", "Agentic Architect 28",
              "Emerging-Economy Constraint 21", "Maximalist 0"):
        assert s in f["F6"]["text"], s
    limits = " ".join(x["text"] for x in index["limits"])
    for s in ("10 of 68 runs fell below 1.0", "9 of them council", "8 of the 9 council failures",
              "4 of 14 cells", "about 19×", "$1.42 vs $0.07 per run", "One model family",
              "budget-matched, not compute-matched"):
        assert s in limits, s
