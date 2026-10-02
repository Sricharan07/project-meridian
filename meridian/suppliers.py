"""Suggested suppliers: who else sells a bought part, and who could make a custom one.

The BOM records who supplied each part once. `python -m meridian suppliers` looks further with OpenAI's web
search and keeps what it found as a dated snapshot: kb/suppliers/ holds every search response with the pages
it returned, kb/suppliers.jsonl the observations made from them. The app reads the snapshot and never
searches, so it answers the same way without a key, and running the command again uses the cached responses
unless asked to refresh them.

Bought parts. Only those where a second source matters are searched: a bought part with a product name or
order number and a recorded unit cost of at least DKK 200 (the laser, the F-theta lens, the oxygen sensor;
not the M5 nuts). The search identifies the manufacturer part number, then looks for other sellers of it,
or for equivalent parts when it is the distributor's own brand. A suggestion is kept only if it is on a site
the search returned and is not the recorded supplier again, and it says how strong the match is:

  part number confirmed   the manufacturer part number is in the page address
  found by the search     the search found the seller; the page's contents were not checked here
  equivalent              a different part to the same specification; compare the datasheets

Custom parts. What making one takes (material, process, size, tightest tolerance, quantity) is worked out from
the cited facts each time the knowledge loads, so a correction changes it. Makers come from one search per
process in Denmark, each with what its own site states; matching a part to a maker is plain rules, each shown.

Prices and stock are never checked, and a suggestion is not an endorsement.
"""

import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from urllib.parse import urlsplit

from meridian import config, evidence, materials
from meridian.evidence import Method, Observation, Source

log = logging.getLogger(__name__)

CACHE = config.KB / "suppliers"
SNAPSHOT = config.KB / "suppliers.jsonl"
MIN_COST_DKK = 200
SEARCH = {"type": "web_search", "search_context_size": "low", "user_location": {"type": "approximate", "country": "DK"}}
PROCESSES = {
    "milling": "CNC milling",
    "turning": "CNC turning",
    "sheet": "sheet metal cutting and bending",
    "welding": "welding",
    "waterjet": "waterjet cutting of rubber and gaskets",
    "polymer": "polymer 3D printing",
}

# --- searching -------------------------------------------------------------------------------------

PART_INSTRUCTIONS = """You identify a purchased part from its distributor listing, then find other places to buy it.
Search once to identify the manufacturer and the manufacturer part number, and say whether it is the
distributor's own brand. Then search once more:
- not its own brand: for other sellers listing that exact manufacturer part number on a product page (same_part true);
- its own brand: for equivalent parts from other makers with the same main specifications (same_part false),
  saying in note which specifications match.
Return up to three, never the recorded supplier. Only use pages your searches returned; never invent a company
or a URL. Write each note and the description as one plain sentence without links."""

PART_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["manufacturer", "part_number", "own_brand", "description", "alternatives"],
    "properties": {
        "manufacturer": {"type": "string"}, "part_number": {"type": "string"}, "own_brand": {"type": "boolean"},
        "description": {"type": "string"},
        "alternatives": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["company", "url", "same_part", "note"],
            "properties": {"company": {"type": "string"}, "url": {"type": "string"}, "same_part": {"type": "boolean"},
                           "note": {"type": "string"}}}},
    },
}

MAKER_INSTRUCTIONS = """You find job shops in Denmark, near Copenhagen if possible, that offer one manufacturing
process to companies in small batches. For each, give what its own website states: the processes, the
materials, the largest part size in millimetres and the tolerance in millimetres, leaving a number at 0 when
the site does not state it. Only use pages your searches returned. Never invent a company or a URL. Use at
most two searches; return up to six companies."""

MAKER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["companies"],
    "properties": {"companies": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["company", "url", "city", "processes", "materials", "max_size_mm", "tolerance_mm"],
        "properties": {"company": {"type": "string"}, "url": {"type": "string"}, "city": {"type": "string"},
                       "processes": {"type": "array", "items": {"type": "string"}},
                       "materials": {"type": "array", "items": {"type": "string"}},
                       "max_size_mm": {"type": "number"}, "tolerance_mm": {"type": "number"}}}}},
}


