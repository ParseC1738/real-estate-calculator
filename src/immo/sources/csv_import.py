"""Adapter that reads listings from a CSV file (SPEC §9).

Expected format: one listing per row, column names = field names of `Listing`
(`source_listing_id`, `offer_type`, `property_type`, `title`, `city`, `postal_code`,
`price` are required). `,` or `;` as separator. Numbers may be written the German way
(`250.000,50`) or the English way (`250000.5`). Unknown columns are kept in `raw`.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from immo.core.models import Listing, SearchQuery
from immo.sources.base import RawListing

CSV_SOURCE = "csv"
REQUIRED_COLUMNS = (
    "source_listing_id",
    "offer_type",
    "property_type",
    "title",
    "city",
    "postal_code",
    "price",
)
_FLOAT_FIELDS = {
    "lat", "lon", "price", "living_area_m2", "plot_area_m2", "rooms", "actual_rent_month",
    "hausgeld_month", "commission_pct",
}  # fmt: skip
_INT_FIELDS = {"units", "year_built"}
_BOOL_FIELDS = {"is_rented"}
_ENUM_FIELDS = {"offer_type", "property_type"}
_TEXT_FIELDS = {
    "source_listing_id", "url", "title", "city", "district", "postal_code", "address",
    "condition", "energy_class",
}  # fmt: skip
_TRUE = {"true", "1", "yes", "y", "ja", "j", "x"}
_FALSE = {"false", "0", "no", "n", "nein"}
_GERMAN_THOUSANDS = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def parse_number(text: str) -> float:
    """Parse '250.000,50', '250000.5', '1,234.56', '62,5 m²' or '1.200 €' into a float."""
    cleaned = re.sub(r"[^\d,.\-]", "", text)
    if not cleaned:
        raise ValueError(f"not a number: {text!r}")
    if "," in cleaned and "." in cleaned:
        # the separator that comes last is the decimal separator
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif _GERMAN_THOUSANDS.match(cleaned):
        cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f"not a number: {text!r}") from None


def _parse_bool(text: str) -> bool:
    value = text.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"not a yes/no value: {text!r}")


def decode_csv(content: bytes) -> str:
    """Decode an uploaded file: UTF-8 (with or without BOM), else Windows/Excel Latin-1."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252")


class CsvAdapter:
    name = CSV_SOURCE

    def __init__(self, text: str) -> None:
        self._text = text

    @classmethod
    def from_path(cls, path: Path | str) -> CsvAdapter:
        return cls(decode_csv(Path(path).read_bytes()))

    def fetch(self, query: SearchQuery) -> Iterable[RawListing]:
        """Yield every row. The query is applied by the pipeline after normalising,

        because a raw CSV row is just text.
        """
        first_line = self._text.lstrip().split("\n", 1)[0]
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        reader = csv.DictReader(io.StringIO(self._text.lstrip()), delimiter=delimiter)
        columns = [c.strip() for c in reader.fieldnames or []]
        missing = [c for c in REQUIRED_COLUMNS if c not in columns]
        if missing:
            raise ValueError(f"CSV is missing required column(s): {', '.join(missing)}")
        for line_number, row in enumerate(reader, start=2):  # line 1 is the header
            data = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
            if not any(data.values()):
                continue  # skip empty lines
            listing_id = data.get("source_listing_id") or f"(line {line_number})"
            yield RawListing(source=self.name, source_listing_id=listing_id, data=data)

    def normalize(self, raw: RawListing) -> Listing:
        fields: dict[str, Any] = {"source": self.name, "raw": raw.data}
        for column, text in raw.data.items():
            if text == "" or column not in Listing.model_fields:
                continue  # empty = unknown; unknown columns stay in `raw` only
            try:
                if column in _FLOAT_FIELDS:
                    fields[column] = parse_number(text)
                elif column in _INT_FIELDS:
                    fields[column] = int(parse_number(text))
                elif column in _BOOL_FIELDS:
                    fields[column] = _parse_bool(text)
                elif column in _ENUM_FIELDS:
                    fields[column] = text.upper()
                elif column in _TEXT_FIELDS:
                    fields[column] = text
            except ValueError as error:
                raise ValueError(f"{column}: {error}") from None
        if "source_listing_id" not in fields:
            raise ValueError("source_listing_id: missing")
        return Listing(**fields)


TEMPLATE_CSV = """\
source_listing_id;offer_type;property_type;title;city;district;postal_code;price;\
living_area_m2;plot_area_m2;rooms;units;year_built;condition;actual_rent_month;\
hausgeld_month;commission_pct;is_rented;url
my-001;KAUF;ETW;3-Zimmer-Wohnung mit Balkon;Potsdam;Babelsberg;14482;329.000;78,5;;3;;1998;\
well kept;;310;3,57;nein;
my-002;KAUF;MFH;Mehrfamilienhaus mit 6 Einheiten;Brandenburg an der Havel;Neustadt;14776;\
790.000;430;620;;6;1925;renovated;3.650;;;ja;
my-003;KAUF;GRUNDSTUECK;Baugrundstück am Stadtrand;Berlin;Spandau;13581;265.000;;540;;;;;;;;;
my-004;MIETE;ETW;2-Zimmer-Wohnung, saniert;Berlin;Pankow;13187;890;58;;2;;1965;renovated;;;;;
"""
