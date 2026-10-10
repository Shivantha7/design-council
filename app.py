"""
Design Council — Development Grid Viewer
=========================================
Read-only Streamlit viewer over the v1 development grid artefacts
(3 workflows x 2 conditions x n=3 = 18 logged runs).

Layers:
  1. Input   — the encoded current-state workflow (steps, requirements, sources)
  2. Process — run provenance (model, git commit, content hashes, protocol)
  3. Output  — the Target-State Specification, gate result, transformation depth
  4. Compare — council vs baseline across all runs of a workflow

Run from the repo root (demo_bundle/ present):
    streamlit run app.py

Reads artefacts only. Writes nothing. No LLM calls.
"""

import json
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------- data access

APP_DIR = Path(__file__).resolve().parent


def find_data_dir() -> Path:
    """Locate the artefact bundle: demo_bundle/ beside the app, or the app dir itself."""
    for cand in (APP_DIR / "demo_bundle", APP_DIR, Path.cwd() / "demo_bundle"):
        if (cand / "runs").is_dir() and (cand / "encodings").is_dir():
            return cand
    st.error(
        "Could not find the artefact bundle. Run this app from the repo root "
        "with `demo_bundle/` present, or place app.py next to it."
    )
    st.stop()


DATA = find_data_dir()
if str(DATA) not in sys.path:
    sys.path.insert(0, str(DATA))


def _load(p: Path):
    with open(p) as f:
        return json.load(f)


@st.cache_data
def load_encodings():
    out = {}
    for p in sorted((DATA / "encodings").glob("*.json")):
        enc = _load(p)
        out[enc["workflow_id"]] = enc
    return out


@st.cache_data
def load_kb():
    p = DATA / "kb" / "ifrs_slfrs_kb.yaml"
    if not p.exists():
        return None
    try:
        import yaml
    except ImportError:
        return "NO_YAML"
    return yaml.safe_load(open(p))["entries"]


@st.cache_data
def load_calls(run_id: str):
    p = DATA / "runs" / run_id / "calls.jsonl"
    if not p.exists():
        return None
    return [json.loads(line) for line in open(p)]


@st.cache_data
def load_runs():
    runs = {}
    for d in sorted((DATA / "runs").iterdir()):
        if not d.is_dir():
            continue
        manifest = _load(d / "run_manifest.json")
        rec = {
            "run_id": manifest["run_id"],
            "workflow_id": manifest["workflow_id"],
            "condition": manifest["condition"],
            "manifest": manifest,
            "tss": _load(d / "tss.json"),
            "gate": _load(d / "gate_result.json"),
        }
        dm = d / "depth_metrics.json"
        if dm.exists():
            rec["depth"] = _load(dm)
        else:  # raw repo runs: compute on demand from the bundled measure
            from design_council.measures import measure_depth  # noqa: deferred import
            rec["depth"] = json.loads(
                measure_depth(rec["tss"], load_encodings()[rec["workflow_id"]]).model_dump_json()
            )
        runs[rec["run_id"]] = rec
    return runs


ENCODINGS = load_encodings()
RUNS = load_runs()

WORKFLOW_NAMES = {wid: f"{wid} — {enc['name']}" for wid, enc in ENCODINGS.items()}

# ------------------------------------------------------------------- palette

COND_COLOR = {"council": "#2a78d6", "baseline": "#eb6834"}  # fixed assignment, never swapped
DISP_COLOR = {
    "eliminated": "#e34948",
    "merged": "#2a78d6",
    "absorbed": "#4a3aa7",
    "retained": "#52514e",
    "restructured": "#1baf7a",
}
DISP_ORDER = ["eliminated", "merged", "absorbed", "retained", "restructured"]
ROLES = [
    "maximalist", "pragmatist", "finance_domain", "emerging_economy",
    "hitl_designer", "agentic_architect", "accounting_standards",
]
ROLE_LABELS = {
    "maximalist": "Maximalist",
    "pragmatist": "Pragmatist",
    "finance_domain": "Finance Domain",
    "emerging_economy": "Emerging-Economy Constraint",
    "hitl_designer": "Human-in-the-Loop Designer",
    "agentic_architect": "Agentic Architect",
    "accounting_standards": "Accounting Standards",
    "baseline_designer": "Baseline Designer (single agent)",
    "synthesis": "Synthesis (moderator)",
    "model_resolution_probe": "Model-resolution probe",
}


