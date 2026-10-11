"""Design Council results app: held-out evaluation and development grid.

    .venv-viewer/bin/streamlit run app.py

Read-only. Reads ONLY export/ (see export/SCHEMA.md), which is produced by
scripts/export_app_data.py from the run logs and committed coding data.
Makes no API calls and writes nothing.
"""

import streamlit as st

st.set_page_config(page_title="Design Council results", page_icon=":material/account_tree:", layout="wide")

page = st.navigation(
    {
        "": [
            st.Page("app_pages/overview.py", title="Overview", icon=":material/home:", default=True),
        ],
        "Held-out evaluation (pre-registered)": [
            st.Page("app_pages/grid.py", title="Held-out grid", icon=":material/grid_view:"),
            st.Page("app_pages/depth.py", title="Transformation depth", icon=":material/stacked_bar_chart:"),
            st.Page("app_pages/transform.py", title="How they transform", icon=":material/transform:"),
            st.Page("app_pages/conformance.py", title="Conformance", icon=":material/rule:"),
            st.Page("app_pages/governance.py", title="Governance controls", icon=":material/verified_user:"),
        ],
        "Exploratory": [
            st.Page("app_pages/productivity.py", title="Productivity potential", icon=":material/speed:"),
        ],
        "Explore": [
            st.Page("app_pages/explorer.py", title="Run explorer", icon=":material/travel_explore:"),
            st.Page("app_pages/dev_grid.py", title="Development grid", icon=":material/science:"),
        ],
    },
    position="sidebar",
)

st.title(page.title, anchor=False)
page.run()
