"""The Crown Heights example's table on two of its days, shared by the CPU
reference (``test_scripts/test_bedford_shadow_example.py``, a NumPy mirror of
the example's GPU steps) and the dashboard e2e
(``test_frontend/test_crown_heights_dashboard_e2e.py``, the GPU itself), so
the GPU has to give what the CPU does.

Each row is keyed by the table's headers. The window's texts are what the
table shows. The three durations are the CPU's minutes on Block 1259's open
ground, which the table shows rounded to the minute ("3 h 55 min").
"""

WINTER = {
    "Day": "Winter solstice",
    "From": "8:46 AM EST",
    "To": "3:01 PM EST",
    "Time counted": "6 h 15 min",
    "Without the proposed building": 235.16,
    "With the proposed building": 260.73,
    "Added": 25.57,
}

SUMMER = {
    "Day": "Summer solstice",
    "From": "6:55 AM EDT",
    "To": "7:00 PM EDT",
    "Time counted": "12 h 5 min",
    "Without the proposed building": 330.81,
    "With the proposed building": 330.81,
    # The proposed building's shadow never reaches the block in summer.
    "Added": 0.0,
}

#: The three durations, in the table's order.
DURATIONS = ("Without the proposed building", "With the proposed building", "Added")

#: How far the GPU's minutes may sit from the CPU's. The GPU works in 32-bit
#: floats and may fuse a multiply and an add, so a ray that grazes a cell's
#: edge can land on the other side of it. Winter's Added sits 0.07 min from
#: a rounding boundary of what the table shows, so compare minutes, not text.
TOLERANCE_MIN = 1.0


def minutes(text: str) -> float:
    """A duration as the table shows it ("3 h 55 min", "4 h", "26 min"), in
    minutes."""
    total = 0.0
    words = text.split()
    for number, unit in zip(words[::2], words[1::2]):
        total += float(number) * (60 if unit == "h" else 1)
    return total
