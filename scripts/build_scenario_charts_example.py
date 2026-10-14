#!/usr/bin/env python3
"""Write the ScenarioCharts example: nine kinds of scenario comparison, each a
Vega-Lite node with its Compare scenarios switch on.

The charts follow figures from the scenario-planning literature (SCOUT's
``backend/data/mock-data/ref_scenario_plots``), each with its figure's own data
and scenarios: an hourly time series with an uncertainty band, fragility
curves, damage-state shares with error bars, an ensemble's spread, binned
emissions, a lifecycle composition, impact shares, multi-criteria route
scores, and a table. The values are mock data shaped like each figure's.

It writes:

- ``datasets/data.curio.scenario-charts@1/``: one bundle, the nine tables as
  CSV parts, each row's scenario in its ``case`` column;
- ``docs/examples/dataflows/ScenarioCharts.json``: a Data Loading node loads
  the bundle, one node per chart and scenario keeps that scenario's rows of its
  table, and each chart's Vega-Lite node compares its scenarios. Every one of
  those nodes is in its dataflow scenario, so each chart draws its scenarios in
  their colors; M5, M6 and M7 each feed two charts.

This is AUTHORING-ONLY tooling, run by hand; nothing imports it. The output
is deterministic, so a rerun rewrites the same files.

USAGE
-----
    python scripts/build_scenario_charts_example.py
"""

from __future__ import annotations

import copy
import csv
import json
import math
import random
import re
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "data.curio.scenario-charts"
DATASET_DIR = REPO_ROOT / "datasets" / f"{DATASET_ID}@1"
DATAFLOW = REPO_ROOT / "docs/examples/dataflows/ScenarioCharts.json"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://curio.dev/examples/ScenarioCharts")
VEGA_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"

# The dataflow's scenarios, each figure's own, in their figures' colors.
SCENARIOS = {
    "weekday": ("Weekday", "#3b6fd4"),
    "offday": ("Offday", "#f59e0b"),
    "as-built": ("As-built", "#374151"),
    "retrofit": ("Retrofit", "#2a9d8f"),
    "m5": ("M5", "#6a4fc4"),
    "m6": ("M6", "#9ca3af"),
    "m7": ("M7", "#f28c28"),
    "original": ("Original", "#7b1fa2"),
    "lchg": ("LCHG priority", "#ff8f00"),
    "bc": ("BC priority", "#2e9e3a"),
    "bc-rb": ("BC priority with RB", "#d32f2f"),
    "baseline": ("Baseline", "#0b3c49"),
    "proposal": ("Proposal", "#e0812b"),
    "solution-1": ("Solution 1", "#d9654b"),
    "solution-2": ("Solution 2", "#4a72b0"),
    "route-1": ("Route 1", "#5b8db8"),
    "route-2": ("Route 2", "#8e6bbf"),
    "route-3": ("Route 3", "#c9a227"),
    "passive": ("Passive Green Wall", "#6aa84f"),
    "active": ("Active Modular System", "#38812f"),
    "intensive": ("Intensive Planting", "#1b5e20"),
}


def _r(value: float, digits: int = 3) -> float:
    return round(value, digits)


# --- the nine tables ---------------------------------------------------------


