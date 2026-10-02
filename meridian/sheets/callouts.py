"""Turn loose text on a sheet into callouts, and read what a callout says.

A SolidWorks callout arrives in pieces: "2 x", a Ø that is drawn as a polyline
rather than typed, "5,0 THRU ALL", and the thread on the line below. Stacked
tolerances and limit dimensions are separate pieces too. Pieces merge when they
sit on one line with a small gap between them, or stack directly on top of
each other.

Numbers use a decimal comma on these sheets ("262,0") except in the title
block weight ("117.3"); both are accepted.
"""

import math
import re
from dataclasses import dataclass
from statistics import median

from meridian.sheets.template import Rect

SYMBOLS = ("Ø", "↧", "±", "⌴")

LINE_GAP = 10.0      # points between pieces on one line; bridges the space SolidWorks leaves around symbols
STACK_GAP = 3.0      # points between stacked rows of one callout
LIMIT_PITCH = 0.85   # limit pairs overlap their rows; separate dimensions sit a full line apart


@dataclass(frozen=True, slots=True)
class Span:
    text: str
    rect: Rect
    direction: tuple[float, float] = (1.0, 0.0)
    padded: bool = False               # SolidWorks pads free-standing dimension text with spaces
    confidence: float | None = None    # OCR word confidence, 0..1


@dataclass(frozen=True, slots=True)
class Callout:
    spans: tuple[Span, ...]

    @property
    def rect(self) -> Rect:
        return (
            min(s.rect[0] for s in self.spans), min(s.rect[1] for s in self.spans),
            max(s.rect[2] for s in self.spans), max(s.rect[3] for s in self.spans),
        )

    @property
    def text(self) -> str:
        rows = _rows(self.spans)
        lines = [_join([s.text for s in row]) for row in rows]
        return " / ".join(line for line in lines if line)

    @property
    def confidence(self) -> float | None:
        scores = [s.confidence for s in self.spans if s.confidence is not None]
        return round(min(scores), 2) if scores else None

    @property
    def stacked_pair(self) -> bool:
        """Two bare numbers sharing a left edge and overlapping rows: how SolidWorks prints a limit dimension."""
        numbers = [s for s in self.spans if _NUMBER_ONLY.match(s.text)]
        if len(numbers) != 2 or len(self.spans) != 2 or any(s.padded for s in numbers):
            return False
        (au, av), (bu, bv) = sorted((_extent(s) for s in numbers), key=lambda e: e[1][0])
        height = av[1] - av[0]
        return abs(au[0] - bu[0]) < 1.5 and (bv[0] - av[0]) < LIMIT_PITCH * height

    def parsed(self) -> dict:
        return parse(self.text, stacked_pair=self.stacked_pair)


