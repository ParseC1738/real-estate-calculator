import pytest
from pydantic import ValidationError

from immo.core.models import OfferType, PropertyType, SearchQuery
from immo.core.sample_data import HISTORY_ROUNDS, SampleWorld
from immo.sources.base import RawListing, SourceAdapter
from immo.sources.csv_import import TEMPLATE_CSV, CsvAdapter, decode_csv, parse_number
from immo.sources.sample import SampleAdapter
from tests.conftest import T0

EVERYTHING = SearchQuery()


# --- protocol ----------------------------------------------------------------------


def test_adapters_implement_the_protocol():
    assert isinstance(SampleAdapter(), SourceAdapter)
    assert isinstance(CsvAdapter(""), SourceAdapter)
    assert not isinstance(object(), SourceAdapter)


# --- sample adapter ----------------------------------------------------------------


@pytest.fixture(scope="module")
def world() -> SampleWorld:
    return SampleWorld(seed=42)


def test_sample_adapter_round_trip_equals_the_generator(world):
    """fetch + normalize must give back exactly what the generator produced."""
    adapter = SampleAdapter(round_index=3, world=world)
    expected = {x.source_listing_id: x for x in world.listings_at(3, T0)}
    raws = list(adapter.fetch(EVERYTHING))
    assert len(raws) == len(expected)
    ignore = {"first_seen", "last_seen", "raw"}
    for raw in raws:
        listing = adapter.normalize(raw)
        assert listing.model_dump(exclude=ignore) == expected[raw.source_listing_id].model_dump(
            exclude=ignore
        )
        assert listing.raw == raw.data  # the original data is kept for debugging


def test_sample_adapter_applies_the_query(world):
    adapter = SampleAdapter(world=world)
    query = SearchQuery(cities=["Potsdam"], property_types=["ETW"], offer_type="KAUF")
    listings = [adapter.normalize(raw) for raw in adapter.fetch(query)]
    assert listings
    assert {(x.city, x.property_type, x.offer_type) for x in listings} == {
        ("Potsdam", PropertyType.ETW, OfferType.KAUF)
    }


def test_sample_adapter_rounds_differ(world):
    def ids(round_index):
        adapter = SampleAdapter(round_index=round_index, world=world)
        return {raw.source_listing_id for raw in adapter.fetch(EVERYTHING)}

    assert ids(HISTORY_ROUNDS) - ids(HISTORY_ROUNDS - 1)  # new listings appear
    assert ids(HISTORY_ROUNDS - 1) - ids(HISTORY_ROUNDS + 5)  # and some disappear


# --- number parsing ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("250000", 250_000),
        ("250000.5", 250_000.5),
        ("250.000", 250_000),  # German thousands separator
        ("1.250.000", 1_250_000),
        ("250.000,50", 250_000.5),
        ("1,234.56", 1234.56),  # English style
        ("62,5", 62.5),
        ("62.5", 62.5),
        ("3.57", 3.57),
        ("1.200 €", 1200),
        ("78,5 m²", 78.5),
        ("-5", -5),
    ],
)
def test_parse_number(text, expected):
    assert parse_number(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "abc", "€", "1.2.3,4,5"])
def test_parse_number_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_number(text)


# --- CSV adapter -------------------------------------------------------------------


def normalized(text: str):
    adapter = CsvAdapter(text)
    return [adapter.normalize(raw) for raw in adapter.fetch(EVERYTHING)]


def test_template_csv_is_valid_and_covers_all_types():
    listings = normalized(TEMPLATE_CSV)
    assert [x.source_listing_id for x in listings] == ["my-001", "my-002", "my-003", "my-004"]
    assert all(x.source == "csv" for x in listings)

    flat, mfh, plot, rental = listings
    assert (flat.price, flat.living_area_m2, flat.rooms) == (329_000, 78.5, 3)
    assert (flat.hausgeld_month, flat.commission_pct, flat.is_rented) == (310, 3.57, False)
    assert flat.plot_area_m2 is None and flat.url is None  # empty cell = unknown
    assert (mfh.property_type, mfh.units, mfh.actual_rent_month) == (PropertyType.MFH, 6, 3650)
    assert mfh.is_rented is True
    assert (plot.property_type, plot.living_area_m2, plot.plot_area_m2) == (
        PropertyType.GRUNDSTUECK,
        None,
        540,
    )
    assert (rental.offer_type, rental.price) == (OfferType.MIETE, 890)


def test_shipped_example_file_matches_the_template():
    from immo.paths import DATA_DIR

    assert (DATA_DIR / "examples" / "listings_example.csv").read_text("utf-8") == TEMPLATE_CSV


def test_comma_separated_english_numbers_and_lowercase_enums():
    text = (
        "source_listing_id,offer_type,property_type,title,city,postal_code,price,living_area_m2\n"
        'a1,kauf,etw,"Flat, with a comma",Berlin,10115,250000.50,62.5\n'
    )
    (listing,) = normalized(text)
    assert listing.title == "Flat, with a comma"
    assert (listing.price, listing.living_area_m2) == (250_000.5, 62.5)
    assert listing.property_type is PropertyType.ETW


def test_unknown_columns_are_kept_in_raw_only():
    text = (
        "source_listing_id;offer_type;property_type;title;city;postal_code;price;balkon\n"
        "a1;KAUF;ETW;Flat;Berlin;10115;250000;ja\n"
    )
    (listing,) = normalized(text)
    assert listing.raw["balkon"] == "ja"
    assert not hasattr(listing, "balkon")


def test_missing_required_column_fails_the_whole_fetch():
    with pytest.raises(ValueError, match="price"):
        list(CsvAdapter("source_listing_id;title\na1;Flat\n").fetch(EVERYTHING))


def test_bad_rows_raise_on_normalize_with_the_column_name():
    header = "source_listing_id;offer_type;property_type;title;city;postal_code;price\n"
    adapter = CsvAdapter(
        header
        + "ok;KAUF;ETW;Flat;Berlin;10115;250000\n"
        + "bad-number;KAUF;ETW;Flat;Berlin;10115;teuer\n"
        + "bad-type;KAUF;SCHLOSS;Flat;Berlin;10115;250000\n"
        + "no-price;KAUF;ETW;Flat;Berlin;10115;\n"
        + ";KAUF;ETW;No id;Berlin;10115;250000\n"
        + ";;;;;;\n"  # empty line: skipped
    )
    raws = list(adapter.fetch(EVERYTHING))
    assert len(raws) == 5
    assert adapter.normalize(raws[0]).price == 250_000
    with pytest.raises(ValueError, match="price: not a number"):
        adapter.normalize(raws[1])
    with pytest.raises(ValidationError):
        adapter.normalize(raws[2])
    with pytest.raises(ValidationError):
        adapter.normalize(raws[3])
    assert raws[4].source_listing_id == "(line 6)"
    with pytest.raises(ValueError, match="source_listing_id"):
        adapter.normalize(raws[4])


def test_from_path_and_encodings(tmp_path):
    path = tmp_path / "listings.csv"
    path.write_bytes(TEMPLATE_CSV.encode("utf-8-sig"))  # Excel adds a BOM
    adapter = CsvAdapter.from_path(path)
    assert len(list(adapter.fetch(EVERYTHING))) == 4
    assert decode_csv("Görden;Baugrundstück".encode("cp1252")) == "Görden;Baugrundstück"


def test_raw_listing_defaults():
    assert RawListing(source="x", source_listing_id="1").data == {}
