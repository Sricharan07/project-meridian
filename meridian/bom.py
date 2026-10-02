"""Read the BOM snapshot into one observation per non-empty cell.

Cells are kept exactly as exported, misspellings included ("Recieved", "Design
Intend"); `parsed` carries the interpretation. Rows are numbered the way a
spreadsheet shows them, header on row 1, so a citation can be checked by
opening the CSV.
"""

import csv
import re
from datetime import UTC, datetime

from meridian import config, materials
from meridian.evidence import Method, Observation, Source

# CSV header -> field name. "Count (Interface with)" is an Airtable rollup of
# another column and says nothing new, so it is not read.
COLUMNS = {
    "Name": "name",
    "Part family": "family",
    "Type": "type",
    "Design": "design_status",
    "Order": "order_status",
    "V&V": "vv_status",
    "Notes": "notes",
    "Design Intend": "design_intent",
    "Material": "material",
    "Product name": "product_name",
    "Supplier Order": "supplier_order",
    "Interface with": "interface_with",
    "Link": "link",
    "Supplier": "supplier",
    "Datasheet": "datasheet",
    "Image": "image",
    "Amount": "amount",
    "Cost": "unit_cost",
    "Total cost": "total_cost",
}

# Attachment cells look like "RecoaterArm.PDF (https://v5.airtableusercontent.com/v3/u/33/33/1728496800000/...)".
# The number in the path is the signed URL's expiry in epoch milliseconds.
_ATTACHMENT = re.compile(r"\s*([^,(]+?)\s*\((https://v5\.airtableusercontent\.com/v3/u/\d+/\d+/(\d+)/[^)]*)\)")
_DKK = re.compile(r"^DKK(-?[\d,]*\.?\d+)$")


def read_bom() -> list[Observation]:
    with config.BOM_CSV.open(encoding="utf-8-sig", newline="") as f:
        records = list(csv.DictReader(f))
    observations = []
    for index, record in enumerate(records):
        row = index + 2
        for column, field in COLUMNS.items():
            raw = record.get(column) or ""
            if not raw.strip():
                continue
            observations.append(Observation(
                id=f"BOM.{row}.{field}",
                subject=f"BOM.{row}",
                field=field,
                value=raw,
                source=Source(doc="BOM", row=row, column=column),
                method=Method.CSV,
                parsed=_parse(field, raw),
            ))
    return observations


def _parse(field: str, raw: str) -> dict | None:
    match field:
        case "material":
            return {"items": _items(raw)} | (materials.read(raw) or {})
        case "interface_with":
            return {"items": _items(raw)}
        case "amount":
            return {"count": int(raw)} if raw.strip().isdigit() else None
        case "unit_cost" | "total_cost":
            m = _DKK.match(raw.strip())
            return {"dkk": float(m.group(1).replace(",", ""))} if m else None
        case "datasheet" | "image":
            return _attachments(raw)
        case "link" if not raw.startswith("http"):
            return {"url": "https://" + raw.strip(), "scheme_missing": True}
    return None


def _items(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _attachments(raw: str) -> dict:
    files, expiries = [], set()
    for name, _url, expires_ms in _ATTACHMENT.findall(raw):
        files.append(name)
        expiries.add(datetime.fromtimestamp(int(expires_ms) / 1000, UTC).date().isoformat())
    return {"files": files, "url_expired_on": sorted(expiries)}