def carpark_occupancy() -> list[dict]:
    """Four carparks' hourly occupancy, weekdays against weekends and holidays,
    the mean and the band the days spread over."""
    rng = random.Random(1)

    def bump(hour, centre, width):
        return math.exp(-((hour - centre) / width) ** 2)

    shapes = {
        "Carpark A": (
            lambda h: 0.64 - 0.31 * bump(h, 13, 4.5),
            lambda h: 0.63 - 0.13 * bump(h, 14, 4),
        ),
        "Carpark B": (
            lambda h: 0.71 - 0.28 * bump(h, 14, 4.5),
            lambda h: 0.68 + 0.12 * bump(h, 9, 2.2) - 0.18 * bump(h, 17, 3),
        ),
        "Carpark C": (
            lambda h: 0.29 + 0.62 * bump(h, 10, 3.2) + 0.2 * bump(h, 18, 1.5),
            lambda h: 0.3 + 0.7 * bump(h, 10, 3.8) + 0.2 * bump(h, 18, 1.5),
        ),
        "Carpark D": (
            lambda h: 0.34 + 0.66 * bump(h, 11, 4.5),
            lambda h: 0.35 + 0.66 * bump(h, 10.5, 4.2),
        ),
    }
    rows = []
    for carpark, (weekday, offday) in shapes.items():
        for case, curve in (("Weekday", weekday), ("Offday", offday)):
            for hour in range(24):
                mean = min(1.0, curve(hour))
                spread = 0.015 + (0.09 if 7 <= hour <= 13 else 0.03) * rng.random()
                rows.append({
                    "case": case, "carpark": carpark, "hour": hour, "occupancy": _r(mean),
                    "lower": _r(max(0.0, mean - spread)), "upper": _r(min(1.0, mean + spread * 0.6)),
                })
    return rows


def fragility_curves() -> list[dict]:
    """A bridge's probability of reaching each damage state as the peak ground
    acceleration grows, lognormal fragility curves, as built and retrofitted."""
    medians = {"Slight": 0.75, "Moderate": 1.15, "Extensive": 1.6, "Complete": 2.6}
    rows = []
    for case, factor in (("As-built", 1.0), ("Retrofit", 1.45)):
        for state, median in medians.items():
            for step in range(41):
                pga = step * 0.025
                z = math.log(pga / (median * factor)) / 0.65 if pga > 0 else -math.inf
                rows.append({
                    "case": case, "damage_state": state, "pga": _r(pga),
                    "probability": _r(0.5 * (1 + math.erf(z / math.sqrt(2)))) if pga > 0 else 0.0,
                })
    return rows


def bridge_damage() -> list[dict]:
    """The share of bridges in each damage state for M5, M6 and M7 events: the
    mean over the event's ground-motion scenarios and its standard deviation."""
    values = {
        "M5": [(0.085, 0.12), (0.02, 0.05), (0.0, 0.0), (0.0, 0.0)],
        "M6": [(0.305, 0.15), (0.16, 0.215), (0.003, 0.005), (0.0, 0.002)],
        "M7": [(0.25, 0.165), (0.605, 0.28), (0.012, 0.02), (0.002, 0.008)],
    }
    states = ["Slight", "Moderate", "Extensive", "Complete"]
    return [
        {"case": case, "damage_state": state, "mean": mean, "sd": sd}
        for case, pairs in values.items()
        for state, (mean, sd) in zip(states, pairs)
    ]


def pga_ensemble() -> list[dict]:
    """The median peak ground acceleration of each of an event's 50 simulated
    ground-motion scenarios, for M5, M6 and M7."""
    rng = random.Random(7)
    spread = {"M5": (0.07, 0.75, 0.33), "M6": (0.22, 0.45, 0.63), "M7": (0.52, 0.45, 1.36)}
    rows = []
    for case, (median, sigma, top) in spread.items():
        for run in range(1, 51):
            value = min(top, median * math.exp(rng.gauss(0, sigma)))
            rows.append({"case": case, "run": run, "median_pga": _r(value)})
    return rows


def carbon_by_distance() -> list[dict]:
    """A delivery fleet's carbon emission by trip distance under the original
    plan and three priorities: low-carbon (LCHG), battery (BC), and battery
    with rebalancing (RB)."""
    bands = ["0-8", "8-16", "16-24", "24-32", "32-40", ">40"]
    values = {
        "Original": [2700, 10200, 9400, 9250, 4400, 3450],
        "LCHG priority": [2850, 10500, 9650, 8500, 3850, 1900],
        "BC priority": [2800, 10300, 11500, 6850, 3800, 2250],
        "BC priority with RB": [2800, 10350, 11550, 6900, 4100, 2250],
    }
    return [
        {"case": case, "distance_band": band, "emission_kg": value}
        for case, row in values.items()
        for band, value in zip(bands, row)
    ]


