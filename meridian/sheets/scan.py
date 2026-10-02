"""Read a degraded scan with OCR, registered onto the sheet template.

The eight scans have no text layer: each page is one grayscale JPEG of the
original sheet, blurred, faded, locally occluded or rotated by a fraction of a
degree. Tesseract reads them at twice their stored resolution. Its output is
one of two independent readings; the vision model is the other (vision.py),
and neither is trusted on its own.

Two of the scans are shifted and cropped by a few points, so the printed
title-block labels ("MATERIAL:", "DRAWN", ...) are found first and the
template cells moved to match before any field is read.
"""

import io
import re
import subprocess
from dataclasses import dataclass
from statistics import median

import pymupdf
from PIL import Image

from meridian.corpus import Drawing
from meridian.evidence import Method, Observation, Source
from meridian.sheets import template
from meridian.sheets.callouts import Callout, Span, group, parse
from meridian.sheets.fields import MARKER, parse_field

UPSCALE = 2
MIN_CALLOUT_CONFIDENCE = 0.5  # below this tesseract is usually reading grain, not text


@dataclass(frozen=True, slots=True)
class ScanPage:
    image: Image.Image
    page_rect: tuple[float, float, float, float]   # where the image sits on the page, in points

    def to_points(self, box: tuple[float, float, float, float], scale: float = 1.0) -> tuple[float, ...]:
        x0, y0, x1, y1 = self.page_rect
        sx = (x1 - x0) / (self.image.width * scale)
        sy = (y1 - y0) / (self.image.height * scale)
        return (round(x0 + box[0] * sx, 1), round(y0 + box[1] * sy, 1),
                round(x0 + box[2] * sx, 1), round(y0 + box[3] * sy, 1))

    def to_pixels(self, rect: tuple[float, ...]) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = self.page_rect
        sx, sy = self.image.width / (x1 - x0), self.image.height / (y1 - y0)
        return (int((rect[0] - x0) * sx), int((rect[1] - y0) * sy),
                int((rect[2] - x0) * sx), int((rect[3] - y0) * sy))


@dataclass(frozen=True, slots=True)
class Registration:
    dx: float
    dy: float
    landmarks: int

    def cell(self, field: str) -> tuple[float, float, float, float]:
        return template.shifted(template.FIELDS[field], self.dx, self.dy)

    @property
    def title_block(self) -> tuple[float, float, float, float]:
        return template.shifted(template.TITLE_BLOCK, self.dx, self.dy)


def scan_pages(drawing: Drawing) -> list[ScanPage]:
    pages = []
    with pymupdf.open(drawing.path) as doc:
        for page in doc:
            (info,) = page.get_images()  # a scan page is exactly one image
            xref = info[0]
            image = Image.open(io.BytesIO(doc.extract_image(xref)["image"])).convert("L")
            r = page.get_image_rects(xref)[0]
            pages.append(ScanPage(image, (r.x0, r.y0, r.x1, r.y1)))
    return pages


def ocr_words(scan: ScanPage) -> list[Span]:
    big = scan.image.resize((scan.image.width * UPSCALE, scan.image.height * UPSCALE), Image.LANCZOS)
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    tsv = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "11", "tsv"],
        input=buf.getvalue(), capture_output=True, check=True,
    ).stdout.decode()
    words = []
    for line in tsv.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or cols[0] != "5" or not cols[11].strip() or float(cols[10]) < 0:
            continue
        left, top, width, height = map(int, cols[6:10])
        box = scan.to_points((left, top, left + width, top + height), scale=UPSCALE)
        words.append(Span(cols[11].strip(), box, confidence=round(float(cols[10]) / 100, 2)))
    return words


def register(words: list[Span]) -> Registration:
    """Median offset between where the template prints its labels and where OCR found them."""
    landmarks = {label.upper(): box for label, box in template.LABELS.items()}
    offsets = [
        (w.rect[0] - landmarks[w.text.upper()][0], w.rect[1] - landmarks[w.text.upper()][1])
        for w in words if w.text.upper() in landmarks
    ]
    offsets = [(dx, dy) for dx, dy in offsets if abs(dx) < 40 and abs(dy) < 40]
    if len(offsets) < 2:
        return Registration(0.0, 0.0, len(offsets))
    return Registration(round(median(o[0] for o in offsets), 1), round(median(o[1] for o in offsets), 1), len(offsets))


