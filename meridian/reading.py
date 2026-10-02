"""How far to trust what a field says, given everyone who read it.

A clean sheet or a BOM cell is read exactly, once. A scan is read twice, by
OCR and by a vision model, and the two are compared. Agreement is the only
thing that earns "confirmed"; a lone reader is reported as such, and a
disagreement is reported with both readings rather than resolved by picking
the likelier one.
"""

import difflib
import re
from enum import StrEnum

from meridian.evidence import MACHINE_READ, Method, Observation

AGREE = 0.8            # similarity of the two readings, after normalisation, that counts as the same text
ABSTAIN_BELOW = 0.4    # a reader this unsure of itself is treated as having said nothing


class Status(StrEnum):
    EXACT = "exact"              # vector text or a CSV cell: characters are certain
    CONFIRMED = "confirmed"      # two independent readers agree
    SINGLE = "single reader"     # one reader produced it; the other could not
    DISPUTED = "disputed"        # two readers disagree; both readings are shown
    BLANK = "blank"              # the field is empty on the sheet
    ILLEGIBLE = "illegible"      # something is there and nobody could read it


def settle(readings: list[Observation]) -> tuple[Status, Observation | None]:
    """The status of one field and the reading to show for it, if any."""
    exact = [r for r in readings if r.method in (Method.PDF_TEXT, Method.CSV, Method.CURATED, Method.TRANSCRIBED)]
    if exact:
        return (Status.BLANK, exact[0]) if exact[0].blank else (Status.EXACT, exact[0])

    machine = [r for r in readings if r.method in MACHINE_READ]
    vision = next((r for r in machine if r.method == Method.VISION), None)
    ocr = next((r for r in machine if r.method == Method.OCR), None)
    speaking = [r for r in machine if not r.blank and (r.confidence is None or r.confidence >= ABSTAIN_BELOW)]

    if vision and (vision.parsed or {}).get("legibility") == "illegible" and not speaking:
        return Status.ILLEGIBLE, None
    if not speaking:
        said_blank = vision is not None and (vision.parsed or {}).get("legibility") == "blank"
        return (Status.BLANK, vision) if said_blank or not machine else (Status.ILLEGIBLE, None)
    if len(speaking) == 1:
        return Status.SINGLE, speaking[0]
    if agree(vision.value, ocr.value):
        return Status.CONFIRMED, vision  # the vision model reads characters better; OCR vouches for them
    return Status.DISPUTED, None


def agree(a: str, b: str) -> bool:
    """Text may differ by a stray character; numbers may not. "4153" and "415.3" are 0.89 similar
    as strings and a factor of ten apart as weights."""
    return _numbers(a) == _numbers(b) and similarity(a, b) >= AGREE


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", comparable(text))


def similarity(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, comparable(a), comparable(b)).ratio(), 2)


def comparable(text: str) -> str:
    """What two readers of the same print should both produce: letters, digits and separators."""
    text = text.upper().replace("@", "Ø").replace(",", ".")
    return re.sub(r"[^0-9A-ZÆØÅ.+\-±↧⌴:/]", "", text)
