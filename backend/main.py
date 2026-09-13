import csv
import json
from datetime import date
from data_types import Driver, Race, Ctor, Result, DriverPair
from fastapi import FastAPI

## GLOBAL DATA ##
driver_by_id: dict[int, Driver] = (
    dict()
)  # indexed by id (e.g 1 -> {Lewis Hamilton Driver Object})
driver_by_ref: dict[str, Driver] = (
    dict()
)  # indexed by driverRef (e.g. "hamilton" -> {Lewis Hamilton Driver Object})
race_by_id: dict[int, Race] = dict()
ctor_by_id: dict[int, Ctor] = dict()
ctor_by_ref: dict[str, Ctor] = dict()
result_by_id: dict[int, Result] = dict()
driver_pair_by_id: dict[tuple[int, int], DriverPair] = dict()


def load_drivers(file_path: str) -> tuple[dict[int, Driver], dict[str, Driver]]:
    driver_by_id = {}
    driver_by_ref = {}
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["number"] == r"\N":
                row["number"] = None
            driver = Driver(**row)
            driver_by_id[int(row["driverId"])] = driver
            driver_by_ref[row["driverRef"]] = driver
        return driver_by_id, driver_by_ref


def load_results(file_path: str) -> dict[int, Result]:
    map = {}
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            map[int(row["resultId"])] = Result(**row)
    return map


def load_races(file_path: str) -> dict[int, Race]:
    map = {}
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            map[int(row["raceId"])] = Race(**row)
    return map


def load_ctors(file_path: str) -> tuple[dict[int, Ctor], dict[str, Ctor]]:
    ctor_by_id: dict[int, Ctor] = {}
    ctor_by_ref: dict[str, Ctor] = {}
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ctor = Ctor(**row)
            ctor_by_id[int(ctor.constructor_id)] = ctor
            ctor_by_ref[ctor.constructor_ref] = ctor
    return ctor_by_id, ctor_by_ref


def process_results(
    race_by_id: dict[int, Race],
    result_by_id: dict[int, Result],
    driver_by_id: dict[int, Driver],
):
    for result in result_by_id.values():
        race: Race = race_by_id[result.race_id]
        race.results.add(result.result_id)
        race.drivers.add(result.driver_id)
        race.ctors.add(result.constructor_id)
        driver_by_id[result.driver_id].years_active.add(race.date.year)
        driver_by_id[result.driver_id].race_ids.add(race.race_id)


def populate_driver_pairings(
    race_by_id: dict[int, Race],
    result_by_id: dict[int, Result],
    driver_by_id: dict[int, Driver],
    ctor_by_id: dict[int, Ctor],
) -> dict[tuple[int, int], DriverPair]:
    driver_pair_by_id: dict[tuple[int, int], DriverPair] = dict()

    for race in race_by_id.values():
        for ctor_id in race.ctors:
            pair: list[int, int] = list()
            for result_id in race.results:
                result: Result = result_by_id[result_id]
                if result.constructor_id == ctor_id:
                    pair.append(result.driver_id)

            # temporary fix for if only one driver
            # TODO: Change this to add drivers that didn't race with teammates
            if len(pair) != 2:
                driver_id = pair[0]
                driver_by_id[driver_id].years_by_ctor.setdefault(ctor_id, set()).add(
                    race.date.year
                )
                continue

            # smaller driver_id goes first, to avoid duplicates
            driver_id1 = min(pair)
            driver_id2 = max(pair)
            driver_pair_id = driver_id1, driver_id2

            driver_pair: DriverPair = driver_pair_by_id.setdefault(
                driver_pair_id, DriverPair(*driver_pair_id)
            )

            # add current race info to pair
            driver_pair.race_ids.add(race.race_id)
            driver_pair.years_by_ctor.setdefault(ctor_id, set()).add(race.date.year)

            # link pair to drivers and ctor
            driver_by_id[driver_id1].driver_pairs.add(driver_pair_id)
            driver_by_id[driver_id1].years_by_ctor.setdefault(ctor_id, set()).add(
                race.date.year
            )

            teammates: list = (
                driver_by_id[driver_id1]
                .teammates_by_year_by_ctor.setdefault(ctor_id, dict())
                .setdefault(race.date.year, list())
            )
            if driver_id2 not in teammates:
                teammates.append(driver_id2)

            driver_by_id[driver_id2].driver_pairs.add(driver_pair_id)
            driver_by_id[driver_id2].years_by_ctor.setdefault(ctor_id, set()).add(
                race.date.year
            )

            teammates: list = (
                driver_by_id[driver_id2]
                .teammates_by_year_by_ctor.setdefault(ctor_id, dict())
                .setdefault(race.date.year, list())
            )
            if driver_id1 not in teammates:
                teammates.append(driver_id1)

            ctor_by_id[ctor_id].driver_pair_ids.add(driver_pair_id)

    return driver_pair_by_id