def lifecycle_gwp() -> list[dict]:
    """A building's global warming potential by lifecycle stage, in kg CO2e per
    m2 per year: the baseline design (12.9) and the proposal (8.5)."""
    values = {
        "Baseline": [6.9, 0.6, 1.1, 1.0, 2.3, 1.0],
        "Proposal": [0.4, 0.6, 0.7, 0.9, 2.2, 3.7],
    }
    stages = ["A1-A3", "A4", "A5", "B4", "B6", "C3-C4"]
    return [
        {"case": case, "stage": stage, "order": index, "gwp": value}
        for case, row in values.items()
        for index, (stage, value) in enumerate(zip(stages, row))
    ]


def impact_share() -> list[dict]:
    """The share of two retrofit solutions' environmental impact from their
    structural and non-structural work, in percent."""
    return [
        {"case": "Solution 1", "component": "Non-Structural", "share": 68.6},
        {"case": "Solution 1", "component": "Structural", "share": 31.4},
        {"case": "Solution 2", "component": "Non-Structural", "share": 61.2},
        {"case": "Solution 2", "component": "Structural", "share": 38.8},
    ]


def route_criteria() -> list[dict]:
    """How much each criterion weighs for or against three candidate routes,
    from -1 to 1, 0 where it does not matter."""
    criteria = [
        "Departure Time", "Travel Cost", "Road Importance",
        "Intersection Number", "Travel Distance", "Congestion Degree",
    ]
    values = {
        "Route 1": [0.05, 0.45, 0.7, -0.15, -0.15, 0.05],
        "Route 2": [0.35, 0.0, 0.7, 0.0, 0.0, 0.35],
        "Route 3": [0.0, 0.45, 0.0, -0.75, -0.5, 0.0],
    }
    return [
        {"case": case, "criterion": criterion, "order": index, "effect": value}
        for case, row in values.items()
        for index, (criterion, value) in enumerate(zip(criteria, row))
    ]


def green_wall() -> list[dict]:
    """A facade's new U-value, its energy savings and its CO2 reduction under
    three green-wall systems."""
    return [
        {"case": "Passive Green Wall", "u_value": 0.96, "energy_savings": 1400, "co2_reduction": 560},
        {"case": "Active Modular System", "u_value": 0.78, "energy_savings": 2450, "co2_reduction": 980},
        {"case": "Intensive Planting", "u_value": 0.66, "energy_savings": 3150, "co2_reduction": 1260},
    ]


# --- the charts --------------------------------------------------------------

AXIS_LABEL0 = {"labelAngle": 0}
NO_LEGEND_SCENARIO = {"field": "scenario_name", "type": "nominal", "title": None}


def spec_occupancy() -> dict:
    return {
        "facet": {"field": "carpark", "type": "nominal", "title": None},
        "columns": 2,
        "spec": {
            "width": 240,
            "height": 130,
            "encoding": {
                "x": {"field": "hour", "type": "quantitative", "title": "Hour", "scale": {"domain": [0, 23]}},
                "color": NO_LEGEND_SCENARIO,
            },
            "layer": [
                {
                    "mark": {"type": "area", "opacity": 0.25},
                    "encoding": {
                        "y": {"field": "lower", "type": "quantitative", "title": "Occupancy",
                              "scale": {"domain": [0, 1.05]}},
                        "y2": {"field": "upper"},
                    },
                },
                {
                    "mark": {"type": "line", "strokeWidth": 2, "tooltip": True},
                    "encoding": {"y": {"field": "occupancy", "type": "quantitative"}},
                },
            ],
        },
    }


def spec_fragility() -> dict:
    return {
        "width": 420,
        "height": 260,
        "mark": {"type": "line", "strokeWidth": 2, "tooltip": True},
        "encoding": {
            "x": {"field": "pga", "type": "quantitative", "title": "PGA [g]"},
            "y": {"field": "probability", "type": "quantitative", "title": "Probability of damage",
                  "axis": {"format": "%"}},
            "color": NO_LEGEND_SCENARIO,
            "strokeDash": {"field": "damage_state", "type": "nominal", "title": "Damage state",
                           "sort": ["Slight", "Moderate", "Extensive", "Complete"]},
            "detail": {"field": "scenario_name"},
        },
    }


