"""Live service (phase 1) against mock clients only. No network.

Skipped where FastAPI is not installed (the research environment). Run with the service
environment:  .venv-service/bin/python -m pytest tests/test_service.py
"""

import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from design_council.run_logging import MockClient  # noqa: E402
from design_council.schemas import WorkflowEncoding  # noqa: E402
from service.app import create_app  # noqa: E402
from service.config import Settings  # noqa: E402
from service.mock import ServiceMockClient  # noqa: E402
from service.validation import validate_encoding  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ENCODING_PATH = REPO_ROOT / "data" / "encodings" / "dev" / "p2p_vendor_invoice_processing.json"
ROLES = ["maximalist", "pragmatist", "finance_domain", "emerging_economy", "hitl_designer",
         "agentic_architect", "accounting_standards"]


def encoding_json() -> dict:
    return json.loads(ENCODING_PATH.read_text())


def mock_factory(settings, encoding):
    return ServiceMockClient(encoding), "mock (no provider)"


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(runs_live_root=tmp_path / "runs_live", max_workers=1, mock=True, **overrides)
    return TestClient(create_app(settings, client_factory=mock_factory))


def wait_for(client, job_id, headers=None, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/runs/{job_id}", headers=headers).json()["job"]
        if job["status"] in ("succeeded", "failed", "interrupted"):
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def read_events(client, job_id, headers=None):
    text = client.get(f"/runs/{job_id}/events", headers=headers).text
    events = []
    for block in text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "data" in lines:
            events.append((int(lines["id"]), json.loads(lines["data"])))
    return events


# --- validation ------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted((REPO_ROOT / "data" / "encodings").rglob("*.json")), ids=lambda p: p.stem)
def test_every_research_encoding_passes_service_validation(path):
    report = validate_encoding(WorkflowEncoding.model_validate_json(path.read_text()))
    assert report.valid, report.errors


def test_validate_endpoint_reports_each_rule(tmp_path):
    client = make_client(tmp_path)
    assert client.post("/encodings/validate", json=encoding_json()).json()["valid"]

    enc = encoding_json()
    enc["requirements"] = [r for r in enc["requirements"] if r["requirement_id"] != "VIP-R-08"]  # VIP-07 unpaired
    codes = {e["code"] for e in client.post("/encodings/validate", json=enc).json()["errors"]}
    assert "unpaired_relational_step" in codes

    enc = encoding_json()
    for r in enc["requirements"]:
        if r["rule_type"] == "inputs_required":
            r["params"]["required_inputs"] = ["purchase order data"]  # case differs from the step input
    codes = {e["code"] for e in client.post("/encodings/validate", json=enc).json()["errors"]}
    assert "required_input_missing" in codes

    enc = encoding_json()
    del enc["steps"]
    report = client.post("/encodings/validate", json=enc).json()
    assert not report["valid"] and report["errors"][0]["code"] == "schema"


def test_invalid_encoding_cannot_start_a_run(tmp_path):
    client = make_client(tmp_path)
    enc = encoding_json()
    enc["requirements"] = []
    r = client.post("/runs", json={"encoding": enc, "conditions": ["baseline"], "confirm_cost": True})
    assert r.status_code == 422


# --- cost guard and access ---------------------------------------------------------


def test_run_requires_cost_confirmation(tmp_path):
    client = make_client(tmp_path)
    r = client.post("/runs", json={"encoding": encoding_json(), "conditions": ["council", "baseline"]})
    assert r.status_code == 409
    assert r.json()["estimate_usd"] == pytest.approx(1.49)
    assert client.get("/runs").json() == []


def test_daily_cap_blocks_new_runs(tmp_path):
    client = make_client(tmp_path, daily_cap_usd=1.0)
    r = client.post("/runs", json={"encoding": encoding_json(), "conditions": ["council"], "confirm_cost": True})
    assert r.status_code == 429
    assert "Daily cap" in r.json()["message"]


def test_password_is_required_when_set(tmp_path):
    client = make_client(tmp_path, password="s3cret")
    assert client.get("/runs").status_code == 401
    assert client.get("/runs", headers={"X-Live-Password": "s3cret"}).status_code == 200
    assert client.get("/runs?password=s3cret").status_code == 200


# --- full runs ----------------------------------------------------------------------


def test_both_conditions_run_end_to_end_with_progress_events(tmp_path):
    research_runs = sorted((REPO_ROOT / "runs").glob("*")) if (REPO_ROOT / "runs").exists() else []
    client = make_client(tmp_path)
    r = client.post("/runs", json={"encoding": encoding_json(), "conditions": ["council", "baseline"],
                                   "profile": "transactional", "confirm_cost": True})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    job = wait_for(client, job_id)
    assert job["status"] == "succeeded", job["error"]

    events = read_events(client, job_id)
    kinds = [e["event"] for _, e in events]
    assert kinds[:2] == ["job_queued", "job_started"] and kinds[-1] == "job_finished"
    assert [i for i, _ in events] == list(range(1, len(events) + 1))
    council_calls = [e for _, e in events if e["event"] == "call" and e["condition"] == "council"]
    assert [e["role"] for e in council_calls if e["phase"] == "round 1"] == ROLES
    assert [e["role"] for e in council_calls if e["phase"] == "round 2"] == ROLES
    assert [e["phase"] for e in council_calls][-1] == "synthesis"
    for condition in ("council", "baseline"):
        order = [e["event"] for _, e in events if e.get("condition") == condition and e["event"] != "call"]
        assert order == ["condition_started", "gate", "measures", "condition_finished"]

    result = client.get(f"/runs/{job_id}").json()
    assert "not part of the pre-registered study" in result["label"].lower()
    for condition in ("council", "baseline"):
        res = result["results"][condition]
        assert res["gate"]["conformance_score"] == 1.0  # the mock returns the identity redesign
        assert res["depth"]["depth_score"] == 0.0
        assert res["productivity"]["primary"]["computed"] and res["productivity"]["profile"] == "transactional"
        assert res["tokens"]["output"] > 0 and res["cost_usd"] > 0
        run_dir = Path(res["run_dir"])
        assert run_dir.parent == tmp_path / "runs_live"
        manifest = json.loads((run_dir / "run_manifest.json").read_text())
        assert "live service demonstration" in manifest["config"]["source"]
        assert (run_dir / "calls.jsonl").exists() and (run_dir / "gate_result.json").exists()
    assert len(result["results"]["council"]["transcript"]) == 15
    assert len(result["results"]["baseline"]["transcript"]) == 1

    history = client.get("/runs").json()
    assert history[0]["job_id"] == job_id and set(history[0]["run_ids"]) == {"council", "baseline"}
    after = sorted((REPO_ROOT / "runs").glob("*")) if (REPO_ROOT / "runs").exists() else []
    assert after == research_runs  # nothing written to runs/


def test_events_resume_after_last_event_id(tmp_path):
    client = make_client(tmp_path)
    job_id = client.post("/runs", json={"encoding": encoding_json(), "conditions": ["baseline"],
                                        "confirm_cost": True}).json()["job_id"]
    wait_for(client, job_id)
    full = read_events(client, job_id)
    resumed = client.get(f"/runs/{job_id}/events", headers={"Last-Event-ID": "3"}).text
    ids = [int(line[4:]) for line in resumed.splitlines() if line.startswith("id: ")]
    assert ids == [i for i, _ in full if i > 3]


def test_engine_failure_is_recorded_not_lost(tmp_path):
    settings = Settings(runs_live_root=tmp_path / "runs_live", max_workers=1, mock=True)
    # A plain MockClient answers every prompt with "canned completion": the baseline cannot
    # parse a TSS from it, repairs once, then fails.
    client = TestClient(create_app(settings, client_factory=lambda s, e: (MockClient(), "mock")))
    job_id = client.post("/runs", json={"encoding": encoding_json(), "conditions": ["baseline"],
                                        "confirm_cost": True}).json()["job_id"]
    job = wait_for(client, job_id)
    assert job["status"] == "failed" and "BaselineError" in job["error"]
    assert job["cost_usd"] > 0  # the calls that were made are still costed
    assert read_events(client, job_id)[-1][1]["event"] == "job_failed"