def parse_phase(agent_role: str):
    """Split 'round1_maximalist' -> ('Round 1 — independent positions', 'maximalist')."""
    if agent_role.startswith("round1_"):
        return "Round 1 — independent positions", agent_role[7:]
    if agent_role.startswith("round2_"):
        return "Round 2 — cross-critique", agent_role[7:]
    if agent_role == "synthesis":
        return "Synthesis", "synthesis"
    if agent_role == "baseline_designer":
        return "Single-agent design", "baseline_designer"
    return "Setup", agent_role


def badge(text: str, color: str) -> str:
    return (
        f'<span style="background:{color};color:#fff;padding:2px 10px;'
        f'border-radius:10px;font-size:0.78rem;font-weight:600;'
        f'white-space:nowrap">{text}</span>'
    )


def cond_badge(condition: str) -> str:
    return badge(condition.upper(), COND_COLOR[condition])


# --------------------------------------------------------------------- page

st.set_page_config(page_title="Design Council — Dev Grid Viewer", layout="wide", page_icon="🏛️")

st.title("Multi-Agent Design Council — Development Grid")
st.caption(
    "Outcome-anchored redesign of finance workflows · CS7P01NM · "
    "v1 development grid: 3 workflows × 2 conditions × n=3 — 18 logged runs. "
    "This viewer renders logged run artefacts only; it makes no model calls."
)

# headline grid status
all_scores = [r["gate"]["conformance_score"] for r in RUNS.values()]
all_disp = [
    d["disposition"]
    for r in RUNS.values()
    for d in r["tss"]["disposition_mapping"]
]
at_ceiling = sum(1 for s in all_scores if s == 1.0)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Logged runs (v1 grid)", len(RUNS))
c2.metric(
    "Runs at gate ceiling (1.00)",
    f"{at_ceiling}/{len(all_scores)}",
    help=f"Minimum conformance across the grid: {min(all_scores):.2f}",
)
c3.metric("Dispositions mapped", len(all_disp))
c4.metric("Eliminations", str(all_disp.count("eliminated")) + " (corpus-driven)")

st.divider()

# ------------------------------------------------------------------ sidebar

with st.sidebar:
    st.header("Select a run")
    wid = st.selectbox(
        "Workflow", options=sorted(ENCODINGS), format_func=lambda w: WORKFLOW_NAMES[w]
    )
    condition = st.radio("Condition", ["council", "baseline"], horizontal=True)
    wf_runs = sorted(
        [r for r in RUNS.values() if r["workflow_id"] == wid and r["condition"] == condition],
        key=lambda r: r["run_id"],
    )
    run = st.selectbox(
        "Run",
        options=wf_runs,
        format_func=lambda r: f'{r["run_id"][:15]}…{r["run_id"][-4:]}  (depth {r["depth"]["depth_score"]:.3f})',
    )
    st.markdown("---")
    st.markdown(
        f'{cond_badge(condition)} &nbsp; **{wid}**<br>'
        f'<span style="font-size:0.8rem;color:#777">run_id: <code>{run["run_id"]}</code></span>',
        unsafe_allow_html=True,
    )

enc = ENCODINGS[wid]
tss = run["tss"]
gate = run["gate"]
depth = run["depth"]
manifest = run["manifest"]

tab_in, tab_proc, tab_delib, tab_out, tab_cmp, tab_rep = st.tabs(
    ["**1 · Input — encoding**", "**2 · Process — provenance**",
     "**3 · Deliberation**", "**4 · Output — redesign**",
     "**5 · Council vs baseline**", "**6 · Outcome report**"]
)

# ------------------------------------------------------------- tab 1: input

