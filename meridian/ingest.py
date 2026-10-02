"""Adding a drawing in the app: read it the way the build reads the supplied ones, and let a person decide.

The PDF and everything read from it live under var/ingest/<id>/, never in dataset/ or kb/. The upload is a
proposal like any correction: it reaches answers, search and the graph only when a reviewer accepts it on the
Review page and says which BOM rows it documents.

Clean sheets are read from their text layer, which needs only the PDF library. A scan needs what the build
needs for scans: tesseract for the first reader and, for the second, an API key for the vision model.

MERIDIAN_HOLD_OUT=D-028 leaves a supplied drawing out of the loaded knowledge base, so it can be added back
through this path and compared with what the build read. That is how the tests check that both paths agree.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pymupdf

from meridian import config, corrections, evidence, linking
from meridian.corpus import Drawing
from meridian.evidence import Method, Observation, Source
from meridian.linking import SUBSYSTEM_FAMILY

DIR = config.VAR / "ingest"
HOLD_OUT = {d.strip() for d in os.environ.get("MERIDIAN_HOLD_OUT", "").split(",") if d.strip()}
PAGE_DPI = 144


def add(kb, pdf: bytes, filename: str, subsystem: str, reason: str, log: Path = corrections.LOG) -> corrections.Correction:
    if subsystem not in SUBSYSTEM_FAMILY:
        raise ValueError(f"Choose a subsystem: {', '.join(SUBSYSTEM_FAMILY)}.")
    digest = hashlib.sha256(pdf).hexdigest()
    if duplicate := _already_known(digest, log):
        raise ValueError(f"This file is already in the knowledge base as {duplicate}.")
    try:
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            pages = len(doc)
            scanned = all(not page.get_text().strip() and page.get_images() for page in doc)
    except Exception as error:
        raise ValueError("That is not a PDF this app can read.") from error

    drawing_id = _next_id()
    folder = DIR / drawing_id
    folder.mkdir(parents=True)
    path = folder / f"{drawing_id}.pdf"
    path.write_bytes(pdf)
    drawing = Drawing(id=drawing_id, path=path, subsystem=subsystem, pages=pages, upstream_path=f"uploaded/{filename}",
                      degraded=scanned, degradation="uploaded scan" if scanned else "")
    try:
        observations = [Observation(f"{drawing_id}.subsystem", drawing_id, "subsystem", subsystem,
                                    Source(doc=f"var/ingest/{drawing_id}"), Method.CURATED, note="Given when the drawing was added.")]
        observations += read(drawing, folder)
        sheets = _render(drawing, folder)
    except Exception:
        shutil.rmtree(folder)
        raise
    candidates = linking.propose({drawing_id: drawing}, kb.base_observations + observations)
    evidence.write_jsonl(folder / "observations.jsonl", observations)
    info = {"subsystem": subsystem, "upstream_path": drawing.upstream_path, "degraded": scanned,
            "degradation": drawing.degradation, "sheets": sheets}
    (folder / "drawing.json").write_text(json.dumps({"info": info, "sha256": digest, "filename": filename}, indent=1))

    title = next((o.value for o in observations if o.field == "title" and o.value), "") or filename
    c = corrections.Correction(
        id=corrections.next_id(log), target=drawing_id, subject=drawing_id, current_value="not in the knowledge base",
        proposed_value=f"{title}: {pages} sheet{'s' if pages > 1 else ''}, {len(observations) - 1} values read",
        reason=reason.strip(), question="", proposed_at=corrections._now(), kind="drawing",
        payload={"id": drawing_id, "title": title, "subsystem": subsystem, "filename": filename, "image": sheets[0]["image"],
                 "candidates": [{"row": c.row, "name": _row_name(kb, c.row), "score": c.score, "reasons": list(c.reasons)}
                                for c in candidates]},
    )
    c.checks = [vars(x) for x in _checks(kb, drawing, observations, candidates)]
    c.impact = [{"change": "adds", "what": f"drawing {drawing_id} to {subsystem}, with {len(observations) - 1} values and the BOM link the reviewer chooses",
                 "cites": []}]
    corrections._append(log, {"event": "proposed", "at": c.proposed_at, "correction": vars(c)})
    return c


def read(drawing: Drawing, folder: Path) -> list[Observation]:
    """The build's own readers: the text layer for a clean sheet, OCR and the vision model for a scan."""
    if not drawing.degraded:
        from meridian.sheets import vector
        return vector.read_clean(drawing)
    if not shutil.which("tesseract"):
        raise ValueError("This is a scanned sheet. Reading one needs tesseract, which is not installed here; "
                         "clean PDFs need nothing extra.")
    try:
        from meridian.sheets import scan, vision
    except ImportError as error:
        raise ValueError("Reading a scanned sheet needs the build packages: pip install -r requirements-build.txt") from error
    ocr, pages = scan.read_scan_ocr(drawing)
    out = list(ocr)
    for number, (page, registration, _) in pages.items():
        reading = vision.read_sheet(drawing.id, number, page, registration, cache=folder / "vision")
        if reading is not None:
            out += vision.observations(drawing.id, number, reading, registration, ocr)
    return out