def spec_bridge_damage() -> dict:
    return {
        "width": 420,
        "height": 260,
        "transform": [
            {"calculate": "max(0, datum.mean - datum.sd)", "as": "lower"},
            {"calculate": "datum.mean + datum.sd", "as": "upper"},
        ],
        "encoding": {
            "x": {"field": "damage_state", "type": "nominal", "title": None,
                  "sort": ["Slight", "Moderate", "Extensive", "Complete"], "axis": AXIS_LABEL0},
            "xOffset": {"field": "scenario_name"},
        },
        "layer": [
            {
                "mark": {"type": "bar", "tooltip": True},
                "encoding": {
                    "y": {"field": "mean", "type": "quantitative",
                          "title": "Proportion of bridges in damage state"},
                    "color": NO_LEGEND_SCENARIO,
                },
            },
            {
                "mark": {"type": "rule", "strokeDash": [4, 3], "color": "#333333"},
                "encoding": {"y": {"field": "lower", "type": "quantitative"}, "y2": {"field": "upper"}},
            },
            {
                "mark": {"type": "tick", "color": "#333333", "size": 8, "thickness": 1.5},
                "encoding": {"y": {"field": "upper", "type": "quantitative"}},
            },
        ],
    }


def spec_pga_ensemble() -> dict:
    return {
        "width": 320,
        "height": 260,
        "encoding": {
            "x": {"field": "scenario_name", "type": "nominal", "title": "Earthquake magnitude",
                  "axis": AXIS_LABEL0},
        },
        "layer": [
            {
                "mark": {"type": "circle", "size": 40, "opacity": 0.8, "tooltip": True},
                "encoding": {
                    "y": {"field": "median_pga", "type": "quantitative",
                          "title": "Median PGA per scenario (g)"},
                    "color": {**NO_LEGEND_SCENARIO, "legend": None},
                },
            },
            {
                "mark": {"type": "tick", "color": "#111111", "thickness": 2, "size": 36},
                "encoding": {"y": {"field": "median_pga", "aggregate": "median", "type": "quantitative"}},
            },
        ],
    }


def spec_carbon_by_distance() -> dict:
    return {
        "width": 440,
        "height": 240,
        "mark": {"type": "bar", "tooltip": True},
        "encoding": {
            "x": {"field": "distance_band", "type": "ordinal", "title": "Distance (km)",
                  "sort": ["0-8", "8-16", "16-24", "24-32", "32-40", ">40"], "axis": AXIS_LABEL0},
            "xOffset": {"field": "scenario_name"},
            "y": {"field": "emission_kg", "type": "quantitative", "title": "Carbon emission (kg)"},
            "color": {**NO_LEGEND_SCENARIO, "legend": {"orient": "top"}},
        },
    }


def spec_lifecycle_gwp() -> dict:
    stages = ["A1-A3", "A4", "A5", "B4", "B6", "C3-C4"]
    return {
        "width": {"step": 120},
        "height": 260,
        "encoding": {
            "x": {"field": "scenario_name", "type": "nominal", "title": None, "axis": AXIS_LABEL0},
        },
        "layer": [
            {
                "mark": {"type": "bar", "tooltip": True},
                "encoding": {
                    "y": {"field": "gwp", "type": "quantitative", "title": "GWP (kg CO2e/m2/year)"},
                    "color": {
                        "field": "stage", "type": "nominal", "title": "Lifecycle stage",
                        "scale": {"domain": stages,
                                  "range": ["#0b3c49", "#cdebf5", "#7fb3b5", "#f7a541", "#fbefc8", "#e0812b"]},
                    },
                    "order": {"field": "order", "type": "quantitative"},
                },
            },
            {
                "mark": {"type": "text", "dy": -6, "baseline": "bottom", "fontWeight": "bold"},
                "encoding": {
                    "y": {"field": "gwp", "aggregate": "sum", "type": "quantitative"},
                    "text": {"field": "gwp", "aggregate": "sum", "type": "quantitative", "format": ".1f"},
                },
            },
        ],
    }


