import streamlit as st

from app_lib.export_data import frame, index, label, result

idx = index()
t = result("heldout_tables")
fi = t["fill_ins"]
profiles = {w["workflow_id"]: w["profile"] for w in idx["workflows"]}

st.caption("Seven workflows by two conditions gives 14 cells. Runs 1 to 4 ran round-robin. After run 4, a cell "
           "stopped if its run-3 depth equalled its run-4 depth, and otherwise received run 5 "
           "(pre-registration section 3).")

with st.container(horizontal=True):
    st.metric("Runs", fi["total_runs"], border=True, help="The pre-registered bound is 56 to 70")
    st.metric("Cells stopped at 4", fi["cells_stopped_at_4"], border=True)
    st.metric("Cells with a fifth run", fi["cells_with_fifth_run"], border=True)

rows = [{"Workflow": label(r["workflow_id"]), "Profile": profiles[r["workflow_id"]],
         "Council n": r["council_n"], "Council stopped at 4": r["council_stopped_at_4"],
         "Baseline n": r["baseline_n"], "Baseline stopped at 4": r["baseline_stopped_at_4"]}
        for r in t["x1_run_completion"]]
st.dataframe(frame(rows), hide_index=True,
             column_config={"Council stopped at 4": st.column_config.CheckboxColumn(),
                            "Baseline stopped at 4": st.column_config.CheckboxColumn()})

with st.expander("Run ids per cell"):
    st.dataframe(frame([{"Workflow": c["workflow_id"], "Condition": c["condition"],
                         "Stopping rule": c["stop_decision"], "Runs (rep order)": ", ".join(c["run_ids"])}
                        for c in idx["sets"]["heldout-v1"]["cells"]]), hide_index=True)
