"""Assumptions: edit every assumption, see the effect at once, save profiles (SPEC §8.3)."""

import streamlit as st

from immo.core.assumptions import (
    Assumptions,
    BlendWeights,
    RentStrategy,
    Threshold,
    TransferTax,
    list_profiles,
    load_assumptions,
    load_profile,
    save_profile,
)
from immo.paths import profiles_dir
from immo.ui import formatting as fmt
from immo.ui import state
from immo.ui.tables import buy_table

GENERATION_KEY = "assumptions_generation"
STRATEGY_HELP = {
    RentStrategy.MARKET: "market – own rental listings, falling back to the price map",
    RentStrategy.MIETSPIEGEL: "mietspiegel – official rent table (conservative)",
    RentStrategy.BLEND: "blend – weighted average of market and Mietspiegel",
}


def _replace(assumptions: Assumptions) -> None:
    """Swap in a whole new set of assumptions (profile loaded / reset).

    Streamlit widgets remember their value under their key. Bumping the "generation"
    changes every key, so all widgets start again from the new assumptions.
    """
    state.set_assumptions(assumptions)
    st.session_state[GENERATION_KEY] = st.session_state.get(GENERATION_KEY, 0) + 1


def _edit(current: Assumptions) -> Assumptions:
    generation = st.session_state.get(GENERATION_KEY, 0)

    def pct(label: str, value: float, name: str, max_value: float = 100.0, step: float = 0.1):
        return st.number_input(
            label, 0.0, max_value, float(value), step, format="%.2f", key=f"a{generation}_{name}"
        )

    costs, financing, running = st.columns(3)
    with costs:
        st.subheader("Purchase costs")
        tax_berlin = pct("Transfer tax Berlin (%)", current.transfer_tax_pct.berlin, "tax_be")
        tax_brandenburg = pct(
            "Transfer tax Brandenburg (%)", current.transfer_tax_pct.brandenburg, "tax_bb"
        )
        notary = pct("Notary + land registry (%)", current.notary_land_registry_pct, "notary")
        commission = pct(
            "Default broker commission (%)",
            current.default_commission_pct,
            "commission",
            step=0.01,
        )
        st.caption("Tax rates must be checked against official sources before real use.")
    with financing:
        st.subheader("Financing")
        equity = st.slider(
            "Equity (% of total investment)",
            0.0, 100.0, float(current.equity_pct), 1.0, key=f"a{generation}_equity",
        )  # fmt: skip
        interest = st.slider(
            "Interest rate (% per year)",
            0.0, 10.0, float(current.interest_rate_pct), 0.05, key=f"a{generation}_interest",
        )  # fmt: skip
        repayment = st.slider(
            "Initial repayment (% per year)",
            0.0, 10.0, float(current.repayment_pct), 0.1, key=f"a{generation}_repayment",
        )  # fmt: skip
    with running:
        st.subheader("Running costs")
        non_recoverable = st.slider(
            "Non-recoverable costs (% of rent)",
            0.0, 50.0, float(current.non_recoverable_costs_pct_of_rent), 1.0,
            key=f"a{generation}_nonrec",
        )  # fmt: skip
        maintenance = st.number_input(
            "Maintenance reserve (€ per m² and year)",
            0.0, 100.0, float(current.maintenance_eur_m2_year), 0.5,
            key=f"a{generation}_maintenance",
        )  # fmt: skip
        vacancy = st.slider(
            "Vacancy (% of rent)",
            0.0, 20.0, float(current.vacancy_pct), 0.5, key=f"a{generation}_vacancy",
        )  # fmt: skip

    rent, signal = st.columns([2, 1])
    with rent:
        st.subheader("Rent estimate")
        strategies = list(RentStrategy)
        strategy = st.radio(
            "Strategy",
            strategies,
            index=strategies.index(current.rent_strategy),
            format_func=STRATEGY_HELP.get,
            key=f"a{generation}_strategy",
        )
        weights = current.rent_blend_weights
        market_share = st.slider(
            "Blend: weight of the market value (%) – the rest is the Mietspiegel",
            0, 100, round(weights.market / (weights.market + weights.mietspiegel) * 100), 5,
            key=f"a{generation}_blend",
            disabled=strategy is not RentStrategy.BLEND,
        )  # fmt: skip
        min_samples = st.number_input(
            "Minimum number of own listings for a median",
            1, 100, current.min_samples_own_listings, 1, key=f"a{generation}_samples",
        )  # fmt: skip
    with signal:
        st.subheader("Signal (gross yield)")
        threshold = current.traffic_light.get(
            "gross_yield_pct", Threshold(green_min=5.0, yellow_min=3.5)
        )
        green = pct("🟢 good from (%)", threshold.green_min, "green", max_value=30.0)
        yellow = pct("🟡 fair from (%)", min(threshold.yellow_min, green), "yellow", max_value=30.0)
        if yellow > green:
            st.warning("'fair' must not be above 'good'; using the same value for both.")
            yellow = green

    return Assumptions(
        transfer_tax_pct=TransferTax(berlin=tax_berlin, brandenburg=tax_brandenburg),
        notary_land_registry_pct=notary,
        default_commission_pct=commission,
        equity_pct=equity,
        interest_rate_pct=interest,
        repayment_pct=repayment,
        non_recoverable_costs_pct_of_rent=non_recoverable,
        maintenance_eur_m2_year=maintenance,
        vacancy_pct=vacancy,
        rent_strategy=strategy,
        rent_blend_weights=BlendWeights(
            market=market_share / 100, mietspiegel=1 - market_share / 100
        ),
        min_samples_own_listings=int(min_samples),
        traffic_light={
            **current.traffic_light,
            "gross_yield_pct": Threshold(green_min=green, yellow_min=yellow),
        },
    )


