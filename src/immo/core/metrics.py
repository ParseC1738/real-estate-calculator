"""Investment metrics (SPEC §6) as pure functions.

"Pure" means: the result depends only on the arguments, and nothing outside is read or
changed (no database, no files, no clock). That is why these functions are trivial to
test with hand-calculated numbers, and why changed assumptions take effect immediately:
the UI simply calls them again.

Conventions: money in EUR as float (rounded only for display), percentages as 5.2.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from immo.core.assumptions import Assumptions, Threshold
from immo.core.models import Listing, OfferType, PropertyType, ValueOrigin

YIELD_TYPES = (PropertyType.ETW, PropertyType.HAUS, PropertyType.MFH)


class Indicator(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class RentInput(BaseModel):
    """The monthly cold rent used for the calculation, with its origin."""

    value_month: float
    origin: ValueOrigin


class PurchaseCosts(BaseModel):
    """Kaufnebenkosten, itemised so the UI can show every step."""

    transfer_tax_pct: float
    transfer_tax: float
    notary_land_registry_pct: float
    notary_land_registry: float
    commission_pct: float
    commission: float
    # ACTUAL = from the listing, ESTIMATED = default commission from the assumptions
    commission_origin: ValueOrigin
    total_pct: float
    total: float


class BuyMetrics(BaseModel):
    """All metrics of one KAUF listing. `None` means "not applicable / not computable"."""

    property_type: PropertyType
    price: float
    price_origin: ValueOrigin = ValueOrigin.ACTUAL
    area_m2: float | None = None  # living area, or plot area for GRUNDSTUECK
    area_origin: ValueOrigin = ValueOrigin.ACTUAL

    # §6.2 all KAUF listings
    price_per_m2: float | None = None
    area_avg_price_per_m2: float | None = None
    price_vs_area_pct: float | None = None  # negative = cheaper than the area
    purchase_costs: PurchaseCosts
    total_investment: float

    # §6.3 ETW, HAUS, MFH
    rent_month: float | None = None
    rent_origin: ValueOrigin | None = None
    annual_cold_rent: float | None = None
    gross_yield_pct: float | None = None
    price_to_rent_factor: float | None = None
    non_recoverable_costs: float | None = None
    maintenance_costs: float | None = None
    vacancy_costs: float | None = None
    net_operating_income: float | None = None
    net_yield_pct: float | None = None
    equity: float | None = None
    loan: float | None = None
    annuity_month: float | None = None
    cashflow_month_pretax: float | None = None
    cash_on_cash_pct: float | None = None

    # MFH only
    rent_per_unit: float | None = None
    rent_upside_pct: float | None = None

    # §6.4 GRUNDSTUECK
    land_value_m2: float | None = None
    price_vs_land_value_pct: float | None = None

    # §6.6
    indicator: Indicator | None = None
    notes: list[str] = []


class RentListingMetrics(BaseModel):
    """Metrics of one MIETE listing (SPEC §6.5)."""

    rent_per_m2: float | None = None
    mietspiegel_rent_m2: float | None = None
    rent_vs_mietspiegel_pct: float | None = None
    area_rent_m2: float | None = None
    rent_vs_area_pct: float | None = None


# --- small building blocks -------------------------------------------------------------


def pct_diff(value: float | None, reference: float | None) -> float | None:
    """How far `value` is above (+) or below (-) `reference`, in percent."""
    if value is None or reference is None or reference == 0:
        return None
    return (value - reference) / reference * 100


def price_per_m2(listing: Listing) -> float | None:
    """Price per m² of living area; per m² of plot area for GRUNDSTUECK."""
    area = (
        listing.plot_area_m2
        if listing.property_type is PropertyType.GRUNDSTUECK
        else listing.living_area_m2
    )
    return listing.price / area if area else None


def purchase_costs(
    price: float, city: str, commission_pct: float | None, assumptions: Assumptions
) -> PurchaseCosts:
    """Kaufnebenkosten = price × (transfer tax + notary/land registry + commission).

    `commission_pct=None` means the listing gives no value: the default is used and the
    result is marked as ESTIMATED. `0` is a real value (no commission).
    """
    tax_pct = assumptions.transfer_tax_for(city)
    notary_pct = assumptions.notary_land_registry_pct
    if commission_pct is None:
        commission, origin = assumptions.default_commission_pct, ValueOrigin.ESTIMATED
    else:
        commission, origin = commission_pct, ValueOrigin.ACTUAL
    total_pct = tax_pct + notary_pct + commission
    return PurchaseCosts(
        transfer_tax_pct=tax_pct,
        transfer_tax=price * tax_pct / 100,
        notary_land_registry_pct=notary_pct,
        notary_land_registry=price * notary_pct / 100,
        commission_pct=commission,
        commission=price * commission / 100,
        commission_origin=origin,
        total_pct=total_pct,
        total=price * total_pct / 100,
    )


def annuity_month(loan: float, interest_rate_pct: float, repayment_pct: float) -> float:
    """Monthly payment of an annuity loan: (interest + initial repayment) per year / 12."""
    return loan * (interest_rate_pct + repayment_pct) / 100 / 12


def traffic_light(value: float | None, threshold: Threshold | None) -> Indicator | None:
    if value is None or threshold is None:
        return None
    if value >= threshold.green_min:
        return Indicator.GREEN
    if value >= threshold.yellow_min:
        return Indicator.YELLOW
    return Indicator.RED


# --- KAUF ------------------------------------------------------------------------------


def buy_metrics(
    listing: Listing,
    assumptions: Assumptions,
    *,
    rent: RentInput | None = None,
    area_avg_price_per_m2: float | None = None,
    land_value_m2: float | None = None,
    market_rent_month: float | None = None,
    price_origin: ValueOrigin = ValueOrigin.ACTUAL,
    area_origin: ValueOrigin = ValueOrigin.ACTUAL,
) -> BuyMetrics:
    """Calculate all metrics for one KAUF listing.

    Everything that needs data from other listings or references is passed in as a
    plain number (`rent`, `area_avg_price_per_m2`, `land_value_m2`,
    `market_rent_month`), so this function needs no database and no estimate logic.
    """
    if listing.offer_type is not OfferType.KAUF:
        raise ValueError("buy_metrics() only handles KAUF listings")

    is_plot = listing.property_type is PropertyType.GRUNDSTUECK
    ppm2 = price_per_m2(listing)
    costs = purchase_costs(listing.price, listing.city, listing.commission_pct, assumptions)
    total_investment = listing.price + costs.total

    result = BuyMetrics(
        property_type=listing.property_type,
        price=listing.price,
        price_origin=price_origin,
        area_m2=listing.plot_area_m2 if is_plot else listing.living_area_m2,
        area_origin=area_origin,
        price_per_m2=ppm2,
        area_avg_price_per_m2=area_avg_price_per_m2,
        price_vs_area_pct=pct_diff(ppm2, area_avg_price_per_m2),
        purchase_costs=costs,
        total_investment=total_investment,
    )

    if is_plot:
        # §6.4: a plot produces no rent, so there are no yield metrics.
        result.land_value_m2 = land_value_m2
        result.price_vs_land_value_pct = pct_diff(ppm2, land_value_m2)
        return result

    if rent is None:
        result.notes.append("No rent available (no actual rent and no estimate possible).")
        return result

    annual_rent = rent.value_month * 12
    non_recoverable = annual_rent * assumptions.non_recoverable_costs_pct_of_rent / 100
    if listing.living_area_m2:
        maintenance = assumptions.maintenance_eur_m2_year * listing.living_area_m2
    else:
        maintenance = 0.0
        result.notes.append("Living area unknown: maintenance reserve not included.")
    vacancy = annual_rent * assumptions.vacancy_pct / 100
    noi = annual_rent - non_recoverable - maintenance - vacancy

    equity = total_investment * assumptions.equity_pct / 100
    loan = total_investment - equity
    annuity = annuity_month(loan, assumptions.interest_rate_pct, assumptions.repayment_pct)
    cashflow = noi / 12 - annuity

    result.rent_month = rent.value_month
    result.rent_origin = rent.origin
    result.annual_cold_rent = annual_rent
    result.gross_yield_pct = annual_rent / listing.price * 100
    result.price_to_rent_factor = listing.price / annual_rent
    result.non_recoverable_costs = non_recoverable
    result.maintenance_costs = maintenance
    result.vacancy_costs = vacancy
    result.net_operating_income = noi
    result.net_yield_pct = noi / total_investment * 100
    result.equity = equity
    result.loan = loan
    result.annuity_month = annuity
    result.cashflow_month_pretax = cashflow
    # with 0 % equity the return on equity is undefined (division by zero)
    result.cash_on_cash_pct = cashflow * 12 / equity * 100 if equity > 0 else None
    result.indicator = traffic_light(
        result.gross_yield_pct, assumptions.traffic_light.get("gross_yield_pct")
    )

    if listing.property_type is PropertyType.MFH:
        if listing.units:
            result.rent_per_unit = rent.value_month / listing.units
        if listing.actual_rent_month and market_rent_month is not None:
            result.rent_upside_pct = pct_diff(market_rent_month, listing.actual_rent_month)

    return result


# --- MIETE -----------------------------------------------------------------------------


def rent_listing_metrics(
    listing: Listing,
    *,
    mietspiegel_rent_m2: float | None = None,
    area_rent_m2: float | None = None,
) -> RentListingMetrics:
    """Metrics for one MIETE listing: rent per m² compared with Mietspiegel and area."""
    if listing.offer_type is not OfferType.MIETE:
        raise ValueError("rent_listing_metrics() only handles MIETE listings")
    rent_m2 = listing.price / listing.living_area_m2 if listing.living_area_m2 else None
    return RentListingMetrics(
        rent_per_m2=rent_m2,
        mietspiegel_rent_m2=mietspiegel_rent_m2,
        rent_vs_mietspiegel_pct=pct_diff(rent_m2, mietspiegel_rent_m2),
        area_rent_m2=area_rent_m2,
        rent_vs_area_pct=pct_diff(rent_m2, area_rent_m2),
    )
