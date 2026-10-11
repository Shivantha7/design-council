import altair as alt
import streamlit as st

from app_lib.export_data import exploratory_note, frame, result

p = result("productivity")
exploratory_note("Structural productivity potential (PI) is the share of original human effort removed by "
                 "each council design under stated assumptions (docs/PRODUCTIVITY_METHOD.md). It is an "
                 "estimate of the potential built into the design, not a measured operational outcome.")

variant = st.segmented_control(
    "Classification", ["primary", "agentic-only"], default="primary", required=True,
    format_func=lambda v: {"primary": "Primary (deterministic automation counts)",
                           "agentic-only": "Agentic AI only (deterministic automation counted as human)"}[v])
v = p["variants"][variant]

with st.container(horizontal=True):
    for g, lbl in (("all", "Pooled PI"), ("transactional", "Transactional"), ("judgment-dense", "Judgment-dense")):
        x = v["pooled"][g]
        st.metric(lbl, f"{x['pi']:.3f}", border=True, help=f"90% workflow-bootstrap interval {x['p05']:.3f} to {x['p95']:.3f}")

df = frame([{"workflow": r["workflow_id"], "profile": r["profile"], "median": r["median"],
             "p05": r["p05"], "p95": r["p95"]} for r in v["per_workflow"]])
order = [r["workflow_id"] for r in v["per_workflow"]]
color = alt.Color("profile:N", title="Profile")
ci = alt.Chart(df).mark_rule(strokeWidth=3).encode(
    x=alt.X("p05:Q", title="PI (median, 90% interval)", scale=alt.Scale(domain=[0, 1])), x2="p95:Q",
    y=alt.Y("workflow:N", sort=order, title=None), color=color)
pt = alt.Chart(df).mark_point(filled=True, size=110).encode(
    x="median:Q", y=alt.Y("workflow:N", sort=order), color=color, tooltip=["workflow", "median", "p05", "p95"])
st.altair_chart((ci + pt).properties(height=320), width="stretch")
st.caption(f"{p['draws']:,} Monte Carlo draws (seed {p['seed']}). The worst case is 0 for every workflow by "
           "construction: all weight falls on the most human-intensive carried step.")

st.subheader("Primary vs agentic-only", anchor=False)
both = frame([{"workflow": a["workflow_id"], "classification": name, "median": a["median"]}
              for name in ("primary", "agentic-only") for a in p["variants"][name]["per_workflow"]])
st.altair_chart(alt.Chart(both).mark_bar().encode(
    x=alt.X("median:Q", title="Median PI"), y=alt.Y("workflow:N", sort=order, title=None),
    yOffset="classification:N", color="classification:N", tooltip=["workflow", "classification", "median"]),
    width="stretch")

st.subheader("Structural indicators: original vs council", anchor=False)
st.caption("No parameters. Council values are means over the workflow's council runs. HITL = human-in-the-loop "
           "checkpoints. H-to-H = hand-offs between two human steps.")
rows = []
for s in v["structural"]:
    o, c = s["original"], s["council"]
    rows.append({"Workflow": s["workflow_id"],
                 "Human steps, original": o["HUMAN"], "Human steps, council": c["HUMAN"]["mean"],
                 "HITL, original": o["HITL"], "HITL, council": c["HITL"]["mean"],
                 "H-to-H hand-offs, original": o["h2h"], "H-to-H hand-offs, council": c["h2h"]["mean"]})
st.dataframe(frame(rows), hide_index=True,
             column_config={k: st.column_config.NumberColumn(format="%.1f") for k in rows[0] if "council" in k})

with st.expander("Sensitivity (partial rank correlation with pooled PI)"):
    st.dataframe(frame([{"Parameter": k, "PRCC": x, "OAT at min": v["oat"][k]["at_min"], "OAT at max": v["oat"][k]["at_max"]}
                        for k, x in sorted(v["prcc"].items(), key=lambda kv: -abs(kv[1]))]), hide_index=True)
