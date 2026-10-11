import altair as alt
import streamlit as st

from app_lib.export_data import DISPOSITIONS, frame, label, result

d = result("dev_grid")
st.caption("The v1 development grid: 3 workflows by 2 conditions at n = 3 (18 runs), under the same "
           "disposition convention as the held-out set. It was used for development; the held-out evaluation "
           "is the confirmatory test. Open individual runs in the run explorer under 'Development grid (v1)'.")

cells = d["cells"]
st.dataframe(frame([{"Workflow": label(c["workflow_id"]), "Condition": c["condition"], "n": c["n"],
                     "Depth mean": c["depth_mean"], "Depth min": c["depth_min"], "Depth max": c["depth_max"],
                     "Conformance": c["conformance_mean"], "Consistency": c["consistency"],
                     "Mean output tokens": c["mean_output_tokens"]} for c in cells]),
             hide_index=True,
             column_config={k: st.column_config.NumberColumn(format="%.3f")
                            for k in ("Depth mean", "Depth min", "Depth max", "Conformance", "Consistency")}
             | {"Mean output tokens": st.column_config.NumberColumn(format="%d")})

df = frame([{"workflow": c["workflow_id"], "condition": c["condition"], "mean": c["depth_mean"],
             "min": c["depth_min"], "max": c["depth_max"]} for c in cells])
color = alt.Color("condition:N", scale=alt.Scale(domain=["council", "baseline"]))
st.altair_chart(
    alt.Chart(df).mark_rule(strokeWidth=2).encode(x=alt.X("min:Q", scale=alt.Scale(domain=[0, 1]),
                                                          title="Depth (mean, range)"),
                                                  x2="max:Q", y=alt.Y("workflow:N", title=None),
                                                  yOffset="condition:N", color=color)
    + alt.Chart(df).mark_point(filled=True, size=90).encode(x="mean:Q", y="workflow:N", yOffset="condition:N",
                                                           color=color, tooltip=["workflow", "condition", "mean"]),
    width="stretch")

st.subheader("Dispositions", anchor=False)
st.dataframe(frame([{"Workflow": c["workflow_id"], "Condition": c["condition"],
                     **{x.capitalize(): c["dispositions"][x] for x in DISPOSITIONS}} for c in cells]),
             hide_index=True)
