"""Small reusable Streamlit widgets shared by several pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def range_filter(
    label: str, column: pd.Series, step: float, fmt_str: str | None = None
) -> tuple[float, float] | None:
    """A range slider over a column. Returns None while it covers the full range,

    so listings with an unknown value are only hidden once the user narrows it.
    """
    values = column.dropna()
    if values.empty or values.min() == values.max():
        return None
    low = float(values.min() // step * step)
    high = float(-(-values.max() // step) * step)  # round up to the next step
    chosen = st.slider(label, low, high, (low, high), step=float(step), format=fmt_str)
    return None if chosen == (low, high) else chosen


def optional_number(label: str, help_text: str, step: float) -> float | None:
    """A number input that may stay empty ("any")."""
    return st.number_input(label, value=None, step=step, help=help_text, placeholder="any")
