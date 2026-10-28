import altair as alt
import streamlit as st

from app_lib.export_data import CONDITION_LABELS, exploratory_note, frame, result, sequential_note

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
             hide_index=True, height="content",
             column_config={k: st.column_config.NumberColumn(format="%.3f")
                            for k in ("After 3", "After 4", "After 5", "Consistency")})

st.subheader("H2 under resampling", anchor=False)
exploratory_note("Bootstrap of the H2 decision rule: runs resampled with replacement within each cell, and the "
                 "rule (gap ≥ 0.2 on at least 4 of 7 workflows) re-applied to every replicate.")
b = result("bootstrap_h2")
st.caption(f"{b['B']:,} replicates, seed {b['seed']}. 'Recorded' uses depth as logged; 'verified' counts only "
           "non-retained labels that the TSS itself bears out (next section). Leave-one-run-out deletes each of "
           "the 68 runs in turn.")
boot_rec, boot_ver, loo_rec, loo_ver = st.columns(4)
for col, key in ((boot_rec, "reported"), (boot_ver, "verified")):
    col.metric(f"Bootstrap, {'recorded' if key == 'reported' else 'verified'}",
               f"{b[key]['bootstrap_pass_rate']:.1%}", border=True,
               help=f"Point estimate: {b[key]['point_pass']} of 7 workflows meet the SESOI")
for col, key in ((loo_rec, "reported"), (loo_ver, "verified")):
    col.metric(f"Leave one out, {'recorded' if key == 'reported' else 'verified'}",
               f"{b[key]['loo_pass_rate']:.1%}", border=True,
               help=f"{len(b[key]['loo_fail_cases'])} of 68 single-run deletions make H2 fail")

dist = frame([{"depth": "recorded" if key == "reported" else "verified", "workflows meeting SESOI": int(k),
               "share of replicates": v}
              for key in ("reported", "verified") for k, v in b[key]["count_distribution"].items()])
bars = alt.Chart(dist).mark_bar().encode(
    x=alt.X("workflows meeting SESOI:O", title="Workflows meeting the SESOI in a replicate",
               axis=alt.Axis(labelAngle=0)),
    xOffset="depth:N", y=alt.Y("share of replicates:Q", axis=alt.Axis(format="%"), title="Share of replicates"),
    color=alt.Color("depth:N", scale=alt.Scale(domain=["recorded", "verified"]), title="Depth"),
    tooltip=["depth", "workflows meeting SESOI", alt.Tooltip("share of replicates:Q", format=".1%")])
st.altair_chart(bars, width="stretch")
st.caption(f"H2 passes in a replicate when at least {b['need']} workflows meet the SESOI.")

st.dataframe(frame([{"Workflow": wf,
                     **{f"{'Recorded' if key == 'reported' else 'Verified'} {col}": val
                        for key in ("reported", "verified")
                        for col, val in (("gap", b[key]["point_gaps"][wf]),
                                         ("95% interval", "[{:.3f}, {:.3f}]".format(*b[key]["gap_95ci"][wf])),
                                         ("P(gap ≥ 0.2)", b[key]["per_workflow_pass_prob"][wf]))}}
                    for wf in order]),
             hide_index=True, column_config={k: st.column_config.NumberColumn(format="%.3f") for k in
                                             ("Recorded gap", "Verified gap")}
             | {k: st.column_config.NumberColumn(format="%.2f") for k in
                ("Recorded P(gap ≥ 0.2)", "Verified P(gap ≥ 0.2)")})

st.subheader("Recorded and verified depth", anchor=False)
exploratory_note("Each non-retained disposition label was checked deterministically against the TSS (actor, "
                 "inputs or position changed). Verified depth counts only the labels that check out.")
v = result("depth_verification")
st.caption(f"{v['runs_ok']} successful runs, {v['labels_total']} baseline-step labels; the {v['runs_failed_excluded']} "
           "failed attempts are excluded from every depth figure.")
st.dataframe(frame([{"Workflow": k.split("|")[0], "Condition": k.split("|")[1], "Runs": c["n"],
                     "Depth (recorded)": c["depth_reported_mean"], "Depth (verified)": c["depth_verified_mean"],
                     "Difference": round(c["depth_verified_mean"] - c["depth_reported_mean"], 3)}
                    for k, c in sorted(v["cells"].items(), key=lambda kv: order.index(kv[0].split("|")[0]))]),
             hide_index=True, height="content",
             column_config={k: st.column_config.NumberColumn(format="%.3f") for k in
                            ("Depth (recorded)", "Depth (verified)", "Difference")})
st.dataframe(frame([{"Condition": cond, "Label": lab, "Labels": s["n"], "Verified": s.get("verified"),
                     "Rate": s.get("rate")}
                    for cond in ("council", "baseline") for lab, s in v["by_condition"][cond].items()]),
             hide_index=True, height="content", column_config={"Rate": st.column_config.NumberColumn(format="%.3f")})
st.caption("For 'retained', verified means consistent: no change in actor, inputs or position. Details in "
           "docs/DEPTH_VERIFICATION.md.")

st.subheader("Sequential condition", anchor=False)
sequential_note()
seq = result("sequential")
st.dataframe(frame([{"Workflow": w["workflow_id"], "Condition": CONDITION_LABELS[c], "Runs": x["n"],
                     "Depth (mean)": x["depth_mean"], "Min": x["depth_min"], "Max": x["depth_max"],
                     "Conformance": x["conformance_mean"], "Runs < 1": x["runs_below_1"],
                     "Consistency": x["consistency"]}
                    for w in seq["workflows"] for c, x in w["conditions"].items()]),
             hide_index=True, height="content",
             column_config={k: st.column_config.NumberColumn(format="%.3f")
                            for k in ("Depth (mean)", "Min", "Max", "Conformance", "Consistency")})
st.caption("Council and budget-matched single agent rows are the held-out cells for the same workflow. Depth as "
           "recorded; consistency is mean pairwise disposition agreement within the cell.")
