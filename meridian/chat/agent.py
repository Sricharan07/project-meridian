"""One chat turn: the model looks things up, writes an answer, the answer is checked.

The model never sees a drawing or the BOM directly, only tool results. Which
sheet opens beside the answer is decided here from what the answer cites,
rather than left to the model to remember. An answer that fails the check gets
one rewrite; if it still fails it is shown with the problems listed, not
hidden and not silently trusted.
"""

import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path

from openai import OpenAI

from meridian import config
from meridian.chat import verify
from meridian.chat.tools import DEFINITIONS, handlers
from meridian.knowledge import KnowledgeBase

INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text()
MAX_ROUNDS = 6

# USD per million tokens, input and output. Used to report what each answer cost.
PRICES = {"gpt-6-luna": (0.10, 0.50)}


@dataclass
class Turn:
    answer: str
    citations: dict[str, dict] = field(default_factory=dict)
    attachments: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    check: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    seconds: float = 0.0
    model: str = config.MODEL
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class Chat:
    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self.turn: dict = {}
        self.tools = handlers(kb, self.turn)
        self.client = OpenAI(api_key=config.OPENAI_API_KEY) if config.OPENAI_API_KEY else None

    def ask(self, question: str, history: list[dict] = ()) -> Turn:
        if self.client is None:
            return self.offline(question)
        self.turn["question"] = question
        started = time.monotonic()
        items: list = [*({"role": m["role"], "content": m["content"]} for m in history), {"role": "user", "content": question}]
        steps, outputs, usage = [], [], Counter()

        for round_ in range(MAX_ROUNDS):
            response = self._respond(items, usage, final=round_ == MAX_ROUNDS - 1)
            calls = [i for i in response.output if i.type == "function_call"]
            if not calls:
                break
            items += response.output
            for call in calls:
                began = time.monotonic()
                arguments = json.loads(call.arguments)
                result = self._run(call.name, arguments)
                outputs.append(result)
                steps.append({"tool": call.name, "arguments": arguments, "ms": round(1000 * (time.monotonic() - began))})
                items.append({"type": "function_call_output", "call_id": call.call_id,
                              "output": json.dumps(result, ensure_ascii=False)})

        answer = response.output_text.strip()
        verdict = verify.check(answer, question, outputs, set(self.kb.obs))
        rewritten = False
        if not verdict.ok:
            items += response.output
            items.append({"role": "developer", "content": verdict.feedback()})
            response = self._respond(items, usage, final=True)
            answer, rewritten = response.output_text.strip(), True
            verdict = verify.check(answer, question, outputs, set(self.kb.obs))

        return Turn(
            answer=answer,
            citations=self._citations(answer),
            attachments=self._attachments(answer, steps),
            steps=steps,
            check={"ok": verdict.ok, "rewritten": rewritten,
                   "unknown_citations": verdict.unknown_citations, "untraced_numbers": verdict.untraced_numbers},
            usage=self._usage(usage),
            seconds=round(time.monotonic() - started, 2),
        )

    def _respond(self, items: list, usage: Counter, final: bool):
        response = self.client.responses.create(
            model=config.MODEL,
            instructions=INSTRUCTIONS,
            input=items,
            tools=DEFINITIONS,
            tool_choice="none" if final else "auto",
            reasoning={"effort": "medium"},  # "low" occasionally skipped citations; medium costs ~0.1 cent and no extra latency
            store=False,
            include=["reasoning.encrypted_content"],  # lets reasoning carry across rounds without storing the chat at OpenAI
        )
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        usage["calls"] += 1
        return response

    def _run(self, name: str, arguments: dict) -> object:
        try:
            return self.tools[name](**arguments)
        except Exception as error:  # a broken tool call is reported to the model, not to the user as a crash
            return {"error": f"{name} failed: {error}"}

    def _usage(self, usage: Counter) -> dict:
        price_in, price_out = PRICES.get(config.MODEL, (0.0, 0.0))
        cost = usage["input_tokens"] * price_in / 1e6 + usage["output_tokens"] * price_out / 1e6
        return dict(usage) | {"usd": round(cost, 5)}

    # --- what the answer points at ----------------------------------------------

    def _citations(self, answer: str) -> dict[str, dict]:
        return {i: e for i in dict.fromkeys(verify.cited_ids(answer)) if (e := self.kb.evidence(i))}

    def _attachments(self, answer: str, steps: list[dict]) -> list[dict]:
        """Drawings the answer cites, in citation order, then drawings it looked at; BOM rows it cites."""
        highlights: dict[str, list[dict]] = {}
        rows: dict[int, list[str]] = {}
        for cite in verify.cited_ids(answer):
            o = self.kb.obs.get(cite)
            if o is None:
                continue
            if o.subject.startswith("D-"):
                highlights.setdefault(o.subject, [])
                if o.source.bbox:
                    highlights[o.subject].append({"cite": cite, "sheet": o.source.page, "bbox": o.source.bbox})
            elif o.source.doc == "BOM":
                rows.setdefault(o.source.row, []).append(cite)
                for drawing in self.kb.drawings_of_row.get(o.source.row, []):
                    highlights.setdefault(drawing, [])
        for step in steps:
            # A part the model looked up is a part the answer is about, even if it only cited a diagram label.
            refs = [step["arguments"]["ref"]] if step["tool"] in ("get_part", "get_interfaces") else \
                step["arguments"].get("refs") or [] if step["tool"] == "procurement" else []
            for ref in refs:
                if ref.startswith("D-") and ref in self.kb.sheets:
                    highlights.setdefault(ref, [])
                elif ref.startswith("BOM.") and ref[4:].isdigit():
                    for drawing in self.kb.drawings_of_row.get(int(ref[4:]), [])[:1]:
                        highlights.setdefault(drawing, [])

        out = [{"type": "drawing", "ref": d, "name": self.kb.drawing_name(d),
                "sheet": marks[0]["sheet"] if marks else 1, "highlights": marks, "model_3d": self.kb.model_3d(d)}
               for d, marks in highlights.items()]
        out += [{"type": "bom_row", "row": row, "name": self.kb.name(f"BOM.{row}"), "cites": cites} for row, cites in rows.items()]
        # An answer about suppliers opens the part on its Suppliers tab.
        for step in steps:
            ref = step["arguments"].get("ref", "")
            known = ref in self.kb.sheets or (ref.startswith("BOM.") and ref[4:].isdigit() and int(ref[4:]) in self.kb.bom_rows)
            if step["tool"] == "suggest_suppliers" and known:
                out.insert(0, {"type": "suppliers", "ref": ref, "name": self.kb.name(ref)})
                break
        # An answer about how parts connect can be followed in the graph, focused where it started.
        for step in steps:
            args = step["arguments"]
            if step["tool"] == "connection_path" and args.get("a") in self.kb.graph.nodes and args.get("b") in self.kb.graph.nodes:
                out.append({"type": "graph", "focus": args["a"], "to": args["b"]})
                break
            if step["tool"] == "get_interfaces" and args.get("ref") in self.kb.graph.nodes:
                out.append({"type": "graph", "focus": args["ref"]})
                break
            if step["tool"] == "subsystem_links":
                out.append({"type": "graph", "focus": None})
                break
        return out

    # --- without an API key -------------------------------------------------------

    def offline(self, question: str) -> Turn:
        """No model available: replay the recorded answer if this question was in the evaluation run,
        otherwise look the part up and show what the evidence says, without prose."""
        if recorded := _recordings().get(question_key(question)):
            turn = Turn(**{k: v for k, v in recorded.items() if k in Turn.__dataclass_fields__})
            turn.model, turn.note = "recorded", f"Recorded in the evaluation run of {recorded['recorded_at']}; no API key is configured."
            return turn
        hits = self.kb.find(question)
        if not hits:
            return Turn(answer="No API key is configured, so I can only look parts up by name, and nothing matched. "
                               "Try a part name or a drawing id such as D-011.", model="offline")
        part = self.kb.part(hits[0]["ref"])
        lines = [f"No API key is configured, so this is the evidence for {part['name']} without a written answer."]
        drawing = part.get("drawing")
        if drawing:
            block = drawing["sheets"][0]["title_block"]
            for f in ("material", "weight"):
                if block[f]["value"]:
                    lines.append(f"- Drawing {f}: {block[f]['value']} ({block[f]['status']}) [{block[f]['cite']}]")
        for row in part.get("bom", []):
            cells = row["cells"]
            if "material" in cells:
                lines.append(f"- BOM row {row['row']} material: {cells['material']['value']} [{cells['material']['cite']}]")
        for c in part.get("comparisons", []):
            lines.append(f"- {c['field'].capitalize()}: {c['verdict']}")
        answer = "\n".join(lines)
        return Turn(answer=answer, citations=self._citations(answer),
                    attachments=self._attachments(answer, [{"tool": "get_part", "arguments": {"ref": part["ref"]}}]),
                    model="offline")


@cache
def _recordings() -> dict[str, dict]:
    path = config.ROOT / "eval" / "transcripts.json"
    return json.loads(path.read_text()) if path.exists() else {}


def question_key(question: str) -> str:
    return re.sub(r"\W+", " ", question.casefold()).strip()
