"""Build the knowledge base in kb/ from dataset/ and curation/.

Everything the app serves comes from here, and everything here was either read
from a source file or decided by a person in curation/. Rebuilding gives the
same files: OCR is deterministic and vision responses are cached in kb/vision/.
"""

import json
import logging
import time

import pymupdf

from meridian import bom, config, corpus, evidence, linking, relations
from meridian.corpus import Drawing
from meridian.sheets import scan, vector, vision

log = logging.getLogger(__name__)

PAGE_DPI = 144  # twice screen resolution; enough to read a 1:5 sheet's callouts zoomed in


def build() -> dict:
    started = time.monotonic()
    drawings = corpus.drawings()
    observations = bom.read_bom()
    unread_by_vision = []

    for drawing in drawings.values():
        if not drawing.degraded:
            observations += vector.read_clean(drawing)
            continue
        ocr, pages = scan.read_scan_ocr(drawing)
        observations += ocr
        for number, (page, registration, _) in pages.items():
            reading = vision.read_sheet(drawing.id, number, page, registration)
            if reading is None:
                unread_by_vision.append(f"{drawing.id} sheet {number}")
            else:
                observations += vision.observations(drawing.id, number, reading, registration, ocr)
        log.info("read %s (%d sheets)", drawing.id, len(pages))

    observations += linking.curated_links()
    diagram_relations, labels = relations.diagram()
    observations += labels
    edges = relations.stated(observations) + diagram_relations + relations.inferred_fits(observations)
    candidates = linking.propose(drawings, observations)

    config.KB.mkdir(exist_ok=True)
    summary = {
        "source_revision": config.SOURCE_REVISION,
        "model": config.MODEL,
        "observations": evidence.write_jsonl(config.KB / "observations.jsonl", observations),
        "relations": relations.write_jsonl(config.KB / "relations.jsonl", edges),
        "link_candidates": _write_candidates(candidates),
        "sheets": _render_sheets(drawings),
        "unread_by_vision": unread_by_vision,
        "seconds": round(time.monotonic() - started, 1),
    }
    (config.KB / "build.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def _write_candidates(candidates: list[linking.Candidate]) -> int:
    lines = [json.dumps({"drawing": c.drawing, "row": c.row, "score": c.score, "reasons": c.reasons}, ensure_ascii=False)
             for c in candidates]
    (config.KB / "link_candidates.jsonl").write_text("\n".join(lines) + "\n")
    return len(lines)


def _render_sheets(drawings: dict[str, Drawing]) -> int:
    """Page images for the viewer, plus an index of their sizes in PDF points so highlights line up."""
    pages_dir = config.KB / "pages"
    pages_dir.mkdir(exist_ok=True)
    index = {}
    for drawing in drawings.values():
        sheets = []
        with pymupdf.open(drawing.path) as doc:
            for page in doc:
                name = f"{drawing.id}-{page.number + 1}"
                if drawing.degraded:
                    # Serve the scan exactly as supplied; re-encoding would add a second generation of artefacts.
                    (info,) = page.get_images()
                    image = doc.extract_image(info[0])
                    file = f"{name}.{image['ext']}"
                    (pages_dir / file).write_bytes(image["image"])
                else:
                    file = f"{name}.png"
                    page.get_pixmap(dpi=PAGE_DPI, colorspace=pymupdf.csGRAY).save(pages_dir / file)
                sheets.append({"image": f"pages/{file}", "width": round(page.rect.width, 2), "height": round(page.rect.height, 2)})
        index[drawing.id] = {
            "subsystem": drawing.subsystem,
            "upstream_path": drawing.upstream_path,
            "degraded": drawing.degraded,
            "degradation": drawing.degradation,
            "sheets": sheets,
        }
    (config.KB / "drawings.json").write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n")
    return sum(len(d["sheets"]) for d in index.values())
