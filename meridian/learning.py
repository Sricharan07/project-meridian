"""Is the knowledge getting better as people correct it?

Every accepted correction is replayed in the order it was decided, and the
knowledge is measured after each one. The measures are the ones the build is
scored on, plus the ones a reviewer can move:

- scanned title-block fields that match what a person read off the sheet
  (eval/truth/title_blocks.csv), and how many are still disputed;
- values a reviewer corrected that still don't match the sheet, so a bad
  correction shows up as a cost, not hidden in the totals;
- callouts that fail their ISO 286 check;
- links to BOM rows by certainty, and connections by kind.

The truth set and the reviewer both read the same sheets, so agreement with
it is expected to rise; what this shows is that the loop works and what each
change moved, not an independent accuracy figure.
"""

import csv
from collections import Counter
from functools import cache

from meridian import config, corrections
from meridian.knowledge import KnowledgeBase
from meridian.scores import FIELDS, _same

MEASURES = [
    ("scan_right", "Scanned title-block fields that match the sheet"),
    ("scan_disputed", "Scanned fields the readers still dispute"),
    ("corrected_wrong", "Corrected values that don't match the sheet"),
    ("fit_failures", "Callouts failing the ISO 286 check"),
    ("links_linked", "Drawings linked to their BOM rows"),
    ("links_uncertain", "Links still probable or ambiguous"),
    ("connections", "Connections between parts"),
]


def quality(kb: KnowledgeBase) -> dict:
    scans = {d for d, info in kb.sheets.items() if info["degraded"]}
    right = disputed = corrected_wrong = total = 0
    for row in _truth():
        if row["drawing"] not in scans:
            continue
        for field in FIELDS:
            f = kb.field(row["drawing"], int(row["page"]), field)
            ok = (f["status"] == "blank" and not row[field]) or (f["value"] and _same(f["value"], row[field], field))
            total += 1
            right += bool(ok)
            disputed += f["status"] == "disputed"
            corrected_wrong += f["status"] == "corrected" and not ok
    links = Counter(link.parsed["status"] for link in kb.links.values())
    return {
        "scan_right": right, "scan_total": total, "scan_disputed": disputed, "corrected_wrong": corrected_wrong,
        "fit_failures": sum(1 for o in kb.current_observations() if (o.parsed or {}).get("fit_check")),
        "links_linked": links["linked"], "links_uncertain": links["probable"] + links["ambiguous"],
        "connections": len(kb.relations),
        "connections_by_kind": dict(Counter(r.kind for r in kb.relations)),
    }


def timeline(log=corrections.LOG) -> dict:
    """Quality before any review, after each accepted correction in decision order, and now."""
    base = KnowledgeBase.load(log)
    proposals = corrections.load(log)
    accepted = sorted((c for c in proposals if c.status == "accepted"), key=lambda c: c.decided_at)
    originals = {o.id: o for o in base.base_observations}

    def at(n: int) -> KnowledgeBase:
        return KnowledgeBase(base.base_observations, base.base_relations, base.sheets,
                             corrections.accepted_observations(accepted[:n], originals), proposals, log)

    before = quality(at(0))
    steps, previous = [], before
    for n, c in enumerate(accepted, start=1):
        after = quality(at(n))
        changes = [{"measure": key, "label": label, "before": previous[key], "after": after[key]}
                   for key, label in MEASURES if previous[key] != after[key]]
        steps.append({"id": c.id, "kind": c.kind, "subject": c.subject, "decided_at": c.decided_at,
                      "decided_by": c.decided_by, "changes": changes})
        previous = after
    return {"measures": [{"key": k, "label": label} for k, label in MEASURES], "before": before, "now": previous,
            "steps": steps}


@cache
def _truth() -> tuple[dict, ...]:
    with (config.ROOT / "eval/truth/title_blocks.csv").open(newline="") as f:
        return tuple(csv.DictReader(f))