def load_accepted(proposals: list[corrections.Correction]) -> tuple[list[Observation], dict]:
    """Drawings accepted in review, as observations and sheet records to load beside the built ones."""
    observations, sheets = [], {}
    for c in proposals:
        if c.kind != "drawing" or c.status != "accepted":
            continue
        folder = DIR / c.subject
        if not folder.exists():
            continue  # var/ was cleared; the decision stays in the log, the drawing is gone
        observations += evidence.read_jsonl(folder / "observations.jsonl")
        sheets[c.subject] = json.loads((folder / "drawing.json").read_text())["info"]
        link = c.payload.get("link") or {"rows": [], "status": "ambiguous"}
        observations.append(Observation(
            f"{c.subject}.bom-link", c.subject, "bom_link", ";".join(map(str, link["rows"])), Source(doc=c.id),
            Method.REVIEW, parsed={"rows": link["rows"], "status": link["status"], "correction": c.id},
            note=c.decision_note or c.reason))
    return observations, sheets


def hold_out(observations: list[Observation], relations: list, sheets: dict) -> tuple[list, list, dict]:
    if not HOLD_OUT:
        return observations, relations, sheets
    return ([o for o in observations if o.subject not in HOLD_OUT],
            [r for r in relations if r.a not in HOLD_OUT and r.b not in HOLD_OUT],
            {d: info for d, info in sheets.items() if d not in HOLD_OUT})


# --- helpers ---------------------------------------------------------------------------------------

def _already_known(digest: str, log: Path) -> str | None:
    manifest = json.loads(config.MANIFEST.read_text())
    for asset in manifest["assets"]:
        if asset.get("sha256") == digest and asset["id"] not in HOLD_OUT:
            return asset["id"]
    for c in corrections.load(log):
        if c.kind == "drawing" and c.status != "rejected" and (DIR / c.subject / "drawing.json").exists():
            if json.loads((DIR / c.subject / "drawing.json").read_text())["sha256"] == digest:
                return c.subject
    return None


def _next_id() -> str:
    """After every supplied drawing and every drawing ever added, so an id is never reused."""
    used = [a["id"] for a in json.loads(config.MANIFEST.read_text())["assets"] if a["id"].startswith("D-")]
    used += [p.name for p in DIR.glob("D-*")] if DIR.exists() else []
    return f"D-{max(int(u[2:]) for u in used) + 1:03d}"


def _render(drawing: Drawing, folder: Path) -> list[dict]:
    pages_dir = folder / "pages"
    pages_dir.mkdir(exist_ok=True)
    out = []
    with pymupdf.open(drawing.path) as doc:
        for page in doc:
            name = f"{drawing.id}-{page.number + 1}"
            if drawing.degraded:
                (info,) = page.get_images()[:1]
                image = doc.extract_image(info[0])
                file = f"{name}.{image['ext']}"
                (pages_dir / file).write_bytes(image["image"])
            else:
                file = f"{name}.png"
                page.get_pixmap(dpi=PAGE_DPI, colorspace=pymupdf.csGRAY).save(pages_dir / file)
            # Served at /ingest/; kb-relative, so the viewer's /kb/<image> resolves there.
            out.append({"image": f"../ingest/{drawing.id}/pages/{file}", "width": round(page.rect.width, 2),
                        "height": round(page.rect.height, 2)})
    return out


def _checks(kb, drawing: Drawing, observations: list[Observation], candidates: list) -> list[corrections.Check]:
    Check = corrections.Check
    values = [o for o in observations if o.field != "subsystem"]
    if drawing.degraded:
        readers = {o.method.value for o in values}
        how = f"A scan, read by {' and '.join(sorted(readers)) or 'no reader'}: {len(values)} values, each settled as the build settles scans."
    else:
        how = f"A clean sheet, read from its text layer: {len(values)} values, each exactly as printed."
    out = [Check("How it was read", "note", how)]
    field = lambda name: next((o.value for o in values if o.field == name and o.value), "")
    title, material, weight = field("title"), field("material"), field("weight")
    out.append(Check("Title block", "pass" if title else "note",
                     f'Title "{title or "not read"}", material "{material or "not read"}", weight {weight or "not read"}.'))
    same = [d for d in kb.sheets if title and kb.drawing_name(d).casefold() == title.casefold()]
    out.append(Check("Already known", "note" if same else "pass",
                     f"{', '.join(same)} has the same title; this may be a revision of it." if same
                     else "No supplied or added drawing has this file or this title."))
    failed = [o for o in values if (o.parsed or {}).get("fit_check")]
    if failed:
        out.append(Check("ISO 286", "fail", f"{len(failed)} callout{'s' if len(failed) > 1 else ''} fail the tolerance check: "
                         + "; ".join(o.value for o in failed[:3]) + "."))
    if candidates:
        best = candidates[0]
        out.append(Check("Automatic linker", "pass" if best.score >= 3 else "note",
                         "Best rows: " + "; ".join(f"row {c.row} {_row_name(kb, c.row)} ({c.score:g}: {', '.join(c.reasons)})" for c in candidates) + "."))
    else:
        out.append(Check("Automatic linker", "note", "No BOM row in this subsystem shares a word, a material or a datasheet with the sheet."))
    return out


def _row_name(kb, row: int) -> str:
    cell = kb.cell(row, "name")
    return cell.value if cell else f"row {row}"
