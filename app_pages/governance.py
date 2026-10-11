import altair as alt
import streamlit as st

from app_lib.export_data import frame, label, result, role

g = result("governance_controls")
controls = g["controls"]

st.caption("Pre-registered coding (section 6). A control is council-attributed when it is present in at least "
           "60% of a workflow's council runs and in none of its baseline runs. All controls were judged with "
           "one evidence standard for both conditions (docs/CONTROL_MERGE_RULE.md).")

passing = [c for c in controls if c["outcome"] == "PASS"]
with st.container(horizontal=True):
    st.metric("Council-attributed controls", len(passing), border=True)
    st.metric("At ≥ 75% (exploratory)", sum(c["strict_75"] for c in passing), border=True)
    st.metric("Controls coded", len(controls), border=True)

left, right = st.columns(2)
with left:
    st.subheader("Per workflow", anchor=False)
    st.dataframe(frame([{"Workflow": r["workflow_id"], "Coded": r["final_controls"], "Attributed": r["pass"],
                         "≥ 75%": r["strict_75"]} for r in g["per_workflow"]]), hide_index=True)
with right:
    st.subheader("By introducing agentic AI role", anchor=False)
    roles = frame([{"role": role(r["role"]), "primary": r["primary"], "any": r["any"]} for r in g["by_role"]])
    st.altair_chart(alt.Chart(roles).mark_bar().encode(
        x=alt.X("primary:Q", title="Attributed controls (primary role)"),
        y=alt.Y("role:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
        tooltip=["role", "primary", "any"]), width="stretch")
    st.caption("Primary = first attributed role of the lowest-numbered member candidate. 'Any' counts every role "
               "that proposed the control.")

st.subheader("Drill down", anchor=False)
with st.container(horizontal=True):
    wf = st.selectbox("Workflow", ["All"] + [r["workflow_id"] for r in g["per_workflow"]],
                      format_func=lambda w: w if w == "All" else label(w))
    rl = st.selectbox("Primary role", ["All"] + sorted({c["primary_role"] for c in passing}),
                      format_func=lambda r: r if r == "All" else role(r))
    show = st.segmented_control("Show", ["Attributed", "All coded"], default="Attributed", required=True)

rows = [c for c in (passing if show == "Attributed" else controls)
        if (wf == "All" or c["workflow_id"] == wf) and (rl == "All" or c["primary_role"] == rl)]
table = frame([{"Control": c["name"], "Workflow": c["workflow_id"], "Primary role": role(c["primary_role"]),
                "Council": f"{c['council_present']}/{c['council_n']}", "Baseline": c["baseline_present"],
                **({"Outcome": c["outcome"]} if show == "All coded" else {})} for c in rows])
selected = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row", key="controls")

picked = selected.selection.rows if selected else []
if picked:
    c = rows[picked[0]]
    with st.container(border=True):
        st.markdown(f"**{c['name']}** · {label(c['workflow_id'])}")
        st.markdown(f"Roles: {', '.join(role(r) for r in c['roles']) or '–'} · Members: {', '.join(c['members'])}")
        if c["quote"]:
            st.markdown(f"> {c['quote']}")
            st.caption(f"From council run `{c['quote_run_id']}`")
else:
    st.caption("Select a row to see the control's evidence quote and run.")