def group(spans: list[Span]) -> list[Callout]:
    """Union pieces that belong together, then order callouts top-to-bottom, left-to-right."""
    parent = list(range(len(spans)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            if _together(spans[i], spans[j]):
                parent[root(i)] = root(j)

    clusters: dict[int, list[Span]] = {}
    for i, span in enumerate(spans):
        clusters.setdefault(root(i), []).append(span)
    callouts = [part for c in clusters.values() for part in _split_at_counts(Callout(tuple(c)))]
    return sorted(callouts, key=lambda c: (round(c.rect[1] / 10), c.rect[0]))


def _split_at_counts(callout: Callout) -> list[Callout]:
    """Hole callouts listed under each other touch; each one starts with its own "N x"."""
    rows = _rows(callout.spans)
    parts: list[list[Span]] = []
    for row in rows:
        starts_new = _COUNT.match(_join([s.text for s in row])) is not None
        if starts_new and parts and any(_COUNT.match(_join([s.text for s in r])) for r in _rows(tuple(parts[-1]))):
            parts.append([])
        if not parts:
            parts.append([])
        parts[-1].extend(row)
    return [Callout(tuple(p)) for p in parts]


def _together(a: Span, b: Span) -> bool:
    if a.text in SYMBOLS or b.text in SYMBOLS:
        # Symbols carry no direction; they belong to whatever text they touch or sit in line with.
        return _near(a.rect, b.rect, 4.0) or _in_line(_extent(a, (1.0, 0.0)), _extent(b, (1.0, 0.0)))
    if math.dist(a.direction, b.direction) > 0.05:
        return False
    if _near(a.rect, b.rect, 0.5):
        return True  # corner to corner, as a fit code sits against its nominal
    ea, eb = _extent(a), _extent(b)
    return _in_line(ea, eb) or _stacked(ea, eb)


def _in_line(a: tuple, b: tuple) -> bool:
    (au0, au1), (av0, av1) = a
    (bu0, bu1), (bv0, bv1) = b
    along_gap = max(au0, bu0) - min(au1, bu1)
    across_overlap = min(av1, bv1) - max(av0, bv0)
    return across_overlap >= 0.4 * min(av1 - av0, bv1 - bv0) and along_gap <= LINE_GAP


def _stacked(a: tuple, b: tuple) -> bool:
    (au0, au1), (av0, av1) = a
    (bu0, bu1), (bv0, bv1) = b
    along_gap = max(au0, bu0) - min(au1, bu1)
    across_gap = max(av0, bv0) - min(av1, bv1)
    return along_gap < 0 and across_gap <= STACK_GAP


def _near(a: Rect, b: Rect, pad: float) -> bool:
    return a[0] - pad <= b[2] and b[0] - pad <= a[2] and a[1] - pad <= b[3] and b[1] - pad <= a[3]


def _extent(span: Span, direction: tuple[float, float] | None = None) -> tuple[tuple[float, float], tuple[float, float]]:
    """The span's interval along a baseline (u) and across it (v); by default its own baseline."""
    ux, uy = direction or span.direction
    vx, vy = -uy, ux
    x0, y0, x1, y1 = span.rect
    corners = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
    us = [x * ux + y * uy for x, y in corners]
    vs = [x * vx + y * vy for x, y in corners]
    return (min(us), max(us)), (min(vs), max(vs))


def _rows(spans: tuple[Span, ...]) -> list[list[Span]]:
    """Reading order in the callout's own frame, so rotated dimensions read the right way round."""
    frame = next((s.direction for s in spans if s.text not in SYMBOLS), (1.0, 0.0))
    extents = {id(s): _extent(s, frame) for s in spans}
    keyed = sorted(spans, key=lambda s: extents[id(s)][1][0])
    height = median(e[1][1] - e[1][0] for e in extents.values())
    rows: list[list[Span]] = []
    for span in keyed:
        centre = sum(extents[id(span)][1]) / 2
        if rows and abs(centre - sum(extents[id(rows[-1][0])][1]) / 2) < 0.45 * height:
            rows[-1].append(span)
        else:
            rows.append([span])
    return [sorted(row, key=lambda s: extents[id(s)][0][0]) for row in rows]


def _join(pieces: list[str]) -> str:
    out = ""
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        glue = out.endswith(SYMBOLS) or not out
        out += piece if glue else " " + piece
    # "+ 0,1" is one deviation; "M6 - 6H" is a thread and keeps its spaces.
    return re.sub(r"(?<!\w)([+\-±])\s+(?=\d+,\d)", r"\1", out)


# --- reading a callout -------------------------------------------------------

_NUM = r"\d+(?:[.,]\d+)?"
_NUMBER_ONLY = re.compile(rf"^\s*{_NUM}\s*$")
_TAP = re.compile(r"TAP FOR\s+(M[\d.,]+(?:x[\d.,]+)?)\s*(HELICOIL)?[^/]*", re.I)
_THREAD = re.compile(rf"\bM({_NUM})(?:\s*x\s*({_NUM}))?(?:\s*-\s*(\d[gGhH]))?(?:\s*↧\s*({_NUM}))?")
_COUNT = re.compile(r"(?:^|/)\s*(\d+)\s*[xX](?=[\s⌴Ø\d]|$)")  # at the start of any line of the callout
_ANGLED = re.compile(rf"({_NUM})\s*[xX]\s*({_NUM})\s*°")
_ANGLE = re.compile(rf"({_NUM})\s*°")
_COUNTERBORE = re.compile(rf"⌴\s*Ø?\s*({_NUM})(?:\s*↧\s*({_NUM}))?")
_DEPTH = re.compile(rf"↧\s*({_NUM})(?:\s*±\s*({_NUM}))?")
_RADIUS = re.compile(rf"\bR\s?({_NUM})")
_FIT = re.compile(r"(?<![A-Za-z\d])(JS|js|[HGFJKNP]|[hgfjknp])(\d{1,2})(?![\d.,])")
_DEVIATION = re.compile(rf"(?<![\w.,])([+\-±])\s*({_NUM})")
_NUMBER = re.compile(_NUM)
_WORD = re.compile(r"[A-Za-zÆØÅæøå]{2,}")
_LAYOUT_WORDS = {"THRU", "ALL", "SECTION", "DETAIL", "SCALE", "VIEW"}
_VIEW_LABELS = ("SECTION", "DETAIL", "VIEW", "SCALE")
_SLOT = re.compile(rf"({_NUM})\s*X\s*({_NUM})(?!\s*°)")  # "4 x 5,5 X 10,0 THRU ALL": slot width by length


def parse(text: str, stacked_pair: bool = False) -> dict:
    """Read a callout's text into numbers with meaning.

    Lines that are prose ("Obs. Ekstra undersænkning", "for M8 weld nut") are
    kept as a remark and never mined for numbers.
    """
    lines = text.split(" / ")
    views = [line for line in lines if line.lstrip().upper().startswith(_VIEW_LABELS)]
    prose = [line for line in lines if line not in views and _is_prose(line)]
    text = " / ".join(line for line in lines if line not in views and line not in prose)

    out: dict = _read_numbers(text, stacked_pair) if text else {}
    out["kind"] = _kind(out) if out else ("note" if prose else "view" if views else "unread")
    if prose:
        out["remark"] = " / ".join(prose)
    if views:
        out["view"] = " / ".join(views)
    return out


def _is_prose(line: str) -> bool:
    words = {w.upper() for w in _WORD.findall(line)}
    return bool(words - _LAYOUT_WORDS - {"TAP", "FOR", "HELICOIL", "INSERT", "DIA"})


def _read_numbers(text: str, stacked_pair: bool) -> dict:
    out: dict = {}
    rest = text

    if m := _TAP.search(rest):
        out["tap"] = m.group(1) + (" helicoil" if m.group(2) else "")
        rest = rest[: m.start()] + rest[m.end():]
    threads = [_thread(m) for m in _THREAD.finditer(rest)]
    if threads:
        out["thread"] = threads[0] if len(threads) == 1 else threads
        rest = _THREAD.sub(" ", rest)
    if m := _COUNT.search(rest):
        out["count"] = int(m.group(1))
        rest = rest[: m.start()] + " / " + rest[m.end():]
    for m in _ANGLED.finditer(rest):
        size, angle = _num(m.group(1)), _num(m.group(2))
        out["chamfer" if angle == 45 else "countersink"] = {"size": size, "angle": angle}
    rest = _ANGLED.sub(" ", rest)
    if m := _SLOT.search(rest):
        out["slot"] = {"width": _num(m.group(1)), "length": _num(m.group(2))}
        rest = rest[: m.start()] + rest[m.end():]
    if m := _COUNTERBORE.search(rest):
        out["counterbore"] = {"diameter": _num(m.group(1))} | ({"depth": _num(m.group(2))} if m.group(2) else {})
        rest = rest[: m.start()] + rest[m.end():]
    if m := _DEPTH.search(rest):
        out["depth"] = _num(m.group(1))
        if m.group(2):
            out["depth_tolerance"] = _num(m.group(2))
        rest = rest[: m.start()] + rest[m.end():]
    if m := _RADIUS.search(rest):
        out["radius"] = _num(m.group(1))
        rest = rest[: m.start()] + rest[m.end():]
    angles = [_num(a) for a in _ANGLE.findall(rest)]
    if angles:
        out["angle"] = angles[0]
        rest = _ANGLE.sub(" ", rest)
    fits = [a + b for a, b in _FIT.findall(rest)]
    if fits:
        out["fit"] = fits[0]
        rest = _FIT.sub(" ", rest)
    deviations = [_num(v) * (-1 if sign == "-" else 1) for sign, v in _DEVIATION.findall(rest)]
    symmetric = "±" in rest
    rest = _DEVIATION.sub(" ", rest)

    numbers = [_num(n) for n in _NUMBER.findall(rest)]
    if deviations or fits:
        # The lower deviation of an H-fit or a one-sided tolerance prints as a bare "0,000".
        deviations += [n for n in numbers if n == 0]
    numbers = [n for n in numbers if n != 0]  # a stray "0,000" is a deviation that lost its partner, never a size
    if symmetric and deviations:
        out["tolerance"] = {"plus_minus": abs(deviations[0])}
    elif len(deviations) >= 2:
        out["tolerance"] = {"upper": max(deviations), "lower": min(deviations)}
    elif deviations:
        out["tolerance"] = {"upper" if deviations[0] > 0 else "lower": deviations[0]}

    diameter = re.search(rf"(?<!⌴)Ø\s*({_NUM})", text)
    if diameter:
        out["diameter"] = _num(diameter.group(1))
        numbers = [n for n in numbers if n != out["diameter"]]
    if "THRU" in text.upper():
        out["thru"] = True

    if stacked_pair and len(numbers) == 2 and not out:
        out["limits"] = sorted(numbers)
    elif len(numbers) == 1:
        out["value"] = numbers[0]
    elif numbers:
        out["values"] = numbers
    return out


def _kind(p: dict) -> str:
    if "thread" in p or "tap" in p or "counterbore" in p or "slot" in p or ("diameter" in p and ("count" in p or "thru" in p or "depth" in p)):
        return "hole"
    if "limits" in p:
        return "limit"
    if "fit" in p:
        return "fit"
    if "chamfer" in p or "countersink" in p:
        return "edge"
    if "radius" in p:
        return "radius"
    if "angle" in p and len(p) == 1:
        return "angle"
    return "dimension"


def _thread(m: re.Match) -> str:
    """"M4 - 6H ↧8,0" -> "M4-6H, 8 deep"; the depth after a thread is the thread's own."""
    size, pitch, tolerance, depth = m.groups()
    out = f"M{size.replace(',', '.')}"
    if pitch:
        out += f"x{pitch.replace(',', '.')}"
    if tolerance:
        out += f"-{tolerance}"
    if depth:
        out += f", {_num(depth):g} deep"
    return out


def _num(s: str) -> float:
    return float(s.replace(",", "."))
