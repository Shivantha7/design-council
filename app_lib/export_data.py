"""Read-only access to export/ for the results app. Nothing else is read.

export/ is produced by scripts/export_app_data.py and documented in export/SCHEMA.md.
"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

EXPORT = Path(__file__).resolve().parent.parent / "export"

ROLE_LABELS = {
    "maximalist": "Maximalist",
    "pragmatist": "Pragmatist",
    "finance_domain": "Finance domain",
    "emerging_economy": "Emerging-economy constraint",
    "hitl_designer": "Human-in-the-loop designer",
    "agentic_architect": "Agentic architect",
    "accounting_standards": "Accounting standards",
    "synthesis": "Synthesis",
    "baseline_designer": "Single agentic AI (baseline)",
}
CONDITION_LABELS = {"council": "Council (multi-agent)", "baseline": "Baseline (single agentic AI)"}
DISPOSITIONS = ["eliminated", "absorbed", "merged", "restructured", "retained"]


@st.cache_data(max_entries=200)
def load(rel: str):
    return json.loads((EXPORT / rel).read_text())


def index() -> dict:
    return load("index.json")


def workflow(workflow_id: str) -> dict:
    return load(f"workflows/{workflow_id}.json")


def run(run_id: str) -> dict:
    return load(f"runs/{run_id}.json")


def result(name: str) -> dict:
    return load(f"results/{name}.json")


def workflow_names() -> dict:
    return {w["workflow_id"]: w["name"] for w in index()["workflows"]}


def label(workflow_id: str) -> str:
    return f"{workflow_id} · {workflow_names().get(workflow_id, '')}"


def role(name: str) -> str:
    return ROLE_LABELS.get(name, name.replace("_", " ").capitalize())


def exploratory_note(what: str) -> None:
    st.warning(f"**Exploratory.** {what} Not pre-registered; read alongside the pre-registered results.",
               icon=":material/science:")


def frame(rows) -> pd.DataFrame:
    return pd.DataFrame(rows)
