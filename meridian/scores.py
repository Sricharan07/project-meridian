"""Score the knowledge base against what a person read off the sheets.

eval/truth/title_blocks.csv was typed from the rendered sheets: the clean ones
checked against their text layer, the scans read by eye at 200 dpi. Every
reader is scored on its own and after settling, and the number that matters
most is reported separately: fields the system calls confirmed or exact that
are wrong.
"""

import csv
import json
from collections import Counter, defaultdict

from meridian import config, corpus, evidence
from meridian.evidence import Method, Observation
from meridian.reading import Status, comparable, settle, similarity

FIELDS = ["title", "material", "weight", "date", "scale", "sheet", "note"]
TRUSTED = {Status.EXACT, Status.CONFIRMED}


def report() -> str:
    observations = list(evidence.read_jsonl(config.KB / "observations.jsonl"))
    return "\n\n".join([_extraction(observations), _linking(observations)])


def _extraction(observations: list[Observation]) -> str:
    readings: dict[tuple, list[Observation]] = defaultdict(list)
    for o in observations:
        if o.subject.startswith("D-") and o.field in FIELDS and o.source.page:
            readings[(o.subject, o.source.page, o.field)].append(o)

    drawings = corpus.drawings()
    tally: Counter = Counter()
    wrong_but_trusted = []
    with (config.ROOT / "eval/truth/title_blocks.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            kind = "scan" if drawings[row["drawing"]].degraded else "clean"
            for field in FIELDS:
                truth = row[field]
                found = readings[(row["drawing"], int(row["page"]), field)]
                for reader in found:
                    tally[(kind, reader.method.value, "total")] += 1
                    tally[(kind, reader.method.value, "right")] += _same(reader.value, truth, field)
                status, shown = settle(found)
                tally[(kind, "settled", "total")] += 1
                right = (status == Status.BLANK and not truth) or (shown is not None and not shown.blank and _same(shown.value, truth, field))
                tally[(kind, "settled", "right")] += right
                tally[(kind, f"status:{status.value}", "total")] += 1
                if status in TRUSTED and not right:
                    wrong_but_trusted.append(f"  {row['drawing']} sheet {row['page']} {field}: shown {shown.value!r}, sheet says {truth!r}")

    lines = ["Title-block extraction against eval/truth/title_blocks.csv", ""]
    lines.append(f"  {'sheets':6} {'reader':12} {'right':>11}")
    for kind in ("clean", "scan"):
        for reader in (Method.PDF_TEXT.value, Method.OCR.value, Method.VISION.value, "settled"):
            total = tally[(kind, reader, "total")]
            if total:
                right = tally[(kind, reader, "right")]
                lines.append(f"  {kind:6} {reader:12} {right:>4}/{total:<4} {right / total:5.0%}")
    lines.append("")
    lines.append("  How scan fields were settled: " + ", ".join(
        f"{s.value} {tally[('scan', f'status:{s.value}', 'total')]}" for s in Status if tally[("scan", f"status:{s.value}", "total")]))
    lines.append(f"  Shown as exact or confirmed but wrong: {len(wrong_but_trusted)}")
    lines += wrong_but_trusted
    return "\n".join(lines)


def _linking(observations: list[Observation]) -> str:
    curated = {o.subject: o.parsed for o in observations if o.field == "bom_link"}
    proposals: dict[str, list[int]] = defaultdict(list)
    for line in (config.KB / "link_candidates.jsonl").read_text().splitlines():
        c = json.loads(line)
        proposals[c["drawing"]].append(c["row"])

    agree, total, misses = 0, 0, []
    for drawing, decision in sorted(curated.items()):
        if decision["status"] == "ambiguous":
            continue
        total += 1
        first = proposals[drawing][0] if proposals[drawing] else None
        if first in decision["rows"]:
            agree += 1
        else:
            misses.append(f"  {drawing}: linker proposed {first or 'nothing'}, curated {decision['rows']} ({decision['status']})")
    ambiguous = sum(1 for d in curated.values() if d["status"] == "ambiguous")
    lines = [
        "Automatic linker against curation/links.csv",
        "",
        f"  First choice matches the curated row: {agree}/{total} drawings ({ambiguous} left ambiguous by the curator, not scored)",
        *misses,
    ]
    return "\n".join(lines)


def _same(read: str, truth: str, field: str) -> bool:
    if not truth.strip():
        return not read.strip()
    if field == "note":
        return similarity(read, truth) >= 0.9  # long free text: a stray character should not count as a miss
    return comparable(read) == comparable(truth)
