"""The tools the chat model can call. Each is a thin, typed door onto KnowledgeBase.

Descriptions are written for the model and say what comes back, so it picks
the narrow tool instead of pulling everything about a part every time.
"""

from collections.abc import Callable

from meridian import corrections
from meridian.knowledge import KnowledgeBase


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        "strict": True,
    }


_REF = {"type": "string", "description": 'A drawing id like "D-011" or a BOM row like "BOM.30", as returned by find_parts.'}

DEFINITIONS = [
    _tool("find_parts",
          "Find drawings and BOM rows by name, drawing id (D-011) or row number (row 30). Returns candidates with the "
          "words that matched, the drawing's subsystem and its linked BOM rows. Use this first when a part is named in words.",
          {"query": {"type": "string"}}, ["query"]),
    _tool("get_part",
          "Everything known about one part: the drawing's title block per sheet with reading status, its callouts "
          "(dimensions, holes, fits), the linked BOM rows with every cell, sheet-versus-BOM comparisons for material, "
          "quantity and datasheet, and its relations. Every value carries a cite id.",
          {"ref": _REF}, ["ref"]),
    _tool("get_interfaces",
          "What a part connects to: BOM 'Interface with' entries (kind stated), relations read off the system diagrams "
          "(kind diagram), and mating fits found across two sheets (kind inferred).",
          {"ref": _REF}, ["ref"]),
    _tool("list_subsystem",
          "Drawings and BOM rows in one subsystem: Box, Powder, Recoater, Optical, Gas Flow or Z-axis (BOM families "
          "Electric, SensorGantry, Support and Raw Materials have rows but no drawings).",
          {"name": {"type": "string"}}, ["name"]),
    _tool("parts_with_material",
          "Drawings and BOM rows naming a material family (aluminium, stainless steel, steel, silicone, ceramic, "
          "polymer, elastomer, paper), with what each source literally says.",
          {"material": {"type": "string"}}, ["material"]),
    _tool("procurement",
          "Recorded supplier, order number, product name, link, amount and DKK cost for the given parts or a whole "
          "subsystem, with the recorded total and the rows whose cost was never recorded. Pass refs, or a subsystem, "
          "not both.",
          {"refs": {"type": ["array", "null"], "items": {"type": "string"}},
           "subsystem": {"type": ["string", "null"]}},
          ["refs", "subsystem"]),
    _tool("search_text",
          "Find a word or phrase in drawing notes, callout text, BOM notes and design intent, e.g. 'weld', 'o-ring', "
          "'too tight'. Case-insensitive substring match.",
          {"text": {"type": "string"}}, ["text"]),
    _tool("propose_correction",
          "File a correction for review when the user says a value in the knowledge base is wrong. target is the cite id "
          "of the one observation being corrected; proposed_value is its complete corrected text, written the way the "
          "source prints it; reason is the user's reason. Nothing changes until a person accepts it in review. Returns "
          "the correction id, the automatic checks and what accepting would change.",
          {"target": {"type": "string"}, "proposed_value": {"type": "string"}, "reason": {"type": "string"}},
          ["target", "proposed_value", "reason"]),
]


def handlers(kb: KnowledgeBase, turn: dict) -> dict[str, Callable[..., object]]:
    """`turn` carries the current question, which is filed with any correction it leads to."""
    return {
        "find_parts": lambda query: kb.find(query),
        "get_part": lambda ref: _or_unknown(kb, ref, kb.part),
        "get_interfaces": lambda ref: _or_unknown(kb, ref, lambda r: {"attention": kb.attention(r), "relations": kb.interfaces(r)}),
        "list_subsystem": lambda name: kb.subsystem(name),
        "parts_with_material": lambda material: kb.with_material(material),
        "procurement": lambda refs, subsystem: kb.procurement(refs=refs, subsystem=subsystem),
        "search_text": lambda text: kb.search(text),
        "propose_correction": lambda target, proposed_value, reason: _propose(kb, turn, target, proposed_value, reason),
    }


def _propose(kb: KnowledgeBase, turn: dict, target: str, value: str, reason: str) -> dict:
    c = corrections.propose(kb, target, value, reason, turn.get("question", ""))
    return {"correction": c.id, "status": "waiting for review", "review_page": "/review", "target": c.target,
            "current_value": c.current_value, "proposed_value": c.proposed_value, "checks": c.checks, "impact": c.impact}


def _or_unknown(kb: KnowledgeBase, ref: str, call: Callable[[str], object]) -> object:
    known = ref in kb.sheets or (ref.startswith("BOM.") and ref[4:].isdigit() and int(ref[4:]) in kb.bom_rows)
    return call(ref) if known else {"error": f'No part "{ref}". Use find_parts to get a valid ref.'}