def _effect(assumptions: Assumptions) -> None:
    """Live preview: the same numbers the overview shows, with the current assumptions."""
    market = state.load_market(assumptions)
    if market.is_empty:
        return
    table = buy_table(state.evaluate_all_buy(market, assumptions))
    table = table[table["is_active"] & table["gross_yield_pct"].notna()]
    if table.empty:
        return
    st.subheader("Effect on the active listings")
    cols = st.columns(5)
    cols[0].metric("Median gross yield", fmt.pct(table["gross_yield_pct"].median(), 2))
    cols[1].metric("Median net yield", fmt.pct(table["net_yield_pct"].median(), 2))
    cols[2].metric("Median cash flow / month", fmt.eur(table["cashflow_month"].median()))
    cols[3].metric("Positive cash flow", f"{int((table['cashflow_month'] > 0).sum())} listings")
    cols[4].metric(
        "🟢 good signal", f"{int(table['signal'].eq(fmt.SIGNAL_LABEL['green']).sum())} listings"
    )
    st.caption("Changes apply immediately on every page; they last until you close the tab.")


def _profiles(assumptions: Assumptions) -> None:
    st.subheader("Profiles")
    directory = profiles_dir()
    save, load, reset = st.columns(3)
    with save:
        name = st.text_input("Save current values as", placeholder="e.g. cautious")
        if st.button("💾 Save profile", disabled=not name.strip()):
            try:
                path = save_profile(assumptions, name, directory)
                st.success(f"Saved as `{path.name}`.")
            except ValueError as error:
                st.error(str(error))
    with load:
        profiles = list_profiles(directory)
        chosen = st.selectbox("Saved profiles", profiles, index=None, placeholder="choose …")
        if st.button("📂 Load profile", disabled=chosen is None):
            _replace(load_profile(chosen, directory))
            st.rerun()
    with reset:
        st.markdown("Defaults from `config/assumptions.yaml`")
        if st.button("↩️ Reset to defaults"):
            _replace(load_assumptions())
            st.rerun()


def main() -> None:
    st.title("Assumptions")
    st.caption(
        "Everything the calculations assume. Nothing here is stored with a listing: all "
        "metrics are recalculated from these values each time a page is shown."
    )
    assumptions = _edit(state.get_assumptions())
    state.set_assumptions(assumptions)
    st.divider()
    _effect(assumptions)
    st.divider()
    _profiles(assumptions)


main()
