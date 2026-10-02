"""Propose which BOM rows a drawing documents, and load the reviewed answer.

The proposal is deliberately plain: a datasheet filename that matches the
sheet's upstream file, words the names share once Danish titles are
translated, agreeing materials and quantities. It is right when the evidence
is lexical and wrong when it is not ("PowderCanister" is the BOM's "Powder
hopper"). That is why curation/links.csv exists, and why the linker is scored
against it instead of being trusted.
"""

import csv
import re
from dataclasses import dataclass

from meridian import config
from meridian.corpus import Drawing
from meridian.evidence import Method, Observation, Source

# The manifest groups sheets by subsystem; the BOM groups rows by part family.
# All Z-axis sheets (cylinder, build base, clamp ring, motor plate) sit under
# "Build-plate" in the BOM.
SUBSYSTEM_FAMILY = {
    "Box": "Box",
    "Powder": "Powder",
    "Recoater": "Recoater",
    "Optical": "Optics",
    "Gas Flow": "Gas flow",
    "Z-axis": "Build-plate",
}

# Translation only. Deciding that a canister is a hopper is a judgement and
# belongs in curation, not in a synonym list.
GLOSSARY = {
    "bygge": "build", "plade": "plate", "spænd": "clamp", "bund": "bottom",
    "montage": "mount", "klods": "block", "silikone": "silicone", "pakning": "gasket",
    "varmeelement": "heating element", "justeringsplade": "adjustment plate",
    "føring": "guide", "linæer": "linear", "lineær": "linear", "rustfri": "stainless",
}
_IGNORED = {"the", "of", "for", "to", "and", "with", "til", "af", "x2", "v2", "v6", "loop2", "version2", "alu", "description"}


@dataclass(frozen=True, slots=True)
class Candidate:
    drawing: str
    row: int
    score: float
    reasons: tuple[str, ...]


def propose(drawings: dict[str, Drawing], observations: list[Observation], top: int = 3) -> list[Candidate]:
    rows = _bom_rows(observations)
    sheets = _sheet_readings(observations)
    out = []
    for drawing in drawings.values():
        names = _words(" ".join([drawing.upstream_name, *sheets.get(drawing.id, {}).get("names", [])]))
        materials = sheets.get(drawing.id, {}).get("materials", set())
        quantity = sheets.get(drawing.id, {}).get("quantity")
        scored = []
        for row, cells in rows.items():
            datasheet = drawing.upstream_name.lower() in {f.rsplit(".", 1)[0].lower() for f in cells["datasheets"]}
            if cells["family"] != SUBSYSTEM_FAMILY[drawing.subsystem] and not datasheet:
                continue
            score, reasons = 0.0, []
            if datasheet:
                score += 5
                reasons.append(f"BOM datasheet is {drawing.upstream_name}")
            shared = names & cells["words"]
            if shared and cells["words"]:
                score += 3 * len(shared) / len(cells["words"])
                reasons.append("shared words: " + ", ".join(sorted(shared)))
            if materials and cells["materials"]:
                if materials & cells["materials"]:
                    score += 1
                    reasons.append("material agrees")
                else:
                    score -= 1
                    reasons.append("material differs")
            if quantity is not None and quantity == cells["amount"]:
                score += 0.5
                reasons.append(f"quantity {quantity} on both")
            if score > 0:
                scored.append(Candidate(drawing.id, row, round(score, 2), tuple(reasons)))
        out += sorted(scored, key=lambda c: -c.score)[:top]
    return out


def curated_links() -> list[Observation]:
    """curation/links.csv as observations: one per drawing, citing the CSV row it came from."""
    path = config.CURATION / "links.csv"
    with path.open(newline="") as f:
        records = list(csv.DictReader(f))
    return [
        Observation(
            id=f"{r['drawing']}.bom-link",
            subject=r["drawing"],
            field="bom_link",
            value=r["bom_rows"],
            source=Source(doc="curation/links.csv", row=index + 2, column="bom_rows"),
            method=Method.CURATED,
            parsed={"rows": [int(x) for x in r["bom_rows"].split(";") if x], "status": r["status"]},
            note=r["basis"],
        )
        for index, r in enumerate(records)
    ]


def _bom_rows(observations: list[Observation]) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    for o in observations:
        if o.source.doc != "BOM":
            continue
        cells = rows.setdefault(o.source.row, {"family": "", "words": set(), "datasheets": [], "materials": set(), "amount": None})
        match o.field:
            case "family":
                cells["family"] = o.value
            case "name":
                cells["words"] = _words(o.value)
            case "datasheet":
                cells["datasheets"] = (o.parsed or {}).get("files", [])
            case "material":
                cells["materials"] = set((o.parsed or {}).get("families", []))
            case "amount":
                cells["amount"] = (o.parsed or {}).get("count")
    return rows


def _sheet_readings(observations: list[Observation]) -> dict[str, dict]:
    """Names, materials and quantity per drawing, from any reader of its first sheet."""
    out: dict[str, dict] = {}
    for o in observations:
        if not o.subject.startswith("D-") or o.source.page != 1 or o.field not in ("title", "note", "material"):
            continue
        sheet = out.setdefault(o.subject, {"names": [], "materials": set(), "quantity": None})
        parsed = o.parsed or {}
        if o.field == "title" and not parsed.get("placeholder"):
            sheet["names"].append(o.value)
        if o.field == "note" and o.value:
            sheet["names"].append(o.value.splitlines()[0])  # sheets without a title put the part name here
        families = parsed.get("families") or parsed.get("materials", {}).get("families", [])
        sheet["materials"].update(families)
        if q := parsed.get("quantity_text"):
            digits = re.findall(r"\d+", q)
            sheet["quantity"] = int(digits[-1]) if digits and "-" not in q else None
    return out


def _words(text: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-zæøå])(?=[A-Z])", " ", text)
    words = []
    for w in re.split(r"[^A-Za-zÆØÅæøå0-9]+", spaced.lower()):
        words += GLOSSARY.get(w, w).split()
    return {w for w in words if len(w) > 1 and w not in _IGNORED and not w.isdigit()}
