import streamlit as st

from app_lib.export_data import index

idx = index()
h = idx["headline"]

st.markdown(f"**Research question.** {idx['research_question']}")
st.caption("A seven-role Design Council (two deliberation rounds and a synthesis) is compared with a "
           "budget-matched single agent on the same model, across seven held-out finance workflows. "
           f"Pre-registration freeze tag `{idx.get('prereg_tag')}`.")

with st.container(horizontal=True):
    st.metric("Held-out runs", h["heldout_runs"], border=True, help="Within the pre-registered bound of 56 to 70")
    st.metric("H2 depth (SESOI 0.2)", h["h2"], border=True, help="Workflows where the council mean depth "
              "exceeds the baseline's by at least 0.2. The threshold is 4 of 7.")
    st.metric("H3 stabilised cells", h["h3"], border=True, help="The threshold is 8 of 14")
    st.metric("Council-attributed controls", h["council_attributed_controls"], border=True,
              help="Present in ≥ 60% of council runs and in no baseline run (section 6)")
    st.metric("Runs below 1.0 conformance", h["runs_below_1"], border=True)
    st.metric("Council cost vs single agent", f"{h['council_to_baseline_cost_ratio']:.0f}×", border=True,
              help="Descriptive. At $2/M input and $10/M output tokens")

st.subheader("Findings", anchor=False)
colors = {"pre-registered": "blue", "pre-registered counts": "blue", "pre-registered coding": "violet",
          "exploratory": "orange"}
for f in idx["findings"]:
    with st.container(border=True):
        st.badge(f["status"], color=colors.get(f["status"], "gray"))
        st.markdown(f"**{f['title']}**")
        st.markdown(f["text"].replace("$", "\\$"))

st.subheader("Limits", anchor=False)
with st.container(border=True):
    for item in idx["limits"]:
        # Escape "$" so amounts are not read as LaTeX.
        st.markdown(f"- **{item['id']}.** " + item["text"].replace("$", "\\$"))
