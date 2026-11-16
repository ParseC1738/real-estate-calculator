import pytest
import yaml
from pydantic import ValidationError

from immo.core.assumptions import (
    Assumptions,
    RentStrategy,
    list_profiles,
    load_assumptions,
    load_profile,
    save_assumptions,
    save_profile,
)
from immo.paths import DEFAULT_ASSUMPTIONS_PATH


def test_defaults_match_the_spec():
    a = Assumptions()
    assert a.transfer_tax_pct.berlin == 6.0
    assert a.transfer_tax_pct.brandenburg == 6.5
    assert a.notary_land_registry_pct == 2.0
    assert a.default_commission_pct == 3.57
    assert a.equity_pct == 20
    assert a.interest_rate_pct == 3.8
    assert a.repayment_pct == 2.0
    assert a.non_recoverable_costs_pct_of_rent == 15
    assert a.maintenance_eur_m2_year == 12
    assert a.vacancy_pct == 2
    assert (a.rent_blend_weights.market, a.rent_blend_weights.mietspiegel) == (0.6, 0.4)
    assert a.min_samples_own_listings == 5
    assert a.rent_strategy is RentStrategy.BLEND


def test_shipped_yaml_equals_the_code_defaults():
    """config/assumptions.yaml and the model defaults must never drift apart."""
    assert load_assumptions(DEFAULT_ASSUMPTIONS_PATH) == Assumptions()


def test_missing_file_gives_defaults(tmp_path):
    assert load_assumptions(tmp_path / "nope.yaml") == Assumptions()


def test_partial_yaml_keeps_other_defaults(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("interest_rate_pct: 4.5\ntransfer_tax_pct:\n  berlin: 6.5\n")
    a = load_assumptions(path)
    assert a.interest_rate_pct == 4.5
    assert a.transfer_tax_pct.berlin == 6.5
    assert a.transfer_tax_pct.brandenburg == 6.5
    assert a.equity_pct == 20


def test_typo_in_yaml_is_an_error(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("intrest_rate_pct: 4.5\n")
    with pytest.raises(ValidationError):
        load_assumptions(path)


@pytest.mark.parametrize(
    "data",
    [
        {"equity_pct": 150},
        {"vacancy_pct": -1},
        {"min_samples_own_listings": 0},
        {"rent_blend_weights": {"market": 0, "mietspiegel": 0}},
        {"traffic_light": {"gross_yield_pct": {"green_min": 3, "yellow_min": 5}}},
        {"rent_strategy": "guess"},
    ],
)
def test_invalid_values_are_rejected(data):
    with pytest.raises(ValidationError):
        Assumptions.model_validate(data)


def test_transfer_tax_depends_on_the_federal_state():
    a = Assumptions()
    assert a.transfer_tax_for("Berlin") == 6.0
    assert a.transfer_tax_for(" berlin ") == 6.0
    assert a.transfer_tax_for("Potsdam") == 6.5
    assert a.transfer_tax_for("Brandenburg an der Havel") == 6.5


def test_save_and_load_round_trip(tmp_path):
    a = Assumptions(interest_rate_pct=4.2, rent_strategy="market")
    path = tmp_path / "sub" / "a.yaml"
    save_assumptions(a, path)
    assert load_assumptions(path) == a
    # the file is plain, human-readable YAML
    assert yaml.safe_load(path.read_text())["rent_strategy"] == "market"


def test_profiles(tmp_path):
    assert list_profiles(tmp_path) == []
    path = save_profile(Assumptions(equity_pct=30), "Vorsichtig 2026!", tmp_path)
    save_profile(Assumptions(equity_pct=10), "aggressive", tmp_path)

    assert path.name == "vorsichtig-2026.yaml"
    assert list_profiles(tmp_path) == ["aggressive", "vorsichtig-2026"]
    assert load_profile("Vorsichtig 2026!", tmp_path).equity_pct == 30
    assert load_profile("vorsichtig-2026", tmp_path).equity_pct == 30
    with pytest.raises(FileNotFoundError):
        load_profile("missing", tmp_path)
    with pytest.raises(ValueError):
        save_profile(Assumptions(), "!!!", tmp_path)
