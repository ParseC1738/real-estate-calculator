"""Detail view: everything about one property, with the calculation steps (SPEC §8.2)."""

import pandas as pd
import streamlit as st

from immo.core.evaluate import BuyEvaluation
from immo.core.history import price_series
from immo.core.models import OfferType, Override, OverrideField, PropertyType
from immo.ui import charts, state
from immo.ui import formatting as fmt
from immo.ui.explain import explain_buy


def _pick_listing(market: state.Market):
    listings = sorted(market.of_type(OfferType.KAUF), key=lambda x: (x.city, x.title))
    ids = [x.id for x in listings]
    by_id = {x.id: x for x in listings}
    preselected = st.session_state.get(state.DETAIL_KEY)
    index = ids.index(preselected) if preselected in by_id else 0
    chosen = st.selectbox(
        "Property",
        ids,
        index=index,
        format_func=lambda i: f"{by_id[i].city} · {by_id[i].title} · {fmt.eur(by_id[i].price)}",
    )
    st.session_state[state.DETAIL_KEY] = chosen
    return by_id[chosen]


def _header(e: BuyEvaluation) -> None:
    listing = e.listing
    st.header(listing.title)
    place = ", ".join(p for p in (listing.district, listing.postal_code, listing.city) if p)
    status = "active" if listing.is_active else "⚠️ no longer online"
    st.caption(f"{fmt.TYPE_LABEL[listing.property_type]} · {place} · {status}")
    if listing.url:
        st.link_button("Open the listing ↗", listing.url)


def _kpis(e: BuyEvaluation) -> None:
    m = e.metrics
    cols = st.columns(6)
    cols[0].metric("Price", fmt.eur(m.price), help=f"Source: {fmt.origin(m.price_origin)}")
    cols[1].metric(
        "Price per m²",
        fmt.eur(m.price_per_m2),
        delta=f"{fmt.pct(m.price_vs_area_pct, signed=True)} vs. area"
        if m.price_vs_area_pct is not None
        else None,
        delta_color="inverse",  # cheaper than the area is good
    )
    if e.listing.property_type is PropertyType.GRUNDSTUECK:
        cols[2].metric("Land value (BORIS)", fmt.eur(m.land_value_m2))
        cols[3].metric("Price vs. land value", fmt.pct(m.price_vs_land_value_pct, signed=True))
        cols[4].metric("Gross yield", fmt.MISSING, help="A plot produces no rent.")
        cols[5].metric("Cash flow / month", fmt.MISSING)
        return
    cols[2].metric("Gross yield", fmt.pct(m.gross_yield_pct, 2), help=fmt.signal(m.indicator))
    cols[3].metric("Net yield", fmt.pct(m.net_yield_pct, 2))
    cols[4].metric("Price-to-rent factor", fmt.num(m.price_to_rent_factor, 1))
    cols[5].metric("Cash flow / month", fmt.eur(m.cashflow_month_pretax))
    st.caption(
        f"Signal: {fmt.signal(m.indicator)} · Rent used: {fmt.eur(m.rent_month)} per month "
        f"({fmt.origin(m.rent_origin)})"
    )


def _property_data(e: BuyEvaluation) -> None:
    listing = e.effective
    m = e.metrics
    rows = [
        ("Price", fmt.eur(listing.price), fmt.origin(m.price_origin)),
        ("Living area", fmt.area(listing.living_area_m2), fmt.origin(m.area_origin)),
        ("Plot area", fmt.area(listing.plot_area_m2), ""),
        ("Rooms", fmt.num(listing.rooms, 1), ""),
        ("Units", fmt.num(listing.units, 0), ""),
        ("Year built", str(listing.year_built) if listing.year_built else fmt.MISSING, ""),
        ("Condition", listing.condition or fmt.MISSING, ""),
        ("Energy class", listing.energy_class or fmt.MISSING, ""),
        ("Rented", {True: "yes", False: "no", None: fmt.MISSING}[listing.is_rented], ""),
        ("Actual rent / month", fmt.eur(listing.actual_rent_month), ""),
        ("Hausgeld / month", fmt.eur(listing.hausgeld_month), ""),
        (
            "Commission",
            fmt.pct(m.purchase_costs.commission_pct, 2),
            fmt.origin(m.purchase_costs.commission_origin),
        ),
        ("Address", listing.address or fmt.MISSING, ""),
        ("Source", f"{listing.source} · {listing.source_listing_id}", ""),
        ("First seen", f"{listing.first_seen:%d %b %Y}", ""),
        ("Last seen", f"{listing.last_seen:%d %b %Y}", ""),
    ]
    st.dataframe(
        pd.DataFrame(rows, columns=["Field", "Value", "Origin"]), hide_index=True, width="stretch"
    )
    with st.expander("Raw data from the source"):
        st.json(e.listing.raw)


