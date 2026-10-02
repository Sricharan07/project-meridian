"""Map the many ways a material is written onto a few families that can be compared.

The sheets name alloys ("7075-T6, Plate (SS)", "3.3315 (EN-AW 5005)"), notes use
plain words in English or Danish ("Alu.", "rustfri"), and the BOM uses broad
classes ("Aluminium", "Stainless steel,Steel"). Comparing them needs a common
family; the original text is always kept next to it.

"(SS)" is a suffix from the SolidWorks material library. It appears on
"7075-T6, Plate (SS)" (an aluminium) and on "AISI 316 Stainless Steel Sheet
(SS)" in this corpus, so it cannot mean stainless, and it is dropped before
matching.
"""

import re

_LIBRARY_TAG = re.compile(r"\((?:SS|SN)\)")

# Order matters: each match is removed before the next pattern runs, so
# "stainless steel" is never also counted as "steel".
_FAMILIES: list[tuple[str, re.Pattern]] = [
    ("stainless steel", re.compile(r"non-magnetic stainless|stainless(?: steel)?|rustfri|\baisi\s*3\d\dL?\b", re.I)),
    ("aluminium", re.compile(r"alumin[iu]+m|\balu\b\.?|\ben[\s-]?aw[\s-]?\d{4}|\baw-\d{4}|\b(?:5005|6061|6063|6082|7075)(?:-T\d)?\b|3\.3315", re.I)),
    ("ceramic", re.compile(r"ceramic(?: paper)?|keramisk", re.I)),
    ("silicone", re.compile(r"silicon(?:e)?(?: rubber)?|silikone", re.I)),
    ("steel", re.compile(r"\bsteel\b|\bstål\b", re.I)),
    ("elastomer", re.compile(r"elastomer|rubber", re.I)),
    ("polymer", re.compile(r"polymer", re.I)),
    ("paper", re.compile(r"\bpaper\b", re.I)),
]

# "x000" is a series ("AW-6000 serie"), not a grade, so it is not captured.
_GRADE = re.compile(r"\b(?:EN[\s-]?AW[\s-]?\d0(?!00)\d\d|[5-7]0(?!00)\d\d(?:-T\d)?|AISI\s*3\d\dL?|3\.3315)\b", re.I)


def read(text: str) -> dict | None:
    """Families and specific grades named in `text`, or None if it names no material."""
    rest = _LIBRARY_TAG.sub(" ", text)
    grades = sorted({_canonical_grade(g) for g in _GRADE.findall(rest)})
    families = []
    for family, pattern in _FAMILIES:
        if pattern.search(rest):
            families.append(family)
            rest = pattern.sub(" ", rest)
    if not families:
        return None
    out: dict = {"families": families}
    if grades:
        out["grades"] = grades
    if _LIBRARY_TAG.search(text):
        out["ignored"] = "SolidWorks library suffix"
    return out


def _canonical_grade(grade: str) -> str:
    """"3.3315", "EN-AW 5005" and "5005" are the same alloy; write them one way."""
    g = re.sub(r"\s+", " ", grade.upper())
    if g == "3.3315":  # Werkstoff number for AlMg1
        return "EN AW-5005"
    if m := re.match(r"(?:EN[\s-]?AW[\s-]?)?([5-7]0\d\d)(-T\d)?$", g):
        return f"EN AW-{m.group(1)}{m.group(2) or ''}"
    return g.replace("AISI", "AISI ").replace("  ", " ")