def to_cytoscape_data(
    driver_by_id: dict[int, Driver],
    ctor_by_id: dict[int, Ctor],
    driver_pair_by_id: dict[tuple[int, int], DriverPair],
    min_year: int = 0,
    max_year: int = 9999,
) -> dict[str, dict]:
    seen = set()  # used to only add edges with both drivers in year range
    nodes = []
    year_range: set[int] = set([i for i in range(min_year, max_year + 1)])

    for id in driver_by_id:
        driver: Driver = driver_by_id[id]
        if len(driver.driver_pairs) == 0:
            continue  # do not include drivers with no teammates
        if driver.years_active & year_range:
            nodes.append(
                {
                    "data": {
                        "id": str(id),
                        "displayCtorId": "0",  # default, will get changed
                        "name": str(driver),
                        "codename": driver.codename,
                        "forename": driver.forename,
                        "surname": driver.surname,
                        # "yearsActive": sorted(list(driver.years_active)), Not using for now, because same info in yearsByCtor
                        "yearsByCtor": sorted(
                            [
                                {
                                    "ctor": ctor_by_id[ctor_id].name,
                                    "ctorId": str(ctor_id),
                                    "years": sorted(years),
                                }
                                for ctor_id, years in driver.years_by_ctor.items()
                            ],
                            key=lambda pair: min(pair["years"]),
                        ),
                        "teammatesByYearByCtor": sorted(
                            [
                                {
                                    "ctorId": ctorId,
                                    "years": sorted(
                                        [list(item) for item in years.items()],
                                        key=lambda year: year[0], reverse=True),
                                }
                                for ctorId, years in driver.teammates_by_year_by_ctor.items()
                            ],
                            key=lambda pair: (
                                max([year[0] for year in pair["years"]]),
                                len(pair["years"]),
                            ), reverse=True
                        ),
                        "raceCount": len(driver.race_ids),
                    }
                }
            ),
            seen.add(id)

    edges = [
        {
            "data": {
                "source": str(driver_pair.driver_id_1),
                "target": str(driver_pair.driver_id_2),
                "displayCtorId": "0",  # default, will get changed
                "yearsByCtor": sorted(
                    [
                        {
                            "ctor": ctor_by_id[ctor_id].name,
                            "ctorId": str(ctor_id),
                            "years": sorted(years),
                        }
                        for ctor_id, years in driver_pair.years_by_ctor.items()
                    ],
                    key=lambda pair: max(pair["years"]),
                ),
            }
        }
        for driver_pair in driver_pair_by_id.values()
        if driver_pair.driver_id_1 in seen and driver_pair.driver_id_2 in seen
    ]

    # Order the nodes from newest to oldest
    #   - This is to fix a label chaching issue, where the last nodes in the list dont get their labels chached
    #   - This was causing their labels to flicker. For now, put old nodes to end of list
    #   - TODO: Come up with better solution, so that no labels flicker
    nodes.sort(
        key=lambda node: min(node["data"]["yearsByCtor"][0]["years"]), reverse=True
    )
    return {"nodes": nodes, "edges": edges}


# creates map that frontend will use to style nodes / edges based on ctor
def create_ctor_map(ctor_by_id: dict[int, Ctor]) -> list[dict[str, str]]:

    return [
        {
            "id": "0",
            "name": "CTOR_NOT_FOUND",
            "colorPrimary": "#D4D4D4",
            "colorSecondary": "#000000",
        }
    ] + [
        {
            "id": str(ctor.constructor_id),
            "name": ctor.name,
            "colorPrimary": ctor.color_primary if ctor.color_primary else "#D4D4D4",
            "colorSecondary": ctor.color_secondary,
        }
        for ctor in ctor_by_id.values()
    ]


