"""Read a clean sheet from its PDF text layer.

Every character and position here is exact, so these observations need no
second reader. Two export quirks are handled:

- The title-block text is written twice (sheet format plus sheet), so spans
  are de-duplicated by text and position.
- Ø, the depth arrow ↧, the counterbore ⌴ and some ± signs are drawn as
  vector polylines instead of characters. They are recognised by shape and put
  back into the text, or "Ø262" would read as a plain length of 262.
"""

import pymupdf

from meridian.corpus import Drawing
from meridian.evidence import Method, Observation, Source
from meridian.sheets import template
from meridian.sheets.callouts import Callout, Span, group
from meridian.sheets.fields import MARKER, parse_field


def read_clean(drawing: Drawing) -> list[Observation]:
    observations = []
    with pymupdf.open(drawing.path) as doc:
        for page in doc:
            spans = _text_spans(page) + _drawn_symbols(page)
            observations += _title_block(drawing.id, page.number + 1, spans)
            observations += _callouts(drawing.id, page.number + 1, spans)
    return observations


def _title_block(drawing_id: str, page: int, spans: list[Span]) -> list[Observation]:
    out = []
    for field, cell in template.FIELDS.items():
        inside = [s for s in spans if template.inside(s.rect, cell) and not template.is_label(s.rect)]
        value = Callout(tuple(inside)).text.replace(" / ", "\n") if inside else ""
        if prefix := template.VALUE_PREFIX.get(field):
            value = value.removeprefix(prefix).strip()
        out.append(Observation(
            id=f"{drawing_id}.p{page}.{field}",
            subject=drawing_id,
            field=field,
            value=value,
            source=Source(doc=drawing_id, page=page, bbox=_union(inside) if inside else cell),
            method=Method.PDF_TEXT,
            parsed=parse_field(field, value),
        ))
    return out


def _callouts(drawing_id: str, page: int, spans: list[Span]) -> list[Observation]:
    frame, block = template.DRAWING_FRAME, template.TITLE_BLOCK
    on_drawing = [s for s in spans if template.inside(s.rect, frame) and not template.inside(s.rect, block)]
    callouts = [c for c in group(on_drawing) if not MARKER.match(c.text)]
    return [
        Observation(
            id=f"{drawing_id}.p{page}.a{n:02d}",
            subject=drawing_id,
            field="callout",
            value=callout.text,
            source=Source(doc=drawing_id, page=page, bbox=_round(callout.rect)),
            method=Method.PDF_TEXT,
            parsed=callout.parsed(),
        )
        for n, callout in enumerate(callouts, start=1)
    ]


def _text_spans(page: pymupdf.Page) -> list[Span]:
    seen, out = set(), []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            direction = (round(line["dir"][0], 2), round(line["dir"][1], 2))
            for s in line["spans"]:
                text = s["text"]
                key = (text.strip(), tuple(round(v) for v in s["bbox"]))
                if not text.strip() or key in seen:
                    continue
                seen.add(key)
                out.append(Span(text.strip(), tuple(s["bbox"]), direction, padded=text != text.strip()))
    return out


def _drawn_symbols(page: pymupdf.Page) -> list[Span]:
    out = []
    for d in page.get_drawings():
        r = d["rect"]
        if not (3 < r.width < 22 and 3 < r.height < 14):  # ⌴ is about 20 x 10 pt, the rest about 10 x 10
            continue
        if symbol := _symbol(d["items"], r):
            out.append(Span(symbol, (r.x0, r.y0, r.x1, r.y1)))
    return out


def _symbol(items: list, r: pymupdf.Rect) -> str | None:
    """Identify the three polyline glyphs SolidWorks uses in callouts."""
    if any(i[0] != "l" for i in items):
        return None
    if len(items) >= 40 and 0.7 < r.width / r.height < 1.4 and r.width < 14:
        return "Ø"  # a 56-segment circle with a slash through it
    lines = [(i[1], i[2]) for i in items]
    horizontal = sum(abs(a.y - b.y) < 0.2 for a, b in lines)
    vertical = sum(abs(a.x - b.x) < 0.2 for a, b in lines)
    if len(items) == 4 and horizontal == 1 and vertical == 1 and r.width < 14:
        return "↧"  # bar, stem and two arrow strokes
    if len(items) == 3 and horizontal == 2 and vertical == 1 and r.width < 8:
        return "±"
    if len(items) == 3 and horizontal == 1 and vertical == 2:
        return "⌴"  # counterbore: two walls and a floor
    return None


def _union(spans: list[Span]) -> tuple[float, float, float, float]:
    return _round((
        min(s.rect[0] for s in spans), min(s.rect[1] for s in spans),
        max(s.rect[2] for s in spans), max(s.rect[3] for s in spans),
    ))


def _round(rect) -> tuple[float, float, float, float]:
    return tuple(round(v, 1) for v in rect)
