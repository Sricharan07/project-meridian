"""Questions the app asks of the knowledge base, answered with their evidence attached.

Every method returns plain dicts in which each fact carries the observation id
it came from ("cite"). The chat model is shown exactly these, the UI renders
exactly these, and nothing in between restates a fact without its source.

Corrections accepted in review are loaded as observations too. They supersede
the observation they correct for display, and the original stays visible next
to them.
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property

from meridian import config, evidence, materials
from meridian.evidence import Method, Observation
from meridian.linking import SUBSYSTEM_FAMILY
from meridian.names import words
from meridian.reading import Status, settle
from meridian.relations import Relation, read_jsonl as read_relations

TITLE_FIELDS = ["title", "note", "material", "weight", "date", "scale", "sheet"]
PROCUREMENT_FIELDS = ["supplier", "supplier_order", "product_name", "link", "amount", "unit_cost", "total_cost", "order_status"]
BOM_SUMMARY_FIELDS = ["name", "family", "type", "material", "amount", "design_status", "order_status", "vv_status",
                      "notes", "design_intent", "interface_with", "datasheet"]

SNAPSHOT = (f"BOM snapshot at upstream commit {config.SOURCE_REVISION[:7]}, retrieved {config.SNAPSHOT_RETRIEVED}. "
            "Suppliers, prices and order numbers record what was bought then, not what is available now.")


@dataclass(frozen=True, slots=True)
class Entity:
    ref: str      # "D-011" or "BOM.30"
    name: str
    kind: str     # "drawing" | "bom"


class KnowledgeBase:
    def __init__(self, observations: list[Observation], relations: list[Relation], sheets: dict,
                 corrections: list[Observation] = ()):
        self.obs = {o.id: o for o in [*observations, *corrections]}
        self.relations = relations
        self.sheets = sheets
        self.superseded_by = {(o.parsed or {})["supersedes"]: o for o in corrections}
        self.by_subject: dict[str, list[Observation]] = defaultdict(list)
        for o in self.obs.values():
            self.by_subject[o.subject].append(o)

    @classmethod
    def load(cls, corrections: list[Observation] = ()) -> "KnowledgeBase":
        return cls(
            list(evidence.read_jsonl(config.KB / "observations.jsonl")),
            read_relations(config.KB / "relations.jsonl"),
            json.loads((config.KB / "drawings.json").read_text()),
            corrections,
        )

    # --- entities -------------------------------------------------------------

    @cached_property
    def links(self) -> dict[str, Observation]:
        """drawing id -> its curated BOM link observation."""
        return {o.subject: o for o in self.obs.values() if o.field == "bom_link"}

    @cached_property
    def drawings_of_row(self) -> dict[int, list[str]]:
        out = defaultdict(list)
        for drawing, link in self.links.items():
            for row in link.parsed["rows"]:
                out[row].append(drawing)
        return out

    @cached_property
    def entities(self) -> list[Entity]:
        out = [Entity(d, self.drawing_name(d), "drawing") for d in self.sheets]
        out += [Entity(f"BOM.{row}", self.cell(row, "name").value, "bom") for row in self.bom_rows]
        return out

    @cached_property
    def models(self) -> dict[str, dict]:
        """3D reconstructions by drawing id, from kb/models/index.json once they have been built."""
        path = config.KB / "models" / "index.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def model_3d(self, drawing: str) -> dict | None:
        return self.models.get(drawing)

    @cached_property
    def bom_rows(self) -> list[int]:
        return sorted({o.source.row for o in self.obs.values() if o.source.doc == "BOM"})

    def cell(self, row: int, field: str) -> Observation | None:
        o = self.obs.get(f"BOM.{row}.{field}")
        return self.superseded_by.get(o.id, o) if o else None

    def drawing_name(self, drawing: str) -> str:
        """The title if it has a real one, else the note's first line when it reads like a name
        (sheets on the DTU template put the name there), else the upstream file name."""
        title = self.field(drawing, 1, "title")
        if title["value"] and not title.get("placeholder"):
            return title["value"]
        note = self.field(drawing, 1, "note")
        first = re.split(r"\n| / ", note["value"])[0].rstrip(".") if note["value"] else ""  # the vision model joins lines with " / "
        if first and len(first) <= 30 and not first.lower().startswith("note"):
            return first
        stem = self.sheets[drawing]["upstream_path"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
        stem = re.sub(r"_(?:loop|v|version)\d+$|_x\d+$", "", stem, flags=re.I)  # MainPlatform_Loop2 -> MainPlatform
        return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem).replace("_", " ")

    def find(self, query: str, limit: int = 8) -> list[dict]:
        """Parts whose names share words with the query, best first, with what matched."""
        if m := re.search(r"\bD-?0*(\d{1,2})\b", query, re.I):
            ref = f"D-{int(m.group(1)):03d}"
            if ref in self.sheets:
                return [self._entity_hit(ref, ["drawing id"], 10.0)]
        if m := re.search(r"\b(?:bom\s*)?row\s*(\d+)\b", query, re.I):
            row = int(m.group(1))
            if row in self.bom_rows:
                return [self._entity_hit(f"BOM.{row}", ["BOM row number"], 10.0)]

        wanted = words(query)
        hits = []
        for entity in self.entities:
            aliases = self._aliases(entity)
            shared = wanted & aliases
            if not shared:
                continue
            score = len(shared) / len(wanted) + 0.5 * len(shared) / len(aliases)
            if entity.kind == "drawing":
                score += 0.05  # a sheet is the richer answer when both name the part equally well
            hits.append(self._entity_hit(entity.ref, sorted(shared), score))
        return sorted(hits, key=lambda h: -h["score"])[:limit]

    def _aliases(self, entity: Entity) -> set[str]:
        if entity.kind == "drawing":
            upstream = self.sheets[entity.ref]["upstream_path"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
            return words(f"{entity.name} {upstream}")
        row = int(entity.ref.split(".")[1])
        extra = [self.cell(row, f) for f in ("product_name", "supplier_order")]
        return words(" ".join([entity.name, *(c.value for c in extra if c)]))

    def _entity_hit(self, ref: str, matched: list[str], score: float) -> dict:
        hit = {"ref": ref, "name": self.name(ref), "matched": matched, "score": round(score, 2)}
        if ref.startswith("D-"):
            hit |= {"subsystem": self.sheets[ref]["subsystem"], "scan": self.sheets[ref]["degraded"],
                    "bom_rows": self.links[ref].parsed["rows"], "link_status": self.links[ref].parsed["status"]}
        else:
            row = int(ref.split(".")[1])
            hit |= {"family": self.cell(row, "family").value if self.cell(row, "family") else "",
                    "drawings": self.drawings_of_row.get(row, [])}
        return hit

    def name(self, ref: str) -> str:
        if ref.startswith("D-"):
            return self.drawing_name(ref)
        cell = self.cell(int(ref.split(".")[1]), "name")
        return cell.value if cell else ref

    # --- sheets ---------------------------------------------------------------

    def field(self, drawing: str, page: int, field: str) -> dict:
        """One title-block field, settled across every reader, with each reading kept."""
        readings = [o for o in self.by_subject[drawing] if o.field == field and o.source.page == page]
        current = [self.superseded_by.get(o.id, o) for o in readings]
        status, shown = settle(current)
        out = {"value": shown.value if shown else "", "status": status.value, "cite": shown.id if shown else None}
        if shown and (shown.parsed or {}).get("placeholder"):
            out["placeholder"] = True
        if status in (Status.DISPUTED, Status.SINGLE) or len(readings) > 1:
            out["readings"] = [{"value": o.value, "method": o.method.value, "confidence": o.confidence, "cite": o.id}
                               for o in readings]
        corrected = [self.superseded_by[o.id] for o in readings if o.id in self.superseded_by]
        if corrected:
            out["corrected"] = {"by": corrected[0].id, "was": [o.value for o in readings]}
        return out

    def drawing(self, drawing: str) -> dict:
        info = self.sheets[drawing]
        sheets = []
        for page, sheet in enumerate(info["sheets"], start=1):
            sheets.append({
                "sheet": page,
                "title_block": {f: self.field(drawing, page, f) for f in TITLE_FIELDS},
                "callouts": [self._callout(o) for o in self.by_subject[drawing]
                             if o.field == "callout" and o.source.page == page and self._shown_callout(o)],
            })
        return {
            "id": drawing,
            "name": self.drawing_name(drawing),
            "subsystem": info["subsystem"],
            "scan": info["degraded"],
            "degradation": info["degradation"] or None,
            "upstream_file": info["upstream_path"],
            "sheets": sheets,
        }

    def _shown_callout(self, o: Observation) -> bool:
        """On a scan, show the vision reading of a callout and only those OCR callouts nothing else accounts for."""
        if o.method != Method.OCR:
            return True
        return not any((v.parsed or {}).get("ocr_match") == o.id for v in self.by_subject[o.subject])

    def _callout(self, o: Observation) -> dict:
        p = {k: v for k, v in (o.parsed or {}).items() if k not in ("ocr_match", "ocr_similarity")}
        out = {"text": o.value, "cite": o.id, "read_by": o.method.value} | p
        if o.method == Method.VISION:
            out["confirmed_by_ocr"] = (o.parsed or {}).get("ocr_match") is not None
        return out

    # --- parts ----------------------------------------------------------------

    def part(self, ref: str) -> dict:
        """A drawing with the BOM rows it documents, or a BOM row with its drawings, and how the two compare."""
        others = []
        if ref.startswith("BOM."):
            row = int(ref.split(".")[1])
            drawings = self.drawings_of_row.get(row, [])
            if not drawings:
                return {"ref": ref, "name": self.name(ref), "bom": [self.bom_row(row)], "drawing": None,
                        "relations": self.interfaces(ref), "note": "No supplied drawing documents this row."}
            ref, others = drawings[0], drawings[1:]
        link = self.links[ref]
        rows = [self.bom_row(r) for r in link.parsed["rows"]]
        return {
            "ref": ref,
            **({"other_drawings_for_this_row": others} if others else {}),
            "attention": self.attention(ref),
            "name": self.drawing_name(ref),
            "drawing": self.drawing(ref),
            "bom_link": {"rows": link.parsed["rows"], "status": link.parsed["status"], "basis": link.note, "cite": link.id},
            "bom": rows,
            "comparisons": self.compare(ref),
            "relations": self.interfaces(ref),
            "model_3d": self.model_3d(ref),
        }

    def bom_row(self, row: int) -> dict:
        cells = {}
        for field in BOM_SUMMARY_FIELDS + PROCUREMENT_FIELDS:
            cell = self.cell(row, field)
            if cell:
                cells[field] = {"value": cell.value, "cite": cell.id} | ({"parsed": cell.parsed} if cell.parsed else {})
                if cell.method == Method.REVIEW:
                    cells[field]["corrected"] = {"by": cell.id, "was": self.obs[cell.parsed["supersedes"]].value}
        return {"row": row, "cells": cells, "drawings": self.drawings_of_row.get(row, [])}

    def compare(self, drawing: str) -> list[dict]:
        """Where the sheet and its BOM rows say the same thing, say different things, or only one speaks."""
        link = self.links[drawing]
        rows = link.parsed["rows"]
        out = []

        # The MATERIAL field speaks for the sheet. The note only stands in when the field is blank or
        # unreadable: notes also name other parts' materials (D-023's mentions the ceramic seal).
        sheet_families, sheet_cites, mentioned = set(), [], set()
        for f in ("material", "note"):
            reading = self.field(drawing, 1, f)
            found = set((materials.read(reading["value"]) or {}).get("families", [])) if reading["value"] else set()
            if not found or reading["status"] == Status.DISPUTED:
                continue
            if not sheet_families:
                sheet_families, sheet_cites = found, [reading["cite"]]
            else:
                mentioned |= found - sheet_families
        bom_families, bom_cites = set(), []
        for row in rows:
            if cell := self.cell(row, "material"):
                bom_families |= set((cell.parsed or {}).get("families", []))
                bom_cites.append(cell.id)
        material = self._verdict("material", sheet_families, sheet_cites, bom_families, bom_cites)
        if mentioned:
            material["note_also_mentions"] = sorted(mentioned)  # D-026: "rustfri og alu", an aluminium variant
        out.append(material)

        out.append(self._compare_quantity(drawing, rows))

        upstream = self.sheets[drawing]["upstream_path"].rsplit("/", 1)[-1]
        for row in rows:
            cell = self.cell(row, "datasheet")
            files = (cell.parsed or {}).get("files", []) if cell else []
            if not files:
                continue
            same = any(f.rsplit(".", 1)[0].lower() == upstream.rsplit(".", 1)[0].lower() for f in files)
            other = [d for d, info in self.sheets.items()
                     if any(f.rsplit(".", 1)[0].lower() == info["upstream_path"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower() for f in files)]
            out.append({
                "field": "datasheet",
                "sheet": {"upstream_file": upstream},
                "bom": [{"row": row, "files": files, "cite": cell.id}],
                "verdict": "agree" if same else "conflict",
                **({"note": f"BOM row {row} names {', '.join(files)}, which is the upstream file of {', '.join(other)}."} if not same and other else {}),
                **({"corrected": {"by": cell.id}} if cell.method == Method.REVIEW else {}),
            })
        return out

    def _compare_quantity(self, drawing: str, rows: list[int]) -> dict:
        """The sheet says "x2", "3 styk" or "1-3 stk af hver"; the BOM says an amount per row."""
        said = None
        for f in ("title", "note"):
            cite = self.field(drawing, 1, f)["cite"]
            if cite and (text := (self.obs[cite].parsed or {}).get("quantity_text")):
                said = {"text": text, "cite": cite}
                break
        amounts = [(row, self.cell(row, "amount")) for row in rows]
        counts = [(c.parsed or {}).get("count") if c else None for _, c in amounts]
        bom = [{"row": row, "amount": n, "cite": c.id if c else None} for (row, c), n in zip(amounts, counts)]
        total = sum(counts) if counts and None not in counts else None

        span = _quantity_span(said["text"]) if said else None
        if said and total is not None and span:
            verdict = "agree" if span[0] <= total <= span[1] else "conflict"
        elif said and total is not None:
            verdict = "not comparable"  # e.g. "one of each": a person can read it, a rule should not guess
        else:
            verdict = "sheet only" if said else "BOM only" if total is not None else "neither records it"
        return {"field": "quantity", "sheet": said, "bom": bom, "bom_total": total, "verdict": verdict}

    @staticmethod
    def _verdict(field: str, sheet: set, sheet_cites: list[str], bom: set, bom_cites: list[str]) -> dict:
        if sheet and bom:
            verdict = "agree" if sheet == bom else "partly agree" if sheet & bom else "conflict"
        else:
            verdict = "sheet only" if sheet else "BOM only" if bom else "neither records it"
        return {"field": field, "sheet": {"families": sorted(sheet), "cites": sheet_cites},
                "bom": {"families": sorted(bom), "cites": bom_cites}, "verdict": verdict}

    def attention(self, ref: str) -> list[dict]:
        """What a careful engineer would point out about this part before anything else, with the evidence.

        Worked out here rather than left for the chat model to notice in a large result: conflicts
        between sources, links that are not certain, readings that disagree or failed a check.
        """
        drawing = ref if ref.startswith("D-") else next(iter(self.drawings_of_row.get(int(ref[4:]), [])), None)
        if drawing is None:
            return []
        notes = []
        link = self.links[drawing]
        rows = ", ".join(map(str, link.parsed["rows"]))
        if link.parsed["status"] != "linked":
            notes.append({"text": f"The link from {drawing} to BOM row(s) {rows} is {link.parsed['status']}: {link.note}",
                          "cites": [link.id]})
        elif "conflict" in link.note.lower():
            notes.append({"text": f"Curator's note on the link to BOM row(s) {rows}: {link.note}", "cites": [link.id]})
        for c in self.compare(drawing):
            if c["verdict"] in ("conflict", "partly agree"):
                notes.append({"text": _describe(c), "cites": _cites_of(c)})
        for page, sheet in enumerate(self.sheets[drawing]["sheets"], start=1):
            for field in ("title", "material", "weight", "note"):  # disputes over scale or sheet number are noise
                f = self.field(drawing, page, field)
                if f["status"] == Status.DISPUTED:
                    readers = {"ocr": "OCR", "vision": "the vision model"}
                    readings = "; ".join(f'{readers[r["method"]]} reads "{r["value"]}"' for r in f["readings"] if r["value"])
                    notes.append({"text": f"Sheet {page} {field} is disputed between the two readers: {readings}.",
                                  "cites": [r["cite"] for r in f["readings"]]})
        for o in self.by_subject[drawing]:
            if (o.parsed or {}).get("fit_check"):
                notes.append({"text": f'Callout "{o.value}" failed the ISO 286 check: {o.parsed["fit_check"]}. '
                                      "No fit relation is inferred from it.", "cites": [o.id]})
        if self.sheets[drawing]["degraded"]:
            notes.append({"text": f"{drawing} is a degraded scan ({self.sheets[drawing]['degradation']}); its values "
                                  "were read by OCR and a vision model, not from a text layer.", "cites": []})
        return notes

    # --- relations ------------------------------------------------------------

    def _counterparts(self, ref: str) -> set[str]:
        if ref.startswith("D-"):
            return {ref, *(f"BOM.{r}" for r in self.links[ref].parsed["rows"])}
        row = int(ref.split(".")[1])
        return {ref, *self.drawings_of_row.get(row, [])}

    def interfaces(self, ref: str) -> list[dict]:
        mine = self._counterparts(ref)
        out = []
        for r in self.relations:
            if r.a not in mine and r.b not in mine:
                continue
            other = r.b if r.a in mine else r.a
            out.append({
                "kind": r.kind,
                "relation": r.relation if r.a in mine else f"{r.relation} (from the other side)",
                "other": other,
                "other_name": self.name(other) if other.startswith(("D-", "BOM.")) else other,
                "cites": list(r.evidence),
                "note": r.note,
            })
        order = {"stated": 0, "diagram": 1, "inferred": 2}
        return sorted(out, key=lambda x: (order[x["kind"]], x["other"]))

    # --- across parts -----------------------------------------------------------

    def subsystem(self, name: str) -> dict:
        wanted = name.strip().casefold()
        aliases = {k.casefold(): k for k in SUBSYSTEM_FAMILY} | {v.casefold(): k for k, v in SUBSYSTEM_FAMILY.items()}
        aliases |= {"optics": "Optical", "build plate": "Z-axis", "gas": "Gas Flow", "z axis": "Z-axis", "zaxis": "Z-axis"}
        subsystem = aliases.get(wanted)
        families = {v.casefold(): v for v in SUBSYSTEM_FAMILY.values()}
        family = SUBSYSTEM_FAMILY.get(subsystem) if subsystem else families.get(wanted)
        all_families = sorted({self.cell(r, "family").value for r in self.bom_rows if self.cell(r, "family")})
        if not subsystem and not family:
            return {"error": f'No subsystem or BOM family called "{name}".', "subsystems": list(SUBSYSTEM_FAMILY),
                    "bom_families": all_families}
        drawings = [{"ref": d, "name": self.drawing_name(d), "scan": info["degraded"], "bom_rows": self.links[d].parsed["rows"]}
                    for d, info in self.sheets.items() if info["subsystem"] == subsystem]
        rows = [{"ref": f"BOM.{r}", "name": self.cell(r, "name").value,
                 "type": self.cell(r, "type").value if self.cell(r, "type") else "",
                 "drawings": self.drawings_of_row.get(r, []), "cite": f"BOM.{r}.family"}
                for r in self.bom_rows if self.cell(r, "family") and self.cell(r, "family").value == family]
        return {"subsystem": subsystem, "bom_family": family,
                "mapping_note": "Z-axis sheets are filed under the BOM family Build-plate." if subsystem == "Z-axis" else None,
                "drawings": drawings, "bom_rows": rows}

    def with_material(self, material: str) -> dict:
        found = materials.read(material)
        if not found:
            return {"error": f'"{material}" does not name a material family this system knows.',
                    "families": ["aluminium", "stainless steel", "steel", "silicone", "ceramic", "polymer", "elastomer", "paper"]}
        family = found["families"][0]
        sheets, rows = [], []
        for d in self.sheets:
            m, n = self.field(d, 1, "material"), self.field(d, 1, "note")
            for f, source in ((m, "material field"), (n, "note")):
                fam = (materials.read(f["value"]) or {}).get("families", []) if f["value"] else []
                if family in fam:
                    sheets.append({"ref": d, "name": self.drawing_name(d), "says": f["value"], "where": source,
                                   "status": f["status"], "cite": f["cite"]})
                    break
        for r in self.bom_rows:
            cell = self.cell(r, "material")
            if cell and family in (cell.parsed or {}).get("families", []):
                rows.append({"ref": f"BOM.{r}", "name": self.cell(r, "name").value, "says": cell.value, "cite": cell.id,
                             "drawings": self.drawings_of_row.get(r, [])})
        return {"family": family, "grades": found.get("grades", []), "sheets": sheets, "bom_rows": rows}

    def procurement(self, refs: list[str] | None = None, subsystem: str | None = None) -> dict:
        if subsystem:
            listing = self.subsystem(subsystem)
            if "error" in listing:
                return listing
            rows = [int(r["ref"].split(".")[1]) for r in listing["bom_rows"]]
        else:
            rows = sorted({int(c.split(".")[1]) for ref in refs or [] for c in self._counterparts(ref) if c.startswith("BOM.")})
        lines, recorded, unrecorded, inconsistent = [], 0.0, [], []
        for row in rows:
            cells = {f: self.cell(row, f) for f in PROCUREMENT_FIELDS}
            total = (cells["total_cost"].parsed or {}).get("dkk") if cells["total_cost"] else None
            unit = (cells["unit_cost"].parsed or {}).get("dkk") if cells["unit_cost"] else None
            if total:
                recorded += total
            elif unit:
                inconsistent.append(row)  # a unit price but a zero total: the amount is missing
            else:
                unrecorded.append(row)
            lines.append({"ref": f"BOM.{row}", "name": self.cell(row, "name").value} |
                         {f: {"value": c.value, "cite": c.id} for f, c in cells.items() if c})
        return {
            "rows": lines,
            "total_recorded_dkk": round(recorded, 2),
            "rows_without_recorded_cost": [f"BOM.{r}" for r in unrecorded],
            "rows_with_unit_cost_but_no_total": [f"BOM.{r}" for r in inconsistent],
            "caveat": SNAPSHOT + " DKK0.00 on a part made at DTU means the cost was not recorded, not that it was free.",
        }

    def search(self, text: str, limit: int = 20) -> list[dict]:
        """Free-text search over notes, design intent and callout remarks: what the sources say in prose."""
        needle = text.casefold().strip()
        prose = {"note", "notes", "design_intent", "callout", "title", "label"}
        hits = []
        for o in self.obs.values():
            if o.field in prose and needle in o.value.casefold():
                owner = o.subject if o.subject.startswith(("D-", "BOM.")) else None
                hits.append({"ref": owner, "name": self.name(owner) if owner else o.subject,
                             "field": o.field, "text": o.value, "cite": o.id, "read_by": o.method.value})
        return hits[:limit]

    def evidence(self, observation_id: str) -> dict | None:
        o = self.obs.get(observation_id)
        if not o:
            return None
        source = {k: v for k, v in {"doc": o.source.doc, "page": o.source.page, "bbox": o.source.bbox,
                                    "row": o.source.row, "column": o.source.column}.items() if v is not None}
        out = {"id": o.id, "subject": o.subject, "field": o.field, "value": o.value, "method": o.method.value,
               "source": source, "label": o.source.label(), "confidence": o.confidence, "parsed": o.parsed, "note": o.note}
        if o.id in self.superseded_by:
            out["superseded_by"] = self.superseded_by[o.id].id
        return out


def _quantity_span(text: str) -> tuple[int, int] | None:
    """"x2" -> (2, 2), "3 styk" -> (3, 3), "1-3 stk af hver" -> (1, 3). Anything else is left to a person."""
    if m := re.search(r"(\d+)\s*-\s*(\d+)", text):
        return int(m.group(1)), int(m.group(2))
    if m := re.search(r"\d+", text):
        return int(m.group()), int(m.group())
    return None


def _describe(comparison: dict) -> str:
    field, verdict = comparison["field"], comparison["verdict"]
    if field == "material":
        text = (f"Material: the sheet names {', '.join(comparison['sheet']['families'])}, "
                f"the BOM names {', '.join(comparison['bom']['families'])} ({verdict}).")
        if also := comparison.get("note_also_mentions"):
            text += f" The sheet's note also mentions {', '.join(also)}."
        return text
    if field == "quantity":
        return (f'Quantity {verdict}: the sheet says "{comparison["sheet"]["text"]}"; '
                f"the BOM amount totals {comparison['bom_total']}.")
    return comparison.get("note") or f"{field.capitalize()}: {verdict}."


def _cites_of(comparison: dict) -> list[str]:
    sheet, bom = comparison.get("sheet") or {}, comparison.get("bom")
    cites = list(sheet.get("cites", [])) + ([sheet["cite"]] if sheet.get("cite") else [])
    if isinstance(bom, dict):
        cites += bom.get("cites", [])
    else:
        cites += [b["cite"] for b in bom or [] if b.get("cite")]
    return cites
