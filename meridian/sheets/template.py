"""The SolidWorks A3 sheet format that every drawing in the corpus uses.

All 22 clean sheets put the title block at identical coordinates, so fields are
read by cell instead of by guessing at layout. Coordinates are PDF points on a
1190.55 x 841.89 landscape page. Scans are registered onto these coordinates
before the same cells are applied (see scan.py).
"""

type Rect = tuple[float, float, float, float]

PAGE_SIZE = (1190.55, 841.89)

# Value cells only; the printed labels sit just above or to the left of them.
# The designer's name, email and phone are in the block too and are left out
# on purpose: they are not engineering knowledge.
FIELDS: dict[str, Rect] = {
    "note":     (740.0, 666.0, 972.0, 768.0),
    "title":    (972.0, 718.0, 1160.0, 768.0),
    "material": (786.0, 768.0, 926.0, 787.0),
    "weight":   (926.0, 768.0, 976.0, 787.0),
    "date":     (926.0, 800.0, 976.0, 814.0),
    "scale":    (1080.0, 800.0, 1121.0, 814.0),
    "sheet":    (1121.0, 800.0, 1160.0, 814.0),
}

TITLE_BLOCK: Rect = (735.0, 650.0, 1180.0, 820.0)

# Text the template itself prints, measured on the clean sheets. Anything inside
# these boxes is a label, never a value, however badly OCR spells it. On scans
# the first word of each label is also a landmark for registration.
LABELS: dict[str, Rect] = {
    "NOTE:": (741.5, 658.9, 757.2, 666.7),
    "COMPANY:": (975.3, 658.9, 1006.1, 666.7),
    "TITLE/DESCRIPTION:": (975.3, 710.4, 1025.3, 718.1),
    "MATERIAL:": (745.3, 772.0, 783.8, 783.0),
    "WEIGHT": (880.7, 772.0, 909.0, 783.0),
    "[g]:": (911.6, 772.0, 924.4, 783.0),
    "FINISH:": (744.4, 795.3, 768.5, 806.2),
    "DRAWN": (893.3, 791.2, 914.4, 799.0),
    "DATE": (897.0, 803.6, 910.6, 811.3),
    "UNLESS": (979.0, 777.1, 997.0, 784.8),
    "DIMENSIONS": (979.0, 784.1, 1012.0, 791.9),
    "TOLERANCES:": (979.0, 791.2, 1016.5, 799.0),
    "DEBURR": (1078.8, 781.6, 1099.0, 789.3),
}
VALUE_PREFIX = {"scale": "SCALE:", "sheet": "SHEET"}  # printed in the same text run as the value

# Outside this frame are the zone letters and numbers printed around the border.
DRAWING_FRAME: Rect = (62.0, 36.0, 1158.0, 806.0)


def inside(rect: Rect, cell: Rect) -> bool:
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    return cell[0] <= cx <= cell[2] and cell[1] <= cy <= cell[3]


def shifted(cell: Rect, dx: float, dy: float) -> Rect:
    return (cell[0] + dx, cell[1] + dy, cell[2] + dx, cell[3] + dy)


def is_label(rect: Rect, dx: float = 0.0, dy: float = 0.0) -> bool:
    return any(inside(rect, shifted(box, dx, dy)) for box in LABELS.values())
