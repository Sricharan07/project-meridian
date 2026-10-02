"""Edges between parts, each tied to the evidence that asserts it.

Three kinds, kept apart in every answer:

- stated    the BOM's "Interface with" column. Written in one direction only
            (Left Side Box lists Print Platform; Print Platform lists nothing),
            so it is read as undirected.
- diagram   read off a system diagram by a person, from
            curation/diagram_relations.csv, citing the label boxes.
- inferred  two sheets carry a mating hole and shaft tolerance at the same
            nominal diameter, e.g. Ø264 H8 in the clamp ring and Ø264 j7 on the
            cylinder. Geometry suggests it; no source says it.
"""

import csv
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from meridian import config
from meridian.evidence import Method, Observation, Source


@dataclass(frozen=True, slots=True)
class Relation:
    id: str
    a: str                       # "BOM.50", "D-027"
    b: str
    relation: str                # in the source's words where there are any
    kind: str                    # stated | diagram | inferred
    evidence: tuple[str, ...]    # observation ids
    note: str = ""


def stated(observations: list[Observation]) -> list[Relation]:
    by_name = {o.value.strip().casefold(): o.subject for o in observations if o.source.doc == "BOM" and o.field == "name"}
    out = []
    for o in observations:
        if o.source.doc != "BOM" or o.field != "interface_with":
            continue
        for name in o.parsed["items"]:
            target = by_name.get(name.casefold())
            out.append(Relation(
                id=f"{o.subject}~{target or name}",
                a=o.subject,
                b=target or name,
                relation="interfaces with",
                kind="stated",
                evidence=(o.id,),
                note="" if target else f'no BOM row is named "{name}"',
            ))
    return out


def diagram(path: Path = config.CURATION / "diagram_relations.csv") -> tuple[list[Relation], list[Observation]]:
    """Relations from the diagrams, and the label observations they cite."""
    with path.open(newline="") as f:
        records = list(csv.DictReader(f))
    labels: dict[tuple, Observation] = {}

    def label(sheet: str, text: str, box: str) -> str:
        key = (sheet, text, box)
        if key not in labels:
            n = sum(1 for k in labels if k[0] == sheet) + 1
            labels[key] = Observation(
                id=f"{sheet}.l{n:02d}",
                subject=f"diagram:{sheet}",
                field="label",
                value=text,
                source=Source(doc=f"diagram:{sheet}", bbox=tuple(float(v) for v in box.split())),
                method=Method.TRANSCRIBED,
            )
        return labels[key].id

    relations = []
    for index, r in enumerate(records):
        a = label(r["diagram"], r["a_label"], r["a_box"])
        b = label(r["diagram"], r["b_label"], r["b_box"])
        relations.append(Relation(
            id=f"{r['diagram']}.r{index + 1:02d}",
            a=r["a"],
            b=r["b"],
            relation=r["relation"],
            kind="diagram",
            evidence=(a, b),
            note=r["basis"],
        ))
    return relations, list(labels.values())


# ISO 286 hole-basis fits: the shaft's letter says what kind of fit an H hole makes with it.
def _fit_class(hole: str, shaft: str) -> str:
    if not hole.startswith("H"):
        return "fit class not determined (hole is not H-based)"
    letter = shaft.rstrip("0123456789").lower()
    if letter <= "h":
        return "clearance fit"
    if letter in ("j", "js", "k", "m", "n"):
        return "transition fit"
    return "interference fit"


def inferred_fits(observations: Iterable[Observation]) -> list[Relation]:
    holes, shafts = [], []
    for o in observations:
        p = o.parsed or {}
        fit, size = p.get("fit"), p.get("diameter", p.get("value"))
        if o.field != "callout" or not fit or size is None or p.get("fit_check"):
            continue  # a reading that fails its own ISO 286 check is not evidence of a mating part
        (holes if fit[0].isupper() else shafts).append((size, fit, o))
    out, seen = [], set()
    for size, hole_fit, hole in holes:
        for shaft_size, shaft_fit, shaft in shafts:
            key = (hole.subject, shaft.subject, size, hole_fit, shaft_fit)
            if shaft_size != size or shaft.subject == hole.subject or key in seen:
                continue
            seen.add(key)  # a sheet often repeats a callout in two views
            out.append(Relation(
                id=f"fit:{hole.id}~{shaft.id}",
                a=hole.subject,
                b=shaft.subject,
                relation=f"Ø{size:g} {hole_fit}/{shaft_fit} {_fit_class(hole_fit, shaft_fit)}",
                kind="inferred",
                evidence=(hole.id, shaft.id),
                note=f"{hole.subject} has a Ø{size:g} {hole_fit} bore and {shaft.subject} a Ø{size:g} {shaft_fit} diameter. "
                     "Matching sizes and tolerance classes suggest they mate; no source says so.",
            ))
    return out


def write_jsonl(path: Path, relations: list[Relation]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(relations, key=lambda r: r.id)
    path.write_text("".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in rows))
    return len(rows)


def read_jsonl(path: Path) -> list[Relation]:
    return [Relation(**{**d, "evidence": tuple(d["evidence"])}) for d in map(json.loads, path.read_text().splitlines())]
