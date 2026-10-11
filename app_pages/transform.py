import altair as alt
import streamlit as st

from app_lib.export_data import DISPOSITIONS, frame, index, result, run

t = result("heldout_tables")
x4 = t["x4_dispositions"]

st.caption("Each baseline step receives one disposition in every target-state specification. The counts "
           "cover all held-out runs (Table X.4).")

df = frame([{"condition": c, "disposition": d, "steps": x4[c][d]} for c in ("council", "baseline") for d in DISPOSITIONS])
chart = alt.Chart(df).mark_bar().encode(
    x=alt.X("steps:Q", title="Baseline steps (all runs)"),
    y=alt.Y("condition:N", title=None),
    color=alt.Color("disposition:N", scale=alt.Scale(domain=DISPOSITIONS), sort=DISPOSITIONS),
    order=alt.Order("order:Q"),
    tooltip=["condition", "disposition", "steps"],
).transform_calculate(order=f"indexof({DISPOSITIONS}, datum.disposition)")
st.altair_chart(chart, width="stretch")

st.dataframe(frame([{"Disposition": d.capitalize(), "Council": x4["council"][d], "Baseline": x4["baseline"][d]}
                    for d in DISPOSITIONS]), hide_index=True)
st.markdown("No step was eliminated in either condition. The council restructures far more often, and absorbs "
            "and merges less often, than the single agentic AI baseline.")

st.subheader("By workflow", anchor=False)
idx = index()
rows = []
for cell in idx["sets"]["heldout-v1"]["cells"]:
    counts = {d: 0 for d in DISPOSITIONS}
    for rid in cell["run_ids"]:
        for d, n in run(rid)["depth"]["counts"].items():
            counts[d] += n
    rows.append({"Workflow": cell["workflow_id"], "Condition": cell["condition"], "Runs": len(cell["run_ids"]),
                 **{d.capitalize(): counts[d] for d in DISPOSITIONS}})
st.dataframe(frame(rows), hide_index=True)
