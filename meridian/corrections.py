"""Corrections: proposed in chat, checked by the machine, decided by a person.

Nothing is edited in place. var/corrections.jsonl only grows: one event when a
correction is proposed, one when it is decided. Accepting adds an observation
with method "review" that supersedes the corrected one for display; the
original stays where it was, still citable, pointing at what replaced it.
Rejecting changes no knowledge, and the proposal stays in the history.

A proposal is checked before anyone looks at it: what kind of value it would
replace, what the other reader saw, whether it holds together under ISO 286,
whether it agrees with the other sources, and what accepting it would change.
"""

import json
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from meridian import bom, config, iso286, materials
from meridian.evidence import Method, Observation, Source
from meridian.reading import agree
from meridian.sheets.callouts import parse
from meridian.sheets.fields import parse_field

LOG = config.VAR / "corrections.jsonl"
_lock = threading.Lock()

HOW_READ = {
    Method.PDF_TEXT: "read from the sheet's text layer, so it is exactly what the sheet prints. Accepting says the sheet itself is wrong.",
    Method.CSV: "a BOM cell exactly as exported. Accepting overrides the BOM's own value.",
    Method.MANIFEST: "taken from the dataset's manifest.",
    Method.OCR: "read by OCR from a scan.",
    Method.VISION: "read by the vision model from a scan.",
    Method.CURATED: "a decision recorded in curation/.",
    Method.TRANSCRIBED: "typed in by a person from a diagram.",
    Method.REVIEW: "itself a correction accepted earlier.",
}


@dataclass
class Correction:
    id: str
    target: str
    subject: str
    current_value: str
    proposed_value: str
    reason: str
    question: str
    proposed_at: str
    checks: list[dict] = field(default_factory=list)
    impact: list[dict] = field(default_factory=list)
    status: str = "pending"
    decided_at: str | None = None
    decided_by: str | None = None
    decision_note: str | None = None


def load(log: Path = LOG) -> list[Correction]:
    """Fold the event log into the current state of every correction."""
    if not log.exists():
        return []
    corrections: dict[str, Correction] = {}
    for line in log.read_text().splitlines():
        event = json.loads(line)
        if event["event"] == "proposed":
            corrections[event["correction"]["id"]] = Correction(**event["correction"])
        elif event["event"] == "decided":
            c = corrections[event["id"]]
            c.status = "accepted" if event["accept"] else "rejected"
            c.decided_at, c.decided_by, c.decision_note = event["at"], event["by"], event["note"]
    return list(corrections.values())


def accepted_observations(corrections: list[Correction], observations: dict[str, Observation]) -> list[Observation]:
    return [as_observation(c, observations[c.target]) for c in corrections if c.status == "accepted"]


def as_observation(c: Correction, original: Observation) -> Observation:
    """The corrected value as evidence: same place on the same sheet, method "review", the original kept."""
    return Observation(
        id=f"{c.target}.{c.id}",
        subject=original.subject,
        field=original.field,
        value=c.proposed_value,
        source=Source(doc=c.id, page=original.source.page, bbox=original.source.bbox,
                      row=original.source.row, column=original.source.column),
        method=Method.REVIEW,
        parsed=(reparse(original, c.proposed_value) or {}) | {
            "supersedes": c.target, "correction": c.id, "decided_by": c.decided_by, "decided_at": c.decided_at},
        note=c.reason,
    )


def reparse(original: Observation, value: str) -> dict | None:
    if original.field == "callout":
        return parse(value)
    if original.source.doc == "BOM":
        return bom._parse(original.field, value)
    return parse_field(original.field, value)


def propose(kb, target: str, value: str, reason: str, question: str, log: Path = LOG) -> Correction:
    """File a correction against one observation. `kb` is the KnowledgeBase it is checked against."""
    original = kb.obs.get(target)
    if original is None:
        raise ValueError(f'No observation "{target}". Use a cite id from a tool result.')
    if original.method == Method.REVIEW:  # correcting a correction targets the original again
        target, original = original.parsed["supersedes"], kb.obs[original.parsed["supersedes"]]
    c = Correction(
        id=f"C-{len(load(log)) + 1:03d}",
        target=target,
        subject=original.subject,
        current_value=kb.superseded_by.get(original.id, original).value,
        proposed_value=value.strip(),
        reason=reason.strip(),
        question=question.strip(),
        proposed_at=_now(),
    )
    c.checks = [asdict(x) for x in _checks(kb, original, c)]
    c.impact = _impact(kb, kb.with_correction(as_observation(c, original)), original.subject)
    _append(log, {"event": "proposed", "at": c.proposed_at, "correction": asdict(c)})
    return c


def decide(correction_id: str, accept: bool, by: str, note: str, log: Path = LOG) -> Correction:
    if not by.strip():
        raise ValueError("A decision needs the reviewer's name.")
    current = {c.id: c for c in load(log)}
    c = current.get(correction_id)
    if c is None:
        raise ValueError(f"No correction {correction_id}")
    if c.status != "pending":
        raise ValueError(f"{correction_id} was already {c.status} by {c.decided_by} on {c.decided_at}")
    _append(log, {"event": "decided", "id": correction_id, "accept": accept, "by": by.strip(), "note": note.strip(), "at": _now()})
    return {c.id: c for c in load(log)}[correction_id]


# --- checks -----------------------------------------------------------------------

@dataclass
class Check:
    name: str
    result: str          # "pass", "fail" or "note"
    detail: str
    cites: list[str] = field(default_factory=list)