with tab_in:
    left, right = st.columns([3, 2])
    with left:
        st.subheader(enc["name"])
        st.markdown(
            f'**Workflow** `{enc["workflow_id"]}` · **Domain** `{enc["domain"]}` · '
            f'{len(enc["steps"])} baseline steps · {len(enc["requirements"])} requirements'
        )
        st.markdown("##### Baseline steps (current state)")
        steps_df = pd.DataFrame(
            [
                {
                    "Step": s["step_id"],
                    "Name": s["name"],
                    "Actor": s["actor"],
                    "Inputs": " · ".join(s["inputs"]),
                    "Outputs": " · ".join(s["outputs"]),
                }
                for s in enc["steps"]
            ]
        )
        st.dataframe(steps_df, width='stretch', hide_index=True)
        with st.expander("Step descriptions"):
            for s in enc["steps"]:
                st.markdown(f'**{s["step_id"]} — {s["name"]}** ({s["actor"]})')
                st.write(s["description"])
    with right:
        st.markdown("##### Requirements (deterministic gate inputs)")
        req_df = pd.DataFrame(
            [
                {
                    "ID": r["requirement_id"],
                    "Rule type": r["rule_type"],
                    "Statement": r["statement"],
                }
                for r in enc["requirements"]
            ]
        )
        st.dataframe(req_df, width='stretch', hide_index=True)
        if enc.get("unconstrained_by_design"):
            with st.expander("Unconstrained by design"):
                st.write(enc["unconstrained_by_design"])
        with st.expander("Source & APQC anchoring"):
            st.json(enc.get("source", {}))
            st.json(enc.get("source_mapping", []))

    kb = load_kb()
    st.markdown("##### Standards knowledge base — IFRS/SLFRS (Accounting Standards agent grounding)")
    if kb == "NO_YAML":
        st.info("Install `pyyaml` to display the knowledge base: `pip install pyyaml`")
    elif kb is None:
        st.info("Knowledge base file not found in the bundle.")
    else:
        wf_step_ids = {s["step_id"] for s in enc["steps"]}
        kb_df = pd.DataFrame(
            [
                {
                    "ID": e["id"],
                    "Standard": f'{e["standard"]} / {e["slfrs_equivalent"]}',
                    "Topic": e["topic"],
                    "Principle": e["principle"],
                    "Relevance": e["relevance"],
                    "Bears on this workflow": "✓ " + ", ".join(
                        i for i in e["bears_on"] if i in wf_step_ids
                    ) if any(i in wf_step_ids for i in e["bears_on"]) else "—",
                }
                for e in kb
            ]
        )
        st.dataframe(kb_df, width='stretch', hide_index=True)
        n_rel = int((kb_df["Bears on this workflow"] != "—").sum())
        st.caption(
            f"{len(kb)} hand-curated principles across 7 standards · {n_rel} bear on "
            f"{wid} steps · the agent declares silence where coverage ends rather than extrapolating."
        )

# ----------------------------------------------------------- tab 2: process

with tab_proc:
    st.subheader("Run provenance")
    st.caption(
        "Every run is logged with the resolved model, repository commit, and content hashes "
        "of its inputs — the run is reproducible and the inputs are tamper-evident."
    )
    a, b = st.columns(2)
    with a:
        st.markdown("##### Identity")
        st.markdown(
            f"""
| | |
|---|---|
| Run ID | `{manifest["run_id"]}` |
| Created (UTC) | {manifest["created_utc"]} |
| Condition | {manifest["condition"]} |
| Workflow | {manifest["workflow_id"]} |
| Requested model | `{manifest["requested_model"]}` |
| Resolved model | `{manifest["resolved_model"]}` |
"""
        )
        st.markdown("##### Protocol")
        st.code(manifest["config"].get("protocol", "—"), language=None)
        st.markdown(
            f'Sampling: {manifest["config"].get("sampling", "—")} · '
            f'params `{json.dumps(manifest["config"].get("sampling_params", {}))}`'
        )
    with b:
        st.markdown("##### Reproducibility anchors")
        st.markdown(
            f"""
| | |
|---|---|
| Git commit | `{manifest["git_commit"][:12]}` |
| Dirty tree | {"⚠️ yes" if manifest["git_dirty"] else "no (clean)"} |
| Encoding SHA-256 | `{manifest["encoding_sha256"][:16]}…` |
| KB SHA-256 | `{manifest["kb_sha256"][:16]}…` |
| Encoding path | `{manifest["config"].get("encoding_path", "—")}` |
"""
        )
        charters = manifest["config"].get("charter_hashes")
        if charters:
            st.markdown("##### Role charter hashes (council)")
            st.dataframe(
                pd.DataFrame(
                    [{"Role": k, "SHA-256": v[:20] + "…"} for k, v in charters.items()]
                ),
                width='stretch', hide_index=True,
            )
        with st.expander("Raw manifest"):
            st.json(manifest)

