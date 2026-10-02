"""Just enough of ISO 286 to check a fit reading for internal consistency.

Two facts are used, both exact in the standard:

- the width of a tolerance band (upper minus lower deviation) is the IT value
  for the size and the grade, e.g. 52 µm for IT7 between 250 and 315 mm;
- an H bore always has a lower deviation of zero, an h shaft an upper one.

Every fit callout on the clean sheets passes both. A reading that fails one has
a misread letter or number: the vision model read D-023's "j7 +0,026/-0,026" as
"H7", which keeps the right band (52 µm, IT7) and breaks the H rule.
"""

import re

# Standard tolerance grades in µm, ISO 286-1 table 1, nominal sizes up to 500 mm.
#             upper limit of the size range: (IT6, IT7, IT8, IT9)
IT = [
    (3, (6, 10, 14, 25)), (6, (8, 12, 18, 30)), (10, (9, 15, 22, 36)), (18, (11, 18, 27, 43)),
    (30, (13, 21, 33, 52)), (50, (16, 25, 39, 62)), (80, (19, 30, 46, 74)), (120, (22, 35, 54, 87)),
    (180, (25, 40, 63, 100)), (250, (29, 46, 72, 115)), (315, (32, 52, 81, 130)), (400, (36, 57, 89, 140)),
    (500, (40, 63, 97, 155)),
]
GRADES = (6, 7, 8, 9)


def it_value(size_mm: float, grade: int) -> int | None:
    if grade not in GRADES or size_mm <= 0:
        return None
    for upper, values in IT:
        if size_mm <= upper:
            return values[GRADES.index(grade)]
    return None


def problems(fit: str, size: float | None, upper: float | None, lower: float | None) -> list[str]:
    """What is inconsistent about this reading, in words an engineer would use. Empty when it holds together."""
    m = re.fullmatch(r"(JS|js|[A-Za-z])(\d{1,2})", fit)
    if not m:
        return []
    letter, grade = m.group(1), int(m.group(2))
    # The fixed deviation is often left unprinted; by definition it is zero.
    if letter == "H" and lower is None and upper is not None:
        lower = 0.0
    if letter == "h" and upper is None and lower is not None:
        upper = 0.0
    out = []
    if letter == "H" and lower not in (None, 0):
        out.append(f"an {fit} bore has a lower deviation of 0, but this reads {lower:+g}")
    if letter == "h" and upper not in (None, 0):
        out.append(f"an {fit} shaft has an upper deviation of 0, but this reads {upper:+g}")
    if size and upper is not None and lower is not None and (expected := it_value(size, grade)):
        band = round((upper - lower) * 1000)
        if band != expected:
            out.append(f"the band is {band} µm, but IT{grade} at Ø{size:g} is {expected} µm")
    return out


def describe(fit: str, size: float, upper: float, lower: float) -> str:
    """One line saying why a reading holds together, for the review page."""
    grade = int(re.sub(r"\D", "", fit))
    expected = it_value(size, grade)
    band = round((upper - lower) * 1000)
    side = "straddles zero, as j and js classes do" if lower < 0 < upper else "sits on one side of zero"
    return f"band {band} µm, IT{grade} at Ø{size:g} is {expected} µm; the band {side}"