def _calculation(e: BuyEvaluation, assumptions) -> None:
    steps = explain_buy(e.metrics, assumptions)
    st.dataframe(
        pd.DataFrame(
            [(s.label, s.formula, s.result) for s in steps],
            columns=["Metric", "Calculation", "Result"],
        ),
        hide_index=True,
        width="stretch",
        height=38 * (len(steps) + 1),
    )
    for note in e.metrics.notes:
        st.warning(note)
    st.caption("All values depend on the current assumptions (interest, equity, costs …).")


def _rent_estimate(e: BuyEvaluation) -> None:
    if e.listing.property_type is PropertyType.GRUNDSTUECK:
        st.info("A plot has no rent, so there is no rent estimate.")
        return
    used, market = e.rent, e.market_rent
    cols = st.columns(3)
    cols[0].metric(
        "Rent used in the calculation",
        fmt.eur(used.value_month if used else None),
        help="Order of precedence: your override → actual rent → estimate.",
    )
    cols[1].metric("Origin", fmt.origin(used.origin) if used else fmt.MISSING)
    cols[2].metric("Estimated market rent", fmt.eur(market.value_month if market else None))
    if market is None:
        st.warning(
            "No market estimate possible: the living area is unknown or there is no data "
            "for this area with the chosen strategy."
        )
        return
    st.markdown(
        f"**Market estimate** – strategy `{market.strategy.value}`, "
        f"{fmt.eur(market.rent_m2, 2)}/m² × {fmt.area(e.effective.living_area_m2)}, "
        f"confidence **{fmt.CONFIDENCE_LABEL[market.confidence]}**"
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Source": fmt.source(c.source.value),
                    "Area": c.area_key,
                    "Rent €/m²": c.rent_m2,
                    "Weight": c.weight,
                    "Samples": c.sample_size,
                    "Used": "yes" if c.weight > 0 else "shown for comparison",
                    "Note": c.note,
                }
                for c in market.components
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Rent €/m²": st.column_config.NumberColumn(format="%.2f €"),
            "Weight": st.column_config.NumberColumn(format="percent"),
        },
    )
    st.caption(
        "The Mietspiegel reflects existing rents and is usually below asking rents. "
        "Sample references are invented values."
    )


def _history(e: BuyEvaluation, market: state.Market) -> None:
    snapshots = market.snapshots.get(e.listing.id, [])
    history = e.history
    if history:
        cols = st.columns(4)
        cols[0].metric("Days online", history.days_online)
        cols[1].metric("Price changes", history.price_change_count)
        cols[2].metric("Total price change", fmt.pct(history.total_price_change_pct, signed=True))
        cols[3].metric("Relisted", "yes" if history.relisted else "no")
    end = market.now if e.listing.is_active else e.listing.last_seen
    state.show_chart(charts.price_history(price_series(snapshots), end, state.chart_theme()))
    rows = []
    for snapshot in snapshots:
        if not snapshot.changes:
            event = "first seen"
        else:
            parts = []
            for name, change in snapshot.changes.items():
                if name == "is_active":
                    parts.append("back online (relisted)" if change["new"] else "went offline")
                else:
                    parts.append(f"{name}: {change['old']} → {change['new']}")
            event = "; ".join(parts)
        rows.append({"Date": snapshot.seen_at, "Price": snapshot.price, "Event": event})
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Date": st.column_config.DatetimeColumn(format="DD MMM YYYY"),
            "Price": st.column_config.NumberColumn(format="%,.0f €"),
        },
    )


