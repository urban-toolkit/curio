#!/usr/bin/env python3
"""Write the nine example tables of the scenario comparison charts dataflow.

Each table illustrates one way to chart a comparison of scenarios, and each is
a CSV dataset of its own in the Data Catalog, ``datasets/data.curio.example-*@1``.
Every row names its scenario in the ``case`` column. The test dataflow
``docs/examples/dataflows/scenario-comparison-charts.json`` keeps each
scenario's rows in a Data Transformation node, and charts each table's
scenarios with a chart of the Scout package that takes each scenario's node
on an input of its own.

The values come from the formulas below and a seeded random generator, so a
run writes the same bytes every time; ``test_scenario_comparison_charts.py``
checks the committed files against a fresh run. The generator only draws
``random.random()``, whose sequence Python keeps the same across versions, and
a normal draw is the inverse distribution function at such a draw.

Authoring-only tooling: nothing imports it at run time.

USAGE
-----
    python scripts/build_example_scenario_charts.py
    python scripts/build_example_scenario_charts.py --root <folder>
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The date every manifest records.
CREATED = "2026-10-17T00:00:00Z"
DATAFLOW = "Nine ways to chart scenario comparisons"
SCRIPT = "scripts/build_example_scenario_charts.py"

_NORMAL = statistics.NormalDist()


def _normal(rng: random.Random, sigma: float) -> float:
    """A normal draw with mean 0 and standard deviation *sigma*."""
    u = rng.random()
    while u <= 0.0:
        u = rng.random()
    return sigma * _NORMAL.inv_cdf(u)


def _jitter(rng: random.Random, width: float) -> float:
    """A uniform draw from -width/2 to width/2."""
    return width * (rng.random() - 0.5)


# --- 1. Lines with a band ----------------------------------------------------

#: Each street: its busiest hourly count, and how busy it is on a weekday and
#: on a weekend day, as a factor of that.
STREETS = (
    ("Main Street", 900, 1.0, 0.9),
    ("Market Street", 650, 0.8, 1.3),
    ("Park Avenue", 420, 0.6, 1.7),
    ("Station Road", 1150, 1.2, 0.45),
)


def _bump(hour: float, centre: float, width: float) -> float:
    return math.exp(-(((hour - centre) / width) ** 2))


def _weekday(hour: int) -> float:
    return 0.08 + _bump(hour, 8, 1.5) + 0.5 * _bump(hour, 12.5, 1.4) + 0.85 * _bump(hour, 17.5, 1.9)


def _weekend(hour: int) -> float:
    return 0.06 + 0.9 * _bump(hour, 13.5, 3.4) + 0.3 * _bump(hour, 20.5, 1.8)


def pedestrians_by_hour(rng: random.Random) -> list[dict]:
    rows = []
    for case, profile, column in (("Weekday", _weekday, 2), ("Weekend", _weekend, 3)):
        for street in STREETS:
            name, busiest, factor = street[0], street[1], street[column]
            for hour in range(24):
                mean = busiest * factor * profile(hour)
                spread = 0.1 + 0.2 * rng.random()
                rows.append({
                    "case": case, "street": name, "hour": hour, "pedestrians": round(mean),
                    "low": round(mean * (1 - spread)), "high": round(mean * (1 + spread)),
                })
    return rows


# --- 2. Curves by state ------------------------------------------------------

DAMAGE_STATES = ("Slight", "Moderate", "Extensive", "Complete")
#: The water depth, in metres, at which a house as built reaches each damage
#: state half the time, and the spread of the depths (lognormal curves).
DAMAGE_MEDIANS = (0.3, 0.8, 1.4, 2.3)
DAMAGE_SPREAD = 0.5
#: How many times floodproofing raises each of those depths.
FLOODPROOFED = 1.7


def flood_damage_curves(rng: random.Random) -> list[dict]:
    rows = []
    for case, factor in (("As built", 1.0), ("Floodproofed", FLOODPROOFED)):
        for state, median in zip(DAMAGE_STATES, DAMAGE_MEDIANS):
            for step in range(31):
                depth = step / 10
                chance = 0.0 if step == 0 else _NORMAL.cdf(math.log(depth / (median * factor)) / DAMAGE_SPREAD)
                rows.append({"case": case, "damage_state": state, "depth_m": depth, "probability": round(chance, 3)})
    return rows


# --- 3. Bars with error bars and 4. strips of an ensemble --------------------

STORMS = ("10-year storm", "50-year storm", "100-year storm")
RUNS = 50
DEPTH_CLASSES = ("Under 10 cm", "10 to 30 cm", "30 to 60 cm", "Over 60 cm")
#: Each storm's usual share of flooded street length in each depth class.
STORM_SHARES = ((0.6, 0.28, 0.1, 0.02), (0.42, 0.32, 0.18, 0.08), (0.28, 0.3, 0.26, 0.16))
#: Each storm's median peak depth at the river gauge, in metres, and its spread.
PEAK_DEPTHS = ((1.1, 0.16), (1.8, 0.18), (2.5, 0.2))


def street_flooding(rng: random.Random) -> list[dict]:
    rows = []
    for case, shares in zip(STORMS, STORM_SHARES):
        runs = []
        for _ in range(RUNS):
            drawn = [share * math.exp(_normal(rng, 0.3)) for share in shares]
            total = sum(drawn)
            runs.append([value / total for value in drawn])
        for index, depth_class in enumerate(DEPTH_CLASSES):
            values = [run[index] for run in runs]
            rows.append({
                "case": case, "depth_class": depth_class,
                "share_mean": round(statistics.fmean(values), 3), "share_sd": round(statistics.stdev(values), 3),
            })
    return rows


def peak_depths(rng: random.Random) -> list[dict]:
    rows = []
    for case, (median, sigma) in zip(STORMS, PEAK_DEPTHS):
        for run in range(1, RUNS + 1):
            rows.append({"case": case, "run": run, "peak_depth_m": round(median * math.exp(_normal(rng, sigma)), 2)})
    return rows


# --- 5. Grouped bars ---------------------------------------------------------

MODES = ("Bike", "Bus", "Car", "Walk")
TRIPS_TODAY = (8000, 26000, 61000, 22000)
#: How each street plan changes each mode's daily trips, as a factor of today's.
STREET_PLANS = (
    ("Today", (1.0, 1.0, 1.0, 1.0)),
    ("Bus lanes", (1.0, 1.35, 0.88, 1.02)),
    ("Bike network", (2.2, 0.97, 0.9, 1.04)),
    ("Car-free center", (1.4, 1.18, 0.62, 1.3)),
)


def trips_by_mode(rng: random.Random) -> list[dict]:
    rows = []
    for case, factors in STREET_PLANS:
        for mode, trips, factor in zip(MODES, TRIPS_TODAY, factors):
            noise = 1.0 if case == "Today" else 1 + _jitter(rng, 0.06)
            rows.append({"case": case, "mode": mode, "daily_trips": int(round(trips * factor * noise, -2))})
    return rows


# --- 6. Stacked bars with totals ---------------------------------------------

LIFE_STAGES = ("Materials", "Transport", "Construction", "Use", "End of life")
#: kg of CO2e per m2 of floor over a 60-year life, stage by stage.
FRAMES = (("Concrete frame", (310, 25, 40, 380, 35)), ("Timber frame", (165, 30, 32, 360, 22)))


def building_carbon(rng: random.Random) -> list[dict]:
    rows = []
    for case, values in FRAMES:
        for order, (stage, value) in enumerate(zip(LIFE_STAGES, values), start=1):
            rows.append({
                "case": case, "stage": stage, "stage_order": order,
                "kg_co2e_per_m2": round(value * (1 + _jitter(rng, 0.08))),
            })
    return rows


# --- 7. A donut per scenario -------------------------------------------------

#: The share of each park design's area in shade at noon in July, in percent.
PARK_DESIGNS = (("Open lawn", 18.0), ("Tree canopy", 57.0))


def park_shade(rng: random.Random) -> list[dict]:
    rows = []
    for case, shade in PARK_DESIGNS:
        shade = round(shade + _jitter(rng, 4), 1)
        rows.append({"case": case, "cover": "Shade", "share_pct": shade})
        rows.append({"case": case, "cover": "Sun", "share_pct": round(100 - shade, 1)})
    return rows


# --- 8. A matrix of weights --------------------------------------------------

ROUTE_FACTORS = ("Travel time", "Traffic stress", "Hills", "Shade", "Crossings", "Scenery")
#: How much each factor counts for (above 0) or against (below 0) each route,
#: from -1 to 1, and 0 where it does not matter.
ROUTES = (
    ("Route A", (0.7, -0.6, 0.0, -0.3, -0.4, 0.0)),
    ("Route B", (-0.3, 0.6, -0.5, 0.5, 0.2, 0.4)),
    ("Route C", (0.2, 0.1, 0.4, 0.0, -0.2, -0.3)),
)


def bike_route_factors(rng: random.Random) -> list[dict]:
    rows = []
    for case, effects in ROUTES:
        for order, (factor, effect) in enumerate(zip(ROUTE_FACTORS, effects), start=1):
            if effect:
                effect = max(-1.0, min(1.0, round((effect + _jitter(rng, 0.1)) * 20) / 20))
            rows.append({"case": case, "factor": factor, "factor_order": order, "effect": effect})
    return rows


# --- 9. A table --------------------------------------------------------------

#: Each green roof system: the share of a year's rain it holds back (%), how
#: much cooler it keeps the roof on a hot afternoon (degrees C), and its cost
#: per m2 (US dollars).
ROOF_SYSTEMS = (
    ("Extensive roof", 45, 14.0, 95),
    ("Semi-intensive roof", 60, 20.0, 165),
    ("Intensive roof", 74, 27.0, 310),
)


def green_roofs(rng: random.Random) -> list[dict]:
    rows = []
    for case, rain, cooling, cost in ROOF_SYSTEMS:
        rows.append({
            "case": case, "rain_held_pct": rain + round(_jitter(rng, 4)),
            "roof_cooling_c": round(cooling + _jitter(rng, 2), 1),
            "cost_per_m2": int(round(cost * (1 + _jitter(rng, 0.06)), -1)),
        })
    return rows


# --- the datasets ------------------------------------------------------------


@dataclass(frozen=True)
class Table:
    dataset_id: str
    file_name: str
    name: str
    #: What its rows hold, a sentence.
    holds: str
    #: How the dataflow draws it.
    chart: str
    seed: int
    rows: Callable[[random.Random], list]


TABLES = (
    Table(
        "data.curio.example-pedestrians-by-hour", "pedestrians_by_hour.csv",
        "Example table: pedestrians per hour",
        "Pedestrians counted per hour on four streets, on weekdays and on weekends: "
        "the mean count of the days, and their low and high counts.",
        "lines with a band, one panel per street", 1, pedestrians_by_hour,
    ),
    Table(
        "data.curio.example-flood-damage-curves", "flood_damage_curves.csv",
        "Example table: flood damage curves",
        "The chance that a house reaches each flood damage state as the water rises, "
        "as built and floodproofed.",
        "one curve per damage state and scenario", 2, flood_damage_curves,
    ),
    Table(
        "data.curio.example-street-flooding", "street_flooding.csv",
        "Example table: flooded streets by depth",
        "The share of flooded street length in each depth class in a 10-, 50- and "
        "100-year storm: the mean over 50 simulated storms and its standard deviation.",
        "grouped bars with error bars", 3, street_flooding,
    ),
    Table(
        "data.curio.example-peak-depths", "peak_depths.csv",
        "Example table: peak depths of simulated storms",
        "The peak water depth at a river gauge in each of 50 simulated storms, for a "
        "10-, 50- and 100-year storm.",
        "a strip of ticks per storm, with its median", 4, peak_depths,
    ),
    Table(
        "data.curio.example-trips-by-mode", "trips_by_mode.csv",
        "Example table: daily trips by mode",
        "Daily trips by bike, by bus, by car and on foot, today and under three street plans.",
        "grouped bars", 5, trips_by_mode,
    ),
    Table(
        "data.curio.example-building-carbon", "building_carbon.csv",
        "Example table: building carbon by life-cycle stage",
        "The carbon of a school building per m2 of floor over its life, stage by stage, "
        "with a concrete frame and with a timber frame.",
        "stacked bars with their totals", 6, building_carbon,
    ),
    Table(
        "data.curio.example-park-shade", "park_shade.csv",
        "Example table: park area in shade",
        "The share of a park's area in shade at noon, for an open lawn design and a tree "
        "canopy design.",
        "a donut per design", 7, park_shade,
    ),
    Table(
        "data.curio.example-bike-route-factors", "bike_route_factors.csv",
        "Example table: bike route factors",
        "How much each factor counts for or against three bike routes, from -1 to 1.",
        "a matrix of circles sized by weight", 8, bike_route_factors,
    ),
    Table(
        "data.curio.example-green-roofs", "green_roofs.csv",
        "Example table: green roof systems",
        "Three green roof systems: the share of a year's rain each holds back, how much "
        "cooler it keeps the roof, and its cost per m2.",
        "a table", 9, green_roofs,
    ),
)


def table_rows(table: Table) -> list[dict]:
    """*table*'s rows, from its own seeded generator."""
    return table.rows(random.Random(table.seed))