def read_scan_ocr(drawing: Drawing) -> tuple[list[Observation], dict[int, tuple[ScanPage, Registration, list[Span]]]]:
    """OCR observations, plus what the vision pass needs to line its reading up with OCR."""
    observations, pages = [], {}
    for number, scan in enumerate(scan_pages(drawing), start=1):
        words = ocr_words(scan)
        reg = register(words)
        pages[number] = (scan, reg, words)
        observations += _title_block(drawing.id, number, words, reg)
        observations += _callouts(drawing.id, number, words, reg)
    return observations, pages


def _title_block(drawing_id: str, page: int, words: list[Span], reg: Registration) -> list[Observation]:
    out = []
    for field in template.FIELDS:
        cell = reg.cell(field)
        inside = [w for w in words if template.inside(w.rect, cell) and not template.is_label(w.rect, reg.dx, reg.dy)]
        value = _text(inside)
        if (prefix := template.VALUE_PREFIX.get(field)) and value.upper().startswith(prefix):
            value = value[len(prefix):].strip()
        out.append(Observation(
            id=f"{drawing_id}.p{page}.{field}.ocr",
            subject=drawing_id,
            field=field,
            value=value,
            source=Source(doc=drawing_id, page=page, bbox=_round(cell)),
            method=Method.OCR,
            confidence=_mean_confidence(inside),
            parsed=parse_field(field, value),
            note=f"registered on {reg.landmarks} title-block labels" if reg.landmarks >= 2 else "not registered; template position assumed",
        ))
    return out


def _callouts(drawing_id: str, page: int, words: list[Span], reg: Registration) -> list[Observation]:
    frame, block = template.DRAWING_FRAME, reg.title_block
    on_drawing = [w for w in words if template.inside(w.rect, frame) and not template.inside(w.rect, block)]
    out = []
    for callout in group(on_drawing):
        text, confidence = callout.text, _mean_confidence(callout.spans)
        if not _looks_like_text(text) or confidence is None or confidence < MIN_CALLOUT_CONFIDENCE:
            continue
        out.append(Observation(
            id=f"{drawing_id}.p{page}.ocr.a{len(out) + 1:02d}",
            subject=drawing_id,
            field="callout",
            value=text,
            source=Source(doc=drawing_id, page=page, bbox=_round(callout.rect)),
            method=Method.OCR,
            confidence=confidence,
            parsed=parse(_ocr_symbols(text), callout.stacked_pair),
        ))
    return out


def _ocr_symbols(text: str) -> str:
    """Tesseract reads the Ø glyph as "@". Fixed for interpretation only; the observed value keeps the "@"."""
    return re.sub(r"@\s*(?=\d)", "Ø", text)


def _looks_like_text(text: str) -> bool:
    """Drop the grain and hatching tesseract turns into "*D*D" or "oooo00o0000"."""
    if MARKER.match(text):
        return False
    visible = [ch for ch in text if not ch.isspace() and ch != "/"]
    sensible = sum(ch.isalnum() or ch in ",.+-±°Ø@" for ch in visible)
    has_number = re.search(r"\d+[,.]\d", text) is not None
    has_words = len(re.findall(r"[A-Za-zæøåÆØÅ]{3,}", text)) >= 2
    repetitive = re.search(r"(.)\1{4,}", text) is not None
    return bool(visible) and sensible / len(visible) > 0.8 and (has_number or has_words) and not repetitive


def _mean_confidence(spans) -> float | None:
    scores = [s.confidence for s in spans if s.confidence is not None]
    return round(sum(scores) / len(scores), 2) if scores else None


def _text(words: list[Span]) -> str:
    return Callout(tuple(words)).text.replace(" / ", "\n") if words else ""


def _round(rect) -> tuple[float, float, float, float]:
    return tuple(round(v, 1) for v in rect)