def _checks(kb, original: Observation, c: Correction) -> list[Check]:
    out = [Check("What would change", "note",
                 f'{original.source.label()} currently reads "{c.current_value}". The value was {HOW_READ[original.method]}',
                 [original.id])]

    if _same(c.current_value, c.proposed_value):
        out.append(Check("Changes something", "fail", "The proposed value is the same as the current one."))

    before, after = _numbers(c.current_value), _numbers(c.proposed_value)
    if before != after:
        out.append(Check("Numbers", "note", f"Changes the numbers {', '.join(before) or 'none'} to {', '.join(after) or 'none'}."))

    for other in _other_readings(kb, original):
        verdict = "pass" if agree(other.value, c.proposed_value) else "note"
        reader = {"ocr": "OCR", "vision": "The vision model"}.get(other.method.value, other.method.value)
        relation = "agrees with" if verdict == "pass" else "does not match"
        out.append(Check("The other reader", verdict, f'{reader} read "{other.value}", which {relation} the proposal.', [other.id]))

    proposed = reparse(original, c.proposed_value) or {}
    fit, holder = proposed.get("fit"), proposed
    if not fit and (proposed.get("counterbore") or {}).get("fit"):
        fit, holder = proposed["counterbore"]["fit"], proposed["counterbore"]
    if fit:
        size = holder.get("diameter", holder.get("value"))
        tolerance = holder.get("tolerance") or {}
        problems = iso286.problems(fit, size, tolerance.get("upper"), tolerance.get("lower"))
        if problems:
            out.append(Check("ISO 286", "fail", "; ".join(problems).capitalize() + "."))
        elif size and tolerance.get("upper") is not None and tolerance.get("lower") is not None:
            out.append(Check("ISO 286", "pass", f"{fit} at Ø{size:g}: {iso286.describe(fit, size, tolerance['upper'], tolerance['lower'])}."))

    if original.field == "material":
        out += _material_checks(kb, original, c.proposed_value)
    if original.field == "datasheet":
        out += _datasheet_checks(kb, original, c.proposed_value)
    return out


def _material_checks(kb, original: Observation, value: str) -> list[Check]:
    families = set((materials.read(value) or {}).get("families", []))
    if not families:
        return [Check("Material", "fail", f'"{value}" does not name a material family the system knows.')]
    out = []
    drawing = original.subject if original.subject.startswith("D-") else None
    rows = kb.links[drawing].parsed["rows"] if drawing else [original.source.row]
    sheets = [drawing] if drawing else kb.drawings_of_row.get(original.source.row, [])
    for o in [kb.cell(r, "material") for r in rows] + [kb.obs.get(f"{d}.p1.material") for d in sheets]:
        if o is None or o.id == original.id or not o.value:
            continue
        theirs = set((materials.read(o.value) or {}).get("families", []))
        if theirs:
            ok = bool(families & theirs)
            out.append(Check("Other sources", "pass" if ok else "fail",
                             f'{o.source.label()} says "{o.value}", which {"agrees" if ok else "conflicts"} with the proposal.', [o.id]))
    return out


def _datasheet_checks(kb, original: Observation, value: str) -> list[Check]:
    stems = {f.rsplit(".", 1)[0].lower() for f in re.findall(r"[\w\-]+\.\w{3}", value)}
    out = []
    for drawing, info in kb.sheets.items():
        upstream = info["upstream_path"].rsplit("/", 1)[-1]
        if upstream.rsplit(".", 1)[0].lower() in stems:
            linked = original.source.row in kb.links[drawing].parsed["rows"]
            out.append(Check("Datasheet file", "pass" if linked else "note",
                             f"{upstream} is the upstream file of {drawing}, which curation "
                             f"{'links' if linked else 'does not link'} to BOM row {original.source.row}.",
                             [kb.links[drawing].id]))
    return out or [Check("Datasheet file", "note", "The proposed file is not one of the supplied drawings.")]


def _other_readings(kb, original: Observation) -> list[Observation]:
    """Another reader's view of the same thing: the other title-block reading, or the OCR match of a callout."""
    if original.method not in (Method.OCR, Method.VISION):
        return []
    if original.field == "callout":
        match = (original.parsed or {}).get("ocr_match")
        return [kb.obs[match]] if match in kb.obs else []
    return [o for o in kb.by_subject[original.subject]
            if o.field == original.field and o.source.page == original.source.page
            and o.method in (Method.OCR, Method.VISION) and o.id != original.id and o.value]


def _impact(before, after, drawing: str) -> list[dict]:
    """What accepting would change for this part: relations and caveats that appear or go away."""
    out = []
    old_rel = {r.id: r for r in before.relations if drawing in (r.a, r.b)}
    new_rel = {r.id: r for r in after.relations if drawing in (r.a, r.b)}
    for rid in new_rel.keys() - old_rel.keys():
        r = new_rel[rid]
        out.append({"change": "adds", "what": f"{r.kind} relation: {r.a} {r.relation} {r.b}", "cites": [c for c in r.evidence if c in before.obs]})
    for rid in old_rel.keys() - new_rel.keys():
        r = old_rel[rid]
        out.append({"change": "removes", "what": f"{r.kind} relation: {r.a} {r.relation} {r.b}", "cites": list(r.evidence)})
    if drawing.startswith("D-"):
        old_att = {a["text"] for a in before.attention(drawing)}
        new_att = {a["text"] for a in after.attention(drawing)}
        out += [{"change": "clears", "what": t, "cites": []} for t in sorted(old_att - new_att)]
        out += [{"change": "raises", "what": t, "cites": []} for t in sorted(new_att - old_att) if "Corrected by" not in t and "waiting for review" not in t]
    return out


def _same(a: str, b: str) -> bool:
    return re.sub(r"\s+", "", a).casefold() == re.sub(r"\s+", "", b).casefold()


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?", text)


def _append(log: Path, event: dict) -> None:
    with _lock:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
