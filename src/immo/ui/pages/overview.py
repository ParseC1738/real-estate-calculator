"""Overview: all KAUF listings with key metrics, filters and summary charts (SPEC §8.1)."""

import pandas as pd
import streamlit as st

from immo.ui import charts, state
from immo.ui import formatting as fmt
from immo.ui.tables import BuyFilters, buy_table, filter_buy_table


def _range_filter(label: str, column: pd.Series, step: float, fmt_str: str | None = None):
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


def _optional_number(label: str, help_text: str, step: float) -> float | None:
    return st.number_input(label, value=None, step=step, help=help_text, placeholder="any")


def sidebar_filters(table: pd.DataFrame) -> BuyFilters:
    filters = BuyFilters()
    with st.sidebar:
        st.header("Filters")
        filters.only_active = st.toggle("Only active listings", value=True)
        filters.only_price_reduced = st.toggle("Only price-reduced")

        filters.cities = st.multiselect("City", sorted(table["city"].unique()))
        in_cities = table[table["city"].isin(filters.cities)] if filters.cities else table
        filters.districts = st.multiselect(
            "District", sorted(in_cities["district"].dropna().unique())
        )
        filters.types = st.multiselect(
            "Property type",
            sorted(table["type"].unique()),
            format_func=lambda code: fmt.TYPE_LABEL.get(code, code),
        )

        with st.expander("Property", expanded=False):
            filters.price = _range_filter("Price (€)", table["price"], 10_000, "%d")
            filters.area_m2 = _range_filter("Area (m²)", table["area_m2"], 10, "%d")
            filters.rooms = _range_filter("Rooms", table["rooms"], 1, "%d")
            filters.year_built = _range_filter("Year built", table["year_built"], 5, "%d")
            filters.days_online = _range_filter("Days online", table["days_online"], 7, "%d")

        with st.expander("Return", expanded=True):
            filters.min_gross_yield_pct = _optional_number(
                "Min. gross yield (%)", "Hides plots, which have no yield.", 0.5
            )
            filters.min_net_yield_pct = _optional_number(
                "Min. net yield (%)", "After non-recoverable costs, maintenance, vacancy.", 0.5
            )
            filters.min_cashflow_month = _optional_number(
                "Min. cash flow (€/month)", "Before tax, with the current financing.", 50.0
            )
            filters.max_price_vs_area_pct = _optional_number(
                "Max. price vs. area (%)", "E.g. -10 = at least 10 % cheaper than the area.", 5.0
            )
    return filters


COLUMN_CONFIG = {
    "signal": st.column_config.TextColumn(
        "Signal", help="Based on the gross yield; thresholds are part of the assumptions."
    ),
    "title": st.column_config.TextColumn("Title", width="medium"),
    "city": "City",
    "district": "District",
    "type": "Type",
    "price": st.column_config.NumberColumn("Price", format="%,.0f €"),
    "area_m2": st.column_config.NumberColumn(
        "Area", format="%.0f m²", help="Living area; plot area for plots."
    ),
    "price_per_m2": st.column_config.NumberColumn("€/m²", format="%,.0f €"),
    "price_vs_area_pct": st.column_config.NumberColumn(
        "vs. area", format="%+.1f %%", help="Negative = cheaper than comparable listings."
    ),
    "rooms": st.column_config.NumberColumn("Rooms", format="%.1f"),
    "year_built": st.column_config.NumberColumn("Built", format="%d"),
    "rent_month": st.column_config.NumberColumn("Rent/month", format="%,.0f €"),
    "rent_origin": st.column_config.TextColumn(
        "Rent source", help="Actual rent from the listing, estimate, or your override."
    ),
    "gross_yield_pct": st.column_config.NumberColumn("Gross yield", format="%.2f %%"),
    "net_yield_pct": st.column_config.NumberColumn("Net yield", format="%.2f %%"),
    "price_to_rent_factor": st.column_config.NumberColumn(
        "Factor", format="%.1f", help="Kaufpreisfaktor: price ÷ annual cold rent."
    ),
    "cashflow_month": st.column_config.NumberColumn(
        "Cash flow/month", format="%+,.0f €", help="Before tax."
    ),
    "cash_on_cash_pct": st.column_config.NumberColumn("Cash-on-cash", format="%+.1f %%"),
    "days_online": st.column_config.NumberColumn("Days online", format="%d"),
    "price_change_pct": st.column_config.NumberColumn(
        "Price change", format="%+.1f %%", help="Since the listing was first seen."
    ),
    "price_drops": st.column_config.NumberColumn("Drops", format="%d"),
    "relisted": st.column_config.CheckboxColumn("Relisted"),
    "is_active": st.column_config.CheckboxColumn("Active"),
    "url": st.column_config.LinkColumn("Link", display_text="open"),
}


def main() -> None:
    st.title("Overview – properties for sale")
    assumptions = state.get_assumptions()
    market = state.load_market(assumptions)
    if market.is_empty:
        state.show_empty_database_hint()
        return

    table = buy_table(state.evaluate_all_buy(market, assumptions))
    filtered = filter_buy_table(table, sidebar_filters(table))

    kpi = st.columns(4)
    kpi[0].metric("Listings shown", f"{len(filtered)} of {len(table)}")
    kpi[1].metric("Median gross yield", fmt.pct(_median(filtered["gross_yield_pct"]), 2))
    kpi[2].metric("Median cash flow / month", fmt.eur(_median(filtered["cashflow_month"])))
    kpi[3].metric("Price-reduced", int((filtered["price_drops"] > 0).sum()))

    if filtered.empty:
        st.warning("No listing matches the current filters.")
        return

    st.caption(
        "Click a column header to sort. Select a row to open its detail view. "
        "Rent source: 📄 actual · 🧮 estimated · ✏️ override."
    )
    selection = st.dataframe(
        filtered.drop(columns=["id"]).assign(type=filtered["type"].map(fmt.TYPE_SHORT)),
        column_config=COLUMN_CONFIG,
        hide_index=True,
        width="stretch",
        height=420,
        on_select="rerun",
        selection_mode="single-row",
        key="overview_table",
    )
    selected_rows = selection.selection.rows
    if selected_rows:
        row = filtered.iloc[selected_rows[0]]
        if st.button(f"🔎 Open detail view: {row['title']}", type="primary"):
            st.session_state[state.DETAIL_KEY] = row["id"]
            st.switch_page("pages/detail.py")

    st.subheader("Summary")
    theme = state.chart_theme()
    left, right = st.columns(2)
    with left:
        st.markdown("**Gross yield distribution**")
        state.show_chart(
            charts.yield_histogram(
                filtered["gross_yield_pct"], assumptions.traffic_light.get("gross_yield_pct"), theme
            )
        )
    with right:
        st.markdown("**Median price per m² by city and type**")
        state.show_chart(charts.price_m2_by_city(filtered, theme))
    with st.expander("Chart data as table"):
        st.dataframe(
            filtered[filtered["price_per_m2"].notna()]
            .groupby(["city", "type"])
            .agg(
                listings=("price_per_m2", "count"),
                median_price_per_m2=("price_per_m2", "median"),
                median_gross_yield_pct=("gross_yield_pct", "median"),
            )
            .round(2)
            .reset_index(),
            hide_index=True,
            width="stretch",
        )


def _median(column: pd.Series) -> float | None:
    values = column.dropna()
    return float(values.median()) if not values.empty else None


main()