def spec_impact_share() -> dict:
    return {
        "facet": {"field": "scenario_name", "type": "nominal", "title": None,
                  "header": {"labelFontSize": 13, "labelFontWeight": "bold"}},
        "spec": {
            "width": 170,
            "height": 170,
            "transform": [
                {"calculate": "datum.component === 'Structural' ? datum.scenario_color : '#c4c4c4'",
                 "as": "slice_color"},
                {"calculate": "format(datum.share, '.1f') + '%'", "as": "label"},
            ],
            "encoding": {
                "theta": {"field": "share", "type": "quantitative", "stack": True},
                "order": {"field": "component", "sort": "descending"},
            },
            "layer": [
                {
                    "mark": {"type": "arc", "innerRadius": 40, "tooltip": True},
                    "encoding": {"color": {"field": "slice_color", "type": "nominal", "scale": None}},
                },
                {
                    "mark": {"type": "text", "radius": 62, "color": "white", "fontWeight": "bold"},
                    "encoding": {"text": {"field": "label"}},
                },
            ],
        },
    }


def spec_route_criteria() -> dict:
    criteria = [
        "Departure Time", "Travel Cost", "Road Importance",
        "Intersection Number", "Travel Distance", "Congestion Degree",
    ]
    return {
        "width": {"step": 115},
        "height": {"step": 70},
        "encoding": {
            "x": {"field": "criterion", "type": "nominal", "sort": criteria, "title": None,
                  "axis": {"orient": "top", "labelAngle": 0, "labelLimit": 0}},
            "y": {"field": "scenario_name", "type": "nominal", "title": None},
        },
        "layer": [
            {
                # Each route's square, in its scenario's color, at the row's start.
                "transform": [{"filter": f"datum.criterion === '{criteria[0]}'"}],
                "mark": {"type": "square", "size": 160, "xOffset": -44, "opacity": 1},
                "encoding": {"fill": {"field": "scenario_name", "type": "nominal", "legend": None}},
            },
            {
                "transform": [
                    {"filter": "datum.effect !== 0"},
                    {"calculate": "abs(datum.effect)", "as": "strength"},
                    {"calculate": "datum.effect > 0 ? 'positive' : 'negative'", "as": "sign"},
                ],
                "mark": {"type": "point", "filled": False, "strokeWidth": 3, "tooltip": True},
                "encoding": {
                    "size": {"field": "strength", "type": "quantitative", "title": "Effect",
                             "scale": {"domain": [0, 1], "range": [0, 1800]}},
                    "stroke": {"field": "sign", "type": "nominal", "title": None,
                               "scale": {"domain": ["positive", "negative"], "range": ["#e4572e", "#17605c"]}},
                },
            },
        ],
    }


def spec_green_wall() -> dict:
    columns = ["Scenario", "New U-value (W/m2K)", "Energy savings (kWh/year)", "CO2 reduction (kg/year)"]
    cell = {"field": "cell", "type": "nominal"}
    colored = {"field": "scenario_name", "type": "nominal", "legend": None}
    return {
        "width": {"step": 190},
        "height": {"step": 38},
        "transform": [
            {"calculate": "datum.scenario_name", "as": "Scenario"},
            {"calculate": "format(datum.u_value, '.2f')", "as": columns[1]},
            {"calculate": "format(datum.energy_savings, ',')", "as": columns[2]},
            {"calculate": "format(datum.co2_reduction, ',')", "as": columns[3]},
            {"fold": columns, "as": ["column", "cell"]},
        ],
        "encoding": {
            "x": {"field": "column", "type": "nominal", "sort": columns, "title": None,
                  "axis": {"orient": "top", "labelAngle": 0, "labelFontSize": 12, "labelFontWeight": "bold",
                           "labelColor": "#333333", "labelPadding": 8, "labelLimit": 0,
                           "domain": False, "ticks": False}},
            "y": {"field": "scenario_name", "type": "nominal", "sort": {"field": "scenario_order"}, "axis": None},
        },
        "layer": [
            {
                "mark": {"type": "rect", "stroke": "#d6d9de", "strokeWidth": 1},
                "encoding": {"fill": {"condition": {"test": "datum.scenario_order % 2 === 1", "value": "#f5f6f8"},
                                      "value": "#ffffff"}},
            },
            {
                "transform": [{"filter": "datum.column === 'Scenario'"}],
                "mark": {"type": "text", "fontSize": 13, "fontWeight": "bold", "tooltip": True},
                "encoding": {"text": cell, "color": colored},
            },
            {
                "transform": [{"filter": "datum.column !== 'Scenario'"}],
                "mark": {"type": "text", "fontSize": 13, "tooltip": True},
                "encoding": {"text": cell, "color": colored},
            },
        ],
        "config": {"view": {"stroke": None}},
    }


