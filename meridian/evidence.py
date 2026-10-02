"""The unit of knowledge: one source said one thing in one place.

An observation records what was read and where. It never records what is true.
Agreement, conflict and illegibility are worked out later by comparing
observations, and when a person settles a question that decision is stored as
one more observation. Nothing here is ever edited in place.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path


class Method(StrEnum):
    PDF_TEXT = "pdf-text"        # vector text in a clean PDF: exact characters, exact position
    OCR = "ocr"                  # tesseract on a raster scan
    VISION = "vision"            # a vision model reading a raster scan
    CSV = "csv"                  # a BOM cell exactly as exported
    TRANSCRIBED = "transcribed"  # typed in by a person, e.g. labels on a system diagram
    CURATED = "curated"          # a person's judgement recorded in curation/, e.g. which BOM row a sheet documents
    REVIEW = "review"            # a correction proposed in chat and accepted in review


MACHINE_READ = {Method.OCR, Method.VISION}


@dataclass(frozen=True, slots=True)
class Source:
    """Enough to put a finger on the evidence: a page region or a BOM cell."""

    doc: str                                           # "D-011", "BOM", "diagram:Zaxis_legend", "C-001"
    page: int | None = None                            # 1-based
    bbox: tuple[float, float, float, float] | None = None  # PDF points (image pixels for diagrams)
    row: int | None = None                             # spreadsheet row; the header is row 1
    column: str | None = None                          # BOM column name as written

    def label(self) -> str:
        if self.row is not None:
            return f"BOM row {self.row} · {self.column}"
        if self.page is not None:
            return f"{self.doc} sheet {self.page}"
        return self.doc


@dataclass(frozen=True, slots=True)
class Observation:
    id: str
    subject: str            # what it is about: "D-011", "BOM.30"
    field: str              # "material", "weight", "annotation", ...
    value: str              # exactly as read; "" means the field exists and is empty
    source: Source
    method: Method
    confidence: float | None = None  # the reader's own estimate, when it gives one
    parsed: dict | None = None       # an interpretation of value; never a replacement for it
    note: str = ""

    @property
    def blank(self) -> bool:
        return not self.value.strip()


def write_jsonl(path: Path, observations: Iterable[Observation]) -> int:
    rows = sorted(observations, key=lambda o: o.id)
    ids = [o.id for o in rows]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate observation ids: {dupes[:5]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for o in rows:
            f.write(json.dumps(_compact(asdict(o)), ensure_ascii=False) + "\n")
    return len(rows)


def read_jsonl(path: Path) -> Iterator[Observation]:
    with path.open() as f:
        for line in f:
            d = json.loads(line)
            src = d.pop("source")
            if src.get("bbox"):
                src["bbox"] = tuple(src["bbox"])
            yield Observation(source=Source(**src), method=Method(d.pop("method")), **d)


def _compact(d: dict) -> dict:
    """Drop empty optional keys so the committed JSONL stays readable in a diff."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            v = _compact(v) if k == "source" else v
        if v is None or (k == "note" and v == ""):
            continue
        out[k] = v
    return out
