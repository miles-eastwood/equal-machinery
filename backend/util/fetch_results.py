"""
Fetches new F1 race results from the Jolpica-F1 API (Ergast-compatible
successor: https://docs.fastf1.dev/api_reference/jolpica.html) and appends
them to the local CSV tables (races.csv, results.csv, drivers.csv,
constructors.csv, circuits.csv, status.csv).

Design goal: one HTTP call per race. Jolpica's per-round results endpoint
(`/{year}/{round}/results.json`) embeds full driver and constructor detail
inside every result, plus the race's circuit info, so no separate lookup
calls are needed for races with only previously-seen drivers/constructors.
New drivers/constructors/circuits/statuses are registered locally from that
same payload; nothing extra is fetched over the network.

Usage (run from the backend/ directory, with the venv active):
    python util/fetch_results.py
    python util/fetch_results.py --start-year 2025 --start-round 8
    python util/fetch_results.py --dry-run

Resumes automatically from the latest (year, round) already present in
data/races.csv unless --start-year/--start-round are given.
"""

import argparse
import csv
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
API_BASE = "https://api.jolpi.ca/ergast/f1"
# Stay comfortably under Jolpica's 4 req/s burst limit.
# https://github.com/jolpica/jolpica-f1/blob/main/docs/rate_limits.md
REQUEST_DELAY_SECONDS = 0.3
DEFAULT_CONSTRUCTOR_COLOR = "#D4D4D4"  # matches CTOR_NOT_FOUND fallback in main.py

# Best-effort primary/secondary colors for constructors that may not yet be
# in constructors.csv. Sourced from team livery reporting; treat as a
# starting point; refine manually in constructors.csv once official colors
# are confirmed.
KNOWN_NEW_CONSTRUCTOR_COLORS: dict[str, tuple[str, str]] = {
    "audi": ("#C8CED4", "#F50537"),
    "cadillac": ("#FFFFFF", "#000000"),
}


def http_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(5):
        response = requests.get(
            url, params=params, headers={"User-Agent": "equal-machinery/1.0"}
        )
        if response.status_code == 429:
            wait = 2**attempt
            print(f"Rate limited, waiting {wait}s before retrying...")
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"Repeated 429s fetching {url}")