def csv_text(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def manifest(table: Table, row_count: int) -> dict:
    return {
        "id": table.dataset_id,
        "name": table.name,
        "version": "1.0.0",
        "format": "csv",
        "description": (
            f"{table.holds} One of nine example tables that illustrate ways to chart a "
            f"comparison of scenarios, each row's scenario in its case column. The {DATAFLOW} "
            f"test dataflow draws it as {table.chart}. Curio's seeded script {SCRIPT} writes it."
        ),
        "publisher": "Curio",
        "license": "MIT",
        "tags": ["example", "scenarios", "csv"],
        "dataFile": f"data/{table.file_name}",
        "compatibility": {"major": 1},
        "sourceLabel": "Curio example tables",
        "rowCount": row_count,
        "featureCount": None,
        "schema": None,
        "createdAt": CREATED,
        "updatedAt": CREATED,
    }


def files(table: Table) -> dict[str, str]:
    """``{path under the dataset folder: text}`` for *table*'s dataset."""
    rows = table_rows(table)
    return {
        "manifest.json": json.dumps(manifest(table, len(rows)), indent=2) + "\n",
        f"data/{table.file_name}": csv_text(rows),
    }


def write(root: Path) -> list[Path]:
    written = []
    for table in TABLES:
        folder = root / "datasets" / f"{table.dataset_id}@1"
        for relative, text in files(table).items():
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as out:
                out.write(text)
            written.append(path)
    return written


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="the folder that holds datasets/")
    args = parser.parse_args(argv)
    for path in write(args.root):
        print(f"{path.stat().st_size:7d}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
