"""Streamlit entry point: `uv run streamlit run src/immo/ui/app.py`.

This file only defines the navigation. Each page is its own script in `pages/`;
Streamlit runs the selected one on every interaction.
"""

import streamlit as st

st.set_page_config(page_title="Immo-Rendite", page_icon="🏠", layout="wide")

PAGES = [
    st.Page("pages/overview.py", title="Overview", icon="📊", default=True),
    st.Page("pages/detail.py", title="Detail view", icon="🔎"),
]

st.navigation(PAGES).run()
