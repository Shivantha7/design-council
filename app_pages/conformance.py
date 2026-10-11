import streamlit as st

from app_lib.export_data import frame, result, run

t = result("heldout_tables")
fi = t["fill_ins"]
cf = result("conformance_failures")

st.caption("The deterministic gate checks every target-state specification against the encoded "
           "requirements. Pre-registered reading (H1): conformance is a validity floor, and every run below "
           "1.0 is reported individually.")

with st.container(horizontal=True):
    st.metric("Runs below 1.0", fi["runs_below_1"], border=True)
    st.metric("Council", fi["runs_below_1_council"], border=True)
    st.metric("Baseline", fi["runs_below_1_baseline"], border=True)
    st.metric("Branch", fi["h1_branch"], border=True)

rows = [{"Run": f["run_id"], "Condition": f["condition"], "Workflow": f["workflow_id"],
         "Score": f"{f['score']:.3f} ({f['passed']}/{f['total']})", "Requirement failed": ", ".join(f["failed"]),
         "Classification (exploratory)": f["classification"]} for f in cf["failures"]]
st.dataframe(frame(rows), hide_index=True)
st.caption("The classification column is exploratory (docs/CONFORMANCE_FAILURE_CLASSIFICATION.md). NAMING means "
           "the input is present with a qualifier, such as 'Tolerance policy (versioned)', that exact matching "
           "does not recognise. No score is changed.")

st.subheader("Gate detail", anchor=False)
choice = st.selectbox("Failed run", [f["run_id"] for f in cf["failures"]])
r = run(choice)
for g in r["gate"]["results"]:
    if not g["passed"]:
        st.error(f"**{g['requirement_id']}** · {g['reason']}", icon=":material/close:")
with st.expander("All requirements for this run"):
    st.dataframe(frame([{"Requirement": g["requirement_id"], "Passed": g["passed"], "Vacuous": g["vacuous"],
                         "Reason": g["reason"]} for g in r["gate"]["results"]]), hide_index=True)