def run(observations: list[Observation], refresh: bool = False) -> dict:
    """Search whatever is not cached yet (everything with refresh), then rewrite the snapshot."""
    jobs = [(PART_INSTRUCTIONS, _part_query(p), PART_SCHEMA) for p in bought_parts(observations)]
    jobs += [(MAKER_INSTRUCTIONS, f"Process: {text}.", MAKER_SCHEMA) for text in PROCESSES.values()]
    todo = [j for j in jobs if refresh or not _cached(*j)]
    if todo:
        if not config.OPENAI_API_KEY:
            raise SystemExit(f"{len(todo)} searches are not cached; set OPENAI_API_KEY to run them.")
        from openai import OpenAI
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        with ThreadPoolExecutor(6) as pool:
            for error in pool.map(lambda j: _search(client, *j), todo):
                if error:
                    log.warning(error)
    return snapshot(observations) | {"searched": len(todo), "cached": len(jobs) - len(todo)} | costs()


def _search(client, instructions: str, query: str, schema: dict) -> str | None:
    try:
        response = client.responses.create(
            model=config.MODEL, instructions=instructions, input=query, tools=[SEARCH], store=False,
            include=["web_search_call.action.sources"],
            text={"format": {"type": "json_schema", "name": "result", "schema": schema, "strict": True}},
        )
        result = _plain(json.loads(response.output_text))
    except Exception as error:  # one failed search leaves a gap, not a failed run; it is retried next time
        return f"search failed for {query[:60]}: {error}"
    calls = [o for o in response.output if o.type == "web_search_call"]
    sources = sorted({s.url for o in calls for s in (getattr(o.action, "sources", None) or []) if getattr(s, "url", None)})
    record = {"query": query, "model": config.MODEL, "retrieved": datetime.now(UTC).date().isoformat(),
              "result": result, "sources": sources, "searches": len(calls),
              "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}}
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{_key(instructions, query, schema)}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False))
    log.info("%d sources for %s", len(sources), query[:70])
    return None


def snapshot(observations: list[Observation]) -> dict:
    """Observations from the cached searches: part identities, suggested sellers, and makers by process."""
    out, dropped = [], []
    for part in bought_parts(observations):
        record = _cached(PART_INSTRUCTIONS, _part_query(part), PART_SCHEMA)
        if not record:
            continue
        found, subject, when = record["result"], f"BOM.{part['row']}", record["retrieved"]
        number, remark = _part_number(found["part_number"])
        maker = re.split(r"\s*[(;—]", found["manufacturer"])[0]
        out.append(Observation(f"{subject}.web.part", subject, "manufacturer_part", f"{maker} {number}" if number else "",
                               Source(doc="web search"), Method.WEB, note=" ".join(filter(None, (found["description"], remark))),
                               parsed={"manufacturer": maker, "part_number": number, "own_brand": found["own_brand"],
                                       "retrieved": when, "pages_returned": len(record["sources"])}))
        recorded = _domain(part["link"])
        kept = 0
        for alt in found["alternatives"]:
            site = _domain(alt["url"])
            if site not in {_domain(s) for s in record["sources"]} or (recorded and site == recorded):
                dropped.append({"row": part["row"], "company": alt["company"], "url": alt["url"],
                                "why": "the recorded supplier" if recorded and site == recorded else "not a site the search returned"})
                continue
            kept += 1
            match = "equivalent" if not alt["same_part"] else (
                "part number confirmed" if number and _mentions(alt["url"], number) else "found by the search")
            out.append(Observation(f"{subject}.web.{kept}", subject, "suggested_supplier", alt["company"],
                                   Source(doc=alt["url"]), Method.WEB, note=alt["note"],
                                   parsed={"url": alt["url"], "match": match, "retrieved": when}))
    makers: dict[str, dict] = {}
    for key, text in PROCESSES.items():
        record = _cached(MAKER_INSTRUCTIONS, f"Process: {text}.", MAKER_SCHEMA)
        for company in (record or {}).get("result", {}).get("companies", []):
            if _domain(company["url"]) not in {_domain(s) for s in record["sources"]}:
                dropped.append({"process": key, "company": company["company"], "url": company["url"],
                                "why": "not a site the search returned"})
                continue
            maker = makers.setdefault(_domain(company["url"]), company | {"found_for": [], "retrieved": record["retrieved"]})
            maker["found_for"].append(key)
    for site, m in makers.items():
        families = _families(m["materials"])
        out.append(Observation(f"maker:{site}", f"maker:{site}", "maker", m["company"], Source(doc=m["url"]), Method.WEB,
                               parsed={"url": m["url"], "city": m["city"], "processes": sorted(set(m["found_for"])),
                                       "stated_processes": m["processes"], "stated_materials": m["materials"],
                                       "families": families, "max_size_mm": m["max_size_mm"] or None,
                                       "tolerance_mm": m["tolerance_mm"] or None, "retrieved": m["retrieved"]}))
    evidence.write_jsonl(SNAPSHOT, out)
    (CACHE / "dropped.json").write_text(json.dumps(dropped, indent=1, ensure_ascii=False))
    return {"identified": sum(o.field == "manufacturer_part" and bool(o.value) for o in out),
            "suggestions": sum(o.field == "suggested_supplier" for o in out), "makers": len(makers), "dropped": len(dropped)}


