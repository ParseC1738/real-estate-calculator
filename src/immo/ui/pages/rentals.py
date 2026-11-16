"""Rental listings: table and filters for MIETE listings (SPEC §8.5)."""

import pandas as pd
import streamlit as st

from immo.ui import formatting as fmt
from immo.ui import state
from immo.ui.tables import RentalFilters, filter_rental_table, rental_table
from immo.ui.widgets import range_filter

COLUMN_CONFIG = {
    "title": st.column_config.TextColumn("Title", width="medium"),
    "city": "City",
    "district": "District",
    "type": "Type",
    "rent_month": st.column_config.NumberColumn("Cold rent/month", format="%,.0f €"),
    "area_m2": st.column_config.NumberColumn("Area", format="%.0f m²"),
    "rent_per_m2": st.column_config.NumberColumn("Rent €/m²", format="%.2f €"),
    "rent_vs_mietspiegel_pct": st.column_config.NumberColumn(
        "vs. Mietspiegel", format="%+.1f %%", help="Asking rent vs. the official rent table."
    ),
    "rent_vs_area_pct": st.column_config.NumberColumn(
        "vs. area", format="%+.1f %%", help="Asking rent vs. the median of comparable listings."
    ),
    "rooms": st.column_config.NumberColumn("Rooms", format="%.1f"),
    "year_built": st.column_config.NumberColumn("Built", format="%d"),
    "days_online": st.column_config.NumberColumn("Days online", format="%d"),
    "price_change_pct": st.column_config.NumberColumn("Rent change", format="%+.1f %%"),
    "is_active": st.column_config.CheckboxColumn("Active"),
    "url": st.column_config.LinkColumn("Link", display_text="open"),
}


def sidebar_filters(table: pd.DataFrame) -> RentalFilters:
    filters = RentalFilters()
    with st.sidebar:
        st.header("Filters")
        filters.only_active = st.toggle("Only active listings", value=True)
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
        filters.rent_month = range_filter("Cold rent (€/month)", table["rent_month"], 50, "%d")
        filters.area_m2 = range_filter("Area (m²)", table["area_m2"], 10, "%d")
        filters.rooms = range_filter("Rooms", table["rooms"], 1, "%d")
        filters.rent_per_m2 = range_filter("Rent (€/m²)", table["rent_per_m2"], 1, "%d")
    return filters


def main() -> None:
    st.title("Rental listings")
    st.caption(
        "Rental listings are mainly the data source for the rent estimates: their median "
        "per area, type and size is the 'market' value."
    )
    assumptions = state.get_assumptions()
    market = state.load_market(assumptions)
    table = rental_table(state.evaluate_all_rentals(market))
    if table.empty:
        state.show_empty_database_hint()
        return
    filtered = filter_rental_table(table, sidebar_filters(table))

    kpi = st.columns(4)
    kpi[0].metric("Listings shown", f"{len(filtered)} of {len(table)}")
    kpi[1].metric("Median rent per m²", fmt.eur(_median(filtered["rent_per_m2"]), 2))
    kpi[2].metric("Median cold rent", fmt.eur(_median(filtered["rent_month"])))
    kpi[3].metric(
        "Median vs. Mietspiegel", fmt.pct(_median(filtered["rent_vs_mietspiegel_pct"]), signed=True)
    )
    if filtered.empty:
        st.warning("No listing matches the current filters.")
        return
    st.dataframe(
        filtered.drop(columns=["id"]).assign(type=filtered["type"].map(fmt.TYPE_SHORT)),
        column_config=COLUMN_CONFIG,
        hide_index=True,
        width="stretch",
        height=560,
    )


def _median(column: pd.Series) -> float | None:
    values = column.dropna()
    return float(values.median()) if not values.empty else None


main()