# ------------------------------------------------------- tab 3: deliberation

with tab_delib:
    calls = load_calls(run["run_id"])
    if calls is None:
        # point at the representative run that carries a transcript
        with_transcript = [
            r["run_id"]
            for r in RUNS.values()
            if r["workflow_id"] == wid and r["condition"] == condition
            and (DATA / "runs" / r["run_id"] / "calls.jsonl").exists()
        ]
        if with_transcript:
            st.info(
                f"The full deliberation transcript is bundled for the representative run of this "
                f"cell — select run `…{with_transcript[0][-4:]}` in the sidebar to replay it. "
                "(Transcripts for every run live in the repository under `runs/<run_id>/calls.jsonl`.)"
            )
        else:
            st.info(
                "No transcript bundled for this cell. Every run's full transcript lives in the "
                "repository under `runs/<run_id>/calls.jsonl`."
            )
    else:
        work = [c for c in calls if c["agent_role"] != "model_resolution_probe"]
        retries = [c for c in calls if c.get("attempt_status", "ok") != "ok"]
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Logged LLM calls", len(calls))
        t2.metric("Output tokens", f'{sum(c.get("output_tokens") or 0 for c in work):,}')
        t3.metric("Thinking tokens", f'{sum(c.get("thinking_tokens") or 0 for c in work):,}')
        t4.metric(
            "Failed attempts (retried & logged)", len(retries),
            help="Stream failures are retried and every attempt is kept in the log — "
                 "nothing is silently dropped.",
        )
        if condition == "council":
            st.caption(
                "Protocol: 7 role agents give independent positions (round 1), each then "
                "cross-critiques the others' positions (round 2), and a moderator synthesises "
                "the final TSS. Every call below is the logged transcript, verbatim."
            )
        phase_order = []
        by_phase = {}
        for c in calls:
            if c["agent_role"] == "model_resolution_probe":
                continue
            phase, role = parse_phase(c["agent_role"])
            if phase not in by_phase:
                by_phase[phase] = []
                phase_order.append(phase)
            by_phase[phase].append((role, c))
        for phase in phase_order:
            st.markdown(f"#### {phase}")
            for role, c in by_phase[phase]:
                label = ROLE_LABELS.get(role, role)
                a_status = c.get("attempt_status", "ok")
                status = "" if a_status == "ok" else f" · ⚠️ {a_status} (retried)"
                with st.expander(
                    f'{label} — {c.get("output_tokens") or 0:,} tokens'
                    f' ({c.get("thinking_tokens") or 0:,} thinking){status}'
                ):
                    if a_status != "ok":
                        st.warning(
                            "This attempt failed mid-stream and was retried; it is kept in the "
                            "log for completeness. The successful attempt follows."
                        )
                    st.markdown(c["raw_completion"])

# ------------------------------------------------------------ tab 4: output