def bought_parts(observations: list[Observation]) -> list[dict]:
    """Bought parts worth a second source: something to search for, and a unit cost of at least DKK 200."""
    rows: dict[int, dict] = {}
    for o in observations:
        if o.source.doc == "BOM":
            rows.setdefault(o.source.row, {})[o.field] = o
    out = []
    for row, cells in sorted(rows.items()):
        text = {f: c.value.strip() for f, c in cells.items()}
        if worth_searching(text.get("type", ""), text.get("product_name") or text.get("supplier_order"),
                           (cells["unit_cost"].parsed or {}).get("dkk") if "unit_cost" in cells else None):
            out.append({"row": row, "name": text["name"], "supplier": text.get("supplier", ""),
                        "product": text.get("product_name", ""), "order": text.get("supplier_order", ""),
                        "link": text.get("link", "").split(" ")[0]})
    return out


def worth_searching(kind: str, identifier: str | None, unit_cost: float | None) -> bool:
    return kind == "Standard" and bool(identifier) and (unit_cost or 0) >= MIN_COST_DKK


# --- custom parts, worked out when asked -----------------------------------------------------------

def profile(kb, row: int) -> dict:
    """What making this part takes, each requirement with the evidence it rests on."""
    drawings = kb.drawings_of_row.get(row, [])
    cites, texts, families = [], [], set()
    for field in ("name", "notes", "design_intent", "material"):
        if cell := kb.cell(row, field):
            texts.append(cell.value)
            # The material column, or a name like "Silicone gasket"; notes mention other parts' materials too.
            found = (cell.parsed or {}).get("families", []) if field == "material" else \
                (materials.read(cell.value) or {}).get("families", []) if field == "name" else []
            if found:
                families |= set(found)
                cites.append(cell.id)
    for d in drawings:
        for field in ("material", "note"):
            reading = kb.field(d, 1, field)
            if reading["value"] and reading["status"] != "disputed":
                texts.append(reading["value"])
                if read := materials.read(reading["value"]):
                    families |= set(read["families"])
                    cites.append(reading["cite"])

    size = thickness = None
    for d in drawings:
        if model := kb.model_record(d):
            outer = [x for x in model["dimensions"] if x["how"] != "as drawn" and not re.search(r"spacing|radius|hole|from", x["name"])]
            if outer:
                big = max(outer, key=lambda x: x["value"])
                box = " × ".join(f"{v:g}" for v in model["extent"])
                size = {"mm": max(model["extent"]), "how": f"{box} mm, the bounding box of the {d} reconstruction", "cite": big["cite"]}
            if t := next((x for x in model["dimensions"] if x["name"] == "thickness"), None):
                thickness = {"mm": t["value"], "cite": t["cite"]}
            break
    if size is None:
        read = [(max(v for k in ("value", "diameter") if isinstance(v := (o.parsed or {}).get(k), (int, float))), o)
                for d in drawings for o in kb.current(d)
                if o.field == "callout" and o.method in (Method.PDF_TEXT, Method.VISION)
                and any(isinstance((o.parsed or {}).get(k), (int, float)) for k in ("value", "diameter"))]
        if read:
            mm, o = max(read, key=lambda x: x[0])
            size = {"mm": mm, "how": f"the largest dimension printed on {o.subject}", "cite": o.id}

    tightest = None
    for d in drawings:
        for o in kb.current(d):
            p = o.parsed or {}
            if o.field != "callout" or p.get("fit_check") or o.method == Method.OCR:
                continue
            for holder in (p, p.get("counterbore") or {}):
                tol = holder.get("tolerance") or {}
                if isinstance(tol.get("upper"), (int, float)) and isinstance(tol.get("lower"), (int, float)):
                    band = round((tol["upper"] - tol["lower"]) * 1000)
                    if band > 0 and (tightest is None or band < tightest["band_um"]):
                        tightest = {"band_um": band, "fit": holder.get("fit", ""), "text": o.value, "cite": o.id}

    amount = kb.cell(row, "amount")
    processes = _processes(families, " ".join(texts).casefold(), thickness)
    return {"row": row, "name": kb.cell(row, "name").value, "drawings": drawings,
            "materials": sorted(families), "material_cites": cites, "processes": processes,
            "thickness": thickness, "size": size, "tightest": tightest,
            "quantity": {"count": (amount.parsed or {}).get("count"), "cite": amount.id} if amount else None}


