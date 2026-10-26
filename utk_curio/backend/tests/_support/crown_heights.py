"""The Crown Heights example's four days and its table of the months, shared
by the CPU reference (``test_scripts/test_bedford_shadow_example.py``, a NumPy
mirror of the example's GPU steps) and the dashboard e2e
(``test_frontend/test_crown_heights_dashboard_e2e.py``, the GPU itself), so
the GPU has to give what the CPU does.

A day's row holds its window as the day's plot shows it, the time the window
counts, and the CPU's minutes in shadow on Block 1259's open ground that day,
which the year's plot draws. A month's row holds the table's text and the
CPU's figures before rounding.
"""

SPRING = {
    "Day": "Spring equinox",
    "Date": "2027-03-20",
    "From": "8:30 AM EDT",
    "To": "5:38 PM EDT",
    "Time counted": "9 h 8 min",
    "Without the proposed building": 275.9,
    "With the proposed building": 275.9,
    # Nor at the equinoxes: only in winter is the sun low enough.
    "Added": 0.0,
}

WINTER = {
    "Day": "Winter solstice",
    "Date": "2027-12-21",
    "From": "8:46 AM EST",
    "To": "3:01 PM EST",
    "Time counted": "6 h 15 min",
    "Without the proposed building": 235.16,
    "With the proposed building": 260.73,
    "Added": 25.57,
}

SUMMER = {
    "Day": "Summer solstice",
    "Date": "2027-06-21",
    "From": "6:55 AM EDT",
    "To": "7:00 PM EDT",
    "Time counted": "12 h 5 min",
    "Without the proposed building": 330.81,
    "With the proposed building": 330.81,
    # The proposed building's shadow never reaches the block in summer.
    "Added": 0.0,
}

FALL = {
    "Day": "Fall equinox",
    "Date": "2027-09-23",
    "From": "8:14 AM EDT",
    "To": "5:22 PM EDT",
    "Time counted": "9 h 7 min",
    "Without the proposed building": 275.76,
    "With the proposed building": 275.76,
    "Added": 0.0,
}

#: The four days in the order the Day radio lists them.
FOUR_DAYS = (SPRING, SUMMER, FALL, WINTER)

#: A day's three durations.
DURATIONS = ("Without the proposed building", "With the proposed building", "Added")

#: The table's second column.
MONTH_HEADER = "Shade added per day (average ± standard deviation)"


def _month(name: str, shown: str, average: float, sd: float) -> dict:
    return {"Month": name, MONTH_HEADER: shown, "average": average, "sd": sd}


#: The table of the months: the shade the proposed building adds to Block
#: 1259's open ground a day, each month's average over its days and their
#: standard deviation, in minutes. Only from November to February does its
#: shadow reach the block, and in October on a few days.
MONTHS = (
    _month("January", "19 ± 4 min", 19.38, 3.86),
    _month("February", "2 ± 2 min", 2.15, 2.38),
    _month("March", "0 ± 0 min", 0.0, 0.0),
    _month("April", "0 ± 0 min", 0.0, 0.0),
    _month("May", "0 ± 0 min", 0.0, 0.0),
    _month("June", "0 ± 0 min", 0.0, 0.0),
    _month("July", "0 ± 0 min", 0.0, 0.0),
    _month("August", "0 ± 0 min", 0.0, 0.0),
    _month("September", "0 ± 0 min", 0.0, 0.0),
    _month("October", "0 ± 1 min", 0.47, 0.73),
    _month("November", "13 ± 6 min", 13.46, 6.39),
    _month("December", "25 ± 1 min", 24.55, 1.05),
)

#: How far the GPU's minutes may sit from the CPU's. The GPU works in 32-bit
#: floats but may divide and fuse a multiply and an add its own way, so a ray
#: that grazes a cell's edge can land on the other side of it: a day's
#: minutes move by a sliver of a minute.
TOLERANCE_MIN = 1.0

#: How far the GPU's figure for a month may sit from the CPU's before the
#: table rounds it. Of 2027's 11.7 million rays a scenario on the block,
#: Metal and SwiftShader put 79, at 12 steps, on the other side of a cell's
#: edge from the CPU. A ray is 0.017 min of a day, and those 79 moved a
#: month's average or deviation by 0.012 min at most. October's average, 0.47,
#: sits 0.03 min from the edge between "0" and "1", so the table may show
#: either.
MONTH_TOLERANCE_MIN = 0.25


def minutes(text: str) -> float:
    """A duration as the example writes it ("3 h 55 min", "4 h", "26 min"), in
    minutes."""
    total = 0.0
    words = text.split()
    for number, unit in zip(words[::2], words[1::2]):
        total += float(number) * (60 if unit == "h" else 1)
    return total


def average_and_sd(text: str) -> tuple[int, int]:
    """A month's cell as the table shows it ("19 ± 4 min"): its average and
    standard deviation, in whole minutes."""
    average, plus_minus, sd, unit = text.split()
    assert plus_minus == "±" and unit == "min", text
    return int(average), int(sd)
