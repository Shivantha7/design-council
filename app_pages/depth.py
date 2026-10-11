import altair as alt
import streamlit as st

from app_lib.export_data import frame, result

t = result("heldout_tables")
fi = t["fill_ins"]

st.caption("Depth is the proportion of baseline steps not retained (pre-registered). H2 holds if the council's "
           "mean depth exceeds the baseline's by at least the SESOI of 0.2 on at least 4 of 7 workflows. Gaps "
           "are compared as exact fractions.")

with st.container(horizontal=True):
    st.metric("Workflows meeting SESOI", f"{fi['h2_workflows_meeting_sesoi']} of 7", border=True)
    st.metric("H2", "Supported" if fi["h2_supported"] else "Not supported", border=True)

x3 = t["x3_depth"]
long = []
for r in x3:
    for c in ("council", "baseline"):
        long.append({"workflow": r["workflow_id"], "condition": c, "mean": r[f"{c}_mean"],
                     "min": r[f"{c}_min"], "max": r[f"{c}_max"]})
df = frame(long)
order = [r["workflow_id"] for r in x3]
color = alt.Color("condition:N", scale=alt.Scale(domain=["council", "baseline"]), title="Condition")
points = alt.Chart(df).mark_point(filled=True, size=90).encode(
    x=alt.X("mean:Q", title="Mean depth (range over runs)", scale=alt.Scale(domain=[0, 1])),
    y=alt.Y("workflow:N", sort=order, title=None), color=color,
    yOffset="condition:N", tooltip=["workflow", "condition", "mean", "min", "max"])
ranges = alt.Chart(df).mark_rule(strokeWidth=2).encode(
    x="min:Q", x2="max:Q", y=alt.Y("workflow:N", sort=order), yOffset="condition:N", color=color)
st.altair_chart(ranges + points, width="stretch")

st.subheader("Gap against the SESOI", anchor=False)
gaps = frame([{"workflow": r["workflow_id"], "gap": r["gap"], "exact": r["gap_exact"],
               "meets SESOI": "yes" if r["meets_sesoi"] else "no"} for r in x3])
bars = alt.Chart(gaps).mark_bar().encode(
    x=alt.X("gap:Q", title="Council mean − baseline mean"), y=alt.Y("workflow:N", sort=order, title=None),
    color=alt.Color("meets SESOI:N", scale=alt.Scale(domain=["yes", "no"])),
    tooltip=["workflow", "gap", "exact", "meets SESOI"])
rule = alt.Chart(frame([{"x": 0.2}])).mark_rule(strokeDash=[6, 4], strokeWidth=2).encode(x="x:Q")
st.altair_chart(bars + rule, width="stretch")
st.caption("Dashed line: SESOI 0.2. TWM and ABB sit exactly on it (gap 1/5) and count as meeting it under "
           "exact comparison.")

st.subheader("Stabilisation (H3)", anchor=False)
st.caption(f"{fi['h3_stabilised_cells']} of 14 cells stabilised against a threshold of {fi['h3_threshold']}: "
           f"{'supported' if fi['h3_supported'] else 'not supported'}. Cumulative mean depth after runs 3, 4 and "
           "5, with run-to-run consistency (mean pairwise disposition agreement).")
st.dataframe(frame([{"Cell": f"{r['workflow_id']} {r['condition']}", "After 3": r["after_3"],
                     "After 4": r["after_4"], "After 5": float("nan") if r["after_5"] is None else r["after_5"], "Stabilised": r["stabilised"],
                     "Consistency": r["consistency"]} for r in t["x5_stabilisation"]]),
             hide_index=True, column_config={k: st.column_config.NumberColumn(format="%.3f")
                                             for k in ("After 3", "After 4", "After 5", "Consistency")})