def makers_for(kb, prof: dict, limit: int = 4) -> list[dict]:
    """Makers found for a process this part needs, checked requirement by requirement against what they state."""
    needed = [p["process"] for p in prof["processes"]]
    out = []
    for o in kb.current_observations():
        if o.field != "maker":
            continue
        m = o.parsed
        shared = [p for p in needed if p in m["processes"]]
        if not shared:
            continue
        checks = [{"requirement": "Process", "result": "pass", "detail": f"found by a search for {', '.join(PROCESSES[p] for p in shared)}"}]
        if prof["materials"]:
            if not m["stated_materials"]:
                checks.append({"requirement": "Material", "result": "unknown", "detail": "its site lists no materials"})
            elif set(m["families"]) & set(prof["materials"]):
                checks.append({"requirement": "Material", "result": "pass", "detail": f"lists {', '.join(m['stated_materials'])}"})
            else:
                continue  # it lists its materials, and this part's is not one of them
        if prof["size"]:
            need = prof["size"]["mm"]
            if m["max_size_mm"]:
                if m["max_size_mm"] < need:
                    continue
                checks.append({"requirement": "Size", "result": "pass", "detail": f"up to {m['max_size_mm']:g} mm; the part is {need:g} mm"})
            else:
                checks.append({"requirement": "Size", "result": "unknown", "detail": "no largest size stated"})
        if prof["tightest"]:
            need = prof["tightest"]["band_um"] / 2000  # half the band either side, in mm
            what = prof["tightest"]["fit"] or "tightest"
            if m["tolerance_mm"]:
                ok = m["tolerance_mm"] <= need
                checks.append({"requirement": "Tolerance", "result": "pass" if ok else "fail",
                               "detail": f"states ±{m['tolerance_mm']:g} mm; the {what} tolerance is ±{need:.3f} mm"})
            else:
                checks.append({"requirement": "Tolerance", "result": "unknown", "detail": f"no tolerance stated; the {what} tolerance is ±{need:.3f} mm"})
        score = sum(c["result"] == "pass" for c in checks) - 2 * sum(c["result"] == "fail" for c in checks)
        out.append({"name": o.value, "url": m["url"], "city": m["city"], "checks": checks, "score": score,
                    "retrieved": m["retrieved"], "cite": o.id})
    return sorted(out, key=lambda x: (-x["score"], x["name"]))[:limit]


def precedent(kb, prof: dict) -> list[dict]:
    """Who made other custom parts of the same material for this machine, from the BOM's supplier column."""
    by: dict[str, list[int]] = {}
    for r in kb.bom_rows:
        kind, supplier = kb.cell(r, "type"), kb.cell(r, "supplier")
        if r == prof["row"] or not kind or kind.value != "Custom" or not supplier or not supplier.value.strip():
            continue
        material = kb.cell(r, "material")
        if not prof["materials"] or set((material.parsed or {}).get("families", []) if material else []) & set(prof["materials"]):
            by.setdefault(supplier.value.strip(), []).append(r)
    return [{"supplier": name, "rows": rows, "cites": [f"BOM.{r}.supplier" for r in rows[:3]]}
            for name, rows in sorted(by.items(), key=lambda kv: -len(kv[1]))]


