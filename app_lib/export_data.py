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
    "finance_domain": "Finance Domain",
    "emerging_economy": "Emerging-Economy Constraint",
    "hitl_designer": "Human-in-the-Loop Designer",
    "agentic_architect": "Agentic Architect",
    "accounting_standards": "Accounting Standards",
    "synthesis": "Synthesis",
    "baseline_designer": "Budget-matched single agent",
}
CONDITION_LABELS = {"council": "Council (multi-agent)", "baseline": "Budget-matched single agent",
                    "sequential": "Sequential (exploratory, post-freeze)"}
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
    return ROLE_LABELS.get(name, name.replace("_", " ").title())


def pct(x: float) -> str:
    """PI as a percentage, as reported in the dissertation."""
    return f"{round(100 * x)}%"


def doc_link(path: str) -> str:
    """A Markdown link to a committed document, on the repository if its URL is recorded."""
    url = index().get("repo_url")
    return f"[{path}]({url}/blob/main/{path})" if url else f"`{path}`"


def sequential_note() -> None:
    seq = result("sequential")
    links = ", ".join(doc_link(w["doc"]) for w in seq["workflows"])
    st.info(f"**{seq['label']}.** One agent given a budget comparable to the council's: {seq['protocol']}. "
            f"Run on {len(seq['workflows'])} held-out workflows only, after "
            f"the freeze; not part of any pre-registered result. Write-ups: {links}.", icon=":material/science:")


def exploratory_note(what: str) -> None:
    st.warning(f"**Exploratory.** {what} Not pre-registered; read alongside the pre-registered results.",
               icon=":material/science:")


def frame(rows) -> pd.DataFrame:
    return pd.DataFrame(rows)
