"""Paths and settings. Everything the app reads or writes is located from here."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATASET = ROOT / "dataset"
DRAWINGS = DATASET / "drawings"
BOM_CSV = DATASET / "context" / "openlpbf-bom.csv"
DIAGRAMS = DATASET / "context" / "diagrams"
MANIFEST = DATASET / "manifest.json"

CURATION = ROOT / "curation"  # human decisions the build consumes
KB = ROOT / "kb"              # build output, committed so the app runs without rebuilding
# Runtime state, never committed. MERIDIAN_VAR points it elsewhere for a throwaway demo.
VAR = Path(os.environ.get("MERIDIAN_VAR", ROOT / "var"))

# The BOM is a snapshot of the upstream Airtable export at this commit.
SOURCE_REVISION = "98f76dad7b11d6f8fc7d59945d7fcf689df87ee7"
SNAPSHOT_RETRIEVED = "2026-09-02"


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

MODEL = os.environ.get("MERIDIAN_MODEL", "gpt-6-luna")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or None