def _processes(families: set, text: str, thickness: dict | None) -> list[dict]:
    """Plain rules from the material, the wording and the thickness. Each says why, so a wrong one shows.
    With no material recorded anywhere, no process is assumed."""
    out = []
    soft = families & {"silicone", "elastomer", "paper", "ceramic"}
    if soft:
        out.append({"process": "waterjet", "why": f"cut from {' and '.join(sorted(soft))} sheet"})
    if "polymer" in families:
        out.append({"process": "polymer", "why": "a polymer part"})
    metal = families & {"aluminium", "stainless steel", "steel"}
    if metal:
        if thickness and thickness["mm"] <= 3:
            out.append({"process": "sheet", "why": f"{thickness['mm']:g} mm thick"})
        elif m := re.search(r"\b(bend|bent|bukke)\w*", text):  # not "sheet": material names say "Plate" and "Sheet"
            out.append({"process": "sheet", "why": f"described as “{m.group(0)}”"})
        if m := re.search(r"\b(weld|svejs)\w*", text):
            out.append({"process": "welding", "why": f"described as “{m.group(0)}”"})
        if m := re.search(r"\b(shaft|aksel|axle|rod|bushing|pin|tube|rør)s?\b", text):
            out.append({"process": "turning", "why": f"described as a {m.group(0)}"})
        if not any(p["process"] == "sheet" for p in out):
            out.append({"process": "milling", "why": f"a machined {' or '.join(sorted(metal))} part"})
    return out


# --- helpers -----------------------------------------------------------------------------------------

def _part_query(part: dict) -> str:
    return (f"Part: {part['name']}. Recorded supplier: {part['supplier']}. Their product name or order number: "
            f"{part['product'] or part['order']}. Recorded link: {part['link'] or 'none'}.")


def _key(instructions: str, query: str, schema: dict) -> str:
    text = "\0".join([config.MODEL, instructions, query, json.dumps(schema, sort_keys=True)])
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def _cached(instructions: str, query: str, schema: dict) -> dict | None:
    path = CACHE / f"{_key(instructions, query, schema)}.json"
    return json.loads(path.read_text()) if path.exists() else None


def _domain(url: str) -> str:
    host = urlsplit(url if "//" in url else f"//{url}").netloc.casefold()
    return host.removeprefix("www.")


def _plain(value):
    """Search results carry inline citations, "([site](url?utm_source=openai))"; the sources are kept separately."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)", "", value)
        return re.sub(r"[?&]utm_source=openai$", "", value).strip()
    return value


def _part_number(text: str) -> tuple[str | None, str]:
    """"SC501MF (likely 1.5 kW model)" is a number and a remark; "Unknown — ..." and "Not stated" are neither."""
    m = re.fullmatch(r"\s*([A-Za-z0-9][\w./-]*\d[\w./-]*)\s*(?:\((.*)\))?\s*", text)
    return (m.group(1), m.group(2) or "") if m else (None, text)


def _families(stated: list[str]) -> list[str]:
    """A maker's materials as families; "metals" covers the metals, "plastics" the polymers."""
    text = " ".join(stated)
    out = set((materials.read(text) or {}).get("families", []))
    if re.search(r"\bmetal|any material", text, re.I):
        out |= {"aluminium", "steel", "stainless steel"}
    if re.search(r"plastic|polymer|nylon|resin|any material|\b(pom|peek|pla|petg|abs|asa|tpu|pa ?12)\b", text, re.I):
        out.add("polymer")
    return sorted(out)


def _mentions(url: str, part_number: str) -> bool:
    squash = lambda s: re.sub(r"[^a-z0-9]", "", s.casefold())
    return len(squash(part_number)) >= 4 and squash(part_number) in squash(url)


def costs() -> dict:
    records = [json.loads(p.read_text()) for p in CACHE.glob("*.json") if p.name != "dropped.json"]
    return {"responses": len(records), "web_searches": sum(r["searches"] for r in records),
            "input_tokens": sum(r["usage"]["input_tokens"] for r in records),
            "output_tokens": sum(r["usage"]["output_tokens"] for r in records)}
