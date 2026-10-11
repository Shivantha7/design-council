import streamlit as st

from app_lib.export_data import CONDITION_LABELS, frame, index, label, role, run, workflow

idx = index()
st.caption("Pick a workflow, condition and run to see its input (the encoding), its process (deliberation by "
           "role) and its output (the target-state specification, dispositions and gate result).")

with st.container(horizontal=True):
    set_name = st.segmented_control("Set", ["heldout-v1", "dev-v1"], default="heldout-v1", required=True,
                                    format_func=lambda s: idx["sets"][s]["label"], key="explorer_set")
    wf = st.selectbox("Workflow", idx["sets"][set_name]["workflows"], format_func=label)
    cond = st.segmented_control("Condition", ["council", "baseline"], default="council", required=True,
                                format_func=CONDITION_LABELS.get)

runs = sorted((run(r) for r in idx["sets"][set_name]["runs"]), key=lambda r: r["rep"])
choices = [r for r in runs if r["workflow_id"] == wf and r["condition"] == cond]
r = st.selectbox("Run", choices, format_func=lambda r: f"rep {r['rep']} · {r['run_id']}")

with st.container(horizontal=True):
    st.metric("Depth", f"{r['depth']['score']:.3f}", border=True)
    st.metric("Conformance", f"{r['gate']['conformance_score']:.3f}", border=True)
    st.metric("Output tokens", f"{r['efficiency']['output_tokens']:,}", border=True)
    st.metric("Runtime", f"{r['efficiency']['runtime_min']:.1f} min", border=True)

tab_in, tab_proc, tab_out = st.tabs([":material/input: Input", ":material/forum: Process", ":material/output: Output"])

with tab_in:
    w = workflow(wf)
    st.markdown(f"**{w['name']}** · {w['function_area']}" + (f" · {w['profile']}" if w["profile"] else ""))
    st.dataframe(frame([{"Step": s["step_id"], "Name": s["name"], "Actor": s["actor"],
                         "Open to elimination": s["step_id"] in w["open_steps"]} for s in w["steps"]]),
                 hide_index=True)
    st.markdown("**Requirements**")
    st.dataframe(frame([{"Id": q["requirement_id"], "Rule": q["rule_type"], "Statement": q["statement"]}
                        for q in w["requirements"]]), hide_index=True)

with tab_proc:
    st.caption("The first 600 characters of each contribution. The full text is in the run's call log.")
    phases = ["round 1", "round 2", "synthesis", "single agent"]
    for phase in phases:
        items = [t for t in r["transcript"] if t["phase"] == phase]
        if not items:
            continue
        st.markdown(f"**{phase.capitalize()}**")
        for t in items:
            with st.expander(role(t["role"])):
                st.text(t["excerpt"] + (" …" if t["truncated"] else ""))

with tab_out:
    cls = st.segmented_control("Actor class", ["class_primary", "class_agentic_only"], default="class_primary",
                               required=True,
                               format_func=lambda c: "Primary" if c == "class_primary" else "Agentic AI only")
    st.dataframe(frame([{"Step": s["step_id"], "Name": s["name"], "Actor": s["actor"], "Class": s[cls]}
                        for s in r["steps"]]), hide_index=True)
    st.markdown("**Disposition mapping**")
    st.dataframe(frame([{"Baseline step": d["baseline_step_id"], "Disposition": d["disposition"],
                         "Target steps": ", ".join(d["target_step_ids"]), "Rationale": d["rationale"]}
                        for d in r["disposition_mapping"]]), hide_index=True)
    st.markdown("**Gate result**")
    st.dataframe(frame([{"Requirement": g["requirement_id"], "Passed": g["passed"], "Vacuous": g["vacuous"],
                         "Reason": g["reason"]} for g in r["gate"]["results"]]), hide_index=True)
