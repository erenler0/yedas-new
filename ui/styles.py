"""Ortak Streamlit stilleri."""

from __future__ import annotations

import streamlit as st

CSS = """
<style>
.block-container {padding-top: 1.2rem; max-width: 1400px;}
div[data-testid="stMetric"] {
  background: linear-gradient(180deg, #1a2332 0%, #141c28 100%);
  border: 1px solid #2c3d55;
  border-radius: 14px;
  padding: 12px 14px;
}
.hint { color: #9bb0c7; font-size: 0.92rem; }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
