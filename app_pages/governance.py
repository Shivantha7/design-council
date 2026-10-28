import altair as alt
import streamlit as st

from app_lib.export_data import exploratory_note, frame, label, result, role

g = result("governance_controls")
controls = g["controls"]

st.caption("Pre-registered coding (section 6). A control is council-attributed when it is present in at least "
           "60% of a workflow's council runs and in none of its baseline runs. All controls were judged with "
           "one evidence standard for both conditions (docs/CONTROL_MERGE_RULE.md).")

passing = [c for c in controls if c["outcome"] == "PASS"]
with st.container(horizontal=True):
    st.metric("Council-attributed controls", len(passing), border=True)
    st.metric("At ≥ 75% (exploratory)", sum(c["strict_75"] for c in passing), border=True)
    st.metric("Distinct controls after merging (from 307 candidates)", len(controls), border=True)

left, right = st.columns(2)
with left:
    st.subheader("Per workflow", anchor=False)
    st.dataframe(frame([{"Workflow": r["workflow_id"], "Coded": r["final_controls"], "Attributed": r["pass"],
                         "≥ 75%": r["strict_75"]} for r in g["per_workflow"]]), hide_index=True)
with right:
    st.subheader("By introducing role", anchor=False)
    roles = frame([{"role": role(r["role"]), "primary": r["primary"], "any": r["any"]} for r in g["by_role"]])
    st.altair_chart(alt.Chart(roles).mark_bar().encode(
        x=alt.X("primary:Q", title="Attributed controls (primary role)"),
        y=alt.Y("role:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
        tooltip=["role", "primary", "any"]), width="stretch")
    st.caption("Primary = first attributed role of the lowest-numbered member candidate. 'Any' counts every role "
               "that proposed the control.")

st.subheader("Symmetric count and length", anchor=False)
exploratory_note("The section 6 rule applied in both directions, and control counts set against TSS length.")
sl = result("controls_symmetric_length")
sym = sl["symmetric"]
st.dataframe(frame([{"Workflow": wf, "Coded": s["final"], "Council-attributed": s["council_pass"],
                     "Baseline-attributed": s["baseline_pass"], "Baseline only (any run)": s["baseline_any_no_council"],
                     "Council only (any run)": s["council_any_no_baseline"], "Both": s["both"]}
                    for wf, s in sym.items()]), hide_index=True)
st.caption("Baseline-attributed applies the same rule with the conditions swapped: present in at least 60% of "
           "baseline runs and in no council run. Candidates came from both conditions' TSSs, but the codebook was "
           "seeded from council deliberation, so a baseline-only mechanism could be under-represented.")

lc = sl["length_by_condition"]
with st.container(horizontal=True):
    for c in ("council", "baseline"):
        st.metric(f"Controls per 1,000 TSS words ({c})", f"{lc[c]['per_1000_words']:.1f}", border=True,
                  help=f"Mean per run: {lc[c]['controls']:.1f} controls in {lc[c]['words']:.0f} words, "
                       f"{lc[c]['per_step']:.2f} per step")
lw = sl["length_by_workflow"]
st.dataframe(frame([{"Workflow": wf, "Council words": lw[wf]["council"]["words"],
                     "Baseline words": lw[wf]["baseline"]["words"],
                     "Council controls": lw[wf]["council"]["controls"],
                     "Baseline controls": lw[wf]["baseline"]["controls"],
                     "Council per 1,000 words": lw[wf]["council"]["per_1000_words"],
                     "Baseline per 1,000 words": lw[wf]["baseline"]["per_1000_words"]} for wf in sym]),
             hide_index=True,
             column_config={**{k: st.column_config.NumberColumn(format="%.0f") for k in ("Council words", "Baseline words")},
                            **{k: st.column_config.NumberColumn(format="%.1f") for k in ("Council controls", "Baseline controls")},
                            **{k: st.column_config.NumberColumn(format="%.2f") for k in
                               ("Council per 1,000 words", "Baseline per 1,000 words")}})
st.caption("Means per successful run, TSS text only. Council TSSs are about twice as long and carry about twice as "
           "many distinct controls, so per 1,000 words the two conditions are close. Details in "
           "docs/CONTROLS_SYMMETRIC_LENGTH.md.")

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