OVERRIDE_INPUTS = {
    OverrideField.RENT_MONTH: ("Cold rent per month (€)", 10.0),
    OverrideField.PRICE: ("Purchase price (€)", 1000.0),
    OverrideField.LIVING_AREA_M2: ("Living area (m²)", 1.0),
}


def _overrides(e: BuyEvaluation, market: state.Market) -> None:
    """Let the user replace rent, price or living area for this one listing."""
    listing = e.listing
    existing = {o.field: o for o in market.overrides.get(listing.id, [])}
    originals = {
        OverrideField.RENT_MONTH: (
            listing.actual_rent_month
            if listing.actual_rent_month is not None
            else (e.market_rent.value_month if e.market_rent else None)
        ),
        OverrideField.PRICE: listing.price,
        OverrideField.LIVING_AREA_M2: listing.living_area_m2,
    }
    st.caption(
        "An override always wins over the listing's value and over any estimate. It is "
        "stored for this listing only; the original data is never changed."
    )
    fields = list(OVERRIDE_INPUTS)
    if listing.property_type is PropertyType.GRUNDSTUECK:
        fields = [OverrideField.PRICE]  # a plot has neither rent nor living area

    with st.form(f"overrides_{listing.id}"):
        values = {}
        for column, field in zip(st.columns(len(fields)), fields, strict=True):
            label, step = OVERRIDE_INPUTS[field]
            original = originals[field]
            values[field] = column.number_input(
                label,
                min_value=0.0,
                value=existing[field].value if field in existing else None,
                step=step,
                placeholder="no override",
                help="Without override: "
                + (fmt.num(original, 2) if original is not None else "unknown"),
            )
        note = st.text_input("Note (optional)", placeholder="e.g. rent after renovation")
        submitted = st.form_submit_button("Save overrides", type="primary")

    if submitted:
        repo = state.get_repo()
        for field, value in values.items():
            current = existing.get(field)
            if value is None or value <= 0:
                if current is not None:
                    repo.delete_override(listing.id, field)
            elif current is None or current.value != value:
                repo.set_override(
                    Override(listing_id=listing.id, field=field, value=value, note=note)
                )
        st.rerun()  # recalculate everything with the new overrides

    if existing:
        st.markdown("**Active overrides**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Field": OVERRIDE_INPUTS[o.field][0],
                        "Override": o.value,
                        "Without override": originals[o.field],
                        "Set on": o.created_at,
                        "Note": o.note,
                    }
                    for o in existing.values()
                ]
            ),
            hide_index=True,
            width="stretch",
            column_config={"Set on": st.column_config.DatetimeColumn(format="DD MMM YYYY, HH:mm")},
        )
        for column, override in zip(st.columns(len(fields)), existing.values(), strict=False):
            label = OVERRIDE_INPUTS[override.field][0]
            if column.button(f"Remove override: {label}", key=f"remove_{override.field.value}"):
                state.get_repo().delete_override(listing.id, override.field)
                st.rerun()
    else:
        st.info("No overrides for this listing.")


def main() -> None:
    st.title("Detail view")
    assumptions = state.get_assumptions()
    market = state.load_market(assumptions)
    if not market.of_type(OfferType.KAUF):
        state.show_empty_database_hint()
        return

    listing = _pick_listing(market)
    evaluation = state.evaluate_buy_listing(listing, market, assumptions)
    _header(evaluation)
    _kpis(evaluation)

    tab_calc, tab_rent, tab_overrides, tab_history, tab_data = st.tabs(
        ["Calculation", "Rent estimate", "Overrides", "Price history", "Property data"]
    )
    with tab_overrides:
        _overrides(evaluation, market)
    with tab_calc:
        _calculation(evaluation, assumptions)
    with tab_rent:
        _rent_estimate(evaluation)
    with tab_history:
        _history(evaluation, market)
    with tab_data:
        _property_data(evaluation)


main()