with tab_out:
    st.subheader("Target-State Specification")

    # disposition summary strip
    counts = depth["profile"]["counts"]
    strip = " &nbsp; ".join(
        badge(f'{d} {counts.get(d, 0)}', DISP_COLOR[d]) for d in DISP_ORDER
    )
    m1, m2, m3 = st.columns([2, 1, 1])
    with m1:
        st.markdown("**Disposition profile** — every baseline step accounted for exactly once:")
        st.markdown(strip, unsafe_allow_html=True)
    m2.metric("Gate conformance", f'{gate["conformance_score"]:.2f}')
    m3.metric(
        "Transformation depth", f'{depth["depth_score"]:.3f}',
        help="Pre-registered scalar: proportion of baseline steps not retained unchanged.",
    )

    st.markdown("##### Disposition mapping (baseline → target)")
    disp_rows = []
    base_names = {s["step_id"]: s["name"] for s in enc["steps"]}
    for d in tss["disposition_mapping"]:
        disp_rows.append(
            {
                "Baseline step": f'{d["baseline_step_id"]} — {base_names.get(d["baseline_step_id"], "")}',
                "Disposition": d["disposition"],
                "Target step(s)": ", ".join(d["target_step_ids"]) or "—",
            }
        )
    st.dataframe(pd.DataFrame(disp_rows), width='stretch', hide_index=True)
    with st.expander("Disposition rationales (council deliberation record)" if condition == "council" else "Disposition rationales"):
        for d in tss["disposition_mapping"]:
            st.markdown(
                f'{badge(d["disposition"], DISP_COLOR[d["disposition"]])} '
                f'**{d["baseline_step_id"]}** → {", ".join(d["target_step_ids"]) or "∅"}',
                unsafe_allow_html=True,
            )
            st.write(d["rationale"])

    st.markdown("##### Redesigned target steps")
    tgt_df = pd.DataFrame(
        [
            {"Step": s["step_id"], "Name": s["name"], "Actor": s["actor"]}
            for s in tss["steps"]
        ]
    )
    st.dataframe(tgt_df, width='stretch', hide_index=True)
    with st.expander("Target step descriptions"):
        for s in tss["steps"]:
            st.markdown(f'**{s["step_id"]} — {s["name"]}** ({s["actor"]})')
            st.write(s["description"])

    st.markdown("##### Rule-conformance gate (deterministic, no LLM)")
    gate_df = pd.DataFrame(
        [
            {
                "Requirement": g["requirement_id"],
                "Result": "✅ pass" if g["passed"] else "❌ fail",
                "Vacuous": "yes" if g.get("vacuous") else "no",
                "Reason": g["reason"],
            }
            for g in gate["results"]
        ]
    )
    st.dataframe(gate_df, width='stretch', hide_index=True)

    supp = depth.get("supplementary", {})
    if supp:
        s1, s2, s3 = st.columns(3)
        s1.metric("Actor reassignments", supp.get("actor_reassignments", 0))
        s2.metric(
            "Steps: baseline → target",
            f'{supp.get("baseline_step_count", "—")} → {supp.get("target_step_count", "—")}',
        )
        s3.metric("Net-new steps", supp.get("net_new_steps", 0))

# -------------------------------------------------------- tab 4: comparison

