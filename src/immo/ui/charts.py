"""Plotly figures. Pure builders: data in, figure out (no Streamlit calls).

Colour rules used here:
- one hue for a single series (the title says what is plotted, no legend needed),
- a FIXED colour per property type, so a filter never repaints the remaining series,
- text, axes and grid stay neutral; only the marks carry colour,
- separate, validated colour steps for the light and the dark theme.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from immo.core.assumptions import Threshold

# Categorical slots 1-3 (colour-blind safe as a set in both themes) + neutral inks.
PALETTE = {
    "light": {
        "series": ["#2a78d6", "#eb6834", "#1baf7a"],
        "surface": "#ffffff",
        "text": "#52514e",
        "grid": "#e6e5e1",
        "reference": "#8a8983",
    },
    "dark": {
        "series": ["#3987e5", "#d95926", "#199e70"],
        "surface": "#0e1117",
        "text": "#c3c2b7",
        "grid": "#33332f",
        "reference": "#8a8983",
    },
}
# colour follows the entity: each property type always gets the same slot
TYPE_SLOT = {"ETW": 0, "HAUS": 1, "MFH": 2}
TYPE_NAME = {"ETW": "Flat (ETW)", "HAUS": "House", "MFH": "Apartment building (MFH)"}

YIELD_BIN_WIDTH = 0.5
YIELD_MAX = 10.0  # everything above is collected in one last bar


def _colors(theme: str) -> dict:
    return PALETTE["dark" if theme == "dark" else "light"]


def _base_layout(fig: go.Figure, theme: str, height: int = 320) -> go.Figure:
    c = _colors(theme)
    fig.update_layout(
        height=height,
        margin={"l": 64, "r": 16, "t": 40, "b": 56},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": c["text"], "size": 13},
        hoverlabel={"font_size": 13},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "x": 0,
            "title_text": "",
            "font": {"color": c["text"]},
        },
        barcornerradius=4,
    )
    axis = {"gridcolor": c["grid"], "linecolor": c["grid"], "automargin": True}
    fig.update_xaxes(zeroline=False, title_standoff=12, **axis)
    fig.update_yaxes(zerolinecolor=c["grid"], title_standoff=12, **axis)
    return fig


def yield_histogram(
    gross_yields: pd.Series, threshold: Threshold | None, theme: str = "light"
) -> go.Figure:
    """Distribution of the gross yield in 0.5-point steps, with the signal thresholds."""
    c = _colors(theme)
    values = gross_yields.dropna().clip(upper=YIELD_MAX)
    edges = [i * YIELD_BIN_WIDTH for i in range(int(YIELD_MAX / YIELD_BIN_WIDTH) + 1)]
    labels, counts = [], []
    for lower in edges:
        if lower >= YIELD_MAX:
            labels.append(f"{YIELD_MAX:g} % or more")
            counts.append(int((values >= YIELD_MAX).sum()))
        else:
            upper = lower + YIELD_BIN_WIDTH
            labels.append(f"{lower:g}–{upper:g} %")
            counts.append(int(((values >= lower) & (values < upper)).sum()))

    fig = go.Figure(
        go.Bar(
            x=[edge + YIELD_BIN_WIDTH / 2 for edge in edges],
            y=counts,
            width=YIELD_BIN_WIDTH * 0.92,  # small gap between neighbouring bars
            marker_color=c["series"][0],
            customdata=labels,
            hovertemplate="%{customdata}<br>%{y} listings<extra></extra>",
        )
    )
    if threshold is not None:
        # the two labels sit on opposite sides of their lines so they never collide
        for value, label, anchor, shift in (
            (threshold.yellow_min, f"fair from {threshold.yellow_min:g} %", "right", -4),
            (threshold.green_min, f"good from {threshold.green_min:g} %", "left", 4),
        ):
            if value <= YIELD_MAX:
                fig.add_vline(x=value, line_width=1, line_color=c["reference"])
                fig.add_annotation(
                    x=value, y=1.0, yref="paper", text=label, showarrow=False,
                    xanchor=anchor, yanchor="bottom", xshift=shift, font={"color": c["text"]},
                )  # fmt: skip
    _base_layout(fig, theme)
    fig.update_xaxes(
        title_text="Gross yield (%)",
        tickvals=list(range(0, int(YIELD_MAX) + 1)),
        ticktext=[*(str(i) for i in range(0, int(YIELD_MAX))), f"{YIELD_MAX:g}+"],
        range=[0, YIELD_MAX + YIELD_BIN_WIDTH],
        showgrid=False,
    )
    fig.update_yaxes(title_text="Listings", rangemode="tozero")
    return fig


def price_m2_by_city(table: pd.DataFrame, theme: str = "light") -> go.Figure:
    """Median asking price per m² of living area, by city and property type."""
    c = _colors(theme)
    data = table[table["type"].isin(TYPE_SLOT) & table["price_per_m2"].notna()]
    medians = data.groupby(["city", "type"])["price_per_m2"].agg(["median", "count"]).reset_index()
    cities = sorted(medians["city"].unique(), reverse=True)  # reversed: first city on top

    fig = go.Figure()
    # horizontal groups are drawn bottom-up, so add the traces in reverse order
    for type_code, slot in reversed(TYPE_SLOT.items()):
        rows = medians[medians["type"] == type_code].set_index("city")
        if rows.empty:
            continue
        present = [city for city in cities if city in rows.index]
        fig.add_bar(
            orientation="h",
            name=TYPE_NAME[type_code],
            y=present,
            x=[rows.loc[city, "median"] for city in present],
            marker_color=c["series"][slot],
            text=[f"{rows.loc[city, 'median']:,.0f} €" for city in present],
            textposition="outside",
            textfont={"color": c["text"]},
            cliponaxis=False,
            customdata=[rows.loc[city, "count"] for city in present],
            hovertemplate=(
                "%{y} · " + TYPE_NAME[type_code]
                + "<br>median %{x:,.0f} €/m²<br>%{customdata} listings<extra></extra>"
            ),
        )  # fmt: skip
    _base_layout(fig, theme, height=max(260, 110 * len(cities) + 80))
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_layout(legend={"traceorder": "reversed"}, margin={"l": 190, "r": 80, "t": 50})
    fig.update_xaxes(title_text="Median price per m²", ticksuffix=" €", tickformat=",.0f")
    fig.update_yaxes(showgrid=False, categoryorder="array", categoryarray=cities)
    return fig


def price_history(
    series: list[tuple[datetime, float]], end: datetime, theme: str = "light"
) -> go.Figure:
    """Asking price over time as a step line (a price holds until the next change)."""
    c = _colors(theme)
    times = [t for t, _ in series]
    prices = [p for _, p in series]
    fig = go.Figure()
    if series:
        # extend the last price to `end`, so the line shows how long it has been valid
        fig.add_scatter(
            x=[*times, max(end, times[-1])],
            y=[*prices, prices[-1]],
            mode="lines",
            line={"shape": "hv", "width": 2, "color": c["series"][0]},
            hoverinfo="skip",
        )
        fig.add_scatter(
            x=times,
            y=prices,
            mode="markers",
            marker={
                "size": 10,
                "color": c["series"][0],
                "line": {"width": 2, "color": c["surface"]},
            },
            hovertemplate="%{x|%d %b %Y}<br>%{y:,.0f} €<extra></extra>",
        )
    _base_layout(fig, theme, height=300)
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title_text="Asking price", ticksuffix=" €", tickformat=",.0f")
    fig.update_xaxes(showgrid=False)
    return fig


def area_comparison(
    table: pd.DataFrame, sources: list[tuple[str, str]], unit: str, theme: str = "light"
) -> go.Figure:
    """Sources side by side per area, as grouped horizontal bars.

    `sources` is a list of (column in `table`, legend label); at most three, so every
    source keeps its own fixed colour slot.
    """
    c = _colors(theme)
    areas = list(table["area"])[::-1]  # reversed: first area on top
    fig = go.Figure()
    for slot, (column, label) in reversed(list(enumerate(sources[:3]))):
        rows = table[table[column].notna()].set_index("area")
        present = [a for a in areas if a in rows.index]
        if not present:
            continue
        decimals = 2 if rows[column].max() < 100 else 0
        fig.add_bar(
            orientation="h",
            name=label,
            y=present,
            x=[rows.loc[a, column] for a in present],
            marker_color=c["series"][slot],
            text=[f"{rows.loc[a, column]:,.{decimals}f}" for a in present],
            textposition="outside",
            textfont={"color": c["text"]},
            cliponaxis=False,
            hovertemplate="%{y} · " + label + "<br>%{x:,.2f} " + unit + "<extra></extra>",
        )
    _base_layout(fig, theme, height=max(260, 30 * len(sources) * len(areas) + 130))
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_layout(legend={"traceorder": "reversed"}, margin={"l": 210, "r": 80, "t": 50})
    fig.update_xaxes(title_text=unit, tickformat=",.0f")
    fig.update_yaxes(showgrid=False, categoryorder="array", categoryarray=areas)
    return fig
