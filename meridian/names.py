"""How parts are named across the sources, and how a name is matched.

A sheet may be titled in Danish ("Cylinder Spænd Ring"), carry its name only in
the note box ("Z-axis MotorPlate"), or have a placeholder title ("Description").
The BOM names the same part in English ("Build cylinder clamp ring"). Matching
works on words after translation; it does not guess synonyms.
"""

import re

# Translation only. Deciding that a canister is a hopper is a judgement and
# belongs in curation, not in a word list.
GLOSSARY = {
    "bygge": "build", "plade": "plate", "spænd": "clamp", "bund": "bottom",
    "montage": "mount", "klods": "block", "silikone": "silicone", "pakning": "gasket",
    "varmeelement": "heating element", "justeringsplade": "adjustment plate",
    "føring": "guide", "linæer": "linear", "lineær": "linear", "rustfri": "stainless",
}
# Standard abbreviations in BOM names, spelled out so "power supply" finds "24VDC PSU 20A". Only names
# are expanded, for search; what a part is stays as the BOM writes it.
ABBREVIATIONS = {
    "psu": "power supply", "vfd": "variable frequency drive inverter", "plc": "programmable logic controller",
    "pid": "temperature controller", "estop": "emergency stop", "solidstate": "solid state", "ssr": "solid state relay",
}

_IGNORED = {"the", "of", "for", "to", "and", "with", "til", "af", "x2", "v2", "v6", "loop2", "version2",
            "alu", "description", "what", "which", "is", "are", "made", "show", "me", "part", "drawing", "about"}


def spelled_out(text: str) -> str:
    """The text followed by what its abbreviations stand for; "24 V" and "24VDC" both become "24v"."""
    found = [ABBREVIATIONS[w] for w in re.findall(r"[a-z]+", text.lower()) if w in ABBREVIATIONS]
    volts = [f"{v}v" for v in re.findall(r"\b(\d+)\s*v(?:dc|ac)?\b", text, re.I)]
    return " ".join([text, *found, *volts])


def words(text: str) -> set[str]:
    """"CylinderSpændRing" -> {"cylinder", "clamp", "ring"}."""
    spaced = re.sub(r"(?<=[a-zæøå])(?=[A-Z])", " ", text)
    out = []
    for w in re.split(r"[^A-Za-zÆØÅæøå0-9]+", spaced.lower()):
        out += GLOSSARY.get(w, w).split()
    return {w.removesuffix("s") if len(w) > 3 and not w.endswith("ss") else w
            for w in out if len(w) > 1 and w not in _IGNORED and not w.isdigit()}
