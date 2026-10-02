"""The supplied drawings, as described by dataset/manifest.json.

The manifest is the provenance record, so the build refuses to run if a file no
longer matches its recorded hash. Degraded scans keep their upstream path for
attribution only; the pristine originals are deliberately not fetched.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from meridian import config


@dataclass(frozen=True, slots=True)
class Drawing:
    id: str               # "D-011"
    path: Path
    subsystem: str        # as the manifest names it: "Box", "Z-axis", ...
    pages: int
    upstream_path: str    # "CAD/Technical Drawings/Recoater/RecoaterArm.PDF"
    degraded: bool        # rasterised scan-like derivative, no text layer
    degradation: str      # "faded-scan-v1", ... or "" for clean sheets

    @property
    def upstream_name(self) -> str:
        """The upstream file stem, e.g. "RecoaterArm". Often the most specific name a sheet has."""
        return Path(self.upstream_path).stem

    @property
    def upstream_words(self) -> list[str]:
        """"Z-axis_MotorPlate" -> ["z", "axis", "motor", "plate"]."""
        spaced = re.sub(r"(?<=[a-zæøå])(?=[A-Z])", " ", self.upstream_name)
        return [w.lower() for w in re.split(r"[\s_\-]+", spaced) if w]


@cache
def drawings() -> dict[str, Drawing]:
    manifest = json.loads(config.MANIFEST.read_text())
    out = {}
    for asset in manifest["assets"]:
        if not asset["id"].startswith("D-"):
            continue
        path = config.ROOT / asset["path"]
        _verify(path, asset["sha256"])
        out[asset["id"]] = Drawing(
            id=asset["id"],
            path=path,
            subsystem=asset["subsystem"],
            pages=asset["pages"],
            upstream_path=asset["source_path"],
            degraded=asset["distribution"] == "degraded-only",
            degradation=asset.get("derivation", {}).get("derivation_profile", ""),
        )
    return out


def _verify(path: Path, sha256: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != sha256:
        raise RuntimeError(f"{path.name} does not match the manifest hash; refusing to build from it")