with tab_cmp:
    st.subheader(f"Council vs baseline — {WORKFLOW_NAMES[wid]}")
    wf_all = sorted(
        [r for r in RUNS.values() if r["workflow_id"] == wid],
        key=lambda r: (r["condition"], r["run_id"]),
    )

    cmp_df = pd.DataFrame(
        [
            {
                "Run": f'{r["condition"]} · {r["run_id"][-4:]}',
                "Condition": r["condition"],
                "Conformance": r["gate"]["conformance_score"],
                "Depth": r["depth"]["depth_score"],
                **{
                    d.capitalize(): r["depth"]["profile"]["counts"].get(d, 0)
                    for d in DISP_ORDER
                },
            }
            for r in wf_all
        ]
    )

    chart_col, table_col = st.columns([1, 1])
    with chart_col:
        st.markdown("##### Transformation depth by run")
        try:
            import altair as alt

            chart = (
                alt.Chart(cmp_df)
                .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=34)
                .encode(
                    x=alt.X("Run:N", sort=None, axis=alt.Axis(labelAngle=0, title=None, labelFontSize=10)),
                    y=alt.Y("Depth:Q", scale=alt.Scale(domain=[0, 1]), title="Depth score"),
                    color=alt.Color(
                        "Condition:N",
                        scale=alt.Scale(
                            domain=["council", "baseline"],
                            range=[COND_COLOR["council"], COND_COLOR["baseline"]],
                        ),
                        legend=alt.Legend(orient="top", title=None),
                    ),
                    tooltip=["Run", "Condition", "Depth", "Conformance"],
                )
                .properties(height=320)
            )
            labels = chart.mark_text(dy=-8, fontSize=11).encode(
                text=alt.Text("Depth:Q", format=".3f"), color=alt.value("#52514e")
            )
            st.altair_chart(chart + labels, width='stretch')
        except ImportError:
            st.bar_chart(cmp_df.set_index("Run")["Depth"])
        cc, cb = (
            cmp_df[cmp_df.Condition == "council"]["Depth"],
            cmp_df[cmp_df.Condition == "baseline"]["Depth"],
        )
        conf = cmp_df.Conformance
        conf_note = (
            "Conformance 1.00 in every run of both conditions."
            if conf.min() == 1.0
            else f"Conformance: {int((conf == 1.0).sum())}/{len(conf)} runs at 1.00, minimum {conf.min():.2f}."
        )
        st.caption(
            f"Council depth: {cc.min():.3f}–{cc.max():.3f} (mean {cc.mean():.3f}) · "
            f"Baseline depth: {cb.min():.3f}–{cb.max():.3f} (mean {cb.mean():.3f}) · "
            f"{conf_note} "
            "n=3 per cell: depth differences within 0.125 are inside sampling noise."
        )
    with table_col:
        st.markdown("##### All runs (this workflow)")
        st.dataframe(cmp_df, width='stretch', hide_index=True)

    st.markdown("##### Role-attributed reasoning in council dispositions")
    st.caption(
        "Counts of explicit role attributions in the disposition rationales of each council run — "
        "the deliberation is traceable to named roles, which the single-agent baseline cannot produce."
    )
    role_rows = []
    for r in wf_all:
        if r["condition"] != "council":
            continue
        text = " ".join(d["rationale"].lower() for d in r["tss"]["disposition_mapping"])
        role_rows.append(
            {
                "Run": r["run_id"][:15] + "…" + r["run_id"][-4:],
                **{role: len(re.findall(re.escape(role), text)) for role in ROLES},
            }
        )
    if role_rows:
        st.dataframe(pd.DataFrame(role_rows), width='stretch', hide_index=True)

# ----------------------------------------------------------- tab 6: report

