"""Interpretations of title-block fields, shared by clean sheets and scans."""

import re
from datetime import date

from meridian import materials

_DATE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$")
_WEIGHT = re.compile(r"^\d+(?:[.,]\d+)?$")
_SHEET = re.compile(r"^(\d+)\s+OF\s+(\d+)$", re.I)
_SCALE = re.compile(r"^(\d+)\s*:\s*(\d+)$")
# "Door - x2", "Galvo Mount Side x2", "2 stk.", "3 styk.", "1-3 stk af hver" (Danish: pieces, of each)
_QUANTITY = re.compile(r"(?:\bx\s?(\d+)\b|\b(\d+(?:\s*-\s*\d+)?)\s*(?:stk|styk)\b\.?(\s+af hver)?|\bone of each\b)", re.I)

MARKER = re.compile(r"^[A-Z](?:-[A-Z])?$")  # datum and section letters carry no knowledge on their own
TEMPLATE_PLACEHOLDERS = {"Description", "Title"}


def parse_field(field: str, value: str) -> dict | None:
    value = value.strip()
    if not value:
        return None
    match field:
        case "weight" if _WEIGHT.match(value):
            return {"grams": float(value.replace(",", "."))}
        case "date" if m := _DATE.match(value):
            day, month, year = map(int, m.groups())
            return {"iso": date(year, month, day).isoformat()}
        case "scale" if m := _SCALE.match(value):
            return {"ratio": f"{m.group(1)}:{m.group(2)}"}
        case "sheet" if m := _SHEET.match(value):
            return {"index": int(m.group(1)), "of": int(m.group(2))}
        case "material":
            return materials.read(value)
        case "title" if value in TEMPLATE_PLACEHOLDERS:
            return {"placeholder": True}  # D-019 ships with the template's own "Description" as its title
        case "note" | "title":
            return _mentions(value)
    return None


def _mentions(text: str) -> dict | None:
    out = {}
    if found := materials.read(text):
        out["materials"] = found
    if m := _QUANTITY.search(text):
        out["quantity_text"] = m.group(0).strip()
    return out or None
