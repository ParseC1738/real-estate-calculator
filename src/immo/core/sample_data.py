"""Reproducible sample data (SPEC §7): listings with a simulated history + references.

How it works
------------
The generator does not produce one static list. It simulates a small *market over time*:
every listing gets a "lifecycle" (when it appears, when its price changes, when it goes
offline, whether it comes back). `SampleWorld.listings_at(round)` then answers the
question "what would a fetch see in this round?".

Seeding the database replays the rounds through the normal upsert logic, so the sample
history is created by exactly the same code that will later process real fetches.

Everything is derived from one `random.Random(seed)`: same seed, same data. All values
are invented; the area references are marked as sample data in their note.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from immo.core.models import (
    AreaMetric,
    AreaReference,
    Listing,
    OfferType,
    PropertyType,
    ReferenceSource,
    city_key,
    district_key,
)

SAMPLE_SOURCE = "sample"
DEFAULT_SEED = 42
HISTORY_ROUNDS = 12  # simulated weekly fetches before "now" (the last one is "now")
FUTURE_ROUNDS = 12  # further rounds, so later "Fetch now" clicks still see changes
ROUND_INTERVAL_DAYS = 7
SAMPLE_NOTE = "SAMPLE DATA - invented value, not from an official source"

_ID_NAMESPACE = uuid.UUID("6f1d3c1e-7a51-4b0e-9d43-1f2a5c8e9b10")


@dataclass(frozen=True)
class District:
    name: str
    postal_code: str
    factor: float  # price level relative to the city average (1.0 = average)


@dataclass(frozen=True)
class CityProfile:
    name: str
    weight: float  # share of all listings
    lat: float
    lon: float
    rent_m2: tuple[float, float]  # asking rent, EUR/m² (SPEC §7)
    flat_price_m2: tuple[float, float]  # flat purchase price, EUR/m² (SPEC §7)
    land_value_m2: tuple[float, float]
    districts: tuple[District, ...]


CITIES: tuple[CityProfile, ...] = (
    CityProfile(
        name="Brandenburg an der Havel",
        weight=0.30,
        lat=52.412,
        lon=12.556,
        rent_m2=(7.0, 10.0),
        flat_price_m2=(1800.0, 3000.0),
        land_value_m2=(70.0, 190.0),
        districts=(
            District("Altstadt", "14770", 1.08),
            District("Neustadt", "14776", 1.10),
            District("Dominsel", "14776", 1.12),
            District("Nord", "14770", 0.95),
            District("Hohenstücken", "14772", 0.85),
            District("Görden", "14772", 0.97),
            District("Plaue", "14774", 0.92),
            District("Kirchmöser", "14774", 0.90),
        ),
    ),
    CityProfile(
        name="Potsdam",
        weight=0.25,
        lat=52.396,
        lon=13.058,
        rent_m2=(11.0, 16.0),
        flat_price_m2=(3500.0, 5500.0),
        land_value_m2=(350.0, 900.0),
        districts=(
            District("Innenstadt", "14467", 1.12),
            District("Babelsberg", "14482", 1.08),
            District("Potsdam West", "14471", 1.05),
            District("Bornstedt", "14469", 1.02),
            District("Waldstadt", "14478", 0.90),
            District("Drewitz", "14480", 0.86),
            District("Am Stern", "14480", 0.90),
            District("Golm", "14476", 0.96),
        ),
    ),
    CityProfile(
        name="Berlin",
        weight=0.45,
        lat=52.520,
        lon=13.405,
        rent_m2=(10.0, 20.0),
        flat_price_m2=(3500.0, 7000.0),
        land_value_m2=(450.0, 1500.0),
        districts=(
            District("Mitte", "10115", 1.22),
            District("Prenzlauer Berg", "10405", 1.18),
            District("Friedrichshain", "10243", 1.12),
            District("Kreuzberg", "10961", 1.14),
            District("Charlottenburg", "10585", 1.15),
            District("Neukölln", "12043", 0.98),
            District("Pankow", "13187", 1.00),
            District("Steglitz", "12163", 1.00),
            District("Lichtenberg", "10365", 0.90),
            District("Köpenick", "12555", 0.92),
            District("Spandau", "13581", 0.82),
            District("Marzahn", "12679", 0.76),
        ),
    ),
)

_KAUF_TYPES = (
    (PropertyType.ETW, 0.50),
    (PropertyType.HAUS, 0.25),
    (PropertyType.MFH, 0.12),
    (PropertyType.GRUNDSTUECK, 0.13),
)
_MIETE_TYPES = ((PropertyType.ETW, 0.88), (PropertyType.HAUS, 0.12))
_CONDITIONS = (
    ("renovated", 1.10),
    ("well kept", 1.00),
    ("first occupancy", 1.18),
    ("needs renovation", 0.80),
)
_ENERGY_CLASSES = ("A+", "A", "B", "C", "D", "E", "F", "G", "H")
_STREETS = ("Hauptstraße", "Bahnhofstraße", "Gartenweg", "Lindenallee", "Am Park", "Seestraße")
_FLAT_WORDS = ("Helle", "Gemütliche", "Sanierte", "Ruhige", "Zentrale", "Charmante")


@dataclass
class _Lifecycle:
    """One listing over time (internal to the generator)."""

    base: Listing
    appear_round: int
    # round -> factor applied to the price from that round on (0.95 = 5 % cheaper)
    price_changes: dict[int, float] = field(default_factory=dict)
    # half-open intervals [start, end) in which the listing is offline; end None = forever
    offline: list[tuple[int, int | None]] = field(default_factory=list)

    def is_online(self, round_index: int) -> bool:
        if round_index < self.appear_round:
            return False
        return not any(
            start <= round_index and (end is None or round_index < end)
            for start, end in self.offline
        )

    def price_at(self, round_index: int) -> float:
        price = self.base.price
        for change_round in sorted(self.price_changes):
            if change_round <= round_index:
                price *= self.price_changes[change_round]
        step = 500 if self.base.offer_type is OfferType.KAUF else 5
        return max(round(price / step) * step, step)


def round_time(round_index: int, now: datetime) -> datetime:
    """Timestamp of a history round: the last history round happens at `now`."""
    weeks_back = HISTORY_ROUNDS - 1 - round_index
    return now - timedelta(days=weeks_back * ROUND_INTERVAL_DAYS)


class SampleWorld:
    """A deterministic, simulated market. See the module docstring."""

    def __init__(self, seed: int = DEFAULT_SEED, n_kauf: int = 300, n_miete: int = 400) -> None:
        self.seed = seed
        self._rng = random.Random(seed)
        self._counter = 0
        self._lifecycles: list[_Lifecycle] = []

        for offer_type, count, new_per_future_round in (
            (OfferType.KAUF, n_kauf, 3),
            (OfferType.MIETE, n_miete, 5),
        ):
            for _ in range(count):
                self._add_lifecycle(offer_type, self._history_appear_round())
            for future_round in range(HISTORY_ROUNDS, self.total_rounds):
                for _ in range(new_per_future_round):
                    self._add_lifecycle(offer_type, future_round)

    @property
    def total_rounds(self) -> int:
        return HISTORY_ROUNDS + FUTURE_ROUNDS

    # --- public API ----------------------------------------------------------------

    def listings_at(self, round_index: int, seen_at: datetime) -> list[Listing]:
        """All listings a fetch in `round_index` would find (offline ones are missing).

        Rounds beyond the simulated horizon return the final state.
        """
        round_index = min(round_index, self.total_rounds - 1)
        result = []
        for lifecycle in self._lifecycles:
            if not lifecycle.is_online(round_index):
                continue
            result.append(
                lifecycle.base.model_copy(
                    update={
                        "price": lifecycle.price_at(round_index),
                        "first_seen": seen_at,
                        "last_seen": seen_at,
                    }
                )
            )
        return result

    def area_references(self, valid_from: date) -> list[AreaReference]:
        """Invented area statistics for all three cities (city and district level)."""
        references: list[AreaReference] = []

        def add(area_key, metric, source, value, spread, property_type=None):
            references.append(
                AreaReference(
                    area_key=area_key,
                    metric=metric,
                    property_type=property_type,
                    value=round(value, 2),
                    low=round(value * (1 - spread), 2),
                    high=round(value * (1 + spread), 2),
                    source=source,
                    valid_from=valid_from,
                    note=SAMPLE_NOTE,
                )
            )

        for city in CITIES:
            rent_mid = sum(city.rent_m2) / 2
            flat_mid = sum(city.flat_price_m2) / 2
            land_mid = sum(city.land_value_m2) / 2
            areas = [(city_key(city.name), 1.0)] + [
                (district_key(city.name, d.name), d.factor) for d in city.districts
            ]
            for area_key, factor in areas:
                rent_factor = factor**0.6  # rents vary less between districts than prices
                # Mietspiegel = existing rents, clearly below asking rents
                add(area_key, AreaMetric.RENT_M2, ReferenceSource.MIETSPIEGEL,
                    rent_mid * rent_factor * 0.80, 0.15)  # fmt: skip
                add(area_key, AreaMetric.RENT_M2, ReferenceSource.PRICE_MAP,
                    rent_mid * rent_factor * 0.97, 0.12)  # fmt: skip
                add(area_key, AreaMetric.BUY_PRICE_M2, ReferenceSource.PRICE_MAP,
                    flat_mid * factor * 0.98, 0.15, PropertyType.ETW)  # fmt: skip
                add(area_key, AreaMetric.BUY_PRICE_M2, ReferenceSource.PRICE_MAP,
                    flat_mid * factor * 0.88, 0.18, PropertyType.HAUS)  # fmt: skip
                add(area_key, AreaMetric.LAND_VALUE_M2, ReferenceSource.BORIS,
                    land_mid * factor, 0.25)  # fmt: skip
            # the valuation committee publishes city-wide averages per property type
            for property_type, level in (
                (PropertyType.ETW, 0.95),
                (PropertyType.HAUS, 0.85),
                (PropertyType.MFH, 0.62),
            ):
                add(city_key(city.name), AreaMetric.BUY_PRICE_M2,
                    ReferenceSource.GUTACHTERAUSSCHUSS, flat_mid * level, 0.20,
                    property_type)  # fmt: skip
        return references

    # --- lifecycle generation ------------------------------------------------------

    def _history_appear_round(self) -> int:
        """About half of the listings are there from the start, the rest trickle in."""
        if self._rng.random() < 0.5:
            return 0
        return self._rng.randint(1, HISTORY_ROUNDS - 1)

    def _add_lifecycle(self, offer_type: OfferType, appear_round: int) -> None:
        rng = self._rng
        base = self._make_listing(offer_type)
        lifecycle = _Lifecycle(base=base, appear_round=appear_round)
        last_round = self.total_rounds - 1
        is_kauf = offer_type is OfferType.KAUF

        # price changes: mostly drops (KAUF: 1-3 drops for about a quarter of listings)
        later_rounds = list(range(appear_round + 1, last_round + 1))
        history_rounds = [r for r in later_rounds if r < HISTORY_ROUNDS]
        if history_rounds and rng.random() < (0.25 if is_kauf else 0.10):
            drops = rng.randint(1, 3) if is_kauf else 1
            for change_round in rng.sample(history_rounds, min(drops, len(history_rounds))):
                lifecycle.price_changes[change_round] = 1 - rng.uniform(0.02, 0.08)
        if history_rounds and rng.random() < 0.03:
            lifecycle.price_changes[rng.choice(history_rounds)] = 1 + rng.uniform(0.02, 0.05)
        future_rounds = [r for r in later_rounds if r >= HISTORY_ROUNDS]
        if future_rounds and rng.random() < 0.15:
            lifecycle.price_changes[rng.choice(future_rounds)] = 1 - rng.uniform(0.02, 0.06)

        # going offline (sold / rented out); about a third come back after a few weeks
        if history_rounds and rng.random() < (0.15 if is_kauf else 0.30):
            start = rng.choice(history_rounds)
            end: int | None = None
            if rng.random() < 0.35 and start < last_round:
                end = min(start + rng.randint(1, 3), last_round)
            lifecycle.offline.append((start, end))
        still_listed = not lifecycle.offline or lifecycle.offline[-1][1] is not None
        if future_rounds and still_listed and rng.random() < 0.12:
            lifecycle.offline.append((rng.choice(future_rounds), None))

        self._lifecycles.append(lifecycle)

    def _pick(self, weighted):
        items, weights = zip(*weighted, strict=True)
        return self._rng.choices(items, weights=weights, k=1)[0]

    def _make_listing(self, offer_type: OfferType) -> Listing:
        rng = self._rng
        self._counter += 1
        is_kauf = offer_type is OfferType.KAUF
        sid = f"S-{'K' if is_kauf else 'M'}-{self._counter:05d}"

        city = self._pick([(c, c.weight) for c in CITIES])
        district = rng.choice(city.districts)
        property_type = self._pick(_KAUF_TYPES if is_kauf else _MIETE_TYPES)
        condition, condition_factor = rng.choice(_CONDITIONS)
        noise = rng.uniform(0.92, 1.08)
        market_rent_m2 = rng.uniform(*city.rent_m2) * district.factor**0.6
        flat_price_m2 = rng.uniform(*city.flat_price_m2) * district.factor * condition_factor

        data: dict = {
            "id": str(uuid.uuid5(_ID_NAMESPACE, sid)),
            "source": SAMPLE_SOURCE,
            "source_listing_id": sid,
            "url": f"https://example.com/expose/{sid}",
            "offer_type": offer_type,
            "property_type": property_type,
            "city": city.name,
            "district": district.name,
            "postal_code": district.postal_code,
            "lat": round(city.lat + rng.uniform(-0.04, 0.04), 5),
            "lon": round(city.lon + rng.uniform(-0.06, 0.06), 5),
            "condition": condition,
            "year_built": rng.choice(
                [rng.randint(1890, 1935), rng.randint(1950, 1989), rng.randint(1990, 2025)]
            ),
            "energy_class": rng.choice(_ENERGY_CLASSES),
            "raw": {},
        }

        if property_type is PropertyType.ETW:
            rooms = self._pick([(1, 2), (1.5, 1), (2, 5), (2.5, 2), (3, 5), (4, 3), (5, 1)])
            area = round(rooms * rng.uniform(21, 30) + rng.uniform(4, 14), 1)
            data.update(rooms=rooms, living_area_m2=area)
            data["title"] = f"{rng.choice(_FLAT_WORDS)} {rooms:g}-Zimmer-Wohnung in {district.name}"
        elif property_type is PropertyType.HAUS:
            rooms = rng.randint(4, 8)
            area = round(rooms * rng.uniform(22, 30), 1)
            data.update(
                rooms=rooms, living_area_m2=area, plot_area_m2=float(rng.randint(250, 1200))
            )
            data["title"] = f"Einfamilienhaus mit Garten in {district.name}"
        elif property_type is PropertyType.MFH:
            units = rng.randint(3, 12)
            area = round(units * rng.uniform(48, 82), 1)
            data.update(
                units=units,
                living_area_m2=area,
                rooms=float(units * rng.randint(2, 3)),
                plot_area_m2=float(rng.randint(400, 1800)),
            )
            data["title"] = f"Mehrfamilienhaus mit {units} Einheiten in {district.name}"
        else:  # GRUNDSTUECK
            plot = float(rng.randint(300, 1500))
            data.update(plot_area_m2=plot)
            data["title"] = f"Baugrundstück {plot:.0f} m² in {district.name}"

        area = data.get("living_area_m2")
        if not is_kauf:
            rent = market_rent_m2 * condition_factor**0.5 * noise * area
            data["price"] = float(max(round(rent / 5), 40) * 5)  # rounded to 5 EUR
            data["title"] = (
                data["title"]
                .replace("Wohnung", "Mietwohnung")
                .replace("Einfamilienhaus", "Haus zur Miete")
            )
        elif property_type is PropertyType.GRUNDSTUECK:
            land_m2 = rng.uniform(*city.land_value_m2) * district.factor * noise
            data["price"] = round(land_m2 * data["plot_area_m2"], -3)
        else:
            type_factor = {PropertyType.ETW: 1.0, PropertyType.HAUS: 0.90, PropertyType.MFH: 0.62}
            price = flat_price_m2 * type_factor[property_type] * noise * area
            data["price"] = max(round(price, -3), 20_000.0)

        if is_kauf and property_type is not PropertyType.GRUNDSTUECK:
            self._add_sale_details(data, property_type, market_rent_m2)
        self._make_messy(data, is_kauf)
        return Listing(**data)

    def _add_sale_details(self, data: dict, property_type: PropertyType, rent_m2: float) -> None:
        rng = self._rng
        area = data["living_area_m2"]
        rented_share = {PropertyType.ETW: 0.25, PropertyType.HAUS: 0.05, PropertyType.MFH: 0.80}
        roll = rng.random()
        if roll < rented_share[property_type]:
            # existing tenancies are usually below today's asking rents
            data["is_rented"] = True
            data["actual_rent_month"] = float(round(area * rent_m2 * rng.uniform(0.70, 0.98)))
        elif roll < rented_share[property_type] + 0.45:
            data["is_rented"] = False
        if property_type is PropertyType.ETW and rng.random() < 0.85:
            data["hausgeld_month"] = float(round(area * rng.uniform(2.5, 4.5)))
        if rng.random() < 0.45:
            data["commission_pct"] = rng.choice([0.0, 2.38, 3.0, 3.57, 3.57])

    def _make_messy(self, data: dict, is_kauf: bool) -> None:
        """Real listings are incomplete and sometimes wrong; so is the sample data."""
        rng = self._rng
        for field_name, probability in (
            ("rooms", 0.10),
            ("year_built", 0.25),
            ("energy_class", 0.40),
            ("district", 0.08),
            ("condition", 0.30),
            ("lat", 0.50),
        ):
            if rng.random() < probability:
                data[field_name] = None
        if data["lat"] is None:
            data["lon"] = None
        if rng.random() < 0.30:
            data["address"] = f"{rng.choice(_STREETS)} {rng.randint(1, 120)}"
        if data.get("living_area_m2") and rng.random() < 0.05:
            data["living_area_m2"] = None

        # a few outliers, labelled in `raw` so they can be recognised when debugging
        if rng.random() < 0.02:
            if is_kauf:
                data["price"] = max(round(data["price"] / 10, -3), 5_000.0)
                data["raw"]["sample_note"] = "outlier: price is missing a digit"
            else:
                data["price"] = data["price"] * 10
                data["raw"]["sample_note"] = "outlier: rent has one digit too many"
        elif data.get("living_area_m2") and rng.random() < 0.01:
            data["living_area_m2"] = round(data["living_area_m2"] * 10, 1)
            data["raw"]["sample_note"] = "outlier: living area has one digit too many"
