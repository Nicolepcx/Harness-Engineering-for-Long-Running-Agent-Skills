"""
Harness Engineering for Long-Running Agent Skills: course lab app.

Run locally:  ALLOW_NO_PASSWORD=1 streamlit run app.py
"""

import streamlit as st

from core.auth import is_authenticated, require_access
from core.ui import inject_css

st.set_page_config(page_title="Skill Harness · Lab", page_icon=":material/build:", layout="wide")
inject_css()

pages = {
    "Course": [
        st.Page("views/home.py", title="Start here", icon=":material/home:", default=True),
    ],
    "Hands-on": [
        st.Page("views/h1_compile_evaluate.py", title="1 · Compile and evaluate", icon=":material/rule:", url_path="compile-evaluate"),
        st.Page("views/h2_state_repair.py", title="2 · State and repair", icon=":material/timeline:", url_path="state-repair"),
    ],
    "Trace": [
        st.Page("views/trace.py", title="Execution trace", icon=":material/history_edu:", url_path="trace"),
    ],
}

# Resolve the page before the password gate so deep links survive the login.
page = st.navigation(pages, position="sidebar" if is_authenticated() else "hidden")
require_access()
page.run()