# Takes result JSON and populates race/result CSVs
def process_new_json(
    json_path: str,
    race_csv_path: str,
    result_csv_path: str,
    driver_by_ref: dict[str, Driver],
    ctor_by_ref: dict[str, Ctor],
) -> None:

    # Load existing CSV to find max raceId
    with open(race_csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        race_rows = list(reader)

    race_header = race_rows[0]
    race_data = race_rows[1:]
    max_race_id = max(int(race[0]) for race in race_data if race[0].isdigit())

    with open(result_csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        result_rows = list(reader)

    result_header = result_rows[0]
    result_data = result_rows[1:]
    max_result_id = max(int(result[0]) for result in result_data if result[0].isdigit())

    # Load JSON races
    with open(json_path, encoding="utf-8") as f:
        races_json = json.load(f)

    new_race_rows = []
    new_result_rows = []
    race_id = max_race_id
    result_id = max_result_id

    for race in races_json["MRData"]["RaceTable"]["Races"]:
        race_id += 1
        season = race.get("season")
        round = race.get("round")
        race_name = race.get("raceName")
        url = race.get("url")
        date = race.get("date")
        time = race.get("time", None)  # Some JSONs include "time"

        # For consistency with your example CSV structure
        # Adjust indexes if your CSV has more columns
        row = [
            race_id,  # raceId
            season,  # season (year)
            round,  # round
            "\\N",  # circuit ID
            race_name,  # raceName
            date,  # race date
            time or "\\N",  # race time
            url,  # wikipedia URL
            "\\N",
            "\\N",  # FP1 date/time
            "\\N",
            "\\N",  # FP2 date/time
            "\\N",
            "\\N",  # FP3 date/time
            "\\N",
            "\\N",  # Quali date/time
            "\\N",
            "\\N",  # Sprint date/time
        ]
        new_race_rows.append(row)

        for result in race.get("Results"):
            result_id += 1
            driver_id = driver_by_ref[result.get("Driver").get("driverId")].driver_id
            ctor_id = ctor_by_ref[
                result.get("Constructor").get("constructorId")
            ].constructor_id
            number = int(result.get("Driver").get("permanentNumber"))
            grid = int(result.get("grid"))
            position = int(result.get("position"))
            position_text = result.get("positionText")
            points = int(result.get("points"))
            position_order = laps = time = milliseconds = fastestLap = rank = (
                fastestLapTime
            ) = fastestLapSpeed = statusId = "\\N"
            row = [
                result_id,
                race_id,
                driver_id,
                ctor_id,
                number,
                grid,
                position,
                position_text,
                position_order,
                points,
                laps,
                time,
                milliseconds,
                fastestLap,
                rank,
                fastestLapTime,
                fastestLapSpeed,
                statusId,
            ]

            new_result_rows.append(row)

    # Write back out with new races appended
    with open("data/new_races.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(race_header)
        writer.writerows(race_data + new_race_rows)

    with open("data/new_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(result_header)
        writer.writerows(result_data + new_result_rows)

    pass


# # MAIN LOADER CODE

driver_by_id, driver_by_ref = load_drivers("data/drivers.csv")
ctor_by_id, ctor_by_ref = load_ctors("data/constructors.csv")
result_by_id = load_results("data/results.csv")
race_by_id = load_races("data/races.csv")
process_results(race_by_id, result_by_id, driver_by_id)

driver_pair_by_id = populate_driver_pairings(
    race_by_id, result_by_id, driver_by_id, ctor_by_id
)

# Cap the graph at the latest year present in the data, so newly fetched
# seasons (see util/fetch_results.py) show up without needing a code change.
MAX_YEAR = max(race.date.year for race in race_by_id.values())

with open("dump.json", "w") as f:
    f.write(
        json.dumps(
            to_cytoscape_data(driver_by_id, ctor_by_id, driver_pair_by_id, 0, MAX_YEAR)
        )
    )

with open("../frontend/src/data/ctorMap.json", "w") as f:
    f.write(json.dumps(create_ctor_map(ctor_by_id)))

# The frontend's static demo view reads this file directly (see
# DriverGraph.tsx), so keep it in sync with the freshly generated graph.
with open("../frontend/public/data/graph.json", "w") as f:
    f.write(
        json.dumps(
            to_cytoscape_data(driver_by_id, ctor_by_id, driver_pair_by_id, 0, MAX_YEAR)
        )
    )

app = FastAPI()


@app.get("/graph")
def get_graph():
    return to_cytoscape_data(driver_by_id, ctor_by_id, driver_pair_by_id, 0, MAX_YEAR)


# process_new_json(
#     "data/2025/f1_2025_results_pt1.json", "data/races.csv", "data/results.csv",
#     driver_by_ref, ctor_by_ref
# )