# key, CSV, table, label, chart title, goal, scenarios, spec
CHARTS = [
    ("occupancy", "carpark_occupancy.csv", carpark_occupancy, "Occupancy",
     "Carpark occupancy", "Compare four carparks' hourly occupancy on weekdays and off days, with the band the days spread over.",
     ["weekday", "offday"], spec_occupancy),
    ("fragility", "fragility_curves.csv", fragility_curves, "Fragility",
     "Bridge fragility curves", "Compare the as-built and retrofitted bridge's probability of each damage state as the ground shakes harder.",
     ["as-built", "retrofit"], spec_fragility),
    ("damage", "bridge_damage.csv", bridge_damage, "Damage",
     "Bridge damage states", "Compare the share of bridges in each damage state for M5, M6 and M7 events, with one standard deviation.",
     ["m5", "m6", "m7"], spec_bridge_damage),
    ("pga", "pga_ensemble.csv", pga_ensemble, "PGA",
     "Ground-motion ensemble", "Compare the spread of the median ground acceleration over each event's simulated scenarios.",
     ["m5", "m6", "m7"], spec_pga_ensemble),
    ("carbon", "carbon_by_distance.csv", carbon_by_distance, "Carbon",
     "Carbon by trip distance", "Compare the fleet's carbon emission by trip distance under the original plan and three priorities.",
     ["original", "lchg", "bc", "bc-rb"], spec_carbon_by_distance),
    ("gwp", "lifecycle_gwp.csv", lifecycle_gwp, "GWP",
     "Lifecycle GWP", "Compare the baseline's and the proposal's global warming potential, stage by stage.",
     ["baseline", "proposal"], spec_lifecycle_gwp),
    ("impact", "impact_share.csv", impact_share, "Impact",
     "Environmental impact share", "Compare how much of each solution's environmental impact is structural.",
     ["solution-1", "solution-2"], spec_impact_share),
    ("routes", "route_criteria.csv", route_criteria, "Criteria",
     "Route criteria", "Compare how each criterion weighs for or against three candidate routes.",
     ["route-1", "route-2", "route-3"], spec_route_criteria),
    ("green-wall", "green_wall.csv", green_wall, "Green wall",
     "Green wall performance", "Compare three green-wall systems' U-value, energy savings and CO2 reduction.",
     ["passive", "active", "intensive"], spec_green_wall),
]

PART_LABELS = {
    "carpark_occupancy.csv": "Carpark occupancy by hour, weekday and off day",
    "fragility_curves.csv": "Bridge fragility curves, as built and retrofitted",
    "bridge_damage.csv": "Bridge damage states for M5, M6 and M7 events",
    "pga_ensemble.csv": "Median PGA of each simulated scenario, M5, M6 and M7",
    "carbon_by_distance.csv": "Fleet carbon emission by trip distance, four priorities",
    "lifecycle_gwp.csv": "Building GWP by lifecycle stage, baseline and proposal",
    "impact_share.csv": "Structural share of two solutions' environmental impact",
    "route_criteria.csv": "Criteria weighing for or against three routes",
    "green_wall.csv": "Green-wall systems' U-value, energy savings and CO2 reduction",
}


# --- writing -----------------------------------------------------------------