class CsvTable:
    """Thin wrapper around a CSV file: loads all rows, tracks the max
    integer id, and buffers new rows to append on save()."""

    def __init__(self, filename: str, id_field: str):
        self.path = DATA_DIR / filename
        self.id_field = id_field
        with open(self.path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            self.header = next(reader)
            self.rows = list(reader)
        id_index = self.header.index(id_field)
        digit_ids = [int(r[id_index]) for r in self.rows if r[id_index].isdigit()]
        self.max_id = max(digit_ids) if digit_ids else 0
        self._new_rows: list[list[str]] = []

    def next_id(self) -> int:
        self.max_id += 1
        return self.max_id

    def add_row(self, row: dict[str, Any]) -> None:
        self._new_rows.append([str(row.get(col, r"\N")) for col in self.header])

    def save(self) -> int:
        if not self._new_rows:
            return 0
        # Guard against files that don't end with a newline: appending
        # directly in "a" mode would otherwise concatenate the first new
        # row onto the end of the last existing line.
        needs_leading_newline = False
        if self.path.stat().st_size > 0:
            with open(self.path, "rb") as f:
                f.seek(-1, 2)
                needs_leading_newline = f.read(1) not in (b"\n", b"\r")

        with open(self.path, "a", newline="", encoding="utf-8") as f:
            if needs_leading_newline:
                f.write("\n")
            writer = csv.writer(f)
            writer.writerows(self._new_rows)
        count = len(self._new_rows)
        self._new_rows = []
        return count


def load_ref_index(table: CsvTable, ref_field: str) -> dict[str, str]:
    """Maps a ref/name column value -> id (as string) for existing rows."""
    ref_index = table.header.index(ref_field)
    id_index = table.header.index(table.id_field)
    return {row[ref_index]: row[id_index] for row in table.rows}


def load_races_index(races: CsvTable) -> tuple[set[tuple[str, str]], int, int]:
    year_index = races.header.index("year")
    round_index = races.header.index("round")
    existing = {(r[year_index], r[round_index]) for r in races.rows}
    if not races.rows:
        return existing, date.today().year, 0
    last_year = max(int(r[year_index]) for r in races.rows)
    last_round = max(
        int(r[round_index]) for r in races.rows if int(r[year_index]) == last_year
    )
    return existing, last_year, last_round


def get_or_create_driver(
    drivers: CsvTable, driver_ref_to_id: dict[str, str], driver: dict[str, Any]
) -> str:
    ref = driver["driverId"]
    if ref in driver_ref_to_id:
        return driver_ref_to_id[ref]

    new_id = str(drivers.next_id())
    drivers.add_row(
        {
            "driverId": new_id,
            "driverRef": ref,
            "number": driver.get("permanentNumber", r"\N"),
            "code": driver.get("code", r"\N"),
            "forename": driver.get("givenName", ""),
            "surname": driver.get("familyName", ""),
            "dob": driver.get("dateOfBirth", r"\N"),
            "nationality": driver.get("nationality", r"\N"),
            "url": driver.get("url", r"\N"),
        }
    )
    driver_ref_to_id[ref] = new_id
    print(f"  + new driver: {driver.get('givenName')} {driver.get('familyName')} ({ref})")
    return new_id


def get_or_create_constructor(
    constructors: CsvTable,
    ctor_ref_to_id: dict[str, str],
    constructor: dict[str, Any],
) -> str:
    ref = constructor["constructorId"]
    if ref in ctor_ref_to_id:
        return ctor_ref_to_id[ref]

    new_id = str(constructors.next_id())
    primary, secondary = KNOWN_NEW_CONSTRUCTOR_COLORS.get(
        ref, (DEFAULT_CONSTRUCTOR_COLOR, "")
    )
    constructors.add_row(
        {
            "constructorId": new_id,
            "constructorRef": ref,
            "name": constructor.get("name", ref),
            "nationality": constructor.get("nationality", r"\N"),
            "url": constructor.get("url", r"\N"),
            "colorPrimary": primary,
            "colorSecondary": secondary,
        }
    )
    ctor_ref_to_id[ref] = new_id
    print(f"  + new constructor: {constructor.get('name')} ({ref}) -- verify colors in constructors.csv")
    return new_id


def get_or_create_circuit(
    circuits: CsvTable, circuit_ref_to_id: dict[str, str], circuit: dict[str, Any]
) -> str:
    ref = circuit["circuitId"]
    if ref in circuit_ref_to_id:
        return circuit_ref_to_id[ref]

    new_id = str(circuits.next_id())
    location = circuit.get("Location", {})
    circuits.add_row(
        {
            "circuitId": new_id,
            "circuitRef": ref,
            "name": circuit.get("circuitName", ref),
            "location": location.get("locality", r"\N"),
            "country": location.get("country", r"\N"),
            "lat": location.get("lat", r"\N"),
            "lng": location.get("long", r"\N"),
            "alt": r"\N",
            "url": circuit.get("url", r"\N"),
        }
    )
    circuit_ref_to_id[ref] = new_id
    print(f"  + new circuit: {circuit.get('circuitName')} ({ref})")
    return new_id


def get_or_create_status(
    statuses: CsvTable, status_to_id: dict[str, str], status_name: str
) -> str:
    if status_name in status_to_id:
        return status_to_id[status_name]

    new_id = str(statuses.next_id())
    statuses.add_row({"statusId": new_id, "status": status_name})
    status_to_id[status_name] = new_id
    print(f"  + new status: {status_name}")
    return new_id


def to_int_or_null(value: Optional[str]) -> str:
    return value if value is not None else r"\N"


def build_race_row(race: dict[str, Any], race_id: int, circuit_id: str) -> dict[str, Any]:
    return {
        "raceId": race_id,
        "year": race["season"],
        "round": race["round"],
        "circuitId": circuit_id,
        "name": race["raceName"],
        "date": race["date"],
        "time": race.get("time", r"\N"),
        "url": race.get("url", r"\N"),
        "fp1_date": r"\N",
        "fp1_time": r"\N",
        "fp2_date": r"\N",
        "fp2_time": r"\N",
        "fp3_date": r"\N",
        "fp3_time": r"\N",
        "quali_date": r"\N",
        "quali_time": r"\N",
        "sprint_date": r"\N",
        "sprint_time": r"\N",
    }


def build_result_row(
    result: dict[str, Any],
    result_id: int,
    race_id: int,
    driver_id: str,
    constructor_id: str,
    status_id: str,
) -> dict[str, Any]:
    position_text = result.get("positionText", "")
    position = position_text if position_text.isdigit() else r"\N"
    position_order = result.get("position", r"\N")

    time_info = result.get("Time", {})
    fastest_lap_info = result.get("FastestLap", {})
    fastest_lap_time_info = fastest_lap_info.get("Time", {})

    return {
        "resultId": result_id,
        "raceId": race_id,
        "driverId": driver_id,
        "constructorId": constructor_id,
        "number": result.get("number", r"\N"),
        "grid": result.get("grid", r"\N"),
        "position": position,
        "positionText": position_text,
        "positionOrder": position_order,
        "points": result.get("points", "0"),
        "laps": result.get("laps", r"\N"),
        "time": time_info.get("time", r"\N"),
        "milliseconds": time_info.get("millis", r"\N"),
        "fastestLap": fastest_lap_info.get("lap", r"\N"),
        "rank": fastest_lap_info.get("rank", r"\N"),
        "fastestLapTime": fastest_lap_time_info.get("time", r"\N"),
        "fastestLapSpeed": r"\N",  # not provided by Jolpica for recent seasons
        "statusId": status_id,
    }


def fetch_round_results(year: int, round_: int) -> Optional[dict[str, Any]]:
    data = http_get(f"{API_BASE}/{year}/{round_}/results.json", {"limit": 100})
    mrdata = data["MRData"]
    if int(mrdata["total"]) == 0:
        return None
    races = mrdata["RaceTable"]["Races"]
    return races[0] if races else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--start-round", type=int, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print what would be added without writing to disk",
    )
    args = parser.parse_args()

    races = CsvTable("races.csv", "raceId")
    results = CsvTable("results.csv", "resultId")
    drivers = CsvTable("drivers.csv", "driverId")
    constructors = CsvTable("constructors.csv", "constructorId")
    circuits = CsvTable("circuits.csv", "circuitId")
    statuses = CsvTable("status.csv", "statusId")

    existing_races, last_year, last_round = load_races_index(races)
    driver_ref_to_id = load_ref_index(drivers, "driverRef")
    ctor_ref_to_id = load_ref_index(constructors, "constructorRef")
    circuit_ref_to_id = load_ref_index(circuits, "circuitRef")
    status_to_id = load_ref_index(statuses, "status")

    year = args.start_year if args.start_year is not None else last_year
    round_ = args.start_round if args.start_round is not None else last_round + 1
    current_year = date.today().year

    print(f"Starting from {year} round {round_} (current year: {current_year})")

    races_added = 0
    results_added = 0

    while year <= current_year:
        race = fetch_round_results(year, round_)
        time.sleep(REQUEST_DELAY_SECONDS)

        if race is None:
            print(f"No results for {year} round {round_}; moving to next year")
            year += 1
            round_ = 1
            continue

        if (str(year), str(round_)) in existing_races:
            print(f"{year} round {round_} already present, skipping")
            round_ += 1
            continue

        race_date = race.get("date")
        if race_date and datetime.strptime(race_date, "%Y-%m-%d").date() > date.today():
            print(f"{year} round {round_} is in the future, stopping")
            break

        print(f"Fetching {year} round {round_}: {race['raceName']}")

        circuit_id = get_or_create_circuit(circuits, circuit_ref_to_id, race["Circuit"])
        race_id = races.next_id()
        races.add_row(build_race_row(race, race_id, circuit_id))
        races_added += 1

        for result in race["Results"]:
            driver_id = get_or_create_driver(drivers, driver_ref_to_id, result["Driver"])
            constructor_id = get_or_create_constructor(
                constructors, ctor_ref_to_id, result["Constructor"]
            )
            status_id = get_or_create_status(statuses, status_to_id, result["status"])
            result_id = results.next_id()
            results.add_row(
                build_result_row(result, result_id, race_id, driver_id, constructor_id, status_id)
            )
            results_added += 1

        round_ += 1

    if args.dry_run:
        print(f"\nDry run: would add {races_added} race(s), {results_added} result(s).")
        return

    saved_races = races.save()
    saved_results = results.save()
    saved_drivers = drivers.save()
    saved_constructors = constructors.save()
    saved_circuits = circuits.save()
    saved_statuses = statuses.save()

    print(
        f"\nDone. Added {saved_races} race(s), {saved_results} result(s), "
        f"{saved_drivers} driver(s), {saved_constructors} constructor(s), "
        f"{saved_circuits} circuit(s), {saved_statuses} status code(s)."
    )
    if saved_races == 0:
        print("No new races found.")


if __name__ == "__main__":
    main()
