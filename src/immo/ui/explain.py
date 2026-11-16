"""Calculation steps for the detail view: every metric with the numbers that went in."""

from __future__ import annotations

from dataclasses import dataclass

from immo.core.assumptions import Assumptions
from immo.core.metrics import BuyMetrics
from immo.core.models import PropertyType
from immo.ui.formatting import eur, num, origin, pct


@dataclass(frozen=True)
class CalcStep:
    label: str
    formula: str
    result: str


def explain_buy(m: BuyMetrics, a: Assumptions) -> list[CalcStep]:
    """The steps from price to cash flow, in the order they build on each other."""
    costs = m.purchase_costs
    is_plot = m.property_type is PropertyType.GRUNDSTUECK
    steps = []
    if m.price_per_m2 is not None:
        area_name = "plot area" if is_plot else "living area"
        steps.append(
            CalcStep(
                "Price per m²",
                f"{eur(m.price)} ÷ {num(m.area_m2, 1, 'm²')} {area_name}",
                eur(m.price_per_m2),
            )
        )
    if m.price_vs_area_pct is not None:
        steps.append(
            CalcStep(
                "Price vs. area",
                f"({eur(m.price_per_m2)} − {eur(m.area_avg_price_per_m2)}) "
                f"÷ {eur(m.area_avg_price_per_m2)}",
                pct(m.price_vs_area_pct, signed=True),
            )
        )
    if m.price_vs_land_value_pct is not None:
        steps.append(
            CalcStep(
                "Price vs. land value (BORIS)",
                f"({eur(m.price_per_m2)} − {eur(m.land_value_m2)}) ÷ {eur(m.land_value_m2)}",
                pct(m.price_vs_land_value_pct, signed=True),
            )
        )
    steps.append(
        CalcStep(
            "Purchase costs (Kaufnebenkosten)",
            f"{eur(m.price)} × ({pct(costs.transfer_tax_pct, 2)} transfer tax "
            f"+ {pct(costs.notary_land_registry_pct, 2)} notary/land registry "
            f"+ {pct(costs.commission_pct, 2)} commission, {origin(costs.commission_origin)})",
            eur(costs.total),
        )
    )
    steps.append(
        CalcStep(
            "Total investment", f"{eur(m.price)} + {eur(costs.total)}", eur(m.total_investment)
        )
    )
    if m.annual_cold_rent is None:
        return steps

    steps += [
        CalcStep(
            "Annual cold rent",
            f"{eur(m.rent_month)} ({origin(m.rent_origin)}) × 12",
            eur(m.annual_cold_rent),
        ),
        CalcStep(
            "Gross yield (Bruttomietrendite)",
            f"{eur(m.annual_cold_rent)} ÷ {eur(m.price)}",
            pct(m.gross_yield_pct, 2),
        ),
        CalcStep(
            "Price-to-rent factor (Kaufpreisfaktor)",
            f"{eur(m.price)} ÷ {eur(m.annual_cold_rent)}",
            num(m.price_to_rent_factor, 1),
        ),
        CalcStep(
            "Non-recoverable costs",
            f"{eur(m.annual_cold_rent)} × {pct(a.non_recoverable_costs_pct_of_rent)}",
            eur(m.non_recoverable_costs),
        ),
        CalcStep(
            "Maintenance reserve",
            f"{eur(a.maintenance_eur_m2_year, 2)} × {num(m.area_m2, 1, 'm²')}"
            if m.area_m2
            else "living area unknown",
            eur(m.maintenance_costs),
        ),
        CalcStep(
            "Vacancy allowance",
            f"{eur(m.annual_cold_rent)} × {pct(a.vacancy_pct)}",
            eur(m.vacancy_costs),
        ),
        CalcStep(
            "Net operating income",
            f"{eur(m.annual_cold_rent)} − {eur(m.non_recoverable_costs)} "
            f"− {eur(m.maintenance_costs)} − {eur(m.vacancy_costs)}",
            eur(m.net_operating_income),
        ),
        CalcStep(
            "Net yield",
            f"{eur(m.net_operating_income)} ÷ {eur(m.total_investment)}",
            pct(m.net_yield_pct, 2),
        ),
        CalcStep("Equity", f"{eur(m.total_investment)} × {pct(a.equity_pct)}", eur(m.equity)),
        CalcStep("Loan", f"{eur(m.total_investment)} − {eur(m.equity)}", eur(m.loan)),
        CalcStep(
            "Loan payment per month",
            f"{eur(m.loan)} × ({pct(a.interest_rate_pct, 2)} interest "
            f"+ {pct(a.repayment_pct, 2)} repayment) ÷ 12",
            eur(m.annuity_month, 2),
        ),
        CalcStep(
            "Cash flow per month (before tax)",
            f"{eur(m.net_operating_income)} ÷ 12 − {eur(m.annuity_month, 2)}",
            eur(m.cashflow_month_pretax, 2),
        ),
    ]
    if m.cash_on_cash_pct is not None:
        steps.append(
            CalcStep(
                "Cash-on-cash return",
                f"{eur(m.cashflow_month_pretax, 2)} × 12 ÷ {eur(m.equity)}",
                pct(m.cash_on_cash_pct, 2),
            )
        )
    if m.rent_per_unit is not None:
        steps.append(
            CalcStep("Rent per unit", f"{eur(m.rent_month)} ÷ units", eur(m.rent_per_unit))
        )
    if m.rent_upside_pct is not None:
        steps.append(
            CalcStep(
                "Rent upside",
                "(estimated market rent − actual rent) ÷ actual rent",
                pct(m.rent_upside_pct, signed=True),
            )
        )
    return steps
