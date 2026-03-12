from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime
from typing import Any, Union

from app.models import Finisher

# Map MarathonGuide.com export headers → canonical field names
MARATHONGUIDE_COLUMN_MAP: dict[str, str] = {
    # --- MarathonGuide.com actual export format ---
    "OverallPlace": "Overall Place",
    "Bib": "Bib",
    "FirstName": "First Name",
    "LastName": "Last Name",
    "Sex": "Gender",
    "SexPlace": "Gender Place",
    "Age": "Age",
    "AgeGroup": "Age Group",
    "AgeGroupPlace": "Age Group Place",
    "City": "City",
    "State": "State",
    "Country": "Country",
    "FinalTime": "Finish Time",
    "ChipFinalTime": "Chip Time",
    "MarathonID": "MarathonID",
    "RaceDate": "Race Date",
    # --- Spaced/alternate variants ---
    "Bib #": "Bib",
    "Bib Number": "Bib",
    "BIB": "Bib",
    "First Name": "First Name",
    "Last Name": "Last Name",
    "first_name": "First Name",
    "last_name": "Last Name",
    "FIRST": "First Name",
    "LAST": "Last Name",
    "Gender": "Gender",
    "GENDER": "Gender",
    "SEX": "Gender",
    "Gender Place": "Gender Place",
    "GEN PL": "Gender Place",
    "SEX PL": "Gender Place",
    "Division": "Age Group",
    "DIVISION": "Age Group",
    "DIV": "Age Group",
    "AG": "Age Group",
    "Age Group": "Age Group",
    "Age Group Place": "Age Group Place",
    "DIV PL": "Age Group Place",
    "AG Place": "Age Group Place",
    "Division Place": "Age Group Place",
    "Overall Place": "Overall Place",
    "OA Place": "Overall Place",
    "OA": "Overall Place",
    "Overall": "Overall Place",
    "OVERALL": "Overall Place",
    "Finish Time": "Finish Time",
    "Time": "Finish Time",
    "FINISH": "Finish Time",
    "GUN TIME": "Finish Time",
    "CHIP TIME": "Finish Time",
    "Race Name": "Race Name",
    "RACE": "Race Name",
    "Race": "Race Name",
    "Race Date": "Race Date",
    "Date": "Race Date",
    "DATE": "Race Date",
    "Race Location": "Race Location",
    "Location": "Race Location",
    "Venue": "Race Location",
    "CITY": "City",
    "STATE": "State",
    "AGE": "Age",
}

# Only fields we truly require (the rest are derived or optional)
REQUIRED_FIELDS = {
    "Bib", "First Name", "Last Name",
    "Age", "Gender",
    "Finish Time", "Overall Place",
}


def _remap_headers(row: dict[str, str]) -> dict[str, str]:
    remapped: dict[str, str] = {}
    for key, value in row.items():
        canonical = MARATHONGUIDE_COLUMN_MAP.get(key.strip(), key.strip())
        remapped[canonical] = value.strip() if value else ""
    return remapped


def _parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return default


def _normalize_date(value: str) -> str:
    """Convert MM/DD/YYYY or YYYY-MM-DD to YYYY-MM-DD."""
    value = value.strip()
    if not value:
        return ""
    # MM/DD/YYYY
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", value)
    if m:
        return f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    return value


def _derive_age_group(age: int, gender: str) -> str:
    """
    Build a standard 5-year age group label.
    Gender prefix: M / F / O (other/NB/U).
    """
    prefix = gender if gender in ("M", "F") else "O"
    if age < 20:
        return f"{prefix}U20"
    if age >= 80:
        return f"{prefix}80+"
    low = (age // 5) * 5
    return f"{prefix}{low}-{low + 4}"


def _normalize_gender(raw: str) -> str:
    """Normalise Sex/Gender values."""
    raw = raw.strip().upper()
    if raw in ("M", "MALE"):
        return "M"
    if raw in ("F", "FEMALE"):
        return "F"
    return raw  # NB, U, etc. — keep as-is


def normalize_row(
    row: dict[str, str],
    race_name: str = "",
    race_date: str = "",
    race_location: str = "",
) -> dict[str, Any]:
    """Validate and cast types; derive missing fields."""
    missing = REQUIRED_FIELDS - set(row.keys())
    if missing:
        raise ValueError(f"CSV row missing required fields: {missing}")

    gender = _normalize_gender(row["Gender"])
    age = _parse_int(row["Age"])

    # Derive AgeGroup if empty
    raw_ag = row.get("Age Group", "").strip()
    age_group = raw_ag if raw_ag else _derive_age_group(age, gender)

    # Race metadata — prefer row values, fall back to caller-supplied defaults
    rn = row.get("Race Name", "").strip() or race_name
    rd = _normalize_date(row.get("Race Date", "").strip() or race_date)
    rl = row.get("Race Location", "").strip() or race_location

    return {
        "bib": row["Bib"],
        "first_name": row["First Name"],
        "last_name": row["Last Name"],
        "full_name": f"{row['First Name']} {row['Last Name']}",
        "city": row.get("City", ""),
        "state": row.get("State", ""),
        "age": age,
        "gender": gender,
        "age_group": age_group,
        "finish_time": row["Finish Time"],
        "overall_place": _parse_int(row["Overall Place"], 9999),
        "gender_place": _parse_int(row.get("Gender Place", ""), 0),
        "age_group_place": _parse_int(row.get("Age Group Place", ""), 0),
        "race_name": rn,
        "race_date": rd,
        "race_location": rl,
    }


def _race_name_from_filename(filename: str) -> str:
    """
    Extract a human-readable race name from the filename.
    e.g. 'results 23-1_02 - Atlanta Marathon.csv' → 'Atlanta Marathon'
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    # Take everything after the last ' - ' separator if present
    if " - " in base:
        return base.split(" - ")[-1].strip()
    return base.strip()


def load_csv(
    file_content: Union[bytes, str],
    filename: str = "",
    race_name: str = "",
    race_location: str = "",
) -> list[Finisher]:
    """
    Parse CSV bytes or string into a list of Finisher objects.

    Args:
        file_content: Raw CSV bytes or string.
        filename: Original filename — used to derive race name if not in CSV.
        race_name: Explicit race name override.
        race_location: Explicit race location override.

    Raises ValueError with a user-friendly message on bad input.
    """
    if isinstance(file_content, bytes):
        file_content = file_content.decode("utf-8-sig")  # handle BOM

    reader = csv.DictReader(io.StringIO(file_content))

    if not reader.fieldnames:
        raise ValueError("CSV file is empty or has no headers.")

    # Derive race name from filename if not supplied
    if not race_name and filename:
        race_name = _race_name_from_filename(filename)

    finishers: list[Finisher] = []
    errors: list[str] = []

    for line_num, raw_row in enumerate(reader, start=2):
        try:
            remapped = _remap_headers(dict(raw_row))
            normalized = normalize_row(
                remapped,
                race_name=race_name,
                race_location=race_location,
            )
            finishers.append(Finisher(**normalized))
        except (ValueError, KeyError) as e:
            errors.append(f"Row {line_num}: {e}")

    if errors and not finishers:
        raise ValueError(f"Could not parse any rows. First error: {errors[0]}")

    if errors:
        import warnings
        warnings.warn(f"Skipped {len(errors)} rows with errors: {errors[:3]}")

    return finishers