def write_dataset() -> None:
    data_dir = DATASET_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for index, (_key, file_name, table, *_rest) in enumerate(CHARTS):
        rows = table()
        with open(data_dir / file_name, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        parts.append({
            "index": index, "label": PART_LABELS[file_name], "kind": "dataframe",
            "format": "csv", "file": f"data/{file_name}",
        })
    (data_dir / "bundle.json").write_text(json.dumps({"version": 1, "parts": parts}, indent=2) + "\n")
    manifest = {
        "id": DATASET_ID,
        "name": "Scenario Chart Gallery (mock)",
        "version": "1.0.0",
        "format": "bundle",
        "description": (
            "Mock data for nine kinds of scenario comparison, shaped like figures from the "
            "scenario-planning literature, one bundle of nine CSV tables, each row's scenario in "
            "its case column: " + "; ".join(
                f"{file_name} ({PART_LABELS[file_name].lower()})" for _k, file_name, *_ in CHARTS
            ) + ". The ScenarioCharts test dataflow loads it and compares each table's scenarios "
            "on a Vega-Lite node. The values are invented, not measured."
        ),
        "publisher": "Curio",
        "license": "MIT (this repository)",
        "tags": ["scenarios", "mock", "vega-lite", "uncertainty", "csv"],
        "dataFile": "data/bundle.json",
        "compatibility": {"major": 1},
        "sourceLabel": "Curio example data",
        "rowCount": None,
        "featureCount": None,
        "schema": None,
        "createdAt": "2026-10-08T00:00:00Z",
        "updatedAt": "2026-10-08T00:00:00Z",
        "sourceUpdatedAt": None,
        "sourceEncoding": None,
        "groupId": None,
        "layerName": None,
        "producerNodeId": None,
        "producerNodeType": None,
        "producerDataflowId": None,
        "producerDataflowName": None,
        "upstreamInputs": None,
        "discoverySource": None,
        "collection": None,
    }
    (DATASET_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def node_id(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


_COLOR_CHANNELS = {"color", "fill", "stroke"}
_ORDER_CHANNELS = {"x", "y", "xOffset", "yOffset", "row", "column", "facet", "shape"}
_SCENARIO_FIELDS = ("scenario", "scenario_name", "scenario_color", "scenario_order")


def _by_input(values) -> str:
    """A Vega expression picking a row's value by the circle it came in on."""
    quoted = ["'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'" for v in values]
    return "[" + ", ".join(quoted) + "][datum.__input__]"


def name_the_scenarios(spec: dict, ids: list, names: list, colors: list) -> dict:
    """*spec* over the node's inputs stacked (the dataset `inputs`, each row's
    `__input__` its circle), naming each circle's scenario itself: the
    scenario columns it reads, from `__input__`, and the scenarios' colors and
    order on the encodings of the scenario that set none of their own. The
    specs share encodings (``NO_LEGEND_SCENARIO``), so a copy is changed."""
    spec = copy.deepcopy(spec)
    text = json.dumps(spec)
    columns = {
        "scenario": _by_input(ids),
        "scenario_name": _by_input(names),
        "scenario_color": _by_input(colors),
        "scenario_order": "datum.__input__",
    }
    calculates = [{"calculate": columns[f], "as": f} for f in _SCENARIO_FIELDS if re.search(rf"\b{f}\b", text)]

    def visit(node) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key in ("data", "datasets"):
                continue
            if isinstance(value, dict) and value.get("field") in ("scenario", "scenario_name"):
                domain = ids if value["field"] == "scenario" else names
                if key in _COLOR_CHANNELS and "scale" not in value:
                    value["scale"] = {"domain": domain, "range": colors}
                elif key in _ORDER_CHANNELS and "sort" not in value:
                    value["sort"] = domain
            visit(value)

    visit(spec)
    transform = calculates + list(spec.get("transform") or [])
    out: dict = {}
    for key, value in spec.items():
        if key in ("data", "transform"):
            continue
        out[key] = value
        if key == "$schema":
            out["data"] = {"name": "inputs"}
            out["transform"] = transform
    if "data" not in out:
        out = {"data": {"name": "inputs"}, "transform": transform, **out}
    return out


def node(key, node_type, x, y, title, goal, content, extra_metadata=None) -> dict:
    metadata = {"keywords": [], **(extra_metadata or {}), "packageTemplateLabel": title}
    return {
        "id": node_id(key), "type": node_type, "x": x, "y": y, "content": content,
        "out": "DEFAULT", "in": "DEFAULT", "goal": goal, "metadata": metadata, "title": title,
    }


def edge(source: str, target: str, slot: int) -> dict:
    handle = "in" if slot == 0 else f"in_{slot}"
    return {
        "id": f"reactflow__edge-{source}out-{target}{handle}",
        "source": source, "target": target, "sourceHandle": "out", "targetHandle": handle,
    }


ROW_HEIGHT = 620
BRANCH_X, BRANCH_STEP = 760, 560
CHART_X = BRANCH_X + 4 * BRANCH_STEP + 120


def write_dataflow() -> None:
    loader = node(
        "loader", "curio.builtin/data-loading", 100, ROW_HEIGHT * 4,
        "Scenario chart data",
        "Load the nine mock tables from the Data Catalog, one bundle.",
        "# Nine mock tables from the Data Catalog, one bundle: each a figure's data, its\n"
        "# rows' scenario in the case column. They come back as a tuple, in the\n"
        "# bundle's order; each scenario's node takes its rows of one of them.\n"
        f'return curio_load_data("{DATASET_ID}")\n',
    )
    nodes, edges = [loader], []
    members: dict[str, list[str]] = {key: [] for key in SCENARIOS}
    for row, (key, file_name, _table, label, title, goal, scenarios, spec) in enumerate(CHARTS):
        y = row * ROW_HEIGHT
        # A plain Vega-Lite node: its spec names each circle's scenario itself.
        named = name_the_scenarios(
            {"$schema": VEGA_SCHEMA, **spec()},
            list(scenarios),
            [SCENARIOS[s][0] for s in scenarios],
            [SCENARIOS[s][1] for s in scenarios],
        )
        chart = node(f"chart/{key}", "curio.builtin/vis-vega", CHART_X, y, title, goal, json.dumps(named, indent=2))
        for slot, scenario in enumerate(scenarios):
            name = SCENARIOS[scenario][0]
            branch = node(
                f"branch/{key}/{scenario}", "curio.builtin/computation-analysis",
                BRANCH_X + slot * BRANCH_STEP, y, f"{label} - {name}",
                f"Keep the {name} rows of the {PART_LABELS[file_name][0].lower()}{PART_LABELS[file_name][1:]} table.",
                f"# Part {row} of the bundle, {file_name}: this scenario's rows, without\n"
                f"# the case column, for the chart comparing the scenarios.\n"
                f"table = input_0[{row}]\n"
                f'return table[table["case"] == "{name}"].drop(columns="case").reset_index(drop=True)\n',
            )
            nodes.append(branch)
            members[scenario].append(branch["id"])
            edges.append(edge(loader["id"], branch["id"], 0))
            edges.append(edge(branch["id"], chart["id"], slot))
        nodes.append(chart)
    dataflow = {
        "dataflow": {
            "categories": {"complexity": ["Beginner"]},
            "nodes": nodes,
            "edges": edges,
            "scenarios": [
                {"id": key, "name": name, "color": color, "nodes": members[key]}
                for key, (name, color) in SCENARIOS.items()
            ],
            "packages": [],
            "datasets": [{
                "datasetId": DATASET_ID, "dirName": f"{DATASET_ID}@1", "origin": "imported",
                "producerNodeId": None, "consumerNodeIds": [], "installedAt": "2026-10-08T00:00:00Z",
            }],
            "name": "ScenarioCharts",
            "task": "",
            "timestamp": 1791417600000,
            "provenance_id": "ScenarioCharts",
        }
    }
    DATAFLOW.write_text(json.dumps(dataflow, indent=2) + "\n")


def main() -> int:
    write_dataset()
    write_dataflow()
    print(f"wrote {DATASET_DIR.relative_to(REPO_ROOT)} and {DATAFLOW.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
