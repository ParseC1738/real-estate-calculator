"""Area statistics: references per area and source side by side (SPEC §8.4)."""

import pandas as pd
import streamlit as st

from immo.core.models import AreaMetric, PropertyType
from immo.ui import charts, state
from immo.ui import formatting as fmt
from immo.ui.tables import AREA_SOURCES, area_table

METRIC_LABEL = {
    AreaMetric.RENT_M2: "Rent (€/m² per month)",
    AreaMetric.BUY_PRICE_M2: "Purchase price (€/m²)",
    AreaMetric.LAND_VALUE_M2: "Land value (€/m²)",
}
# which own listings are compared for each metric
TYPE_CHOICES = {
    AreaMetric.RENT_M2: [PropertyType.ETW, PropertyType.HAUS],
    AreaMetric.BUY_PRICE_M2: [PropertyType.ETW, PropertyType.HAUS, PropertyType.MFH],
    AreaMetric.LAND_VALUE_M2: [PropertyType.GRUNDSTUECK],
}


def main() -> None:
    st.title("Area statistics")
    assumptions = state.get_assumptions()
    market = state.load_market(assumptions)
    if market.is_empty and not market.references:
        state.show_empty_database_hint()
        return

    keys = market.index.area_keys()
    cities = [k for k in keys if "/" not in k and not k.startswith("plz:")]

    left, middle, right = st.columns(3)
    metric = left.selectbox("Metric", list(METRIC_LABEL), format_func=METRIC_LABEL.get)
    property_type = middle.selectbox(
        "Property type (own listings)", TYPE_CHOICES[metric], format_func=fmt.TYPE_LABEL.get
    )
    level = right.selectbox("Areas", ["Cities", *(f"Districts of {city}" for city in cities)])
    if level == "Cities":
        area_keys = cities
    else:
        city = level.removeprefix("Districts of ")
        area_keys = [k for k in keys if k.startswith(f"{city}/")]

    table = area_table(market.index, area_keys, metric, property_type)
    table["area"] = table["area"].str.split("/").str[-1]
    sources = AREA_SOURCES[metric]

    own_note = (
        "median asking rent of own rental listings"
        if metric is AreaMetric.RENT_M2
        else "median asking price of own sale listings"
    )
    st.caption(
        f"Own listings = {own_note} of this type (needs at least "
        f"{assumptions.min_samples_own_listings} listings per area, otherwise empty). "
        "Stored references in the sample database are invented values."
    )

    chart_sources = [("own_listings", "Own listings")]
    chart_sources += [(s.value, fmt.source(s.value)) for s in sources]
    if table[[column for column, _ in chart_sources]].notna().any().any():
        state.show_chart(
            charts.area_comparison(
                table, chart_sources[:3], METRIC_LABEL[metric], state.chart_theme()
            )
        )

    money = st.column_config.NumberColumn
    config = {
        "area": "Area",
        "own_listings": money("Own listings (median)", format="%,.2f €"),
        "own_samples": money("Listings", format="%d"),
    }
    for source in sources:
        config[source.value] = money(fmt.source(source.value), format="%,.2f €")
        config[f"own_vs_{source.value}_pct"] = money(
            f"Own vs. {fmt.source(source.value).split(' (')[0]}",
            format="%+.1f %%",
            help="How far the own-listings median is above (+) or below (−) this source.",
        )
    st.dataframe(table, column_config=config, hide_index=True, width="stretch")

    with st.expander(f"All stored references ({len(market.references)})"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Area": r.area_key,
                        "Metric": r.metric.value,
                        "Type": r.property_type.value if r.property_type else "all",
                        "Segment": r.segment or "all",
                        "Value": r.value,
                        "Low": r.low,
                        "High": r.high,
                        "Source": fmt.source(r.source.value),
                        "Valid from": r.valid_from,
                        "Valid to": r.valid_to,
                        "Note": r.note,
                    }
                    for r in market.references
                ]
            ),
            hide_index=True,
            width="stretch",
        )


main()
