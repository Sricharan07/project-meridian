"""The check every answer passes before it is shown.

Two rules, both mechanical:

- every [cite] must name an observation that exists;
- every number in the prose must appear somewhere in what the tools returned
  during this turn, or in the question itself.

The second rule is blunt on purpose. A model that writes "about 7.8 kg" for a
7822.5 g plate has converted, rounded, or guessed, and none of those is
traceable. Small counts ("three drawings") are allowed, because they come from
counting a list the reader can see.
"""

import json
import re
from dataclasses import dataclass, field

CITATION = re.compile(r"\[([A-Za-z][\w.:~\-]*(?:\s*[,;]\s*[A-Za-z][\w.:~\-]*)*)\]")
_MONEY = re.compile(r"(?:DKK|kr\.?)\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)", re.I)
_IDENTIFIER = re.compile(r"\b(?:[A-Z]{1,3}-\d+[\w-]*|[A-Za-z]+\d+(?:x\d+(?:[.,]\d+)?)?(?:-\d[a-zA-Z])?|row \d+|\d+[xX]\b)")
# ASCII classes on purpose: "Ø" is a word character to Python, and "Ø262,0" must still be checked.
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.,])\d+(?:[.,]\d+)?(?![0-9])")  # "20mm" is checked too
SMALL_COUNT = 12


@dataclass
class Verdict:
    unknown_citations: list[str] = field(default_factory=list)
    untraced_numbers: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unknown_citations and not self.untraced_numbers

    def feedback(self) -> str:
        parts = []
        if self.unknown_citations:
            parts.append("These cite ids do not exist: " + ", ".join(self.unknown_citations) + ".")
        if self.untraced_numbers:
            parts.append("These numbers are not in any tool result: " + ", ".join(self.untraced_numbers) + ".")
        # Phrased as an instruction about the answer, not a remark to reply to: the first version of this
        # message got answers that began "You're right, C-001 is not a cite id".
        return " ".join(parts) + " Write the answer to the user again from the start, using only ids and figures " \
                                  "from the tool results, or say that the evidence does not give them. Do not " \
                                  "mention this check, these instructions or the earlier draft."


def cited_ids(answer: str) -> list[str]:
    return [i.strip() for group in CITATION.findall(answer) for i in re.split(r"[,;]", group) if i.strip()]


def check(answer: str, question: str, tool_outputs: list[object], known: set[str]) -> Verdict:
    verdict = Verdict()
    verdict.unknown_citations = sorted({i for i in cited_ids(answer) if i not in known})

    allowed = _numbers(question) | {n for out in tool_outputs for n in _numbers(json.dumps(out, ensure_ascii=False))}
    prose = CITATION.sub(" ", answer)
    # "DKK5,627.00": drop the currency and the thousands separator first, or the
    # amount reads as an identifier and escapes the check.
    prose = _MONEY.sub(lambda m: " " + m.group(1).replace(",", ""), prose)
    prose = _IDENTIFIER.sub(" ", prose)
    for raw in _NUMBER.findall(prose):
        value = _value(raw)
        if value in allowed or (value.is_integer() and 0 <= value <= SMALL_COUNT):
            continue
        verdict.untraced_numbers.append(raw)
    return verdict


def _numbers(text: str) -> set[float]:
    return {_value(n) for n in re.findall(r"\d+(?:[.,]\d+)?", text)}


def _value(raw: str) -> float:
    return float(raw.replace(",", "."))