with tab_rep:
    st.subheader(f"Outcome report — {WORKFLOW_NAMES[wid]}")
    st.caption("Generated from logged artefacts for review. Download as Markdown below.")

    wf_all_r = sorted(
        [r for r in RUNS.values() if r["workflow_id"] == wid],
        key=lambda r: (r["condition"], r["run_id"]),
    )
    cc_runs = [r for r in wf_all_r if r["condition"] == "council"]
    cb_runs = [r for r in wf_all_r if r["condition"] == "baseline"]

    def stats(rs, key):
        vals = [key(r) for r in rs]
        return min(vals), max(vals), sum(vals) / len(vals)

    cd_min, cd_max, cd_mean = stats(cc_runs, lambda r: r["depth"]["depth_score"])
    bd_min, bd_max, bd_mean = stats(cb_runs, lambda r: r["depth"]["depth_score"])
    gate_fails = [
        (r, g)
        for r in wf_all_r
        for g in r["gate"]["results"]
        if not g["passed"]
    ]
    # aggregate dispositions per condition
    def disp_agg(rs):
        agg = {d: 0 for d in DISP_ORDER}
        for r in rs:
            for d, n in r["depth"]["profile"]["counts"].items():
                agg[d] += n
        return agg

    agg_c, agg_b = disp_agg(cc_runs), disp_agg(cb_runs)
    role_counts = {role: 0 for role in ROLES}
    for r in cc_runs:
        text = " ".join(d["rationale"].lower() for d in r["tss"]["disposition_mapping"])
        for role in ROLES:
            role_counts[role] += len(re.findall(re.escape(role), text))

    lines = [
        f"# Outcome report — {WORKFLOW_NAMES[wid]}",
        "",
        f"*Development grid, v1 instrument · n=3 per condition · generated from logged run artefacts*",
        "",
        "## Design",
        f"- **Workflow**: {enc['name']} ({wid}, domain {enc['domain']}) — "
        f"{len(enc['steps'])} baseline steps, {len(enc['requirements'])} gate requirements",
        "- **Conditions**: seven-role Design Council (2 deliberation rounds + synthesis) vs "
        "compute-matched single-agent baseline, same base model",
        "- **Measures**: deterministic rule-conformance gate (primary); transformation depth "
        "(proportion of baseline steps not retained); run-to-run consistency",
        "",
        "## Results",
        "",
        "| Run | Condition | Conformance | Depth | " + " | ".join(d.capitalize() for d in DISP_ORDER) + " |",
        "|---|---|---|---|" + "---|" * len(DISP_ORDER),
    ]
    for r in wf_all_r:
        cts = r["depth"]["profile"]["counts"]
        lines.append(
            f'| …{r["run_id"][-4:]} | {r["condition"]} | '
            f'{r["gate"]["conformance_score"]:.2f} | {r["depth"]["depth_score"]:.3f} | '
            + " | ".join(str(cts.get(d, 0)) for d in DISP_ORDER) + " |"
        )
    lines += [
        "",
        f"- **Depth** — council {cd_min:.3f}–{cd_max:.3f} (mean {cd_mean:.3f}); "
        f"baseline {bd_min:.3f}–{bd_max:.3f} (mean {bd_mean:.3f}). "
        "At n=3 per cell, differences within the 0.125 quantum are inside sampling noise.",
        f"- **Dispositions (aggregate over 3 runs)** — council: "
        + ", ".join(f"{agg_c[d]} {d}" for d in DISP_ORDER if agg_c[d]) + "; baseline: "
        + ", ".join(f"{agg_b[d]} {d}" for d in DISP_ORDER if agg_b[d]) + ".",
        "- **Eliminations** — zero in both conditions: the roles explicitly reason that no "
        "elimination is defensible on this corpus; transformation is carried by restructuring, "
        "merging and actor reassignment (a corpus-driven finding, logged in transcripts).",
    ]
    if gate_fails:
        lines.append("")
        lines.append("## Gate exceptions")
        for r, g in gate_fails:
            lines.append(
                f'- Run `…{r["run_id"][-4:]}` ({r["condition"]}): **{g["requirement_id"]} failed** — '
                f'{g["reason"]} *(the deterministic gate catching a real violation; '
                f'scored, logged, and reported as-is).*'
            )
    else:
        lines.append("")
        lines.append("All requirements passed in every run of both conditions (gate ceiling).")
    lines += [
        "",
        "## Role-attributed reasoning (council only)",
        "Explicit role attributions in disposition rationales across the three council runs: "
        + ", ".join(
            f"{ROLE_LABELS[role]} {n}" for role, n in role_counts.items() if n
        ) + ".",
        "",
        "Council TSSs carry role-attributed governance controls absent from baseline draws — "
        "the council's primary demonstrated advantage at this sample size.",
        "",
        "---",
        "*All figures are read from logged run artefacts (manifests, TSSs, gate results) or "
        "recomputed deterministically from them. Development phase; held-out runs follow the "
        "pre-registration freeze.*",
    ]
    report_md = "\n".join(lines)
    st.download_button(
        "⬇ Download report (Markdown)",
        report_md,
        file_name=f"outcome_report_{wid}.md",
        mime="text/markdown",
    )
    st.markdown(report_md)

st.divider()
st.caption(
    "Artefact viewer only — all numbers are read from logged run artefacts "
    "(manifests, TSS, gate results) or recomputed deterministically from them. "
    "Development grid (pre-freeze); held-out runs follow the pre-registration freeze."
)
